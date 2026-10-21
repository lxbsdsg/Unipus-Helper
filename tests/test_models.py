from unipus_web.models import (
    Course,
    CourseResource,
    as_bool,
    as_float,
    as_int,
    lenient_obj,
)


def test_lenient_obj_accepts_string_encoded_json():
    assert lenient_obj('{"a": 1}') == {"a": 1}
    assert lenient_obj("not json") == {}
    assert lenient_obj(None) == {}
    assert lenient_obj({"a": 1}) == {"a": 1}


def test_scalar_coercion_survives_empty_strings():
    assert as_int("", 7) == 7
    assert as_int("12", 0) == 12
    assert as_int(None, 0) == 0
    assert as_float("1.5", 0.0) == 1.5
    assert as_float("abc", 2.0) == 2.0
    assert as_bool("true", False) is True
    assert as_bool("false", True) is False
    assert as_bool("", True) is True


def test_course_resource_from_json_uses_defaults():
    r = CourseResource.from_json({"id": "123", "strategyId": "", "finishPointNum": None})
    assert r.id == 123
    assert r.strategy_id == 0
    assert r.finish_point_num == 0


def test_course_from_json_handles_missing_resources():
    c = Course.from_json({"id": 1, "name": "大英", "courseResourceList": None})
    assert c.name == "大英"
    assert c.resources == []


def test_course_to_dict_roundtrip():
    c = Course.from_json(
        {
            "id": 1,
            "name": "大英",
            "startTime": 10,
            "endTime": 20,
            "courseResourceList": [{"id": 7, "name": "读写", "totalPointNum": 9}],
        }
    )
    d = c.to_dict()
    assert d["resources"][0]["id"] == 7
    assert d["resources"][0]["total_point_num"] == 9
