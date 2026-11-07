"""Reusable API mock fixtures for E2E tests."""

from __future__ import annotations

import json


def task_snapshot(**overrides):
    base = {
        "id": "T1",
        "username": "demo",
        "name": "演示任务",
        "status": "READY",
        "description": "登录成功，等待选择任务类型",
        "completed": 0,
        "total": 0,
        "progress_percent": 0,
        "user_name": "演示用户",
        "school_name": "演示学校",
        "user_operation": None,
        "practice_mode": "required",
        "duration_param": "",
        "duration_targets": [],
        "selected_duration_target": None,
        "selected_duration_targets": [],
        "courses": [],
        "warning": "",
        "error": "",
    }
    base.update(overrides)
    return base


def duration_target(group_id, name, unit="u1", unit_name="Unit 1", index=0):
    return {
        "group_id": group_id,
        "unit_id": unit,
        "unit_name": unit_name,
        "unit_index": index,
        "micro_id": "m" + group_id,
        "route_path": f"{unit}/{group_id}",
        "name": name,
        "path": f"{unit_name} / {name}",
    }


def course(course_id=101, name="大学英语 III"):
    return {
        "id": course_id,
        "name": name,
        "start_time": 0,
        "end_time": 0,
        "resources": [
            {
                "id": course_id * 10 + 1,
                "resource_id": f"r{course_id}",
                "instance_id": f"i{course_id}",
                "strategy_id": 0,
                "name": f"{name} 教程",
                "finish_point_num": 2,
                "total_point_num": 8,
            }
        ],
    }


def fulfill_json(route, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False)
    route.fulfill(status=status, content_type="application/json", body=body)


def install_base_mocks(page, task, courses=None):
    """Mock the boot endpoints plus task/course snapshots. Returns a state dict."""
    state = {"task": task, "courses": courses if courses is not None else [], "courses_calls": 0}

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
        elif url.endswith("/courses") and method == "GET":
            state["courses_calls"] += 1
            fulfill_json(route, state["courses"])
        elif "/api/tasks/T1" in url and method == "GET":
            fulfill_json(route, state["task"])
        else:
            fulfill_json(route, {"error": {"message": f"E2E mock 未覆盖: {method} {url}"}}, status=404)

    page.route("**/api/**", handler)
    return state
