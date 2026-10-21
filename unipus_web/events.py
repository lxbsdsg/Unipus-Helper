"""线程 → asyncio 的事件总线。"""

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any

logger = logging.getLogger(__name__)

_QUEUE_SIZE = 1000


class EventBus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: list[asyncio.Queue] = []
        self._seq = itertools.count(1)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def publish(self, event_type: str, payload: dict | None = None) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            # 没有事件循环时静默丢弃。注意不能在这里写日志：
            # LogStore 的监听器本身就会 publish，会形成日志→事件→日志的死循环。
            return

        event: dict[str, Any] = {
            "type": event_type,
            "data": payload or {},
            "seq": next(self._seq),
        }
        for queue in list(self._subscribers):
            try:
                loop.call_soon_threadsafe(self._offer, queue, event)
            except RuntimeError:
                # loop 正在关闭
                return

    @staticmethod
    def _offer(queue: asyncio.Queue, event: dict) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass
