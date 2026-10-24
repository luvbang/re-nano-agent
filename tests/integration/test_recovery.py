"""崩溃恢复与 SSE 重连（M3 D4 DoD：kill -9 后客户端能重新订阅到状态）。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.base import StreamEnd, TextDelta, Usage
from agentd.providers.fake import FakeChatProvider, demo_turn

ADMIN_KEY = "admin-recovery-test"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test", data_dir=tmp_path, log_level="WARNING", log_json=False, admin_api_key=ADMIN_KEY
    )


_project_seq = 0


async def bootstrap(client: AsyncClient) -> dict[str, str]:
    global _project_seq
    _project_seq += 1
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (
        await client.post("/v1/admin/projects", json={"name": f"p{_project_seq}"}, headers=admin)
    ).json()
    key = (
        await client.post("/v1/admin/keys", json={"project_id": project["id"]}, headers=admin)
    ).json()["key"]
    return {"Authorization": f"Bearer {key}"}


async def test_kill9_client_can_resubscribe_to_state(tmp_path: Path) -> None:
    """进程死亡（run 留 running + 部分事件已落库）→ 新进程收敛 interrupted → SSE 可订阅。"""
    settings = make_settings(tmp_path)
    db_path = settings.db_path
    assert db_path is not None

    # 阶段一：拿一个真实 session，随后模拟死亡进程留下的 DB 现场（等价 kill -9 落点）
    app1 = create_app(settings, provider=FakeChatProvider(turn_fn=demo_turn))
    async with (
        app1.router.lifespan_context(app1),
        AsyncClient(transport=ASGITransport(app=app1), base_url="http://t") as client,
    ):
        headers = await bootstrap(client)
        session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
    # 阶段二沿用同一把 key（key 落库跨进程有效），不再新开 project
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO runs (id, session_id, project_id, status, model) VALUES"
        " ('r_dead', ?, (SELECT project_id FROM sessions LIMIT 1), 'running', 'x')",
        (session["id"],),
    )
    conn.execute(
        "INSERT INTO run_events (run_id, seq, type, payload_json) VALUES"
        " ('r_dead', 1, 'run.started', ?)",
        (json.dumps({"run_id": "r_dead", "session_id": session["id"]}),),
    )
    conn.commit()
    conn.close()

    # 阶段二：新进程启动（lifespan 收敛 interrupted），客户端重新订阅
    app2 = create_app(settings, provider=FakeChatProvider(turn_fn=demo_turn))
    async with (
        app2.router.lifespan_context(app2),
        AsyncClient(transport=ASGITransport(app=app2), base_url="http://t") as client,
    ):
        run = await client.get("/v1/runs/r_dead", headers=headers)
        assert run.status_code == 200
        assert run.json()["status"] == "interrupted"

        buffer = ""
        async with client.stream("GET", "/v1/runs/r_dead/events", headers=headers) as resp:
            assert resp.status_code == 200
            async for chunk in resp.aiter_text():
                buffer += chunk
        assert "event: run.started" in buffer  # 回放已落库事件
        assert "event: run.failed" in buffer  # 合成终态
        assert "interrupted" in buffer


async def test_reconnect_mid_run_with_last_event_id(tmp_path: Path) -> None:
    """活跃 run 中途断开，带 Last-Event-ID 重连仍能拿到终态（不丢 run.completed）。"""
    slow_turn: list[Any] = [TextDelta(f"chunk{i}") for i in range(60)]
    slow_turn.append(StreamEnd("stop", Usage(3, 3)))
    provider = FakeChatProvider(turns=[slow_turn], delay_s=0.02)
    settings = make_settings(tmp_path)
    app = create_app(settings, provider=provider)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        headers = await bootstrap(client)
        session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
        created = await client.post(
            f"/v1/sessions/{session['id']}/runs", json={"input": "慢点"}, headers=headers
        )
        run_id = created.json()["run_id"]
        await asyncio.sleep(0.3)  # 让 run 进行到中途（部分事件已落库）

        first_buffer = ""
        async with client.stream("GET", f"/v1/runs/{run_id}/events", headers=headers) as resp:
            async for chunk in resp.aiter_text():
                first_buffer += chunk
                if "run.started" in first_buffer:
                    break  # 客户端主动断开

        # 重连：从 seq 1 之后继续
        buffer = ""
        async with client.stream(
            "GET",
            f"/v1/runs/{run_id}/events",
            headers={**headers, "Last-Event-ID": "1"},
        ) as resp:
            async for chunk in resp.aiter_text():
                buffer += chunk
        assert "event: run.started" not in buffer  # 不重复回放 seq<=1
        assert "event: message.completed" in buffer  # 终态全文到达
        assert "event: run.completed" in buffer

        # 会话锁已释放：可以继续下一轮
        again = await client.post(
            f"/v1/sessions/{session['id']}/runs", json={"input": "下一轮"}, headers=headers
        )
        assert again.status_code == 202


async def test_shutdown_cancels_active_runs(tmp_path: Path) -> None:
    """优雅停机：活跃 run 被取消并落 cancelled（kill -9 才会留 interrupted）。"""
    slow_turn: list[Any] = [TextDelta(f"c{i}") for i in range(500)]
    slow_turn.append(StreamEnd("stop", Usage(1, 1)))
    provider = FakeChatProvider(turns=[slow_turn], delay_s=0.01)
    settings = make_settings(tmp_path)
    app = create_app(settings, provider=provider)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        headers = await bootstrap(client)
        session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
        created = await client.post(
            f"/v1/sessions/{session['id']}/runs", json={"input": "x"}, headers=headers
        )
        run_id = created.json()["run_id"]
    # lifespan 退出（优雅停机）后：
    conn = sqlite3.connect(str(settings.db_path))
    row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    assert row is not None and row[0] == "cancelled"
