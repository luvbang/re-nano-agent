"""异步客户端核心（同步包装见 sync.py）。

- REST：sessions/runs/usage/models/memories，错误信封 → 类型化异常
- SSE：runs.stream() 产出 StreamEvent（seq/type/data），断流自动带 Last-Event-ID 重连
- 自动重试：retryable 错误指数退避（Retry-After 优先），最多 max_retries；
  POST runs 默认自动生成 Idempotency-Key 保证重试安全
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from agentd_client.errors import (
    AgentdError,
    NetworkError,
    RateLimitError,
    ValidationError,
    from_envelope,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_MAX_RETRIES = 3
RECONNECT_MAX = 3

#: 记忆状态：active 注入上下文；archived 仅留档（软删除）
MemoryStatus = Literal["active", "archived"]
_MEMORY_LIMIT_MIN = 1
_MEMORY_LIMIT_MAX = 200


@dataclass(frozen=True, slots=True)
class StreamEvent:
    seq: int
    type: str
    data: dict[str, Any]


class AsyncClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        api_key: str,
        timeout_s: float = 60.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_retries = max_retries
        self._owns = client is None
        if client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout_s,
            )
        else:
            self._client = client
            self._client.headers.setdefault("Authorization", f"Bearer {api_key}")

    async def aclose(self) -> None:
        if self._owns:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ---------- REST ----------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        _retried: bool = False,
    ) -> Any:
        attempt = 0
        error: AgentdError | None = None
        while True:
            try:
                response = await self._client.request(
                    method, path, json=json_body, headers=headers
                )
            except httpx.HTTPError as exc:
                error = NetworkError(f"网络错误：{exc}")
            else:
                if response.status_code < 400:
                    result: Any = response.json() if response.content else {}
                    return result
                error = self._envelope_error(response)
            assert error is not None
            if not error.retryable or attempt >= self.max_retries or _retried:
                raise error
            delay = getattr(error, "retry_after_s", None)
            if delay is None:
                delay = min(0.5 * (2**attempt), 8.0)
            await asyncio.sleep(delay)
            attempt += 1

    @staticmethod
    def _envelope_error(response: httpx.Response) -> AgentdError:
        try:
            payload = response.json().get("error", {})
        except ValueError:
            payload = {"code": "internal", "message": response.text[:200]}
        error = from_envelope(payload, status_code=response.status_code)
        if isinstance(error, RateLimitError):
            raw = response.headers.get("retry-after")
            if raw:
                with contextlib.suppress(ValueError):
                    error.retry_after_s = max(0.0, float(raw))
        return error

    # ---------- sessions ----------

    async def create_session(
        self, *, title: str | None = None, external_user_id: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if title:
            body["title"] = title
        if external_user_id:
            body["external_user_id"] = external_user_id
        result: dict[str, Any] = await self._request("POST", "/v1/sessions", json_body=body)
        return result

    async def get_session(self, session_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._request("GET", f"/v1/sessions/{session_id}")
        return result

    async def rename_session(self, session_id: str, *, title: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._request(
            "PATCH", f"/v1/sessions/{session_id}", json_body={"title": title}
        )
        return result

    async def delete_session(self, session_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._request("DELETE", f"/v1/sessions/{session_id}")
        return result

    async def list_messages(
        self, session_id: str, *, limit: int = 50, before_seq: int | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if before_seq is not None:
            params["before_seq"] = before_seq
        query = "&".join(f"{k}={v}" for k, v in params.items())
        result: dict[str, Any] = await self._request(
            "GET", f"/v1/sessions/{session_id}/messages?{query}"
        )
        return result

    # ---------- runs ----------

    async def create_run(
        self,
        session_id: str,
        *,
        input: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = idempotency_key or f"sdk-{uuid.uuid4().hex[:16]}"
        result: dict[str, Any] = await self._request(
            "POST",
            f"/v1/sessions/{session_id}/runs",
            json_body={"input": input},
            headers={"Idempotency-Key": key},
        )
        return result

    async def get_run(self, run_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._request("GET", f"/v1/runs/{run_id}")
        return result

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._request("POST", f"/v1/runs/{run_id}/cancel")
        return result

    async def stream(
        self, run_id: str, *, last_event_id: int | None = None
    ) -> AsyncIterator[StreamEvent]:
        """SSE 事件迭代器；断流自动带 Last-Event-ID 重连（≤3 次），不重放已收事件。"""
        last_seq = last_event_id or 0
        reconnects = 0
        while True:
            try:
                async for event in self._raw_stream(run_id, last_seq):
                    if event.seq <= last_seq:
                        continue
                    last_seq = event.seq
                    yield event
                return
            except NetworkError:
                if reconnects >= RECONNECT_MAX:
                    raise
                reconnects += 1
                await asyncio.sleep(0.5 * reconnects)

    async def _raw_stream(self, run_id: str, after_seq: int) -> AsyncIterator[StreamEvent]:
        headers: dict[str, str] = {"Accept": "text/event-stream"}
        if after_seq:
            headers["Last-Event-ID"] = str(after_seq)
        try:
            async with self._client.stream(
                "GET", f"/v1/runs/{run_id}/events", headers=headers
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise self._envelope_error(response)
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                        event = _parse_block(block)
                        if event is not None:
                            yield event
        except httpx.HTTPError as exc:
            raise NetworkError(f"SSE 断流：{exc}") from exc

    # ---------- memories ----------

    async def list_memories(
        self, *, status: MemoryStatus | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """记忆列表（最近创建优先）。

        `status=None` 返回**全部**状态（含已归档）——服务端是先按 limit 取最近的行再按状态过滤，
        因此 `status="archived"` 可能被更近的 active 记忆挤出前 limit 条，拿不全时请调大 limit。
        `limit` 超出 1..200 会直接抛 ValidationError（本地校验，省一次 400 往返）。
        """
        if not _MEMORY_LIMIT_MIN <= limit <= _MEMORY_LIMIT_MAX:
            raise ValidationError(
                f"limit 必须在 {_MEMORY_LIMIT_MIN}..{_MEMORY_LIMIT_MAX} 之间"
                f"（服务端约束），收到 {limit}"
            )
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        query = "&".join(f"{k}={v}" for k, v in params.items())
        raw: Any = await self._request("GET", f"/v1/memories?{query}")
        return list(raw)

    async def create_memory(self, *, content: str) -> dict[str, Any]:
        """写入一条记忆（project 作用域）。

        服务端**同内容去重**：content 前后空白会被 strip，已有 active 同内容行时不新增，
        而是刷新该行 last_seen_at 并原样返回既有行（HTTP 仍是 201，无法从响应区分新建/命中）。
        content 为纯空白时服务端返回 500（已知缺陷），这里提前抛 ValidationError 拦住。
        """
        if not content.strip():
            raise ValidationError("content 不能为空或仅含空白字符")
        result: dict[str, Any] = await self._request(
            "POST", "/v1/memories", json_body={"content": content}
        )
        return result

    async def archive_memory(self, memory_id: str) -> dict[str, Any]:
        """归档记忆（软删除：置 status=archived，不物理删除，Dream 与审计保留痕迹）。

        服务端返回 204 无响应体 → 这里统一返回 `{}`，与其他方法「返回响应 JSON」保持一致。
        归档不存在的 id（或属于其他 project 的 id）抛 NotFoundError；
        已归档的 id 再次归档仍是 204（幂等）。
        """
        result: dict[str, Any] = await self._request("DELETE", f"/v1/memories/{memory_id}")
        return result

    # ---------- misc ----------

    async def usage(self, *, group_by: str = "day", date_from: str | None = None,
                    date_to: str | None = None) -> dict[str, Any]:
        params = [f"group_by={group_by}"]
        if date_from:
            params.append(f"date_from={date_from}")
        if date_to:
            params.append(f"date_to={date_to}")
        result: dict[str, Any] = await self._request("GET", "/v1/usage?" + "&".join(params))
        return result

    async def models(self) -> list[dict[str, Any]]:
        raw: Any = await self._request("GET", "/v1/models")
        return list(raw)


def _parse_block(block: str) -> StreamEvent | None:
    event_name = ""
    seq = 0
    data = ""
    for line in block.splitlines():
        if line.startswith("event: "):
            event_name = line[len("event: ") :].strip()
        elif line.startswith("id: "):
            try:
                seq = int(line[len("id: ") :].strip())
            except ValueError:
                seq = 0
        elif line.startswith("data: "):
            data = line[len("data: ") :]
    if not event_name and not data:
        return None
    try:
        payload = json.loads(data) if data else {}
    except ValueError:
        payload = {"raw": data}
    return StreamEvent(seq=seq, type=event_name or "message", data=payload)


def iter_blocks_sync(text: str) -> Iterator[StreamEvent]:
    """同步解析 SSE 文本（sync.py 复用同一解析器）。"""
    for block in text.split("\n\n"):
        event = _parse_block(block)
        if event is not None:
            yield event
