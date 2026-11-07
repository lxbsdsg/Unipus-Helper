# -*- coding: utf-8 -*-
"""设置表单回收复用的行为级回归测试。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

from .helpers import course, duration_target, fulfill_json, task_snapshot


def click_mode(page, text):
    options = page.locator('.mode-option')
    assert options.count() == 2, page.evaluate(
        "() => ({ options: document.querySelectorAll('.mode-option').length, body: document.body.innerText.slice(0, 200) })"
    )
    options.filter(has_text=text).click()


def test_duration_course_form_can_remount_after_full_flow(page, base_url):
    state = {
        "task": task_snapshot(practice_mode="duration"),
        "courses": [course()],
        "courses_calls": 0,
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
            state["task"] = task_snapshot(
                status="NEED_OPERATION",
                user_operation="CHOOSE_COURSE",
                practice_mode="duration",
                description="请选择要学习的教程",
                courses=state["courses"],
            )
            fulfill_json(route, {"ok": True})
        elif url.endswith("/duration/choose") and method == "POST":
            state["task"] = task_snapshot(
                status="RUNNING",
                practice_mode="duration",
                duration_param="30",
                description="正在累计学习时长",
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
                duration_targets=[duration_target("g1", "听力练习")],
                duration_param="30",
            )
            route.fulfill(status=204, body="")
        elif url.endswith("/courses") and method == "GET":
            state["courses_calls"] += 1
            fulfill_json(route, state["courses"])
        elif "/api/tasks/T1" in url and method == "GET":
            fulfill_json(route, state["task"])
        else:
            fulfill_json(route, {"error": {"message": "miss"}}, status=404)

    page.route("**/api/**", handler)
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(600)

    # 第一次完整流程：课程 → 计时内容 → 运行
    click_mode(page, '刷时长')
    deadline_steps = 30
    for _ in range(deadline_steps):
        if page.locator(".course-node").count():
            break
        page.wait_for_timeout(200)
    page.click(".course-node-head")
    page.click(".course-leaf >> nth=0")
    page.click("#course-submit")
    page.wait_for_timeout(400)

    page.click(".duration-unit-head")
    page.locator(".duration-item input[type=checkbox]").first.check()
    page.click("#duration-target-submit")
    page.wait_for_timeout(400)
    assert "任务运行中" in page.locator(".stage-running h3").inner_text()

    # 任务重置回 READY 后再次进入：课程表单必须能重新挂载
    state["task"] = task_snapshot(practice_mode="duration", description="任务已重置")
    page.evaluate("t => handleEvent({type: 'task.updated', data: t})", state["task"])
    page.wait_for_timeout(300)
    assert page.locator(".mode-option").count() == 2

    click_mode(page, '刷时长')
    page.wait_for_timeout(600)
    assert page.locator("#course-form").count() == 1
    assert page.locator(".course-node").count() == 1


def test_practice_form_can_reopen_after_run(page, base_url):
    state = {"task": task_snapshot()}

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
        elif url.endswith("/start") and method == "POST":
            state["task"] = task_snapshot(
                status="RUNNING", practice_mode="required", description="正在完成必修任务", total=3
            )
            fulfill_json(route, {"ok": True})
        elif "/api/tasks/T1" in url and method == "GET":
            fulfill_json(route, state["task"])
        else:
            fulfill_json(route, {"error": {"message": "miss"}}, status=404)

    page.route("**/api/**", handler)
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(600)

    click_mode(page, '刷正确率')
    assert page.locator("#practice-form").count() == 1
    page.click("#practice-submit")
    page.wait_for_timeout(400)
    assert "任务运行中" in page.locator(".stage-running h3").inner_text()

    state["task"] = task_snapshot()
    page.evaluate("t => handleEvent({type: 'task.updated', data: t})", state["task"])
    page.wait_for_timeout(300)
    assert page.locator(".mode-option").count() == 2

    click_mode(page, '刷正确率')
    page.wait_for_timeout(300)
    assert page.locator("#practice-form").count() == 1
