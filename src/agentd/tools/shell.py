"""shell 工具（M2 D3）：run_command。

默认关闭（AGENTD_ENABLE_SHELL_TOOL=1 才注册）。即使开启也只拿到 workspace 作 cwd、
硬超时封顶、输出经注册表 16k 截断——这是纵深防御的一层，不是沙箱；威胁模型是
"管理员明确授权 + 模型提示词注入"，故高风险环境保持默认关闭（ADR-006）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agentd.providers.base import ToolDefinition
from agentd.tools.base import Tool, ToolResult

DEFAULT_TIMEOUT_S = 10.0
MAX_TIMEOUT_S = 30.0
OUTPUT_MAX_CHARS = 8_000


class RunCommandTool(Tool):
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="run_command",
            description=(
                "在 workspace 目录执行一条 shell 命令并返回合并输出。"
                "适用于构建、搜索等任务；每条命令独立执行，无状态。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "timeout_s": {
                        "type": "number",
                        "description": (
                            f"超时秒数，默认 {DEFAULT_TIMEOUT_S:.0f}，"
                            f"上限 {MAX_TIMEOUT_S:.0f}"
                        ),
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult.error("command 必须是非空字符串")
        raw_timeout = args.get("timeout_s", DEFAULT_TIMEOUT_S)
        if not isinstance(raw_timeout, (int, float)) or isinstance(raw_timeout, bool):
            return ToolResult.error("timeout_s 必须是数字")
        timeout_s = min(float(raw_timeout), MAX_TIMEOUT_S)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=self.workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            return ToolResult.error(f"无法启动命令：{exc}")
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return ToolResult.error(f"命令超过 {timeout_s:.0f}s 被终止")
        text = stdout.decode("utf-8", errors="replace")
        if len(text) > OUTPUT_MAX_CHARS:
            overflow = len(text) - OUTPUT_MAX_CHARS
            text = text[:OUTPUT_MAX_CHARS] + f"\n...[truncated {overflow} chars]"
        failed = proc.returncode != 0
        return ToolResult(content=f"exit={proc.returncode}\n{text}", is_error=failed)
