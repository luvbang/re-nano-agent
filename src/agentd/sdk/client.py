"""agentd Python SDK（M4）。目标形态见 docs/api-contract.md §5。

用法（契约冻结的公开形态）::

    from agentd import Client

    client = Client(base_url="https://agent.example.com", api_key="agd_...")

    session = client.sessions.create(external_user_id="u_123")
    with client.runs.stream(session.id, input="帮我总结这个仓库的结构") as stream:
        for event in stream:
            if event.type == "message.delta":
                print(event.delta, end="")
            elif event.type == "tool.started":
                print(f"\\n[tool] {event.name}")
    print("usage:", stream.result.usage)

同步 + 异步双 API；异常类型对应错误码（``sdk/errors.py``）；
自动重试仅对 retryable；类型注解完整。
"""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal

import httpx

from agentd.sdk._core import build_params, request_with_retry
from agentd.sdk.errors import AgentdError
from agentd.sdk.streaming import (
    RunCompleted,
    RunFailed,
    StreamEvent,
    parse_event,
)


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    external_user_id: str | None
    title: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    seq: int
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class Run:
    id: str
    session_id: str
    status: str
    model: str | None
    input_tokens: int
    output_tokens: int
    error: dict[str, Any] | None
    created_at: str
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class UsageItem:
    group: str
    runs: int
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class Usage:
    from_: str
    to: str
    group_by: str
    items: list[UsageItem]


@dataclass(frozen=True, slots=True)
class ApiKey:
    id: str
    key_prefix: str
    name: str | None
    scopes: str
    rate_limit_per_min: int
    revoked_at: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class CreatedKey:
    key: ApiKey
    secret: str


def _session(body: dict[str, Any]) -> Session:
    return Session(
        id=str(body["id"]),
        external_user_id=body.get("external_user_id"),
        title=body.get("title"),
        metadata=body.get("metadata") or {},
        created_at=str(body["created_at"]),
        updated_at=str(body["updated_at"]),
    )


def _message(body: dict[str, Any]) -> Message:
    return Message(
        id=str(body["id"]),
        seq=int(body["seq"]),
        role=str(body["role"]),
        content=body.get("content"),
        tool_calls=body.get("tool_calls"),
        tool_call_id=body.get("tool_call_id"),
        created_at=str(body["created_at"]),
    )


def _run(body: dict[str, Any]) -> Run:
    return Run(
        id=str(body["id"]),
        session_id=str(body["session_id"]),
        status=str(body["status"]),
        model=body.get("model"),
        input_tokens=int(body.get("input_tokens") or 0),
        output_tokens=int(body.get("output_tokens") or 0),
        error=body.get("error"),
        created_at=str(body["created_at"]),
        finished_at=body.get("finished_at"),
    )


def _api_key(body: dict[str, Any]) -> ApiKey:
    return ApiKey(
        id=str(body["id"]),
        key_prefix=str(body["key_prefix"]),
        name=body.get("name"),
        scopes=str(body["scopes"]),
        rate_limit_per_min=int(body["rate_limit_per_min"]),
        revoked_at=body.get("revoked_at"),
        created_at=str(body["created_at"]),
    )


def _usage(body: dict[str, Any]) -> Usage:
    return Usage(
        from_=str(body.get("from", "")),
        to=str(body.get("to", "")),
        group_by=str(body.get("group_by", "")),
        items=[
            UsageItem(
                group=str(i["group"]),
                runs=int(i["runs"]),
                input_tokens=int(i["input_tokens"]),
                output_tokens=int(i["output_tokens"]),
            )
            for i in body.get("items", [])
        ],
    )


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        from agentd.sdk._core import _error_from_response

        raise _error_from_response(resp)


