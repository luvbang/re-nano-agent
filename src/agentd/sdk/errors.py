"""SDK 异常层级（M4）：类型对应契约错误码（api-contract §4）。

自动重试仅作用于 retryable 且传输层可重试的错误（ConnectionError / 429 / 502 / 504）。
"""

from __future__ import annotations

from typing import Any


class AgentdError(Exception):
    """SDK 错误基类；code 为契约错误码。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "internal",
        status: int = 0,
        retryable: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.retryable = retryable
        self.request_id = request_id

    def __str__(self) -> str:
        prefix = f"[{self.code}]"
        rid = f" request_id={self.request_id}" if self.request_id else ""
        return f"{prefix} {self.message}{rid}"


class AuthenticationError(AgentdError):
    """401：缺 key / key 不存在 / 已撤销。"""


class PermissionDeniedError(AgentdError):
    """403：key 无权访问（如非 admin 调管理端点）。"""


class NotFoundError(AgentdError):
    """404：资源不存在（跨项目一律 404）。"""


class ConflictError(AgentdError):
    """409：同 session 并发 run / 幂等键冲突。"""


class RateLimitError(AgentdError):
    """429：超出限流；retry_after_s 为建议等待秒数。"""

    def __init__(self, *args: Any, retry_after_s: float | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retry_after_s = retry_after_s


class ModelError(AgentdError):
    """502：上游模型错误。"""


class ToolError(AgentdError):
    """422：工具执行失败。"""


class APITimeoutError(AgentdError):
    """504：run 超时 / 上游超时。"""


class InvalidRequestError(AgentdError):
    """400：参数校验失败。"""


class InternalServerError(AgentdError):
    """500：未预期异常。"""


class ConnectionError(AgentdError):  # noqa: A001 — 与内置同名是有意的（网络层语义）
    """网络层失败（连不上 / 断流）；retryable。"""

    def __init__(self, message: str = "无法连接 agentd 服务") -> None:
        super().__init__(message, code="network_error", retryable=True)


_CODE_TO_ERROR: dict[str, type[AgentdError]] = {
    "unauthorized": AuthenticationError,
    "forbidden": PermissionDeniedError,
    "not_found": NotFoundError,
    "conflict": ConflictError,
    "rate_limited": RateLimitError,
    "model_error": ModelError,
    "tool_error": ToolError,
    "timeout": APITimeoutError,
    "invalid_request": InvalidRequestError,
    "internal": InternalServerError,
}


def error_from_body(status: int, body: dict[str, Any]) -> AgentdError:
    """把错误信封（{"error": {...}}）映射为具体异常；未知 code 落基类。"""
    err = body.get("error") if isinstance(body, dict) else None
    if not isinstance(err, dict):
        return InternalServerError(f"HTTP {status}", status=status)
    code = str(err.get("code", "internal"))
    cls = _CODE_TO_ERROR.get(code, AgentdError)
    message = str(err.get("message", f"HTTP {status}"))
    retryable = bool(err.get("retryable", False))
    request_id = err.get("request_id")
    if cls is RateLimitError:
        return RateLimitError(
            message, code=code, status=status, retryable=retryable, request_id=request_id
        )
    if issubclass(cls, AgentdError):
        return cls(
            message, code=code, status=status, retryable=retryable, request_id=request_id
        )
    return AgentdError(message, code=code, status=status, retryable=retryable)  # pragma: no cover
