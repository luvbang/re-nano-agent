"""文件工具（M2 D3）：read_file / write_file / list_dir。

所有路径先过 ``security.paths.resolve_in_workspace``（穿越/软链/绝对路径拒绝）。
读有上限（截断标注），写建父目录、限制单文件大小；list_dir 只报名字与类型。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentd.providers.base import ToolDefinition
from agentd.security.paths import PathOutsideWorkspace, resolve_in_workspace
from agentd.tools.base import Tool, ToolResult

READ_MAX_BYTES = 200_000
WRITE_MAX_BYTES = 200_000
LIST_MAX_ENTRIES = 500


class _WorkspaceTool(Tool):
    """workspace 内文件工具的公共基类：只依赖 workspace 根路径。"""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace


class ReadFileTool(_WorkspaceTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description="读取 workspace 内的文本文件（UTF-8），超长自动截断。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "workspace 相对路径"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path")
        if not isinstance(path, str):
            return ToolResult.error("path 必须是字符串")
        try:
            target = resolve_in_workspace(self.workspace, path)
        except PathOutsideWorkspace as exc:
            return ToolResult.error(str(exc))
        if not target.exists():
            return ToolResult.error(f"文件不存在：{path}")
        if target.is_dir():
            return ToolResult.error(f"{path} 是目录，请用 list_dir")
        try:
            data = target.read_bytes()
        except OSError as exc:
            return ToolResult.error(f"读取失败：{exc}")
        truncated = len(data) > READ_MAX_BYTES
        if truncated:
            data = data[:READ_MAX_BYTES]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return ToolResult.error(f"{path} 不是 UTF-8 文本文件")
        if truncated:
            text += f"\n...[truncated at {READ_MAX_BYTES} bytes]"
        return ToolResult(content=text)


class WriteFileTool(_WorkspaceTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_file",
            description="把文本写入 workspace 内的文件（覆盖写，自动建父目录）。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "workspace 相对路径"},
                    "content": {"type": "string", "description": "要写入的完整内容"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path")
        content = args.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            return ToolResult.error("path 与 content 必须是字符串")
        if len(content.encode("utf-8")) > WRITE_MAX_BYTES:
            return ToolResult.error(f"内容超过单文件上限 {WRITE_MAX_BYTES} 字节")
        try:
            target = resolve_in_workspace(self.workspace, path)
        except PathOutsideWorkspace as exc:
            return ToolResult.error(str(exc))
        if target == self.workspace.resolve():
            return ToolResult.error("path 不能指向 workspace 根目录")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.error(f"写入失败：{exc}")
        return ToolResult(content=f"written {path} ({len(content)} chars)")


class ListDirTool(_WorkspaceTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_dir",
            description="列出 workspace 内某目录的一级内容（名字 + 文件/目录）。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "workspace 相对路径，默认根目录"},
                },
                "required": [],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        if path is None:
            path = ""
        if not isinstance(path, str):
            return ToolResult.error("path 必须是字符串")
        try:
            target = resolve_in_workspace(self.workspace, path or ".")
        except PathOutsideWorkspace as exc:
            return ToolResult.error(str(exc))
        if not target.exists():
            return ToolResult.error(f"目录不存在：{path or '.'}")
        if not target.is_dir():
            return ToolResult.error(f"{path} 是文件，请用 read_file")
        try:
            entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError as exc:
            return ToolResult.error(f"列目录失败：{exc}")
        lines: list[str] = []
        for entry in entries[:LIST_MAX_ENTRIES]:
            kind = "dir" if entry.is_dir() else "file"
            size = entry.stat().st_size if entry.is_file() else ""
            item = {"name": entry.name, "type": kind, "size": size}
            lines.append(json.dumps(item, ensure_ascii=False))
        if not lines:
            return ToolResult(content="(empty dir)")
        if len(entries) > LIST_MAX_ENTRIES:
            lines.append(f"...[truncated at {LIST_MAX_ENTRIES} entries]")
        return ToolResult(content="\n".join(lines))