class _RunStream:
    """同步流式 run 句柄：``with`` 打开、``for`` 迭代、结束后读 ``result``。"""

    def __init__(self, http: httpx.Client, url: str, api_key: str) -> None:
        self._http = http
        self._url = url
        self._api_key = api_key
        self._cm: Any = None
        self._response: httpx.Response | None = None
        self.result: Run | None = None

    def __enter__(self) -> _RunStream:
        # httpx.stream() 的 context 保持打开直到 __exit__，iter_bytes() 才有数据
        self._cm = self._http.stream(
            "GET", self._url, headers={"Authorization": f"Bearer {self._api_key}"}
        )
        resp = self._cm.__enter__()
        if resp.status_code >= 400:
            content = resp.read()
            status = resp.status_code
            self._cm.__exit__(None, None, None)
            self._cm = None
            from agentd.sdk._core import _error_from_body_bytes

            raise _error_from_body_bytes(status, content)
        self._response = resp
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        if self._cm is not None:
            self._cm.__exit__(exc_type, exc, tb)
            self._cm = None
            self._response = None
        return False

    def __iter__(self) -> Iterator[StreamEvent]:
        if self._response is None:
            raise AgentdError("stream 未打开：请用 with 语句")
        buffer = b""
        pending_event = ""
        pending_data: list[str] = []
        for chunk in self._response.iter_bytes():
            buffer += chunk
            while (idx := buffer.find(b"\n")) >= 0:
                line = buffer[:idx].decode("utf-8", errors="replace").rstrip("\r")
                buffer = buffer[idx + 1 :]
                if not line:
                    if pending_data:
                        event = parse_event(pending_event, "\n".join(pending_data))
                        pending_event, pending_data = "", []
                        if event is not None:
                            yield event
                            if isinstance(event, (RunCompleted, RunFailed)):
                                self._set_result(event)
                                return
                    continue
                if line.startswith(":"):
                    continue
                fname, _, value = line.partition(":")
                value = value.lstrip(" ")
                if fname == "event":
                    pending_event = value
                elif fname == "data":
                    pending_data.append(value)

    def _set_result(self, terminal: RunCompleted | RunFailed) -> None:
        usage = terminal.usage if isinstance(terminal, RunCompleted) else {}
        self.result = Run(
            id="",
            session_id="",
            status="completed" if isinstance(terminal, RunCompleted) else "failed",
            model=None,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            error=terminal.error if isinstance(terminal, RunFailed) else None,
            created_at="",
            finished_at=None,
        )


class _AsyncRunStream:
    """异步流式 run 句柄：``async with`` 打开、``async for`` 迭代。"""

    def __init__(self, ahttp: httpx.AsyncClient, url: str, api_key: str) -> None:
        self._ahttp = ahttp
        self._url = url
        self._api_key = api_key
        self._cm: Any = None
        self._response: httpx.Response | None = None
        self.result: Run | None = None

    async def __aenter__(self) -> _AsyncRunStream:
        self._cm = self._ahttp.stream(
            "GET", self._url, headers={"Authorization": f"Bearer {self._api_key}"}
        )
        resp = await self._cm.__aenter__()
        if resp.status_code >= 400:
            content = await resp.aread()
            status = resp.status_code
            await self._cm.__aexit__(None, None, None)
            self._cm = None
            from agentd.sdk._core import _error_from_body_bytes

            raise _error_from_body_bytes(status, content)
        self._response = resp
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        if self._cm is not None:
            await self._cm.__aexit__(exc_type, exc, tb)
            self._cm = None
            self._response = None
        return False

    def __aiter__(self) -> AsyncIterator[StreamEvent]:
        return self._aiter()

    async def _aiter(self) -> AsyncIterator[StreamEvent]:
        if self._response is None:
            raise AgentdError("stream 未打开：请用 async with 语句")
        buffer = b""
        pending_event = ""
        pending_data: list[str] = []
        async for chunk in self._response.aiter_bytes():
            buffer += chunk
            while (idx := buffer.find(b"\n")) >= 0:
                line = buffer[:idx].decode("utf-8", errors="replace").rstrip("\r")
                buffer = buffer[idx + 1 :]
                if not line:
                    if pending_data:
                        event = parse_event(pending_event, "\n".join(pending_data))
                        pending_event, pending_data = "", []
                        if event is not None:
                            yield event
                            if isinstance(event, (RunCompleted, RunFailed)):
                                self._set_result(event)
                                return
                    continue
                if line.startswith(":"):
                    continue
                fname, _, value = line.partition(":")
                value = value.lstrip(" ")
                if fname == "event":
                    pending_event = value
                elif fname == "data":
                    pending_data.append(value)

    def _set_result(self, terminal: RunCompleted | RunFailed) -> None:
        usage = terminal.usage if isinstance(terminal, RunCompleted) else {}
        self.result = Run(
            id="",
            session_id="",
            status="completed" if isinstance(terminal, RunCompleted) else "failed",
            model=None,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            error=terminal.error if isinstance(terminal, RunFailed) else None,
            created_at="",
            finished_at=None,
        )


