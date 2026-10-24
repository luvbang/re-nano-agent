"""20 并发压测（M3 D5 DoD：20 并发 run 无 5xx；取消后无残留）。

对真实外部服务器的压测用 scripts/loadtest.py；这里在进程内（ASGI + fake provider）
跑同样的并发形态，进 CI 作为回归门禁。
"""

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

ADMIN_KEY = "admin-load-test"
CONCURRENCY = 20


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        env="test",
        data_dir=tmp_path,
        log_level="WARNING",
        log_json=False,
        admin_api_key=ADMIN_KEY,
    )
    app = create_app(settings, provider=FakeChatProvider(turn_fn=demo_turn))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def setup_keys(client: AsyncClient, count: int) -> list[dict[str, str]]:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (
        await client.post("/v1/admin/projects", json={"name": "load"}, headers=admin)
    ).json()
    headers_list = []
    for _ in range(count):
        key = (
            await client.post(
                "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin
            )
        ).json()["key"]
        headers_list.append({"Authorization": f"Bearer {key}"})
    return headers_list


async def drive_run(client: AsyncClient, headers: dict[str, str]) -> int:
    """一个完整 run 的状态码（200=completed；4xx/5xx 原样返回）。"""
    session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
    created = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "并发压测"}, headers=headers
    )
    if created.status_code != 202:
        return created.status_code
    run_id: str = created.json()["run_id"]
    for _ in range(400):
        await asyncio.sleep(0.02)
        run: dict[str, Any] = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
        if run["status"] == "completed":
            return 200
        if run["status"] in ("failed", "cancelled", "interrupted"):
            return 500
    return 504


async def test_twenty_concurrent_runs_no_5xx(client: AsyncClient) -> None:
    headers_list = await setup_keys(client, CONCURRENCY)
    codes = await asyncio.gather(*(drive_run(client, h) for h in headers_list))
    assert all(code == 200 for code in codes), f"非 200：{codes}"
    # 全部落库完成
    stats = (
        await client.get("/v1/admin/stats", headers={"Authorization": f"Bearer {ADMIN_KEY}"})
    ).json()
    assert stats["runs_by_status"].get("completed", 0) >= CONCURRENCY


async def test_cancel_leaves_no_residue(client: AsyncClient) -> None:
    headers = (await setup_keys(client, 1))[0]
    session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
    created = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "你好"}, headers=headers
    )
    run_id = created.json()["run_id"]
    cancel = await client.post(f"/v1/runs/{run_id}/cancel", headers=headers)
    assert cancel.status_code in (200, 409)  # 已完成时取消报 409 属正常竞态
    for _ in range(200):
        run = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
        if run["status"] in ("completed", "cancelled"):
            break
        await asyncio.sleep(0.02)
    # 取消后同 session 可继续新 run（无残留锁/任务）
    again = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "下一轮"}, headers=headers
    )
    assert again.status_code == 202
