"""agentd 平台 Python SDK。

    from agentd_client import Client, AsyncClient

    client = Client(base_url="https://agent.example.com", api_key="agd_...")
    session = client.create_session(title="demo")
    run = client.create_run(session["id"], input="你好")
    for event in client.stream(run["run_id"]):
        if event.type == "message.delta":
            print(event.data["delta"], end="")
"""

from agentd_client.core import DEFAULT_BASE_URL, AsyncClient, StreamEvent
from agentd_client.errors import (
    AgentdError,
    AuthenticationError,
    ConflictError,
    ModelError,
    NetworkError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerTimeoutError,
    ValidationError,
)
from agentd_client.sync import Client

__all__ = [
    "DEFAULT_BASE_URL",
    "AgentdError",
    "AsyncClient",
    "AuthenticationError",
    "Client",
    "ConflictError",
    "ModelError",
    "NetworkError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServerTimeoutError",
    "StreamEvent",
    "ValidationError",
]
