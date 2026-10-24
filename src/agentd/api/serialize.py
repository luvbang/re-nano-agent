"""DB 行 → 响应模型的序列化（M3）。JSON 列在这里解开，路由层不碰列名细节。"""

from __future__ import annotations

import json
from typing import Any

from agentd.api.schemas import (
    KeyOut,
    MessageOut,
    RunOut,
    SessionOut,
    ToolCallOut,
)
from agentd.storage.repositories import RunRepository


def session_out(row: dict[str, Any]) -> SessionOut:
    metadata: dict[str, Any] = {}
    if row.get("metadata_json"):
        try:
            loaded = json.loads(row["metadata_json"])
            if isinstance(loaded, dict):
                metadata = loaded
        except ValueError:
            metadata = {}
    return SessionOut(
        id=str(row["id"]),
        external_user_id=row.get("external_user_id"),
        title=row.get("title"),
        metadata=metadata,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def message_out(row: dict[str, Any]) -> MessageOut:
    content: str | None = None
    if row.get("content_json") is not None:
        try:
            decoded = json.loads(row["content_json"])
            is_str = isinstance(decoded, str)
        except ValueError:
            decoded, is_str = row["content_json"], True
        # 非字符串（多模态块）压回紧凑 JSON
        content = decoded if is_str else json.dumps(decoded, ensure_ascii=False)
    tool_calls: list[ToolCallOut] | None = None
    if row.get("tool_calls_json"):
        try:
            calls = json.loads(row["tool_calls_json"])
        except ValueError:
            calls = []
        tool_calls = [
            ToolCallOut.model_validate(call, from_attributes=True)
            for call in calls
            if isinstance(call, dict)
        ] or None
    return MessageOut(
        id=str(row["id"]),
        seq=int(row["seq"]),
        role=str(row["role"]),
        content=content,
        tool_calls=tool_calls,
        tool_call_id=row.get("tool_call_id"),
        created_at=str(row["created_at"]),
    )


def run_out(row: dict[str, Any]) -> RunOut:
    error = None
    if row.get("error_json"):
        try:
            loaded = json.loads(row["error_json"])
            if isinstance(loaded, dict):
                from agentd.api.schemas import RunErrorOut

                error = RunErrorOut.model_validate(loaded)
        except ValueError:
            error = None
    return RunOut(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        status=str(row["status"]),
        model=row.get("model"),
        input_tokens=int(row.get("input_tokens") or 0),
        output_tokens=int(row.get("output_tokens") or 0),
        error=error,
        created_at=str(row["created_at"]),
        finished_at=row.get("finished_at"),
    )


def key_out(row: dict[str, Any]) -> KeyOut:
    return KeyOut(
        id=str(row["id"]),
        key_prefix=str(row["key_prefix"]),
        name=row.get("name"),
        scopes=str(row["scopes"]),
        rate_limit_per_min=int(row["rate_limit_per_min"]),
        revoked_at=row.get("revoked_at"),
        created_at=str(row["created_at"]),
    )


def is_terminal_status(status: str) -> bool:
    return status in RunRepository.TERMINAL_STATUSES
