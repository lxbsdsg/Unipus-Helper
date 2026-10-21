import json

from unipus_web.core.course_detail import CourseDetail, QuestionType

COURSE = {
    "name": "大英",
    "type": "general",
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
                    "name": "Listening",
                    "url": "x",
                    "ref-out": "y",
                    "question_num": 3,
                    "base": "single-choice",
                    "tab_type": "text",
                    "linkType": "task",
                }
            ],
        }
    ],
}


def test_parses_tree_and_question_types():
    course = CourseDetail.from_json(COURSE)
    assert course.get_node("t1").name == "Listening"
    assert course.get_question_types("t1") == [QuestionType.SINGLE_CHOICE]
    # 索引越界时回落到最后一个已知题型，而不是崩溃
    assert course.get_question_type("t1", 2) == QuestionType.SINGLE_CHOICE


def test_unknown_base_maps_to_unknown():
    data = json.loads(json.dumps(COURSE))
    data["units"][0]["children"][0]["base"] = "brand-new-type"
    assert CourseDetail.from_json(data).get_question_types("t1") == [
        QuestionType.UNKNOWN
    ]


def test_task_times_read_from_strategies_level():
    course = CourseDetail.from_json(COURSE)
    payload = {
        "code": 0,
        "rt": {
            "leafs": {
                "t1": {
                    "duration": 0,
                    "strategies": {"start_time": 100, "end_time": 200},
                }
            }
        },
    }
    assert course.init_task_times(payload) is True
    assert course.get_task_start("t1") == 100
    assert course.get_task_end("t1") == 200


def test_task_times_fallback_to_leaf_level():
    course = CourseDetail.from_json(COURSE)
    course.init_task_times({"rt": {"leafs": {"t1": {"start_time": 5, "end_time": 6}}}})
    assert course.get_task_start("t1") == 5


def test_missing_times_use_defaults():
    course = CourseDetail.from_json(COURSE)
    course.init_task_times({"rt": {"leafs": {}}})
    assert course.get_task_start("nope") == 0
    assert course.get_task_end("nope") == 32503651200


def test_section_nodes_do_not_require_url():
    data = json.loads(json.dumps(COURSE))
    data["units"][0]["children"].insert(
        0,
        {"id": "s1", "role": "section", "caption": "", "name": "Preview"},
    )
    course = CourseDetail.from_json(data)
    assert course.get_node("s1").role.value == "section"
