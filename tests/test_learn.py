import json

from unipus_web.core.learn import (
    build_catalog,
    learn_course,
    learn_selected_tasks,
    load_course_context,
)
from unipus_web.models import CourseResource


class FakeUser:
    app_user_id = "a"
    sso_id = "s"
    open_id = "o"


class FakeControl:
    def __init__(self):
        self.descriptions = []
        self.statuses = []
        self.progress = []
        self.warnings = []
        self.stop_requested = False
        self.user = FakeUser()

    def checkpoint(self):
        pass

    def set_description(self, text):
        self.descriptions.append(text)

    def set_progress(self, completed, total):
        self.progress.append((completed, total))

    def set_status(self, status):
        self.statuses.append(status)

    def wait_for_cooldown(self, ms, waiting_desc, after_desc):
        pass

    def suspend(self):
        pass

    def warn(self, message):
        self.warnings.append(message)


class FakeClient:
    def __init__(self, units_json=None, total_progress=100, unit_list=None,
                 required=None, unit_situation=None, answer_json="[]",
                 course_list=None):
        self.units_json = units_json or '{"name":"c","units":[]}'
        self.total_progress = total_progress
        self.unit_list = unit_list or []
        self.required = required or []
        self.unit_situation = unit_situation or {"value": {"list": []}}
        self.answer_json = answer_json
        self.course_list = course_list or []
        self.time_payload = {"rt": {"leafs": {}}}
        self.submitted_body = None

    def get_course_resource_info(self, resource_id):
        return {
            "success": True,
            "value": {
                "courseResource": {
                    "courseName": "c",
                    "courseResourceId": 1,
                    "resourceId": "r",
                    "courseInstanceId": "ci",
                    "strategyId": 7,
                    "tutorial": {"resourceName": "book"},
                }
            },
        }

    def get_all_tasks(self, course_instance_id):
        return {"code": 0, "course": self.units_json}

    def get_required_part(self, strategy_id, course_resource_id):
        return {
            "success": True,
            "value": {"courseUnitStrategyList": self.required},
        }

    def get_total_and_unit_situation(self, resource_id, app_user_id):
        return {
            "success": True,
            "value": {
                "totalDetail": {"finishProgress": self.total_progress},
                "unitList": self.unit_list,
            },
        }

    def get_task_time_info(self, *args):
        return self.time_payload

    def get_unit_task_situation(self, *args):
        return self.unit_situation

    def get_answer(self, *args):
        return {"code": 0, "data": self.answer_json, "k": ""}

    def submit(self, body, open_id):
        self.submitted_body = body
        return {"code": 0, "data": {"version": "v", "state": {"score_avg": 100}}}

    def get_task_info(self, *args):
        return {
            "code": 0,
            "data": {"state": {"__EXTEND_DATA__": {"__SUMMARY__": {"answerList": {}}}}},
        }

    def get_course_list(self):
        return {"success": True, "value": {"courseList": self.course_list}}


def test_returns_completed_when_total_progress_is_100():
    control = FakeControl()
    summary = learn_course(control, FakeClient(), CourseResource(id=1))
    assert summary.submitted_tasks == 0
    assert summary.skipped_tasks == 0


def test_missing_node_is_skipped_with_warning_not_crash():
    units = {
        "name": "c",
        "units": [
            {
                "id": "u1",
                "role": "unit",
                "caption": "Unit 1",
                "name": "Unit 1",
                "children": [
                    {
                        "id": "t1",
                        "role": "link",
                        "caption": "",
                        "name": "Task 1",
                        "url": "x",
                        "ref-out": "y",
                        "question_num": 1,
                        "base": "single-choice",
                        "tab_type": "text",
                        "linkType": "task",
                    }
                ],
            }
        ],
    }
    client = FakeClient(
        units_json=json.dumps(units),
        total_progress=0,
        unit_list=[
            {"nodeId": "u1", "caption": "Unit 1", "name": "Unit 1", "finishProgress": 0}
        ],
        required=[{"unitId": "u1", "requiredTask": ["t1"]}],
        unit_situation={"value": {"list": []}},
    )
    control = FakeControl()
    summary = learn_course(control, client, CourseResource(id=1))
    assert summary.skipped_tasks >= 1
    assert any("缺失" in warning for warning in control.warnings)


