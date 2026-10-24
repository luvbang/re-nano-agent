"""RetryingProvider 退避重试测试（M1 D3 DoD：重试次数/延迟可测）。"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence

import pytest

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
    ToolDefinition,
    Usage,
)
from agentd.providers.retry import RetryingProvider


class FlakyProvider(Provider):
    """前 N 次调用抛预设错误，之后正常回放 events；记录调用数。"""

    def __init__(
        self, failures: Sequence[ProviderError], events: Sequence[ProviderEvent]
    ) -> None:
        self.failures = list(failures)
        self.events = list(events)
        self.calls = 0

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[ProviderEvent, None]:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        for event in self.events:
            yield event


class SleepSpy:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def ok_events() -> list[ProviderEvent]:
    return [TextDelta("hi"), StreamEnd("stop", Usage(1, 1))]


async def test_retries_with_exponential_backoff_then_succeeds() -> None:
    spy = SleepSpy()
    inner = FlakyProvider(
        [ProviderServerError("503"), ProviderServerError("503 again")], ok_events()
    )
    provider = RetryingProvider(inner, sleep=spy)

    events = [event async for event in provider.chat([ChatMessage(role="user", content="x")])]

    assert [type(e) for e in events] == [TextDelta, StreamEnd]
    assert inner.calls == 3
    assert spy.delays == [0.5, 1.0]


async def test_retry_after_header_wins_over_backoff() -> None:
    spy = SleepSpy()
    inner = FlakyProvider([ProviderRateLimited("429", retry_after_s=3.0)], ok_events())
    provider = RetryingProvider(inner, sleep=spy)

    _ = [event async for event in provider.chat([ChatMessage(role="user", content="x")])]

    assert spy.delays == [3.0]


async def test_backoff_capped_at_max_delay() -> None:
    spy = SleepSpy()
    failures = [ProviderServerError("x") for _ in range(5)]
    inner = FlakyProvider(failures, ok_events())
    provider = RetryingProvider(inner, base_delay_s=1.0, max_delay_s=2.5, sleep=spy)

    with pytest.raises(ProviderServerError):
        _ = [event async for event in provider.chat([ChatMessage(role="user", content="x")])]

    assert spy.delays == [1.0, 2.0, 2.5]


async def test_non_retryable_error_raises_immediately() -> None:
    spy = SleepSpy()
    inner = FlakyProvider([ProviderRejectedError("401 bad key")], ok_events())
    provider = RetryingProvider(inner, sleep=spy)

    with pytest.raises(ProviderRejectedError):
        _ = [event async for event in provider.chat([ChatMessage(role="user", content="x")])]
    assert inner.calls == 1
    assert spy.delays == []


async def test_no_retry_after_events_delivered() -> None:
    """已产出 delta 后断流：不能重试（会重复输出），直接抛错。"""

    class HalfThenBoom(FlakyProvider):
        async def chat(
            self,
            messages: Sequence[ChatMessage],
            *,
            tools: Sequence[ToolDefinition] | None = None,
            model: str | None = None,
        ) -> AsyncGenerator[ProviderEvent, None]:
            self.calls += 1
            yield TextDelta("半截")
            raise ProviderServerError("stream died")

    spy = SleepSpy()
    provider = RetryingProvider(HalfThenBoom([], []), sleep=spy)
    collected: list[ProviderEvent] = []
    with pytest.raises(ProviderServerError):
        async for event in provider.chat([ChatMessage(role="user", content="x")]):
            collected.append(event)
    assert len(collected) == 1
    assert spy.delays == []


async def test_exhausted_retries_raise_last_error() -> None:
    spy = SleepSpy()
    failures = [ProviderServerError("x") for _ in range(4)]
    inner = FlakyProvider(failures, ok_events())
    provider = RetryingProvider(inner, sleep=spy)

    with pytest.raises(ProviderServerError):
        _ = [event async for event in provider.chat([ChatMessage(role="user", content="x")])]

    assert inner.calls == 4  # 首次 + 3 次重试
    assert provider.attempts == 4
    assert spy.delays == [0.5, 1.0, 2.0]
