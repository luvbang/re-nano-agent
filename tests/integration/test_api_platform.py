"""平台端点与限流测试（M3 D3 DoD：429 带 Retry-After；usage/models/stats）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.fake import FakeChatProvider, demo_turn

ADMIN_KEY = "admin-platform-test"


def make_settings(tmp_path: Path, **kwargs: Any) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path,
        log_level="WARNING",
        log_json=False,
        admin_api_key=ADMIN_KEY,
        **kwargs,
    )


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = create_app(make_settings(tmp_path), provider=FakeChatProvider(turn_fn=demo_turn))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def bootstrap(client: AsyncClient, *, rate_limit_per_min: int = 60) -> dict[str, str]:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (
        await client.post("/v1/admin/projects", json={"name": "p"}, headers=admin)
    ).json()
    key = (
        await client.post(
            "/v1/admin/keys",
            json={"project_id": project["id"], "rate_limit_per_min": rate_limit_per_min},
            headers=admin,
        )
    ).json()["key"]
    return {"Authorization": f"Bearer {key}"}


async def run_one(client: AsyncClient, headers: dict[str, str]) -> str:
    session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
    created = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "你好"}, headers=headers
    )
    assert created.status_code == 202, created.text
    run_id: str = created.json()["run_id"]
    for _ in range(100):
        run: dict[str, Any] = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
        if run["status"] in ("completed", "failed"):
            return run_id
        await asyncio.sleep(0.05)
    raise AssertionError("run 未完成")


async def test_rate_limit_returns_429_with_retry_after(tmp_path: Path) -> None:
    app = create_app(
        make_settings(tmp_path, ratelimit_global_per_min=10_000),
        provider=FakeChatProvider(turn_fn=demo_turn),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        headers = await bootstrap(client, rate_limit_per_min=1)  # 每分钟 1 次
        ok = await client.post("/v1/sessions", json={}, headers=headers)
        assert ok.status_code == 201
        throttled = await client.post("/v1/sessions", json={}, headers=headers)
        assert throttled.status_code == 429
        body = throttled.json()["error"]
        assert body["code"] == "rate_limited" and body["retryable"] is True
        assert "retry-after" in {k.lower() for k in throttled.headers}
        assert int(throttled.headers["retry-after"]) >= 1


async def test_usage_aggregation_by_model(client: AsyncClient) -> None:
    headers = await bootstrap(client)
    await run_one(client, headers)
    usage = await client.get("/v1/usage?group_by=model", headers=headers)
    assert usage.status_code == 200
    items = usage.json()["items"]
    assert items and items[0]["bucket"] == "custom"  # 注入 provider 的默认 model 名
    assert items[0]["runs"] == 1 and items[0]["input_tokens"] > 0


async def test_usage_by_day_shape(client: AsyncClient) -> None:
    headers = await bootstrap(client)
    usage = await client.get("/v1/usage", headers=headers)
    assert usage.status_code == 200
    assert usage.json()["group_by"] == "day"


async def test_models_endpoint(client: AsyncClient) -> None:
    headers = await bootstrap(client)
    models = await client.get("/v1/models", headers=headers)
    assert models.status_code == 200
    assert models.json()[0]["id"] == "gpt-4o-mini"  # 测试配置默认值


async def test_admin_stats(client: AsyncClient) -> None:
    headers = await bootstrap(client)
    await run_one(client, headers)
    stats = await client.get(
        "/v1/admin/stats", headers={"Authorization": f"Bearer {ADMIN_KEY}"}
    )
    assert stats.status_code == 200
    body = stats.json()
    assert body["runs_by_status"].get("completed", 0) >= 1
    assert body["usage"]["records"] >= 1
    assert body["db_size_bytes"] > 0


async def test_rate_limit_requires_auth_first(client: AsyncClient) -> None:
    no_auth = await client.get("/v1/models")
    assert no_auth.status_code == 401  # 鉴权先于限流