class _SessionsApi:
    def __init__(self, http: httpx.Client, params: dict[str, Any]) -> None:
        self._http = http
        self._p = params

    def create(
        self,
        *,
        external_user_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        resp = request_with_retry(
            self._http, "POST", "/v1/sessions", api_key=self._p["api_key"],
            json_body={
                "external_user_id": external_user_id,
                "title": title,
                "metadata": metadata or {},
            },
        )
        return _session(resp.json())

    def get(self, session_id: str) -> Session:
        resp = request_with_retry(
            self._http, "GET", f"/v1/sessions/{session_id}", api_key=self._p["api_key"]
        )
        return _session(resp.json())

    def list(self, *, limit: int = 50) -> builtins.list[Session]:
        resp = request_with_retry(
            self._http, "GET", "/v1/sessions", api_key=self._p["api_key"],
            params={"limit": str(limit)},
        )
        return [_session(b) for b in resp.json()]

    def messages(
        self, session_id: str, *, limit: int = 100, before: int | None = None
    ) -> builtins.list[Message]:
        params = {"limit": str(limit)}
        if before is not None:
            params["before"] = str(before)
        resp = request_with_retry(
            self._http, "GET", f"/v1/sessions/{session_id}/messages",
            api_key=self._p["api_key"], params=params,
        )
        return [_message(b) for b in resp.json()]


class _RunsApi:
    def __init__(self, http: httpx.Client, params: dict[str, Any]) -> None:
        self._http = http
        self._p = params

    def create(
        self, session_id: str, *, input: str, idempotency_key: str | None = None
    ) -> str:
        resp = request_with_retry(
            self._http, "POST", f"/v1/sessions/{session_id}/runs",
            api_key=self._p["api_key"], json_body={"input": input},
            idempotency_key=idempotency_key,
        )
        return str(resp.json()["run_id"])

    def get(self, run_id: str) -> Run:
        resp = request_with_retry(
            self._http, "GET", f"/v1/runs/{run_id}", api_key=self._p["api_key"]
        )
        return _run(resp.json())

    def cancel(self, run_id: str) -> Run:
        resp = request_with_retry(
            self._http, "POST", f"/v1/runs/{run_id}/cancel", api_key=self._p["api_key"]
        )
        return _run(resp.json())

    def stream(
        self, session_id: str, *, input: str, idempotency_key: str | None = None
    ) -> _RunStream:
        run_id = self.create(session_id, input=input, idempotency_key=idempotency_key)
        return _RunStream(self._http, f"/v1/runs/{run_id}/events", self._p["api_key"])


class _KeysApi:
    def __init__(self, http: httpx.Client, params: dict[str, Any]) -> None:
        self._http = http
        self._p = params

    def create(self, *, name: str | None = None, rate_limit_per_min: int = 60) -> CreatedKey:
        resp = request_with_retry(
            self._http, "POST", "/v1/admin/keys", api_key=self._p["api_key"],
            json_body={"name": name, "rate_limit_per_min": rate_limit_per_min},
        )
        body = resp.json()
        return CreatedKey(key=_api_key(body["key"]), secret=str(body["secret"]))

    def list(self) -> builtins.list[ApiKey]:
        resp = request_with_retry(
            self._http, "GET", "/v1/admin/keys", api_key=self._p["api_key"]
        )
        return [_api_key(b) for b in resp.json()]

    def revoke(self, key_id: str) -> None:
        request_with_retry(
            self._http, "DELETE", f"/v1/admin/keys/{key_id}", api_key=self._p["api_key"]
        )


class _UsageApi:
    def __init__(self, http: httpx.Client, params: dict[str, Any]) -> None:
        self._http = http
        self._p = params

    def get(
        self, *, from_: str, to: str, group_by: Literal["day", "model"] = "day"
    ) -> Usage:
        resp = request_with_retry(
            self._http, "GET", "/v1/usage", api_key=self._p["api_key"],
            params={"from": from_, "to": to, "group_by": group_by},
        )
        return _usage(resp.json())


class Client:
    """agentd 客户端（同步）。上下文管理器用法::

        with Client(base_url=..., api_key=...) as client:
            session = client.sessions.create(title="demo")
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000",
        api_key: str = "",
        timeout_s: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.max_retries = max_retries
        self._params = build_params(base_url, api_key, timeout_s)
        self._http = httpx.Client(timeout=timeout_s, base_url=base_url.rstrip("/"))
        self.sessions = _SessionsApi(self._http, self._params)
        self.runs = _RunsApi(self._http, self._params)
        self.keys = _KeysApi(self._http, self._params)
        self.usage = _UsageApi(self._http, self._params)

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None  # type: ignore[assignment]

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> Literal[False]:
        self.close()
        return False


class AsyncClient:
    """agentd 客户端（异步）::

        async with AsyncClient(base_url=..., api_key=...) as client:
            session = await client.sessions.create(title="demo")
            async with await client.runs.stream(session.id, input="...") as stream:
                async for event in stream:
                    ...
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000",
        api_key: str = "",
        timeout_s: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.max_retries = max_retries
        self._params = build_params(base_url, api_key, timeout_s)
        self._ahttp = httpx.AsyncClient(timeout=timeout_s, base_url=base_url.rstrip("/"))
        self.sessions = _AsyncSessionsApi(self._ahttp, self._params)
        self.runs = _AsyncRunsApi(self._ahttp, self._params)

    async def close(self) -> None:
        await self._ahttp.aclose()

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *_: object) -> Literal[False]:
        await self.close()
        return False


