"""ContextBuilder 预算与裁剪测试（M2 D2 DoD：超长历史不超窗；截断可追溯）。"""

from __future__ import annotations

from typing import Any

import pytest

import agentd.runtime.tokens as tokens
from agentd.providers.base import ChatMessage
from agentd.providers.fake import FakeChatProvider, text_turn
from agentd.runtime.context import ContextBudgetError, ContextBuilder, message_tokens
from agentd.runtime.events import RunFailed
from agentd.runtime.runner import AgentRunner


def fallback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """让估算退化为 len/4，数字可精确断言。"""
    monkeypatch.setattr(tokens, "_load_encoder", lambda: None)


def user(text: str) -> ChatMessage:
    return ChatMessage(role="user", content=text)


def assistant(text: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=text)


def tool_msg(call_id: str, text: str) -> ChatMessage:
    return ChatMessage(role="tool", content=text, tool_call_id=call_id)


def test_within_budget_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback_only(monkeypatch)
    builder = ContextBuilder(context_window=1000, max_output=100)
    history = [user("问"), assistant("答")]
    messages = builder.build(history, "新问题", system_prompt="SYS")
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "问"  # 未被裁剪


def test_old_tool_results_trimmed_first(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback_only(monkeypatch)
    builder = ContextBuilder(context_window=300, max_output=50)  # budget=225
    big_tool = tool_msg("t1", "x" * 1200)  # ~300 tokens，远超预算
    history = [user("问1"), assistant("答1"), big_tool]
    messages = builder.build(history, "问2", system_prompt="SYS")

    trimmed = messages[3]
    assert trimmed["role"] == "tool"
    assert "裁剪" in (trimmed["content"] or "")
    assert trimmed.get("tool_call_id") == "t1"  # 配对关系保留
    # 用户与助手的原文不动
    assert messages[1]["content"] == "问1"
    assert messages[4]["content"] == "问2"
    assert sum(message_tokens(m) for m in messages) <= builder.budget


def test_long_history_message_truncated_with_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback_only(monkeypatch)
    builder = ContextBuilder(context_window=300, max_output=50)
    long_answer = assistant("y" * 2000)  # ~500 tokens
    history = [user("q"), long_answer]
    messages = builder.build(history, "now", system_prompt="SYS")
    truncated = messages[2]
    assert "已截断" in (truncated["content"] or "")
    assert sum(message_tokens(m) for m in messages) <= builder.budget


def test_oversized_user_input_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback_only(monkeypatch)
    builder = ContextBuilder(context_window=200, max_output=50)  # budget=135
    with pytest.raises(ContextBudgetError, match="预算"):
        builder.build([], "z" * 1200, system_prompt="SYS")


async def test_runner_maps_budget_error_to_run_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback_only(monkeypatch)
    builder = ContextBuilder(context_window=200, max_output=50)
    provider = FakeChatProvider(turns=[text_turn("never")])
    runner = AgentRunner(provider, context_builder=builder)
    events = [event async for event in runner.run([], "z" * 1200)]
    assert events[0].__class__.__name__ == "RunStarted"
    assert isinstance(events[-1], RunFailed)
    failed = events[-1]
    assert failed.code == "invalid_request" and failed.retryable is False
    assert provider.calls == []  # 根本没打模型


def test_budget_math(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback_only(monkeypatch)
    builder = ContextBuilder(context_window=1000, max_output=100)
    assert builder.budget == 810  # (1000-100)*0.9
    msg = ChatMessage(role="user", content="abcd")  # 1 token + 4 开销
    assert message_tokens(msg) == 5


# ---------- 工具结果超限落盘（同属 D2） ----------


async def test_tool_overflow_written_to_disk(tmp_path: Any) -> None:
    from agentd.tools.base import Tool, ToolResult
    from agentd.tools.registry import MAX_TOOL_RESULT_CHARS, ToolRegistry

    class BigTool(Tool):
        @property
        def definition(self):  # type: ignore[no-untyped-def]
            from agentd.providers.base import ToolDefinition

            return ToolDefinition(
                name="big", description="", parameters={"type": "object", "properties": {}}
            )

        async def execute(self, args: dict[str, Any]) -> ToolResult:
            return ToolResult(content="A" * (MAX_TOOL_RESULT_CHARS + 5000))

    registry = ToolRegistry(overflow_root=tmp_path).register(BigTool())
    result = await registry.execute("big", "{}", run_id="r_1")
    assert "完整结果已写入" in result.content
    written = tmp_path / "r_1" / "tool-results" / "001-big.txt"
    assert written.exists()
    assert len(written.read_text(encoding="utf-8")) == MAX_TOOL_RESULT_CHARS + 5000


async def test_tool_overflow_without_root_still_inline() -> None:
    from agentd.tools.base import Tool, ToolResult
    from agentd.tools.registry import MAX_TOOL_RESULT_CHARS, ToolRegistry

    class BigTool(Tool):
        @property
        def definition(self):  # type: ignore[no-untyped-def]
            from agentd.providers.base import ToolDefinition

            return ToolDefinition(
                name="big", description="", parameters={"type": "object", "properties": {}}
            )

        async def execute(self, args: dict[str, Any]) -> ToolResult:
            return ToolResult(content="A" * (MAX_TOOL_RESULT_CHARS + 10))

    result = await ToolRegistry().register(BigTool()).execute("big", "{}")
    assert "truncated" in result.content and "写入" not in result.content
