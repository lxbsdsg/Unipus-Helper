"""网络请求记录器（内存环形缓冲 + 脱敏）。"""

from __future__ import annotations

import copy
import json
import threading
from collections import deque
from typing import Callable

from .config import NETWORK_BUFFER_SIZE

SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-annotator-auth-token",
}
SENSITIVE_KEYS = {"password", "passwd", "pwd"}
SENSITIVE_RESPONSE_URLS = (
    "https://sso.unipus.cn/sso/0.1/sso/login",
    "https://uai.unipus.cn/api/account/user/info",
    "uai.unipus.cn/api/tla/learningDetail/studyRecord/totalAndUnitSituation",
)


def redact_headers(headers: dict | None) -> dict:
    if not headers:
        return {}
    out = {}
    for key, value in headers.items():
        if str(key).lower() in SENSITIVE_HEADERS:
            out[key] = "<redacted>"
        else:
            out[key] = value
    return out


def _redact_payload(payload: str | None) -> str | None:
    if not payload:
        return payload
    try:
        parsed = json.loads(payload)
    except (ValueError, TypeError):
        return payload

    def walk(value):
        if isinstance(value, dict):
            return {
                k: ("<redacted>" if str(k).lower() in SENSITIVE_KEYS else walk(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return json.dumps(walk(parsed), ensure_ascii=False)


def redact_record(record: dict) -> dict:
    """返回脱敏后的深拷贝，用于 API 输出、WebSocket 推送与报告。"""
    out = copy.deepcopy(record)
    out["request_headers"] = redact_headers(record.get("request_headers"))
    out["response_headers"] = redact_headers(record.get("response_headers"))
    out["request_payload"] = _redact_payload(record.get("request_payload"))

    # 登录、用户信息、学习进度响应包含 JWT、openid、姓名等，整段隐藏
    url = str(record.get("url", ""))
    if any(marker in url for marker in SENSITIVE_RESPONSE_URLS):
        out["response_body"] = "<redacted>"
    return out


class NetworkRecorder:
    def __init__(self, capacity: int = NETWORK_BUFFER_SIZE) -> None:
        self._items: deque[dict] = deque(maxlen=max(1, capacity))
        self._seq = 0
        self._lock = threading.Lock()
        self._listener: Callable[[dict], None] | None = None

    def set_listener(self, listener: Callable[[dict], None] | None) -> None:
        self._listener = listener

    def add(self, record: dict) -> dict:
        with self._lock:
            self._seq += 1
            item = {"seq": self._seq, **record}
            self._items.append(item)
        listener = self._listener
        if listener is not None:
            try:
                listener(item)
            except Exception:  # 监听器故障不得影响请求
                pass
        return item

    def query(self, after_seq: int = 0, limit: int = 200) -> list[dict]:
        with self._lock:
            items = [dict(i) for i in self._items if i.get("seq", 0) > after_seq]
        return items[-limit:] if limit > 0 else items

    def snapshot(self) -> list[dict]:
        return self.query(limit=0)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
