"""OpenAI-compatible chat.completions 流式实现（M1 D1）。

- httpx stream + 手写 SSE 解析（不引 OpenAI SDK，依赖面最小）
- tool_calls 分片按 index 累积，流结束一次性产出完整调用
- usage 取最后一个带 usage 的 chunk（stream_options.include_usage）
- 错误归一化：429 → ProviderRateLimited（带 Retry-After）、5xx → ProviderServerError、
  超时 → ProviderTimeout、断流/缺 [DONE]/畸形 JSON → ProviderProtocolError、
  其它 4xx → ProviderRejectedError

严格性约定：流必须以 [DONE] 或非空 finish_reason 结束，否则视为断流
（容忍个别网关丢 [DONE]，但完全无终态即报错，不能把半截回答当成功）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

from agentd.providers.base import (
    ChatMessage,
    Provider,
    ProviderEvent,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderRejectedError,
    ProviderServerError,
    ProviderTimeout,
    ReasoningDelta,
    StreamEnd,
    TextDelta,
    ToolCallCompleted,
    ToolDefinition,
    Usage,
)

_MAX_ERROR_SNIPPET = 300


class OpenAICompatProvider(Provider):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout_s: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[ProviderEvent, None]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": list(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = [tool.to_openai() for tool in tools]
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "text/event-stream",
        }
        tool_acc: dict[int, dict[str, str]] = {}
        usage: Usage | None = None
        finish_reason: str | None = None
        saw_done = False
        try:
            async with self._client.stream(
                "POST", self._url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    _raise_for_status(resp.status_code, body, resp.headers)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # 事件名行 / 心跳注释 / 空行
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        saw_done = True
                        break
                    try:
                        chunk: Any = json.loads(data)
                    except ValueError as exc:
                        raise ProviderProtocolError(
                            f"malformed SSE JSON: {data[:120]!r}"
                        ) from exc
                    usage = _merge_usage(chunk, usage)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield TextDelta(content)
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        yield ReasoningDelta(reasoning)
                    for tc in delta.get("tool_calls") or []:
                        _accumulate_tool_call(tool_acc, tc)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"model request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderProtocolError(f"model stream failed: {exc}") from exc
        if not saw_done and finish_reason is None:
            raise ProviderProtocolError("stream ended without [DONE] or finish_reason")
        for idx in sorted(tool_acc):
            slot = tool_acc[idx]
            yield ToolCallCompleted(
                id=slot["id"], name=slot["name"], arguments=slot["arguments"]
            )
        yield StreamEnd(finish_reason=finish_reason, usage=usage)


def _accumulate_tool_call(acc: dict[int, dict[str, str]], tc: Any) -> None:
    """按 index 累积 tool_calls 分片；id/name 可能只在首个分片出现。"""
    idx = int(tc.get("index") or 0)
    slot = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
    if tc.get("id"):
        slot["id"] = str(tc["id"])
    function = tc.get("function") or {}
    if function.get("name"):
        slot["name"] += str(function["name"])
    if function.get("arguments"):
        slot["arguments"] += str(function["arguments"])


def _merge_usage(chunk: Any, current: Usage | None) -> Usage | None:
    raw = chunk.get("usage")
    if not raw:
        return current
    return Usage(
        input_tokens=int(raw.get("prompt_tokens") or 0),
        output_tokens=int(raw.get("completion_tokens") or 0),
    )


def _raise_for_status(status: int, body: str, headers: httpx.Headers) -> None:
    snippet = " ".join(body.split())[:_MAX_ERROR_SNIPPET]
    if status == 429:
        retry_after: float | None = None
        raw = headers.get("retry-after")
        if raw:
            try:
                retry_after = max(0.0, float(raw))
            except ValueError:
                retry_after = None
        raise ProviderRateLimited(f"model rate limited: {snippet}", retry_after_s=retry_after)
    if status >= 500:
        raise ProviderServerError(f"model server error {status}: {snippet}")
    raise ProviderRejectedError(f"model request rejected {status}: {snippet}")
