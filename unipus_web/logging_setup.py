"""内存日志缓冲 + 标准 logging 桥接。"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable

from .config import LOG_BUFFER_SIZE

_LEVEL_RANK = {
    "TRACE": 5,
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "WARNING": 30,
    "ERROR": 40,
    "FATAL": 50,
    "CRITICAL": 50,
}


def _level_name(level: int | str) -> str:
    if isinstance(level, int):
        return logging.getLevelName(level)
    return str(level).upper()


class LogStore:
    def __init__(self, capacity: int = LOG_BUFFER_SIZE) -> None:
        self._items: deque[dict] = deque(maxlen=max(1, capacity))
        self._seq = 0
        self._lock = threading.Lock()
        self._listener: Callable[[dict], None] | None = None

    def set_listener(self, listener: Callable[[dict], None] | None) -> None:
        self._listener = listener

    def add(
        self,
        level: int | str,
        logger: str,
        message: str,
        task_id: str | None = None,
        thread: str | None = None,
    ) -> dict:
        with self._lock:
            self._seq += 1
            record = {
                "seq": self._seq,
                "ts": int(time.time() * 1000),
                "level": _level_name(level),
                "logger": logger,
                "message": message,
                "task_id": task_id,
                "thread": thread or threading.current_thread().name,
            }
            self._items.append(record)
        listener = self._listener
        if listener is not None:
            try:
                listener(record)
            except Exception:
                pass
        return record

    def query(
        self, after_seq: int = 0, limit: int = 1000, min_level: str | None = None
    ) -> list[dict]:
        with self._lock:
            items = [dict(i) for i in self._items if i["seq"] > after_seq]
        if min_level:
            threshold = _LEVEL_RANK.get(min_level.upper(), 0)
            items = [i for i in items if _LEVEL_RANK.get(i["level"], 0) >= threshold]
        if limit and limit > 0:
            items = items[-limit:]
        return items

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class BusLogHandler(logging.Handler):
    def __init__(self, store: LogStore, level: int = logging.DEBUG) -> None:
        super().__init__(level)
        self.store = store

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.store.add(
                record.levelno,
                record.name,
                record.getMessage(),
                task_id=getattr(record, "task_id", None),
                thread=record.threadName,
            )
        except Exception:
            self.handleError(record)


_configured = False


def setup_logging(log_store: LogStore, level: int = logging.DEBUG) -> None:
    """给根 logger 挂上内存 Handler 与精简控制台 Handler。

    重复调用（例如测试中多次 create_app）会替换旧的内存 Handler，
    保证日志进入当前应用实例的 LogStore。
    """
    global _configured

    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        if isinstance(handler, BusLogHandler):
            root.removeHandler(handler)

    bus_handler = BusLogHandler(log_store)
    bus_handler.setLevel(level)
    root.addHandler(bus_handler)

    has_console = any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, BusLogHandler)
        for handler in root.handlers
    )
    if not has_console:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s %(name)s - %(message)s")
        )
        root.addHandler(console)

    # 降低第三方噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.INFO)
    _configured = True
