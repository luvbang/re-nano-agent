"""PinnedIPTransport 测试（v0.2）：URL 重写、Host/SNI 保留、工具集成钉点。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

import agentd.tools.web as web_module
from agentd.security.pinned import PinnedIPTransport
from agentd.tools.web import WebFetchTool

PINNED_IP = "93.184.216.34"


class RecordingTransport(httpx.AsyncBaseTransport):
    """捕获 inner 收到的请求（钉点后的形态）。"""

    def __init__(self) -> None:
        self.captured: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured = request
        return httpx.Response(200)


async def test_request_rewritten_to_pinned_ip() -> None:
    inner = RecordingTransport()
    transport = PinnedIPTransport(PINNED_IP, inner=inner)

    request = httpx.Request("GET", "https://ok.example/page")
    await transport.handle_async_request(request)

    captured = inner.captured
    assert captured is not None
    assert captured.url.host == PINNED_IP  # 连接目标 = 钉住的 IP
    assert captured.headers.get("Host") == "ok.example"  # Host 保持原主机名
    assert captured.extensions.get("sni_hostname") == "ok.example"  # TLS SNI/校验用原主机名


async def test_post_body_preserved() -> None:
    inner = RecordingTransport()
    transport = PinnedIPTransport(PINNED_IP, inner=inner)
    request = httpx.Request(
        "POST", "https://ok.example/api", content=b'{"a": 1}',
        headers={"content-type": "application/json"},
    )
    await transport.handle_async_request(request)
    assert inner.captured is not None
    assert (await inner.captured.aread()) == b'{"a": 1}'


@respx.mock
async def test_tool_pins_first_resolved_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_ips: list[str] = []

    class SpyTransport(PinnedIPTransport):
        def __init__(self, pinned_ip: str, **kwargs: Any) -> None:
            captured_ips.append(pinned_ip)
            super().__init__(pinned_ip, **kwargs)

    respx.get(f"https://{PINNED_IP}/page").mock(
        return_value=httpx.Response(200, text="页面内容", headers={"content-type": "text/html"})
    )
    monkeypatch.setattr(web_module, "PinnedIPTransport", SpyTransport)
    tool = WebFetchTool(validator=lambda url: [PINNED_IP])

    result = await tool.execute({"url": "https://ok.example/page"})

    assert not result.is_error
    assert "页面内容" in result.content
    assert captured_ips == [PINNED_IP]  # validator 返回的第一个 IP 被钉进连接层
