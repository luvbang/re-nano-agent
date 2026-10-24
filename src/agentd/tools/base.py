"""工具协议（M1 D2）。

执行管线的完整形态（docs/architecture.md §6.2）在 M2 随真工具落地；
M1 只需要：注册、定义导出（OpenAI 格式）、分发执行、超时与异常兜底、结果截断。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agentd.providers.base import ToolDefinition


@dataclass(frozen=True, slots=True)
class ToolResult:
    content: str
    is_error: bool = False

    @classmethod
    def error(cls, message: str) -> ToolResult:
        return cls(content=message, is_error=True)


class Tool(ABC):
    """内置工具基类；v0.2 再考虑 entry_points 插件。"""

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """暴露给模型的声明（名称/描述/JSON Schema 参数）。"""

    @abstractmethod
    async def execute(self, args: dict[str, Any]) -> ToolResult:
        """执行工具。抛出的任何异常都会被注册表转成错误结果，绝不炸 run。"""
