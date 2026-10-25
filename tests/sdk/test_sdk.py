"""SDK 测试（M4 D1 DoD：SDK 端到端跑通）——对进程内 ASGI app + fake provider。"""

from __future__ import annotations

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
    RateLimitError,
    StreamEvent,
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
