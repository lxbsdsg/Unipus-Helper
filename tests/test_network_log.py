import json

from unipus_web.network_log import NetworkRecorder, redact_record


def test_recorder_assigns_sequence_and_queries_incrementally():
    recorder = NetworkRecorder(capacity=3)
    for i in range(4):
        recorder.add({"url": f"u{i}", "request_payload": None, "response_body": None})
    assert [r["seq"] for r in recorder.query()] == [2, 3, 4]
    assert [r["url"] for r in recorder.query(after_seq=3)] == ["u3"]


def test_recorder_notifies_listener():
    seen = []
    recorder = NetworkRecorder()
    recorder.set_listener(seen.append)
    recorder.add({"url": "u"})
    assert seen[0]["url"] == "u"


def test_redact_record_masks_password_in_payload():
    record = {
        "request_payload": json.dumps({"username": "u", "password": "p"}),
        "request_headers": {"Cookie": "a=b"},
    }
    masked = redact_record(record)
    assert "p" not in json.loads(masked["request_payload"])["password"]
    assert masked["request_headers"]["Cookie"] == "<redacted>"


def test_redact_record_hides_login_and_userinfo_response_bodies():
    login = redact_record(
        {
            "url": "https://sso.unipus.cn/sso/0.1/sso/login",
            "response_body": json.dumps({"rs": {"jwt": "secret-jwt"}}),
        }
    )
    assert "secret-jwt" not in login["response_body"]

    userinfo = redact_record(
        {
            "url": "https://uai.unipus.cn/api/account/user/info",
            "response_body": json.dumps({"value": {"userInfo": {"name": "张三"}}}),
        }
    )
    assert "张三" not in userinfo["response_body"]
