"""OpenAI Responses API 流式实现（v0.2 多 provider）。

与 chat.completions 的差异：input 是条目列表（function_call / function_call_output
一等公民），instructions 承载 system；事件带 event: 名。

- 消息映射：system → instructions（多条拼接）；user → input_text 条目；
  assistant 的 tool_calls → function_call 条目（call_id/name/arguments）；
  tool 角色 → function_call_output 条目（output = 工具结果文本）
- SSE：response.output_text.delta（文本增量）→ response.output_item.added/done
  （function_call 条目，arguments 可经 function_call_arguments.delta 分片累积）
  → response.completed（usage 与终态）。failed 事件归一化为错误
- 严格性约定：必须收到 completed/incomplete 终态，否则视为断流
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


class ResponsesProvider(Provider):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        max_output_tokens: int = 4096,
        timeout_s: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/responses"
        self._max_output_tokens = max_output_tokens
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
        payload = _build_payload(
            messages, tools=tools, model=model or self.model,
            max_output_tokens=self._max_output_tokens,
        )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "text/event-stream",
        }
        usage: Usage | None = None
        status: str | None = None
        saw_terminal = False
        # function_call 条目的 arguments 分片按 item id 累积
        call_acc: dict[str, dict[str, str]] = {}
        try:
            async with self._client.stream(
                "POST", self._url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    _raise_for_status(resp.status_code, body, resp.headers)
                event_name = ""
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event_name = line[len("event:") :].strip()
                        continue
                    if not line.startswith("data:"):
                        continue  # 心跳/空行
                    data = line[len("data:") :].strip()
                    if not data:
                        continue
                    try:
                        chunk: Any = json.loads(data)
                    except ValueError as exc:
                        raise ProviderProtocolError(
                            f"malformed SSE JSON: {data[:120]!r}"
                        ) from exc
                    kind = event_name or str(chunk.get("type") or "")
                    if kind == "response.output_text.delta":
                        if chunk.get("delta"):
                            yield TextDelta(str(chunk["delta"]))
                    elif kind in (
                        "response.reasoning_text.delta",
                        "response.reasoning_summary_text.delta",
                    ):
                        if chunk.get("delta"):
                            yield ReasoningDelta(str(chunk["delta"]))
                    elif kind == "response.function_call_arguments.delta":
                        slot = call_acc.setdefault(
                            str(chunk.get("item_id") or ""), {"id": "", "name": "", "arguments": ""}
                        )
                        slot["arguments"] += str(chunk.get("delta") or "")
                    elif kind == "response.output_item.done":
                        item = chunk.get("item") or {}
                        if item.get("type") == "function_call":
                            call_id = str(item.get("call_id") or item.get("id") or "")
                            # 分片为空时以条目自带 arguments 为准（部分网关一次给全量）
                            slot = call_acc.get(str(item.get("id") or ""), {})
                            args = str(item.get("arguments") or slot.get("arguments") or "{}")
                            yield ToolCallCompleted(
                                id=call_id,
                                name=str(item.get("name") or ""),
                                arguments=args,
                            )
                    elif kind == "response.completed":
                        response = chunk.get("response") or {}
                        raw_usage = response.get("usage") or {}
                        usage = Usage(
                            int(raw_usage.get("input_tokens") or 0),
                            int(raw_usage.get("output_tokens") or 0),
                        )
                        status = str(response.get("status") or "completed")
                        saw_terminal = True
                        break
                    elif kind == "response.incomplete":
                        response = chunk.get("response") or {}
                        raw_usage = response.get("usage") or {}
                        usage = Usage(
                            int(raw_usage.get("input_tokens") or 0),
                            int(raw_usage.get("output_tokens") or 0),
                        )
                        status = "incomplete"
                        saw_terminal = True
                        break
                    elif kind == "response.failed":
                        err = (chunk.get("response") or {}).get("error") or {}
                        raise ProviderServerError(
                            f"response.failed: {err.get('code') or 'unknown'}: "
                            f"{err.get('message') or ''}"
                        )
                    elif kind == "error":
                        err = chunk.get("error") or {}
                        code = str(err.get("code") or "")
                        message = str(err.get("message") or "responses stream error")
                        if code == "rate_limit_exceeded":
                            raise ProviderRateLimited(f"model rate limited: {message}")
                        raise ProviderRejectedError(f"model request rejected ({code}): {message}")
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"model request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderProtocolError(f"model stream failed: {exc}") from exc
        if not saw_terminal:
            raise ProviderProtocolError("stream ended without completed/incomplete")
        yield StreamEnd(
            finish_reason="length" if status == "incomplete" else "stop", usage=usage
        )


def _build_payload(
    messages: Sequence[ChatMessage],
    *,
    tools: Sequence[ToolDefinition] | None,
    model: str,
    max_output_tokens: int,
) -> dict[str, Any]:
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        text = m.get("content") or ""
        if role == "system":
            instructions.append(text)
        elif role == "user":
            items.append({"role": "user", "content": [{"type": "input_text", "text": text}]})
        elif role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(m.get("tool_call_id") or ""),
                    "output": text,
                }
            )
        elif role == "assistant":
            if text:
                items.append(
                    {"role": "assistant", "content": [{"type": "output_text", "text": text}]}
                )
            for call in m.get("tool_calls") or []:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": str(call["id"]),
                        "name": str(call["function"]["name"]),
                        "arguments": str(call["function"]["arguments"]),
                    }
                )

    payload: dict[str, Any] = {
        "model": model,
        "input": items,
        "stream": True,
        "max_output_tokens": max_output_tokens,
    }
    if instructions:
        payload["instructions"] = "\n\n".join(instructions)
    if tools:
        payload["tools"] = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in tools
        ]
    return payload


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
