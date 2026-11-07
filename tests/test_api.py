import json
import time

import pytest
from fastapi.testclient import TestClient

from unipus_web.app import create_app


class FakeClient:
    def login(self, username, password):
        return {"openid": "o", "jwt": "j", "username": username}

    def get_user_info(self):
        return {
            "success": True,
            "value": {"userInfo": {"name": "张三", "schName": "学校", "appUserId": "a", "ssoId": "s"}},
        }

    def get_course_list(self):
        return {
            "success": True,
            "value": {
                "courseList": [
                    {
                        "id": 1,
                        "name": "课程",
                        "startTime": 0,
                        "endTime": 4102444800000,
                        "courseResourceList": [
                            {
                                "id": 11,
                                "name": "教程",
                                "resourceId": "res",
                                "instanceId": "ci",
                                "strategyId": 7,
                            }
                        ],
                    }
                ]
            },
        }

    def get_course_resource_info(self, resource_id):
        return {
            "success": True,
            "value": {
                "courseResource": {
                    "courseName": "课程",
                    "courseResourceId": 11,
                    "courseInstanceId": "ci",
                    "strategyId": 7,
                }
            },
        }

    def get_all_tasks(self, course_instance_id):
        return {
            "code": 0,
            "course": {
                "name": "课程",
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
                            }
                        ],
                    }
                ],
            },
        }

    def get_required_part(self, strategy_id, course_resource_id):
        return {
            "success": True,
            "value": {
                "courseUnitStrategyList": [
                    {"unitId": "u1", "requiredTask": ["t1"]}
                ]
            },
        }

    def get_unit_task_situation(self, *args):
        return {
            "success": True,
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
            },
        }

    def get_answer(self, *args):
        return {"code": 0, "data": "[]", "k": ""}

    def close(self):
        pass

    def export_login_session(self):
        return {"version": 1, "login_result": {"openid": "o"}, "cookies": []}


def make_client():
    app = create_app(testing=True)
    app.state.manager.client_factory = lambda tid: FakeClient()
    return TestClient(app)


class TwoTargetClient(FakeClient):
    """同一单元下两个可计时叶子，用于触发时长内容选择流程。"""

    def get_all_tasks(self, course_instance_id):
        payload = super().get_all_tasks(course_instance_id)
        unit = payload["course"]["units"][0]
        unit["children"] = [
            dict(unit["children"][0], id="t1", name="Reading 1"),
            dict(unit["children"][0], id="t2", name="Reading 2"),
        ]
        return payload


def make_two_target_client():
    app = create_app(testing=True)
    app.state.manager.client_factory = lambda tid: TwoTargetClient()
    return TestClient(app)


def test_index_and_empty_snapshot():
    client = make_client()
    assert client.get("/").status_code == 200
    assert client.get("/api/tasks").json() == []


def test_add_task_returns_accepted_snapshot():
    client = make_client()
    response = client.post("/api/tasks", json={"username": "u", "password": "p"})
    assert response.status_code == 202
    assert response.json()["status"] in {"INITIALIZING", "READY", "ERROR"}


def test_add_task_requires_username_or_credential():
    client = make_client()
    assert client.post("/api/tasks", json={}).status_code == 422
    assert client.post("/api/tasks", json={"password": "p"}).status_code == 422


def test_duration_target_validation():
    client = make_client()
    created = client.post("/api/tasks", json={"username": "u", "password": "p"})
    task_id = created.json()["id"]
    task = client.app.state.manager._wait_ready(task_id)
    assert task is not None
    # READY 状态（未进入选择计时内容）时，选择接口一律 409
    assert client.post(
        f"/api/tasks/{task_id}/duration/choose",
        json={"target_id": " ", "duration": "30"},
    ).status_code == 409
    assert client.post(
        f"/api/tasks/{task_id}/duration/choose",
        json={"target_ids": [" ", ""], "duration": "30"},
    ).status_code == 409
    # /duration 只负责进入时长模式（课程/内容/时长随后选择），不再校验时长
    assert client.post(f"/api/tasks/{task_id}/duration", json={}).status_code == 202
    # 即使只有 1 个计时内容，也必须进入选择界面让用户设置时长
    deadline = time.time() + 3
    while time.time() < deadline and task.status.value != "NEED_OPERATION":
        time.sleep(0.02)
    assert task.status.value == "NEED_OPERATION"
    assert task.user_operation.value == "CHOOSE_DURATION"
    # 空目标在 CHOOSE_DURATION 状态下返回 400
    assert client.post(
        f"/api/tasks/{task_id}/duration/choose",
        json={"target_ids": [" "], "duration": "30"},
    ).status_code == 400


def test_duration_choose_validates_targets_and_duration():
    client = make_two_target_client()
    created = client.post("/api/tasks", json={"username": "u", "password": "p"})
    task_id = created.json()["id"]
    task = client.app.state.manager._wait_ready(task_id)
    assert task is not None

    assert client.post(f"/api/tasks/{task_id}/duration", json={}).status_code == 202
    deadline = time.time() + 3
    while time.time() < deadline and task.status.value != "NEED_OPERATION":
        time.sleep(0.02)
    assert task.status.value == "NEED_OPERATION"
    assert task.user_operation.value == "CHOOSE_DURATION"
    ids = [target["group_id"] for target in task.snapshot()["duration_targets"]]
    assert len(ids) == 2

    # 非法时长与未知内容都会被拒绝
    assert client.post(
        f"/api/tasks/{task_id}/duration/choose",
        json={"target_ids": [ids[0]], "duration": "10,5"},
    ).status_code == 400
    assert client.post(
        f"/api/tasks/{task_id}/duration/choose",
        json={"target_ids": ["nope"], "duration": "30"},
    ).status_code == 400

    # 合法请求进入计时并回到 RUNNING
    assert client.post(
        f"/api/tasks/{task_id}/duration/choose",
        json={"target_ids": ids, "duration": "10,30"},
    ).status_code == 204
    assert task.snapshot()["duration_param"] == "10,30"


