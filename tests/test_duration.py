import json
import queue
import threading
import time

from unipus_web.core.course_detail import CourseDetail
from unipus_web.core.duration import (
    CourseDurationClient,
    DurationTarget,
    build_duration_targets,
)
from unipus_web.core.task import Status, Task


class FakeSocket:
    def __init__(self):
        self.incoming = queue.Queue()
        self.sent = []
        self.lock = threading.Lock()
        self.closed = threading.Event()

    def send(self, message):
        with self.lock:
            self.sent.append(message)
        if message.startswith("42/userActivities,"):
            ack_id = message.split(",", 2)[1]
            self.incoming.put(
                f"43/userActivities,{ack_id}" + json.dumps([{"code": 0, "msg": "ok"}])
            )
        elif message == "40/userActivities,":
            self.incoming.put("40/userActivities,")

    def recv(self, timeout=None):
        try:
            return self.incoming.get(timeout=timeout or 0.05)
        except queue.Empty:
            return None

    def close(self):
        self.closed.set()


class FakeDurationClient:
    instances = []

    def __init__(self):
        self.connected = False
        self.healthy = True
        self.closed = False
        self.started = []
        self.stopped = 0
        FakeDurationClient.instances.append(self)

    def connect(self):
        self.connected = True

    def start(self, target, course_id, resource_id):
        self.started.append((target, course_id, resource_id))

    def stop(self):
        self.stopped += 1

    def close(self):
        self.closed = True


