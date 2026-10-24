"""MCP 客户端（v0.2 D1）：把 MCP 服务器的工具桥接为平台内置工具。

传输：Streamable HTTP（JSON-RPC 2.0 over POST；响应 JSON 或 SSE 帧都能解析）。
握手：initialize → 记录 Mcp-Session-Id → notifications/initialized；后续请求带头。
容错：单个服务器不可用/握手失败 → 记日志跳过，绝不拖垮其它工具。

配置（AGENTD_MCP_SERVERS，JSON）：
    {"fetch": {"url": "https://mcp.example/mcp", "token": "可选 bearer"}}
"""

from __future__ import annotations

import itertools
import json
import logging
from typing import Any

import httpx

from agentd.providers.base import ToolDefinition
from agentd.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

_PROTOCOL_VERSION = "2025-06-18"
_TIMEOUT_S = 30.0


class McpEndpoint:
    """单个 MCP 服务器的 JSON-RPC 端点（懒初始化，复用一个 httpx client）。"""

    def __init__(self, name: str, url: str, *, token: str | None = None) -> None:
        self.name = name
        self.url = url
        self._token = token
        self.session_id: str | None = None
        self._initialized = False
        self._ids = itertools.count(1)
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._client = httpx.AsyncClient(timeout=_TIMEOUT_S, headers=headers)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        client = self._ensure_client()
        headers: dict[str, str] = {}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return await client.post(self.url, json=payload, headers=headers)

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        """响应体可能是纯 JSON，也可能是 SSE 帧（data: {...}）。"""
        text = response.text
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            for line in text.splitlines():
                if line.startswith("data:"):
                    decoded: dict[str, Any] = json.loads(line[len("data:") :].strip())
                    return decoded
            raise ValueError("SSE 响应无 data 帧")
        decoded = json.loads(text)
        return decoded

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
            "params": params,
        }
        response = await self._post(payload)
        response.raise_for_status()
        if self.session_id is None:
            self.session_id = response.headers.get("mcp-session-id")
        body = self._decode(response)
        if "error" in body:
            raise RuntimeError(f"MCP {method} 错误：{body['error']}")
        return body.get("result") or {}

    async def initialize(self) -> None:
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agentd", "version": "0.1.0"},
            },
        )
        del result  # initialize 的 result 内容（capabilities 等）v0.1 不消费；
        # 真不兼容的服务器会在 tools/list 阶段以明确错误暴露
        # 通知无需响应体；2xx 即成功
        response = await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        response.raise_for_status()
        self._initialized = True
        logger.info("mcp.initialized", extra={"server": self.name})

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self._initialized:
            await self.initialize()
        result = await self._rpc("tools/list", {})
        return list(result.get("tools") or [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self._initialized:
            await self.initialize()
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})


class McpTool(Tool):
    """把 MCP 服务器上的一个工具包装成平台工具（执行转发，结果文本拼接）。"""

    def __init__(self, endpoint: McpEndpoint, info: dict[str, Any]) -> None:
        self.endpoint = endpoint
        self.info = info
        self.tool_name = str(info.get("name") or "")

    @property
    def definition(self) -> ToolDefinition:
        schema = self.info.get("inputSchema")
        if not isinstance(schema, dict) or not schema:
            schema = {"type": "object", "properties": {}}
        return ToolDefinition(
            name=self.tool_name,
            description=str(self.info.get("description") or f"MCP 工具（{self.endpoint.name}）"),
            parameters=schema,
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            result = await self.endpoint.call_tool(self.tool_name, args)
        except Exception as exc:  # 网络/协议错误 → 工具错误结果，不炸 run
            return ToolResult.error(f"MCP 调用失败（{self.endpoint.name}）：{exc}")
        parts = [
            block.get("text", "")
            for block in (result.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(str(p) for p in parts if p)
        if result.get("isError"):
            return ToolResult.error(text or "MCP 工具返回错误（无文本内容）")
        return ToolResult(content=text or "(MCP 工具无文本输出)")


async def load_mcp_tools(config: dict[str, dict[str, Any]]) -> list[Tool]:
    """按配置加载所有服务器的工具；单服务器失败只记日志跳过。"""
    tools: list[Tool] = []
    for name, raw in config.items():
        url = str(raw.get("url") or "")
        if not url:
            logger.warning("mcp.skipped_no_url", extra={"server": name})
            continue
        endpoint = McpEndpoint(name, url, token=raw.get("token"))
        try:
            infos = await endpoint.list_tools()
        except Exception as exc:
            logger.warning("mcp.unavailable", extra={"server": name, "error": str(exc)[:200]})
            await endpoint.aclose()
            continue
        for info in infos:
            tools.append(McpTool(endpoint, info))
        logger.info("mcp.loaded", extra={"server": name, "tools": len(infos)})
    return tools


def parse_mcp_config(raw: str) -> dict[str, dict[str, Any]]:
    if not raw or not raw.strip():
        return {}
    try:
        parsed: Any = json.loads(raw)
    except ValueError:
        logger.warning("mcp.invalid_config_json")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("mcp.invalid_config_shape")
        return {}
    return {str(k): v for k, v in parsed.items() if isinstance(v, dict)}
