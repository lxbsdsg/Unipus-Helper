"""问题报告导出（内存 zip，已脱敏）。"""

from __future__ import annotations

import io
import json
import re
import time
import zipfile

from ..config import VERSION
from ..network_log import redact_record

_SENSITIVE_URLS = (
    "https://sso.unipus.cn/sso/0.1/sso/login",
    "https://uai.unipus.cn/api/account/user/info",
    "uai.unipus.cn/api/tla/learningDetail/studyRecord/totalAndUnitSituation",
)

_PASSWORD_RE = re.compile(
    r'(?i)(password["\']?\s*[:=]\s*["\']?)([^"\'\s,}&]+)'
)


def _collect_sensitive(manager) -> list[str]:
    values: set[str] = set()
    for task in manager._tasks.values():  # 报告需要覆盖所有任务
        if task.username:
            values.add(task.username)
        user = task.user
        if user is not None:
            for value in (user.name, user.school_name, user.app_user_id, user.sso_id):
                if value:
                    values.add(value)
    return sorted(values, key=len, reverse=True)


def _redact_text(text: str, sensitive: list[str]) -> str:
    for value in sensitive:
        text = text.replace(value, "***")
    return _PASSWORD_RE.sub(r"\1***", text)


def build_report(manager) -> bytes:
    """生成报告 zip 的字节内容。"""
    sensitive = _collect_sensitive(manager)

    log_lines = []
    for record in manager.log_store.query(limit=0):
        line = (
            f"{record['ts']} [{record['level']}] "
            f"[{record.get('task_id') or '-'}] {record['message']}"
        )
        log_lines.append(_redact_text(line, sensitive))

    network_lines = []
    for record in manager.network.snapshot():
        if any(marker in record.get("url", "") for marker in _SENSITIVE_URLS):
            continue
        safe = redact_record(record)
        network_lines.append(_redact_text(json.dumps(safe, ensure_ascii=False), sensitive))

    meta = {
        "app": "Unipus Helper",
        "version": VERSION,
        "generated_at": int(time.time() * 1000),
        "tasks": [
            {
                "id": snap["id"],
                "name": snap["name"],
                "status": snap["status"],
                "progress": f"{snap['completed']}/{snap['total']}",
            }
            for snap in manager.snapshots()
        ],
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("logs.log", "\n".join(log_lines))
        archive.writestr("networks.jsonl", "\n".join(network_lines))
        archive.writestr(
            "meta.json", json.dumps(meta, ensure_ascii=False, indent=2)
        )
    return buffer.getvalue()
