"""FailoverProvider 与 provider 工厂的测试（v0.2 多 provider DoD）。

覆盖：主 provider 未产出事件即失败 → 切换备选；已产出事件后失败 → 不切换、
错误上抛；全链失败 → 抛最后一个错误；工厂按 settings 装配（向后兼容 /
anthropic 主链 / fallbacks 去重 / 无凭据返回 None）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence

import pytest

from agentd.config import Settings
from agentd.providers.anthropic import AnthropicProvider
from agentd.providers.base import (
    ChatMessage,
    Provider,
    ProviderError,
    ProviderEvent,
    ProviderRateLimited,
    ProviderRejectedError,
    ProviderServerError,
    StreamEnd,
    TextDelta,
    Usage,
)
from agentd.providers.factory import build_provider
from agentd.providers.failover import FailoverProvider
from agentd.providers.openai_compat import OpenAICompatProvider
from agentd.providers.retry import RetryingProvider


class ScriptedProvider(Provider):
    """脚本化 provider：每次 chat 回放一条「流脚本」（事件序列 + 可选流末错误）。

    流末错误在事件 yield 完之后抛出——模拟"已产出 delta 后中途崩了"的真实形态。
    """

    def __init__(
        self,
        streams: Sequence[tuple[Sequence[ProviderEvent], ProviderError | None]],
        *,
        name: str = "scripted",
    ) -> None:
        self._streams = list(streams)
        self._i = 0
        self.model = name
        self.calls = 0

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[object] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[ProviderEvent, None]:
        self.calls += 1
        events, error = self._streams[min(self._i, len(self._streams) - 1)]
        self._i += 1
        for event in events:
            yield event
        if error is not None:
            raise error


async def collect(p: Provider) -> list[object]:
    return [e async for e in p.chat([ChatMessage(role="user", content="hi")])]


class TestFailover:
    async def test_switches_when_primary_fails_before_events(self) -> None:
        primary = ScriptedProvider([([], ProviderRateLimited("429"))], name="primary")
        fallback = ScriptedProvider(
            [([TextDelta("来自备选"), StreamEnd("stop", Usage(1, 1))], None)], name="fallback"
        )
        chain = FailoverProvider([primary, fallback])

        events = await collect(chain)
        assert events == [TextDelta("来自备选"), StreamEnd("stop", Usage(1, 1))]
        assert primary.calls == 1 and fallback.calls == 1
        assert chain.model == "primary"

    async def test_no_switch_after_events_delivered(self) -> None:
        primary = ScriptedProvider(
            [([TextDelta("已输出一半")], ProviderServerError("半路崩了"))], name="primary"
        )
        fallback = ScriptedProvider([([TextDelta("不该出现")], None)], name="fallback")
        chain = FailoverProvider([primary, fallback])

        with pytest.raises(ProviderError, match="半路崩了"):
            await collect(chain)
        assert fallback.calls == 0

    async def test_walks_chain_and_raises_last_error(self) -> None:
        first = ScriptedProvider([([], ProviderRateLimited("429"))], name="first")
        second = ScriptedProvider([([], ProviderServerError("500"))], name="second")
        third = ScriptedProvider([([], ProviderRejectedError("401 bad key"))], name="third")
        chain = FailoverProvider([first, second, third])

        with pytest.raises(ProviderRejectedError, match="401"):
            await collect(chain)
        assert (first.calls, second.calls, third.calls) == (1, 1, 1)

    async def test_empty_chain_rejected(self) -> None:
        with pytest.raises(ValueError):
            FailoverProvider([])

    async def test_happy_primary_never_touches_fallback(self) -> None:
        primary = ScriptedProvider(
            [([TextDelta("ok"), StreamEnd("stop", None)], None)], name="primary"
        )
        fallback = ScriptedProvider([], name="fallback")
        events = await collect(FailoverProvider([primary, fallback]))
        assert len(events) == 2
        assert fallback.calls == 0


class TestFactory:
    def test_openai_only_is_backward_compatible(self) -> None:
        settings = Settings(env="test", llm_api_key="sk-x", llm_provider="openai")
        provider, model = build_provider(settings)
        assert isinstance(provider, RetryingProvider)
        assert isinstance(provider.inner, OpenAICompatProvider)
        assert model == "gpt-4o-mini"

    def test_no_credentials_returns_none(self) -> None:
        settings = Settings(env="test", llm_api_key="", anthropic_api_key="")
        provider, _ = build_provider(settings)
        assert provider is None

    def test_anthropic_primary_uses_own_credentials(self) -> None:
        settings = Settings(
            env="test",
            llm_api_key="",
            llm_provider="anthropic",
            anthropic_api_key="ak-x",
            anthropic_model="claude-test-model",
        )
        provider, model = build_provider(settings)
        assert isinstance(provider, RetryingProvider)
        assert isinstance(provider.inner, AnthropicProvider)
        assert provider.inner.model == "claude-test-model"
        assert model == "claude-test-model"

    def test_fallbacks_build_failover_chain_and_dedupe(self) -> None:
        settings = Settings(
            env="test",
            llm_api_key="sk-x",
            anthropic_api_key="ak-x",
            llm_provider="openai",
            llm_fallbacks="anthropic, openai",  # 重复的 openai 应去重
        )
        provider, _ = build_provider(settings)
        assert isinstance(provider, FailoverProvider)
        # 顺序 = 主链去重保序；anthropic 未设模型时用默认值
        assert [m.model for m in provider.members] == ["gpt-4o-mini", "claude-sonnet-4-5"]

    def test_fallback_without_credentials_is_skipped(self) -> None:
        settings = Settings(
            env="test",
            llm_api_key="sk-x",
            llm_provider="openai",
            llm_fallbacks="anthropic",  # 无 anthropic 凭据 → 跳过
        )
        provider, _ = build_provider(settings)
        assert isinstance(provider, RetryingProvider)  # 单成员，不构成链

    def test_responses_provider_shape(self) -> None:
        from agentd.providers.responses import ResponsesProvider

        settings = Settings(env="test", llm_api_key="sk-x", llm_provider="responses")
        provider, model = build_provider(settings)
        assert isinstance(provider, RetryingProvider)
        assert isinstance(provider.inner, ResponsesProvider)
        assert model == "gpt-4o-mini"
