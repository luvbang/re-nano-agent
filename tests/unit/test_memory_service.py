"""MemoryService 单元测试（v0.2-3）：去重写入、预算注入、Dream 整理、自动提取。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentd.providers.base import (
    Provider,
    ProviderEvent,
    StreamEnd,
    TextDelta,
    Usage,
)
from agentd.providers.fake import FakeChatProvider, text_turn
from agentd.runtime.runner import AgentRunner
from agentd.services.memory import MemoryService
from agentd.storage.db import Database
from agentd.storage.repositories import MemoryRepository, ProjectRepository


@pytest.fixture
async def db(tmp_path: Path) -> Any:
    db = Database(tmp_path / "memory-test.db")
    db.migrate()
    yield db
    db.close()


@pytest.fixture
async def project_id(db: Database) -> str:
    row = await ProjectRepository(db).create(name="p", workspace_path="pending")
    return str(row["id"])


def service(db: Database, **overrides: Any) -> MemoryService:
    return MemoryService(db, **overrides)


async def test_add_and_dedupe_bumps_last_seen(db: Database, project_id: str) -> None:
    svc = service(db)
    row1, created1 = await svc.add(project_id, "用户偏好深色主题")
    row2, created2 = await svc.add(project_id, "用户偏好深色主题")

    assert created1 is True and created2 is False
    assert row1["id"] == row2["id"]  # 同内容只保留一条
    assert row2["last_seen_at"] >= row1["last_seen_at"]


async def test_add_empty_content_rejected(db: Database, project_id: str) -> None:
    with pytest.raises(ValueError):
        await service(db).add(project_id, "   ")


async def test_prompt_block_empty_when_no_memories(db: Database, project_id: str) -> None:
    assert await service(db).prompt_block(project_id) == ""


async def test_prompt_block_lists_and_bumps_last_seen(db: Database, project_id: str) -> None:
    svc = service(db)
    await svc.add(project_id, "项目使用 SQLite")
    await svc.add(project_id, "用户偏好深色主题")

    block = await svc.prompt_block(project_id)
    assert block.startswith("# 长期记忆")
    assert "项目使用 SQLite" in block and "用户偏好深色主题" in block

    rows = await MemoryRepository(db).list_active(project_id)
    # 注入即确认：所有被选中的记忆 last_seen 被刷新（不早于 created）
    assert all(r["last_seen_at"] >= r["created_at"] for r in rows)


async def test_prompt_block_respects_token_budget(db: Database, project_id: str) -> None:
    svc = service(db, budget_tokens=64)
    for i in range(6):
        await svc.add(project_id, f"事实 {i}：" + "很长的记忆内容" * 8)

    block = await svc.prompt_block(project_id)
    assert block.startswith("# 长期记忆")
    # 预算 64 tokens：只装得下前几条，不会全量注入
    assert block.count("\n- ") < 6


async def test_runner_injects_memory_block_into_system(db: Database, project_id: str) -> None:
    provider = FakeChatProvider(turns=[text_turn("好的")])
    runner = AgentRunner(
        provider,
        memory_block="# 长期记忆\n- 用户偏好深色主题",
        context_builder=None,
    )
    _ = [e async for e in runner.run([], "你好")]
    first_call = provider.calls[0]
    assert first_call[0]["role"] == "system"
    assert "长期记忆" in (first_call[0]["content"] or "")
    assert "用户偏好深色主题" in (first_call[0]["content"] or "")


async def test_extract_from_dialog_writes_facts(db: Database, project_id: str) -> None:
    extraction_stream: list[ProviderEvent] = [
        TextDelta("- 用户偏好深色主题\n"),
        TextDelta("项目部署在 VPS\n"),
        StreamEnd("stop", Usage(5, 5)),
    ]
    provider = FakeChatProvider(turns=[extraction_stream])
    svc = service(db)

    created = await svc.extract_from_dialog(
        project_id,
        session_id="s_1",
        run_id="r_1",
        user_input="我喜欢深色主题，部署在 VPS",
        assistant_reply="记住了",
        provider=provider,
    )
    assert len(created) == 2
    rows = await MemoryRepository(db).list_active(project_id)
    assert {r["content"] for r in rows} == {"用户偏好深色主题", "项目部署在 VPS"}


async def test_extract_caps_at_five_and_strips_bullets(db: Database, project_id: str) -> None:
    lines = "\n".join(f"- 事实 {i}" for i in range(8))
    provider = FakeChatProvider(turns=[[TextDelta(lines + "\n"), StreamEnd("stop", None)]])
    created = await service(db).extract_from_dialog(
        project_id,
        session_id="s_1",
        run_id="r_1",
        user_input="u",
        assistant_reply="a",
        provider=provider,
    )
    assert len(created) == 5
    assert all(not c.startswith("-") for c in created)


async def test_extract_failure_degrades_to_noop(db: Database, project_id: str) -> None:
    class Broken(Provider):
        model = "broken"

        async def chat(self, messages, *, tools=None, model=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("上游炸了")
            yield  # pragma: no cover

    created = await service(db).extract_from_dialog(
        project_id,
        session_id="s_1",
        run_id="r_1",
        user_input="u",
        assistant_reply="a",
        provider=Broken(),
    )
    assert created == []  # 永不失败调用方
    assert await MemoryRepository(db).list_active(project_id) == []


async def test_dream_dedupes_and_archives_stale(db: Database, project_id: str) -> None:
    repo = MemoryRepository(db)
    svc = service(db, stale_days=90)
    await svc.add(project_id, "重复记忆")  # last_seen = now
    await repo.create(project_id=project_id, content="重复记忆")  # 手工造第二条同内容
    stale_row = await repo.create(project_id=project_id, content="很久没被想起的记忆")
    await db.execute(
        "UPDATE memories SET last_seen_at = datetime('now', '-200 days') WHERE id = ?",
        (stale_row["id"],),
    )

    report = await svc.dream(project_id)

    assert report.as_dict() == {"scanned": 3, "deduped": 1, "archived_stale": 1}
    active = await repo.list_active(project_id)
    assert [r["content"] for r in active] == ["重复记忆"]
