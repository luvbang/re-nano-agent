"""CLI chat REPL 测试（M1 D4 DoD：CLI 连续 10 轮对话正常）。"""

from __future__ import annotations

import argparse
from collections.abc import AsyncGenerator, Callable, Sequence

from agentd.cli import _build_chat_provider, _chat_repl
from agentd.config import Settings
from agentd.providers.base import (
    ChatMessage,
    Provider,
    ProviderEvent,
    ProviderServerError,
    ToolDefinition,
)
from agentd.providers.fake import FakeChatProvider, demo_turn
from agentd.runtime.runner import AgentRunner
from agentd.tools.builtin import BUILTIN_TOOLS
from agentd.tools.registry import ToolRegistry


class FailFirstProvider(Provider):
    """第一次调用抛上游错误，之后委托内层 provider。"""

    def __init__(self, inner: Provider) -> None:
        self.inner = inner
        self.call_count = 0

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[ProviderEvent, None]:
        self.call_count += 1
        if self.call_count == 1:
            raise ProviderServerError("upstream down")
            yield  # pragma: no cover — 使函数成为 async generator
        async for event in self.inner.chat(messages, tools=tools, model=model):
            yield event


def make_runner(provider: FakeChatProvider) -> AgentRunner:
    registry = ToolRegistry().register_all(BUILTIN_TOOLS)
    return AgentRunner(provider, tools=registry)


def scripted_input(lines: list[str]) -> Callable[[str], str]:
    remaining = iter(lines)

    def input_fn(prompt: str = "") -> str:
        try:
            return next(remaining)
        except StopIteration as exc:
            raise EOFError from exc

    return input_fn


def capture_print() -> tuple[list[str], Callable[..., None]]:
    out: list[str] = []

    def print_fn(*args: object, **kwargs: object) -> None:
        out.append("".join(str(a) for a in args))

    return out, print_fn


async def test_repl_tool_loop_and_history() -> None:
    provider = FakeChatProvider(turn_fn=demo_turn)
    out, print_fn = capture_print()
    rc = await _chat_repl(
        make_runner(provider),
        input_fn=scripted_input(["你好", "现在几点了？", "/echo 回显我", "exit"]),
        print_fn=print_fn,
    )
    joined = "".join(out)
    assert rc == 0
    assert "(fake)你说的是：你好" in joined
    assert "[tool] get_time {}" in joined
    assert "[tool] get_time ok" in joined
    assert "[tool] echo" in joined
    assert "[usage] in=" in joined
    # 工具轮 = 2 次模型调用（tool_calls + 收到结果后的回答）
    assert len(provider.calls) == 5
    # 历史逐轮增长且带工具消息
    assert "tool_call_id" in provider.calls[-1][-2] or provider.calls[-1][-1]["role"] == "tool"


async def test_repl_ten_rounds_doD() -> None:
    provider = FakeChatProvider(turn_fn=demo_turn)
    _out, print_fn = capture_print()
    lines = [f"第{i}轮" for i in range(1, 11)] + ["exit"]
    rc = await _chat_repl(make_runner(provider), input_fn=scripted_input(lines), print_fn=print_fn)
    assert rc == 0
    assert len(provider.calls) == 10  # 每轮一次模型调用
    # 每轮都能看到完整历史（多轮记忆）
    assert len(provider.calls[0]) == 2  # 首轮 = system + user
    assert len(provider.calls[-1]) == 20  # system + 前 9 轮(user+assistant) + 本轮 user
    last_content = provider.calls[-1][-1]["content"]
    assert last_content is not None and "第10轮" in last_content


async def test_repl_eof_exits_cleanly() -> None:
    provider = FakeChatProvider(turn_fn=demo_turn)
    _out, print_fn = capture_print()
    rc = await _chat_repl(
        make_runner(provider), input_fn=scripted_input(["hi"]), print_fn=print_fn
    )
    assert rc == 0  # 输入耗尽（EOF）正常退出


async def test_repl_failed_turn_not_written_to_history() -> None:
    provider = FailFirstProvider(FakeChatProvider(turn_fn=demo_turn))
    out, print_fn = capture_print()
    rc = await _chat_repl(
        AgentRunner(provider, tools=ToolRegistry().register_all(BUILTIN_TOOLS)),
        input_fn=scripted_input(["第一轮会失败", "第二轮", "exit"]),
        print_fn=print_fn,
    )
    assert rc == 0
    joined = "".join(out)
    assert "[failed:model_error]" in joined
    # 失败轮不写回历史：第二次调用只含 system+user（第二轮）
    assert provider.call_count == 2


def test_build_chat_provider_fake_and_missing_key() -> None:
    settings = Settings(env="test")

    fake_args = argparse.Namespace(fake=True, model=None)
    assert isinstance(_build_chat_provider(fake_args, settings), FakeChatProvider)

    real_args = argparse.Namespace(fake=False, model=None)
    assert _build_chat_provider(real_args, settings) is None  # 未配置 key → 明确报错路径
