"""SDK 传输核心（M4）：httpx 请求封装、错误映射、retryable 自动重试、SSE 流。

同步与异步共用 ``_request_once`` / ``_stream_once`` 的参数构造与响应处理，
避免两套实现漂移。自动重试：仅 retryable（429/502/504/网络错误）且对
``Idempotency-Key`` 友好的 POST；指数退避 + Retry-After 优先。
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx

from agentd.sdk.errors import AgentdError, ConnectionError, RateLimitError, error_from_body
from agentd.sdk.streaming import StreamEvent, iter_sse_lines, parse_event

_RETRYABLE_STATUS = {429, 502, 504}


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _error_from_response(resp: httpx.Response) -> AgentdError:
    try:
        body: Any = resp.json()
    except ValueError:
        body = {}
    err = error_from_body(resp.status_code, body if isinstance(body, dict) else {})
    if resp.status_code == 429 and isinstance(err, RateLimitError):
        retry_after = resp.headers.get("Retry-After")
        if retry_after is not None and retry_after.isdigit():
            err.retry_after_s = float(retry_after)
    return err


def _error_from_body_bytes(status: int, content: bytes) -> AgentdError:
    """流式路径的错误构造：body 已读出、无响应头上下文。"""
    import json as _json

    try:
        body: Any = _json.loads(content)
    except ValueError:
        body = {}
    return error_from_body(status, body if isinstance(body, dict) else {})


def _should_retry(err: AgentdError, attempt: int, max_retries: int) -> float | None:
    """返回建议等待秒数；None 表示不重试。"""
    if attempt >= max_retries:
        return None
    backoff = float(0.5 * 2**attempt)
    if isinstance(err, RateLimitError):
        return float(err.retry_after_s) if err.retry_after_s else backoff
    status = int(err.status)
    if (status in _RETRYABLE_STATUS or status == 0) and err.retryable:
        return backoff
    return None


def build_params(base_url: str, api_key: str, timeout_s: float) -> dict[str, Any]:
    return {"base_url": base_url.rstrip("/"), "api_key": api_key, "timeout_s": timeout_s}


def _request_once(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    api_key: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> httpx.Response:
    headers = _headers(api_key)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return client.request(
        method, path, json=json_body, params=params, headers=headers
    )


def request_with_retry(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    api_key: str,
    max_retries: int = 2,
    sleep: Any = time.sleep,
    **kwargs: Any,
) -> httpx.Response:
    attempt = 0
    while True:
        try:
            resp = _request_once(client, method, path, api_key=api_key, **kwargs)
        except httpx.HTTPError as exc:
            err: AgentdError = ConnectionError(f"请求失败：{exc}")
            wait = _should_retry(err, attempt, max_retries)
            if wait is None:
                raise err from exc
            attempt += 1
            sleep(wait)
            continue
        if resp.status_code < 400:
            return resp
        err = _error_from_response(resp)
        wait = _should_retry(err, attempt, max_retries)
        if wait is None:
            raise err
        attempt += 1
        sleep(wait)


def sse_events_sync(chunks: Iterator[bytes]) -> Iterator[StreamEvent]:
    for event_name, data in iter_sse_lines(chunks):
        event = parse_event(event_name, data)
        if event is not None:
            yield event
