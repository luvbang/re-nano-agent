"""内置演示工具（M1）：echo（D2 工具执行入口）、get_time（D5 闭环演示）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agentd.providers.base import ToolDefinition
from agentd.tools.base import Tool, ToolResult


class EchoTool(Tool):
    """把输入原样返回；验证工具调用回路的最小工具。"""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="echo",
            description="原样回显给定文本。用于测试工具调用回路。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要回显的文本"},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        text = args.get("text", "")
        if not isinstance(text, str):
            return ToolResult.error("text 必须是字符串")
        return ToolResult(content=text)


class GetTimeTool(Tool):
    """返回当前 UTC/本地时间；只读、无参数。"""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_time",
            description="获取当前时间（UTC 与本地）。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        now = datetime.now(UTC)
        local = datetime.now().astimezone().isoformat(timespec="seconds")
        return ToolResult(content=f"utc={now.strftime('%Y-%m-%dT%H:%M:%SZ')} local={local}")


BUILTIN_TOOLS: tuple[Tool, ...] = (EchoTool(), GetTimeTool())