class _AsyncSessionsApi:
    def __init__(self, ahttp: httpx.AsyncClient, params: dict[str, Any]) -> None:
        self._ahttp = ahttp
        self._p = params

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._p['api_key']}"}
        resp = await self._ahttp.request(method, path, headers=headers, **kwargs)
        _raise_for(resp)
        return resp.json()  # type: ignore[no-any-return]

    async def _request_list(self, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self._p['api_key']}"}
        resp = await self._ahttp.request("GET", path, headers=headers, **kwargs)
        _raise_for(resp)
        return resp.json()  # type: ignore[no-any-return]

    async def create(
        self,
        *,
        external_user_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        body = await self._request(
            "POST", "/v1/sessions",
            json={
                "external_user_id": external_user_id,
                "title": title,
                "metadata": metadata or {},
            },
        )
        return _session(body)

    async def get(self, session_id: str) -> Session:
        return _session(await self._request("GET", f"/v1/sessions/{session_id}"))

    async def messages(
        self, session_id: str, *, limit: int = 100
    ) -> builtins.list[Message]:
        body = await self._request_list(
            f"/v1/sessions/{session_id}/messages", params={"limit": str(limit)}
        )
        return [_message(b) for b in body]


class _AsyncRunsApi:
    def __init__(self, ahttp: httpx.AsyncClient, params: dict[str, Any]) -> None:
        self._ahttp = ahttp
        self._p = params

    async def _post(self, path: str, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._p['api_key']}"}
        resp = await self._ahttp.post(path, json=json_body, headers=headers)
        _raise_for(resp)
        return resp.json()  # type: ignore[no-any-return]

    async def create(
        self, session_id: str, *, input: str, idempotency_key: str | None = None
    ) -> str:
        headers = (
            {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        )
        resp = await self._ahttp.post(
            f"/v1/sessions/{session_id}/runs",
            json={"input": input},
            headers={"Authorization": f"Bearer {self._p['api_key']}"} | headers,
        )
        _raise_for(resp)
        return str(resp.json()["run_id"])

    async def cancel(self, run_id: str) -> Run:
        body = await self._post(f"/v1/runs/{run_id}/cancel")
        return _run(body)

    async def stream_async(
        self, session_id: str, *, input: str, idempotency_key: str | None = None
    ) -> _AsyncRunStream:
        run_id = await self.create(
            session_id, input=input, idempotency_key=idempotency_key
        )
        return _AsyncRunStream(self._ahttp, f"/v1/runs/{run_id}/events", self._p["api_key"])
