"""故障演练（M7 D4）：上游断流/熔断注入——run 落终态、事件可回放、会话可继续。

DB 锁/磁盘满/OOM/证书过期不可本机演练，处置步骤见 docs/runbook.md。
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
from agentd.providers.base import ProviderServerError, TextDelta
from agentd.providers.fake import FakeChatProvider

ADMIN_KEY = "admin-drill-test"


class MidStreamDyingProvider(FakeChatProvider):
    """先吐 2 个 delta 再断流（模拟上游连接中断）。"""

    async def chat(self, messages, *, tools=None, model=None):  # type: ignore[no-untyped-def]
        yield TextDelta("开头")
        yield TextDelta("还在写")
        raise ProviderServerError("上游连接中断")


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test", data_dir=tmp_path, log_level="WARNING", log_json=False,
        admin_api_key=ADMIN_KEY, llm_retries=0,
    )


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = create_app(make_settings(tmp_path), provider=MidStreamDyingProvider())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def bootstrap(client: AsyncClient) -> dict[str, str]:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (
        await client.post("/v1/admin/projects", json={"name": "drill"}, headers=admin)
    ).json()
    key = (
        await client.post("/v1/admin/keys", json={"project_id": project["id"]}, headers=admin)
    ).json()["key"]
    return {"Authorization": f"Bearer {key}"}


async def sse_text(client: AsyncClient, run_id: str, headers: dict[str, str]) -> str:
    buffer = ""
    async with client.stream("GET", f"/v1/runs/{run_id}/events", headers=headers) as response:
        async for chunk in response.aiter_text():
            buffer += chunk
    return buffer


async def test_upstream_midstream_death_fails_run_and_session_recovers(
    client: AsyncClient,
) -> None:
    headers = await bootstrap(client)
    session = (await client.post("/v1/sessions", json={}, headers=headers)).json()

    created = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "会被断流"}, headers=headers
    )
    run_id = created.json()["run_id"]
    for _ in range(100):
        run: dict[str, Any] = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
        if run["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.02)
    assert run["status"] == "failed"
    assert run["error"]["code"] == "model_error"

    # 事件流以 run.failed 收尾（含已产生的 run.started），可回放
    text = await sse_text(client, run_id, headers)
    assert "event: run.started" in text
    assert "event: run.failed" in text
    assert "上游连接中断" in text

    # 会话可继续：新 run 正常受理（故障不外溢）
    again = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "再来一次"}, headers=headers
    )
    assert again.status_code == 202


async def test_retryable_5xx_exhausts_into_failed_run(client: AsyncClient) -> None:
    """重试耗尽（llm_retries=0 即刻失败）也必须落终态而不是悬挂。"""
    headers = await bootstrap(client)
    session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
    created = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "x"}, headers=headers
    )
    run_id = created.json()["run_id"]
    for _ in range(100):
        run = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
        if run["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.02)
    assert run["status"] == "failed"
    # 审计可见 run.created（失败也会留下轨迹）
    audit = await client.get(
        "/v1/admin/audit?action=run.created", headers={"Authorization": f"Bearer {ADMIN_KEY}"}
    )
    assert any(entry["target"] == run_id for entry in audit.json())

