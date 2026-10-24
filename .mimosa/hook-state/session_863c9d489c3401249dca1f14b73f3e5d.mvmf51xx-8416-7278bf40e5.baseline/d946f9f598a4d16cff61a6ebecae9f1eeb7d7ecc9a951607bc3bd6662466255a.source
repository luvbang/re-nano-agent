"""工具层（M2）：base / registry / filesystem / shell / web。"""

from __future__ import annotations

from pathlib import Path

from agentd.tools.base import Tool, ToolResult
from agentd.tools.builtin import EchoTool, GetTimeTool
from agentd.tools.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from agentd.tools.shell import RunCommandTool
from agentd.tools.web import WebFetchTool

__all__ = [
    "EchoTool",
    "GetTimeTool",
    "ListDirTool",
    "ReadFileTool",
    "RunCommandTool",
    "Tool",
    "ToolResult",
    "WebFetchTool",
    "WriteFileTool",
    "build_workspace_tools",
]


def build_workspace_tools(
    workspace: Path,
    *,
    enable_shell: bool = False,
    web_fetch: bool = True,
    echo: bool = True,
) -> tuple[Tool, ...]:
    """组装一个 workspace 的默认工具集；shell 默认不注册（纵深防御）。"""
    tools: list[Tool] = [ReadFileTool(workspace), WriteFileTool(workspace), ListDirTool(workspace)]
    if web_fetch:
        tools.append(WebFetchTool())
    if enable_shell:
        tools.append(RunCommandTool(workspace))
    if echo:
        tools.append(EchoTool())
    tools.append(GetTimeTool())
    return tuple(tools)
