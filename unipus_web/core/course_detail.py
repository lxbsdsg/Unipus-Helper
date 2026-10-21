"""课程结构（AllTaskofCourseResponse.course）解析。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..api.errors import UnsupportedError
from ..config import DEFAULT_TASK_END
from ..models import as_int, as_str, lenient_obj


class QuestionType(str, Enum):
    MATERIAL_BANKED_CLOZE = "material-banked-cloze"
    SINGLE_CHOICE = "single-choice"
    SHORT_ANSWER = "short_answer"
    TRANSLATION = "translation"
    TEXT_LEARN = "text-learn"
    DISCUSSION = "discussion"
    INPUT = "input"
    VIDEO_POINT_READ = "video-point-read"
    RICH_TEXT_READ = "rich-text-read"
    VOCABULARY = "vocabulary"
    SEQUENCE = "sequence"
    BASIC_SCOOP_CONTENT = "basic-scoop-content"
    VIDEO_POPUP = "video-popup"
    WRITING = "writing"
    MULTI_FILE_UPLOAD = "multiFileUpload"
    EXIT_TICKET = "exit-ticket"
    MULTICHOICE = "multichoice"
    UNKNOWN = "__unknown__"

    @classmethod
    def from_raw(cls, raw: str | None) -> "QuestionType":
        if not raw:
            return cls.UNKNOWN
        key = _normalise(raw)
        if key in _TYPE_LOOKUP:
            return _TYPE_LOOKUP[key]
        alt = key.replace("_", "-")
        if alt in _TYPE_LOOKUP:
            return _TYPE_LOOKUP[alt]
        kebab = _normalise(_camel_to_kebab(raw))
        return _TYPE_LOOKUP.get(kebab, cls.UNKNOWN)


class Role(str, Enum):
    UNIT = "unit"
    SECTION = "section"
    NODE = "node"
    LINK = "link"
    GROUP = "group"

    @classmethod
    def from_raw(cls, raw: str | None) -> "Role":
        try:
            return cls((raw or "").strip().lower())
        except ValueError:
            return cls.NODE


def _normalise(value: str) -> str:
    return value.strip().lower()


def _camel_to_kebab(value: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1-\2", value)


_TYPE_LOOKUP = {}
for _member in QuestionType:
    if _member is QuestionType.UNKNOWN:
        continue
    for _raw in (
        _member.value,
        _member.value.replace("_", "-"),
        _camel_to_kebab(_member.value),
    ):
        _TYPE_LOOKUP[_normalise(_raw)] = _member


# 当前不支持提交的题型集合
INVALID_TYPES = {
    QuestionType.DISCUSSION,
    QuestionType.MULTI_FILE_UPLOAD,
    QuestionType.EXIT_TICKET,
    QuestionType.MULTICHOICE,
    QuestionType.UNKNOWN,
}
STUDY_MODES = {
    QuestionType.RICH_TEXT_READ,
    QuestionType.TEXT_LEARN,
    QuestionType.VIDEO_POPUP,
    QuestionType.VOCABULARY,
    QuestionType.DISCUSSION,
    QuestionType.INPUT,
    QuestionType.VIDEO_POINT_READ,
}
PRESET_MODES = {
    QuestionType.RICH_TEXT_READ,
    QuestionType.TEXT_LEARN,
    QuestionType.VOCABULARY,
    QuestionType.INPUT,
    QuestionType.VIDEO_POINT_READ,
}


@dataclass
class Node:
    id: str = ""
    role: Role = Role.NODE
    caption: str = ""
    name: str = ""
    url: str = ""
    ref_out: str = ""
    children: list["Node"] = field(default_factory=list)
    question_num: int = 0
    bases: list[QuestionType] = field(default_factory=list)
    tab_type: str = "unknown"
    link_type: str = "unknown"


def is_answerable(node: Node, *, allow_multi_question: bool = True) -> bool:
    """叶子节点是否属于当前程序可以作答的任务。"""
    if node.children or not node.id:
        return False
    if node.role not in (Role.GROUP, Role.LINK):
        return False
    if not node.bases:
        return False
    if any(qtype in INVALID_TYPES for qtype in node.bases):
        return False
    # 与 _learn_task 的规则保持一致：单一题型；多小题受配置开关控制
    if len(set(node.bases)) != 1:
        return False
    if node.question_num > 1 and not allow_multi_question:
        return False
    return True


def _node_to_dict(node: Node) -> dict:
    data = {
        "id": node.id,
        "role": node.role.value,
        "caption": node.caption,
        "name": node.name,
        "question_num": node.question_num,
        "bases": [qtype.value for qtype in node.bases],
        "tab_type": node.tab_type,
        "link_type": node.link_type,
    }
    if node.children:
        data["children"] = [_node_to_dict(child) for child in node.children]
    return data


class CourseDetail:
    def __init__(self, name: str, type_: str, units: list[Node]) -> None:
        self.name = name
        self.type = type_
        self.units = units
        self.node_index: dict[str, Node] = {}
        self.unit_of: dict[str, str] = {}
        self._start_times: dict[str, int] = {}
        self._end_times: dict[str, int] = {}

    @classmethod
    def from_json(cls, course_json: str | dict) -> "CourseDetail":
        if isinstance(course_json, str):
            try:
                root = json.loads(course_json)
            except ValueError as exc:
                raise UnsupportedError("课程结构不是合法 JSON") from exc
        else:
            root = course_json or {}
        if not isinstance(root, dict):
            raise UnsupportedError("课程结构不是 JSON 对象")

        course = cls(
            name=as_str(root.get("name")),
            type_=as_str(root.get("type"), "unknown"),
            units=[],
        )
        for element in root.get("units") or []:
            node = Node()
            course._traverse(node, element, course.node_index, "")
            course.units.append(node)
        return course

    def _traverse(
        self, node: Node, element: Any, index: dict[str, Node], parent_unit: str
    ) -> None:
        data = lenient_obj(element)
        node.id = as_str(data.get("id") or data.get("url"))
        node.role = Role.from_raw(as_str(data.get("role")))
        node.caption = as_str(data.get("caption"))
        node.name = as_str(data.get("name"), "Unknown name")
        if node.role is not Role.SECTION:
            node.url = as_str(data.get("url"), "Unknown url")
            node.ref_out = as_str(data.get("ref-out"), "Unknown ref-out")

        current_unit = node.id if node.role is Role.UNIT and node.id else parent_unit
        if node.id:
            index[node.id] = node
            self.unit_of[node.id] = current_unit

        children = data.get("children")
        if isinstance(children, list):
            node.children = []
            for child_element in children:
                child = Node()
                node.children.append(child)
                self._traverse(child, child_element, index, current_unit)
        else:
            node.question_num = as_int(data.get("question_num"))
            raw_base = as_str(data.get("base"), "unknown")
            node.bases = [QuestionType.from_raw(part.strip()) for part in raw_base.split(",")]
            node.tab_type = as_str(data.get("tab_type"), "unknown")
            if node.role is Role.LINK:
                node.link_type = as_str(data.get("linkType"), "unknown")

    # ------------------------------------------------------------- 目录

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "units": [_node_to_dict(node) for node in self.units],
        }

    # ------------------------------------------------------------- 查询

    def get_node(self, node_id: str) -> Node | None:
        return self.node_index.get(node_id)

    def get_question_types(self, node_id: str) -> list[QuestionType]:
        node = self.get_node(node_id)
        if node is None:
            raise UnsupportedError(f"未知题目节点：{node_id}")
        if node.role not in (Role.GROUP, Role.LINK):
            raise UnsupportedError(f"{node_id} 不是可作答节点")
        return list(node.bases)

    def get_question_type(self, node_id: str, index: int = 0) -> QuestionType:
        types = self.get_question_types(node_id)
        if not types:
            return QuestionType.UNKNOWN
        # 同一题型多小题时 bases 只有一项，越界回落到最后一项
        return types[min(max(index, 0), len(types) - 1)]

    # ------------------------------------------------------------- 时间表

    def init_task_times(self, payload: str | dict) -> bool:
        if isinstance(payload, str):
            try:
                root = json.loads(payload)
            except ValueError:
                return False
        else:
            root = payload or {}
        root = lenient_obj(root)
        code = as_int(root.get("code"), 0)
        if code != 0:
            return False

        rt = lenient_obj(root.get("rt"))
        leafs = lenient_obj(rt.get("leafs"))
        self._start_times.clear()
        self._end_times.clear()
        for node_id, leaf in leafs.items():
            leaf = lenient_obj(leaf)
            # 时间字段位于 strategies 层级，优先读取并回退到叶子节点
            strategies = lenient_obj(leaf.get("strategies"))
            start = strategies.get("start_time", leaf.get("start_time", 0))
            end = strategies.get("end_time", leaf.get("end_time", DEFAULT_TASK_END))
            self._start_times[node_id] = as_int(start, 0)
            self._end_times[node_id] = as_int(end, DEFAULT_TASK_END)
        return True

    def get_task_start(self, node_id: str) -> int:
        return self._start_times.get(node_id, 0)

    def get_task_end(self, node_id: str) -> int:
        return self._end_times.get(node_id, DEFAULT_TASK_END)
