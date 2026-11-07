# -*- coding: utf-8 -*-
"""课程树交互回归：自动选教程、收起保留选择、提交防重复。"""

from __future__ import annotations

import pytest
import time

pytestmark = pytest.mark.e2e

from .helpers import course, duration_target, fulfill_json, install_base_mocks, task_snapshot


def _course_page(page, base_url, courses):
    task = task_snapshot(
        status="NEED_OPERATION",
        user_operation="CHOOSE_COURSE",
        practice_mode="duration",
        description="请选择要学习的教程",
        courses=courses,
    )
    install_base_mocks(page, task, courses)
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(600)
    assert page.locator(".course-node").count() > 0, page.evaluate(
        "() => ({ tasks: state.tasks.size, stageView: state.stageView, body: document.getElementById('stage-body').innerText })"
    )
    return page


def test_single_tutorial_is_auto_selected(page, base_url):
    """恢复旧版行为：课程下只有一门教程时，点课程即选中教程。"""
    _course_page(page, base_url, [course()])
    assert page.evaluate("() => document.getElementById('course-submit').disabled")

    page.click(".course-node-head")
    page.wait_for_timeout(200)

    assert page.evaluate("() => state.courseSelection.resource?.id") == 1011
    assert not page.evaluate("() => document.getElementById('course-submit').disabled")


def test_collapsing_course_keeps_selected_tutorial(page, base_url):
    """收起课程只改变展示状态，不能丢掉已选教程。"""
    multi = course(101, "课程A")
    multi["resources"].append(
        {
            "id": 1013,
            "resource_id": "r101b",
            "instance_id": "i101b",
            "strategy_id": 0,
            "name": "教程B",
            "finish_point_num": 1,
            "total_point_num": 4,
        }
    )
    _course_page(page, base_url, [multi])

    page.click(".course-node-head")
    page.click(".course-leaf >> nth=1")
    assert page.evaluate("() => state.courseSelection.resource?.id") == 1013

    page.click(".course-node-head")  # 收起
    page.wait_for_timeout(200)

    assert page.evaluate("() => state.courseSelection.resource?.id") == 1013
    assert not page.evaluate("() => document.getElementById('course-submit').disabled")


def test_course_submit_sends_only_one_request_under_double_click(page, base_url):
    """请求进行中按钮必须保持禁用，双击不能产生两次提交。"""
    task = task_snapshot(
        status="NEED_OPERATION",
        user_operation="CHOOSE_COURSE",
        practice_mode="duration",
        description="请选择要学习的教程",
        courses=[course()],
    )
    install_base_mocks(page, task, [course()])
    choose_calls = []

    def handler(route, request):
        choose_calls.append(request.post_data)
        page.wait_for_timeout(250)  # keep the first request in flight
        route.fulfill(status=204, body="")

    page.route("**/api/tasks/T1/choose", handler)
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(600)

    page.click(".course-node-head")
    page.wait_for_timeout(200)
    assert not page.evaluate("() => document.getElementById('course-submit').disabled")

    # Two rapid submissions: the first disables the button, so the second
    # click must be swallowed before reaching fetch().
    page.locator("#course-submit").click(click_count=2, delay=80)
    page.wait_for_timeout(300)
    assert page.evaluate("() => !state.courseSubmitting")

    assert len(choose_calls) == 1


