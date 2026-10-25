"""runs API 与 SSE 测试（M3 D2 DoD：并发不串会话；SSE 可重连；取消不悬挂）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.fake import FakeChatProvider, demo_turn

ADMIN_KEY = "admin-runs-test"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path,
        log_level="WARNING",
        log_json=False,
        admin_api_key=ADMIN_KEY,
        run_timeout_s=30,
    )


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    provider = FakeChatProvider(turn_fn=demo_turn)
    app = create_app(make_settings(tmp_path), provider=provider)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


async def setup_session(client: AsyncClient) -> tuple[str, dict[str, str]]:
    """管理员引导 project+key，再用 key 建 session。返回 (session_id, headers)。"""
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


async def read_sse(client: AsyncClient, url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with client.stream("GET", url, headers=headers) as response:
        assert response.status_code == 200
        buffer = ""
        async for chunk in response.aiter_text():
            buffer += chunk
        for block in buffer.split("\n\n"):
            if not block.strip() or block.startswith(":"):
                continue
            entry: dict[str, Any] = {}
            for line in block.splitlines():
                if line.startswith("event: "):
                    entry["event"] = line[len("event: ") :]
                elif line.startswith("id: "):
                    entry["id"] = int(line[len("id: ") :])
                elif line.startswith("data: "):
                    entry["data"] = json.loads(line[len("data: ") :])
            if entry:
                events.append(entry)
    return events


async def wait_terminal(
    client: AsyncClient, run_id: str, headers: dict[str, str]
) -> dict[str, Any]:
    for _ in range(100):
        run: dict[str, Any] = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
        if run["status"] in ("completed", "failed", "cancelled", "interrupted"):
            return run
        await asyncio.sleep(0.05)
    raise AssertionError(f"run 未终态：{run_id}")


async def test_run_lifecycle_with_sse(client: AsyncClient) -> None:
    session_id, headers = await setup_session(client)
    created = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "你好"}, headers=headers
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]

    events = await read_sse(client, f"/v1/runs/{run_id}/events", headers)
    names = [e["event"] for e in events]
    assert names[0] == "run.started"
    assert events[0]["data"]["run_id"] == run_id
    assert "message.delta" in names
    completed = next(e for e in events if e["event"] == "message.completed")
    assert "你说的是" in completed["data"]["content"]
    assert names[-1] == "run.completed"
    # seq 单调递增
    seqs = [e["id"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    run = await wait_terminal(client, run_id, headers)
    assert run["status"] == "completed"
    assert run["input_tokens"] > 0


async def test_concurrent_same_session_conflicts(client: AsyncClient) -> None:
    session_id, headers = await setup_session(client)
    first = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "第一问"}, headers=headers
    )
    assert first.status_code == 202
    second = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "第二问"}, headers=headers
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"
    await wait_terminal(client, first.json()["run_id"], headers)


async def test_cancel_running_run(client: AsyncClient) -> None:
    session_id, headers = await setup_session(client)
    created = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "你好"}, headers=headers
    )
    run_id = created.json()["run_id"]
    cancel = await client.post(f"/v1/runs/{run_id}/cancel", headers=headers)
    assert cancel.status_code == 200
    run = await wait_terminal(client, run_id, headers)
    assert run["status"] in ("cancelled", "completed")  # 极快完成时取消竞态允许 completed
    # 无悬挂：进程内无残留 active（通过再次建 run 可成功验证 session 锁已释放）
    again = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "再问"}, headers=headers
    )
    assert again.status_code == 202
    await wait_terminal(client, again.json()["run_id"], headers)


async def test_idempotency_key_returns_same_run(client: AsyncClient) -> None:
    session_id, headers = await setup_session(client)
    idem = {"Authorization": headers["Authorization"], "Idempotency-Key": "idem-1"}
    first = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "幂等"}, headers=idem
    )
    second = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "幂等"}, headers=idem
    )
    assert first.json()["run_id"] == second.json()["run_id"]
    await wait_terminal(client, first.json()["run_id"], headers)


async def test_sse_replay_after_completion_with_last_event_id(client: AsyncClient) -> None:
    session_id, headers = await setup_session(client)
    created = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "几点了？"}, headers=headers
    )
    run_id = created.json()["run_id"]
    await wait_terminal(client, run_id, headers)

    # 全量回放（delta 不入库，只含控制事件）
    full = await read_sse(client, f"/v1/runs/{run_id}/events", headers)
    assert next(e["event"] for e in full) == "run.started"
    assert "message.delta" not in [e["event"] for e in full]

    # Last-Event-ID=2 → 只回 seq>2
    partial_headers = {**headers, "Last-Event-ID": "2"}
    partial = await read_sse(client, f"/v1/runs/{run_id}/events", partial_headers)
    assert all(e["id"] > 2 for e in partial)
    assert [e["event"] for e in partial][-1] == "run.completed"


async def test_tool_run_events_persisted(client: AsyncClient) -> None:
    session_id, headers = await setup_session(client)
    created = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "几点了？"}, headers=headers
    )
    run_id = created.json()["run_id"]
    await wait_terminal(client, run_id, headers)
    events = await read_sse(client, f"/v1/runs/{run_id}/events", headers)
    names = [e["event"] for e in events]
    assert "tool.started" in names and "tool.completed" in names
    tool_done = next(e for e in events if e["event"] == "tool.completed")
    assert tool_done["data"]["name"] == "get_time"
    assert tool_done["data"]["status"] == "ok"


async def test_messages_expose_tool_calls_wire(client: AsyncClient) -> None:
    """历史消息透出 tool_calls wire（控制台据此重建工具卡）。"""
    session_id, headers = await setup_session(client)
    created = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "几点了？"}, headers=headers
    )
    await wait_terminal(client, created.json()["run_id"], headers)
    page = await client.get(f"/v1/sessions/{session_id}/messages", headers=headers)
    assert page.status_code == 200
    items = page.json()["items"]
    assistant_with_tools = next(m for m in items if m["tool_calls"])
    call = assistant_with_tools["tool_calls"][0]
    assert call["id"] and call["type"] == "function"
    assert call["function"]["name"] == "get_time"


async def test_cross_project_run_is_404(client: AsyncClient) -> None:
    session_id, headers = await setup_session(client)
    created = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "x"}, headers=headers
    )
    run_id = created.json()["run_id"]
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project2 = (await client.post("/v1/admin/projects", json={"name": "p2"}, headers=admin)).json()
    key2 = (
        await client.post("/v1/admin/keys", json={"project_id": project2["id"]}, headers=admin)
    ).json()["key"]
    other = await client.get(
        f"/v1/runs/{run_id}", headers={"Authorization": f"Bearer {key2}"}
    )
    assert other.status_code == 404


async def test_run_without_model_config_returns_502(tmp_path: Path) -> None:
    settings = Settings(env="test", data_dir=tmp_path, log_level="WARNING", admin_api_key=ADMIN_KEY)
    app = create_app(settings)  # 无 provider、无 llm key
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
            project = (
                await client.post("/v1/admin/projects", json={"name": "p"}, headers=admin)
            ).json()
            key = (
                await client.post(
                    "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin
                )
            ).json()["key"]
            session = await client.post(
                "/v1/sessions", json={}, headers={"Authorization": f"Bearer {key}"}
            )
            run = await client.post(
                f"/v1/sessions/{session.json()['id']}/runs",
                json={"input": "hi"},
                headers={"Authorization": f"Bearer {key}"},
            )
            assert run.status_code == 502
            assert run.json()["error"]["code"] == "model_error"
