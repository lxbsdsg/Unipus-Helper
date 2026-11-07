from pathlib import Path

WEB = Path(__file__).parents[1] / "unipus_web" / "web"


def test_required_elements_and_endpoints_exist():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "style.css").read_text(encoding="utf-8")

    for selector in [
        "task-list",
        "add-task",
        "debug-drawer",
        "report-modal",
        "theme-toggle",
        "empty-state",
        "log-list",
        "network-list",
        "stage-body",
        "stage-progress",
        "mode-options",
        "rail-add-task",
        "duration-per-practice",
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
        "/duration",
        "/duration/choose",
    ]:
        assert endpoint in js, f"缺少接口调用：{endpoint}"

    assert "localStorage" in js
    # 已保存账号走 credential_id，密码不进入浏览器存储
    assert "credential_id" in js
    assert "localStorage.setItem('password'" not in js
    # 目录批量选择只提交真正可练习的叶子，已完成/不可做题目不能被计入
    assert "catalogDescendantLeaves" in js
    assert "leaf.selectable" in js
    # 刷题两个范围共用一个入口，时长任务使用独立入口
    assert "function openPracticeSetup" in js
    assert "function startDuration" in js
    assert "formatDuration" in js
    # 时长内容支持并行多选
    assert "function courseCheckbox" in js
    assert "target_ids" in js
    # 时长支持固定秒数与随机范围两种输入，校验/摘要走同一处刷新
    assert "function durationParamValue" in js
    assert "function refreshDurationTargetForm" in js
    # 任务设置流程内嵌到中间工作区，不再叠 dialog
    assert 'id="practice-dialog"' not in html
    assert 'id="duration-target-dialog"' not in html
    assert 'id="course-dialog"' not in html
    assert 'id="catalog-dialog"' not in html
    assert "function renderStage" in js
    assert "function mountStageForm" in js
    assert "stage-templates" in html
    # 课程选择改成可展开的二级目录树，不再使用固定两列
    assert "function courseTreeItem" in js
    assert 'class="course-tree"' in html
    assert 'id="resource-options"' not in html
    # 设置表单是常驻模板：切换视图必须回收，不能从文档中删除后无法再次进入
    assert "function recycleStageForms" in js
    assert "recycleStageForms(body)" in js
    assert "body.dataset.taskId === task.id" in js
    # 关键提交后主动拉取快照，WebSocket 延迟/断线时界面也能推进
    assert js.count("await refreshTaskSnapshot") >= 4
    # 加载失败给出可重试的可见状态，而不是永远停在“正在加载”
    assert "function renderCourseLoadError" in js
    assert "load-error" in css
    assert "重试" in js
    # 课程树保留旧版单教程自动选中，收起不丢选择；表单提交有 in-flight 保护
    assert "resources.length === 1" in js
    assert "belongsToCourse" in js
    assert "state.courseSubmitting" in js
    assert "state.catalogSubmitting" in js
    assert "renderDurationCourseTimeout" in js
    # 计时内容支持单元整选/半选，并从计时内容返回课程选择
    assert "function setDurationUnitSelection" in js
    assert "function durationUnitCheckbox" in js
    assert "function backToCourseSelection" in js
    assert "返回课程" in js
    # 单元是独立整包选择：子项不自动点亮，提交前才展开为全部小节
    assert "durationTargetUnitSelection" in js
    assert "function durationEffectiveTargets" in js
    assert "整个单元" in js
    # 返回课程操作有 in-flight 保护，避免重复 restart
    assert "state.durationGoingBack" in js
    assert 'if (!taskId || state.durationGoingBack) return;' in js
    # 课程选择：目录内部滚动，确认按钮吸底常驻；手机端进入表单时自动滚到工作区
    assert ".stage-form-foot" in css
    assert "position: sticky" in css
    assert "clamp(168px, 34vh, 320px)" in css
    assert "scrollStageOnNextForm" in js
    # 吸底参数与 stage-body padding 用同一 CSS 变量；错误提示 margin 覆盖生效
    assert "--stage-body-padding" in css
    assert "var(--stage-body-padding)" in css
    assert "--stage-footer-shadow" in css
    assert "margin: 12px 20px !important" not in css
    # 所有模式入口在手机端一致地滚入工作台
    assert s.count("state.scrollStageOnNextForm = true") >= 5 if False else js.count("state.scrollStageOnNextForm = true") >= 5
    # READY 设置步骤可返回重新选择模式
    assert "重选模式" in js
    # 刷时长启动后课程列表由任务线程异步加载：不能立刻 GET /courses 拿空列表，
    # 必须等 NEED_OPERATION，并有轮询兜底与“未加载完成不吞渲染”保护
    assert "async function pollDurationCourseList" in js
    assert "pollDurationCourseList(taskId)" in js
    assert "courseListPending" in js
    assert "state.courseSelection.loaded" in js
    assert "state.courseRequestId" in js
    assert "openCourse(taskId, { mounted: true });\n    pollDurationCourseList" not in js


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
    assert "grid-template-columns: 260px minmax(0, 1fr)" in css
    assert "@media (max-width: 820px)" in css