def test_duration_unit_checkbox_selects_whole_unit(page, base_url):
    """勾选单元标题应选择整个单元；勾小节时单元框应变为全选/半选。"""
    task = task_snapshot(
        status="NEED_OPERATION",
        user_operation="CHOOSE_DURATION",
        practice_mode="duration",
        description="请选择要累计时长的学习内容",
        duration_targets=[
            duration_target("g1", "练习 1"),
            duration_target("g2", "练习 2"),
            duration_target("g3", "练习 3", unit="u2", unit_name="Unit 2", index=1),
        ],
        duration_param="30",
    )
    install_base_mocks(page, task, [])
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(600)

    # 勾选 Unit 1：单元是独立“整包选择”，子项不自动点亮，但提交可用
    page.locator(".duration-unit-head-row input[type=checkbox]").first.check()
    page.wait_for_timeout(200)
    assert page.evaluate("() => state.durationTargetSelection.size") == 0
    assert page.evaluate("() => state.durationTargetUnitSelection.size") == 1
    assert not page.evaluate("() => document.getElementById('duration-target-submit').disabled")
    assert "已选 2 个练习" in page.locator("#duration-target-summary").inner_text()

    # 展开后勾选一个小节：先取消整单元，子项计数为 1，单元框半选
    page.locator(".duration-unit-head", has_text="Unit 1").click()
    page.locator(".duration-item input[type=checkbox]").first.check()
    page.wait_for_timeout(200)
    assert page.evaluate("() => state.durationTargetUnitSelection.size") == 0
    assert page.evaluate("() => state.durationTargetSelection.size") == 1
    assert page.evaluate(
        "() => document.querySelector('.duration-unit-head-row input[type=checkbox]').indeterminate"
    )

    # 勾满该单元剩余小节：单元框应显示全选（但子项选择仍保留）
    page.locator(".duration-item input[type=checkbox]").nth(1).check()
    page.wait_for_timeout(200)
    assert page.evaluate("() => state.durationTargetSelection.size") == 2
    assert page.evaluate(
        "() => document.querySelector('.duration-unit-head-row input[type=checkbox]').checked"
    )


def test_back_to_course_selection_returns_to_course_step(page, base_url):
    """从计时内容选择返回课程选择；重新选课程后进入计时内容。"""
    task = task_snapshot(
        status="NEED_OPERATION",
        user_operation="CHOOSE_DURATION",
        practice_mode="duration",
        description="请选择要累计时长的学习内容",
        duration_targets=[duration_target("g1", "练习 1")],
        duration_param="30",
    )
    state = install_base_mocks(page, task, [course()])
    restart_calls = 0

    def handler(route, request):
        nonlocal restart_calls
        url, method = request.url, request.method
        if url.endswith("/restart") and method == "POST":
            restart_calls += 1
            page.wait_for_timeout(250)  # keep the first request in flight
            state["task"] = task_snapshot(practice_mode="duration", description="任务已重置")
            return fulfill_json(route, {"ok": True})
        if url.endswith("/duration") and method == "POST":
            state["task"] = task_snapshot(
                status="NEED_OPERATION",
                user_operation="CHOOSE_COURSE",
                practice_mode="duration",
                description="请选择要学习的教程",
                courses=[course()],
            )
            return fulfill_json(route, {"ok": True})
        if url.endswith("/choose") and method == "POST":
            state["task"] = task_snapshot(
                status="NEED_OPERATION",
                user_operation="CHOOSE_DURATION",
                practice_mode="duration",
                description="请选择要累计时长的学习内容",
                duration_targets=[duration_target("g1", "练习 1")],
                duration_param="30",
            )
            return route.fulfill(status=204, body="")
        if url.endswith("/courses") and method == "GET":
            return fulfill_json(route, [course()])
        if "/api/tasks/T1" in url and method == "GET":
            return fulfill_json(route, state["task"])
        if url.endswith("/api/tasks") and method == "GET":
            return fulfill_json(route, [state["task"]])
        return route.fallback()

    page.route("**/api/**", handler)
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(600)

    assert page.locator("#duration-target-form").count() == 1
    page.locator('[data-action="back-course"]').click()

    # 确认前按钮被禁用，防止用户重复触发返回
    assert page.locator('[data-action="back-course"]').is_disabled()
    page.locator("#confirm-ok").click()
    page.wait_for_timeout(100)
    assert page.evaluate("() => state.durationGoingBack")
    page.locator('[data-action="back-course"]').click(force=True)
    page.wait_for_timeout(400)

    assert restart_calls == 1
    assert page.locator("#course-form").count() == 1
    deadline = time.time() + 5
    while time.time() < deadline and page.locator(".course-node").count() == 0:
        page.wait_for_timeout(200)
    assert page.locator(".course-node").count() == 1


def _many_courses(count=12, tutorials=4):
    courses = []
    for i in range(1, count + 1):
        item = course(100 + i, f"课程 {i:02d}")
        item["resources"] = [
            {
                "id": item["id"] * 10 + j,
                "resource_id": f"r{i}-{j}",
                "instance_id": f"i{i}-{j}",
                "strategy_id": 0,
                "name": f"教程 {i}-{j}",
                "finish_point_num": j % 3,
                "total_point_num": 6,
            }
            for j in range(1, tutorials + 1)
        ]
        courses.append(item)
    return courses


