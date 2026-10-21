from unipus_web.credentials import CredentialStore


def test_add_list_get_delete_roundtrip(tmp_path):
    store = CredentialStore(tmp_path / "cred.dat")
    item = store.add("13800000000", "secret-pw", "测试账号")
    assert store.list()[0]["username"] == "13800000000"
    assert store.get_secret(item["id"]) == ("13800000000", "secret-pw")
    assert store.delete(item["id"]) is True
    assert store.list() == []


def test_file_does_not_contain_plaintext_password(tmp_path):
    path = tmp_path / "cred.dat"
    CredentialStore(path).add("u", "very-secret-pw")
    assert b"very-secret-pw" not in path.read_bytes()


def test_duplicate_username_updates_existing(tmp_path):
    store = CredentialStore(tmp_path / "cred.dat")
    first = store.add("u", "p1")
    second = store.add("u", "p2")
    assert first["id"] == second["id"]
    assert store.get_secret(second["id"]) == ("u", "p2")


def test_list_never_exposes_password(tmp_path):
    store = CredentialStore(tmp_path / "cred.dat")
    store.add("u", "p")
    assert set(store.list()[0]) == {"id", "username", "label"}


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "cred.dat"
    CredentialStore(path).add("u", "p")
    assert CredentialStore(path).get_secret(CredentialStore(path).list()[0]["id"]) == (
        "u",
        "p",
    )
