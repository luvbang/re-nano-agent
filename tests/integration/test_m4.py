"""M4 集成测试：SDK 全流程（同步+异步，真 HTTP）、审计、摘要压缩、日志脱敏。

SDK 测试用真实 uvicorn 起在随机端口（httpx ASGITransport 是 async-only 的，
同步 SDK 打不了；这也是"外部人员 30 分钟接入"最接近真实的路径）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agentd import AgentdError, AuthenticationError, Client
from agentd import AsyncClient as AgentdAsyncClient
from agentd.config import Settings
from agentd.log import redact
from agentd.main import create_app

ADMIN_KEY = "agd_" + "m4" * 2 + "_admin_" + "0123456789"  # fake 值，非真实凭据


def make_settings(tmp_path: Path, *, token_budget: int = 24_000) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path,
        log_level="WARNING",
        log_json=False,
        admin_api_key=ADMIN_KEY,
        context_token_budget=token_budget,
    )


@pytest.fixture
async def app(tmp_path: Path) -> AsyncIterator[FastAPI]:
    application = create_app(make_settings(tmp_path))
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def sdk_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_KEY}"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _LiveServer:
    """测试专用：真实 uvicorn 起在随机端口，同步/异步 SDK 都打真 HTTP。"""

    def __init__(self, tmp_path: Path) -> None:
        self.port = _free_port()
        self.app = create_app(make_settings(tmp_path))
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> _LiveServer:
        self.thread.start()
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return self
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("test server 未在超时内启动")

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[_LiveServer]:
    with _LiveServer(tmp_path) as server:
        yield server


# ---------- SDK 同步全流程（真 HTTP） ----------


def test_sdk_sync_full_flow(live_server: _LiveServer) -> None:
    with Client(base_url=live_server.base_url, api_key=ADMIN_KEY) as client:
        session = client.sessions.create(title="SDK 会话")
        assert session.id.startswith("s_")

        # 流式 + 工具回路
        with client.runs.stream(session.id, input="现在几点了？") as stream:
            events = list(stream)
        types = [type(e).__name__ for e in events]
        assert "RunStarted" in types and "ToolStarted" in types
        assert types[-1] == "RunCompleted"
        assert stream.result is not None and stream.result.status == "completed"
        assert stream.result.input_tokens > 0

        # 非流式查询
        from agentd.sdk.streaming import RunStarted

        run_id = next(e.run_id for e in events if isinstance(e, RunStarted))
        run = client.runs.get(run_id)
        assert run.status == "completed"
        history = client.sessions.messages(session.id)
        assert [m.role for m in history] == ["user", "assistant", "tool", "assistant"]

        # usage
        usage = client.usage.get(from_="2000-01-01", to="2999-01-01", group_by="model")
        assert sum(i.runs for i in usage.items) >= 1

        # keys
        created = client.keys.create(name="sdk-created")
        assert created.secret.startswith("agd_")
        assert any(k.id == created.key.id for k in client.keys.list())
        client.keys.revoke(created.key.id)
        assert all(k.id != created.key.id or k.revoked_at for k in client.keys.list())


def test_sdk_error_types(live_server: _LiveServer) -> None:
    with (
        Client(base_url=live_server.base_url, api_key="agd_" + "wrong" * 4) as client,
        pytest.raises(AuthenticationError),
    ):
        client.sessions.list()
    with Client(base_url=live_server.base_url, api_key=ADMIN_KEY) as client:
        with pytest.raises(AgentdError) as exc_info:
            client.sessions.get("s_none")
        assert exc_info.value.code == "not_found"


async def test_sdk_async_stream(live_server: _LiveServer) -> None:
    async with AgentdAsyncClient(base_url=live_server.base_url, api_key=ADMIN_KEY) as client:
        session = await client.sessions.create(title="异步会话")
        stream = await client.runs.stream_async(session.id, input="你好")
        async with stream:
            types = []
            async for event in stream:
                types.append(type(event).__name__)
        assert types[-1] == "RunCompleted"
        assert stream.result is not None


# ---------- 审计 ----------


async def test_audit_trail(client: AsyncClient) -> None:
    resp = await client.post("/v1/sessions", json={"title": "审计"}, headers=sdk_headers())
    session_id = resp.json()["id"]
    resp = await client.post(
        f"/v1/sessions/{session_id}/runs", json={"input": "你好"}, headers=sdk_headers()
    )
    run_id = resp.json()["run_id"]
    resp = await client.post("/v1/admin/keys", json={"name": "审计"}, headers=sdk_headers())
    key_id = resp.json()["key"]["id"]
    await client.delete(f"/v1/admin/keys/{key_id}", headers=sdk_headers())
    for _ in range(100):
        run = (await client.get(f"/v1/runs/{run_id}", headers=sdk_headers())).json()
        if run["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.05)

    actions: list[str] = []
    for _ in range(20):
        resp = await client.get("/v1/admin/audit", headers=sdk_headers())
        actions = [row["action"] for row in resp.json()]
        if "key.revoked" in actions:
            break
        await asyncio.sleep(0.05)
    assert "session.created" in actions
    assert "run.created" in actions
    assert "key.created" in actions
    assert "key.revoked" in actions


async def test_tool_calls_recorded(app: FastAPI, client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/sessions", json={"title": "工具审计"}, headers=sdk_headers()
    )
    session_id = resp.json()["id"]
    resp = await client.post(
        f"/v1/sessions/{session_id}/runs",
        json={"input": "现在几点了？"},
        headers=sdk_headers(),
    )
    run_id = resp.json()["run_id"]
    for _ in range(100):
        run = (await client.get(f"/v1/runs/{run_id}", headers=sdk_headers())).json()
        if run["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.05)
    db = app.state.db
    rows = await db.fetch_all("SELECT * FROM tool_calls WHERE run_id = ?", (run_id,))
    assert len(rows) == 1
    assert rows[0]["name"] == "get_time"
    assert rows[0]["status"] == "ok"


# ---------- 摘要压缩 ----------


async def test_summary_compression(tmp_path: Path) -> None:
    """超小预算 + summarizer：旧轮次被压成 summary 落库，上下文 = summary + 保留轮。"""
    from agentd.services.conversation import ConversationService
    from agentd.storage.db import Database
    from agentd.storage.repositories import ProjectRepository, SessionRepository

    db = Database(tmp_path / "t.db")
    db.migrate()
    conv = ConversationService(db, token_budget=1)  # 直接构造，绕过 Settings 下限
    project = await ProjectRepository(db).create(name="p", workspace_path=str(tmp_path))
    session = await SessionRepository(db).create(project_id=project["id"])
    for i in range(2):
        await conv.persist_exchange(
            str(session["id"]),
            [
                {"role": "user", "content": f"问题{i}" * 50},
                {"role": "assistant", "content": f"回答{i}" * 50},
            ],
        )
    calls: list[str] = []

    async def summarizer(transcript: str) -> str:
        calls.append(transcript)
        return "压缩摘要：用户问了两个问题，助手均已作答。"

    history = await conv.load_history(str(session["id"]), summarizer=summarizer)
    assert len(calls) == 1
    assert history[0]["role"] == "system"
    assert "压缩摘要" in (history[0]["content"] or "")
    assert any(m["role"] == "user" for m in history[1:])
    rows = await db.fetch_all(
        "SELECT * FROM messages WHERE session_id = ? AND role = 'summary'",
        (str(session["id"]),),
    )
    assert len(rows) == 1
    # 再次加载：活历史在 summary 之后（即使为空也保留 summary 头）
    history2 = await conv.load_history(str(session["id"]), summarizer=summarizer)
    assert len(calls) == 1
    assert history2[0]["role"] == "system"
    db.close()


async def test_summary_without_summarizer_falls_back(tmp_path: Path) -> None:
    from agentd.services.conversation import ConversationService
    from agentd.storage.db import Database
    from agentd.storage.repositories import ProjectRepository, SessionRepository

    db = Database(tmp_path / "t.db")
    db.migrate()
    conv = ConversationService(db, token_budget=1)
    project = await ProjectRepository(db).create(name="p", workspace_path=str(tmp_path))
    session = await SessionRepository(db).create(project_id=project["id"])
    for i in range(3):
        await conv.persist_exchange(
            str(session["id"]),
            [
                {"role": "user", "content": f"问题{i}" * 50},
                {"role": "assistant", "content": f"回答{i}" * 50},
            ],
        )
    history = await conv.load_history(str(session["id"]))  # 无 summarizer
    assert not any(
        m["role"] == "system" and "摘要" in (m.get("content") or "") for m in history
    )
    db.close()


# ---------- 日志脱敏 ----------


# 脱敏测试用的 fake 凭据（拼接构造，非真实 secret）
FAKE_KEY = "agd_" + "abcd" * 4
FAKE_TOKEN = "sk-" + "secret" * 3
FAKE_SECRET = "super-" + "secret" * 2
FAKE_SESSION = "t-" + "123"


def test_log_redaction() -> None:
    line = json.dumps(
        {
            "msg": f"login with {FAKE_KEY} done",
            "auth": f"Bearer {FAKE_TOKEN}",
            "nested": json.dumps(
                {"api_key": FAKE_SECRET, "token": FAKE_SESSION}
            ),
            "safe": "keep-me",
        },
        ensure_ascii=False,
    )
    out = redact(line)
    assert FAKE_KEY not in out
    assert "agd_***" in out
    assert FAKE_TOKEN not in out
    assert FAKE_SECRET not in out
    assert FAKE_SESSION not in out
    assert "keep-me" in out  # 非敏感内容不受影响
    assert "Bearer ***" in out


def test_log_formatter_redacts_json_output() -> None:
    """JsonFormatter 输出层脱敏：record 本体不变，序列化后的 JSON 擦掉敏感串。"""
    import io

    from agentd.log import JsonFormatter

    stream = io.StringIO()
    logger = logging.getLogger("agentd.test.redact")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    old_handlers, old_level, old_propagate = logger.handlers[:], logger.level, logger.propagate
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logger.info("connect with %s", "agd_sensitive_value_99")
    finally:
        logger.handlers, logger.level, logger.propagate = old_handlers, old_level, old_propagate
    output = stream.getvalue()
    assert "agd_sensitive_value_99" not in output
    assert "agd_***" in output
