"""MemoryService：长期记忆的写入、注入、整理（v0.2-3，nanobot Memory/Dream 思路裁剪）。

- 写入：精确去重（同 project 同 content 的 active 记忆只 bump last_seen）
- 注入：active 记忆按 score/last_seen 排序，token 预算内拼成 system 附加段
- 自动提取：run 成功后用 provider 从对话中提取事实（可关；永不失败 run，
  失败退化为「本轮不产记忆」，与压缩的降级哲学一致）
- Dream 整理：规则版——去重（同内容组保留最新）、归档超过陈旧阈值且超出的
  低分记忆；LLM 驱动的语义合并留待后续
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agentd.providers.base import ChatMessage, Provider, TextDelta
from agentd.runtime.tokens import estimate_tokens
from agentd.storage.db import Database
from agentd.storage.repositories import AuditRepository, MemoryRepository

logger = logging.getLogger(__name__)

_MEMORY_HEADER = "# 长期记忆（跨会话事实）"
_EXTRACT_SYSTEM = (
    "你是记忆提取器。从对话中提取值得跨会话记住的事实（用户偏好、项目约定、"
    "环境事实、长期目标）。规则：只输出事实本身，一行一条，最多 5 条，"
    "每条不超过 120 字；没有值得记住的内容就什么都不输出；不要输出解释、"
    "标点列表符号或 JSON。"
)
_MAX_FACT_CHARS = 200


@dataclass(frozen=True, slots=True)
class DreamReport:
    scanned: int
    deduped: int  # 重复并入后归档的条数
    archived_stale: int  # 超过陈旧阈值归档的条数

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "deduped": self.deduped,
            "archived_stale": self.archived_stale,
        }


class MemoryService:
    def __init__(
        self,
        db: Database,
        *,
        budget_tokens: int = 512,
        max_active: int = 50,
        stale_days: int = 90,
        audit: AuditRepository | None = None,
    ) -> None:
        self.memories = MemoryRepository(db)
        self.audit = audit
        self.budget_tokens = budget_tokens
        self.max_active = max_active
        self.stale_days = stale_days

    async def add(
        self,
        project_id: str,
        content: str,
        *,
        source_session_id: str | None = None,
        source_run_id: str | None = None,
        actor: str = "system",
    ) -> tuple[dict[str, Any], bool]:
        """写入一条记忆；同内容已存在时 bump last_seen（返回 (行, 是否新建)）。"""
        content = content.strip()
        if not content:
            raise ValueError("memory content 不能为空")
        existing = await self.memories.find_same_content(project_id, content)
        if existing is not None:
            await self.memories.touch(str(existing["id"]))
            return existing, False
        row = await self.memories.create(
            project_id=project_id,
            content=content,
            source_session_id=source_session_id,
            source_run_id=source_run_id,
        )
        if self.audit is not None:
            await self.audit.append(
                action="memory.created",
                actor=actor,
                project_id=project_id,
                target=str(row["id"]),
                detail={"chars": len(content)},
            )
        return row, True

    async def list_active(self, project_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return await self.memories.list_recent(project_id, limit=limit)

    async def archive(self, project_id: str, memory_id: str, *, actor: str = "api") -> bool:
        row = await self.memories.get(memory_id)
        if row is None or str(row["project_id"]) != project_id:
            return False
        await self.memories.archive(memory_id)
        if self.audit is not None:
            await self.audit.append(
                action="memory.archived",
                actor=actor,
                project_id=project_id,
                target=memory_id,
            )
        return True

    async def prompt_block(self, project_id: str) -> str:
        """active 记忆拼成 system 附加段（预算内按 score/last_seen 取前 N 条）。

        注入即确认：被选中的记忆 bump last_seen（Dream 据此判陈旧）。
        无记忆时返回空串（不产生空标题段）。
        """
        rows = await self.memories.list_active(project_id, limit=self.max_active)
        if not rows:
            return ""
        chosen: list[str] = []
        used = estimate_tokens(_MEMORY_HEADER) + 1
        for row in rows:
            line = f"- {row['content']}"
            cost = estimate_tokens(line) + 1
            if used + cost > self.budget_tokens and chosen:
                break
            chosen.append(line)
            used += cost
            await self.memories.touch(str(row["id"]))
        if not chosen:
            return ""
        return "\n".join([_MEMORY_HEADER, *chosen])

    async def extract_from_dialog(
        self,
        project_id: str,
        *,
        session_id: str,
        run_id: str,
        user_input: str,
        assistant_reply: str,
        provider: Provider,
    ) -> list[str]:
        """用 provider 从本轮对话提取事实并写入记忆（自动提取路径）。

        任何失败都只记日志返回空列表——记忆提取永不影响 run 结果。
        """
        dialog = [
            ChatMessage(role="system", content=_EXTRACT_SYSTEM),
            ChatMessage(
                role="user",
                content=f"用户：{user_input}\n\n助手：{assistant_reply[:4000]}",
            ),
        ]
        try:
            facts: list[str] = []
            async for event in provider.chat(dialog):
                if isinstance(event, TextDelta):
                    for line in event.text.splitlines():
                        line = line.strip().lstrip("-•*0123456789. 、")
                        if line and len(line) <= _MAX_FACT_CHARS and line not in facts:
                            facts.append(line)
            facts = facts[:5]
            created: list[str] = []
            for fact in facts:
                _, is_new = await self.add(
                    project_id,
                    fact,
                    source_session_id=session_id,
                    source_run_id=run_id,
                    actor=f"run:{run_id}",
                )
                if is_new:
                    created.append(fact)
            if created:
                logger.info(
                    "memory.extracted", extra={"project_id": project_id, "n": len(created)}
                )
            return created
        except Exception as exc:
            logger.warning("memory.extract_failed", extra={"error": str(exc)})
            return []

    async def dream(self, project_id: str | None = None) -> DreamReport:
        """规则版整理：同内容去重 + 超陈旧阈值归档。返回报告供 CLI/测试断言。"""
        project_ids = (
            [project_id] if project_id is not None else await self.memories.project_ids()
        )
        scanned = deduped = archived_stale = 0
        for pid in project_ids:
            rows = await self.memories.list_recent(pid, limit=500)
            scanned += len(rows)
            seen_content: set[str] = set()
            for row in rows:
                if str(row["status"]) != "active":
                    continue
                content = str(row["content"])
                if content in seen_content:
                    await self.memories.archive(str(row["id"]))
                    deduped += 1
                    continue
                seen_content.add(content)
            stale = await self.memories.list_stale(
                pid, older_than_days=self.stale_days, limit=500
            )
            for row in stale:
                await self.memories.archive(str(row["id"]))
                archived_stale += 1
        return DreamReport(scanned=scanned, deduped=deduped, archived_stale=archived_stale)
