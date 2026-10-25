"""ResponsesProvider 的 respx fixture 测试（v0.2 多 provider DoD）。

覆盖：纯文本流+usage、function_call 条目（added/delta 分片/done）、请求形状
（instructions / function_call_output / 扁平 tools）、completed/incomplete、
response.failed、error 事件、429/5xx/4xx、断流。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from agentd.providers.base import (
    ChatMessage,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderRejectedError,
    ProviderServerError,
    StreamEnd,
    TextDelta,
    ToolCallCompleted,
    ToolDefinition,
    Usage,
)
from agentd.providers.responses import ResponsesProvider

URL = "https://api.openai.test/v1/responses"


def sse(*events: tuple[str, dict[str, Any]]) -> bytes:
    blocks = [
        f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}"
        for name, payload in events
    ]
    return ("\n\n".join(blocks) + "\n\n").encode("utf-8")


def completed(input_tokens: int = 10, output_tokens: int = 7) -> tuple[str, dict[str, Any]]:
    return (
        "response.completed",
        {
            "response": {
                "status": "completed",
                "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            }
        },
    )


def provider(**overrides: Any) -> ResponsesProvider:
    return ResponsesProvider(
        api_key="sk-test", base_url="https://api.openai.test/v1", model="test-model", **overrides
    )


async def collect(p: ResponsesProvider, messages: list[ChatMessage] | None = None) -> list[Any]:
    return [e async for e in p.chat(messages or [ChatMessage(role="user", content="hi")])]


@respx.mock
async def test_text_stream_and_usage() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            content=sse(
                ("response.output_text.delta", {"delta": "你"}),
                ("response.output_text.delta", {"delta": "好"}),
                completed(),
            ),
        )
    )
    events = await collect(provider())

    assert events[0] == TextDelta("你")
    assert events[1] == TextDelta("好")
    end = events[2]
    assert isinstance(end, StreamEnd)
    assert end.finish_reason == "stop"
    assert end.usage == Usage(input_tokens=10, output_tokens=7)
    assert route.called


@respx.mock
async def test_function_call_stream_and_payload_shape() -> None:
    call_item = {"type": "function_call", "id": "item_1", "call_id": "call_1", "name": "get_time"}
    body = sse(
        ("response.output_item.added", {"item": call_item}),
        ("response.function_call_arguments.delta", {"item_id": "item_1", "delta": '{"tz":'}),
        ("response.function_call_arguments.delta", {"item_id": "item_1", "delta": '"utc"}'}),
        ("response.output_item.done", {"item": {**call_item, "arguments": '{"tz":"utc"}'}}),
        completed(input_tokens=12, output_tokens=20),
    )
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    p = provider(max_output_tokens=777)
    tools = [ToolDefinition(name="get_time", description="时间", parameters={"type": "object"})]
    messages: list[ChatMessage] = [
        ChatMessage(role="system", content="你是时钟"),
        ChatMessage(role="user", content="几点了"),
    ]
    events = [e async for e in p.chat(messages, tools=tools)]

    assert events[0] == ToolCallCompleted(id="call_1", name="get_time", arguments='{"tz":"utc"}')
    end = events[1]
    assert isinstance(end, StreamEnd)
    assert end.finish_reason == "stop"
    assert end.usage == Usage(input_tokens=12, output_tokens=20)

    expected_tool = {
        "type": "function",
        "name": "get_time",
        "description": "时间",
        "parameters": {"type": "object"},
    }
    expected_input = {"role": "user", "content": [{"type": "input_text", "text": "几点了"}]}
    payload = json.loads(route.calls.last.request.content)
    assert payload["instructions"] == "你是时钟"
    assert payload["max_output_tokens"] == 777
    assert payload["tools"] == [expected_tool]
    assert payload["input"][0] == expected_input


@respx.mock
async def test_tool_round_trip_payload() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=sse(completed())))
    messages: list[ChatMessage] = [
        ChatMessage(role="user", content="几点了"),
        ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "call_9",
                    "type": "function",
                    "function": {"name": "get_time", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(role="tool", content="utc=12:00", tool_call_id="call_9"),
    ]
    await collect(provider(), messages)

    payload = json.loads(route.calls.last.request.content)
    items = payload["input"]
    assert items[0]["role"] == "user"
    assert items[1] == {
        "type": "function_call",
        "call_id": "call_9",
        "name": "get_time",
        "arguments": "{}",
    }
    assert items[2] == {"type": "function_call_output", "call_id": "call_9", "output": "utc=12:00"}


@respx.mock
async def test_incomplete_maps_to_length() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            content=sse(
                ("response.output_text.delta", {"delta": "截断的回答"}),
                (
                    "response.incomplete",
                    {
                        "response": {
                            "status": "incomplete",
                            "usage": {"input_tokens": 5, "output_tokens": 6},
                        }
                    },
                ),
            ),
        )
    )
    events = await collect(provider())
    end = events[-1]
    assert isinstance(end, StreamEnd) and end.finish_reason == "length"


@respx.mock
async def test_response_failed_is_server_error() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            content=sse(
                (
                    "response.failed",
                    {"response": {"error": {"code": "server_error", "message": "oops"}}},
                )
            ),
        )
    )
    with pytest.raises(ProviderServerError):
        await collect(provider())


@respx.mock
async def test_error_event_rate_limit() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            content=(
                "event: error\ndata: "
                + json.dumps({"error": {"code": "rate_limit_exceeded", "message": "slow"}})
                + "\n\n"
            ).encode("utf-8"),
        )
    )
    with pytest.raises(ProviderRateLimited):
        await collect(provider())


@respx.mock
async def test_4xx_rejected() -> None:
    respx.post(URL).mock(return_value=httpx.Response(401, text="bad key"))
    with pytest.raises(ProviderRejectedError):
        await collect(provider())


@respx.mock
async def test_stream_without_terminal_is_protocol_error() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            content=b"event: response.output_text.delta\ndata: {\"delta\": \"half\"}\n\n",
        )
    )
    with pytest.raises(ProviderProtocolError):
        await collect(provider())
