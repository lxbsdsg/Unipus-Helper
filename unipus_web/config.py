"""全局常量与协议参数。"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Unipus Helper"
VERSION = "2.0.0"

# 服务监听
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PORT_RANGE = range(8765, 8800)

# U校园接口
MAIN_HOST = "uai.unipus.cn"
SSO_HOST = "sso.unipus.cn"
CONTENT_HOST = "ucontent.unipus.cn"
USER_AGENT = "Unipus Helper/1.0"

# x-annotator-auth-token
ANNOTATOR_SECRET = "a824b379f126b8b7aa5e33dee83fb0a05aa7462c"
ANNOTATOR_ISSUER = "c4f772063dcfa98e9c50"
ANNOTATOR_AUDIENCE = "edx.unipus.cn"
ANNOTATOR_TOKEN_TTL_MS = 31_536_000_000  # 一年（毫秒）

# 提交限流
MAX_SUBMITS_PER_MINUTE = 5
SUBMIT_RATE_COOLDOWN_MS = 120_000

# 时间兜底：2100-01-01 左右的秒级时间戳
DEFAULT_TASK_END = 32503651200

# 缓冲区
LOG_BUFFER_SIZE = 5000
NETWORK_BUFFER_SIZE = 2048
RESPONSE_PEEK_LIMIT = 10 * 1024 * 1024  # 10 MB

# 数据目录
DATA_DIR = Path(os.environ.get("UNIPUS_DATA_DIR", Path.home() / ".unipus_helper")).resolve()
CREDENTIALS_FILE = DATA_DIR / "credentials.dat"
