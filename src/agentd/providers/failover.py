"""故障切换链（v0.2 多 provider）。

语义与 RetryingProvider 对齐：仅在「尚未向下游产出任何事件」时切换下一个
provider——已产出 delta 后切换会造成重复输出，此时错误原样上抛。
成员各自携带凭据与默认模型；chat() 不向下传 model（每个成员用自己的模型）。

典型装配：FailoverProvider([RetryingProvider(primary), RetryingProvider(fallback…)])
——先在同一 provider 内重试（快路径 429），重试耗尽才整链切换。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence

from agentd.providers.base import (
    ChatMessage,
    Provider,
    ProviderError,
    ProviderEvent,
    ToolDefinition,
)


class FailoverProvider(Provider):
    def __init__(self, members: Sequence[Provider]) -> None:
        if not members:
            raise ValueError("FailoverProvider 需要至少一个 provider")
        self.members = list(members)
        # run 记录 / 用量归属沿用主 provider 的模型名
        self.model = getattr(members[0], "model", "custom")

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[ProviderEvent, None]:
        last_error: ProviderError | None = None
        for member in self.members:
            delivered = False
            try:
                async for event in member.chat(messages, tools=tools):
                    delivered = True  # yield 前置位：一旦产出就无法安全切换
                    yield event
                return
            except ProviderError as exc:
                if delivered:
                    raise
                last_error = exc  # 该成员重试耗尽/不可重试 → 尝试下一个
        assert last_error is not None  # members 非空保证
        raise last_error
