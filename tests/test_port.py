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
