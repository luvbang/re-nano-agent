"""OpenAICompatProvider 的 respx fixture 测试（M1 D1 DoD）。

覆盖：纯文本流、工具调用流（分片累积）、usage、429、5xx、4xx、超时、断流（缺 [DONE]）、畸形 JSON。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from agentd.providers.base import (
    ChatMessage,
    ProviderError,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderRejectedError,
    ProviderServerError,
    ProviderTimeout,
    StreamEnd,
    TextDelta,
    ToolCallCompleted,
    Usage,
)
from agentd.providers.openai_compat import OpenAICompatProvider

URL = "https://api.test/v1/chat/completions"


def sse(*chunks: Any, done: bool = True) -> bytes:
    lines = [f"data: {json.dumps(c, ensure_ascii=False)}" for c in chunks]
    if done:
        lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode("utf-8")


def chunk_delta(content: str | None = None, **delta: Any) -> dict[str, Any]:
    return {"id": "cmpl_1", "choices": [{"index": 0, "delta": {"content": content, **delta}}]}


def provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(
        api_key="sk-test", base_url="https://api.test/v1", model="test-model"
    )


async def collect(p: OpenAICompatProvider) -> list[Any]:
    return [event async for event in p.chat([ChatMessage(role="user", content="hi")])]


@respx.mock
async def test_text_stream_and_usage() -> None:
    body = sse(
        chunk_delta("你"),
        chunk_delta("好"),
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 7}},
    )
    respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    events = await collect(provider())

    assert events[0] == TextDelta("你")
    assert events[1] == TextDelta("好")
    end = events[2]
    assert isinstance(end, StreamEnd)
    assert end.finish_reason == "stop"
    assert end.usage == Usage(input_tokens=10, output_tokens=7)


@respx.mock
async def test_reasoning_delta_streamed() -> None:
    body = sse(
        chunk_delta(None, reasoning_content="思考中"),
        chunk_delta("答案"),
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    )
    respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    events = await collect(provider())

    assert events[0].__class__.__name__ == "ReasoningDelta"
    assert events[1] == TextDelta("答案")


@respx.mock
async def test_tool_call_stream_accumulates_fragments() -> None:
    body = sse(
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "echo", "arguments": ""},
                            }
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": '{"te'}}
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": 'xt":"hi"}'}}
                        ]
                    },
                }
            ]
        },
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    )
    respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    events = await collect(provider())

    call = events[0]
    assert call == ToolCallCompleted(id="call_1", name="echo", arguments='{"text":"hi"}')
    end = events[1]
    assert isinstance(end, StreamEnd)
    assert end.finish_reason == "tool_calls"


@respx.mock
async def test_tools_sent_in_request_payload() -> None:
    from agentd.providers.base import ToolDefinition

    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            content=sse({"choices": [{"index": 0, "delta": {"content": "ok"}}]},
                        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
        )
    )
    p = provider()
    definition = ToolDefinition(
        name="echo",
        description="回显",
        parameters={"type": "object", "properties": {}},
    )
    _ = [
        event
        async for event in p.chat([ChatMessage(role="user", content="hi")], tools=[definition])
    ]

    request = json.loads(route.calls.last.request.content)
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}
    assert request["tools"][0]["function"]["name"] == "echo"


@respx.mock
async def test_429_maps_to_rate_limited_with_retry_after() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "2"}, content=b"slow down")
    )
    with pytest.raises(ProviderRateLimited) as excinfo:
        await collect(provider())
    assert excinfo.value.retryable is True
    assert excinfo.value.retry_after_s == 2.0


@respx.mock
async def test_500_maps_to_server_error() -> None:
    respx.post(URL).mock(return_value=httpx.Response(500, content=b"boom"))
    with pytest.raises(ProviderServerError):
        await collect(provider())


@respx.mock
async def test_401_maps_to_rejected_not_retryable() -> None:
    respx.post(URL).mock(return_value=httpx.Response(401, content=b"bad key"))
    with pytest.raises(ProviderRejectedError) as excinfo:
        await collect(provider())
    assert excinfo.value.retryable is False


@respx.mock
async def test_timeout_maps_to_provider_timeout() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectTimeout("connect timeout"))
    with pytest.raises(ProviderTimeout):
        await collect(provider())


@respx.mock
async def test_broken_stream_without_done_raises() -> None:
    # 两个 chunk 后连接直接 EOF（无 [DONE]、无 finish_reason）→ 断流
    body = sse(chunk_delta("半"), chunk_delta("截"), done=False)
    respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    with pytest.raises(ProviderProtocolError):
        await collect(provider())


@respx.mock
async def test_missing_done_but_finish_reason_is_tolerated() -> None:
    body = sse(
        chunk_delta("ok"),
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        done=False,
    )
    respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    events = await collect(provider())
    assert events[-1].finish_reason == "stop"


@respx.mock
async def test_malformed_json_chunk_raises_protocol_error() -> None:
    body = b"data: {not json}\n\ndata: [DONE]\n\n"
    respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    with pytest.raises(ProviderProtocolError):
        await collect(provider())


@respx.mock
async def test_error_body_snippet_is_bounded() -> None:
    respx.post(URL).mock(return_value=httpx.Response(500, content=b"x" * 10_000))
    with pytest.raises(ProviderError) as excinfo:
        await collect(provider())
    assert len(str(excinfo.value)) < 400
