"""文件系统工具（M2 D3）：read_file / write_file / edit_file / list_dir。

所有路径经 WorkspacePathResolver（越界/软链/绝对路径一律错误结果，不抛异常）。
限额：读写 1MB、单次读 2000 行、列表 500 条 —— 超限给错误结果而不是默默吞。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentd.providers.base import ToolDefinition
from agentd.security.paths import PathOutsideWorkspaceError, WorkspacePathResolver
from agentd.tools.base import Tool, ToolResult

MAX_READ_BYTES = 1_000_000
MAX_WRITE_BYTES = 1_000_000
MAX_LINES_PER_READ = 2_000
MAX_LIST_ENTRIES = 500


def _guard(message: str) -> ToolResult:
    return ToolResult.error(message)


class ReadFileTool(Tool):
    def __init__(self, resolver: WorkspacePathResolver) -> None:
        self.resolver = resolver

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description="读取 workspace 内的文本文件，返回指定行区间。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "workspace 相对路径"},
                    "offset_lines": {
                        "type": "integer",
                        "description": "起始行（0 起，默认 0）",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": f"最多返回行数（默认 {MAX_LINES_PER_READ}）",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        path_raw = str(args.get("path", ""))
        try:
            path = self.resolver.resolve(path_raw)
        except PathOutsideWorkspaceError as exc:
            return _guard(f"read_file 拒绝：{exc}")
        if not path.exists():
            return _guard(f"文件不存在：{path_raw}")
        if path.is_dir():
            return _guard(f"是目录不是文件：{path_raw}")
        size = path.stat().st_size
        if size > MAX_READ_BYTES:
            return _guard(f"文件过大（{size} 字节 > {MAX_READ_BYTES}）：{path_raw}")
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        offset = max(int(args.get("offset_lines", 0) or 0), 0)
        requested = int(args.get("max_lines", MAX_LINES_PER_READ) or MAX_LINES_PER_READ)
        max_lines = min(requested, MAX_LINES_PER_READ)
        selected = lines[offset : offset + max_lines]
        body = "\n".join(selected)
        if offset > 0 or offset + max_lines < len(lines):
            body += f"\n…（第 {offset}–{offset + len(selected)} 行，共 {len(lines)} 行）"
        return ToolResult(content=body)


class WriteFileTool(Tool):
    def __init__(self, resolver: WorkspacePathResolver) -> None:
        self.resolver = resolver

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_file",
            description="写入/覆盖 workspace 内的文本文件（自动建父目录）。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "workspace 相对路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        path_raw = str(args.get("path", ""))
        content = args.get("content")
        if not isinstance(content, str):
            return _guard("content 必须是字符串")
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return _guard(f"内容过大（> {MAX_WRITE_BYTES} 字节）")
        try:
            path = self.resolver.resolve(path_raw)
        except PathOutsideWorkspaceError as exc:
            return _guard(f"write_file 拒绝：{exc}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult(content=f"已写入 {path_raw}（{len(content)} 字符）")


class EditFileTool(Tool):
    def __init__(self, resolver: WorkspacePathResolver) -> None:
        self.resolver = resolver

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="edit_file",
            description="精确替换文件中的一处文本（old_string 必须恰好出现一次）。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "workspace 相对路径"},
                    "old_string": {"type": "string", "description": "要替换的原文"},
                    "new_string": {"type": "string", "description": "替换后的文本"},
                },
                "required": ["path", "old_string", "new_string"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        path_raw = str(args.get("path", ""))
        old = args.get("old_string")
        new = args.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            return _guard("old_string/new_string 必须是非空字符串")
        try:
            path = self.resolver.resolve(path_raw)
        except PathOutsideWorkspaceError as exc:
            return _guard(f"edit_file 拒绝：{exc}")
        if not path.is_file():
            return _guard(f"文件不存在：{path_raw}")
        text = path.read_text(encoding="utf-8", errors="replace")
        occurrences = text.count(old)
        if occurrences == 0:
            return _guard("old_string 在文件中不存在")
        if occurrences > 1:
            return _guard(f"old_string 出现 {occurrences} 次，请提供更长的唯一上下文")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return ToolResult(content=f"已替换 {path_raw} 中 1 处（{len(old)} → {len(new)} 字符）")


class ListDirTool(Tool):
    def __init__(self, resolver: WorkspacePathResolver) -> None:
        self.resolver = resolver

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_dir",
            description="列出 workspace 内目录的一层内容（目录加 d/ 前缀）。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "workspace 相对路径，默认 ."},
                },
                "required": [],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        path_raw = str(args.get("path", ".") or ".")
        try:
            path = self.resolver.resolve(path_raw)
        except PathOutsideWorkspaceError as exc:
            return _guard(f"list_dir 拒绝：{exc}")
        if not path.is_dir():
            return _guard(f"不是目录：{path_raw}")
        entries = sorted(path.iterdir(), key=lambda p: p.name)
        lines = [
            f"{'d' if entry.is_dir() else '-'} {entry.name}" for entry in entries[:MAX_LIST_ENTRIES]
        ]
        if len(entries) > MAX_LIST_ENTRIES:
            lines.append(f"…（共 {len(entries)} 项，仅显示前 {MAX_LIST_ENTRIES}）")
        return ToolResult(content="\n".join(lines) or "（空目录）")


def filesystem_tools(workspace_root: Path) -> tuple[Tool, ...]:
    resolver = WorkspacePathResolver(workspace_root)
    return (
        ReadFileTool(resolver),
        WriteFileTool(resolver),
        EditFileTool(resolver),
        ListDirTool(resolver),
    )
