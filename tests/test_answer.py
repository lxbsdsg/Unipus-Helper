import json

from unipus_web.core.answer import extract_answers, parse_answers
from unipus_web.core.course_detail import QuestionType
from unipus_web.core.submit import create_submit_body


def test_empty_answer_slots_are_preserved_for_submission_count():
    answer_json = json.dumps(
        [
            {
                "id": 1262939522850193408,
                "answer": json.dumps(
                    {"children": [{"answers": []} for _ in range(10)]}
                ),
            }
        ]
    )

    records = parse_answers(answer_json)
    assert len(records) == 1
    assert records[0].answers == []
    assert records[0].answer_slots == [""] * 10

    values = extract_answers(records[0], QuestionType.BASIC_SCOOP_CONTENT)
    assert values == [""] * 10

    body = json.loads(
        create_submit_body(
            [records[0].id],
            [values],
            "6b815494600090b",
            "course-v2:test",
            "open-id",
            [QuestionType.BASIC_SCOOP_CONTENT],
        )
    )
    inner = json.loads(body["quesDatas"][0]["answer"])
    assert len(inner["children"]) == 10
    expected_child = {"value": [""], "isDone": True}
    assert all(child == expected_child for child in inner["children"])
    assert body["isCompleted"] == [True] * 10
    assert len(json.loads(body["thirdPartyJudges"])) == 10


def test_translation_still_falls_back_to_analysis_for_empty_answer_arrays():
    answer_json = json.dumps(
        [
            {
                "id": 12,
                "answer": json.dumps(
                    {"children": [{"answers": []}, {"answers": []}]}
                ),
                "analysis": json.dumps(
                    {"children": [{"analysis": "answer one"}, {"analysis": "answer two"}]}
                ),
            }
        ]
    )

    records = parse_answers(answer_json)

    assert extract_answers(records[0], QuestionType.TRANSLATION) == [
        "answer one",
        "answer two",
    ]


def test_video_popup_does_not_turn_empty_answer_arrays_into_blank_choices():
    answer_json = json.dumps(
        [
            {
                "id": 13,
                "answer": json.dumps(
                    {"children": [{"answers": []}, {"answers": []}]}
                ),
            }
        ]
    )

    records = parse_answers(answer_json)

    assert extract_answers(records[0], QuestionType.VIDEO_POPUP) == []
