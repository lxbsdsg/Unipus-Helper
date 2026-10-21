"""答案 JSON 解析与按题型抽取。"""

from __future__ import annotations

import json
from typing import Any

from ..api.errors import UnsupportedError
from ..models import AnswerRecord, as_int, as_str, lenient_obj
from .course_detail import QuestionType

_OBJECTIVE_TYPES = {
    QuestionType.MATERIAL_BANKED_CLOZE,
    QuestionType.SINGLE_CHOICE,
    QuestionType.SEQUENCE,
    QuestionType.BASIC_SCOOP_CONTENT,
    QuestionType.TRANSLATION,
    QuestionType.VIDEO_POPUP,
}
_NO_ANSWER_TYPES = {
    QuestionType.RICH_TEXT_READ,
    QuestionType.TEXT_LEARN,
    QuestionType.VIDEO_POINT_READ,
    QuestionType.VOCABULARY,
    QuestionType.INPUT,
}


def _decode_inner(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        return lenient_obj(value)
    return {}


def parse_answers(answer_json: str | None) -> list[AnswerRecord]:
    """解析 getAnswer 返回的 JSON 数组；坏数据返回可解析部分。"""
    if not answer_json:
        return []
    try:
        items = json.loads(answer_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(items, list):
        return []

    records: list[AnswerRecord] = []
    for item in items:
        data = lenient_obj(item)
        answer_obj = _decode_inner(data.get("answer"))
        analysis_obj = _decode_inner(data.get("analysis"))

        answers: list[str] = []
        for child in answer_obj.get("children") or []:
            child_data = lenient_obj(child)
            raw_answers = child_data.get("answers")
            if isinstance(raw_answers, list) and raw_answers:
                answers.append(as_str(raw_answers[0]))

        analysis_items: list[str] = []
        for child in analysis_obj.get("children") or []:
            analysis_items.append(as_str(lenient_obj(child).get("analysis")))

        records.append(
            AnswerRecord(
                id=as_int(data.get("id")),
                answers=answers,
                analysis_items=analysis_items,
                analysis=as_str(analysis_obj.get("analysis")),
            )
        )
    return records


def extract_answers(answer: AnswerRecord, qtype: QuestionType) -> list[str]:
    if qtype in _OBJECTIVE_TYPES:
        return list(answer.answers)
    if qtype is QuestionType.SHORT_ANSWER:
        return list(answer.analysis_items)
    if qtype is QuestionType.WRITING:
        return [answer.analysis] if answer.analysis else []
    if qtype in _NO_ANSWER_TYPES:
        return []
    raise UnsupportedError(f"不支持的题型：{qtype.value}")
