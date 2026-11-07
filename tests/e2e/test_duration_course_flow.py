# -*- coding: utf-8 -*-
"""刷时长课程加载竞态的行为级回归测试。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

import time

from .helpers import course, duration_target, fulfill_json, task_snapshot


def click_mode(page, text):
    options = page.locator('.mode-option')
    assert options.count() == 2, page.evaluate(
        "() => ({ options: document.querySelectorAll('.mode-option').length, body: document.body.innerText.slice(0, 200) })"
    )
    options.filter(has_text=text).click()


def _race_handler(state, ready_delay):
    def handler(route, request):
        url, method = request.url, request.method
        if url.endswith("/api/tasks") and method == "GET":
            fulfill_json(route, [state["task"]])
        elif url.endswith("/api/credentials"):
            fulfill_json(route, [])
        elif "/api/logs" in url:
            fulfill_json(route, [])
        elif "/api/network" in url:
            fulfill_json(route, [])
        elif url.endswith("/duration") and method == "POST":
            state["ready_at"] = time.time() + ready_delay
            state["task"] = task_snapshot(
                status="RUNNING", practice_mode="duration", description="正在获取课程列表..."
            )
            fulfill_json(route, {"ok": True})
        elif url.endswith("/courses") and method == "GET":
            state["courses_calls"] += 1
            if time.time() < state["ready_at"]:
                fulfill_json(route, [])  # 复现旧 bug 中的空列表竞态
            else:
                state["task"] = task_snapshot(
                    status="NEED_OPERATION",
                    user_operation="CHOOSE_COURSE",
                    practice_mode="duration",
                    description="请选择要学习的教程",
                    courses=[course()],
                )
                fulfill_json(route, [course()])
        elif "/api/tasks/T1" in url and method == "GET":
            if time.time() >= state["ready_at"] and state["task"]["status"] == "RUNNING":
                state["task"] = task_snapshot(
                    status="NEED_OPERATION",
                    user_operation="CHOOSE_COURSE",
                    practice_mode="duration",
                    description="请选择要学习的教程",
                    courses=[course()],
                )
            fulfill_json(route, state["task"])
        else:
            fulfill_json(route, {"error": {"message": "miss"}}, status=404)

    return handler


def test_course_list_appears_after_async_load_without_reload(page, base_url):
    """POST /duration 立刻返回；课程就绪后必须自动出现，不需要刷新页面。"""
    state = {"task": task_snapshot(), "ready_at": 0.0, "courses_calls": 0}
    page.route("**/api/**", _race_handler(state, 1.2))
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(500)

    click_mode(page, '刷时长')
    page.wait_for_timeout(500)

    # 等待期间不允许发起课程请求（旧实现这里会拿到空列表并卡死）
    assert state["courses_calls"] == 0
    assert "正在获取课程列表" in page.locator("#stage-body").inner_text()

    deadline = time.time() + 6
    while time.time() < deadline and page.locator(".course-node").count() == 0:
        page.wait_for_timeout(200)

    assert page.locator(".course-node").count() == 1
    assert state["courses_calls"] == 1


def test_course_poll_timeout_shows_retryable_error(page, base_url):
    """任务长时间停留在 RUNNING 时，轮询超时后必须给出可重试的明确状态。"""
    state = {"task": task_snapshot(), "ready_at": float("inf"), "courses_calls": 0}
    page.route("**/api/**", _race_handler(state, 999))
    page.add_init_script(
        "window.UNIPUS_UI_TIMING = { durationCoursePollAttempts: 2, durationCoursePollIntervalMs: 80 };"
    )
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(500)

    click_mode(page, '刷时长')
    page.wait_for_timeout(600)

    error = page.locator(".load-error")
    assert error.count() == 1
    assert "课程列表读取超时" in error.inner_text()
    assert error.locator("button", has_text="重试").count() == 1

    # 平台恢复后点重试，课程选择应自动打开
    state["ready_at"] = time.time() - 1
    state["task"] = task_snapshot(
        status="NEED_OPERATION",
        user_operation="CHOOSE_COURSE",
        practice_mode="duration",
        description="请选择要学习的教程",
        courses=[course()],
    )
    error.locator("button", has_text="重试").click()
    deadline = time.time() + 6
    while time.time() < deadline and page.locator(".course-node").count() == 0:
        page.wait_for_timeout(200)
    assert page.locator(".course-node").count() == 1


def test_full_duration_flow_reaches_target_selection(page, base_url):
    """课程加载竞态修复后，完整流程仍能走到计时内容选择。"""
    state = {
        "task": task_snapshot(),
        "courses": [course()],
        "ready_at": 0.0,
        "courses_calls": 0,
        "phase": "ready",
    }

    def handler(route, request):
        url, method = request.url, request.method
        if url.endswith("/api/tasks") and method == "GET":
            fulfill_json(route, [state["task"]])
        elif url.endswith("/api/credentials"):
            fulfill_json(route, [])
        elif "/api/logs" in url:
            fulfill_json(route, [])
        elif "/api/network" in url:
            fulfill_json(route, [])
        elif url.endswith("/duration") and method == "POST":
            state["phase"] = "running"
            state["task"] = task_snapshot(
                status="RUNNING", practice_mode="duration", description="正在获取课程列表..."
            )
            fulfill_json(route, {"ok": True})
        elif url.endswith("/duration/choose") and method == "POST":
            state["task"] = task_snapshot(
                status="RUNNING",
                practice_mode="duration",
                duration_param="30",
                description="正在累计学习时长",
                completed=0,
                total=30,
                selected_duration_targets=[duration_target("g1", "听力练习")],
            )
            route.fulfill(status=204, body="")
        elif url.endswith("/choose") and method == "POST":
            state["task"] = task_snapshot(
                status="NEED_OPERATION",
                user_operation="CHOOSE_DURATION",
                practice_mode="duration",
                description="请选择要累计时长的学习内容",
                duration_targets=[
                    duration_target("g1", "听力练习"),
                    duration_target("g2", "阅读练习"),
                ],
                duration_param="30",
            )
            route.fulfill(status=204, body="")
        elif url.endswith("/courses") and method == "GET":
            fulfill_json(route, state["courses"])
        elif "/api/tasks/T1" in url and method == "GET":
            if state["phase"] == "running" and state["task"]["status"] == "RUNNING":
                state["phase"] = "need_course"
                state["task"] = task_snapshot(
                    status="NEED_OPERATION",
                    user_operation="CHOOSE_COURSE",
                    practice_mode="duration",
                    description="请选择要学习的教程",
                    courses=state["courses"],
                )
            fulfill_json(route, state["task"])
        else:
            fulfill_json(route, {"error": {"message": "miss"}}, status=404)

    page.route("**/api/**", handler)
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(500)

    click_mode(page, '刷时长')
    deadline = time.time() + 5
    while time.time() < deadline and page.locator(".course-node").count() == 0:
        page.wait_for_timeout(200)

    page.click(".course-node-head")
    page.click(".course-leaf >> nth=0")
    assert page.locator("#course-submit").is_enabled()
    page.click("#course-submit")
    page.wait_for_timeout(500)

    assert page.locator("#duration-target-form").count() == 1
    assert page.locator(".duration-unit").count() == 1
