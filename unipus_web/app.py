"""FastAPI 应用：REST + WebSocket + 静态前端。"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .api.client import UnipusClient
from .api.errors import ApiError, AuthError, NetworkError, UnipusError
from .config import VERSION
from .core.manager import TaskManager
from .core.reporter import build_report
from .credentials import CredentialStore
from .events import EventBus
from .logging_setup import LogStore, setup_logging
from .network_log import NetworkRecorder, redact_record

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _hostname(host_header: str | None) -> str:
    if not host_header:
        return ""
    return (urlsplit("//" + host_header).hostname or "").lower()


class CreateTaskRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    credential_id: str | None = None


class ChooseCourseRequest(BaseModel):
    course_id: int
    resource_id: int


class CredentialRequest(BaseModel):
    username: str
    password: str
    label: str = ""


def create_app(
    *,
    allow_multi_question: bool = True,
    testing: bool = False,
    proxy: str | None = None,
) -> FastAPI:
    app = FastAPI(title="Unipus Helper", version=VERSION)

    log_store = LogStore()
    bus = EventBus()
    network = NetworkRecorder()
    credentials = CredentialStore()

    log_store.set_listener(lambda record: bus.publish("log.append", record))
    # 必须脱敏后再推送：原始记录包含登录密码、JWT、Cookie
    network.set_listener(
        lambda record: bus.publish("network.append", redact_record(record))
    )

    def client_factory(task_id: str) -> UnipusClient:
        return UnipusClient(task_id, record=network.add, proxy=proxy)

    manager = TaskManager(
        bus=bus,
        log_store=log_store,
        network=network,
        credentials=credentials,
        allow_multi_question=allow_multi_question,
        client_factory=client_factory,
    )

    setup_logging(log_store)

    app.state.manager = manager
    app.state.log_store = log_store
    app.state.network = network
    app.state.credentials = credentials
    app.state.bus = bus

    def host_allowed(host: str | None) -> bool:
        name = _hostname(host)
        if testing and name == "testserver":
            return True
        return name in _ALLOWED_HOSTS

    @app.middleware("http")
    async def host_guard(request: Request, call_next):
        if not host_allowed(request.headers.get("host")):
            return JSONResponse(
                {"error": {"code": "bad_host", "message": "仅允许本机访问"}},
                status_code=400,
            )
        return await call_next(request)

    # ------------------------------------------------------------ 前端

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    # ------------------------------------------------------------ 任务

    @app.get("/api/tasks")
    def list_tasks():
        return manager.snapshots()

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        task = manager.get(task_id)
        if task is None:
            raise HTTPException(404, "任务不存在")
        return task.snapshot()

    @app.post("/api/tasks", status_code=202)
    def create_task(payload: CreateTaskRequest):
        if not payload.credential_id and not payload.username:
            raise HTTPException(422, "需要 username 或 credential_id")
        try:
            return manager.create_task(
                payload.username,
                payload.password,
                credential_id=payload.credential_id,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def require_task(task_id: str):
        task = manager.get(task_id)
        if task is None:
            raise HTTPException(404, "任务不存在")
        return task

    @app.post("/api/tasks/{task_id}/start")
    def start_task(task_id: str):
        require_task(task_id)
        return {"ok": manager.start(task_id)}

    @app.post("/api/tasks/{task_id}/pause")
    def pause_task(task_id: str):
        require_task(task_id)
        return {"ok": manager.pause(task_id)}

    @app.post("/api/tasks/{task_id}/resume")
    def resume_task(task_id: str):
        require_task(task_id)
        return {"ok": manager.resume(task_id)}

    @app.post("/api/tasks/{task_id}/stop")
    def stop_task(task_id: str):
        require_task(task_id)
        return {"ok": manager.stop(task_id)}

    @app.post("/api/tasks/{task_id}/restart")
    def restart_task(task_id: str):
        require_task(task_id)
        return {"ok": manager.restart(task_id)}

    @app.delete("/api/tasks/{task_id}", status_code=204)
    def delete_task(task_id: str):
        if not manager.remove(task_id):
            raise HTTPException(404, "任务不存在")
        return Response(status_code=204)

    @app.get("/api/tasks/{task_id}/courses")
    def task_courses(task_id: str):
        task = require_task(task_id)
        if task.status.value == "INITIALIZING":
            raise HTTPException(409, "任务仍在登录中")
        return task.snapshot()["courses"]

    @app.post("/api/tasks/{task_id}/choose", status_code=204)
    def choose_course(task_id: str, payload: ChooseCourseRequest):
        require_task(task_id)
        try:
            manager.choose_course(task_id, payload.course_id, payload.resource_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return Response(status_code=204)

    # ------------------------------------------------------------ 凭据

    @app.get("/api/credentials")
    def list_credentials():
        return credentials.list()

    @app.post("/api/credentials", status_code=201)
    def add_credential(payload: CredentialRequest):
        if not payload.username:
            raise HTTPException(422, "用户名不能为空")
        return credentials.add(payload.username, payload.password, payload.label)

    @app.delete("/api/credentials/{cred_id}", status_code=204)
    def delete_credential(cred_id: str):
        if not credentials.delete(cred_id):
            raise HTTPException(404, "凭据不存在")
        return Response(status_code=204)

    # ------------------------------------------------------------ 调试

    @app.get("/api/logs")
    def get_logs(after: int = 0, limit: int = 1000, min_level: str | None = None):
        return log_store.query(after_seq=after, limit=limit, min_level=min_level)

    @app.get("/api/network")
    def get_network(after: int = 0, limit: int = 200):
        return [redact_record(record) for record in network.query(after, limit)]

    @app.post("/api/report")
    def report():
        data = build_report(manager)
        filename = f"unipus_report_{int(time.time() * 1000)}.zip"
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ------------------------------------------------------------ WebSocket

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        if not host_allowed(websocket.headers.get("host")):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        bus.bind_loop(asyncio.get_running_loop())
        queue = bus.subscribe()
        try:
            await websocket.send_json(
                {"type": "snapshot", "data": manager.snapshots(), "seq": 0}
            )
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        except RuntimeError:
            pass
        finally:
            bus.unsubscribe(queue)

    # ------------------------------------------------------------ 异常

    @app.exception_handler(AuthError)
    async def auth_error(_request: Request, exc: AuthError):
        return JSONResponse(
            {"error": {"code": "auth_error", "message": str(exc)}}, status_code=400
        )

    @app.exception_handler(NetworkError)
    async def network_error(_request: Request, exc: NetworkError):
        return JSONResponse(
            {"error": {"code": "network_error", "message": str(exc)}}, status_code=502
        )

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError):
        return JSONResponse(
            {"error": {"code": "api_error", "message": exc.message}}, status_code=502
        )

    @app.exception_handler(UnipusError)
    async def unipus_error(_request: Request, exc: UnipusError):
        return JSONResponse(
            {"error": {"code": "unipus_error", "message": str(exc)}}, status_code=400
        )

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception):
        logger.exception("Unhandled API error")
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "服务器内部错误"}},
            status_code=500,
        )

    return app
