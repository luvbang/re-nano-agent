"""端到端闭环（M2 D5 DoD）：模型 → 读文件 → 改文件 → 总结，全程落库。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentd.providers.base import StreamEnd, ToolCallCompleted
from agentd.providers.fake import FakeChatProvider, text_turn
from agentd.runtime.events import ToolStarted
from agentd.services.chat_service import ChatService
from agentd.storage.db import Database
from agentd.storage.repositories import ProjectRepository, SessionRepository
from agentd.tools.filesystem import filesystem_tools
from agentd.tools.registry import ToolRegistry


@pytest.fixture
async def env(tmp_path: Path) -> dict[str, Any]:
    db = Database(tmp_path / "e2e.db")
    db.migrate()
    projects = ProjectRepository(db)
    sessions = SessionRepository(db)
    project = await projects.create(name="e2e", workspace_path=str(tmp_path / "ws"))
    session = await sessions.create(project_id=str(project["id"]), title="e2e")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("draft status", encoding="utf-8")
    return {
        "db": db,
        "project_id": str(project["id"]),
        "session_id": str(session["id"]),
        "workspace": workspace,
    }


async def test_read_edit_summarize_loop(env: dict[str, Any]) -> None:
    provider = FakeChatProvider(
        turns=[
            # ① 先读
            [
                ToolCallCompleted(id="c1", name="read_file", arguments='{"path": "notes.txt"}'),
                StreamEnd("tool_calls", None),
            ],
            # ② 看到内容后改
            [
                ToolCallCompleted(
                    id="c2",
                    name="edit_file",
                    arguments='{"path": "notes.txt", "old_string": "draft", "new_string": "final"}',
                ),
                StreamEnd("tool_calls", None),
            ],
            # ③ 总结
            text_turn("已把 draft 改成 final，文件现在是 final status"),
        ]
    )
    registry = ToolRegistry().register_all(filesystem_tools(env["workspace"]))
    service = ChatService(env["db"])
    events = [
        event
        async for event in service.stream(
            str(env["session_id"]),
            project_id=str(env["project_id"]),
            user_input="处理 notes.txt",
            provider=provider,
            model="fake-e2e",
            tools=registry,
        )
    ]

    # 文件真实被改
    assert (env["workspace"] / "notes.txt").read_text(encoding="utf-8") == "final status"
    # 事件序列：两次工具对 + 最终完成
    from agentd.runtime.events import ToolCompleted

    tool_events = [e for e in events if isinstance(e, (ToolStarted, ToolCompleted))]
    assert [e.__class__.__name__ for e in tool_events] == [
        "ToolStarted",
        "ToolCompleted",
        "ToolStarted",
        "ToolCompleted",
    ]
    assert all(e.status == "ok" for e in tool_events if isinstance(e, ToolCompleted))
    assert events[-1].__class__.__name__ == "RunCompleted"
    # 第二次模型调用能看到 read_file 的真实结果（模型据它决定 edit）
    second_call = provider.calls[1]
    read_result = next(m for m in second_call if m["role"] == "tool")
    assert read_result["content"] == "draft status"
    # 全程落库：user/assistant/ tool/assistant/ tool/assistant
    rows = await env["db"].fetch_all(
        "SELECT role FROM messages WHERE session_id = ? ORDER BY seq", (env["session_id"],)
    )
    assert [r["role"] for r in rows] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
