"""AnthropicProvider 的 respx fixture 测试（v0.2 多 provider DoD）。

覆盖：纯文本流+usage、tool_use 流（input_json_delta 累积）、请求形状
（system 提取 / tool_result 映射 / 连续同角色合并 / tools.input_schema）、
429（Retry-After）、5xx、4xx、529、error 事件、超时、断流、畸形 JSON。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from agentd.providers.anthropic import AnthropicProvider
from agentd.providers.base import (
    ChatMessage,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderRejectedError,
    ProviderServerError,
    ProviderTimeout,
    StreamEnd,
    TextDelta,
    ToolCallCompleted,
    ToolDefinition,
    Usage,
)

URL = "https://api.anthropic.test/v1/messages"


def sse(*events: tuple[str, dict[str, Any]], stop: bool = True) -> bytes:
    blocks = [
        f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}"
        for name, payload in events
    ]
    if stop:
        blocks.append('event: message_stop\ndata: {"type":"message_stop"}')
    return ("\n\n".join(blocks) + "\n\n").encode("utf-8")


def message_start(input_tokens: int = 10) -> tuple[str, dict[str, Any]]:
    return (
        "message_start",
        {"type": "message_start", "message": {"usage": {"input_tokens": input_tokens}}},
    )


def text_block(idx: int, text: str) -> tuple[str, dict[str, Any]]:
    return (
        "content_block_delta",
        {"index": idx, "delta": {"type": "text_delta", "text": text}},
    )


def json_delta(idx: int, partial: str) -> tuple[str, dict[str, Any]]:
    return (
        "content_block_delta",
        {"index": idx, "delta": {"type": "input_json_delta", "partial_json": partial}},
    )


def message_delta(stop_reason: str, out_tokens: int = 7) -> tuple[str, dict[str, Any]]:
    return (
        "message_delta",
        {"delta": {"stop_reason": stop_reason}, "usage": {"output_tokens": out_tokens}},
    )


def tool_start(idx: int, tool_id: str, name: str) -> tuple[str, dict[str, Any]]:
    return (
        "content_block_start",
        {"index": idx, "content_block": {"type": "tool_use", "id": tool_id, "name": name}},
    )


def provider(**overrides: Any) -> AnthropicProvider:
    return AnthropicProvider(
        api_key="ak-test", base_url="https://api.anthropic.test", model="claude-test", **overrides
    )


async def collect(p: AnthropicProvider, messages: list[ChatMessage] | None = None) -> list[Any]:
    return [e async for e in p.chat(messages or [ChatMessage(role="user", content="hi")])]


@respx.mock
async def test_text_stream_and_usage() -> None:
    body = sse(
        message_start(),
        ("content_block_start", {"index": 0, "content_block": {"type": "text"}}),
        text_block(0, "你"),
        text_block(0, "好"),
        ("content_block_stop", {"index": 0}),
        message_delta("end_turn"),
    )
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    events = await collect(provider())

    assert events[0] == TextDelta("你")
    assert events[1] == TextDelta("好")
    end = events[2]
    assert isinstance(end, StreamEnd)
    assert end.finish_reason == "stop"
    assert end.usage == Usage(input_tokens=10, output_tokens=7)
    assert route.called


@respx.mock
async def test_tool_use_stream_and_payload_shape() -> None:
    body = sse(
        message_start(12),
        ("content_block_start", {"index": 0, "content_block": {"type": "text"}}),
        text_block(0, "我查一下"),
        ("content_block_stop", {"index": 0}),
        tool_start(1, "toolu_1", "get_time"),
        json_delta(1, '{"tz":'),
        json_delta(1, '"utc"}'),
        ("content_block_stop", {"index": 1}),
        message_delta("tool_use", out_tokens=20),
    )
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    p = provider(max_tokens=512)
    tools = [ToolDefinition(name="get_time", description="时间", parameters={"type": "object"})]
    messages: list[ChatMessage] = [
        ChatMessage(role="system", content="你是时钟"),
        ChatMessage(role="user", content="几点了"),
    ]
    events = [e async for e in p.chat(messages, tools=tools)]

    assert events[0] == TextDelta("我查一下")
    assert events[1] == ToolCallCompleted(id="toolu_1", name="get_time", arguments='{"tz":"utc"}')
    end = events[2]
    assert isinstance(end, StreamEnd)
    assert end.finish_reason == "tool_calls"
    assert end.usage == Usage(input_tokens=12, output_tokens=20)

    payload = json.loads(route.calls.last.request.content)
    assert payload["system"] == "你是时钟"
    assert payload["max_tokens"] == 512
    assert payload["tools"] == [
        {"name": "get_time", "description": "时间", "input_schema": {"type": "object"}}
    ]


@respx.mock
async def test_tool_result_and_consecutive_roles_merged() -> None:
    body = sse(
        message_start(),
        text_block(0, "好"),
        ("content_block_stop", {"index": 0}),
        message_delta("end_turn"),
    )
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    messages: list[ChatMessage] = [
        ChatMessage(role="user", content="第一问"),
        ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "toolu_9",
                    "type": "function",
                    "function": {"name": "echo", "arguments": '{"text": "hi"}'},
                }
            ],
        ),
        ChatMessage(role="tool", content="echo: hi", tool_call_id="toolu_9"),
        ChatMessage(role="user", content="第二问"),
    ]
    await collect(provider(), messages)

    payload = json.loads(route.calls.last.request.content)
    msgs = payload["messages"]
    # user / assistant(tool_use) / user(tool_result + 第二问合并) 交替
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    tool_use = msgs[1]["content"][0]
    assert tool_use == {
        "type": "tool_use",
        "id": "toolu_9",
        "name": "echo",
        "input": {"text": "hi"},
    }
    tool_result = msgs[2]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_9"
    assert tool_result["content"] == "echo: hi"
    assert msgs[2]["content"][1] == {"type": "text", "text": "第二问"}


@respx.mock
async def test_429_with_retry_after() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(429, text="rate limited", headers={"retry-after": "3.5"})
    )
    with pytest.raises(ProviderRateLimited) as exc_info:
        await collect(provider())
    assert exc_info.value.retry_after_s == 3.5


@respx.mock
async def test_5xx_and_529_are_server_errors() -> None:
    respx.post(URL).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(ProviderServerError):
        await collect(provider())
    respx.post(URL).mock(return_value=httpx.Response(529, text="overloaded"))
    with pytest.raises(ProviderServerError):
        await collect(provider())


@respx.mock
async def test_4xx_rejected() -> None:
    respx.post(URL).mock(return_value=httpx.Response(401, text="bad key"))
    with pytest.raises(ProviderRejectedError):
        await collect(provider())


@respx.mock
async def test_error_event_mapping() -> None:
    rate_limited = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            content=("event: error\ndata: " + json.dumps(rate_limited) + "\n\n").encode("utf-8"),
        )
    )
    with pytest.raises(ProviderRateLimited):
        await collect(provider())
    rejected = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    respx.post(URL).mock(
        return_value=httpx.Response(
            200, content=("event: error\ndata: " + json.dumps(rejected) + "\n\n").encode("utf-8")
        )
    )
    with pytest.raises(ProviderRejectedError):
        await collect(provider())


@respx.mock
async def test_timeout() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectTimeout("timed out"))
    with pytest.raises(ProviderTimeout):
        await collect(provider())


@respx.mock
async def test_stream_without_message_stop_is_protocol_error() -> None:
    # 断流：只有 message_start，没有 message_stop
    respx.post(URL).mock(
        return_value=httpx.Response(200, content=sse(message_start(), stop=False))
    )
    with pytest.raises(ProviderProtocolError):
        await collect(provider())


@respx.mock
async def test_malformed_json_is_protocol_error() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(200, content=b"event: content_block_delta\ndata: {oops\n\n")
    )
    with pytest.raises(ProviderProtocolError):
        await collect(provider())
