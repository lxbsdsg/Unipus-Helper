from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_run_bat_creates_venv_and_launches():
    text = (ROOT / "run.bat").read_text(encoding="utf-8")
    assert ".venv" in text
    assert "pip install" in text
    assert "unipus_web" in text


def test_run_sh_launches_module():
    text = (ROOT / "run.sh").read_text(encoding="utf-8")
    assert "venv" in text
    assert "unipus_web" in text


def test_run_bat_keeps_window_open_and_forwards_args():
    text = (ROOT / "run.bat").read_text(encoding="utf-8")
    # 命令行参数必须透传，例如 --no-browser / --port
    assert "%*" in text
    # 服务停止或出错后窗口不能一闪而过
    assert "pause" in text
    assert "Ctrl+C" in text


def test_readme_documents_cmd_startup():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "命令行启动" in text
    assert "--no-browser" in text
    assert "Ctrl+C" in text


def test_run_cli_bat_is_a_fallback_to_terminal_mode():
    text = (ROOT / "run-cli.bat").read_text(encoding="utf-8")
    assert "--cli" in text
    assert "run.bat" in text


def test_readme_documents_cli_fallback():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "--cli" in text
    assert "备选" in text


def test_smoke_script_is_read_only():
    text = (ROOT / "scripts" / "smoke_login.py").read_text(encoding="utf-8")
    assert "get_course_list" in text
    assert "submit(" not in text
    assert "UNIPUS_USERNAME" in text


def test_readme_states_known_limitations():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "多小题" in text
    assert "已知限制" in text
    assert "127.0.0.1" in text
