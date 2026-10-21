"""学习主流程。按设计文档第 5.3 节的顺序实现。"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

from ..api.errors import TaskStopped, UnipusError, UnsupportedError
from ..config import MAX_SUBMITS_PER_MINUTE
from ..crypto import decrypt_answer
from ..models import (
    CourseResource,
    as_float,
    as_int,
    as_str,
    lenient_obj,
)
from .answer import extract_answers, parse_answers
from .course_detail import (
    INVALID_TYPES,
    PRESET_MODES,
    CourseDetail,
    QuestionType,
)
from .submit import create_submit_body
from .unit_situation import UnitSituation

logger = logging.getLogger(__name__)


@dataclass
class LearnSummary:
    submitted_tasks: int = 0
    skipped_tasks: int = 0
    completed_units: int = 0
    skipped_reasons: list[str] = field(default_factory=list)


class SubmitThrottle:
    """每次 learn_course 运行共享一份提交时间戳，限制 5 次/分钟。

    submitTimestamps 跨单元、跨任务生效；
    整次学习流程必须复用同一个实例。
    """

    def __init__(self, max_per_minute: int = MAX_SUBMITS_PER_MINUTE, clock=time.time):
        self._max = max(1, max_per_minute)
        self._clock = clock
        self._timestamps: deque[float] = deque()

    def wait_ms(self) -> int:
        now = self._clock()
        while self._timestamps and self._timestamps[0] + 60 < now:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._max:
            return max(0, int((self._timestamps[0] + 60 - now) * 1000))
        return 0

    def record(self) -> None:
        self._timestamps.append(self._clock())


def _skip(control, summary: LearnSummary, reason: str) -> None:
    summary.skipped_tasks += 1
    summary.skipped_reasons.append(reason)
    logger.info("Task skipped: %s", reason)


def learn_course(
    control,
    client,
    resource: CourseResource,
    *,
    allow_multi_question: bool = True,
) -> LearnSummary:
    summary = LearnSummary()
    throttle = SubmitThrottle()
    user = control.user
    if user is None:
        raise UnipusError("尚未登录，无法开始学习。")

    control.checkpoint()
    control.set_description("正在获取教程信息")
    info = client.get_course_resource_info(str(resource.id))
    course_resource = lenient_obj(lenient_obj(info.get("value")).get("courseResource"))
    if not course_resource:
        raise UnipusError("获取教程信息失败，请检查网络连接后重试")

    course_instance_id = as_str(course_resource.get("courseInstanceId"))
    resource_id = as_int(course_resource.get("courseResourceId"))
    strategy_id = resource.strategy_id or as_int(course_resource.get("strategyId"))
    course_name = as_str(course_resource.get("courseName"))
    logger.info("Learning course %s (instance=%s)", course_name, course_instance_id)

    control.checkpoint()
    control.set_description("正在获取所有题目信息")
    all_tasks = client.get_all_tasks(resource.instance_id or course_instance_id)
    if as_int(all_tasks.get("code"), -1) != 0:
        raise UnipusError("获取教程信息失败，请检查网络连接后重试")
    course = CourseDetail.from_json(all_tasks.get("course"))

    control.checkpoint()
    control.set_description("正在获取必修课程信息")
    required_response = client.get_required_part(strategy_id, str(resource_id))
    if not required_response.get("success"):
        raise UnipusError("获取必修课程信息失败，请检查网络连接后重试")
    required_map: dict[str, list[str]] = {}
    strategies = lenient_obj(required_response.get("value")).get("courseUnitStrategyList")
    if isinstance(strategies, list):
        for item in strategies:
            entry = lenient_obj(item)
            unit_id = as_str(entry.get("unitId"))
            tasks = entry.get("requiredTask")
            required_map[unit_id] = (
                [as_str(t) for t in tasks] if isinstance(tasks, list) else []
            )

    control.checkpoint()
    control.set_description("正在查询学习进度")
    progress_response = client.get_total_and_unit_situation(
        resource_id, user.app_user_id
    )
    if not progress_response.get("success"):
        raise UnipusError("获取学习进度失败，请检查网络连接后重试")
    progress_value = lenient_obj(progress_response.get("value"))
    total_detail = lenient_obj(progress_value.get("totalDetail"))
    if as_float(total_detail.get("finishProgress")) == 100.0:
        control.set_description("所有单元已完成学习")
        return summary

    unit_list = progress_value.get("unitList")
    if not isinstance(unit_list, list):
        unit_list = []

    for unit in unit_list:
        control.checkpoint()
        unit = lenient_obj(unit)
        unit_id = as_str(unit.get("nodeId"))
        caption = as_str(unit.get("caption"))
        unit_name = as_str(unit.get("name"))
        control.set_description(f"正在学习{caption} : {unit_name}")

        if as_float(unit.get("finishProgress")) == 100.0:
            continue

        if _learn_unit(
            control,
            client,
            course,
            unit_id,
            caption,
            unit_name,
            course_instance_id,
            resource_id,
            required_map,
            summary,
            allow_multi_question=allow_multi_question,
            throttle=throttle,
        ):
            summary.completed_units += 1

    return summary


def _learn_unit(
    control,
    client,
    course: CourseDetail,
    unit_id: str,
    caption: str,
    unit_name: str,
    course_instance_id: str,
    resource_id: int,
    required_map: dict[str, list[str]],
    summary: LearnSummary,
    *,
    allow_multi_question: bool,
    throttle: SubmitThrottle,
) -> bool:
    user = control.user
    control.checkpoint()
    control.set_description(f"正在学习{caption} : {unit_name}")

    try:
        time_payload = client.get_task_time_info(
            course_instance_id, user.open_id, unit_id
        )
        course.init_task_times(time_payload)
    except UnipusError:
        raise
    except Exception as exc:
        logger.warning("Failed to init task times for unit %s: %s", unit_id, exc)

    control.checkpoint()
    situation_response = client.get_unit_task_situation(
        unit_id, resource_id, user.app_user_id, user.sso_id
    )
    if not situation_response.get("success", True):
        raise UnipusError("获取单元学习进度失败，请检查网络连接后重试")
    situation = UnitSituation.parse(situation_response)

    required_tasks = required_map.get(unit_id) or []
    if not required_tasks:
        return False

    need_learn: list[str] = []
    for task_id in required_tasks:
        node = situation.get_node_by_node_id(task_id)
        if node is None:
            # 缺失节点时跳过并告警，避免空引用
            reason = f"单元进度缺失节点 {task_id}"
            control.warn(reason)
            _skip(control, summary, reason)
            continue
        if node.finish_progress != 100.0:
            need_learn.append(task_id)

    if not need_learn:
        return False

    for task_id in need_learn:
        control.checkpoint()
        node = course.get_node(task_id)
        node_name = node.name if node else task_id
        control.set_description(f"正在学习任务 {caption} : {unit_name} - {node_name}")
        if not _learn_task(
            control,
            client,
            course,
            task_id,
            course_instance_id,
            resource_id,
            allow_multi_question=allow_multi_question,
            summary=summary,
            throttle=throttle,
        ):
            control.set_description(
                f"已跳过任务 {caption} : {unit_name} - {node_name}"
            )
    return True


def _learn_task(
    control,
    client,
    course: CourseDetail,
    task_id: str,
    course_instance_id: str,
    resource_id: int,
    *,
    allow_multi_question: bool,
    summary: LearnSummary,
    throttle: SubmitThrottle,
) -> bool:
    node = course.get_node(task_id)
    if node is None:
        _skip(control, summary, f"课程树中缺少节点 {task_id}")
        return False

    now_seconds = int(time.time())
    start = course.get_task_start(task_id)
    end = course.get_task_end(task_id)
    if not (start == 0 or end == 0) and not (start < now_seconds < end):
        _skip(control, summary, f"任务 {task_id} 不在学习时间内")
        return False

    try:
        types = course.get_question_types(task_id)
    except UnsupportedError as exc:
        _skip(control, summary, f"任务 {task_id}：{exc}")
        return False

    if not types:
        _skip(control, summary, f"任务 {task_id} 没有题型信息")
        return False

    distinct = list(dict.fromkeys(types))
    if len(distinct) != 1:
        _skip(control, summary, f"任务 {task_id} 包含多种题型，暂不支持")
        return False

    unsupported = [t for t in types if t in INVALID_TYPES]
    if unsupported:
        _skip(
            control,
            summary,
            f"任务 {task_id} 含不支持的题型：{unsupported[0].value}",
        )
        return False

    question_num = max(1, node.question_num)
    if question_num > 1 and not allow_multi_question:
        _skip(control, summary, f"任务 {task_id} 为多小题任务，已按配置跳过")
        return False
    if question_num > 1:
        logger.warning(
            "[experimental] multi-question submit task=%s questions=%s",
            task_id,
            question_num,
        )

    instance_ids: list[int] = []
    answers: list[list[str]] = []
    question_types: list[QuestionType] = []

    is_preset = all(t in PRESET_MODES for t in types)
    if is_preset:
        for index in range(question_num):
            instance_ids.append(0)
            answers.append([])  # 每题独立列表，避免互相污染
            question_types.append(course.get_question_type(task_id, index))
    else:
        checkpoints_answer = client.get_answer(
            course_instance_id, task_id, control.user.open_id
        )
        if as_int(checkpoints_answer.get("code"), -1) != 0:
            raise UnipusError(f"获取题目答案失败（task {task_id}）")
        answer_json = decrypt_answer(
            as_str(checkpoints_answer.get("data")), as_str(checkpoints_answer.get("k"))
        )
        records = parse_answers(answer_json)
        if len(records) < question_num:
            # 答案条数不足时跳过该任务
            _skip(
                control,
                summary,
                f"任务 {task_id} 答案数量不足（{len(records)}/{question_num}）",
            )
            return False

        for index in range(question_num):
            question_type = course.get_question_type(task_id, index)
            try:
                extracted = extract_answers(records[index], question_type)
            except UnsupportedError as exc:
                _skip(control, summary, f"任务 {task_id}：{exc}")
                return False
            instance_ids.append(records[index].id)
            answers.append(extracted)  # 每题独立列表，避免互相污染
            question_types.append(question_type)

    control.checkpoint()
    body = create_submit_body(
        instance_ids,
        answers,
        task_id,
        course_instance_id,
        control.user.open_id,
        question_types,
    )

    _submit_with_retry(
        control,
        client,
        body,
        task_id,
        course_instance_id,
        throttle,
    )
    _refresh_progress(control, client, resource_id)
    summary.submitted_tasks += 1
    return True


def _submit_with_retry(
    control,
    client,
    body: str,
    task_id: str,
    course_instance_id: str,
    throttle: SubmitThrottle,
) -> None:
    while True:
        control.checkpoint()
        wait_ms = throttle.wait_ms()
        if wait_ms > 0:
            control.wait_for_cooldown(wait_ms, "提交速度太快了，休息一下", "继续提交")
            control.checkpoint()

        response = client.submit(body, control.user.open_id)
        throttle.record()

        code = as_int(response.get("code"), -1)
        if code in (600001, 600002):
            control.wait_for_cooldown(
                120_000, "提交速度太快了，休息两分钟", "继续提交"
            )
            continue

        raw_data = response.get("data")
        if code != 0 or raw_data is None:
            # code=0 但 data 缺失时按失败处理
            raise UnipusError(f"提交答案失败（task {task_id}, code={code}）")

        data = lenient_obj(raw_data)
        version = as_str(data.get("version"))
        score_avg = as_float(lenient_obj(data.get("state")).get("score_avg"))
        _check_zero_score(
            control,
            client,
            task_id,
            course_instance_id,
            version,
            score_avg,
        )
        return


def _check_zero_score(
    control,
    client,
    task_id: str,
    course_instance_id: str,
    version: str,
    score_avg: float,
) -> None:
    if score_avg != 0.0:
        return
    try:
        info = client.get_task_info(
            course_instance_id, task_id, version, control.user.open_id
        )
        state = lenient_obj(lenient_obj(info.get("data")).get("state"))
        extend = lenient_obj(state.get("__EXTEND_DATA__"))
        answer_list = lenient_obj(lenient_obj(extend.get("__SUMMARY__")).get("answerList"))
        has_objective = any(
            as_int(lenient_obj(item).get("questionType")) in (1, 3)
            for item in answer_list.values()
        )
    except Exception as exc:
        logger.warning("Failed to check zero score for task %s: %s", task_id, exc)
        return

    if not has_objective:
        return

    message = (
        f"任务 {task_id} 本次得分为 0，为防止继续产生 0 分，任务已自动暂停。\n"
        "可能原因：未知新题型、答案或判分逻辑变化。\n"
        "请到 U校园后台核对该题目后，再手动恢复运行。"
    )
    logger.warning(message)
    control.warn(message)
    control.suspend()


def _refresh_progress(control, client, resource_id: int) -> None:
    try:
        data = client.get_course_list()
        courses = lenient_obj(data.get("value")).get("courseList")
        if not isinstance(courses, list):
            return
        for course in courses:
            for resource in lenient_obj(course).get("courseResourceList") or []:
                entry = lenient_obj(resource)
                if as_int(entry.get("id")) == resource_id:
                    control.set_progress(
                        as_int(entry.get("finishPointNum")),
                        as_int(entry.get("totalPointNum")),
                    )
                    return
    except TaskStopped:
        raise
    except Exception as exc:
        logger.warning("Failed to refresh course progress: %s", exc)
