from unipus_web.core.answer import extract_answers, parse_answers
from unipus_web.core.course_detail import QuestionType
from unipus_web.core.unit_situation import UnitSituation


def test_unit_situation_indexes_nested_nodes():
    payload = {
        "code": 1,
        "success": True,
        "value": {
            "list": [
                {
                    "nodeId": "u",
                    "role": "unit",
                    "children": [
                        {
                            "nodeId": "",
                            "role": "section",
                            "children": [
                                {
                                    "nodeId": "t",
                                    "role": "link",
                                    "finishProgress": 50,
                                    "path": "u/s/t",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }
    situation = UnitSituation.parse(payload)
    assert situation.get_node_by_node_id("t").finish_progress == 50
    assert situation.get_node_by_node_id("") is None
    assert situation.get_node_by_path("u/s/t").node_id == "t"


def test_answer_parsing_and_extraction():
    raw = (
        '[{"id": 11, "answer": "{\\"children\\":[{\\"answers\\":[\\"A\\"]},'
        '{\\"answers\\":[\\"B\\"]}]}", "analysis": "{\\"children\\":'
        '[{\\"analysis\\":\\"why\\"}]}"}]'
    )
    answers = parse_answers(raw)
    assert answers[0].id == 11
    assert extract_answers(answers[0], QuestionType.SINGLE_CHOICE) == ["A", "B"]
    assert extract_answers(answers[0], QuestionType.SHORT_ANSWER) == ["why"]
    assert extract_answers(answers[0], QuestionType.TEXT_LEARN) == []


def test_answer_parsing_tolerates_bad_input():
    assert parse_answers("[]") == []
    assert parse_answers("not json") == []
    assert parse_answers(None) == []
