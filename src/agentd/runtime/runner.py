"""AgentRunner：provider ↔ tool 对话循环（M1 D2/D3）。

一次 run = prepare（system+history+user 组装）→ loop（流式消费、工具执行）→ 终态事件。
- 最多 max_iterations 次模型调用；最后一次仍要工具则判 model_error（不静默续跑）
- 工具失败/超时转 ToolCompleted(status=error)，绝不中断 run
- 整 run 有 timeout_s 上限（asyncio.timeout），超时发 RunFailed("timeout")
- ProviderError 归一化到契约错误码；取消依赖 async generator 的关闭语义（连带关闭 provider 流）
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from agentd.providers.base import (
    ChatMessage,
    Provider,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
    StreamEnd,
    TextDelta,
    ToolCallCompleted,
    ToolCallWire,
    Usage,
)
from agentd.providers.base import (
    ReasoningDelta as ProviderReasoningDelta,
)
from agentd.runtime.events import (
    MessageCompleted,
    MessageDelta,
    ReasoningDelta,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunStarted,
    ToolCompleted,
    ToolStarted,
)
from agentd.tools.base import ToolResult
from agentd.tools.registry import ToolRegistry

DEFAULT_SYSTEM_PROMPT = "你是 agentd，一个可自托管的 Agent 运行时。回答保持简洁、可靠。"


class MaxModelCallsError(ProviderError):
    """达到迭代上限仍无最终回答；按 model_error 上报，不可重试。"""

    def __init__(self, max_iterations: int) -> None:
        super().__init__(
            f"达到模型调用上限（{max_iterations} 次）仍未给出最终回答", retryable=False
        )


class _UsageTotals:
    """Usage 是 frozen 值对象，这里用可变累加器跨轮累计。"""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, usage: Usage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens

    def usage(self) -> Usage:
        return Usage(input_tokens=self.input_tokens, output_tokens=self.output_tokens)


class AgentRunner:
    def __init__(
        self,
        provider: Provider,
        *,
        tools: ToolRegistry | None = None,
        run_id: str = "r_local",
        session_id: str = "s_local",
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_iterations: int = 8,
        timeout_s: float = 600.0,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.run_id = run_id
        self.session_id = session_id
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.timeout_s = timeout_s

    async def run(
        self, history: Sequence[ChatMessage], user_input: str
    ) -> AsyncGenerator[RunEvent, None]:
        """执行一轮对话；事件序列以 RunStarted 开头，以 RunCompleted 或 RunFailed 结尾。"""
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=self.system_prompt),
            *history,
            ChatMessage(role="user", content=user_input),
        ]
        yield RunStarted(run_id=self.run_id, session_id=self.session_id)
        usage_total = _UsageTotals()
        drive = self._drive(messages, usage_total)
        try:
            async with asyncio.timeout(self.timeout_s):
                async for event in drive:
                    yield event
        except TimeoutError:
            yield RunFailed(
                code="timeout", message=f"run 超过 {self.timeout_s:.0f}s 上限", retryable=True
            )
        except ProviderError as exc:
            yield RunFailed(
                code=_provider_error_code(exc),
                message=str(exc),
                retryable=bool(exc.retryable),
            )
        finally:
            # 消费方提前放弃（aclose/任务取消）时，把关闭语义显式传导到内层流，
            # 不依赖异步 GC —— 否则 provider 侧资源悬挂到事件循环收尾。
            await drive.aclose()

    async def _drive(
        self, messages: list[ChatMessage], usage_total: _UsageTotals
    ) -> AsyncGenerator[RunEvent, None]:
        for iteration in range(self.max_iterations):
            text = ""
            calls: list[ToolCallCompleted] = []
            stream = self.provider.chat(
                messages, tools=self.tools.definitions() if self.tools else None
            )
            try:
                async for event in stream:
                    match event:
                        case TextDelta(delta):
                            text += delta
                            yield MessageDelta(delta=delta)
                        case ProviderReasoningDelta(delta):
                            yield ReasoningDelta(delta=delta)
                        case ToolCallCompleted() as call:
                            calls.append(call)
                        case StreamEnd() as end:
                            if end.usage is not None:
                                usage_total.add(end.usage)
            finally:
                await stream.aclose()
            usage = usage_total.usage()
            if not calls:
                yield MessageCompleted(content=text, usage=usage)
                yield RunCompleted(usage=usage)
                return
            if iteration == self.max_iterations - 1:
                raise MaxModelCallsError(self.max_iterations)
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=text or None,
                    tool_calls=[_to_wire(call) for call in calls],
                )
            )
            for call in calls:
                args = _parse_args(call.arguments)
                yield ToolStarted(tool_call_id=call.id, name=call.name, args=args)
                started = time.perf_counter()
                result = await self._execute(call)
                duration_ms = int((time.perf_counter() - started) * 1000)
                yield ToolCompleted(
                    tool_call_id=call.id,
                    name=call.name,
                    status="error" if result.is_error else "ok",
                    duration_ms=duration_ms,
                )
                messages.append(
                    ChatMessage(role="tool", content=result.content, tool_call_id=call.id)
                )

    async def _execute(self, call: ToolCallCompleted) -> ToolResult:
        if self.tools is None:
            return ToolResult.error(f"工具 {call.name} 不存在：注册表未配置")
        return await self.tools.execute(call.name, call.arguments)


def _parse_args(arguments_json: str) -> dict[str, Any]:
    """解析工具参数供事件展示；解析失败返回空对象（执行侧还会再给出错误结果）。"""
    try:
        parsed: Any = json.loads(arguments_json) if arguments_json.strip() else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _provider_error_code(exc: ProviderError) -> str:
    if isinstance(exc, ProviderRateLimited):
        return "rate_limited"
    if isinstance(exc, ProviderTimeout):
        return "timeout"
    return "model_error"


def _to_wire(call: ToolCallCompleted) -> ToolCallWire:
    return ToolCallWire(
        id=call.id,
        type="function",
        function={"name": call.name, "arguments": call.arguments},
    )