def test_bad_host_header_is_rejected():
    client = make_client()
    response = client.get("/", headers={"host": "evil.example"})
    assert response.status_code == 400


def test_credentials_never_return_password():
    client = make_client()
    created = client.post(
        "/api/credentials", json={"username": "u", "password": "p"}
    )
    assert created.status_code == 201
    body = client.get("/api/credentials").text
    assert "password" not in body
    assert '"p"' not in body


def test_add_credential_can_capture_ready_task_login_session():
    client = make_client()
    task_id = client.post(
        "/api/tasks", json={"username": "u", "password": "p"}
    ).json()["id"]
    task = client.app.state.manager._wait_ready(task_id, timeout=2)
    assert task is not None

    response = client.post(
        "/api/credentials",
        json={"username": "u", "password": "p", "task_id": task_id},
    )

    assert response.status_code == 201
    credential_id = response.json()["id"]
    assert client.app.state.credentials.get_login_session(credential_id)["version"] == 1
    assert "session" not in client.get("/api/credentials").text


def test_report_download_headers():
    client = make_client()
    response = client.post("/api/report")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]


def test_unknown_task_returns_404():
    client = make_client()
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.post("/api/tasks/nope/start").status_code == 404
    assert client.delete("/api/tasks/nope").status_code == 404


def test_task_lifecycle_endpoints(tmp_path):
    client = make_client()
    task_id = client.post(
        "/api/tasks", json={"username": "u", "password": "p"}
    ).json()["id"]
    for action in ("start", "pause", "resume", "stop"):
        assert client.post(f"/api/tasks/{task_id}/{action}").status_code == 200
    assert client.delete(f"/api/tasks/{task_id}").status_code == 204


def test_logs_and_network_are_incremental():
    client = make_client()
    assert client.get("/api/logs").json() == []
    assert client.get("/api/network").json() == []


def test_websocket_network_events_are_redacted():
    import json

    client = make_client()
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "snapshot"

        client.app.state.network.add(
            {
                "method": "POST",
                "url": "https://sso.unipus.cn/sso/0.1/sso/login",
                "request_headers": {"Cookie": "session=abc"},
                "request_payload": json.dumps(
                    {"username": "u", "password": "secret-pw"}
                ),
                "response_body": json.dumps({"rs": {"jwt": "secret-jwt"}}),
            }
        )

        event = ws.receive_json()
        assert event["type"] == "network.append"
        payload = json.dumps(event["data"])
        assert "secret-pw" not in payload
        assert "secret-jwt" not in payload
        assert event["data"]["request_headers"]["Cookie"] == "<redacted>"


def test_restart_endpoint_recovers_an_error_task():
    client = make_client()
    task_id = client.post(
        "/api/tasks", json={"username": "u", "password": "p"}
    ).json()["id"]
    client.app.state.manager._wait_ready(task_id, timeout=2)

    response = client.post(f"/api/tasks/{task_id}/restart")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_catalog_endpoints_load_and_choose():
    client = make_client()
    task_id = client.post(
        "/api/tasks", json={"username": "u", "password": "p"}
    ).json()["id"]
    task = client.app.state.manager._wait_ready(task_id)
    assert task is not None

    assert client.get(f"/api/tasks/{task_id}/catalog").status_code == 409

    assert client.post(f"/api/tasks/{task_id}/catalog").status_code == 202
    deadline = time.time() + 3
    while time.time() < deadline and task.status.value != "NEED_OPERATION":
        time.sleep(0.02)

    assert task.status.value == "NEED_OPERATION"
    assert task.user_operation.value == "CHOOSE_PRACTICE"
    assert task.snapshot()["practice_mode"] == "catalog"

    tree = client.get(f"/api/tasks/{task_id}/catalog").json()
    leaf = tree["units"][0]["children"][0]
    assert leaf["id"] == "t1"
    assert leaf["selectable"] is True

    empty = client.post(
        f"/api/tasks/{task_id}/catalog/choose", json={"task_ids": []}
    )
    assert empty.status_code == 400

    blank = client.post(
        f"/api/tasks/{task_id}/catalog/choose", json={"task_ids": ["", " "]}
    )
    assert blank.status_code == 400

    chosen = client.post(
        f"/api/tasks/{task_id}/catalog/choose", json={"task_ids": ["t1"]}
    )
    assert chosen.status_code == 204


def test_catalog_endpoints_unknown_task_returns_404():
    client = make_client()
    assert client.post("/api/tasks/nope/catalog").status_code == 404
    assert client.get("/api/tasks/nope/catalog").status_code == 404
    assert (
        client.post("/api/tasks/nope/catalog/choose", json={"task_ids": ["t1"]}).status_code
        == 404
    )
