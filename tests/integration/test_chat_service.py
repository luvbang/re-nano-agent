"""ChatService 持久化测试（M2 D1 DoD：重启后同 session 续聊；run 状态机落库）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentd.providers.base import (
    ProviderServerError,
    StreamEnd,
    ToolCallCompleted,
    Usage,
)
from agentd.providers.fake import FakeChatProvider, text_turn
from agentd.services.chat_service import ChatService
from agentd.storage.db import Database
from agentd.storage.repositories import (
    MessageRepository,
    ProjectRepository,
    SessionRepository,
    ToolCallRepository,
    UsageRepository,
)
from agentd.tools.builtin import BUILTIN_TOOLS
from agentd.tools.registry import ToolRegistry


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


@pytest.fixture
async def session(db: Database) -> dict[str, Any]:
    projects = ProjectRepository(db)
    sessions = SessionRepository(db)
    project = await projects.create(name="p1", workspace_path="/tmp/ws")
    row = await sessions.create(project_id=str(project["id"]), title="s1")
    row["project_id"] = project["id"]
    return row


def registry() -> ToolRegistry:
    return ToolRegistry().register_all(BUILTIN_TOOLS)


async def run_turn(
    db: Database, session: dict[str, Any], provider: FakeChatProvider, text: str
) -> list[object]:
    service = ChatService(db)
    return [
        event
        async for event in service.stream(
            str(session["id"]),
            project_id=str(session["project_id"]),
            user_input=text,
            provider=provider,
            model="fake-test",
            tools=registry(),
        )
    ]


async def test_messages_persisted_with_tool_wire(db: Database, session: dict[str, Any]) -> None:
    provider = FakeChatProvider(
        turns=[
            [
                ToolCallCompleted(id="c1", name="echo", arguments='{"text": "hi"}'),
                StreamEnd("tool_calls", Usage(5, 5)),
            ],
            text_turn("done", usage=Usage(3, 3)),
        ]
    )
    events = await run_turn(db, session, provider, "打个招呼")
    assert events[-1].__class__.__name__ == "RunCompleted"

    rows = await MessageRepository(db).list_for_session(str(session["id"]))
    roles = [row["role"] for row in rows]
    assert roles == ["user", "assistant", "tool", "assistant"]
    # assistant 带 tool_calls wire，tool 带 tool_call_id
    assert rows[1]["tool_calls_json"] is not None and "echo" in rows[1]["tool_calls_json"]
    assert rows[2]["tool_call_id"] == "c1"
    assert "hi" in (rows[2]["content_json"] or "")


async def test_restart_continues_same_session(db: Database, session: dict[str, Any]) -> None:
    # 第一次进程：一轮对话落库
    await run_turn(db, session, FakeChatProvider(turns=[text_turn("第一答")]), "第一问")
    # 模拟重启：全新对象，只共享 DB 文件
    db2 = Database(db.path)
    db2.migrate()
    provider2 = FakeChatProvider(turn_fn=lambda msgs: text_turn("第二答"))
    service = ChatService(db2)
    _ = [
        event
        async for event in service.stream(
            str(session["id"]),
            project_id=str(session["project_id"]),
            user_input="第二问",
            provider=provider2,
            model="fake-test",
        )
    ]
    # 第二次调用看到的模型历史 = 第一轮完整四条消息(user/assistant)
    sent = provider2.calls[0]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "第一问"
    assert sent[2]["content"] == "第一答"
    # 会话总消息数：2 轮 × (user+assistant)
    rows = await MessageRepository(db2).list_for_session(str(session["id"]))
    assert [row["role"] for row in rows] == ["user", "assistant", "user", "assistant"]


async def test_run_state_machine_and_usage(db: Database, session: dict[str, Any]) -> None:
    await run_turn(db, session, FakeChatProvider(turns=[text_turn("ok", usage=Usage(7, 4))]), "hi")
    all_runs = await db.fetch_all("SELECT * FROM runs")
    assert len(all_runs) == 1
    run = all_runs[0]
    assert run["status"] == "completed"
    assert run["input_tokens"] == 7 and run["output_tokens"] == 4
    assert run["finished_at"] is not None
    usage = await UsageRepository(db).totals_by_project(str(session["project_id"]))
    assert usage["n"] == 1 and usage["input_tokens"] == 7


async def test_failed_run_marks_run_and_keeps_user_message(
    db: Database, session: dict[str, Any]
) -> None:
    class FailProvider(FakeChatProvider):
        async def chat(self, messages, *, tools=None, model=None):  # type: ignore[no-untyped-def]
            raise ProviderServerError("upstream down")
            yield  # pragma: no cover

    service = ChatService(db)
    events = [
        event
        async for event in service.stream(
            str(session["id"]),
            project_id=str(session["project_id"]),
            user_input="会失败",
            provider=FailProvider(),
            model="fake-test",
        )
    ]
    assert events[-1].__class__.__name__ == "RunFailed"
    all_runs = await db.fetch_all("SELECT * FROM runs")
    assert all_runs[0]["status"] == "failed"
    assert "upstream" in (all_runs[0]["error_json"] or "")
    # user 消息真实发生 → 落库；assistant 无可信内容 → 不落
    rows = await MessageRepository(db).list_for_session(str(session["id"]))
    assert [row["role"] for row in rows] == ["user"]


async def test_tool_calls_recorded_with_preview(db: Database, session: dict[str, Any]) -> None:
    provider = FakeChatProvider(
        turns=[
            [
                ToolCallCompleted(id="c9", name="echo", arguments='{"text": "预览内容"}'),
                StreamEnd("tool_calls", None),
            ],
            text_turn("ok"),
        ]
    )
    await run_turn(db, session, provider, "x")
    run_row = await db.fetch_one("SELECT id FROM runs")
    assert run_row is not None
    records = await ToolCallRepository(db).list_by_run(str(run_row["id"]))
    assert len(records) == 1
    assert records[0]["name"] == "echo"
    assert records[0]["status"] == "ok"
    assert "预览内容" in (records[0]["result_preview"] or "")