def test_unsupported_type_is_skipped():
    units = {
        "name": "c",
        "units": [
            {
                "id": "u1",
                "role": "unit",
                "caption": "Unit 1",
                "name": "Unit 1",
                "children": [
                    {
                        "id": "t1",
                        "role": "link",
                        "caption": "",
                        "name": "Discussion",
                        "url": "x",
                        "ref-out": "y",
                        "question_num": 1,
                        "base": "discussion",
                        "tab_type": "text",
                        "linkType": "task",
                    }
                ],
            }
        ],
    }
    client = FakeClient(
        units_json=json.dumps(units),
        total_progress=0,
        unit_list=[
            {"nodeId": "u1", "caption": "Unit 1", "name": "Unit 1", "finishProgress": 0}
        ],
        required=[{"unitId": "u1", "requiredTask": ["t1"]}],
        unit_situation={
            "value": {
                "list": [
                    {
                        "nodeId": "u1",
                        "role": "unit",
                        "children": [
                            {"nodeId": "t1", "role": "link", "finishProgress": 0}
                        ],
                    }
                ]
            }
        },
    )
    summary = learn_course(FakeControl(), client, CourseResource(id=1))
    assert summary.skipped_tasks == 1
    assert any("discussion" in reason.lower() for reason in summary.skipped_reasons)


def test_multi_question_answers_are_submitted_independently_and_progress_refreshed():
    units = {
        "name": "c",
        "units": [
            {
                "id": "u1",
                "role": "unit",
                "caption": "Unit 1",
                "name": "Unit 1",
                "children": [
                    {
                        "id": "t1",
                        "role": "link",
                        "caption": "",
                        "name": "Two questions",
                        "url": "x",
                        "ref-out": "y",
                        "question_num": 2,
                        "base": "single-choice",
                        "tab_type": "text",
                        "linkType": "task",
                    }
                ],
            }
        ],
    }
    answer_json = json.dumps(
        [
            {"id": 11, "answer": json.dumps({"children": [{"answers": ["A"]}]})},
            {"id": 12, "answer": json.dumps({"children": [{"answers": ["B"]}]})},
        ]
    )
    client = FakeClient(
        units_json=json.dumps(units),
        total_progress=0,
        unit_list=[
            {"nodeId": "u1", "caption": "Unit 1", "name": "Unit 1", "finishProgress": 0}
        ],
        required=[{"unitId": "u1", "requiredTask": ["t1"]}],
        unit_situation={
            "value": {
                "list": [
                    {
                        "nodeId": "u1",
                        "role": "unit",
                        "children": [
                            {"nodeId": "t1", "role": "link", "finishProgress": 0}
                        ],
                    }
                ]
            }
        },
        answer_json=answer_json,
        course_list=[
            {
                "id": 1,
                "courseResourceList": [
                    {"id": 1, "finishPointNum": 3, "totalPointNum": 4}
                ],
            }
        ],
    )
    control = FakeControl()
    summary = learn_course(control, client, CourseResource(id=1))

    assert summary.submitted_tasks == 1
    assert control.progress == [(3, 4)]

    body = json.loads(client.submitted_body)
    assert len(body["quesDatas"]) == 2
    first = json.loads(body["quesDatas"][0]["answer"])
    second = json.loads(body["quesDatas"][1]["answer"])
    assert [c["value"] for c in first["children"]] == [["A"]]
    assert [c["value"] for c in second["children"]] == [["B"]]


CATALOG_UNITS = {
    "name": "c",
    "units": [
        {
            "id": "u1",
            "role": "unit",
            "caption": "Unit 1",
            "name": "Unit 1",
            "children": [
                {
                    "id": "t1",
                    "role": "link",
                    "name": "Listening",
                    "url": "x",
                    "ref-out": "y",
                    "question_num": 1,
                    "base": "single-choice",
                    "tab_type": "text",
                    "linkType": "task",
                },
                {
                    "id": "t2",
                    "role": "link",
                    "name": "Reading",
                    "url": "x",
                    "ref-out": "y",
                    "question_num": 1,
                    "base": "single-choice",
                    "tab_type": "text",
                    "linkType": "task",
                },
                {
                    "id": "t3",
                    "role": "link",
                    "name": "Discuss",
                    "url": "x",
                    "ref-out": "y",
                    "question_num": 1,
                    "base": "discussion",
                    "tab_type": "text",
                    "linkType": "task",
                },
            ],
        }
    ],
}


def make_catalog_client(answer_json="[]"):
    return FakeClient(
        units_json=json.dumps(CATALOG_UNITS),
        required=[{"unitId": "u1", "requiredTask": ["t1"]}],
        unit_situation={
            "value": {
                "list": [
                    {
                        "nodeId": "u1",
                        "role": "unit",
                        "children": [
                            {"nodeId": "t1", "role": "link", "finishProgress": 0},
                            {"nodeId": "t2", "role": "link", "finishProgress": 100},
                            {"nodeId": "t3", "role": "link", "finishProgress": 0},
                        ],
                    }
                ]
            }
        },
        answer_json=answer_json,
    )


