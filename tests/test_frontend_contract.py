from pathlib import Path

WEB = Path(__file__).parents[1] / "unipus_web" / "web"


def test_required_elements_and_endpoints_exist():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    for selector in [
        "task-list",
        "add-task",
        "debug-drawer",
        "report-modal",
        "theme-toggle",
        "empty-state",
        "log-list",
        "network-list",
    ]:
        assert selector in html, f"缺少元素：{selector}"

    for endpoint in ["/api/tasks", "/api/logs", "/api/network", "/api/report", "/ws"]:
        assert endpoint in js, f"缺少接口调用：{endpoint}"

    assert "localStorage" in js
    # 已保存账号走 credential_id，密码不进入浏览器存储
    assert "credential_id" in js
    assert "localStorage.setItem('password'" not in js


def test_no_inline_external_scripts():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<script src="http' not in html
    assert "https://cdn" not in html


def test_styles_support_both_themes():
    css = (WEB / "style.css").read_text(encoding="utf-8")
    assert '[data-theme="dark"]' in css
    assert "prefers-reduced-motion" in css
    assert "focus-visible" in css
