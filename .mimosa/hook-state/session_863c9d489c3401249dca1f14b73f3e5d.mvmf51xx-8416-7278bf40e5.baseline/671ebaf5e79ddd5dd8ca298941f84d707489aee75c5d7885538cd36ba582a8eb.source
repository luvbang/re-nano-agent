"""ConversationService 与 CLI 重启续聊测试（M2 DoD：重启恢复）。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agentd.cli import _chat_repl
from agentd.providers.base import ChatMessage
from agentd.providers.fake import FakeChatProvider, demo_turn
from agentd.runtime.runner import AgentRunner
from agentd.services.conversation import (
    ConversationService,
    estimate_messages,
    split_turns,
    trim_to_budget,
)
from agentd.storage.db import Database
from agentd.storage.repositories import ProjectRepository, SessionRepository
from agentd.tools.builtin import BUILTIN_TOOLS
from agentd.tools.registry import ToolRegistry


def capture_print() -> tuple[list[str], Callable[..., None]]:
    out: list[str] = []

    def print_fn(*args: object, **kwargs: object) -> None:
        out.append("".join(str(a) for a in args))

    return out, print_fn


def scripted_input(lines: list[str]) -> Callable[[str], str]:
    remaining = iter(lines)

    def input_fn(prompt: str = "") -> str:
        try:
            return next(remaining)
        except StopIteration as exc:
            raise EOFError from exc

    return input_fn


def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "agentd.db")
    db.migrate()
    return db


async def _session_in_default_project(db: Database, workspace: Path) -> str:
    projects = ProjectRepository(db)
    project = await projects.get_by_name("default")
    if project is None:
        project = await projects.create(name="default", workspace_path=str(workspace))
    session = await SessionRepository(db).create(
        project_id=project["id"], external_user_id="cli", title="demo"
    )
    return str(session["id"])


class TestTrim:
    def test_split_and_trim_drops_oldest_turns_first(self) -> None:
        long_text = "这是一段用来撑大上下文体积的重复文本，" * 12
        messages: list[ChatMessage] = []
        for i in range(5):
            messages.append(ChatMessage(role="user", content=f"u{i} {long_text}"))
            messages.append(ChatMessage(role="assistant", content=f"a{i} {long_text}"))
        turns = split_turns(messages)
        assert [len(t) for t in turns] == [2, 2, 2, 2, 2]
        # 预算动态计算（tiktoken 与 len/4 的估算差异太大，不能写死数字）
        per_turn = estimate_messages(turns[0])
        total = estimate_messages(messages)
        budget = total - 2 * per_turn
        trimmed = trim_to_budget(messages, budget_tokens=budget)
        first = trimmed[0]["content"] or ""
        assert first.startswith("u2")  # 最旧两轮被整轮丢弃
        last = trimmed[-1]["content"] or ""
        assert last.startswith("a4")  # 最新一轮永远保留

    def test_trim_keeps_last_turn_even_over_budget(self) -> None:
        messages = [
            ChatMessage(role="user", content="u " + "y" * 100_000),
            ChatMessage(role="assistant", content="a " + "y" * 100_000),
        ]
        trimmed = trim_to_budget(messages, budget_tokens=10)
        assert len(trimmed) == 2  # 只有一轮时不再丢


async def test_persist_and_reload_roundtrip(tmp_path: Path) -> None:
    db = _db(tmp_path)
    session_id = await _session_in_default_project(db, tmp_path)
    conversation = ConversationService(db, token_budget=24_000)
    exchange = [
        ChatMessage(role="user", content="看下时间"),
        ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "t_1",
                    "type": "function",
                    "function": {"name": "get_time", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(role="tool", content="utc=...", tool_call_id="t_1"),
        ChatMessage(role="assistant", content="现在时间是 utc=..."),
    ]
    await conversation.persist_exchange(session_id, exchange)
    reloaded = await conversation.load_history(session_id)
    assert reloaded == exchange
    db.close()


async def test_cli_restart_resumes_history(tmp_path: Path) -> None:
    """两个进程（两次 REPL）共用同一 DB 会话：第二次自动载入第一次的历史。"""
    db = _db(tmp_path)
    session_id = await _session_in_default_project(db, tmp_path)
    conversation = ConversationService(db, token_budget=24_000)

    async def persist(exchange: list[ChatMessage]) -> None:
        await conversation.persist_exchange(session_id, exchange)

    # 第一次会话：两轮
    provider1 = FakeChatProvider(turn_fn=demo_turn)
    _out1, print1 = capture_print()
    await _chat_repl(
        AgentRunner(provider1, tools=ToolRegistry().register_all(BUILTIN_TOOLS)),
        input_fn=scripted_input(["第一轮问题", "第二轮问题", "exit"]),
        print_fn=print1,
        on_turn=persist,
    )
    # 第二次会话（模拟重启）：从 DB 重建历史
    provider2 = FakeChatProvider(turn_fn=demo_turn)
    history2 = await conversation.load_history(session_id)
    assert len(history2) == 4  # 两轮 × (user + assistant)
    _out2, print2 = capture_print()
    await _chat_repl(
        AgentRunner(provider2, tools=ToolRegistry().register_all(BUILTIN_TOOLS)),
        input_fn=scripted_input(["第三轮问题", "exit"]),
        print_fn=print2,
        history=history2,
    )
    # 第三轮调用时模型能看到前两轮完整历史：system + 4 历史 + user
    assert len(provider2.calls[0]) == 6
    assert provider2.calls[0][-1]["content"] == "第三轮问题"
    assert provider2.calls[0][1]["content"] == "第一轮问题"
    assert provider2.calls[0][-2]["content"] == "(fake)你说的是：第二轮问题"
    db.close()
