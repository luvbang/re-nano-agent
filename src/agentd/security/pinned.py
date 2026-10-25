"""SSRF pinned transport（v0.2）：把校验时解析到的 IP 钉成实际连接目标。

M2 登记的技术债：assert_public_url 校验与 httpx 实际建连之间存在 DNS TOCTOU
窗口——校验时解析到公网 IP，连接时 DNS 可能已被改写（DNS rebinding）。

本 transport 把请求 URL 的 host 直接改写为校验阶段拿到的 IP：
- TCP/TLS 连接目标是钉住的 IP；
- TLS 的 SNI 与证书校验仍用原主机名（httpcore 请求扩展 sni_hostname）；
- Host 头保持原主机名（多数网关按 Host 路由）；
- URL/响应对上层完全透明（页面内容、重定向逻辑不受影响）。

限制：多个解析记录时只钉第一个（A 记录轮询的容错由连接失败重试兜底）。
"""

from __future__ import annotations

import httpx


class PinnedIPTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        pinned_ip: str,
        *,
        inner: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._pinned_ip = pinned_ip
        # 超时由 client 的请求扩展传给 httpcore，transport 不另设
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        pinned_url = request.url.copy_with(host=self._pinned_ip)
        headers = request.headers.copy()
        headers["Host"] = host
        new_request = httpx.Request(
            request.method,
            pinned_url,
            headers=headers,
            content=await request.aread(),
            extensions={**request.extensions, "sni_hostname": host},
        )
        return await self._inner.handle_async_request(new_request)
