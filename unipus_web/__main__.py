"""命令行入口：python -m unipus_web。"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser

import uvicorn

from .app import create_app
from .config import DEFAULT_PORT, HOST, PORT_RANGE


def pick_port(host: str, preferred: int | None = None) -> int:
    candidates = [preferred] if preferred else []
    candidates += [port for port in PORT_RANGE if port != preferred]
    for port in candidates:
        if port is None:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit("端口 8765-8799 全部被占用，无法启动。")


def run(
    host: str = HOST,
    port: int | None = None,
    *,
    open_browser: bool = True,
    allow_multi_question: bool = True,
    proxy: str | None = None,
) -> None:
    actual_port = pick_port(host, port)
    app = create_app(
        allow_multi_question=allow_multi_question,
        proxy=proxy,
    )
    url = f"http://{host}:{actual_port}/"
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    print("=" * 56, flush=True)
    print("  Unipus Helper", flush=True)
    print(f"  地址：{url}", flush=True)
    print("  按 Ctrl+C 停止服务", flush=True)
    print("=" * 56, flush=True)

    uvicorn.run(app, host=host, port=actual_port, log_config=None, log_level="info")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unipus Helper Web")
    parser.add_argument("--host", default=HOST, help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument(
        "--no-multi-question",
        action="store_true",
        help="关闭实验性的多小题提交",
    )
    parser.add_argument("--proxy", default=None, help="HTTP 代理，如 http://127.0.0.1:7890")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="终端备选模式：不启动 Web UI，直接在 cmd 里运行",
    )
    parser.add_argument("--username", default=None, help="CLI 模式账号")
    parser.add_argument(
        "--password", default=None, help="CLI 模式密码（建议改用环境变量）"
    )
    parser.add_argument(
        "--yes", action="store_true", help="CLI 模式自动选择第一个课程/教程"
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="CLI 模式不交互提问；缺少凭据或多课程时直接失败",
    )
    args = parser.parse_args(argv)

    if args.cli:
        from .cli import run_cli

        return run_cli(
            username=args.username,
            password=args.password,
            proxy=args.proxy,
            allow_multi_question=not args.no_multi_question,
            assume_yes=args.yes,
            allow_prompt=not args.no_prompt,
        )

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "警告：当前监听地址不是回环地址，本程序没有访问鉴权，请勿在不可信网络中使用。",
            file=sys.stderr,
        )

    run(
        args.host,
        args.port,
        open_browser=not args.no_browser,
        allow_multi_question=not args.no_multi_question,
        proxy=args.proxy,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
