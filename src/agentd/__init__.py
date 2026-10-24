"""agentd — 可自托管的 Agent 运行时（HTTP/SSE API + Python SDK）。"""

from __future__ import annotations

from agentd.config import APP_VERSION as __version__
from agentd.sdk.client import AsyncClient, Client
from agentd.sdk.errors import (
    AgentdError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    ConnectionError,
    InternalServerError,
    InvalidRequestError,
    ModelError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ToolError,
)
from agentd.sdk.streaming import (
    MessageCompleted,
    MessageDelta,
    ReasoningDelta,
    RunCompleted,
    RunFailed,
    RunStarted,
    ToolCompleted,
    ToolStarted,
)

__all__ = [
    "APITimeoutError",
    "AgentdError",
    "AsyncClient",
    "AuthenticationError",
    "Client",
    "ConflictError",
    "ConnectionError",
    "InternalServerError",
    "InvalidRequestError",
    "MessageCompleted",
    "MessageDelta",
    "ModelError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "ReasoningDelta",
    "RunCompleted",
    "RunFailed",
    "RunStarted",
    "ToolCompleted",
    "ToolError",
    "ToolStarted",
    "__version__",
]
