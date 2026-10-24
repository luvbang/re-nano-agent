"""/metrics 指标端点测试（M5 D4）。"""

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

ADMIN_KEY = "admin-metrics-test"


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        env="test", data_dir=tmp_path, log_level="WARNING", log_json=False,
        admin_api_key=ADMIN_KEY,
    )
    app = create_app(settings, provider=FakeChatProvider(turn_fn=demo_turn))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def drive_run(client: AsyncClient, headers: dict[str, str]) -> str:
    session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
    created = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "你好"}, headers=headers
    )
    run_id: str = created.json()["run_id"]
    for _ in range(100):
        run: dict[str, Any] = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
        if run["status"] == "completed":
            return run_id
        await asyncio.sleep(0.02)
    raise AssertionError("run 未完成")


async def issue_key(client: AsyncClient) -> dict[str, str]:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (
        await client.post("/v1/admin/projects", json={"name": "p"}, headers=admin)
    ).json()
    key = (
        await client.post("/v1/admin/keys", json={"project_id": project["id"]}, headers=admin)
    ).json()["key"]
    return {"Authorization": f"Bearer {key}"}


async def test_metrics_requires_admin(client: AsyncClient) -> None:
    denied = await client.get("/metrics")
    assert denied.status_code in (401, 403)


async def test_metrics_content_after_traffic(client: AsyncClient) -> None:
    headers = await issue_key(client)
    await drive_run(client, headers)

    response = await client.get(
        "/metrics", headers={"Authorization": f"Bearer {ADMIN_KEY}"}
    )
    assert response.status_code == 200
    text = response.text
    assert "text/plain" in response.headers["content-type"]
    # 请求计数（至少覆盖本测试的请求）
    assert "# TYPE agentd_http_requests_total counter" in text
    assert 'agentd_http_requests_total{status="200"}' in text
    # run 终态计数 + 时长直方图
    assert 'agentd_runs_total{status="completed"} 1' in text
    assert "agentd_run_duration_seconds_bucket" in text
    assert "agentd_run_duration_seconds_count 1" in text
    # DB 体量 gauge
    assert "agentd_db_size_bytes" in text
    assert "agentd_http_request_duration_seconds" in text
