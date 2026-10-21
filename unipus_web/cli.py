"""终端备选模式：不启动 Web UI，直接在 cmd / 终端里登录并学习。"""

from __future__ import annotations

import getpass
import os
import sys
import time
from typing import Callable

from .api.client import UnipusClient
from .core.task import Status, Task
from .logging_setup import LogStore, setup_logging
from .models import Course, CourseResource


def flatten_choices(courses: list[Course] | None) -> list[tuple[Course, CourseResource]]:
    pairs: list[tuple[Course, CourseResource]] = []
    for course in courses or []:
        for resource in course.resources or []:
            pairs.append((course, resource))
    return pairs


def parse_choice(text: str, count: int) -> int | None:
    text = (text or "").strip()
    if not text:
        return 0
    try:
        value = int(text)
    except ValueError:
        return None
    if 1 <= value <= count:
        return value - 1
    return None


def format_progress(snapshot: dict) -> str:
    return (
        f"[{snapshot.get('status', '')}] {snapshot.get('description', '')} "
        f"({snapshot.get('completed', 0)}/{snapshot.get('total', 0)}, "
        f"{snapshot.get('progress_percent', 0)}%)"
    )


def prompt_choice(choices: list[tuple[Course, CourseResource]], out=print) -> int:
    out("检测到多个课程/教程：")
    for index, (course, resource) in enumerate(choices, 1):
        out(f"  [{index}] {course.name} > {resource.name}")
    try:
        text = input(f"请选择编号（1-{len(choices)}，回车默认 1）: ")
    except EOFError:
        return 0
    selected = parse_choice(text, len(choices))
    if selected is None:
        out("输入无效，使用第 1 项。")
        return 0
    return selected


def _prompt_credentials(
    username: str | None, password: str | None, allow_prompt: bool
) -> tuple[str, str]:
    username = (username or os.environ.get("UNIPUS_USERNAME") or "").strip()
    password = password or os.environ.get("UNIPUS_PASSWORD") or ""

    if not username and allow_prompt:
        try:
            username = input("U校园账号: ").strip()
        except EOFError:
            username = ""
    if not password and allow_prompt:
        try:
            password = getpass.getpass("密码: ")
        except EOFError:
            password = ""
    return username, password


def _build_task(**kwargs) -> Task:
    proxy = kwargs.pop("proxy", None)
    return Task(
        kwargs["task_id"],
        kwargs["username"],
        kwargs["password"],
        client_factory=lambda task_id: UnipusClient(task_id, proxy=proxy),
        on_change=kwargs["on_change"],
        on_warning=kwargs["on_warning"],
        on_error=kwargs["on_error"],
        allow_multi_question=kwargs["allow_multi_question"],
    )


def run_cli(
    *,
    username: str | None = None,
    password: str | None = None,
    proxy: str | None = None,
    allow_multi_question: bool = True,
    assume_yes: bool = False,
    allow_prompt: bool = True,
    task_factory: Callable[..., Task] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    out: Callable[[str], None] = print,
    configure_logging: bool = True,
) -> int:
    """在终端里完成登录 → 选课 → 学习 → 退出。

    返回码：0 完成，1 失败，2 缺少凭据/需要选择，130 用户中断。
    """
    if configure_logging:
        setup_logging(LogStore())

    username, password = _prompt_credentials(username, password, allow_prompt)
    if not username or not password:
        print("缺少账号或密码。可用 --username/--password 或环境变量提供。", file=sys.stderr)
        return 2

    task_id = f"task-{username}"
    factory = task_factory or _build_task
    task = factory(
        task_id=task_id,
        username=username,
        password=password,
        on_change=lambda snapshot: None,
        on_warning=lambda message: out(f"[警告] {message}"),
        on_error=lambda message: out(f"[错误] {message}"),
        proxy=proxy,
        allow_multi_question=allow_multi_question,
    )

    try:
        out(f"正在登录：{username}")
        task.initialize()
        if task.status is Status.ERROR:
            out(f"登录失败：{task.description or '未知错误'}")
            return 1
        out(f"登录成功：{task.name or username}")

        if not task.start():
            out("任务无法启动。")
            return 1
        out("任务已启动，按 Ctrl+C 停止。")

        last_line = None
        prompted = False
        snapshot = task.snapshot()
        while True:
            snapshot = task.snapshot()
            status = snapshot.get("status")

            if status == "NEED_OPERATION" and not prompted:
                choices = flatten_choices(task.course_list)
                if not choices:
                    out("没有可选择的课程，任务已停止。")
                    task.request_stop()
                    return 1
                index = 0
                if not assume_yes:
                    if not allow_prompt:
                        out("存在多个课程/教程，请在终端运行或加 --yes 自动选择第一个。")
                        task.request_stop()
                        return 1
                    index = prompt_choice(choices, out)
                task.choose_course(*choices[index])
                prompted = True

            line = format_progress(snapshot)
            if line != last_line:
                out(line)
                last_line = line

            if status in ("COMPLETED", "ERROR", "READY"):
                break
            sleep(0.5)

        return 0 if snapshot.get("status") == "COMPLETED" else 1

    except KeyboardInterrupt:
        out("\n已请求停止...")
        try:
            task.request_stop()
        except Exception:
            pass
        return 130
