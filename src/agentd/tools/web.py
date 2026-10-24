"""web_fetch 工具（M2 D4）：出站 HTTP 抓取，逐跳过 SSRF 校验。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from agentd.providers.base import ToolDefinition
from agentd.security.ssrf import SsrfViolationError, assert_public_url
from agentd.tools.base import Tool, ToolResult

MAX_REDIRECTS = 5
DEFAULT_MAX_CHARS = 16_000
FETCH_TIMEOUT_S = 20.0
ALLOWED_CONTENT_PREFIXES = ("text/", "application/json", "application/xml", "application/xhtml")

UrlValidator = Callable[[str], list[str]]


class WebFetchTool(Tool):
    def __init__(
        self,
        *,
        timeout_s: float = FETCH_TIMEOUT_S,
        validator: UrlValidator = assert_public_url,
    ) -> None:
        self.timeout_s = timeout_s
        self._validator = validator

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_fetch",
            description="抓取公网页面并返回文本内容（内网/回环/云元数据地址会被拒绝）。",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "http(s) URL"},
                    "max_chars": {
                        "type": "integer",
                        "description": f"最多返回字符数（默认 {DEFAULT_MAX_CHARS}）",
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        url = str(args.get("url", ""))
        max_chars = min(
            int(args.get("max_chars", DEFAULT_MAX_CHARS) or DEFAULT_MAX_CHARS), 64_000
        )
        redirects = 0
        try:
            self._validator(url)
            async with httpx.AsyncClient(follow_redirects=False, timeout=self.timeout_s) as client:
                while True:
                    response = await client.get(url)
                    if response.status_code in (301, 302, 303, 307, 308):
                        redirects += 1
                        if redirects > MAX_REDIRECTS:
                            return ToolResult.error(f"重定向超过 {MAX_REDIRECTS} 跳")
                        url = str(response.headers.get("location", ""))
                        if not url:
                            return ToolResult.error("重定向缺少 Location 头")
                        # 逐跳校验：每一跳都重新走 SSRF 判定
                        self._validator(url)
                        continue
                    if response.status_code != 200:
                        return ToolResult.error(f"HTTP {response.status_code}：{url}")
                    content_type = response.headers.get("content-type", "").split(";")[0].strip()
                    if content_type and not content_type.startswith(ALLOWED_CONTENT_PREFIXES):
                        return ToolResult.error(f"不支持的 Content-Type：{content_type}")
                    text = response.text
                    truncated_note = ""
                    if len(text) > max_chars:
                        text = text[:max_chars]
                        truncated_note = f"\n…[截断，原文 {len(response.text)} 字符]"
                    return ToolResult(content=f"[{url}]\n{text}{truncated_note}")
        except SsrfViolationError as exc:
            return ToolResult.error(f"web_fetch 拒绝：{exc}")
        except httpx.HTTPError as exc:
            return ToolResult.error(f"抓取失败：{exc}")
