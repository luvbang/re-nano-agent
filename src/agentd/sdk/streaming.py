"""SDK 流式迭代（M4）：SSE 解析 + 事件数据类。

同步与异步共用同一解析逻辑（``iter_sse_lines`` 逐行产出），事件对象为
frozen dataclass，字段与契约 §3 一致。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class RunStarted:
    type: Literal["run.started"] = "run.started"
    seq: int = 0
    run_id: str = ""
    session_id: str = ""


@dataclass(frozen=True, slots=True)
class MessageDelta:
    type: Literal["message.delta"] = "message.delta"
    seq: int = 0
    delta: str = ""


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    type: Literal["reasoning.delta"] = "reasoning.delta"
    seq: int = 0
    delta: str = ""


@dataclass(frozen=True, slots=True)
class ToolStarted:
    type: Literal["tool.started"] = "tool.started"
    seq: int = 0
    tool_call_id: str = ""
    name: str = ""
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCompleted:
    type: Literal["tool.completed"] = "tool.completed"
    seq: int = 0
    tool_call_id: str = ""
    name: str = ""
    status: str = "ok"
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class MessageCompleted:
    type: Literal["message.completed"] = "message.completed"
    seq: int = 0
    content: str = ""
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunCompleted:
    type: Literal["run.completed"] = "run.completed"
    seq: int = 0
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunFailed:
    type: Literal["run.failed"] = "run.failed"
    seq: int = 0
    error: dict[str, Any] = field(default_factory=dict)


StreamEvent = (
    RunStarted
    | MessageDelta
    | ReasoningDelta
    | ToolStarted
    | ToolCompleted
    | MessageCompleted
    | RunCompleted
    | RunFailed
)

_EVENT_TYPES: dict[str, type] = {
    "run.started": RunStarted,
    "message.delta": MessageDelta,
    "reasoning.delta": ReasoningDelta,
    "tool.started": ToolStarted,
    "tool.completed": ToolCompleted,
    "message.completed": MessageCompleted,
    "run.completed": RunCompleted,
    "run.failed": RunFailed,
}


def parse_event(event_name: str, data: str) -> StreamEvent | None:
    """SSE 事件 → dataclass；未知事件名/畸形 JSON 返回 None（前向兼容）。

    服务端信封带 ``type`` 字段（= 事件名），dataclass 不含它，构造前剔除。
    """
    try:
        payload = json.loads(data)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    cls = _EVENT_TYPES.get(event_name)
    if cls is None or "seq" not in payload:
        return None
    try:
        event: StreamEvent | None = cls(**payload)  # type: ignore[arg-type]
        return event
    except TypeError:
        return None


def iter_sse_lines(chunks: Iterator[bytes]) -> Iterator[tuple[str, str]]:
    """字节流 → (event, data) 二元组；处理跨 chunk 撕裂与 CRLF。"""
    buffer = b""
    pending_event = ""
    pending_data: list[str] = []
    for chunk in chunks:
        buffer += chunk
        while (idx := buffer.find(b"\n")) >= 0:
            line = buffer[:idx].decode("utf-8", errors="replace").rstrip("\r")
            buffer = buffer[idx + 1 :]
            if not line:
                if pending_data:
                    yield pending_event, "\n".join(pending_data)
                    pending_event, pending_data = "", []
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            value = value.lstrip(" ")
            if field == "event":
                pending_event = value
            elif field == "data":
                pending_data.append(value)
    if pending_data:
        yield pending_event, "\n".join(pending_data)
