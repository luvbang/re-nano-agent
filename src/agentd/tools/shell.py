"""shell 工具（M2 D4）：默认关闭。开启 = 信任调用方（ROADMAP §6.3）。

约束：cwd 锁定 workspace；allowlist 前缀匹配（空 allowlist = 未启用，拒绝一切）；
超时杀进程；信号量限并发；输出截断。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agentd.providers.base import ToolDefinition
from agentd.tools.base import Tool, ToolResult

MAX_OUTPUT_CHARS = 16_000


class ShellTool(Tool):
    def __init__(
        self,
        workspace_root: Path,
        *,
        allowlist: Sequence[str] = (),
        timeout_s: float = 30.0,
        max_concurrency: int = 2,
    ) -> None:
        self.workspace_root = workspace_root
        self.allowlist = [entry.strip() for entry in allowlist if entry.strip()]
        self.timeout_s = timeout_s
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="shell",
            description="在 workspace 内执行命令（受 allowlist 限制，默认关闭）。",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令行"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        )

    def _allowed(self, command: str) -> bool:
        return any(command.strip().startswith(prefix) for prefix in self.allowlist)

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        command = str(args.get("command", "")).strip()
        if not self.allowlist:
            return ToolResult.error("shell 工具未启用（allowlist 为空，默认关闭）")
        if not command:
            return ToolResult.error("command 为空")
        if not self._allowed(command):
            return ToolResult.error(f"命令不在 allowlist 内：{command!r}")
        async with self._semaphore:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=self.timeout_s)
            except TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult.error(f"命令超时（>{self.timeout_s:.0f}s）已终止")
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + f"\n…[输出截断，原文 {len(output)} 字符]"
        status = "ok" if process.returncode == 0 else f"exit={process.returncode}"
        return ToolResult(content=f"[{status}]\n{output or '(无输出)'}")
