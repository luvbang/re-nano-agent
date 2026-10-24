"""Request-id 中间件（纯 ASGI）。

不用 BaseHTTPMiddleware：它对流式响应有缓冲/任务隔离问题，而 SSE 是 v0.1 的核心路径。
"""

from __future__ import annotations

import logging
import re
import secrets
import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agentd.log import request_id_var

logger = logging.getLogger("agentd.access")

_VALID_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp, *, header_name: str = "X-Request-Id") -> None:
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(self.header_name)
        request_id = (
            incoming if incoming and _VALID_ID.match(incoming) else f"req_{secrets.token_hex(8)}"
        )
        token = request_id_var.set(request_id)
        status_code = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                MutableHeaders(scope=message).append(self.header_name, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            metrics = getattr(getattr(scope.get("app"), "state", None), "metrics", None)
            if metrics is not None:
                metrics.inc("agentd_http_requests_total", status=str(status_code))
                metrics.observe("agentd_http_request_duration_seconds", duration_ms / 1000)
            logger.info(
                "http.request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
