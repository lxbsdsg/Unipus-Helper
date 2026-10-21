"""只读冒烟脚本：登录并拉取课程列表，不提交任何答案。

用法：
    set UNIPUS_USERNAME=你的账号
    set UNIPUS_PASSWORD=你的密码
    .venv\\Scripts\\python.exe scripts\\smoke_login.py

或者直接运行，按提示输入。
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unipus_web.api.client import UnipusClient  # noqa: E402
from unipus_web.api.errors import UnipusError  # noqa: E402
from unipus_web.models import Course, lenient_obj  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Unipus Helper 只读登录冒烟")
    parser.add_argument(
        "--username", default=os.environ.get("UNIPUS_USERNAME"), help="账号"
    )
    parser.add_argument("--proxy", default=None, help="HTTP 代理")
    args = parser.parse_args()

    username = args.username or input("U校园账号: ").strip()
    password = os.environ.get("UNIPUS_PASSWORD") or getpass.getpass("密码: ")

    client = UnipusClient("smoke-login", proxy=args.proxy)
    try:
        rs = client.login(username, password)
        print(f"登录成功：openid={rs.get('openid', '')[:8]}…")

        user = client.get_user_info()
        info = lenient_obj(lenient_obj(user.get("value")).get("userInfo"))
        print(f"用户：{info.get('name', '')} / {info.get('schName', '')}")

        data = client.get_course_list()
        raw_courses = lenient_obj(data.get("value")).get("courseList")
        courses = (
            [Course.from_json(item) for item in raw_courses]
            if isinstance(raw_courses, list)
            else []
        )
        print(f"课程数：{len(courses)}")
        for course in courses:
            print(f"- {course.name}（{len(course.resources)} 个教程）")
    except UnipusError as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    print("冒烟完成：只读取了登录信息与课程列表，没有提交任何答案。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
