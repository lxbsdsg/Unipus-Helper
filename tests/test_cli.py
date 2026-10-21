from unipus_web.cli import flatten_choices, format_progress, parse_choice, run_cli
from unipus_web.core.task import Status
from unipus_web.models import Course


def make_courses():
    return [
        Course.from_json(
            {
                "id": 1,
                "name": "课程A",
                "courseResourceList": [
                    {"id": 11, "name": "教程A1"},
                    {"id": 12, "name": "教程A2"},
                ],
            }
        ),
        Course.from_json(
            {
                "id": 2,
                "name": "课程B",
                "courseResourceList": [{"id": 21, "name": "教程B1"}],
            }
        ),
    ]


def test_flatten_choices_lists_every_course_resource_pair():
    choices = flatten_choices(make_courses())
    assert [(course.name, resource.name) for course, resource in choices] == [
        ("课程A", "教程A1"),
        ("课程A", "教程A2"),
        ("课程B", "教程B1"),
    ]


def test_parse_choice_defaults_and_bounds():
    assert parse_choice("", 3) == 0
    assert parse_choice("2", 3) == 1
    assert parse_choice("9", 3) is None
    assert parse_choice("abc", 3) is None


def test_format_progress_includes_status_and_numbers():
    line = format_progress(
        {
            "status": "RUNNING",
            "description": "学习中",
            "completed": 3,
            "total": 5,
            "progress_percent": 60,
        }
    )
    assert "RUNNING" in line
    assert "3/5" in line
    assert "60%" in line


class FakeTask:
    def __init__(self):
        self.status = Status.READY
        self.course_list = []
        self.user = None
        self.name = "fake"
        self.description = ""
        self.completed = 0
        self.total = 0
        self.calls = []
        self._snapshots = [
            {
                "status": "RUNNING",
                "description": "学习中",
                "completed": 0,
                "total": 1,
                "progress_percent": 0,
            },
            {
                "status": "COMPLETED",
                "description": "完成",
                "completed": 1,
                "total": 1,
                "progress_percent": 100,
            },
        ]

    def initialize(self):
        self.calls.append("initialize")

    def start(self):
        self.calls.append("start")
        self.status = Status.RUNNING
        return True

    def request_stop(self):
        self.calls.append("stop")

    def snapshot(self):
        if len(self._snapshots) > 1:
            return self._snapshots.pop(0)
        return self._snapshots[0]


def test_run_cli_drives_a_task_to_completion():
    task = FakeTask()
    lines = []

    code = run_cli(
        username="u",
        password="p",
        assume_yes=True,
        task_factory=lambda **kwargs: task,
        sleep=lambda _seconds: None,
        out=lines.append,
        configure_logging=False,
    )

    assert code == 0
    assert task.calls == ["initialize", "start"]
    assert any("COMPLETED" in line for line in lines)


def test_run_cli_rejects_missing_credentials():
    lines = []
    code = run_cli(
        username="",
        password="",
        allow_prompt=False,
        task_factory=lambda **kwargs: FakeTask(),
        sleep=lambda _seconds: None,
        out=lines.append,
        configure_logging=False,
    )
    assert code == 2