def test_course_submit_button_visible_without_scrolling(page, base_url):
    """长课程列表下，确认按钮必须留在首屏内；列表自己内部滚动。"""
    courses = _many_courses()
    state = {"task": task_snapshot(), "courses": courses}

    def handler(route, request):
        url, method = request.url, request.method
        if url.endswith("/api/tasks") and method == "GET":
            return fulfill_json(route, [state["task"]])
        if url.endswith("/api/credentials"):
            return fulfill_json(route, [])
        if "/api/logs" in url:
            return fulfill_json(route, [])
        if "/api/network" in url:
            return fulfill_json(route, [])
        if url.endswith("/duration") and method == "POST":
            state["task"] = task_snapshot(
                status="NEED_OPERATION",
                user_operation="CHOOSE_COURSE",
                practice_mode="duration",
                description="请选择要学习的教程",
                courses=courses,
            )
            return fulfill_json(route, {"ok": True})
        if url.endswith("/courses"):
            return fulfill_json(route, courses)
        if "/api/tasks/T1" in url and method == "GET":
            return fulfill_json(route, state["task"])
        return fulfill_json(route, {"error": {"message": "miss"}}, status=404)

    page.route("**/api/**", handler)

    for width, height in ((1366, 768), (390, 844)):
        state["task"] = task_snapshot()
        page.set_viewport_size({"width": width, "height": height})
        page.goto(base_url, wait_until="load")
        page.wait_for_timeout(500)
        page.locator(".mode-option").filter(has_text="刷时长").click()

        deadline = time.time() + 6
        while time.time() < deadline and page.locator(".course-node").count() == 0:
            page.wait_for_timeout(150)
        page.wait_for_timeout(900)  # let mobile smooth scrolling settle

        metrics = page.evaluate(
            """() => {
              const button = document.getElementById('course-submit');
              const rect = button.getBoundingClientRect();
              const list = document.getElementById('course-options');
              return {
                visible: rect.top >= 0 && rect.bottom <= innerHeight,
                listScrollsInternally: list.scrollHeight > list.clientHeight,
              };
            }"""
        )
        assert metrics["visible"], (width, height, metrics)
        assert metrics["listScrollsInternally"], (width, height, metrics)


def test_course_error_does_not_push_submit_out_of_view(page, base_url):
    """显示校验错误时，确认按钮仍应留在首屏内（margin 覆盖必须生效）。"""
    task = task_snapshot(
        status="NEED_OPERATION",
        user_operation="CHOOSE_COURSE",
        practice_mode="duration",
        courses=[course()],
    )
    install_base_mocks(page, task, [course()])
    page.set_viewport_size({"width": 1366, "height": 768})
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(600)

    page.evaluate("() => document.getElementById('course-form').requestSubmit()")
    page.wait_for_timeout(200)
    assert page.evaluate("() => getComputedStyle(document.getElementById('course-error')).margin") == "0px"
    assert page.evaluate(
        "() => { const r = document.getElementById('course-submit').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }"
    )


def test_all_mode_entries_scroll_stage_on_mobile(page, base_url):
    """手机端点击刷正确率/刷时长都应把工作台滚入视口。"""
    page.set_viewport_size({"width": 390, "height": 844})
    for label in ("刷正确率", "刷时长"):
        state = {"task": task_snapshot()}
        install_base_mocks(page, state["task"], [])
        page.goto(base_url, wait_until="load")
        page.wait_for_timeout(500)
        assert page.evaluate("() => scrollY") == 0

        page.locator(".mode-option").filter(has_text=label).click()
        page.wait_for_timeout(900)
        assert page.evaluate("() => scrollY") > 0, label


