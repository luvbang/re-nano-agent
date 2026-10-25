"""Anthropic 原生 Messages API 流式实现（v0.2 多 provider）。

- 端点：POST {base_url}/v1/messages，x-api-key + anthropic-version 头（不引 SDK，依赖面最小）
- 消息映射：system 角色 → 顶层 system（多条拼接）；assistant 的 tool_calls →
  tool_use 块（input = JSON.parse(arguments)）；tool 角色 → user 消息里的
  tool_result 块；连续同角色合并（Anthropic 要求 user/assistant 交替）
- SSE：message_start（usage.input）→ content_block_start/delta/stop（text_delta 增量、
  thinking_delta 推理、tool_use 的 input_json_delta 按 index 累积）→
  message_delta（stop_reason + usage.output）→ message_stop（终态）；
  error 事件按错误类型归一化
- 严格性约定与 openai_compat 对齐：必须收到 message_stop，否则视为断流，
  不能把半截回答当成功
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
_DEFAULT_VERSION = "2023-06-01"

_STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "refusal": "stop",
}


class AnthropicProvider(Provider):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        model: str = "claude-sonnet-4-5",
        max_tokens: int = 4096,
        timeout_s: float = 120.0,
        version: str = _DEFAULT_VERSION,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/v1/messages"
        self._max_tokens = max_tokens
        self._version = version
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
            messages, tools=tools, model=model or self.model, max_tokens=self._max_tokens
        )
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self._version,
            "Accept": "text/event-stream",
        }
        usage = Usage(0, 0)
        stop_reason: str | None = None
        saw_stop = False
        # tool_use 块按 content_block index 累积；block 结束即产出完整调用
        tool_acc: dict[int, dict[str, str]] = {}
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
                    if kind == "error":
                        _raise_for_event_error(chunk)
                    if kind == "message_start":
                        usage = usage.plus(
                            Usage(int(_dig(chunk, "message", "usage", "input_tokens") or 0), 0)
                        )
                    elif kind == "content_block_start":
                        block = chunk.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            idx = int(chunk.get("index") or 0)
                            tool_acc[idx] = {
                                "id": str(block.get("id") or ""),
                                "name": str(block.get("name") or ""),
                                "arguments": "",
                            }
                    elif kind == "content_block_delta":
                        delta = chunk.get("delta") or {}
                        dtype = delta.get("type")
                        if dtype == "text_delta" and delta.get("text"):
                            yield TextDelta(str(delta["text"]))
                        elif dtype == "thinking_delta" and delta.get("thinking"):
                            yield ReasoningDelta(str(delta["thinking"]))
                        elif dtype == "input_json_delta" and delta.get("partial_json"):
                            idx = int(chunk.get("index") or 0)
                            slot = tool_acc.setdefault(
                                idx, {"id": "", "name": "", "arguments": ""}
                            )
                            slot["arguments"] += str(delta["partial_json"])
                    elif kind == "content_block_stop":
                        idx = int(chunk.get("index") or 0)
                        finished = tool_acc.get(idx)
                        if finished is not None:
                            del tool_acc[idx]
                            yield ToolCallCompleted(
                                id=finished["id"],
                                name=finished["name"],
                                arguments=finished["arguments"] or "{}",
                            )
                    elif kind == "message_delta":
                        delta = chunk.get("delta") or {}
                        if delta.get("stop_reason"):
                            stop_reason = str(delta["stop_reason"])
                        out = _dig(chunk, "usage", "output_tokens")
                        if out:
                            # Anthropic 的 message_delta.usage.output_tokens 是累计值
                            usage = Usage(usage.input_tokens, int(out))
                    elif kind == "message_stop":
                        saw_stop = True
                        break
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"model request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderProtocolError(f"model stream failed: {exc}") from exc
        if not saw_stop:
            raise ProviderProtocolError("stream ended without message_stop")
        yield StreamEnd(
            finish_reason=_STOP_REASON_MAP.get(stop_reason or "", stop_reason), usage=usage
        )


def _build_payload(
    messages: Sequence[ChatMessage],
    *,
    tools: Sequence[ToolDefinition] | None,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    system_parts: list[str] = []
    mapped: list[dict[str, Any]] = []

    def append(role: str, block: Any) -> None:
        if mapped and mapped[-1]["role"] == role:
            mapped[-1]["content"].append(block)
        else:
            mapped.append({"role": role, "content": [block]})

    for m in messages:
        role = m.get("role")
        text = m.get("content") or ""
        if role == "system":
            system_parts.append(text)
        elif role == "user":
            append("user", {"type": "text", "text": text})
        elif role == "tool":
            append(
                "user",
                {
                    "type": "tool_result",
                    "tool_use_id": str(m.get("tool_call_id") or ""),
                    "content": text,
                },
            )
        elif role == "assistant":
            if text:
                append("assistant", {"type": "text", "text": text})
            for call in m.get("tool_calls") or []:
                try:
                    parsed = json.loads(call["function"]["arguments"])
                except (ValueError, KeyError):
                    parsed = {}
                append(
                    "assistant",
                    {
                        "type": "tool_use",
                        "id": str(call["id"]),
                        "name": str(call["function"]["name"]),
                        "input": parsed if isinstance(parsed, dict) else {},
                    },
                )

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": mapped,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if tools:
        payload["tools"] = [tool.to_anthropic() for tool in tools]
    return payload


def _dig(chunk: Any, *keys: str) -> Any:
    cur: Any = chunk
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _raise_for_event_error(chunk: Any) -> None:
    err = chunk.get("error") or {}
    etype = str(err.get("type") or "")
    message = str(err.get("message") or "anthropic stream error")
    if etype == "rate_limit_error":
        raise ProviderRateLimited(f"model rate limited: {message}")
    if etype in ("api_error", "overloaded_error"):
        raise ProviderServerError(f"model server error ({etype}): {message}")
    raise ProviderRejectedError(f"model request rejected ({etype}): {message}")


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
    if status >= 500 or status == 529:
        raise ProviderServerError(f"model server error {status}: {snippet}")
    raise ProviderRejectedError(f"model request rejected {status}: {snippet}")
