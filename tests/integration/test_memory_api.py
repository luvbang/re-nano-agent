"""记忆端点集成测试 + run 成功后的自动提取旁路（v0.2-3）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.base import TextDelta
from agentd.providers.fake import FakeChatProvider, demo_turn, text_turn

ADMIN_KEY = "admin-memory-test"


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path,
        log_level="WARNING",
        log_json=False,
        admin_api_key=ADMIN_KEY,
        **overrides,  # type: ignore[arg-type]
    )


async def setup_session(client: AsyncClient) -> tuple[str, dict[str, str]]:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (await client.post("/v1/admin/projects", json={"name": "p"}, headers=admin)).json()
    key = (
        await client.post(
            "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin
        )
    ).json()["key"]
    headers = {"Authorization": f"Bearer {key}"}
    session = await client.post("/v1/sessions", json={"title": "s"}, headers=headers)
    return session.json()["id"], headers


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = create_app(make_settings(tmp_path), provider=FakeChatProvider(turn_fn=demo_turn))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def test_memory_crud_and_dedupe(client: AsyncClient) -> None:
    _session_id, headers = await setup_session(client)

    created = await client.post(
        "/v1/memories", json={"content": "用户偏好深色主题"}, headers=headers
    )
    assert created.status_code == 201
    row = created.json()
    assert row["content"] == "用户偏好深色主题" and row["status"] == "active"

    # 同内容去重：仍是 1 条 active
    again = await client.post(
        "/v1/memories", json={"content": " 用户偏好深色主题 "}, headers=headers
    )
    assert again.status_code == 201
    listed = await client.get("/v1/memories?status=active", headers=headers)
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["last_seen_at"] >= row["last_seen_at"]

    # 空内容 → 校验错误统一映射为 400 invalid_request 信封
    empty = await client.post("/v1/memories", json={"content": ""}, headers=headers)
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "invalid_request"

    # 归档后默认列表不再出现；再删 → 404
    deleted = await client.delete(f"/v1/memories/{row['id']}", headers=headers)
    assert deleted.status_code == 204
    active = (await client.get("/v1/memories?status=active", headers=headers)).json()
    assert active == []
    # DELETE 幂等：再次归档同一记忆仍是 204
    gone = await client.delete(f"/v1/memories/{row['id']}", headers=headers)
    assert gone.status_code == 204


async def test_memory_scoped_by_project(client: AsyncClient) -> None:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    p1 = (await client.post("/v1/admin/projects", json={"name": "p1"}, headers=admin)).json()
    p2 = (await client.post("/v1/admin/projects", json={"name": "p2"}, headers=admin)).json()
    key1 = (
        await client.post("/v1/admin/keys", json={"project_id": p1["id"]}, headers=admin)
    ).json()["key"]
    key2 = (
        await client.post("/v1/admin/keys", json={"project_id": p2["id"]}, headers=admin)
    ).json()["key"]

    await client.post(
        "/v1/memories", json={"content": "p1 的记忆"}, headers={"Authorization": f"Bearer {key1}"}
    )
    listed_p2 = await client.get(
        "/v1/memories", headers={"Authorization": f"Bearer {key2}"}
    )
    assert listed_p2.json() == []
    # 跨 project 删除 → 404（不泄漏存在性）
    mem_id = (
        await client.get("/v1/memories", headers={"Authorization": f"Bearer {key1}"})
    ).json()[0]["id"]
    cross = await client.delete(
        f"/v1/memories/{mem_id}", headers={"Authorization": f"Bearer {key2}"}
    )
    assert cross.status_code == 404


async def test_memory_requires_auth(client: AsyncClient) -> None:
    denied = await client.get("/v1/memories")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"


async def test_run_extraction_writes_memories(tmp_path: Path) -> None:
    """memory_extract_enabled=True：run 成功后旁路提取事实入库（不改 run 结果）。"""
    extraction_stream = [
        TextDelta("- 用户偏好深色主题\n"),
        TextDelta("项目使用 SQLite\n"),
    ]
    provider = FakeChatProvider(
        turns=[text_turn("记住了"), extraction_stream],
    )
    app = create_app(
        make_settings(tmp_path, memory_extract_enabled=True),
        provider=provider,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
        project = (
            await client.post("/v1/admin/projects", json={"name": "p"}, headers=admin)
        ).json()
        key = (
            await client.post(
                "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin
            )
        ).json()["key"]
        headers = {"Authorization": f"Bearer {key}"}
        session = (
            await client.post("/v1/sessions", json={}, headers=headers)
        ).json()
        created = await client.post(
            f"/v1/sessions/{session['id']}/runs",
            json={"input": "我喜欢深色主题，数据库用 SQLite"},
            headers=headers,
        )
        assert created.status_code == 202
        run_id = created.json()["run_id"]

        # 等 run 终态
        for _ in range(200):
            run = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
            if run.get("status") in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(0.02)
        assert run["status"] == "completed"

        # 提取是旁路任务：直接等待后台任务集收尾（确定性，不靠轮询碰运气）
        manager = app.state.run_manager
        if manager._bg_tasks:
            await asyncio.gather(*manager._bg_tasks, return_exceptions=True)
        rows: list[dict[str, Any]] = (
            await client.get("/v1/memories?status=active", headers=headers)
        ).json()
        contents = {r["content"] for r in rows}
        assert contents == {"用户偏好深色主题", "项目使用 SQLite"}
        # run 结果不受提取影响
        assert run["status"] == "completed" and run["error"] is None
