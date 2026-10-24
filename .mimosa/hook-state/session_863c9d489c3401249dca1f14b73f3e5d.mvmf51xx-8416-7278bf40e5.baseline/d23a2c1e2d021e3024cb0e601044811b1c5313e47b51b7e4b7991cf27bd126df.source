"""web 工具（M2 D3）：web_fetch。

每一跳（含重定向）都过 ``security.ssrf.assert_url_allowed``；响应按字节上限截断、
只接受文本类 Content-Type。resolver 可注入（测试离线注入公网/内网解析结果）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from agentd.providers.base import ToolDefinition
from agentd.security.ssrf import SsrfBlockedError, assert_url_allowed
from agentd.tools.base import Tool, ToolResult

MAX_REDIRECTS = 3
FETCH_TIMEOUT_S = 15.0
MAX_BYTES = 128_000
_TEXT_CONTENT_TYPES = ("text/", "application/json", "application/xml", "application/javascript")


class WebFetchTool(Tool):
    def __init__(
        self,
        *,
        timeout_s: float = FETCH_TIMEOUT_S,
        max_bytes: int = MAX_BYTES,
        resolver: Callable[[str], Awaitable[list[str]]] | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self._resolver = resolver

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_fetch",
            description="抓取一个公网 http(s) URL 的文本内容（内网/保留地址会被拒绝）。",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL（http/https）"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        url = args.get("url")
        if not isinstance(url, str):
            return ToolResult.error("url 必须是字符串")
        async with httpx.AsyncClient(
            timeout=self.timeout_s, follow_redirects=False, trust_env=False
        ) as client:
            current = url
            resp: httpx.Response | None = None
            for _hop in range(MAX_REDIRECTS + 1):
                try:
                    if self._resolver is not None:
                        await assert_url_allowed(current, resolver=self._resolver)
                    else:
                        await assert_url_allowed(current)
                except SsrfBlockedError as exc:
                    return ToolResult.error(str(exc))
                try:
                    resp = await client.get(current)
                except httpx.HTTPError as exc:
                    return ToolResult.error(f"请求失败：{exc}")
                if not resp.is_redirect:
                    break
                location = resp.headers.get("location")
                if not location:
                    return ToolResult.error("重定向缺少 Location 头")
                current = str(httpx.URL(current).join(location))
            else:
                return ToolResult.error(f"重定向超过 {MAX_REDIRECTS} 跳")
            assert resp is not None
            return await self._read_text(resp)

    async def _read_text(self, resp: httpx.Response) -> ToolResult:
        content_type = resp.headers.get("content-type", "")
        if content_type and not content_type.startswith(_TEXT_CONTENT_TYPES):
            return ToolResult.error(f"不支持的内容类型：{content_type}")
        raw = b""
        async for chunk in resp.aiter_bytes():
            raw += chunk
            if len(raw) >= self.max_bytes:
                break
        truncated = len(raw) >= self.max_bytes
        text = raw[: self.max_bytes].decode("utf-8", errors="replace")
        if truncated:
            text += f"\n...[truncated at {self.max_bytes} bytes]"
        return ToolResult(content=f"status={resp.status_code}\n{text}")
