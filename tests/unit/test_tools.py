"""工具注册表测试（M1 D2）：分发、超时、异常兜底、截断、未知工具。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agentd.providers.base import ToolDefinition
from agentd.tools.base import Tool, ToolResult
from agentd.tools.builtin import EchoTool, GetTimeTool
from agentd.tools.registry import MAX_TOOL_RESULT_CHARS, ToolRegistry


class SlowTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="slow", description="", parameters={"type": "object", "properties": {}}
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult(content="never")


class BoomTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="boom", description="", parameters={"type": "object", "properties": {}}
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        raise RuntimeError("工具炸了")


def registry() -> ToolRegistry:
    return ToolRegistry(tool_timeout_s=0.1).register_all([EchoTool(), BoomTool(), SlowTool()])


async def test_echo_roundtrip() -> None:
    result = await registry().execute("echo", json.dumps({"text": "你好"}))
    assert result == ToolResult(content="你好")


async def test_unknown_tool_returns_error_with_suggestions() -> None:
    result = await registry().execute("nope", "{}")
    assert result.is_error
    assert "unknown tool" in result.content
    assert "echo" in result.content  # Did-you-mean 提示


async def test_invalid_json_arguments() -> None:
    result = await registry().execute("echo", "{不是json")
    assert result.is_error
    assert "JSON" in result.content


async def test_non_object_arguments() -> None:
    result = await registry().execute("echo", "[1,2]")
    assert result.is_error
    assert "对象" in result.content


async def test_exception_becomes_error_result() -> None:
    result = await registry().execute("boom", "{}")
    assert result.is_error
    assert "工具炸了" in result.content


async def test_tool_timeout_not_hang() -> None:
    result = await registry().execute("slow", "{}")
    assert result.is_error
    assert "超时" in result.content


class BigOutputTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="big", description="", parameters={"type": "object", "properties": {}}
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(content="x" * (MAX_TOOL_RESULT_CHARS + 2_000))


async def test_result_truncation() -> None:
    result = await ToolRegistry().register(BigOutputTool()).execute("big", "{}")
    assert len(result.content) < MAX_TOOL_RESULT_CHARS + 200
    assert "truncated" in result.content


async def test_duplicate_registration_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate tool"):
        ToolRegistry().register(EchoTool()).register(EchoTool())


async def test_builtin_get_time() -> None:
    result = await ToolRegistry().register(GetTimeTool()).execute("get_time", "{}")
    assert not result.is_error
    assert "utc=" in result.content
