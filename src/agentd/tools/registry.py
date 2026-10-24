"""工具注册表与执行入口（M1 D2；M2 D2 增超限落盘）。

M1 执行序：存在性检查 → arguments JSON 解析 → wait_for 超时 → 异常转错误结果 → 结果截断。
（JSON Schema 参数校验、before_tool 审计钩子随 M3/M4 补齐。）
超限落盘：配置 overflow_root 且带 run_id 时，超过 16k 的完整结果写到
``<overflow_root>/<run_id>/tool-results/<序号>-<名字>.txt``，返回头部 + 文件路径。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agentd.providers.base import ToolDefinition
from agentd.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 16_000


class ToolRegistry:
    def __init__(
        self,
        *,
        tool_timeout_s: float = 60.0,
        overflow_root: Path | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self.tool_timeout_s = tool_timeout_s
        self.overflow_root = overflow_root
        self._overflow_seq = 0

    def register(self, tool: Tool) -> ToolRegistry:
        name = tool.definition.name
        if name in self._tools:
            raise ValueError(f"duplicate tool registration: {name}")
        self._tools[name] = tool
        return self

    def register_all(self, tools: Sequence[Tool]) -> ToolRegistry:
        for tool in tools:
            self.register(tool)
        return self

    def definitions(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    async def execute(
        self, name: str, arguments_json: str, *, run_id: str | None = None
    ) -> ToolResult:
        """按名字执行工具；所有失败路径都返回 ToolResult，不抛异常。"""
        tool = self._tools.get(name)
        if tool is None:
            known = "、".join(sorted(self._tools)) or "（注册表为空）"
            return ToolResult.error(f"unknown tool: {name}，可用工具：{known}")
        try:
            args: dict[str, Any] = json.loads(arguments_json) if arguments_json.strip() else {}
        except ValueError:
            return ToolResult.error(
                f"tool {name} arguments 不是合法 JSON：{arguments_json[:200]!r}"
            )
        if not isinstance(args, dict):
            return ToolResult.error(f"tool {name} arguments 必须是 JSON 对象")
        try:
            result = await asyncio.wait_for(tool.execute(args), timeout=self.tool_timeout_s)
        except TimeoutError:
            return ToolResult.error(f"tool {name} 超时（>{self.tool_timeout_s:.0f}s）")
        except asyncio.CancelledError:
            raise  # run 取消不吞
        except Exception as exc:
            logger.warning("tool.failed", extra={"tool": name, "error": str(exc)[:200]})
            return ToolResult.error(f"tool {name} 执行失败：{exc}")
        return await self._finalize(result, name=name, run_id=run_id)

    async def _finalize(self, result: ToolResult, *, name: str, run_id: str | None) -> ToolResult:
        if len(result.content) <= MAX_TOOL_RESULT_CHARS:
            return result
        head = result.content[:MAX_TOOL_RESULT_CHARS]
        overflow = len(result.content) - MAX_TOOL_RESULT_CHARS
        if self.overflow_root is None or run_id is None:
            return ToolResult(
                content=head + f"\n...[truncated {overflow} chars]",
                is_error=result.is_error,
            )
        self._overflow_seq += 1
        path = (
            self.overflow_root / run_id / "tool-results" / f"{self._overflow_seq:03d}-{name}.txt"
        )
        await asyncio.to_thread(self._write_overflow, path, result.content)
        return ToolResult(
            content=head + f"\n...[truncated {overflow} chars，完整结果已写入 {path}]",
            is_error=result.is_error,
        )

    @staticmethod
    def _write_overflow(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
