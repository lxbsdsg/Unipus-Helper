import pytest
from fastapi.testclient import TestClient

from unipus_web.app import create_app


class FakeClient:
    def login(self, username, password):
        return {"openid": "o", "jwt": "j", "username": username}

    def get_user_info(self):
        return {
            "success": True,
            "value": {"userInfo": {"name": "张三", "schName": "学校"}},
        }

    def close(self):
        pass


def make_client():
    app = create_app(testing=True)
    app.state.manager.client_factory = lambda tid: FakeClient()
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
