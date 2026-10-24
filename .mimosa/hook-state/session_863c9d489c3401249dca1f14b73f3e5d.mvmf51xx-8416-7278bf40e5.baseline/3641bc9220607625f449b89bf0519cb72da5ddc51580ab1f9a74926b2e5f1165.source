"""会话上下文服务（M2 D1/D2）：messages 表 ↔ ChatMessage 的双向映射。

- ``load_history``：读库 → wire 消息（user/assistant/tool；summary 视作 system 附加），
  按 token 预算从最旧的**完整轮**开始丢弃（保持 assistant.tool_calls 与 tool 结果成对）。
- ``persist_exchange``：把 Runner 成功轮的交换（user + 各轮 assistant/tool + 最终回答）
  原样落库，重启后 ``load_history`` 能重建等价上下文。
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from agentd.providers.base import ChatMessage, ToolCallWire
from agentd.runtime.tokens import estimate_tokens
from agentd.storage.db import Database
from agentd.storage.repositories import MessageRepository

logger = logging.getLogger(__name__)

#: 单条 tool 结果回放时的内容上限（执行时已 16k 截断，这里是上下文侧的二次保险）
TOOL_CONTENT_MAX_CHARS = 16_000

_PER_MESSAGE_OVERHEAD = 4  # role/定界符的粗略开销


def _row_to_message(row: dict[str, Any]) -> ChatMessage:
    content: str | None = None
    if row["content_json"] is not None:
        try:
            decoded = json.loads(row["content_json"])
            decoded_is_str = isinstance(decoded, str)
        except ValueError:
            decoded, decoded_is_str = row["content_json"], True
        # 未来多模态块：压回紧凑 JSON 当纯文本喂给模型
        content = str(decoded) if decoded_is_str else json.dumps(decoded, ensure_ascii=False)
    msg: ChatMessage = ChatMessage(role=row["role"], content=content)
    if row["tool_calls_json"]:
        try:
            calls = json.loads(row["tool_calls_json"])
        except ValueError:
            calls = []
        msg["tool_calls"] = cast(
            "list[ToolCallWire]", [call for call in calls if isinstance(call, dict)]
        )
    if row["tool_call_id"]:
        msg["tool_call_id"] = row["tool_call_id"]
    if msg["role"] == "tool" and len(msg["content"] or "") > TOOL_CONTENT_MAX_CHARS:
        msg["content"] = (msg["content"] or "")[:TOOL_CONTENT_MAX_CHARS] + "\n...[trimmed]"
    return msg


def estimate_messages(messages: list[ChatMessage]) -> int:
    total = 0
    for msg in messages:
        total += _PER_MESSAGE_OVERHEAD + estimate_tokens(msg.get("content") or "")
        for call in msg.get("tool_calls") or []:
            total += estimate_tokens(json.dumps(call, ensure_ascii=False))
    return total


def split_turns(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    """按 user 消息切轮；开头不成对的孤行（理论不出现）归入第一轮。"""
    turns: list[list[ChatMessage]] = []
    for msg in messages:
        if msg["role"] == "user" or not turns:
            turns.append([msg])
        else:
            turns[-1].append(msg)
    return turns


def trim_to_budget(messages: list[ChatMessage], *, budget_tokens: int) -> list[ChatMessage]:
    """超出预算时从最旧的完整轮开始丢弃；至少保留最近一轮。"""
    if estimate_messages(messages) <= budget_tokens:
        return messages
    turns = split_turns(messages)
    while len(turns) > 1 and estimate_messages([m for t in turns for m in t]) > budget_tokens:
        dropped = turns.pop(0)
        logger.info("context.trimmed_turn", extra={"messages": len(dropped)})
    return [msg for turn in turns for msg in turn]


class ConversationService:
    def __init__(self, db: Database, *, token_budget: int = 24_000) -> None:
        self.db = db
        self.messages = MessageRepository(db)
        self.token_budget = token_budget

    async def load_history(self, session_id: str) -> list[ChatMessage]:
        rows = await self.messages.list_by_session(session_id, limit=1_000)
        history = [_row_to_message(row) for row in rows]
        return trim_to_budget(history, budget_tokens=self.token_budget)

    async def persist_exchange(self, session_id: str, exchange: list[ChatMessage]) -> None:
        for msg in exchange:
            tool_calls: list[ToolCallWire] = msg.get("tool_calls") or []
            await self.messages.append(
                session_id,
                role=msg["role"],
                content=msg.get("content"),
                tool_calls_json=(
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None
                ),
                tool_call_id=msg.get("tool_call_id"),
            )
