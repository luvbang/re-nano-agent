"""/v1 平台 API 集成测试（M3 DoD：curl 全流程 = 这里用 httpx 走同一条路径）。

覆盖：鉴权（401/403/撤销）、全流程（session→run→SSE→落库→usage）、工具回路、
SSE 回放（Last-Event-ID）、取消、并发冲突、限流、跨项目 404、幂等、重启恢复。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.fake import FakeChatProvider, demo_turn
from agentd.services.keys import generate_key
from agentd.storage.db import Database
from agentd.storage.repositories import ApiKeyRepository, ProjectRepository

ADMIN_KEY = "agd_test_admin_0123456789"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path,
        log_level="WARNING",
        log_json=False,
        admin_api_key=ADMIN_KEY,
    )


@pytest.fixture
def m3_settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
async def app(m3_settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(m3_settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def admin_headers(key: str = ADMIN_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def create_session(client: AsyncClient) -> dict[str, Any]:
    resp = await client.post(
        "/v1/sessions", json={"title": "测试会话"}, headers=admin_headers()
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def wait_terminal(
    client: AsyncClient, run_id: str, timeout_s: float = 10.0
) -> dict[str, Any]:
    for _ in range(int(timeout_s / 0.05)):
        resp = await client.get(f"/v1/runs/{run_id}", headers=admin_headers())
        assert resp.status_code == 200, resp.text
        run: dict[str, Any] = resp.json()
        if run["status"] in ("completed", "failed", "cancelled", "interrupted"):
            return run
        await asyncio.sleep(0.05)
    raise AssertionError("run 未在超时内进入终态")


async def collect_sse(
    client: AsyncClient, run_id: str, last_event_id: int | None = None
) -> list[dict[str, Any]]:
    headers = admin_headers()
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    events: list[dict[str, Any]] = []
    async with client.stream("GET", f"/v1/runs/{run_id}/events", headers=headers) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload: dict[str, Any] = json.loads(line[6:])
            events.append(payload)
            if payload.get("type") in ("run.completed", "run.failed"):
                break
    return events


# ---------- 鉴权 ----------


async def test_auth_missing_and_bad_key(client: AsyncClient) -> None:
    resp = await client.get("/v1/sessions")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    resp = await client.get("/v1/sessions", headers=admin_headers("agd_wrong"))
    assert resp.status_code == 401


async def test_non_admin_forbidden(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/admin/keys", json={"name": "x"}, headers=admin_headers()
    )
    assert resp.status_code == 201
    secret = resp.json()["secret"]
    resp = await client.get("/v1/admin/keys", headers=admin_headers(secret))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


async def test_revoked_key_rejected_immediately(client: AsyncClient) -> None:
    resp = await client.post("/v1/admin/keys", json={"name": "t"}, headers=admin_headers())
    key_id, secret = resp.json()["key"]["id"], resp.json()["secret"]
    assert (await client.get("/v1/sessions", headers=admin_headers(secret))).status_code == 200
    resp = await client.delete(f"/v1/admin/keys/{key_id}", headers=admin_headers())
    assert resp.status_code == 204
    resp = await client.get("/v1/sessions", headers=admin_headers(secret))
    assert resp.status_code == 401


# ---------- 会话与消息 ----------


async def test_session_crud_and_message_pagination(client: AsyncClient) -> None:
    session = await create_session(client)
    assert session["title"] == "测试会话"
    resp = await client.get("/v1/sessions", headers=admin_headers())
    assert [s["id"] for s in resp.json()] == [session["id"]]
    resp = await client.get(f"/v1/sessions/{session['id']}", headers=admin_headers())
    assert resp.status_code == 200
    resp = await client.get("/v1/sessions/s_none", headers=admin_headers())
    assert resp.status_code == 404
    # 空消息列表
    resp = await client.get(
        f"/v1/sessions/{session['id']}/messages", headers=admin_headers()
    )
    assert resp.json() == []


# ---------- 全流程（含工具回路） ----------


async def test_full_flow_text_run(client: AsyncClient) -> None:
    session = await create_session(client)
    resp = await client.post(
        f"/v1/sessions/{session['id']}/runs",
        json={"input": "你好"},
        headers=admin_headers(),
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    events = await collect_sse(client, run_id)
    types = [e["type"] for e in events]
    assert types[0] == "run.started"
    assert types[-1] == "run.completed"
    # 契约 §3 已知限制：delta 不落库，晚于终态连接时收不到增量（以 completed 全文为准）
    if "message.delta" in types:
        delta_before_completed = types.index("message.delta") < types.index("message.completed")
        assert delta_before_completed
    # seq 单调递增
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    # completed 全文（回放保证）
    completed = next(e for e in events if e["type"] == "message.completed")
    assert completed["content"] == "(fake)你说的是：你好"

    run = await wait_terminal(client, run_id)
    assert run["status"] == "completed"
    assert run["input_tokens"] > 0

    # messages：user + assistant
    resp = await client.get(
        f"/v1/sessions/{session['id']}/messages", headers=admin_headers()
    )
    messages = resp.json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "你好"
    assert messages[1]["content"] == "(fake)你说的是：你好"

    # usage 聚合（按天/按模型）
    for group_by in ("day", "model"):
        resp = await client.get(
            "/v1/usage",
            params={"from": "2000-01-01", "to": "2999-01-01", "group_by": group_by},
            headers=admin_headers(),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["group_by"] == group_by
        assert sum(i["runs"] for i in body["items"]) == 1


async def test_full_flow_tool_run_and_sse_replay(client: AsyncClient) -> None:
    session = await create_session(client)
    resp = await client.post(
        f"/v1/sessions/{session['id']}/runs",
        json={"input": "现在几点了？"},
        headers=admin_headers(),
    )
    run_id = resp.json()["run_id"]
    events = await collect_sse(client, run_id)
    types = [e["type"] for e in events]
    assert "tool.started" in types and "tool.completed" in types
    tool_started = next(e for e in events if e["type"] == "tool.started")
    assert tool_started["name"] == "get_time"

    # 终态后重连：控制类事件全量回放（delta 不落库）
    replay = await collect_sse(client, run_id)
    replay_types = [e["type"] for e in replay]
    assert replay_types == [
        "run.started",
        "tool.started",
        "tool.completed",
        "message.completed",
        "run.completed",
    ]
    # Last-Event-ID=1 → 只回放 seq>1
    partial = await collect_sse(client, run_id, last_event_id=1)
    assert all(e["seq"] > 1 for e in partial)
    assert partial[-1]["type"] == "run.completed"

    # messages：完整工具交换（user + assistant(tool_calls) + tool + assistant）
    resp = await client.get(
        f"/v1/sessions/{session['id']}/messages", headers=admin_headers()
    )
    messages = resp.json()
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[1]["tool_calls"][0]["function"]["name"] == "get_time"
    assert messages[2]["tool_call_id"] == messages[1]["tool_calls"][0]["id"]


# ---------- 取消 / 冲突 / 幂等 ----------


async def test_cancel_and_conflict(app: FastAPI, client: AsyncClient) -> None:
    app.state.provider = FakeChatProvider(turn_fn=demo_turn, delay_s=0.15)
    session = await create_session(client)
    first = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "慢一点"}, headers=admin_headers()
    )
    assert first.status_code == 202
    run_id = first.json()["run_id"]
    # 同 session 并发 run → 409
    second = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "并发"}, headers=admin_headers()
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"
    # 取消 → cancelled；SSE 流随之结束
    resp = await client.post(f"/v1/runs/{run_id}/cancel", headers=admin_headers())
    assert resp.status_code == 200
    run = await wait_terminal(client, run_id)
    assert run["status"] == "cancelled"
    events = await collect_sse(client, run_id)
    assert all(e["type"] != "run.completed" for e in events)  # 取消不发终态事件


async def test_idempotency_key_returns_same_run(client: AsyncClient) -> None:
    session = await create_session(client)
    headers = admin_headers() | {"Idempotency-Key": "idem-1"}
    r1 = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "你好"}, headers=headers
    )
    r2 = await client.post(
        f"/v1/sessions/{session['id']}/runs", json={"input": "你好"}, headers=headers
    )
    assert r1.json()["run_id"] == r2.json()["run_id"]
    assert r2.headers.get("Idempotency-Replayed") == "true"


# ---------- 限流 / 跨项目 404 ----------


async def test_rate_limit_429_with_retry_after(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/admin/keys",
        json={"name": "低频", "rate_limit_per_min": 2},
        headers=admin_headers(),
    )
    secret = resp.json()["secret"]
    ok = 0
    for _ in range(3):
        resp = await client.get("/v1/sessions", headers=admin_headers(secret))
        if resp.status_code == 429:
            assert resp.json()["error"]["code"] == "rate_limited"
            assert resp.json()["error"]["retryable"] is True
            assert "retry-after" in {k.lower() for k in resp.headers}
            break
        ok += 1
    assert ok == 2, "前两次应放行，第三次应 429"


async def test_cross_project_is_404(app: FastAPI, client: AsyncClient) -> None:
    session = await create_session(client)
    db: Database = app.state.db
    other_project = await ProjectRepository(db).create(
        name="other", workspace_path=str(app.state.settings.workspace_root)
    )
    secret, key_hash, prefix = generate_key()
    await ApiKeyRepository(db).create(
        project_id=other_project["id"], key_hash=key_hash, key_prefix=prefix, name="other"
    )
    # 对方项目看不到本项目的 session / messages（404，不泄漏存在性）
    resp = await client.get(
        f"/v1/sessions/{session['id']}", headers=admin_headers(secret)
    )
    assert resp.status_code == 404
    resp = await client.get(
        f"/v1/sessions/{session['id']}/messages", headers=admin_headers(secret)
    )
    assert resp.status_code == 404
    # 自己项目的列表正常（不是 403，资源就不存在）
    resp = await client.get("/v1/sessions", headers=admin_headers(secret))
    assert resp.status_code == 200
    assert resp.json() == []
    # 对方项目在本项目 session 里建 run → 404
    resp = await client.post(
        f"/v1/sessions/{session['id']}/runs",
        json={"input": "hi"},
        headers=admin_headers(secret),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# ---------- 重启恢复 ----------


async def test_restart_resumes_history(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    # 第一个进程：一轮对话
    app1 = create_app(settings)
    async with (
        app1.router.lifespan_context(app1),
        AsyncClient(transport=ASGITransport(app=app1), base_url="http://t1") as c1,
    ):
        session = (await create_session(c1))["id"]
        r = await c1.post(
            f"/v1/sessions/{session}/runs", json={"input": "第一轮"}, headers=admin_headers()
        )
        await wait_terminal(c1, r.json()["run_id"])
    # 第二个进程（同一 DB）：续聊，模型能看到第一轮历史
    app2 = create_app(settings)
    async with (
        app2.router.lifespan_context(app2),
        AsyncClient(transport=ASGITransport(app=app2), base_url="http://t2") as c2,
    ):
        r = await c2.post(
            f"/v1/sessions/{session}/runs", json={"input": "第二轮"}, headers=admin_headers()
        )
        run_id = r.json()["run_id"]
        events = await collect_sse(c2, run_id)
        assert events[-1]["type"] == "run.completed"
        provider: FakeChatProvider = app2.state.provider
        first_call = provider.calls[0]
        contents = [m.get("content") or "" for m in first_call]
        assert any("(fake)你说的是：第一轮" in c for c in contents)
        messages = (
            await c2.get(f"/v1/sessions/{session}/messages", headers=admin_headers())
        ).json()
        assert len(messages) == 4  # 两轮 × (user + assistant)


# ---------- models ----------


async def test_models_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/v1/models", headers=admin_headers())
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["id"] == "gpt-4o-mini"
    assert "read_file" in item["tools"] and "get_time" in item["tools"]