def test_all_form_submit_buttons_sticky_and_visible(page, base_url):
    """所有表单的操作按钮都应吸底且在笔记本视口内可见。"""
    targets = [
        duration_target(f"g{i}", f"练习 {i}", unit=f"u{(i-1)//6+1}", unit_name=f"Unit {(i-1)//6+1}", index=(i-1)//6)
        for i in range(1, 25)
    ]
    scenarios = [
        ("practice-submit", task_snapshot(), None),
        ("course-submit", task_snapshot(
            status="NEED_OPERATION", user_operation="CHOOSE_COURSE", practice_mode="duration",
            courses=[course()]), [course()]),
        ("duration-target-submit", task_snapshot(
            status="NEED_OPERATION", user_operation="CHOOSE_DURATION", practice_mode="duration",
            duration_targets=targets, duration_param="30"), []),
    ]
    page.set_viewport_size({"width": 1366, "height": 768})
    for btn_id, task, courses in scenarios:
        state = install_base_mocks(page, task, courses)
        if courses:
            page.route("**/api/tasks/T1/courses", lambda r: fulfill_json(r, courses))
        page.goto(base_url, wait_until="load")
        page.wait_for_timeout(600)
        if btn_id == "practice-submit":
            page.locator(".mode-option").filter(has_text="刷正确率").click()
            page.wait_for_timeout(400)

        info = page.evaluate(
            """(btnId) => {
                const btn = document.getElementById(btnId);
                const foot = btn.closest("footer");
                const r = btn.getBoundingClientRect();
                return {
                    visible: r.top >= 0 && r.bottom <= innerHeight,
                    sticky: foot ? getComputedStyle(foot).position : null,
                };
            }""",
            btn_id,
        )
        assert info["sticky"] == "sticky", (btn_id, info)
        assert info["visible"], (btn_id, info)


def test_catalog_item_list_fully_expands(page, base_url):
    """题目列表应横向展开，题型/路径信息换行显示而非截断。"""
    tree = {"name": "教程", "type": "book", "units": [{"id": "u1", "role": "unit", "caption": "Unit 1", "name": "U1", "children": [
        {"id": "s1", "role": "section", "caption": "Section 1 一个较长的小节名称", "name": "S1", "children": [
            {"id": f"q{i}", "role": "group", "caption": f"题目 {i:02d} 这是一个比较长的题目名称", "name": f"Q{i}",
             "question_num": 2, "bases": ["single-choice"], "tab_type": "ex", "required": True,
             "answerable": True, "status_known": True, "finish_progress": 0, "selectable": True}
            for i in range(1, 12)
        ]}
    ]}]}
    task = task_snapshot(status="NEED_OPERATION", user_operation="CHOOSE_PRACTICE", practice_mode="catalog")
    install_base_mocks(page, task, [])
    page.route("**/api/tasks/T1/catalog", lambda r: fulfill_json(r, tree))
    page.set_viewport_size({"width": 1366, "height": 768})
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(800)

    page.locator(".catalog-group").first.click()
    page.wait_for_timeout(400)

    metrics = page.evaluate(
        """() => {
            const panel = document.querySelector('.catalog-item-panel');
            const row = document.querySelector('.catalog-items .catalog-leaf-row');
            const details = row ? row.querySelector('.catalog-item-details') : null;
            const types = row ? row.querySelector('.catalog-item-types') : null;
            const ctx = document.querySelector('.context-sidebar');
            return {
                panelWidth: Math.round(panel.getBoundingClientRect().width),
                detailsWidth: details ? Math.round(details.getBoundingClientRect().width) : 0,
                typesWhiteSpace: types ? getComputedStyle(types).whiteSpace : null,
                contextSidebarHidden: !ctx || getComputedStyle(ctx).display === 'none',
            };
        }"""
    )
    assert metrics["panelWidth"] > 400, metrics
    assert metrics["detailsWidth"] > 250, metrics
    assert metrics["typesWhiteSpace"] == "normal", metrics
    assert metrics["contextSidebarHidden"], metrics


def test_single_duration_target_shows_setting_form(page, base_url):
    """只有 1 个计时内容时，不能跳过设置时长；应显示表单并预选。"""
    target = duration_target("g1", "唯一练习")
    task = task_snapshot(
        status="NEED_OPERATION",
        user_operation="CHOOSE_DURATION",
        practice_mode="duration",
        description="请选择要累计时长的学习内容",
        duration_targets=[target],
        selected_duration_targets=[target],
        duration_param="",
    )
    install_base_mocks(page, task, [])
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(700)

    assert page.locator("#duration-target-form").count() == 1
    # 预选勾选：用户只需确认并设时长
    assert page.evaluate("() => state.durationTargetSelection.size") == 1
    assert page.evaluate("() => state.durationTargetUnitSelection.size") == 1
    # 输入时长后按钮可用
    page.fill("#duration-per-practice", "45")
    page.wait_for_timeout(200)
    assert not page.evaluate("() => document.getElementById('duration-target-submit').disabled")
