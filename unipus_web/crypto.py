"""加密与文本工具。

- JWT：x-annotator-auth-token（HS256，exp 为毫秒）
- AES：解密 U校园答案（AES/ECB/NoPadding）
- 文本：HTML → 纯文本、提交前非法字符清洗
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .config import (
    ANNOTATOR_AUDIENCE,
    ANNOTATOR_ISSUER,
    ANNOTATOR_SECRET,
    ANNOTATOR_TOKEN_TTL_MS,
)

_IV = b"\x00" * 16
_AES_BLOCK = 16
_VALID_KEY_SIZES = (16, 24, 32)


# ---------------------------------------------------------------- base64url


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


# --------------------------------------------------------------------- JWT


def generate_auth_token(open_id: str, *, now_ms: int | None = None) -> str:
    """生成 x-annotator-auth-token 所需的 HS256 JWT。"""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "open_id": open_id or "",
        "name": "",
        "email": "",
        "administrator": False,
        "exp": (now_ms if now_ms is not None else int(time.time() * 1000))
        + ANNOTATOR_TOKEN_TTL_MS,
        "iss": ANNOTATOR_ISSUER,
        "aud": ANNOTATOR_AUDIENCE,
    }
    segments = [
        b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
        b64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(
        ANNOTATOR_SECRET.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    segments.append(b64url_encode(signature))
    return ".".join(segments)


# --------------------------------------------------------------------- AES


def hex_to_bytes(s: str) -> bytes:
    if len(s) % 2:
        s = "0" + s
    return bytes.fromhex(s)


def _normalise_key(raw: bytes) -> bytes:
    size = len(raw)
    if size > 32:
        raise ValueError(f"AES key too long: {size} bytes")
    for valid in _VALID_KEY_SIZES:
        if size <= valid:
            return raw + b"\x00" * (valid - size)
    raise ValueError(f"Invalid AES key length: {size} bytes")


def decrypt_answer(data_with_prefix: str | None, k: str | None) -> str:
    """解密 "unipus.<hex>" 答案；非密文或空值原样返回。"""
    if not data_with_prefix:
        return ""
    if not data_with_prefix.startswith("unipus."):
        return data_with_prefix

    key = _normalise_key(b"1a2b3c4d" + (k or "").encode("utf-8"))
    cipher_bytes = hex_to_bytes(data_with_prefix[len("unipus."):])
    # NoPadding：密文按 16 字节块对齐
    cipher_bytes = cipher_bytes + b"\x00" * (-len(cipher_bytes) % _AES_BLOCK)

    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = decryptor.update(cipher_bytes) + decryptor.finalize()
    return padded.rstrip(b"\x00").decode("utf-8", errors="replace")


# -------------------------------------------------------------------- 文本


def html_to_text(html: str | None) -> str:
    """把 HTML 转成纯文本，保留段落/换行语义。"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.insert(0, "\n")
        p.append("\n")

    text = soup.get_text()
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# U校园后端允许的字符集合（逐区间实现，不得随意增删）
_ALLOWED = (
    r"a-zA-Z"
    "Ёё"          # Ё ё
    "À-ÿ"         # À-ÿ
    r"0-9"
    "一-龥"         # 一-龥
    "Ѐ-ӿ"         # Ѐ-ӿ
    "＀-￯"
    "￰-￿"
    "　"                # 全角空格
    "⼀-⿟"
    "㐀-䶵"
    "豈-﫿"
    ""
    "가-힯"
    "ᄀ-ᇿ"
    "㄰-㆏"
    "ꥠ-꥿"
    "ힰ-퟿"
    "぀-ゟ"
    "゠-ヿ"
    "ㇰ-ㇿ"
    "Ā-ſ"
    "\u0080-ÿ"
    "Ḁ-ỿ"
    "《》（）+=_￥¥。，、;:：；【】…？！！”“’‘•·„€「」『』々ヽヾ"
    r"\[\],\.\{\}\(\)<>\?/\|`~\"'@#\$%&*"
    r"\\\-"
    r"\s"
)

_ILLEGAL_RE = re.compile("[^" + _ALLOWED + "]")


def sanitize_answer(text: str) -> str:
    """把 U校园不允许的字符替换为空格。"""
    if not text:
        return ""
    return _ILLEGAL_RE.sub(" ", text)
