"""SDK 测试（M4 D1 DoD：SDK 端到端跑通）——对进程内 ASGI app + fake provider。"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx
from httpx import ASGITransport
from httpx import AsyncClient as HttpxAsyncClient

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.fake import FakeChatProvider, demo_turn
from agentd_client import (
    AsyncClient,
    AuthenticationError,
    Client,
    NotFoundError,
    RateLimitError,
    StreamEvent,
    ValidationError,
)

ADMIN_KEY = "admin-sdk-test"


@pytest.fixture
async def transport(tmp_path: Path) -> AsyncIterator[ASGITransport]:
    settings = Settings(
        env="test", data_dir=tmp_path, log_level="WARNING", log_json=False,
        admin_api_key=ADMIN_KEY,
    )
    app = create_app(settings, provider=FakeChatProvider(turn_fn=demo_turn))
    async with app.router.lifespan_context(app):
        yield ASGITransport(app=app)


async def issue_key(admin_client: HttpxAsyncClient) -> str:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (
        await admin_client.post("/v1/admin/projects", json={"name": "sdk"}, headers=admin)
    ).json()
    created: dict[str, object] = (
        await admin_client.post(
            "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin
        )
    ).json()
    return str(created["key"])


async def test_async_end_to_end_stream(transport: ASGITransport) -> None:
    async with HttpxAsyncClient(transport=transport, base_url="http://t") as admin_client:
        api_key = await issue_key(admin_client)

    sdk = AsyncClient("http://t", api_key=api_key, client=httpx.AsyncClient(
        transport=transport, base_url="http://t"
    ))
    try:
        session = await sdk.create_session(title="sdk-e2e")
        assert session["title"] == "sdk-e2e"

        created = await sdk.create_run(session["id"], input="你好")
        run_id = created["run_id"]
        deltas = ""
        answer = ""
        final: StreamEvent | None = None
        async for event in sdk.stream(run_id):
            if event.type == "message.delta":
                deltas += event.data["delta"]
            elif event.type == "message.completed":
                answer = event.data["content"]
            elif event.type == "run.completed":
                final = event
        # 契约规定以 message.completed 为准（续传不重放 delta）
        assert "你说的是" in answer
        assert "你说的是" in deltas
        assert final is not None and final.data["usage"]["input_tokens"] > 0

        run = await sdk.get_run(run_id)
        assert run["status"] == "completed"

        messages = await sdk.list_messages(session["id"])
        assert [m["role"] for m in messages["items"]] == ["user", "assistant"]

        usage = await sdk.usage(group_by="model")
        assert usage["items"], "SDK 应能查到用量"
    finally:
        await sdk.aclose()


async def test_async_error_mapping(transport: ASGITransport) -> None:
    sdk = AsyncClient(
        "http://t", api_key=f"agd_missing_{uuid.uuid4().hex}",
        client=httpx.AsyncClient(transport=transport, base_url="http://t"),
    )
    try:
        with pytest.raises(AuthenticationError):
            await sdk.create_session()
    finally:
        await sdk.aclose()


def test_sync_client_streams(tmp_path: Path) -> None:
    """同步客户端对真实 HTTP 服务（uvicorn 线程）：后台循环 + 队列交接的 SSE 迭代。"""
    import threading
    import time as time_mod

    import uvicorn

    from agentd.config import Settings as AppSettings

    settings = AppSettings(
        env="test", data_dir=tmp_path, log_level="WARNING", log_json=False,
        admin_api_key=ADMIN_KEY,
    )
    app = create_app(settings, provider=FakeChatProvider(turn_fn=demo_turn))
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time_mod.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        import asyncio as asyncio_mod

        async def _key() -> str:
            async with HttpxAsyncClient(base_url=f"http://127.0.0.1:{port}") as admin_client:
                return await issue_key(admin_client)

        api_key = asyncio_mod.run(_key())
        with Client(f"http://127.0.0.1:{port}", api_key=api_key) as client:
            session = client.create_session(title="sync")
            created = client.create_run(session["id"], input="同步你好")
            answer = ""
            for event in client.stream(created["run_id"]):
                if event.type == "message.completed":
                    answer = event.data["content"]  # run 可能先完成，回放无 delta
            assert "你说的是" in answer
            run = client.get_run(created["run_id"])
            assert run["status"] == "completed"
            models = client.models()
            assert models[0]["id"]
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@respx.mock
async def test_retry_on_rate_limit_then_success() -> None:
    """可重试错误自动退避重试（Retry-After 优先）。"""
    route = respx.get("http://sdk.test/v1/models").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={
                "error": {"code": "rate_limited", "message": "slow", "retryable": True}
            }),
            httpx.Response(200, json=[{"id": "m"}]),
        ]
    )
    sdk = AsyncClient("http://sdk.test", api_key="k", client=httpx.AsyncClient(
        base_url="http://sdk.test"
    ))
    try:
        result = await sdk.models()
        assert result == [{"id": "m"}]
        assert route.call_count == 2  # 一次失败 + 一次重试成功
    finally:
        await sdk.aclose()


@respx.mock
async def test_no_retry_on_auth_error() -> None:
    route = respx.get("http://sdk.test/v1/models").mock(
        return_value=httpx.Response(401, json={
            "error": {"code": "unauthorized", "message": "bad key", "retryable": False}
        })
    )
    sdk = AsyncClient("http://sdk.test", api_key="k", client=httpx.AsyncClient(
        base_url="http://sdk.test"
    ))
    try:
        with pytest.raises(AuthenticationError):
            await sdk.models()
        assert route.call_count == 1
    finally:
        await sdk.aclose()


@respx.mock
async def test_rate_limit_error_carries_retry_after() -> None:
    respx.get("http://sdk.test/v1/models").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "7"}, json={
            "error": {"code": "rate_limited", "message": "slow", "retryable": True}
        })
    )
    sdk = AsyncClient(
        "http://sdk.test", api_key="k", max_retries=0,
        client=httpx.AsyncClient(base_url="http://sdk.test"),
    )
    try:
        with pytest.raises(RateLimitError) as excinfo:
            await sdk.models()
        assert excinfo.value.retry_after_s == 7.0
    finally:
        await sdk.aclose()


# ---------- 记忆（/v1/memories） ----------


def _memory_row(
    memory_id: str = "mem_1",
    *,
    content: str = "用户偏好深色主题",
    status: str = "active",
    last_seen_at: str = "2026-01-01 00:00:00",
) -> dict[str, object]:
    return {
        "id": memory_id,
        "content": content,
        "status": status,
        "score": 1.0,
        "created_at": "2026-01-01 00:00:00",
        "last_seen_at": last_seen_at,
    }


async def test_async_memory_roundtrip(transport: ASGITransport) -> None:
    """记忆三方法对真实 app：写 → 去重 → 列表过滤 → 归档 → 404。"""
    async with HttpxAsyncClient(transport=transport, base_url="http://t") as admin_client:
        api_key = await issue_key(admin_client)

    sdk = AsyncClient("http://t", api_key=api_key, client=httpx.AsyncClient(
        transport=transport, base_url="http://t"
    ))
    try:
        created = await sdk.create_memory(content="用户偏好深色主题")
        assert created["status"] == "active" and created["content"] == "用户偏好深色主题"

        # 同内容（前后空白被 strip）→ 不新增行，返回同一 id
        again = await sdk.create_memory(content="  用户偏好深色主题  ")
        assert again["id"] == created["id"]

        active = await sdk.list_memories(status="active")
        assert [m["id"] for m in active] == [created["id"]]

        # 204 无响应体 → 统一返回 {}
        assert await sdk.archive_memory(created["id"]) == {}
        assert await sdk.list_memories(status="active") == []
        archived = await sdk.list_memories(status="archived")
        assert [m["id"] for m in archived] == [created["id"]]
        # 归档幂等
        assert await sdk.archive_memory(created["id"]) == {}

        with pytest.raises(NotFoundError):
            await sdk.archive_memory("mem_does_not_exist")
    finally:
        await sdk.aclose()


@respx.mock
async def test_list_memories_query_shape() -> None:
    """status 缺省时不带该查询参数（服务端默认返回全部状态）。"""
    route = respx.get("http://sdk.test/v1/memories").mock(
        return_value=httpx.Response(200, json=[_memory_row()])
    )
    sdk = AsyncClient("http://sdk.test", api_key="k", client=httpx.AsyncClient(
        base_url="http://sdk.test"
    ))
    try:
        rows = await sdk.list_memories()
        assert rows[0]["id"] == "mem_1"
        url = route.calls.last.request.url
        assert url.params["limit"] == "100"
        assert "status" not in url.params

        await sdk.list_memories(status="archived", limit=5)
        url = route.calls.last.request.url
        assert url.params["status"] == "archived" and url.params["limit"] == "5"
    finally:
        await sdk.aclose()


@respx.mock
async def test_create_memory_posts_content() -> None:
    route = respx.post("http://sdk.test/v1/memories").mock(
        return_value=httpx.Response(201, json=_memory_row())
    )
    sdk = AsyncClient("http://sdk.test", api_key="k", client=httpx.AsyncClient(
        base_url="http://sdk.test"
    ))
    try:
        row = await sdk.create_memory(content="项目使用 SQLite")
        assert row["id"] == "mem_1"
        payload = json.loads(route.calls.last.request.content)
        assert payload == {"content": "项目使用 SQLite"}
    finally:
        await sdk.aclose()


@respx.mock
async def test_dedupe_returns_existing_row() -> None:
    """服务端同日同内容去重：仍回 201，但内容是既有行（last_seen_at 被 bump）。"""
    route = respx.post("http://sdk.test/v1/memories").mock(
        side_effect=[
            httpx.Response(201, json=_memory_row("mem_dup", last_seen_at="2026-01-01 00:00:00")),
            httpx.Response(201, json=_memory_row("mem_dup", last_seen_at="2026-01-02 00:00:00")),
        ]
    )
    sdk = AsyncClient("http://sdk.test", api_key="k", client=httpx.AsyncClient(
        base_url="http://sdk.test"
    ))
    try:
        first = await sdk.create_memory(content="重复内容")
        second = await sdk.create_memory(content="重复内容")
        assert first["id"] == second["id"]
        assert second["last_seen_at"] > first["last_seen_at"]
        assert route.call_count == 2
    finally:
        await sdk.aclose()


@respx.mock
async def test_archive_memory_404_and_no_retry() -> None:
    """不存在 / 跨 project 的记忆 → NotFoundError，且不可重试（只请求一次）。"""
    route = respx.delete("http://sdk.test/v1/memories/mem_x").mock(
        return_value=httpx.Response(404, json={
            "error": {"code": "not_found", "message": "memory 不存在", "retryable": False}
        })
    )
    sdk = AsyncClient("http://sdk.test", api_key="k", client=httpx.AsyncClient(
        base_url="http://sdk.test"
    ))
    try:
        with pytest.raises(NotFoundError):
            await sdk.archive_memory("mem_x")
        assert route.call_count == 1
    finally:
        await sdk.aclose()


@respx.mock
async def test_memory_argument_validation() -> None:
    """本地参数校验：越界 limit / 空白 content 不发请求，直接 ValidationError。"""
    respx.route().mock(return_value=httpx.Response(500))
    sdk = AsyncClient(
        "http://sdk.test", api_key="k",
        client=httpx.AsyncClient(base_url="http://sdk.test"),
    )
    try:
        for bad_limit in (0, -1, 201):
            with pytest.raises(ValidationError):
                await sdk.list_memories(limit=bad_limit)
        for blank in ("", "   ", "\n\t"):
            with pytest.raises(ValidationError):
                await sdk.create_memory(content=blank)
        assert respx.calls.call_count == 0, "参数校验失败不应产生任何网络请求"
    finally:
        await sdk.aclose()


async def test_async_client_context_manager() -> None:
    """`async with AsyncClient(...)` 必须可用（examples/sdk_quickstart.py 就这么写）。"""
    async with AsyncClient("http://sdk.test", api_key="k") as sdk:
        assert isinstance(sdk, AsyncClient)


@respx.mock
def test_sync_client_memories() -> None:
    """同步封装与异步签名一致：三个方法都能直接调用。"""
    respx.get("http://sdk.test/v1/memories").mock(
        return_value=httpx.Response(200, json=[_memory_row()])
    )
    respx.post("http://sdk.test/v1/memories").mock(
        return_value=httpx.Response(201, json=_memory_row("mem_new"))
    )
    respx.delete("http://sdk.test/v1/memories/mem_new").mock(
        return_value=httpx.Response(204)
    )
    with Client("http://sdk.test", api_key="k") as client:
        assert client.create_memory(content="同步记忆")["id"] == "mem_new"
        assert [m["id"] for m in client.list_memories(status="active")] == ["mem_1"]
        assert client.archive_memory("mem_new") == {}
        with pytest.raises(ValidationError):
            client.list_memories(limit=0)
