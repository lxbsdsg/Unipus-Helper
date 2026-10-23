"""任务管理器：创建、控制、移除任务，并向外广播事件。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from ..api.client import UnipusClient
from ..credentials import CredentialStore
from ..events import EventBus
from ..logging_setup import LogStore
from ..models import Course, CourseResource
from ..network_log import NetworkRecorder
from .task import Status, Task

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(
        self,
        *,
        bus: EventBus,
        log_store: LogStore,
        network: NetworkRecorder,
        credentials: CredentialStore,
        allow_multi_question: bool = True,
        client_factory: Callable[[str], object] | None = None,
    ) -> None:
        self.bus = bus
        self.log_store = log_store
        self.network = network
        self.credentials = credentials
        self.allow_multi_question = allow_multi_question
        self.client_factory = client_factory or self._default_client_factory

        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()

    def _default_client_factory(self, task_id: str) -> UnipusClient:
        return UnipusClient(task_id, record=self.network.add)

    # ------------------------------------------------------------ 创建/移除

    def create_task(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        credential_id: str | None = None,
    ) -> dict:
        login_session = None
        if credential_id:
            secret = self.credentials.get_secret(credential_id)
            if secret is None:
                raise ValueError("已保存的账号不存在")
            username, password = secret
            login_session = self.credentials.get_login_session(credential_id)
        if not username:
            raise ValueError("缺少用户名")

        task_id = f"task-{username}"
        session_saver = None
        if credential_id:
            session_saver = lambda session, cid=credential_id: (
                self.credentials.update_session(cid, session)
            )
        with self._lock:
            if task_id in self._tasks:
                raise ValueError("任务已存在")
            task = Task(
                task_id,
                username,
                password,
                client_factory=self.client_factory,
                on_change=self._on_task_change,
                on_warning=lambda message, tid=task_id: self._on_warning(tid, message),
                on_error=lambda message, tid=task_id: self._on_error(tid, message),
                credential_id=credential_id,
                login_session=login_session,
                on_login_session=session_saver,
                allow_multi_question=self.allow_multi_question,
            )
            self._tasks[task_id] = task

        logger.info("Task %s added.", task_id)
        self.bus.publish("task.added", task.snapshot())
        threading.Thread(
            target=task.initialize,
            name=f"init-{task_id}",
            daemon=True,
        ).start()
        return task.snapshot()

    def export_login_session(self, task_id: str, username: str) -> dict | None:
        task = self.get(task_id)
        if task is None or task.username != username or task.client is None:
            return None
        try:
            return task.client.export_login_session()
        except Exception:
            return None

    def remove(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.pop(task_id, None)
        if task is None:
            return False
        task.mark_removed()
        try:
            if task.client is not None:
                task.client.close()
        except Exception:
            pass
        self.bus.publish("task.removed", {"id": task_id})
        logger.info("Task %s removed.", task_id)
        return True

    def shutdown(self) -> None:
        with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for task in tasks:
            task.mark_removed()
            try:
                if task.client is not None:
                    task.client.close()
            except Exception:
                pass
        self.bus.publish("tasks.cleared", {})

    # ------------------------------------------------------------ 控制

    def start(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        ok = task.start()
        self.bus.publish("task.updated", task.snapshot())
        return ok

    def start_catalog(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        ok = task.start_catalog()
        self.bus.publish("task.updated", task.snapshot())
        return ok

    def pause(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        task.request_pause()
        return True

    def resume(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        task.request_resume()
        return True

    def stop(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        task.request_stop()
        return True

    def restart(self, task_id: str) -> bool:
        """停止后重新启动；用于 ERROR / COMPLETED 状态的任务。"""
        task = self.get(task_id)
        if task is None:
            return False
        if task.status is Status.INITIALIZING:
            return False
        mode = task.practice_mode
        task.request_stop()
        return task.start(practice_mode=mode)

    def choose_course(self, task_id: str, course_id: int, resource_id: int) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        course = self._find_course(task, course_id)
        if course is None:
            raise ValueError("课程不存在")
        resource = self._find_resource(course, resource_id)
        if resource is None:
            raise ValueError("教程不存在")
        task.choose_course(course, resource)
        return True

    def choose_practice(self, task_id: str, task_ids: list[str]) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        task.choose_practice(task_ids)
        return True

    # ------------------------------------------------------------ 查询

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def snapshots(self) -> list[dict]:
        with self._lock:
            tasks = list(self._tasks.values())
        return [task.snapshot() for task in tasks]

    def _wait_ready(self, task_id: str, timeout: float = 2.0) -> Task | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = self.get(task_id)
            if task is not None and task.status in (Status.READY, Status.ERROR):
                return task
            time.sleep(0.01)
        return self.get(task_id)

    # ------------------------------------------------------------ 事件回调

    def _on_task_change(self, snapshot: dict) -> None:
        self.bus.publish("task.updated", snapshot)

    def _on_warning(self, task_id: str, message: str) -> None:
        logger.warning("[%s] %s", task_id, message)
        self.bus.publish(
            "task.warning", {"task_id": task_id, "message": message}
        )

    def _on_error(self, task_id: str, message: str) -> None:
        logger.error("[%s] %s", task_id, message)
        self.bus.publish("task.error", {"task_id": task_id, "message": message})

    # ------------------------------------------------------------ 课程查找

    @staticmethod
    def _find_course(task: Task, course_id: int) -> Course | None:
        for course in task.course_list:
            if course.id == course_id:
                return course
        return None

    @staticmethod
    def _find_resource(course: Course, resource_id: int) -> CourseResource | None:
        for resource in course.resources:
            if resource.id == resource_id:
                return resource
        return None
