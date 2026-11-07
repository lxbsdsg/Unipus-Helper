"""Shared fixtures for mocked-browser E2E tests.

These tests never touch real accounts: all /api requests are intercepted.
They are skipped automatically when Playwright/Chromium is unavailable.
"""

from __future__ import annotations

import glob
import os
import socket
import threading
import time
import urllib.request

import pytest

playwright_api = pytest.importorskip("playwright.sync_api", reason="Playwright 未安装，跳过 E2E")

from unipus_web.app import create_app  # noqa: E402

WS_STUB = (
    "window.WebSocket = class {"
    " constructor() { this.listeners = {}; }"
    " addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); }"
    " removeEventListener() {}"
    " close() {}"
    "};"
)


UNSAFE_BROWSER_PORTS = {4045, 6666, 6000}

def _free_port() -> int:
    # Chromium blocks a small set of "unsafe" ports; skip those explicitly.
    for _ in range(100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            if port not in UNSAFE_BROWSER_PORTS:
                return port
    pytest.fail("无法选择浏览器可用端口")


@pytest.fixture(scope="session")
def base_url():
    app = create_app()
    port = _free_port()
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/"
    for _ in range(200):
        try:
            urllib.request.urlopen(url, timeout=0.2)
            break
        except OSError:
            time.sleep(0.05)
    else:
        pytest.fail("本地 E2E 服务启动失败")

    yield url
    server.should_exit = True
    thread.join(timeout=5)


def _launch_chromium(playwright):
    try:
        return playwright.chromium.launch(headless=True)
    except Exception:
        # pip 版 Playwright 与已安装浏览器缓存版本不一致时，回退到本机缓存。
        pattern = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "ms-playwright", "chromium-*", "chrome-win64", "chrome.exe"
        )
        for executable in sorted(glob.glob(pattern), reverse=True):
            try:
                return playwright.chromium.launch(headless=True, executable_path=executable)
            except Exception:
                continue
        pytest.skip("本机没有可用的 Chromium，跳过 E2E")


@pytest.fixture
def page(base_url):
    with playwright_api.sync_playwright() as playwright:
        browser = _launch_chromium(playwright)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script(WS_STUB)
        try:
            yield context.new_page()
        finally:
            context.close()
            browser.close()