class FakeCourseClient:
    def login(self, username, password):
        return {"openid": "open-id", "jwt": "jwt", "username": username}

    def get_user_info(self):
        return {
            "success": True,
            "value": {
                "userInfo": {
                    "name": "??",
                    "schName": "??",
                    "appUserId": "app-user",
                    "ssoId": "sso",
                }
            },
        }

    def get_course_list(self):
        return {
            "value": {
                "courseList": [
                    {
                        "id": 1,
                        "name": "??",
                        "startTime": 0,
                        "endTime": 4102444800000,
                        "courseResourceList": [
                            {"id": 11, "name": "??", "instanceId": "course-v2:test"}
                        ],
                    }
                ]
            }
        }

    def get_course_resource_info(self, resource_id):
        return {
            "value": {
                "courseResource": {
                    "courseName": "??",
                    "courseResourceId": 11,
                    "courseInstanceId": "course-v2:test",
                    "strategyId": 7,
                }
            }
        }

    def get_all_tasks(self, course_instance_id):
        return {
            "code": 0,
            "course": {
                "name": "??",
                "units": [
                    {
                        "id": "unit",
                        "role": "unit",
                        "name": "Unit 1",
                        "children": [
                            {
                                "id": "micro",
                                "role": "section",
                                "name": "Section 1",
                                "children": [
                                    {
                                        "id": "group",
                                        "role": "link",
                                        "name": "Reading",
                                        "url": "u",
                                        "ref-out": "r",
                                        "question_num": 1,
                                        "base": "single-choice",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        }

    def get_required_part(self, strategy_id, resource_id):
        return {"success": True, "value": {"courseUnitStrategyList": []}}

    def close(self):
        pass


def test_build_duration_targets_handles_page_suffix():
    course_json = {
        "name": "课程",
        "units": [
            {
                "id": "unit",
                "role": "unit",
                "name": "Unit 1",
                "children": [
                    {
                        "id": "micro",
                        "role": "section",
                        "name": "Section",
                        "children": [
                            {
                                "id": "group",
                                "role": "node",
                                "name": "Group",
                                "children": [
                                    {
                                        "id": "p_1",
                                        "role": "link",
                                        "name": "Page 1",
                                        "url": "u",
                                        "ref-out": "r",
                                        "question_num": 1,
                                        "base": "single-choice",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    target = build_duration_targets(CourseDetail.from_json(course_json))[0]

    assert target.group_id == "group"
    assert target.unit_id == "unit"
    assert target.micro_id == "micro"
    assert target.route_path == "unit/micro/group/p_1"


def test_build_duration_targets_maps_course_route_ids():
    course = CourseDetail.from_json(FakeCourseClient().get_all_tasks("c")["course"])
    targets = build_duration_targets(course)

    assert len(targets) == 1
    assert targets[0].group_id == "group"
    assert targets[0].unit_id == "unit"
    assert targets[0].micro_id == "micro"


def test_duration_client_handshake_events_and_ping(monkeypatch):
    socket = FakeSocket()
    socket.incoming.put('0{"sid":"s","upgrades":[],"pingInterval":10}')
    socket.incoming.put("40")
    monkeypatch.setattr(
        CourseDurationClient, "socket_connect", staticmethod(lambda *args, **kwargs: socket)
    )
    client = CourseDurationClient("open-id")
    client.connect()

    target = DurationTarget(
        "group", "unit", "micro", "unit/micro/group", "Reading", "Unit / Reading"
    )
    client.start(target, "course-v2:test", 11)
    socket.incoming.put("2")
    deadline = time.monotonic() + 1
    while "3" not in socket.sent and time.monotonic() < deadline:
        time.sleep(0.01)

    # 复现真实服务先发送默认命名空间 40，再发送 /userActivities 确认。
    assert "40/userActivities," in socket.sent
    assert "3" in socket.sent
    start_frame = next(item for item in socket.sent if '"start"' in item)
    payload = json.loads(start_frame.split(",", 2)[2])[1]
    assert payload["module"] == "group"
    assert payload["moduleGroup"] == "course-v2:test"
    assert payload["tag1"] == "unit"
    assert payload["tag2"] == "micro"
    assert payload["client"] == "pc"
    assert isinstance(payload["timer"], int)
    client.stop()
    stop_frame = next(item for item in socket.sent if '"stop"' in item)
    stop_payload = json.loads(stop_frame.split(",", 2)[2])[1]
    assert stop_payload["module"] == "group"
    assert stop_payload["moduleGroup"] == "course-v2:test"
    client.close()


def make_duration_task():
    FakeDurationClient.instances = []
    return Task(
        "duration-task",
        "u",
        "p",
        client_factory=lambda task_id: FakeCourseClient(),
        on_change=lambda snapshot: None,
        on_warning=lambda message: None,
        on_error=lambda message: None,
        duration_client_factory=FakeDurationClient,
    )


def test_duration_task_runs_and_stops_socket():
    task = make_duration_task()
    task.initialize()
    assert task.start_duration(1, target_seconds=1)

    deadline = time.monotonic() + 5
    while task.status is not Status.COMPLETED and time.monotonic() < deadline:
        time.sleep(0.02)
    task._worker.join(timeout=2)

    assert task.status is Status.COMPLETED
    assert task.completed == 1
    assert task.total == 1
    client = FakeDurationClient.instances[0]
    assert client.started
    assert client.started[0][0].group_id == "group"
    assert client.started[0][1] == "course-v2:test"
    assert client.stopped == 1
    assert client.closed


def test_start_duration_rejects_invalid_target():
    task = make_duration_task()
    task.initialize()
    try:
        task.start_duration(0)
        raised = False
    except ValueError:
        raised = True
    assert raised


class TwoTargetCourseClient(FakeCourseClient):
    def get_all_tasks(self, course_instance_id):
        payload = super().get_all_tasks(course_instance_id)
        payload["course"]["units"][0]["children"][0]["children"] = [
            {
                "id": "group-1",
                "role": "link",
                "name": "Reading 1",
                "url": "u",
                "ref-out": "r",
                "question_num": 1,
                "base": "single-choice",
            },
            {
                "id": "group-2",
                "role": "link",
                "name": "Reading 2",
                "url": "u",
                "ref-out": "r",
                "question_num": 1,
                "base": "single-choice",
            },
        ]
        return payload


def wait_for_status(task, status, timeout=5):
    deadline = time.monotonic() + timeout
    while task.status is not status and time.monotonic() < deadline:
        time.sleep(0.02)
    return task.status is status


def test_duration_task_asks_for_and_accepts_target_choice():
    FakeDurationClient.instances = []
    task = Task(
        "duration-choice",
        "u",
        "p",
        client_factory=lambda task_id: TwoTargetCourseClient(),
        on_change=lambda snapshot: None,
        on_warning=lambda message: None,
        on_error=lambda message: None,
        duration_client_factory=FakeDurationClient,
    )
    task.initialize()
    assert task.start_duration(1, target_seconds=1)
    assert wait_for_status(task, Status.NEED_OPERATION)
    snapshot = task.snapshot()
    assert snapshot["duration_targets"][1]["group_id"] == "group-2"

    task.choose_duration("group-2")
    assert wait_for_status(task, Status.COMPLETED)
    task._worker.join(timeout=2)
    assert task.selected_duration_target.group_id == "group-2"
    assert FakeDurationClient.instances[0].started[0][0].group_id == "group-2"


def test_pause_stops_timer_and_resume_starts_new_segment():
    FakeDurationClient.instances = []
    task = make_duration_task()
    task.initialize()
    assert task.start_duration(1, target_seconds=3)

    deadline = time.monotonic() + 3
    while (
        not FakeDurationClient.instances
        or not FakeDurationClient.instances[0].started
    ) and time.monotonic() < deadline:
        time.sleep(0.01)
    task.request_pause()
    deadline = time.monotonic() + 3
    while FakeDurationClient.instances[0].stopped != 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert task.status is Status.PAUSED

    task.request_resume()
    assert wait_for_status(task, Status.COMPLETED, timeout=5)
    task._worker.join(timeout=2)
    client = FakeDurationClient.instances[0]
    assert len(client.started) == 2
    assert client.stopped == 2


def test_duration_task_fails_promptly_when_socket_becomes_unhealthy():
    FakeDurationClient.instances = []
    task = make_duration_task()
    task.initialize()
    assert task.start_duration(30, target_seconds=1800)

    deadline = time.monotonic() + 3
    while (
        not FakeDurationClient.instances
        or not FakeDurationClient.instances[0].started
    ) and time.monotonic() < deadline:
        time.sleep(0.01)
    FakeDurationClient.instances[0].healthy = False

    assert wait_for_status(task, Status.ERROR, timeout=2)
    task._worker.join(timeout=2)
    assert "计时连接中断" in (task.error or task.description)
    assert FakeDurationClient.instances[0].closed
