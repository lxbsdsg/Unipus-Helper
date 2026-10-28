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
        "catalog-dialog",
        "catalog-tree",
        "catalog-select-all",
        "catalog-select-current",
        "catalog-items",
        "catalog-path",
        "catalog-search",
        "catalog-filter",
        "task-search",
    ]:
        assert selector in html, f"缺少元素：{selector}"

    for endpoint in [
        "/api/tasks",
        "/api/logs",
        "/api/network",
        "/api/report",
        "/ws",
        "/catalog",
        "/catalog/choose",
    ]:
        assert endpoint in js, f"缺少接口调用：{endpoint}"

    assert "localStorage" in js
    # 已保存账号走 credential_id，密码不进入浏览器存储
    assert "credential_id" in js
    assert "localStorage.setItem('password'" not in js
    # 目录批量选择只提交真正可练习的叶子，已完成/不可做题目不能被计入
    assert "catalogDescendantLeaves" in js
    assert "leaf.selectable" in js


def test_no_inline_external_scripts():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<script src="http' not in html
    assert "https://cdn" not in html


def test_styles_support_both_themes():
    css = (WEB / "style.css").read_text(encoding="utf-8")
    assert '[data-theme="dark"]' in css
    assert "prefers-reduced-motion" in css
    assert "focus-visible" in css


def test_catalog_ui_has_navigation_and_item_panes():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "style.css").read_text(encoding="utf-8")

    assert 'class="catalog-workbench"' in html
    assert ".catalog-workbench" in css
    assert "grid-template-columns: 310px minmax(0, 1fr)" in css
    assert "@media (max-width: 820px)" in css
