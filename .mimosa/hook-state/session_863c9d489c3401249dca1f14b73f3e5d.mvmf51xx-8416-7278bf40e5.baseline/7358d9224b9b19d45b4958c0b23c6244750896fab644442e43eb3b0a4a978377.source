"""Provider 协议与事件类型（M1 D1）。

运行时只依赖此处的抽象；具体实现（openai_compat / fake）可替换。
事件粒度 = Runner 需要的最小集合：文本/推理增量、累积完成的工具调用、流结束统计。
工具调用分片由 Provider 内部按 index 累积，对 Runner 只暴露完成态。

错误统一归一化为 ProviderError 子类（retryable + 可选 retry_after_s）；
是否重试由 RetryingProvider 决定，Provider 自身不重试。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict


@dataclass(frozen=True, slots=True)
class Usage:
    """一次模型调用（或整个 run 累计）的 token 用量。"""

    input_tokens: int = 0
    output_tokens: int = 0

    def plus(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


# ---------- 对话消息（OpenAI wire 兼容） ----------


class ToolCallFunction(TypedDict):
    name: str
    arguments: str  # 原始 JSON 字符串，解析责任在工具执行侧


class ToolCallWire(TypedDict):
    id: str
    type: str  # 固定 "function"
    function: ToolCallFunction


class ChatMessage(TypedDict):
    role: str  # system | user | assistant | tool
    content: str | None
    tool_calls: NotRequired[list[ToolCallWire]]
    tool_call_id: NotRequired[str]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """暴露给模型的工具声明（JSON Schema 参数）。"""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ---------- 流式事件 ----------


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallCompleted:
    """一次累积完成的工具调用；arguments 为原始 JSON 字符串。"""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class StreamEnd:
    finish_reason: str | None
    usage: Usage | None


ProviderEvent = TextDelta | ReasoningDelta | ToolCallCompleted | StreamEnd


# ---------- 错误归一化 ----------


class ProviderError(Exception):
    """上游模型错误基类。retryable 由 RetryingProvider 读取决定是否重试。"""

    def __init__(
        self, message: str, *, retryable: bool, retry_after_s: float | None = None
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_s = retry_after_s


class ProviderRateLimited(ProviderError):
    """429。优先使用响应头的 Retry-After。"""

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message, retryable=True, retry_after_s=retry_after_s)


class ProviderServerError(ProviderError):
    """上游 5xx，稍后重试通常可恢复。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class ProviderTimeout(ProviderError):
    """连接/读取超时。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class ProviderProtocolError(ProviderError):
    """断流 / 缺 [DONE] / 畸形响应。未消费任何事件时可安全重试。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class ProviderRejectedError(ProviderError):
    """上游 4xx（鉴权/参数/模型名错误），重试无意义。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


# ---------- 协议 ----------


class Provider(ABC):
    """chat.completions 风格的流式对话接口。

    返回 AsyncGenerator 而非 AsyncIterator：调用方（Runner）有提前关闭流的
    语义（aclose），这是取消语义的一部分，属于接口契约。
    """

    @abstractmethod
    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[ProviderEvent, None]:
        raise NotImplementedError
