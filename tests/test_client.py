import json

import httpx
import pytest

from unipus_web.api.client import UnipusClient
from unipus_web.api.errors import ApiError, AuthError, NetworkError
from unipus_web.network_log import redact_headers


def make_client(handler, records=None):
    recorder = records.append if records is not None else None
    client = UnipusClient("task-test", record=recorder)
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    )
    return client


def test_login_posts_expected_body_and_returns_rs():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"code": "0", "rs": {"openid": "o1", "jwt": "j1", "username": "u1"}},
        )

    rs = make_client(handler).login("u1", "p1")
    assert seen["url"] == "https://sso.unipus.cn/sso/0.1/sso/login"
    assert seen["body"] == {
        "username": "u1",
        "password": "p1",
        "remember": True,
        "agreement": True,
        "service": "https://uai.unipus.cn/home",
    }
    assert rs["openid"] == "o1"


def test_login_without_rs_raises_auth_error():
    client = make_client(
        lambda r: httpx.Response(200, json={"code": "1", "msg": "密码错误"})
    )
    with pytest.raises(AuthError, match="密码错误"):
        client.login("u1", "bad")


def test_non_json_response_raises_api_error():
    client = make_client(lambda r: httpx.Response(502, text="<html>bad gateway</html>"))
    with pytest.raises(ApiError):
        client.get_course_list()


def test_transport_error_raises_network_error():
    def handler(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    client = make_client(handler)
    with pytest.raises(NetworkError) as excinfo:
        client.get_course_list()
    assert "网络" in str(excinfo.value)


def test_record_contains_method_status_and_url():
    records = []
    client = make_client(
        lambda r: httpx.Response(200, json={"success": True}), records
    )
    client.get_course_list()
    assert records[0]["method"] == "GET"
    assert records[0]["status_code"] == 200
    assert records[0]["url"].endswith("/api/cmgt/course/getCourseListByStudent")
    assert records[0]["task_id"] == "task-test"


def test_record_keeps_going_when_hook_fails():
    def broken(_record):
        raise RuntimeError("hook exploded")

    client = UnipusClient("t", record=broken)
    client._client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    assert client.get_course_list() == {}


def test_answer_request_carries_annotator_token():
    seen = {}

    def handler(request):
        seen["token"] = request.headers.get("x-annotator-auth-token")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"code": 0, "data": "x", "k": "y"})

    make_client(handler).get_answer("course-v2:abc+def", "task1", "openid")
    assert seen["token"].count(".") == 2
    assert "/course/api/v3/answer/course-v2:abc+def/task1/default" in seen["url"]


def test_redact_headers_is_case_insensitive():
    masked = redact_headers({"Authorization": "Bearer x", "User-Agent": "ua", "cookie": "c=1"})
    assert masked["Authorization"] == "<redacted>"
    assert masked["cookie"] == "<redacted>"
    assert masked["User-Agent"] == "ua"
