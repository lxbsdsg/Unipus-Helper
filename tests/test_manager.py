import io
import json
import zipfile

import pytest

from unipus_web.credentials import CredentialStore
from unipus_web.core.manager import TaskManager
from unipus_web.core.reporter import build_report
from unipus_web.events import EventBus
from unipus_web.logging_setup import LogStore
from unipus_web.network_log import NetworkRecorder


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


def make_manager(tmp_path):
    return TaskManager(
        bus=EventBus(),
        log_store=LogStore(),
        network=NetworkRecorder(),
        credentials=CredentialStore(tmp_path / "c.dat"),
        client_factory=lambda tid: FakeClient(),
    )


def test_create_task_from_credentials_then_remove(tmp_path):
    manager = make_manager(tmp_path)
    cred = manager.credentials.add("u", "p")
    snapshot = manager.create_task(credential_id=cred["id"])
    manager._wait_ready(snapshot["id"], timeout=2)
    assert manager.get(snapshot["id"]).status.value == "READY"
    assert manager.remove(snapshot["id"]) is True
    assert manager.snapshots() == []


def test_duplicate_task_raises(tmp_path):
    manager = make_manager(tmp_path)
    manager.create_task(username="u", password="p")
    with pytest.raises(ValueError):
        manager.create_task(username="u", password="p")


def test_missing_credential_raises(tmp_path):
    manager = make_manager(tmp_path)
    with pytest.raises(ValueError):
        manager.create_task(credential_id="nope")


def test_report_zip_redacts_password(tmp_path):
    manager = make_manager(tmp_path)
    manager.log_store.add("INFO", "t", "login password=plain-pw")
    manager.network.add(
        {
            "method": "POST",
            "url": "https://sso.unipus.cn/sso/0.1/sso/login",
            "request_payload": json.dumps({"password": "plain-pw"}),
            "response_body": "",
        }
    )

    data = build_report(manager)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert {"logs.log", "networks.jsonl", "meta.json"} <= names
        joined = b"".join(archive.read(n) for n in names).decode("utf-8", "replace")
        assert "plain-pw" not in joined


def test_restart_preserves_practice_mode(tmp_path):
    manager = make_manager(tmp_path)
    snapshot = manager.create_task(username="u", password="p")
    task = manager._wait_ready(snapshot["id"], timeout=2)
    task.practice_mode = "catalog"

    assert manager.restart(snapshot["id"]) is True
    assert task.practice_mode == "catalog"
