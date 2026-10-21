import threading
import time

import pytest

from unipus_web.api.errors import TaskStopped
from unipus_web.core.task import Status, Task


class FakeClient:
    def login(self, username, password):
        return {"openid": "o", "jwt": "j", "username": username}

    def get_user_info(self):
        return {
            "success": True,
            "value": {
                "userInfo": {
                    "name": "张三",
                    "schName": "某大学",
                    "appUserId": "a",
                    "ssoId": "s",
                }
            },
        }

    def close(self):
        pass


def make_task(**kwargs):
    task = Task(
        "task-u",
        "u",
        "p",
        client_factory=lambda tid: FakeClient(),
        on_change=lambda snap: None,
        on_warning=lambda msg: None,
        on_error=lambda msg: None,
        **kwargs,
    )
    task.initialize()
    return task


def test_initialize_sets_ready_and_user():
    task = make_task()
    assert task.status == Status.READY
    assert task.user.name == "张三"
    assert task.user.school_name == "某大学"


def test_stop_wakes_cooldown_immediately():
    task = make_task()
    outcome = []

    def worker():
        task._tls.generation = task.generation
        try:
            task.wait_for_cooldown(60_000, "冷却", "继续")
            outcome.append("returned")
        except TaskStopped:
            outcome.append("stopped")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    time.sleep(0.05)

    started = time.monotonic()
    task.request_stop()
    thread.join(timeout=1.0)
    assert time.monotonic() - started < 1.0
    assert outcome == ["stopped"]
    assert task.status == Status.READY


def test_pause_blocks_checkpoint_until_resume():
    task = make_task()
    seen = []

    def worker():
        task.set_status(Status.RUNNING)
        task.request_pause()
        seen.append("before")
        task.checkpoint()
        seen.append("after")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    time.sleep(0.1)
    assert seen == ["before"]

    task.request_resume()
    thread.join(timeout=1.0)
    assert seen == ["before", "after"]


def test_generation_prevents_stale_writes():
    task = make_task()
    task.start()
    task.request_stop()
    stale_generation = task.generation - 1

    task._set_status_if_current(stale_generation, Status.RUNNING)
    assert task.status == Status.READY

    task._set_status_if_current(task.generation, Status.RUNNING)
    assert task.status == Status.RUNNING


def test_stale_worker_cannot_pass_checkpoint_after_restart():
    task = make_task()
    stale_generation = task.generation
    task.request_stop()
    task.start()  # 重新启动，generation 递增且 stop_event 被清除

    outcome = []

    def worker():
        task._tls.generation = stale_generation
        try:
            task.checkpoint()
            outcome.append("passed")
        except TaskStopped:
            outcome.append("stopped")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=1.0)
    assert outcome == ["stopped"]


def test_stale_worker_cannot_wait_for_cooldown_after_restart():
    task = make_task()
    stale_generation = task.generation
    task.request_stop()
    task.start()

    outcome = []

    def worker():
        task._tls.generation = stale_generation
        try:
            task.wait_for_cooldown(60_000, "冷却", "继续")
            outcome.append("passed")
        except TaskStopped:
            outcome.append("stopped")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=1.0)
    assert outcome == ["stopped"]


def test_stop_during_user_operation_raises():
    task = make_task()
    task._begin_user_operation()

    def stopper():
        time.sleep(0.05)
        task.request_stop()

    threading.Thread(target=stopper, daemon=True).start()
    try:
        task.wait_for_user_operation()
        raised = False
    except Exception as exc:  # TaskStopped
        raised = type(exc).__name__ == "TaskStopped"
    assert raised is True
    assert task.status == Status.READY


def test_snapshot_reports_practice_mode():
    task = make_task()
    assert task.snapshot()["practice_mode"] == "required"


def test_choose_practice_releases_waiting_worker():
    from unipus_web.core.task import UserOperation

    task = make_task()
    task._begin_user_operation(UserOperation.CHOOSE_PRACTICE)
    assert task.status == Status.NEED_OPERATION
    assert task.user_operation == UserOperation.CHOOSE_PRACTICE

    outcome = []

    def worker():
        task.wait_for_user_operation()
        outcome.append(list(task.selected_task_ids))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    time.sleep(0.05)
    task.choose_practice(["t1", "t2"])
    thread.join(timeout=1.0)

    assert outcome == [["t1", "t2"]]
    assert task.status == Status.RUNNING
    assert task.user_operation is None


def test_stop_during_practice_selection_raises():
    from unipus_web.core.task import UserOperation

    task = make_task()
    task._begin_user_operation(UserOperation.CHOOSE_PRACTICE)

    def stopper():
        time.sleep(0.05)
        task.request_stop()

    threading.Thread(target=stopper, daemon=True).start()
    try:
        task.wait_for_user_operation()
        raised = False
    except Exception as exc:
        raised = type(exc).__name__ == "TaskStopped"
    assert raised is True


def test_resume_restores_pending_practice_selection():
    from unipus_web.core.task import UserOperation

    task = make_task()
    task._begin_user_operation(UserOperation.CHOOSE_PRACTICE)
    task.request_pause()
    assert task.status == Status.PAUSED

    task.request_resume()
    assert task.status == Status.NEED_OPERATION


def test_begin_user_operation_keeps_paused_status():
    from unipus_web.core.task import UserOperation

    task = make_task()
    task.set_status(Status.RUNNING)
    task.request_pause()
    assert task.status == Status.PAUSED

    task._begin_user_operation(
        UserOperation.CHOOSE_PRACTICE, generation=task.generation
    )
    assert task.status == Status.PAUSED

    task.request_resume()
    assert task.status == Status.NEED_OPERATION
