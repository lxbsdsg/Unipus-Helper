import hashlib
import hmac
import json

from unipus_web import crypto


def test_jwt_header_payload_and_signature():
    token = crypto.generate_auth_token("openid-123", now_ms=1_700_000_000_000)
    h, p, s = token.split(".")
    header = json.loads(crypto.b64url_decode(h))
    payload = json.loads(crypto.b64url_decode(p))

    assert header == {"alg": "HS256", "typ": "JWT"}
    assert payload["open_id"] == "openid-123"
    assert payload["name"] == ""
    assert payload["email"] == ""
    assert payload["administrator"] is False
    assert payload["exp"] == 1_700_000_000_000 + 31_536_000_000  # 毫秒
    assert payload["iss"] == "c4f772063dcfa98e9c50"
    assert payload["aud"] == "edx.unipus.cn"

    expected = hmac.new(
        b"a824b379f126b8b7aa5e33dee83fb0a05aa7462c",
        f"{h}.{p}".encode(),
        hashlib.sha256,
    ).digest()
    assert crypto.b64url_decode(s) == expected


def test_decrypt_answer_known_vector():
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = b"1a2b3c4d20250627"
    plain = b'{"id":1}'
    padded = plain + b"\x00" * (-len(plain) % 16)
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    cipher_hex = (enc.update(padded) + enc.finalize()).hex()

    assert crypto.decrypt_answer("unipus." + cipher_hex, "20250627") == '{"id":1}'


def test_decrypt_passthrough_and_bad_key():
    assert crypto.decrypt_answer("plain", "x") == "plain"
    assert crypto.decrypt_answer(None, None) == ""


def test_sanitize_keeps_chinese_and_punctuation_replaces_emoji():
    # 白名单允许 ASCII '?' 但不允许 ASCII '!'，与 U校园 后端保持一致
    assert crypto.sanitize_answer("你好，world? 123") == "你好，world? 123"
    assert crypto.sanitize_answer("hi!") == "hi "
    assert crypto.sanitize_answer("a😀b") == "a b"


def test_html_to_text_handles_br_and_entities():
    text = crypto.html_to_text("<p>Hello&nbsp;<b>world</b></p><p>second</p>")
    assert text.splitlines()[0] == "Hello world"
    assert "second" in text
