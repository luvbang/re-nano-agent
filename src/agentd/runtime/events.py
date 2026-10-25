"""Run 事件类型（M1 D3，契约见 docs/api-contract.md §3）。

Runner 是事件的唯一生产者；seq 编号、SSE 序列化、run_events 回放属于 M3 API 层，
这里保持纯数据形态。code 取契约错误码子集：model_error / rate_limited / timeout。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agentd.providers.base import Usage

ToolStatus = Literal["ok", "error"]


@dataclass(frozen=True, slots=True)
class RunStarted:
    run_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class MessageDelta:
    delta: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    delta: str


@dataclass(frozen=True, slots=True)
class ToolStarted:
    tool_call_id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCompleted:
    tool_call_id: str
    name: str
    status: ToolStatus
    duration_ms: int
    #: 工具输出预览（v0.2-4 控制台文件预览用；工具管线已截断，SSE 序列化时再封顶）
    result: str = ""


@dataclass(frozen=True, slots=True)
class MessageCompleted:
    content: str
    usage: Usage


@dataclass(frozen=True, slots=True)
class RunCompleted:
    usage: Usage


@dataclass(frozen=True, slots=True)
class RunFailed:
    code: str
    message: str
    retryable: bool


RunEvent = (
    RunStarted
    | MessageDelta
    | ReasoningDelta
    | ToolStarted
    | ToolCompleted
    | MessageCompleted
    | RunCompleted
    | RunFailed
)
