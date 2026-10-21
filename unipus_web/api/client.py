"""U校园 HTTP 客户端。

所有端点、header 与字段名均以接口契约为准。
"""

from __future__ import annotations

import json
import time
from typing import Callable

import httpx

from ..config import (
    CONTENT_HOST,
    MAIN_HOST,
    RESPONSE_PEEK_LIMIT,
    SSO_HOST,
    USER_AGENT,
)
from ..crypto import generate_auth_token
from ..models import as_str
from .errors import ApiError, AuthError, NetworkError

RecordHook = Callable[[dict], None]


class UnipusClient:
    def __init__(
        self,
        task_id: str,
        *,
        record: RecordHook | None = None,
        proxy: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.task_id = task_id
        self._record = record
        self._client = httpx.Client(
            proxy=proxy,
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
        )

    # ------------------------------------------------------------ 基础设施

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def _emit_record(
        self,
        *,
        method: str,
        url: str,
        response: httpx.Response | None,
        duration_ms: int,
        error: str | None,
        request_payload: str | None,
    ) -> None:
        if self._record is None:
            return
        try:
            response_body = None
            if response is not None:
                try:
                    response_body = response.text[:RESPONSE_PEEK_LIMIT]
                except Exception:
                    response_body = None
            self._record(
                {
                    "ts": int(time.time() * 1000),
                    "task_id": self.task_id,
                    "method": method,
                    "url": url,
                    "status_code": response.status_code if response is not None else None,
                    "status_text": response.reason_phrase if response is not None else "",
                    "duration_ms": duration_ms,
                    "request_headers": dict(response.request.headers)
                    if response is not None
                    else {},
                    "response_headers": dict(response.headers) if response is not None else {},
                    "request_payload": request_payload,
                    "response_body": response_body,
                    "error": error,
                }
            )
        except Exception:
            pass

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict | None = None,
        raw_body: str | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        merged = {"User-Agent": USER_AGENT, "Connection": "keep-alive"}
        if headers:
            merged.update(headers)
        if raw_body is not None:
            merged.setdefault("Content-Type", "application/json; charset=utf-8")

        payload_for_log = (
            json.dumps(json_body, ensure_ascii=False) if json_body is not None else raw_body
        )
        start = time.perf_counter()
        response: httpx.Response | None = None
        error_text: str | None = None
        try:
            response = self._client.request(
                method, url, json=json_body, content=raw_body, headers=merged
            )
            return response
        except httpx.HTTPError as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            raise NetworkError(f"网络请求失败：{exc}") from exc
        finally:
            self._emit_record(
                method=method,
                url=url,
                response=response,
                duration_ms=int((time.perf_counter() - start) * 1000),
                error=error_text,
                request_payload=payload_for_log,
            )

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        if response.status_code >= 400:
            raise ApiError(response.status_code, f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError(response.status_code, "服务端返回了非 JSON 内容") from exc
        if not isinstance(data, dict):
            raise ApiError(response.status_code, "服务端返回了非对象 JSON")
        return data

    @staticmethod
    def _url(host: str, path: str) -> str:
        return f"https://{host}/{path.lstrip('/')}"

    # ---------------------------------------------------------------- 登录

    def login(self, username: str, password: str) -> dict:
        data = self._json(
            self._request(
                "POST",
                self._url(SSO_HOST, "sso/0.1/sso/login"),
                json_body={
                    "username": username,
                    "password": password,
                    "remember": True,
                    "agreement": True,
                    "service": "https://uai.unipus.cn/home",
                },
            )
        )
        rs = data.get("rs")
        if not isinstance(rs, dict):
            raise AuthError(as_str(data.get("msg"), "账号或密码错误"))
        return rs

    def get_user_info(self) -> dict:
        return self._json(
            self._request(
                "GET",
                self._url(MAIN_HOST, "api/account/user/info"),
                headers={"Authorization": ""},
            )
        )

    # ---------------------------------------------------------------- 课程

    def get_course_list(self) -> dict:
        return self._json(
            self._request(
                "GET",
                self._url(MAIN_HOST, "api/cmgt/course/getCourseListByStudent"),
                headers={"Authorization": ""},
            )
        )

    def get_course_resource_info(self, resource_id: str) -> dict:
        return self._json(
            self._request(
                "GET",
                self._url(
                    MAIN_HOST, f"api/cmgt/course/getCourseResourceInfoById/{resource_id}"
                ),
                headers={"Authorization": ""},
            )
        )

    def get_all_tasks(self, course_instance_id: str) -> dict:
        return self._json(
            self._request(
                "GET",
                self._url(
                    CONTENT_HOST, f"course/api/course/{course_instance_id}/default"
                ),
                headers={"Authorization": ""},
            )
        )

    def get_required_part(self, strategy_id: int, course_resource_id: str) -> dict:
        return self._json(
            self._request(
                "POST",
                self._url(MAIN_HOST, "api/tla/courseStudyStrategy/detail"),
                json_body={"id": strategy_id, "courseResourceId": course_resource_id},
                headers={"Authorization": ""},
            )
        )

    def get_total_and_unit_situation(self, resource_id: int, app_user_id: str) -> dict:
        query = httpx.QueryParams({"id": str(resource_id), "appUserId": app_user_id})
        return self._json(
            self._request(
                "GET",
                self._url(MAIN_HOST, "api/tla/learningDetail/studyRecord/totalAndUnitSituation")
                + f"?{query}",
                headers={"Authorization": ""},
            )
        )

    def get_unit_task_situation(
        self, node_id: str, resource_id: int, app_user_id: str, sso_id: str
    ) -> dict:
        query = httpx.QueryParams(
            {
                "nodeId": node_id,
                "id": str(resource_id),
                "appUserId": app_user_id,
                "ssoId": sso_id,
            }
        )
        return self._json(
            self._request(
                "GET",
                self._url(MAIN_HOST, "api/tla/learningDetail/studyRecord/unitTaskSituation")
                + f"?{query}",
                headers={"Authorization": ""},
            )
        )

    # ---------------------------------------------------------- 任务与答题

    def get_task_time_info(
        self, course_instance_id: str, open_id: str, unit_node_id: str
    ) -> dict:
        return self._json(
            self._request(
                "GET",
                self._url(
                    CONTENT_HOST,
                    f"course/api/v2/course_progress/{course_instance_id}/{unit_node_id}/{open_id}/default",
                ),
                headers={
                    "Authorization": "",
                    "x-annotator-auth-token": generate_auth_token(open_id),
                },
            )
        )

    def get_answer(self, course_instance_id: str, task_id: str, open_id: str) -> dict:
        return self._json(
            self._request(
                "GET",
                self._url(
                    CONTENT_HOST, f"course/api/v3/answer/{course_instance_id}/{task_id}/default"
                ),
                headers={
                    "Authorization": "",
                    "x-annotator-auth-token": generate_auth_token(open_id),
                },
            )
        )

    def submit(self, body: str, open_id: str) -> dict:
        return self._json(
            self._request(
                "POST",
                self._url(CONTENT_HOST, "course/api/v3/newExploration/submit"),
                raw_body=body,
                headers={"x-annotator-auth-token": generate_auth_token(open_id)},
            )
        )

    def get_task_info(
        self, course_instance_id: str, task_id: str, version: str, open_id: str
    ) -> dict:
        return self._json(
            self._request(
                "GET",
                self._url(
                    CONTENT_HOST,
                    f"api/mobile/user_module/{course_instance_id}/{task_id}-{version}",
                ),
                headers={
                    "Authorization": "",
                    "x-annotator-auth-token": generate_auth_token(open_id),
                },
            )
        )
