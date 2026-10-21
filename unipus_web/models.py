"""跨层数据模型与宽松 JSON 取值工具。

后端字段经常出现 null、""、字符串化 JSON，这里统一做容错。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


# ------------------------------------------------------------ 宽松取值工具


def lenient_obj(value: Any) -> dict:
    """dict 原样返回；字符串尝试二次解析；其余返回空 dict。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        text = str(value).strip()
        if not text:
            return default
        return int(text)
    except (ValueError, TypeError):
        try:
            return int(float(str(value).strip()))
        except (ValueError, TypeError):
            return default


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    try:
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except (ValueError, TypeError):
        return default


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return default


def as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


# ------------------------------------------------------------------- 模型


@dataclass
class User:
    username: str = ""
    jwt: str = ""
    open_id: str = ""
    name: str = ""
    school_name: str = ""
    app_user_id: str = ""
    sso_id: str = ""


@dataclass
class CourseResource:
    id: int = 0
    resource_id: str = ""
    instance_id: str = ""
    strategy_id: int = 0
    name: str = ""
    finish_point_num: int = 0
    total_point_num: int = 0

    @classmethod
    def from_json(cls, data: dict | None) -> "CourseResource":
        d = lenient_obj(data)
        return cls(
            id=as_int(d.get("id")),
            resource_id=as_str(d.get("resourceId")),
            instance_id=as_str(d.get("instanceId")),
            strategy_id=as_int(d.get("strategyId")),
            name=as_str(d.get("name")),
            finish_point_num=as_int(d.get("finishPointNum")),
            total_point_num=as_int(d.get("totalPointNum")),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Course:
    id: int = 0
    name: str = ""
    start_time: int = 0
    end_time: int = 0
    resources: list[CourseResource] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict | None) -> "Course":
        d = lenient_obj(data)
        raw_resources = d.get("courseResourceList")
        resources = (
            [CourseResource.from_json(r) for r in raw_resources]
            if isinstance(raw_resources, list)
            else []
        )
        return cls(
            id=as_int(d.get("id")),
            name=as_str(d.get("name")),
            start_time=as_int(d.get("startTime")),
            end_time=as_int(d.get("endTime")),
            resources=resources,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "resources": [r.to_dict() for r in self.resources],
        }


@dataclass
class TaskSnapshot:
    id: str = ""
    username: str = ""
    name: str = ""
    status: str = "INITIALIZING"
    description: str = ""
    completed: int = 0
    total: int = 0
    progress_percent: int = 0
    user_name: str = ""
    school_name: str = ""
    user_operation: str | None = None
    courses: list[dict] = field(default_factory=list)
    warning: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnswerRecord:
    id: int = 0
    answers: list[str] = field(default_factory=list)
    analysis_items: list[str] = field(default_factory=list)
    analysis: str = ""


@dataclass
class SituationNode:
    node_id: str = ""
    caption: str = ""
    name: str = ""
    path: str = ""
    role: str = ""
    finish_progress: float = 0.0
    duration: int = 0
    required: bool = False
    score_task_flag: bool = False
    children: list["SituationNode"] = field(default_factory=list)


@dataclass
class LogRecord:
    seq: int = 0
    ts: int = 0
    level: str = "INFO"
    logger: str = ""
    message: str = ""
    task_id: str | None = None
    thread: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RequestRecord:
    seq: int = 0
    ts: int = 0
    task_id: str = ""
    method: str = "GET"
    url: str = ""
    status_code: int | None = None
    status_text: str = ""
    duration_ms: int = 0
    request_headers: dict = field(default_factory=dict)
    response_headers: dict = field(default_factory=dict)
    request_payload: str | None = None
    response_body: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
