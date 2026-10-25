"""价格表与成本计量测试（M4 D2 DoD：能回答“本月花了多少钱”）。"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.fake import FakeChatProvider, demo_turn
from agentd.services.usage_service import UsageService, parse_price_table
from agentd.storage.db import Database

PRICE = '{"gpt-4o-mini": {"input": 0.15, "output": 0.6}}'


def test_parse_price_table_valid_empty_invalid() -> None:
    assert parse_price_table("") == {}
    assert parse_price_table("not json") == {}
    assert parse_price_table("[1,2]") == {}
    assert parse_price_table(PRICE)["gpt-4o-mini"] == {"input": 0.15, "output": 0.6}


def test_cost_math() -> None:
    service = UsageService.__new__(UsageService)  # 不连库，只测换算
    service.price_table = parse_price_table(PRICE)
    # 1M input + 0.5M output = 0.15 + 0.30
    assert service.cost_usd("gpt-4o-mini", 1_000_000, 500_000) == pytest.approx(0.45)
    assert service.cost_usd("未知模型", 1_000_000, 1_000_000) == 0.0


async def test_record_writes_cost_to_usage_and_run(tmp_path: Path) -> None:
    db = Database(tmp_path / "u.db")
    db.migrate()
    from agentd.storage.repositories import ProjectRepository, SessionRepository

    project = await ProjectRepository(db).create(name="p", workspace_path="/tmp")
    session = await SessionRepository(db).create(project_id=str(project["id"]))
    db.execute_sync(
        "INSERT INTO runs (id, session_id, project_id, status, model)"
        " VALUES ('r_1', ?, ?, 'completed', 'gpt-4o-mini')",
        (str(session["id"]), str(project["id"])),
    )
    service = UsageService(db, parse_price_table(PRICE))
    cost = await service.record(
        project_id=str(project["id"]),
        run_id="r_1",
        model="gpt-4o-mini",
        input_tokens=2_000_000,
        output_tokens=1_000_000,
    )
    assert cost == pytest.approx(0.9)  # 2M*0.15 + 1M*0.6
    run_row = await db.fetch_one("SELECT cost_usd FROM runs WHERE id = 'r_1'")
    assert run_row is not None and float(run_row["cost_usd"]) == pytest.approx(0.9)
    usage_row = await db.fetch_one(
        "SELECT cost_usd FROM usage_records WHERE run_id = 'r_1'"
    )
    assert usage_row is not None and float(usage_row["cost_usd"]) == pytest.approx(0.9)
    db.close()


async def test_usage_endpoint_reports_cost_field(tmp_path: Path) -> None:
    admin_key = f"admin-{uuid.uuid4().hex}"
    settings = Settings(
        env="test",
        data_dir=tmp_path,
        log_level="WARNING",
        log_json=False,
        admin_api_key=admin_key,
        llm_price_table=PRICE,
    )
    app = create_app(settings, provider=FakeChatProvider(turn_fn=demo_turn))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        admin = {"Authorization": f"Bearer {admin_key}"}
        project = (
            await client.post("/v1/admin/projects", json={"name": "p"}, headers=admin)
        ).json()
        key = (
            await client.post(
                "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin
            )
        ).json()["key"]
        headers = {"Authorization": f"Bearer {key}"}
        session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
        created = await client.post(
            f"/v1/sessions/{session['id']}/runs", json={"input": "你好"}, headers=headers
        )
        run_id = created.json()["run_id"]
        for _ in range(100):
            run = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
            if run["status"] == "completed":
                break
            await asyncio.sleep(0.02)
        usage = await client.get("/v1/usage?group_by=model", headers=headers)
        item = usage.json()["items"][0]
        # 注入 provider 的 model 名不在价格表内 → 成本 0 但字段存在（token 计量仍准确）
        assert item["cost_usd"] == 0.0 and item["input_tokens"] > 0
