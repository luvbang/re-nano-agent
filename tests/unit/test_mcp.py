"""MCP 客户端测试（v0.2 D1）：握手/发现/调用/容错，respx 模拟 Streamable HTTP。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import respx

from agentd.tools.mcp import (
    McpEndpoint,
    McpTool,
    load_mcp_tools,
    parse_mcp_config,
)

BASE = "https://mcp.test/mcp"


@respx.mock
async def test_handshake_list_and_call_roundtrip() -> None:
    route = respx.post(BASE).mock(side_effect=rpc_result_wrapper)
    endpoint = McpEndpoint("srv", BASE)
    try:
        # 预置：initialize → 会话头；tools/list → 2 个工具；tools/call → 文本
        set_script(
            initialize={"protocolVersion": "2025-06-18", "capabilities": {}},
            tools=[
                {"name": "fetch", "description": "抓网页", "inputSchema": {"type": "object"}},
                {"name": "bare"},
            ],
            calls={"fetch": {"content": [{"type": "text", "text": "页面内容"}]}},
        )
        tools_info = await endpoint.list_tools()
        assert [t["name"] for t in tools_info] == ["fetch", "bare"]
        assert endpoint.session_id == "sess-123"

        # 会话头已带上
        result = await endpoint.call_tool("fetch", {"url": "https://x"})
        assert result["content"][0]["text"] == "页面内容"
        assert "sess-123" in route.calls.last.request.headers.get("mcp-session-id", "")
    finally:
        await endpoint.aclose()


_SCRIPT: dict[str, Any] = {}


def set_script(**kwargs: Any) -> None:
    _SCRIPT.clear()
    _SCRIPT.update(kwargs)


def rpc_result_wrapper(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content.decode("utf-8"))
    method = body.get("method")
    if method == "initialize":
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": _SCRIPT.get("initialize", {})},
            headers={"Mcp-Session-Id": "sess-123"},
        )
    if method == "notifications/initialized":
        return httpx.Response(202)
    if method == "tools/list":
        result = {"tools": _SCRIPT.get("tools", [])}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
    if method == "tools/call":
        name = body["params"]["name"]
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": _SCRIPT["calls"][name]}
        )
    return httpx.Response(400)


@respx.mock
async def test_sse_framed_response_variant() -> None:
    def sse_router(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        if body.get("method") == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body.get("method") == "notifications/initialized":
            return httpx.Response(202)
        result = {"tools": [{"name": "t"}]}
        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        sse_body = "event: message\ndata: " + payload + "\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=sse_body)

    respx.post(BASE).mock(side_effect=sse_router)
    endpoint = McpEndpoint("srv", BASE)
    try:
        tools = await endpoint.list_tools()
        assert tools == [{"name": "t"}]
    finally:
        await endpoint.aclose()


@respx.mock
async def test_tool_wrapper_maps_results_and_errors() -> None:
    set_script(
        initialize={},
        tools=[{"name": "fetch", "inputSchema": {"type": "object", "properties": {}}}],
        calls={
            "fetch": {"content": [{"type": "text", "text": "ok"}]},
        },
    )
    respx.post(BASE).mock(side_effect=rpc_result_wrapper)
    endpoint = McpEndpoint("srv", BASE)
    tool = McpTool(endpoint, {"name": "fetch", "description": "抓取"})
    try:
        result = await tool.execute({})
        assert result.content == "ok" and not result.is_error
        assert tool.definition.name == "fetch"
    finally:
        await endpoint.aclose()


@respx.mock
async def test_load_mcp_tools_skips_unavailable_server() -> None:
    set_script(
        initialize={},
        tools=[{"name": "good_tool"}],
        calls={},
    )
    respx.post(BASE).mock(side_effect=rpc_result_wrapper)
    respx.post("https://down.test/mcp").mock(side_effect=httpx.ConnectTimeout("down"))
    tools = await load_mcp_tools(
        {"up": {"url": BASE}, "down": {"url": "https://down.test/mcp"}, "no_url": {}}
    )
    assert [t.definition.name for t in tools] == ["good_tool"]


def test_parse_config_shapes() -> None:
    assert parse_mcp_config("") == {}
    assert parse_mcp_config("bad") == {}
    assert parse_mcp_config('["x"]') == {}
    assert parse_mcp_config('{"a": {"url": "https://x"}}') == {"a": {"url": "https://x"}}
