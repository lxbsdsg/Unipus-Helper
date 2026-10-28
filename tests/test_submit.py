import json

import pytest

from unipus_web.core.course_detail import QuestionType
from unipus_web.core.learn import SubmitThrottle
from unipus_web.core.submit import create_submit_body


def test_submit_throttle_allows_five_then_requests_a_wait():
    now = [1000.0]
    throttle = SubmitThrottle(max_per_minute=5, clock=lambda: now[0])

    for _ in range(5):
        assert throttle.wait_ms() == 0
        throttle.record()
        now[0] += 1

    assert throttle.wait_ms() > 0

    now[0] += 61
    assert throttle.wait_ms() == 0


def test_single_question_body_matches_contract():
    body = json.loads(
        create_submit_body([11], [["A"]], "g", "c", "o", [QuestionType.SINGLE_CHOICE])
    )
    q = body["quesDatas"][0]
    assert q["instanceId"] == "11"
    assert q["contextVersion"] == 0
    inner = json.loads(q["answer"])
    assert inner["children"] == [{"value": ["A"], "isDone": True}]
    assert body["submitType"] == 1
    assert body["thirdPartyJudges"] != "[]"
    judges = json.loads(body["thirdPartyJudges"])
    assert judges[0]["payloads"][0]["recordDetail"]["score"] == 100.0


def test_preset_mode_body_has_no_quesdatas():
    body = json.loads(
        create_submit_body([0], [[]], "g", "c", "o", [QuestionType.TEXT_LEARN])
    )
    assert body["quesDatas"] == []
    assert body["submitType"] == 2
    assert body["hideLoading"] is True


def test_video_popup_body_records_watched_progress_and_merged_answers():
    body = json.loads(
        create_submit_body(
            [42],
            [["A", "B", "C", "D"]],
            "g",
            "c",
            "o",
            [QuestionType.VIDEO_POPUP],
        )
    )

    question = body["quesDatas"][0]
    answer = json.loads(question["answer"])
    assert question["contextVersion"] == 1
    assert question["answerVersion"] == 1
    assert answer["children"] == [
        {"value": ["A", "B", "C", "D"], "isDone": True}
    ]
    assert answer["progress"] == {"0": True}
    assert body["submitType"] == 1
    assert body["isCompleted"] == [True]

    judges = json.loads(body["thirdPartyJudges"])
    assert judges == [
        {
            "value": "A,B,C,D",
            "question_type": "video-popup",
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
    ]


def test_multi_question_body_has_course_answer_map():
    body = json.loads(
        create_submit_body(
            [1, 2],
            [["A"], ["B"]],
            "g",
            "c",
            "o",
            [QuestionType.SINGLE_CHOICE, QuestionType.MATERIAL_BANKED_CLOZE],
        )
    )
    assert len(body["quesDatas"]) == 2
    assert set(body["quesDatas"][0]["courseAnswerMap"]) == {"1", "2"}
    assert body["quesDatas"][0]["courseAnswer"]["isRight"] == [True]


def test_multi_question_answers_are_not_shared_or_accumulated():
    body = json.loads(
        create_submit_body(
            [1, 2],
            [["A"], ["B", "C"]],
            "g",
            "c",
            "o",
            [QuestionType.SINGLE_CHOICE, QuestionType.SINGLE_CHOICE],
        )
    )
    a1 = json.loads(body["quesDatas"][0]["answer"])
    a2 = json.loads(body["quesDatas"][1]["answer"])
    assert [c["value"] for c in a1["children"]] == [["A"]]
    assert [c["value"] for c in a2["children"]] == [["B"], ["C"]]


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        create_submit_body(
            [1, 2], [["A"]], "g", "c", "o", [QuestionType.SINGLE_CHOICE] * 2
        )
