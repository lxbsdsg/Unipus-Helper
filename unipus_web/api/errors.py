"""领域异常。"""

from __future__ import annotations


class UnipusError(Exception):
    """所有业务异常的基类。"""


class NetworkError(UnipusError):
    """网络不可达、超时、连接被重置。"""


class AuthError(UnipusError):
    """账号、密码或登录态无效。"""


class ApiError(UnipusError):
    """服务端返回了错误状态码或无法解析的内容。"""

    def __init__(self, code: int | str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class UnsupportedError(UnipusError):
    """题型或数据结构暂不支持。"""


class TaskStopped(Exception):
    """协作式停止信号，不是错误。"""
