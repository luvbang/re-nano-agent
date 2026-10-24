"""可重试的 Provider 装饰器（M1 D3）。

- 只在「尚未向下游产出任何事件」时重试：已发过 delta 再从头重试会造成重复输出
- 429 的 Retry-After 优先；否则指数退避 base * 2^attempt，封顶 max_delay_s
- sleep 函数可注入，测试里用 spy 断言退避序列
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence

from agentd.providers.base import (
    ChatMessage,
    Provider,
    ProviderError,
    ProviderEvent,
    ToolDefinition,
)

SleepFn = Callable[[float], Awaitable[None]]


class RetryingProvider(Provider):
    def __init__(
        self,
        inner: Provider,
        *,
        max_retries: int = 3,
        base_delay_s: float = 0.5,
        max_delay_s: float = 8.0,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self.inner = inner
        self.max_retries = max_retries
        self.base_delay_s = base_delay_s
        self.max_delay_s = max_delay_s
        self._sleep = sleep
        self.attempts = 0  # 观测面：总尝试次数

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[ProviderEvent, None]:
        attempt = 0
        while True:
            self.attempts += 1
            delivered = False
            stream = self.inner.chat(messages, tools=tools, model=model)
            try:
                async for event in stream:
                    delivered = True  # 必须在 yield 前置位：一旦产出就无法安全重试
                    yield event
                return
            except ProviderError as exc:
                if delivered or not exc.retryable or attempt >= self.max_retries:
                    raise
                delay = exc.retry_after_s
                if delay is None:
                    delay = min(self.base_delay_s * (2**attempt), self.max_delay_s)
                await self._sleep(delay)
                attempt += 1
