"""脚本化 Fake Provider（M1）：无网络的 Runner/CLI 测试与演示。

- turns：每次 chat 按序取出一"回合脚本"逐事件回放（dataclass 事件直接给出）
- turn_fn：根据当前消息动态决定脚本（CLI 演示用，可触发工具调用回路）
- open_streams 追踪未关闭的流数量，用于断言"取消后无悬挂"
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Sequence

from agentd.providers.base import (
    ChatMessage,
    Provider,
    ProviderEvent,
    StreamEnd,
    TextDelta,
    ToolCallCompleted,
    ToolDefinition,
    Usage,
)

TurnScript = Sequence[ProviderEvent]
TurnFn = Callable[[Sequence[ChatMessage]], TurnScript]


def text_turn(text: str, *, usage: Usage | None = None) -> list[ProviderEvent]:
    """最常用的单回合：一段完整文本 + 正常结束。"""
    return [TextDelta(text), StreamEnd(finish_reason="stop", usage=usage or Usage(6, 6))]


class FakeChatProvider(Provider):
    def __init__(
        self,
        turns: Sequence[TurnScript] | None = None,
        *,
        turn_fn: TurnFn | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self._turns = list(turns or [])
        self._turn_fn = turn_fn
        self.delay_s = delay_s
        # 断言用的观测面
        self.calls: list[list[ChatMessage]] = []
        self.requested_tools: list[list[ToolDefinition] | None] = []
        self.requested_models: list[str | None] = []
        self.open_streams = 0

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[ProviderEvent, None]:
        self.calls.append(list(messages))
        self.requested_tools.append(list(tools) if tools else None)
        self.requested_models.append(model)
        self.open_streams += 1
        try:
            for event in self._next_turn(messages):
                if self.delay_s:
                    await asyncio.sleep(self.delay_s)
                yield event
        finally:
            self.open_streams -= 1

    def _next_turn(self, messages: Sequence[ChatMessage]) -> TurnScript:
        if self._turn_fn is not None:
            return self._turn_fn(messages)
        if self._turns:
            turn = self._turns.pop(0)
            return turn
        return text_turn("(fake)ok")


def demo_turn(messages: Sequence[ChatMessage]) -> TurnScript:
    """CLI --fake 演示脚本：普通寒暄直答；"几点" 触发 get_time；"/echo X" 触发 echo。

    第二次进入时 messages 末尾是工具结果，直接基于它作答，形成
    模型 → 工具 → 模型 → 回答 的闭环。
    """
    last = messages[-1]
    if last["role"] == "tool":
        return [
            TextDelta(f"工具 {last['tool_call_id']} 的结果是：{last['content']}"),
            StreamEnd(finish_reason="stop", usage=Usage(9, 9)),
        ]
    text = last.get("content") or ""
    if "几点" in text or text.startswith("/time"):
        return [
            ToolCallCompleted(id="call_demo_1", name="get_time", arguments="{}"),
            StreamEnd(finish_reason="tool_calls", usage=Usage(5, 5)),
        ]
    if text.startswith("/echo "):
        arguments = json.dumps({"text": text[len("/echo ") :]}, ensure_ascii=False)
        return [
            ToolCallCompleted(id="call_demo_1", name="echo", arguments=arguments),
            StreamEnd(finish_reason="tool_calls", usage=Usage(5, 5)),
        ]
    return [
        TextDelta(f"(fake)你说的是：{text}"),
        StreamEnd(finish_reason="stop", usage=Usage(6, 6)),
    ]
