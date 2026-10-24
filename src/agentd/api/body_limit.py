"""请求体大小限制中间件（M5 D3，纯 ASGI——同 RequestIDMiddleware 的理由）。

- 带 Content-Length：超限直接 413 错误信封，不读 body
- 无 Content-Length（分块）：先把 body 预读缓冲（v0.1 请求全是小 JSON，可行），
  超限同样在进入应用前 413——否则截断会被框架吞成 400，语义就丢了
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_TOO_LARGE_JSON = (
    b'{"error":{"code":"invalid_request","message":"request body too large",'
    b'"retryable":false,"request_id":""}}'
)
_FINAL_MESSAGE: Message = {"type": "http.request", "body": b"", "more_body": False}


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                await self._reject(send)  # 非法 Content-Length 一律拒绝
                return
            if declared > self.max_bytes:
                await self._reject(send)
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
                    await self._reject(send)
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

    async def _reject(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_TOO_LARGE_JSON)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _TOO_LARGE_JSON})
