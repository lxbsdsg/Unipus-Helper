"""提交请求体构造。

按接口契约构造单题 / 预设 / 多题三种提交体。
多小题路径尚未经过实网验证，属实验性特性。
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..crypto import html_to_text, sanitize_answer
from .course_detail import (
    INVALID_TYPES,
    PRESET_MODES,
    STUDY_MODES,
    QuestionType,
)


def map_question_type(qtype: QuestionType) -> str:
    name = qtype.name.lower()
    if "banked" in name or "cloze" in name:
        return "material-banked-cloze"
    return name.replace("_", "-")


def map_reply_type(qtype: QuestionType) -> str:
    name = qtype.name.lower()
    if "banked" in name or "cloze" in name:
        return "bankedcloze"
    return "objective"


def _prepare(value: str, sanitize: bool) -> str:
    if not sanitize:
        return value
    return sanitize_answer(html_to_text(value))


def _preset_body(group_id: str, course_id: str, open_id: str) -> str:
    return json.dumps(
        {
            "quesDatas": [],
            "groupId": group_id,
            "isCompleted": [],
            "thirdPartyJudges": "[]",
            "submitType": 2,
            "hideLoading": True,
            "associationGroupId": "",
            "courseId": course_id,
            "openId": open_id,
            "version": "default",
        },
        ensure_ascii=False,
    )


def _single_body(
    instance_id: int,
    answers: list[str],
    group_id: str,
    course_id: str,
    open_id: str,
    qtype: QuestionType,
    sanitize: bool,
) -> str:
    if qtype in INVALID_TYPES:
        raise ValueError(f"不支持的题型：{qtype.value}")
    if qtype in PRESET_MODES:
        return _preset_body(group_id, course_id, open_id)

    children: list[dict] = []
    is_completed: list[bool] = []
    judges: list[dict] = []
    for raw in answers:
        value = _prepare(raw, sanitize)
        children.append({"value": [value], "isDone": True})
        is_completed.append(True)
        judges.append(
            {
                "value": value,
                "question_type": "basic",
                "payloads": [
                    {"recordDetail": {"score": 100.0, "comment": ""}}
                ],
            }
        )

    answer_obj = {
        "value": [],
        "children": children,
        "progress": {},
        "record": {"url": ""},
    }
    body = {
        "quesDatas": [
            {
                "instanceId": str(instance_id),
                "answer": json.dumps(answer_obj, ensure_ascii=False),
                "context": '{"state":"submitted"}',
                "contextVersion": 0,
                "answerVersion": 0,
            }
        ],
        "groupId": group_id,
        "isCompleted": is_completed,
        "thirdPartyJudges": json.dumps(judges, ensure_ascii=False),
        "submitType": 2 if qtype in STUDY_MODES else 1,
        "hideLoading": False,
        "associationGroupId": "",
        "courseId": course_id,
        "openId": open_id,
        "version": "default",
    }
    return json.dumps(body, ensure_ascii=False)


def _video_popup_body(
    instance_ids: list[int],
    answers: list[list[str]],
    group_id: str,
    course_id: str,
    open_id: str,
    sanitize: bool,
) -> str:
    """构造视频弹题提交体。

    官方页面会把弹题的所有选项合并到同一个 child，并在 progress 中写入
    已观看标记；缺少该标记时服务端只保存答案，不会推进视频完成度。
    """
    ques_datas: list[dict] = []
    is_completed: list[bool] = []
    judges: list[dict] = []
    for instance_id, raw_answers in zip(instance_ids, answers):
        values = [_prepare(value, sanitize) for value in raw_answers]
        answer_obj = {
            "value": [],
            "children": [{"value": values, "isDone": True}],
            "progress": {"0": True},
            "record": {"url": ""},
        }
        ques_datas.append(
            {
                "instanceId": str(instance_id),
                "answer": json.dumps(answer_obj, ensure_ascii=False),
                "context": '{"state":"submitted"}',
                "contextVersion": 1,
                "answerVersion": 1,
            }
        )
        is_completed.append(True)
        judges.append(
            {
                "value": ",".join(values),
                "question_type": QuestionType.VIDEO_POPUP.value,
                "reply_type": "multichoice",
                "versions": {
                    "course": 0,
                    "group": 1,
                    "template": 1,
                    "answer": 0,
                    "content": 0,
                },
                "payloads": [],
            }
        )

    body = {
        "quesDatas": ques_datas,
        "groupId": group_id,
        "isCompleted": is_completed,
        "thirdPartyJudges": json.dumps(judges, ensure_ascii=False),
        "submitType": 1,
        "hideLoading": False,
        "associationGroupId": "",
        "courseId": course_id,
        "openId": open_id,
        "version": "default",
    }
    return json.dumps(body, ensure_ascii=False)


def _repeat(value: Any, n: int) -> list:
    return [value for _ in range(n)]


def _build_course_answer_block(
    group_id: str, ques_id: str, blanks: int, submit_info: dict
) -> dict:
    return {
        "isStudy": False,
        "groupId": group_id,
        "quesId": ques_id,
        "isRight": _repeat(True, blanks),
        "isDone": _repeat(True, blanks),
        "subPct": _repeat(1, blanks),
        "counted": _repeat(True, blanks),
        "isObjective": _repeat(True, blanks),
        "firstSubmit": False,
        "submitInfo": submit_info,
    }


def _build_submit_info_full_score(
    group_id: str, total_blanks: int, now_ms: int
) -> dict:
    now_sec = now_ms // 1000
    return {
        "group_id": group_id,
        "strategyId": 0,
        "record_grade": {"scorePct": 1.0, "ts": now_ms},
        "state": {
            "expired": False,
            "lastSubmit": now_sec,
            "not_start": False,
            "real_score_pct": "1.0",
            "score": _repeat(1, total_blanks),
            "score_avg": "100",
            "score_pct": "1.0",
            "state": 0,
        },
        "strategy": {
            "endTime": now_sec + 30 * 24 * 3600,
            "record_every_submit": False,
            "record_max_submit": False,
            "required": True,
            "startTime": now_sec,
            "task_mini_score_pct": 0,
        },
        "version": str(now_sec),
        "pass": True,
    }


def _build_inner_answer_string(answers: list[str], full_right: bool = True) -> str:
    children = [
        {
            "value": [value],
            "isDone": True,
            "isRight": True if full_right else None,
            "replyCategory": "objective",
        }
        for value in answers
    ]
    answer_obj = {
        "value": [],
        "children": children,
        "progress": {},
        "record": {"url": ""},
    }
    return json.dumps(answer_obj, ensure_ascii=False)


def _multi_body(
    instance_ids: list[int],
    answers: list[list[str]],
    group_id: str,
    course_id: str,
    open_id: str,
    question_types: list[QuestionType],
    sanitize: bool,
    now_ms: int,
) -> str:
    n = len(instance_ids)
    prepared = [
        [_prepare(v, sanitize) for v in (answers[i] or [])] for i in range(n)
    ]
    per_question_blanks = [len(a) for a in prepared]
    total_blanks = sum(per_question_blanks)

    submit_info = _build_submit_info_full_score(group_id, total_blanks, now_ms)
    shared_map = {
        str(instance_ids[j]): _build_course_answer_block(
            group_id, str(instance_ids[j]), per_question_blanks[j], submit_info
        )
        for j in range(n)
    }

    is_completed: list[bool] = []
    judges: list[dict] = []
    ques_datas: list[dict] = []

    for i in range(n):
        qid = str(instance_ids[i])
        ans = prepared[i]
        qtype = question_types[i]

        for value in ans:
            is_completed.append(True)
            judges.append(
                {
                    "value": value,
                    "question_type": map_question_type(qtype),
                    "reply_type": map_reply_type(qtype),
                    "versions": {
                        "course": 0,
                        "group": 1,
                        "template": 1,
                        "answer": 0,
                        "content": 0,
                    },
                    "payloads": [],
                }
            )

        ques_datas.append(
            {
                "courseAnswer": _build_course_answer_block(
                    group_id, qid, len(ans), submit_info
                ),
                "courseAnswerMap": shared_map,
                "instanceId": qid,
                "answer": _build_inner_answer_string(ans),
                "context": json.dumps({"state": "submitted"}),
                "contextVersion": 1,
                "answerVersion": 0,
            }
        )

    submit_type = 2 if all(t in STUDY_MODES for t in question_types) else 1
    body = {
        "quesDatas": ques_datas,
        "groupId": group_id,
        "isCompleted": is_completed,
        "thirdPartyJudges": json.dumps(judges, ensure_ascii=False),
        "submitType": submit_type,
        "hideLoading": False,
        "associationGroupId": "",
        "courseId": course_id,
        "openId": open_id,
        "version": "default",
    }
    return json.dumps(body, ensure_ascii=False)


def create_submit_body(
    instance_ids: list[int],
    answers: list[list[str]],
    group_id: str,
    course_id: str,
    open_id: str,
    question_types: list[QuestionType],
    *,
    sanitize: bool = True,
    now_ms: int | None = None,
) -> str:
    if not (
        len(instance_ids) == len(answers) == len(question_types)
        and len(instance_ids) > 0
    ):
        raise ValueError(
            "instance_ids, answers, question_types 长度必须一致且非空；"
            f"实际为 {len(instance_ids)}/{len(answers)}/{len(question_types)}"
        )

    if all(qtype is QuestionType.VIDEO_POPUP for qtype in question_types):
        return _video_popup_body(
            instance_ids,
            answers,
            group_id,
            course_id,
            open_id,
            sanitize,
        )

    if len(instance_ids) == 1:
        return _single_body(
            instance_ids[0],
            answers[0] or [],
            group_id,
            course_id,
            open_id,
            question_types[0],
            sanitize,
        )

    return _multi_body(
        instance_ids,
        answers,
        group_id,
        course_id,
        open_id,
        question_types,
        sanitize,
        now_ms if now_ms is not None else int(time.time() * 1000),
    )
