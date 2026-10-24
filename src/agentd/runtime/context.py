"""ContextBuilder：prompt 组装与 token 预算（M2 D2）。

预算 = (context_window − max_output) 再留 10% 安全余量（估算误差兜底）。
超限处置顺序（docs/architecture.md §6.4，LLM 摘要属 M4）：
    ① 从最旧开始，把历史 tool 结果替换为占位符（保留 tool_call_id 以维持配对）
    ② 截断历史区超长单条（system 与本轮 user 永不动）
    ③ 仍超限 → ContextBudgetError（报错而非静默截断用户输入）
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from agentd.providers.base import ChatMessage
from agentd.runtime.tokens import estimate_tokens

#: 每 message 的角色/结构固定开销（经验值）
_ROLE_OVERHEAD_TOKENS = 4
#: 占位符必须短且稳定，防止反复重放时抖动
_TOOL_TRIMMED = "[工具结果已按上下文预算裁剪]"
_MESSAGE_TRUNCATED = "\n…[历史消息已截断]"


class ContextBudgetError(Exception):
    """预算内装不下 system + 本轮输入：调用方应显式失败，不静默截断。"""


def message_tokens(message: ChatMessage) -> int:
    base = estimate_tokens(message.get("content") or "")
    if message.get("tool_calls"):
        base += estimate_tokens(json.dumps(message["tool_calls"], ensure_ascii=False))
    return base + _ROLE_OVERHEAD_TOKENS


class ContextBuilder:
    def __init__(self, *, context_window: int = 128_000, max_output: int = 4_096) -> None:
        self.context_window = context_window
        self.max_output = max_output

    @property
    def budget(self) -> int:
        return int((self.context_window - self.max_output) * 0.9)

    def build(
        self,
        history: Sequence[ChatMessage],
        user_input: str,
        *,
        system_prompt: str,
    ) -> list[ChatMessage]:
        system = ChatMessage(role="system", content=system_prompt)
        user = ChatMessage(role="user", content=user_input)
        messages: list[ChatMessage] = [system, *history, user]
        total = sum(message_tokens(m) for m in messages)
        if total <= self.budget:
            return messages
        total = self._trim_tool_results(messages, total)
        if total <= self.budget:
            return messages
        total = self._truncate_long_history(messages, total)
        if total <= self.budget:
            return messages
        raise ContextBudgetError(
            f"上下文预算 {self.budget} tokens 装不下 system + 本轮输入"
            f"（约 {total} tokens）：请缩短输入或开新会话"
        )

    def _trim_tool_results(self, messages: list[ChatMessage], total: int) -> int:
        """从最旧的 tool 消息开始替换为占位符；返回新的总 token。"""
        for i, message in enumerate(messages):
            if total <= self.budget:
                break
            if message["role"] != "tool":
                continue
            saved = message_tokens(message)
            trimmed = ChatMessage(role="tool", content=_TOOL_TRIMMED)
            if message.get("tool_call_id"):
                trimmed["tool_call_id"] = message["tool_call_id"]
            messages[i] = trimmed
            total -= saved - message_tokens(trimmed)
        return total

    def _truncate_long_history(self, messages: list[ChatMessage], total: int) -> int:
        """截断历史区（下标 1..-2）的超长单条；system 与本轮 user 永不动。"""
        per_message_cap = max(self.budget // 4, 64)
        changed = True
        while total > self.budget and changed:
            changed = False
            for i in range(1, len(messages) - 1):
                if total <= self.budget:
                    break
                message = messages[i]
                content = message.get("content")
                if content is None or _MESSAGE_TRUNCATED in content:
                    continue
                tokens = message_tokens(message)
                if tokens <= per_message_cap:
                    continue
                # 字符预算按 token×3 估（保守低于 ×4），保证截断后确实低于 cap
                keep_chars = max(per_message_cap * 3 - len(_MESSAGE_TRUNCATED), 64)
                truncated = ChatMessage(
                    role=message["role"],
                    content=content[:keep_chars] + _MESSAGE_TRUNCATED,
                )
                if message.get("tool_calls"):
                    truncated["tool_calls"] = message["tool_calls"]
                if message.get("tool_call_id"):
                    truncated["tool_call_id"] = message["tool_call_id"]
                messages[i] = truncated
                total -= tokens - message_tokens(truncated)
                changed = True
        return total