def test_build_catalog_merges_progress_and_required_flags():
    client = make_catalog_client()
    control = FakeControl()
    context = load_course_context(control, client, CourseResource(id=1))
    catalog = build_catalog(control, client, context)

    leaves = {node["id"]: node for node in catalog["tree"]["units"][0]["children"]}
    assert leaves["t1"]["required"] is True
    assert leaves["t1"]["selectable"] is True
    assert leaves["t2"]["required"] is False
    assert leaves["t2"]["finish_progress"] == 100.0
    assert leaves["t2"]["selectable"] is False
    # discussion 属于不支持题型，可展示但不可选
    assert leaves["t3"]["answerable"] is False
    assert leaves["t3"]["selectable"] is False
    assert leaves["t1"]["status_known"] is True
    assert leaves["t2"]["status_known"] is True


def test_learn_selected_tasks_only_submits_unfinished_selection():
    answer_json = json.dumps(
        [
            {
                "id": 11,
                "answer": json.dumps({"children": [{"answers": ["A"]}]}),
            }
        ]
    )
    client = make_catalog_client(answer_json=answer_json)
    control = FakeControl()
    context = load_course_context(control, client, CourseResource(id=1))

    summary = learn_selected_tasks(
        control,
        client,
        context,
        ["t1", "t2", "missing"],
        progress={"t1": 0.0, "t2": 100.0, "t3": 0.0},
    )

    assert summary.submitted_tasks == 1
    assert summary.skipped_tasks == 2
    assert any("已完成" in reason for reason in summary.skipped_reasons)
    assert any("缺少节点" in reason for reason in summary.skipped_reasons)
    body = json.loads(client.submitted_body)
    assert len(body["quesDatas"]) == 1


def _single_leaf_client(base="single-choice", question_num=1):
    units = {
        "name": "c",
        "units": [
            {
                "id": "u1",
                "role": "unit",
                "caption": "Unit 1",
                "name": "Unit 1",
                "children": [
                    {
                        "id": "t1",
                        "role": "link",
                        "name": "Task",
                        "url": "x",
                        "ref-out": "y",
                        "question_num": question_num,
                        "base": base,
                        "tab_type": "text",
                        "linkType": "task",
                    }
                ],
            }
        ],
    }
    return FakeClient(
        units_json=json.dumps(units),
        unit_situation={
            "value": {
                "list": [
                    {
                        "nodeId": "u1",
                        "role": "unit",
                        "children": [
                            {"nodeId": "t1", "role": "link", "finishProgress": 0}
                        ],
                    }
                ]
            }
        },
    )


def test_catalog_marks_mixed_type_task_unselectable():
    client = _single_leaf_client(base="single-choice,translation")
    control = FakeControl()
    context = load_course_context(control, client, CourseResource(id=1))
    catalog = build_catalog(control, client, context)
    leaf = catalog["tree"]["units"][0]["children"][0]
    assert leaf["answerable"] is False
    assert leaf["selectable"] is False


def test_catalog_respects_multi_question_flag():
    client = _single_leaf_client(question_num=2)
    control = FakeControl()
    context = load_course_context(control, client, CourseResource(id=1))

    disabled = build_catalog(
        control, client, context, allow_multi_question=False
    )
    assert disabled["tree"]["units"][0]["children"][0]["selectable"] is False

    enabled = build_catalog(control, client, context)
    assert enabled["tree"]["units"][0]["children"][0]["selectable"] is True


def test_catalog_marks_unknown_status_when_unit_progress_fails():
    client = _single_leaf_client()
    client.unit_situation = {"success": False, "value": {}}
    control = FakeControl()
    context = load_course_context(control, client, CourseResource(id=1))
    catalog = build_catalog(control, client, context)
    leaf = catalog["tree"]["units"][0]["children"][0]
    assert leaf["status_known"] is False
    assert leaf["selectable"] is False


def test_catalog_marks_missing_leaf_status_unknown():
    client = _single_leaf_client()
    client.unit_situation = {
        "success": True,
        "value": {"list": [{"nodeId": "u1", "role": "unit", "children": []}]},
    }
    control = FakeControl()
    context = load_course_context(control, client, CourseResource(id=1))
    catalog = build_catalog(control, client, context)
    leaf = catalog["tree"]["units"][0]["children"][0]
    assert leaf["status_known"] is False
    assert leaf["selectable"] is False


def test_learn_selected_tasks_respects_task_time_window():
    import time

    answer_json = json.dumps(
        [{"id": 11, "answer": json.dumps({"children": [{"answers": ["A"]}]})}]
    )
    client = make_catalog_client(answer_json=answer_json)
    now = int(time.time())
    client.time_payload = {
        "rt": {
            "leafs": {
                "t1": {"strategies": {"start_time": now + 3600, "end_time": now + 7200}}
            }
        }
    }
    control = FakeControl()
    context = load_course_context(control, client, CourseResource(id=1))

    summary = learn_selected_tasks(
        control, client, context, ["t1"], progress={"t1": 0.0}
    )

    assert summary.submitted_tasks == 0
    assert any("不在学习时间" in reason for reason in summary.skipped_reasons)
