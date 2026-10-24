"""审计日志与日志脱敏测试（M4 D3 DoD：敏感字段不落日志）。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from io import StringIO
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.log import JsonFormatter, redact
from agentd.main import create_app
from agentd.providers.fake import FakeChatProvider, demo_turn

ADMIN_KEY = "admin-audit-test"
PLAINTEXT_KEY = "agd_super_secret_key_value_12345"


def test_redact_patterns() -> None:
    assert redact("key=agd_abcdefghijklmnop123") == "key=[REDACTED]"
    assert redact("Bearer sk-abcdef1234567890") == "Bearer [REDACTED]"
    assert redact('"password": "hunter2secret"') == "[REDACTED]"
    assert redact("普通日志不受影响") == "普通日志不受影响"


def test_json_formatter_redacts_records() -> None:
    logger = logging.getLogger("agentd.test.redaction")
    buffer = StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.warning(
            "请求失败 key=%s", PLAINTEXT_KEY, extra={"authorization": f"Bearer {PLAINTEXT_KEY}"}
        )
    finally:
        logger.removeHandler(handler)
    out = buffer.getvalue()
    assert PLAINTEXT_KEY not in out
    assert "[REDACTED]" in out


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


async def test_audit_trail_for_admin_and_run_flow(client: AsyncClient) -> None:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (
        await client.post("/v1/admin/projects", json={"name": "audit"}, headers=admin)
    ).json()
    created = await client.post(
        "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin
    )
    headers = {"Authorization": f"Bearer {created.json()['key']}"}

    session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
    run = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "几点了？"}, headers=headers
    )
    run_id = run.json()["run_id"]
    for _ in range(100):
        status = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
        if status["status"] == "completed":
            break
        await asyncio.sleep(0.02)

    audit = await client.get("/v1/admin/audit", headers=admin)
    assert audit.status_code == 200
    entries = audit.json()
    actions = {entry["action"] for entry in entries}
    assert {"project.created", "key.created", "run.created", "tool.call"} <= actions
    # 明文 key 绝不出现在审计里（只有 prefix）
    assert PLAINTEXT_KEY not in json.dumps(entries)
    key_entry = next(e for e in entries if e["action"] == "key.created")
    assert key_entry["detail"]["prefix"].startswith("agd_")
    assert len(key_entry["detail"]["prefix"]) <= 12
    # 过滤参数
    only_runs = await client.get(
        "/v1/admin/audit?action=run.created", headers=admin
    )
    assert all(e["action"] == "run.created" for e in only_runs.json())
    tool_entry = next(e for e in entries if e["action"] == "tool.call")
    assert tool_entry["target"] == "get_time" and tool_entry["detail"]["status"] == "ok"


async def test_key_revocation_audited(client: AsyncClient) -> None:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (
        await client.post("/v1/admin/projects", json={"name": "audit2"}, headers=admin)
    ).json()
    created = await client.post(
        "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin
    )
    key_id = created.json()["detail"]["id"]
    revoked = await client.post(f"/v1/admin/keys/{key_id}/revoke", headers=admin)
    assert revoked.status_code == 200
    audit = await client.get("/v1/admin/audit?action=key.revoked", headers=admin)
    assert audit.json()[0]["target"] == key_id
