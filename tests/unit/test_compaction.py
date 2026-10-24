"""历史压缩 v1 测试（M4 D4 DoD：长对话上下文稳定；摘要失败不炸）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import agentd.runtime.tokens as tokens
from agentd.providers.fake import FakeChatProvider, text_turn
from agentd.runtime.compaction import SUMMARY_MARKER, HistoryCompactor, prompt_view
from agentd.runtime.context import ContextBuilder
from agentd.storage.db import Database
from agentd.storage.repositories import MessageRepository, ProjectRepository, SessionRepository


def fallback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tokens, "_load_encoder", lambda: None)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "c.db")
    database.migrate()
    return database


async def seed_history(db: Database, n_turns: int, chars: int) -> str:
    project = await ProjectRepository(db).create(name="p", workspace_path="/tmp")
    session = await SessionRepository(db).create(project_id=str(project["id"]))
    repo = MessageRepository(db)
    for i in range(n_turns):
        await repo.append(str(session["id"]), role="user", text=f"问{i} " + "x" * chars)
        await repo.append(str(session["id"]), role="assistant", text=f"答{i} " + "y" * chars)
    return str(session["id"])


async def test_prompt_view_drops_before_last_summary(db: Database) -> None:
    session_id = await seed_history(db, 2, 5)
    repo = MessageRepository(db)
    await repo.append(session_id, role="summary", text="旧摘要")
    await repo.append(session_id, role="user", text="摘要后的新问题")

    rows = await repo.list_for_session(session_id)
    view = prompt_view(rows)
    assert len(view) == 2
    assert view[0]["content"] is not None and view[0]["content"].startswith(SUMMARY_MARKER)
    assert "旧摘要" in view[0]["content"]
    assert view[1]["content"] == "摘要后的新问题"


async def test_compact_under_threshold_noop(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    fallback_only(monkeypatch)
    session_id = await seed_history(db, 3, 10)
    provider = FakeChatProvider(turns=[text_turn("不应被调用")])
    compactor = HistoryCompactor(
        db, provider, context_builder=ContextBuilder(context_window=100_000, max_output=1_000)
    )
    view = await compactor.compact(session_id)
    assert len(view) == 6  # 3 轮原文，未摘要
    assert provider.calls == []


async def test_compact_over_threshold_summarizes(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    fallback_only(monkeypatch)
    # 预算 = (2000-200)*0.9=1620；阈值 60%≈972。历史 10 轮 × ~每条 260 字符/4≈65+4 ≈ 690/轮 → 超
    session_id = await seed_history(db, 10, 250)
    provider = FakeChatProvider(turns=[text_turn("这是要点摘要")])
    compactor = HistoryCompactor(
        db,
        provider,
        context_builder=ContextBuilder(context_window=2_000, max_output=200),
    )
    view = await compactor.compact(session_id)

    # 摘要置顶 + 最近 6 条原文
    assert len(view) == 1 + 6
    assert view[0]["content"] is not None and "这是要点摘要" in view[0]["content"]
    # checkpoint 已落库（原始消息保留）
    rows = await MessageRepository(db).list_for_session(session_id)
    summary_rows = [r for r in rows if r["role"] == "summary"]
    assert len(summary_rows) == 1
    assert len(rows) == 20 + 1  # 10 轮原文 + 1 summary
    # 再压一次：prompt_view 从最新 summary 起步，阈值以下不再摘要
    provider2 = FakeChatProvider(turns=[text_turn("不应再摘要")])
    compactor2 = HistoryCompactor(
        db, provider2, context_builder=ContextBuilder(context_window=2_000, max_output=200)
    )
    view2 = await compactor2.compact(session_id)
    assert len(view2) == 1 + 6 and provider2.calls == []


async def test_compact_provider_failure_falls_back(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    fallback_only(monkeypatch)
    session_id = await seed_history(db, 10, 250)

    class Boom(FakeChatProvider):
        async def chat(self, messages, *, tools=None, model=None):  # type: ignore[no-untyped-def]
            from agentd.providers.base import ProviderServerError

            raise ProviderServerError("summarize down")
            yield  # pragma: no cover

    compactor = HistoryCompactor(
        db,
        Boom(),
        context_builder=ContextBuilder(context_window=2_000, max_output=200),
    )
    view = await compactor.compact(session_id)
    assert len(view) == 20  # 原样返回（回退 builder 裁剪）
    rows = await MessageRepository(db).list_for_session(session_id)
    assert not [r for r in rows if r["role"] == "summary"]  # 无 checkpoint 落库


async def test_short_history_not_compacted(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    fallback_only(monkeypatch)
    session_id = await seed_history(db, 4, 4_000)  # 超阈值但只有 8 条 = min_messages
    provider = FakeChatProvider(turns=[text_turn("x")])
    compactor = HistoryCompactor(
        db,
        provider,
        context_builder=ContextBuilder(context_window=2_000, max_output=200),
        min_messages=10,
    )
    view = await compactor.compact(session_id)
    assert len(view) == 8 and provider.calls == []


async def test_run_survives_with_compaction(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """压缩 + run 全链路：ChatService 带 compactor，摘要失败也不炸 run。"""
    fallback_only(monkeypatch)
    from agentd.services.chat_service import ChatService

    session_id = await seed_history(db, 10, 250)

    class FlakySummarizer(FakeChatProvider):
        def __init__(self) -> None:
            super().__init__(turns=[text_turn("好的回答")])
            self.calls_made = 0

        async def chat(self, messages, *, tools=None, model=None):  # type: ignore[no-untyped-def]
            from agentd.providers.base import ProviderServerError

            self.calls_made += 1
            if self.calls_made == 1:
                raise ProviderServerError("摘要挂了")
            async for event in super().chat(messages, tools=tools, model=model):
                yield event

    service = ChatService(db, compactor=HistoryCompactor(
        db,
        FlakySummarizer(),
        context_builder=ContextBuilder(context_window=2_000, max_output=200),
    ))
    events: list[Any] = []
    session_row = await db.fetch_one("SELECT project_id FROM sessions")
    assert session_row is not None
    async for event in service.stream(
        session_id,
        project_id=str(session_row["project_id"]),
        user_input="继续",
        provider=FakeChatProvider(turns=[text_turn("ok")]),
        model="fake",
    ):
        events.append(event)
    assert events[-1].__class__.__name__ == "RunCompleted"
