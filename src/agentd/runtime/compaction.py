"""历史压缩 v1（M4 D4）：超预算 60% 时对旧消息做 LLM 摘要，写 summary checkpoint。

语义（docs/architecture.md §6.4）：
- ``messages`` 保留全部原始消息（审计/重放真相），``role=summary`` 是 checkpoint
- prompt 视图 = 最后一条 summary（映射为带标记的 user 消息）+ 其后原文（保留最近 keep_recent 条）
- 摘要失败（Provider 报错/超时）→ 原样返回，交给 ContextBuilder 的裁剪兜底（绝不炸 run）
- 不足 min_messages 条或未超阈值 → 不动
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agentd.providers.base import ChatMessage, Provider
from agentd.runtime.context import ContextBuilder, message_tokens
from agentd.storage.db import Database
from agentd.storage.repositories import MessageRepository, rows_to_chat_messages

logger = logging.getLogger(__name__)

SUMMARY_MARKER = "【此前对话摘要】"
_SUMMARY_SYSTEM = (
    "你是对话压缩器。把给定对话压缩为要点摘要：保留用户目标、关键事实、"
 "已做决定与未决事项；直接输出摘要正文，不要寒暄。"
)
_TRANSCRIPT_CAP_CHARS = 30_000


def prompt_view(rows: list[dict[str, Any]]) -> list[ChatMessage]:
    """DB 行 → prompt 视图：最后一条 summary（置顶）+ 未被其覆盖的原文。

    summary 的 meta.covers_up_to 记录它覆盖到的最大 seq（summary 行物理上在
    行尾，但被保留的最近原文 seq 小于它——按序号取，不按位置取）。
    """
    last_summary: dict[str, Any] | None = None
    for row in rows:
        if row["role"] == "summary":
            last_summary = row
    if last_summary is None:
        return rows_to_chat_messages(rows)
    covers = 0
    if last_summary["meta_json"]:
        try:
            covers = int(json.loads(last_summary["meta_json"]).get("covers_up_to") or 0)
        except (ValueError, TypeError):
            covers = 0
    if covers:
        tail_rows = [r for r in rows if r["seq"] > covers and r["role"] != "summary"]
    else:
        idx = rows.index(last_summary)
        tail_rows = [r for r in rows[idx + 1 :] if r["role"] != "summary"]
    summary_text = ""
    if last_summary["content_json"]:
        summary_text = json.loads(last_summary["content_json"]).get("text") or ""
    head = ChatMessage(role="user", content=f"{SUMMARY_MARKER}\n{summary_text}")
    return [head, *rows_to_chat_messages(tail_rows)]


class HistoryCompactor:
    def __init__(
        self,
        db: Database,
        provider: Provider,
        *,
        context_builder: ContextBuilder,
        keep_recent: int = 6,
        min_messages: int = 8,
        threshold: float = 0.6,
    ) -> None:
        self.db = db
        self.provider = provider
        self.context_builder = context_builder
        self.keep_recent = keep_recent
        self.min_messages = min_messages
        self.threshold = threshold

    async def compact(self, session_id: str) -> list[ChatMessage]:
        """返回该 session 的 prompt 视图；必要时先写一条 summary checkpoint。"""
        repo = MessageRepository(self.db)
        rows = await repo.list_for_session(session_id)
        view = prompt_view(rows)
        budget = self.context_builder.budget
        total = sum(message_tokens(m) for m in view)
        if total <= int(budget * self.threshold):
            return view
        if len(view) < self.min_messages:
            return view  # 太短不值得摘要，交给 builder 裁剪
        old, recent = view[: -self.keep_recent], view[-self.keep_recent :]
        summary_text = await self._summarize(old)
        if summary_text is None:
            return view  # 失败回退：builder 三级裁剪兜底
        # covers_up_to = 被保留的最近原文之前那条的 seq（recent 对应 rows 的最后
        # keep_recent 行；无论其中是否夹着更早的 summary，都以序号为准）
        boundary_index = len(rows) - self.keep_recent - 1
        covers_up_to = int(rows[boundary_index]["seq"]) if boundary_index >= 0 else 0
        await repo.append(
            session_id, role="summary", text=summary_text, meta={"covers_up_to": covers_up_to}
        )
        head = ChatMessage(role="user", content=f"{SUMMARY_MARKER}\n{summary_text}")
        logger.info(
            "history.compacted",
            extra={"session_id": session_id, "old_messages": len(old), "tokens_before": total},
        )
        return [head, *recent]

    async def _summarize(self, old: list[ChatMessage]) -> str | None:
        transcript = json.dumps(
            [{"role": m["role"], "content": m.get("content") or ""} for m in old],
            ensure_ascii=False,
        )[:_TRANSCRIPT_CAP_CHARS]
        request: list[ChatMessage] = [
            ChatMessage(role="system", content=_SUMMARY_SYSTEM),
            ChatMessage(role="user", content=transcript),
        ]
        stream = self.provider.chat(request)
        try:
            parts: list[str] = []
            async for event in stream:  # 只关心文本增量
                text = getattr(event, "text", None)
                if isinstance(text, str):
                    parts.append(text)
            summary = "".join(parts).strip()
            return summary or None
        except Exception:
            logger.warning("history.compaction_failed", exc_info=True)
            return None
        finally:
            await stream.aclose()
