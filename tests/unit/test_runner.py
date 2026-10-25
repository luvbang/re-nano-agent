"""AgentRunner 脚本化测试（M1 D2/D3 DoD）。

用 FakeChatProvider 预设回合：单轮文本、多轮工具、到上限、错误归一化、
run 超时、工具错误不炸循环、取消无悬挂。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence

import pytest

from agentd.providers.base import (
    ChatMessage,
    Provider,
    ProviderError,
    ProviderEvent,
    ProviderRateLimited,
    ProviderServerError,
    StreamEnd,
    TextDelta,
    ToolCallCompleted,
    ToolDefinition,
    Usage,
)
from agentd.providers.fake import FakeChatProvider, text_turn
from agentd.runtime.events import (
    MessageCompleted,
    MessageDelta,
    RunCompleted,
    RunFailed,
    RunStarted,
    ToolCompleted,
    ToolStarted,
)
from agentd.runtime.runner import AgentRunner
from agentd.tools.builtin import EchoTool
from agentd.tools.registry import ToolRegistry


class RaisingProvider(Provider):
    """调用即抛错的 provider；用于错误归一化测试。"""

    def __init__(self, error: ProviderError) -> None:
        self.error = error

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[ProviderEvent, None]:
        raise self.error
        yield  # pragma: no cover — 仅为把函数体变成 async generator


def echo_registry() -> ToolRegistry:
    return ToolRegistry().register(EchoTool())


def tool_call(call_id: str = "call_1", arguments: str = '{"text": "hi"}') -> ToolCallCompleted:
    return ToolCallCompleted(id=call_id, name="echo", arguments=arguments)


async def events_of(runner: AgentRunner, text: str = "你好") -> list[object]:
    return [event async for event in runner.run([], text)]


def types_of(events: list[object]) -> list[str]:
    return [event.__class__.__name__ for event in events]


async def test_single_turn_text() -> None:
    provider = FakeChatProvider(turns=[text_turn("你好，我是回答。", usage=Usage(10, 5))])
    events = await events_of(AgentRunner(provider))

    assert types_of(events) == ["RunStarted", "MessageDelta", "MessageCompleted", "RunCompleted"]
    delta = events[1]
    assert isinstance(delta, MessageDelta)
    assert delta.delta == "你好，我是回答。"
    completed = events[2]
    assert isinstance(completed, MessageCompleted)
    assert completed.usage == Usage(10, 5)


async def test_system_and_history_assembled() -> None:
    provider = FakeChatProvider(turns=[text_turn("ok")])
    history: list[ChatMessage] = [
        ChatMessage(role="user", content="第一轮"),
        ChatMessage(role="assistant", content="第一答"),
    ]
    runner = AgentRunner(provider, system_prompt="SYS")
    _ = [event async for event in runner.run(history, "第二轮")]

    sent = provider.calls[0]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[0]["content"] == "SYS"
    assert sent[-1]["content"] == "第二轮"


async def test_tool_loop_roundtrip_and_message_wire() -> None:
    provider = FakeChatProvider(
        turns=[
            [tool_call("call_1", '{"text": "hi"}'), StreamEnd("tool_calls", Usage(5, 5))],
            text_turn("echo 说的是 hi", usage=Usage(7, 7)),
        ]
    )
    runner = AgentRunner(provider, tools=echo_registry())
    events = await events_of(runner)

    assert types_of(events) == [
        "RunStarted",
        "ToolStarted",
        "ToolCompleted",
        "MessageDelta",
        "MessageCompleted",
        "RunCompleted",
    ]
    started_event = events[1]
    assert isinstance(started_event, ToolStarted)
    assert started_event.args == {"text": "hi"}
    done = events[2]
    assert isinstance(done, ToolCompleted)
    assert done.status == "ok"
    assert done.duration_ms >= 0
    assert done.result == "hi"  # v0.2-4：事件携带工具输出预览

    # 第二次模型调用看到的 wire 消息：assistant(tool_calls) + tool 结果
    second_call = provider.calls[1]
    assistant_msg = second_call[-2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "echo"
    tool_msg = second_call[-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["content"] == "hi"
    # 工具定义确实下发了
    assert provider.requested_tools[0] is not None
    assert provider.requested_tools[0][0].name == "echo"
    # usage 跨轮累计
    final = events[-1]
    assert isinstance(final, RunCompleted)
    assert final.usage == Usage(12, 12)


async def test_tool_error_does_not_break_loop() -> None:
    provider = FakeChatProvider(
        turns=[
            [tool_call("call_bad", "不是json"), StreamEnd("tool_calls", None)],
            text_turn("已收到工具错误", usage=Usage(2, 2)),
        ]
    )
    runner = AgentRunner(provider, tools=echo_registry())
    events = await events_of(runner)

    completed = events[2]
    assert isinstance(completed, ToolCompleted)
    assert completed.status == "error"
    # 模型收到了错误内容并正常收尾
    assert isinstance(events[-1], RunCompleted)
    tool_msg = provider.calls[1][-1]
    assert tool_msg["content"] is not None and "JSON" in tool_msg["content"]


async def test_unknown_tool_reports_error_result() -> None:
    provider = FakeChatProvider(
        turns=[
            [
                ToolCallCompleted(id="c1", name="nope", arguments="{}"),
                StreamEnd("tool_calls", None),
            ],
            text_turn("ok"),
        ]
    )
    runner = AgentRunner(provider)  # 不带注册表
    events = await events_of(runner)
    assert isinstance(events[2], ToolCompleted)
    assert events[2].status == "error"
    assert isinstance(events[-1], RunCompleted)


async def test_max_iterations_fails_run() -> None:
    always_tools: list[list[ProviderEvent]] = [
        [tool_call(f"call_{i}"), StreamEnd("tool_calls", None)] for i in range(3)
    ]
    provider = FakeChatProvider(turns=always_tools)
    runner = AgentRunner(provider, tools=echo_registry(), max_iterations=2)
    events = await events_of(runner)

    failed = events[-1]
    assert isinstance(failed, RunFailed)
    assert failed.code == "model_error"
    assert "上限" in failed.message
    assert failed.retryable is False
    # 恰好 max_iterations 次模型调用，第 2 次直接判失败不再执行工具
    assert len(provider.calls) == 2


async def test_provider_rate_limited_maps_to_run_failed() -> None:
    runner = AgentRunner(RaisingProvider(ProviderRateLimited("429 too many")))
    events = await events_of(runner)
    failed = events[-1]
    assert isinstance(failed, RunFailed)
    assert failed.code == "rate_limited"
    assert failed.retryable is True


async def test_run_timeout_emits_timeout_failure() -> None:
    provider = FakeChatProvider(turns=[[TextDelta("a"), StreamEnd("stop", None)]] * 10, delay_s=0.5)
    runner = AgentRunner(provider, timeout_s=0.15)
    events = await events_of(runner)
    failed = events[-1]
    assert isinstance(failed, RunFailed)
    assert failed.code == "timeout"


async def test_cancel_closes_provider_stream_no_pending_tasks() -> None:
    long_turn = [TextDelta(f"chunk{i}") for i in range(100)] + [StreamEnd("stop", None)]
    provider = FakeChatProvider(turns=[long_turn], delay_s=0.02)
    runner = AgentRunner(provider)

    stream = runner.run([], "hi")
    first = await anext(stream)
    assert isinstance(first, RunStarted)
    second = await anext(stream)
    assert isinstance(second, MessageDelta)
    await stream.aclose()  # 消费方放弃（等价于任务取消）

    assert provider.open_streams == 0  # provider 流被连带关闭
    await asyncio.sleep(0.05)  # 给清理任务让出事件循环
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert pending == []


async def test_task_cancel_semantics() -> None:
    """经 asyncio.Task 取消（M3 /stop 的实际路径）也不悬挂。"""
    long_turn = [TextDelta(f"c{i}") for i in range(100)] + [StreamEnd("stop", None)]
    provider = FakeChatProvider(turns=[long_turn], delay_s=0.02)
    runner = AgentRunner(provider)

    async def consume() -> list[object]:
        return [event async for event in runner.run([], "hi")]

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)
    assert provider.open_streams == 0


async def test_provider_server_error_maps_to_model_error() -> None:
    events = await events_of(AgentRunner(RaisingProvider(ProviderServerError("503 gone"))))
    failed = events[-1]
    assert isinstance(failed, RunFailed)
    assert failed.code == "model_error"
    assert failed.retryable is True
