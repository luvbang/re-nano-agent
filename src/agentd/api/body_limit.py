"""请求体大小限制中间件（M5 D3，纯 ASGI——同 RequestIDMiddleware 的理由）。

- 带 Content-Length：超限直接 413 错误信封，不读 body
- 无 Content-Length（分块）：先把 body 预读缓冲（v0.1 请求全是小 JSON，可行），
  超限同样在进入应用前 413——否则截断会被框架吞成 400，语义就丢了
"""

from __future__ import annotations

import json

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agentd.api.middleware import REQUEST_ID_HEADER, resolve_request_id

_FINAL_MESSAGE: Message = {"type": "http.request", "body": b"", "more_body": False}


def _request_id_for(scope: Scope) -> str:
    """413 也要带 request_id（契约 §4）；本中间件在 RequestIDMiddleware 之外，自行解析。"""
    return resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))


def _too_large_body(request_id: str) -> bytes:
    return json.dumps(
        {
            "error": {
                "code": "invalid_request",
                "message": "request body too large",
                "retryable": False,
                "request_id": request_id,
            }
        }
    ).encode()


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        # 本中间件在 RequestIDMiddleware 之外，届时 request_id 还没生成；自行解析一份，
        # 保证 413 也满足契约 §4（错误体 request_id 与响应头一致且非空）。
        request_id = _request_id_for(scope)
        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                await self._reject(send, request_id)  # 非法 Content-Length 一律拒绝
                return
            if declared > self.max_bytes:
                await self._reject(send, request_id)
                return
            await self.app(scope, receive, send)
            return

        # 分块：预读缓冲，超限拒绝
        buffered: list[Message] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                buffered.insert(0, message)
                break
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    await self._reject(send, request_id)
                    return
                buffered.append(message)
                if not message.get("more_body"):
                    break

        index = 0

        async def replay() -> Message:
            nonlocal index
            if index < len(buffered):
                message = buffered[index]
                index += 1
                return message
            return _FINAL_MESSAGE

        await self.app(scope, replay, send)

    async def _reject(self, send: Send, request_id: str = "") -> None:
        body = _too_large_body(request_id)
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (REQUEST_ID_HEADER.lower().encode(), request_id.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
