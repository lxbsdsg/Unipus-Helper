"""本地加密凭据存储。

Windows：DPAPI（机器 + 用户绑定）。
其他平台：AES-GCM + 本地随机密钥文件（0600）。

密码永远不会出现在 `list()` 的返回值里。
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import CREDENTIALS_FILE

MAGIC = b"UHP1"
_KEY_SIZE = 32


# ------------------------------------------------------------------- DPAPI


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _make_blob(data: bytes):
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def _dpapi_protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    in_blob, in_buffer = _make_blob(data)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob)
    )
    if not ok:
        raise OSError(ctypes.GetLastError(), "CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    in_blob, in_buffer = _make_blob(data)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob)
    )
    if not ok:
        raise OSError(ctypes.GetLastError(), "CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


# --------------------------------------------------------------- 平台加解密


def _key_path(path: Path) -> Path:
    return path.with_name(path.name + ".key")


def _load_key(path: Path) -> bytes:
    key_path = _key_path(path)
    if key_path.exists():
        return key_path.read_bytes()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(_KEY_SIZE)
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


def _protect(data: bytes, path: Path) -> bytes:
    if sys.platform == "win32":
        return _dpapi_protect(data)
    key = _load_key(path)
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def _unprotect(data: bytes, path: Path) -> bytes:
    if sys.platform == "win32":
        return _dpapi_unprotect(data)
    key = _load_key(path)
    return AESGCM(key).decrypt(data[:12], data[12:], None)


# ------------------------------------------------------------------ 存储


class CredentialStore:
    def __init__(self, path: Path | str = CREDENTIALS_FILE) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._items: list[dict] = []
        self._load()

    # ---------------------------------------------------------- 内部读写

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = self.path.read_bytes()
            if raw.startswith(MAGIC):
                raw = raw[len(MAGIC):]
            plain = _unprotect(raw, self.path)
            data = json.loads(plain.decode("utf-8"))
            items = data.get("items")
            self._items = items if isinstance(items, list) else []
        except Exception:
            # 文件损坏或换了机器：备份后从空开始，不阻塞启动
            try:
                self.path.replace(
                    self.path.with_name(self.path.name + f".corrupt-{int(time.time())}")
                )
            except OSError:
                pass
            self._items = []

    def _save(self) -> None:
        payload = json.dumps(
            {"version": 1, "items": self._items}, ensure_ascii=False
        ).encode("utf-8")
        blob = MAGIC + _protect(payload, self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(blob)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ---------------------------------------------------------- 公共接口

    def list(self) -> list[dict]:
        with self._lock:
            return [
                {"id": item["id"], "username": item["username"], "label": item["label"]}
                for item in self._items
            ]

    def add(
        self,
        username: str,
        password: str,
        label: str = "",
        *,
        session: dict | None = None,
    ) -> dict:
        with self._lock:
            for item in self._items:
                if item["username"] == username:
                    session_changed = (
                        session is not None or item.get("password") != password
                    )
                    item["password"] = password
                    item["label"] = label or item.get("label", "")
                    if session_changed:
                        item["session"] = session or {}
                    self._save()
                    return {
                        "id": item["id"],
                        "username": item["username"],
                        "label": item["label"],
                    }
            item = {
                "id": uuid.uuid4().hex,
                "username": username,
                "label": label,
                "password": password,
                "session": session or {},
            }
            self._items.append(item)
            self._save()
            return {"id": item["id"], "username": username, "label": label}

    def get_secret(self, cred_id: str) -> tuple[str, str] | None:
        with self._lock:
            for item in self._items:
                if item["id"] == cred_id:
                    return item["username"], item["password"]
        return None

    def get_login_session(self, cred_id: str) -> dict | None:
        with self._lock:
            for item in self._items:
                if item["id"] == cred_id:
                    return item.get("session") or None
        return None

    def update_session(self, cred_id: str, session: dict) -> bool:
        with self._lock:
            for item in self._items:
                if item["id"] != cred_id:
                    continue
                item["session"] = session
                self._save()
                return True
        return False

    def delete(self, cred_id: str) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [item for item in self._items if item["id"] != cred_id]
            if len(self._items) == before:
                return False
            self._save()
            return True
