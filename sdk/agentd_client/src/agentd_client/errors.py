"""类型化错误（对齐服务端错误信封 docs/api-contract.md §4）。"""

from __future__ import annotations

from typing import Any


class AgentdError(Exception):
    """SDK 错误基类。retryable=True 的错误会被自动重试（除流式消费）。"""

    code = "internal"
    retryable = False

    def __init__(self, message: str, *, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload = payload or {}


class ValidationError(AgentdError):
    code = "invalid_request"


class AuthenticationError(AgentdError):
    code = "unauthorized"


class PermissionDeniedError(AgentdError):
    code = "forbidden"


class NotFoundError(AgentdError):
    code = "not_found"


class ConflictError(AgentdError):
    code = "conflict"


class RateLimitError(AgentdError):
    code = "rate_limited"
    retryable = True

    def __init__(self, message: str, *, payload: dict[str, Any] | None = None,
                 retry_after_s: float | None = None) -> None:
        super().__init__(message, payload=payload)
        self.retry_after_s = retry_after_s


class ModelError(AgentdError):
    code = "model_error"
    retryable = True


class ServerTimeoutError(AgentdError):
    code = "timeout"
    retryable = True


class NetworkError(AgentdError):
    """传输层错误（连接失败/断流）。可重试。"""

    code = "network"
    retryable = True


_BY_CODE: dict[str, type[AgentdError]] = {
    cls.code: cls
    for cls in (
        ValidationError,
        AuthenticationError,
        PermissionDeniedError,
        NotFoundError,
        ConflictError,
        RateLimitError,
        ModelError,
        ServerTimeoutError,
    )
}


def from_envelope(payload: dict[str, Any], *, status_code: int) -> AgentdError:
    code = str(payload.get("code") or "internal")
    message = str(payload.get("message") or "请求失败")
    cls = _BY_CODE.get(code, AgentdError)
    if cls is RateLimitError:
        return RateLimitError(message, payload=payload)
    error = cls(message, payload=payload)
    error.retryable = bool(payload.get("retryable", cls.retryable))
    if status_code >= 500 and not isinstance(error, (ModelError, ServerTimeoutError)):
        # 信封之外的 5xx 一律视作可重试的服务端错误
        error.retryable = True
    return error
