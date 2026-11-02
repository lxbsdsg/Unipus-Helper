"""课程学习时长任务。"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

from websockets.sync.client import connect

from ..api.errors import NetworkError, UnipusError
from ..crypto import generate_auth_token
from .course_detail import CourseDetail


_DURATION_HOST = "ucontent.unipus.cn"
_SOCKET_PATH = "/unipusio"
_ACK_RE = re.compile(r"^43/userActivities,(?:(\d+),?)?(\[.*\])$")


@dataclass(frozen=True)
class DurationTarget:
    """一个可计时的课程叶子节点。"""
    group_id: str
    unit_id: str
    micro_id: str
    route_path: str
    name: str
    path: str

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "unit_id": self.unit_id,
            "micro_id": self.micro_id,
            "route_path": self.route_path,
            "name": self.name,
            "path": self.path,
        }


def build_duration_targets(course: CourseDetail) -> list[DurationTarget]:
    """从课程树提取计时目标。

    官方路由使用 unit / micro / group 三层标识。课程树中 unit 的第一个
    子层级对应 micro，叶子节点对应 group。
    """
    targets: list[DurationTarget] = []
    seen_groups: set[str] = set()

    def walk(node, ancestors: list[str], labels: list[str]) -> None:
        if not node.children:
            if not node.id or not ancestors:
                return
            route_ids = ancestors + [node.id]
            unit_id = route_ids[0]
            micro_id = route_ids[1] if len(route_ids) > 1 else unit_id
            # 官方路由会把页码段（例如 p_1）之前的内容作为题组 ID。
            group_id = (
                route_ids[-2]
                if len(route_ids) > 1 and re.fullmatch(r"p_\d+", node.id)
                else node.id
            )
            if not group_id or group_id in seen_groups:
                return
            seen_groups.add(group_id)
            targets.append(
                DurationTarget(
                    group_id=group_id,
                    unit_id=unit_id,
                    micro_id=micro_id,
                    route_path="/".join(route_ids),
                    name=node.name or group_id,
                    path=" / ".join((labels + [node.name or node.id])[-3:]),
                )
            )
            return
        for child in node.children:
            walk(child, ancestors + [node.id], labels + [node.name or node.id])

    for unit in course.units:
        for child in unit.children:
            walk(child, [unit.id], [unit.name or unit.id])

    return targets


class CourseDurationClient:
    """课程计时的 Engine.IO 3 / Socket.IO 1 同步客户端。"""

    socket_connect: Callable[..., object] = staticmethod(connect)

    def __init__(
        self, open_id: str, *, proxy: str | None = None, open_timeout: float = 10.0
    ) -> None:
        self.open_id = open_id
        self.proxy = proxy
        self.token = generate_auth_token(open_id)
        self.open_timeout = open_timeout
        self._socket = None
        self._reader: threading.Thread | None = None
        self._closed = False
        self._ack_lock = threading.Lock()
        self._ack_sequence = 0
        self._ack_events: dict[int, threading.Event] = {}
        self._ack_results: dict[int, dict | None] = {}
        self._error: Exception | None = None
        self._error_event = threading.Event()
        self._last_payload: dict | None = None

    @property
    def healthy(self) -> bool:
        """连接是否仍在读循环中且没有已记录的网络错误。"""

        return (
            self._socket is not None
            and not self._closed
            and self._error is None
            and self._reader is not None
            and self._reader.is_alive()
        )

    def connect(self) -> None:
        query = urlencode(
            {
                "EIO": "3",
                "transport": "websocket",
                "uuid": self.open_id,
                "token": self.token,
            }
        )
        url = f"wss://{_DURATION_HOST}{_SOCKET_PATH}/?{query}"
        try:
            self._socket = self.socket_connect(
                url,
                additional_headers={"User-Agent": "Unipus Helper/1.0"},
                open_timeout=self.open_timeout,
                close_timeout=2,
                proxy=self.proxy,
            )
            opening = self._recv_sync()
            if not isinstance(opening, str) or not opening.startswith("0"):
                raise NetworkError("计时服务返回了无效握手")
            self._send_sync("40/userActivities,")
            # 实际服务会先确认默认命名空间（40），再确认
            # /userActivities；握手期间也要响应 Engine.IO 心跳。
            while True:
                namespace = self._recv_sync()
                if namespace == "2":
                    self._send_sync("3")
                    continue
                if isinstance(namespace, str) and namespace.startswith(
                    "40/userActivities"
                ):
                    break
                if namespace == "40":
                    continue
                raise NetworkError("计时服务命名空间连接失败")
        except Exception as exc:
            self._close_socket()
            if isinstance(exc, NetworkError):
                raise
            raise NetworkError(f"计时服务连接失败：{exc}") from exc
        self._reader = threading.Thread(
            target=self._pump,
            name=f"duration-{self.open_id[:8]}",
            daemon=True,
        )
        self._reader.start()

    def start(self, target: DurationTarget, course_id: str, resource_id: int) -> None:
        payload = {
            "module": target.group_id,
            "moduleGroup": course_id,
            "client": "pc",
            "url": self._page_url(target, course_id, resource_id),
            "tag1": target.unit_id,
            "tag2": target.micro_id,
            "tag3": json.dumps(
                {
                    "microBlock": f"{target.unit_id}/{target.micro_id}",
                    "version": "1",
                    "source": "ucontent",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        self._last_payload = payload
        self.emit("start", payload)

    def stop(self) -> None:
        self.emit("stop", self._last_payload or {})

    def emit(self, event: str, payload: dict) -> dict:
        if self._socket is None or self._closed:
            raise NetworkError("计时连接已关闭")
        if self._error is not None:
            raise NetworkError(f"计时连接中断：{self._error}")
        with self._ack_lock:
            self._ack_sequence += 1
            ack_id = self._ack_sequence
            done = threading.Event()
            self._ack_events[ack_id] = done
            self._ack_results[ack_id] = None

        body = json.dumps(
            [event, {**payload, "timer": int(time.time() * 1000)}],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            self._send_sync(f"42/userActivities,{ack_id},{body}")
        except Exception as exc:
            self._fail(exc)
            raise NetworkError(f"计时请求发送失败：{exc}") from exc
        if not done.wait(self.open_timeout) and not self._error_event.is_set():
            self._fail(TimeoutError("等待计时服务回执超时"))
            raise NetworkError(f"计时连接中断：{self._error}")
        result = self._ack_results.get(ack_id)
        with self._ack_lock:
            self._ack_events.pop(ack_id, None)
            self._ack_results.pop(ack_id, None)
        if not isinstance(result, dict) or result.get("code") != 0:
            message = (
                result.get("msg") if isinstance(result, dict) else None
            ) or "计时服务拒绝请求"
        return result

    def close(self) -> None:
        self._closed = True
        self._close_socket()
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2)
        self._error_event.set()
        for event in self._ack_events.values():
            event.set()

    def _page_url(
        self, target: DurationTarget, course_id: str, resource_id: int
    ) -> str:
        return (
            f"https://{_DURATION_HOST}/_explorationpc_default/pc.html"
            f"?source=cloud&courseResourceId={resource_id}"
            f"#/{course_id}/courseware/{target.route_path}"
        )

    def _send_sync(self, message: str) -> None:
        if self._socket is None:
            raise NetworkError("计时连接未建立")
        self._socket.send(message)

    def _recv_sync(self):
        if self._socket is None:
            raise NetworkError("计时连接未建立")
        return self._socket.recv(timeout=self.open_timeout)

    def _pump(self) -> None:
        try:
            while not self._closed:
                try:
                    message = self._socket.recv(timeout=1) if self._socket else None
                except TimeoutError:
                    continue
                if message is None:
                    continue
                if not isinstance(message, str):
                    continue
                if message == "2":
                    self._send_sync("3")
                    continue
                match = _ACK_RE.match(message)
                if not match:
                    continue
                try:
                    arguments = json.loads(match.group(2))
                except ValueError:
                    continue
                result = arguments[0] if arguments else None
                with self._ack_lock:
                    ack_id = int(match.group(1) or 0)
                    if ack_id not in self._ack_events:
                        pending = sorted(self._ack_events)
                        ack_id = pending[0] if pending else 0
                    if ack_id:
                        self._ack_results[ack_id] = (
                            result if isinstance(result, dict) else None
                        )
                        self._ack_events[ack_id].set()
        except Exception as exc:
            self._fail(exc)

    def _fail(self, exc: Exception | None) -> None:
        with self._ack_lock:
            if self._error is None:
                self._error = exc or NetworkError("计时连接中断")
            for event in self._ack_events.values():
                event.set()

    def _close_socket(self) -> None:
        socket = self._socket
        self._socket = None
        if socket is None:
            return
        try:
            socket.close()
        except Exception:
            pass
