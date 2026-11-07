import socket

from unipus_web import __main__ as entry


def test_preferred_port_is_tried_first(monkeypatch):
    seen = []
    monkeypatch.setattr(
        entry,
        "_is_port_available",
        lambda host, port: seen.append(port) or port == 8765,
    )

    assert entry.pick_port("127.0.0.1", 8765) == 8765
    assert seen == [8765]


def test_busy_preferred_port_is_skipped(monkeypatch):
    seen = []
    monkeypatch.setattr(
        entry,
        "_is_port_available",
        lambda host, port: seen.append(port) or port == 8766,
    )

    assert entry.pick_port("127.0.0.1", 8765) == 8766
    assert seen[0] == 8765


def test_falls_back_to_system_assigned_port(monkeypatch):
    monkeypatch.setattr(entry, "_is_port_available", lambda host, port: False)

    port = entry.pick_port("127.0.0.1")

    assert port not in entry.PORT_RANGE
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))


def test_is_port_available_rejects_listening_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]

        assert not entry._is_port_available("127.0.0.1", port)


def _mock_run_environment(monkeypatch, picked):
    monkeypatch.setattr(entry, "pick_port", lambda host, port=None: picked)
    monkeypatch.setattr(entry, "create_app", lambda **kwargs: object())
    started = {}
    monkeypatch.setattr(
        entry.uvicorn,
        "run",
        lambda app, host, port, **kwargs: started.update({"host": host, "port": port}),
    )
    return started


def test_explicit_port_does_not_warn_about_default_range(monkeypatch, capsys):
    started = _mock_run_environment(monkeypatch, 18789)

    entry.run("127.0.0.1", 18789, open_browser=False)

    assert "不可用" not in capsys.readouterr().out
    assert started == {"host": "127.0.0.1", "port": 18789}


def test_automatic_fallback_port_still_warns(monkeypatch, capsys):
    started = _mock_run_environment(monkeypatch, 18789)

    entry.run("127.0.0.1", None, open_browser=False)

    assert "8765-8799 端口不可用" in capsys.readouterr().out
    assert started == {"host": "127.0.0.1", "port": 18789}
