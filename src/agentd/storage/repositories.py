"""Repository 层：所有 SQL 只出现在这里，服务层不拼 SQL（M3 迁 Postgres 时只改本文件）。"""

from __future__ import annotations

import json
import secrets
from typing import Any, cast

from agentd.providers.base import ChatMessage, ToolCallWire
from agentd.storage.db import Database


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db


class ProjectRepository(Repository):
    async def create(self, *, name: str, workspace_path: str) -> dict[str, Any]:
        project_id = new_id("p")
        await self.db.execute(
            "INSERT INTO projects (id, name, workspace_path) VALUES (?, ?, ?)",
            (project_id, name, workspace_path),
        )
        row = await self.get(project_id)
        assert row is not None
        return row

    async def get(self, project_id: str) -> dict[str, Any] | None:
        return await self.db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))

    async def get_by_name(self, name: str) -> dict[str, Any] | None:
        return await self.db.fetch_one("SELECT * FROM projects WHERE name = ?", (name,))

    async def get_or_create(self, *, name: str, workspace_path: str) -> dict[str, Any]:
        row = await self.get_by_name(name)
        if row is not None:
            return row
        return await self.create(name=name, workspace_path=workspace_path)


class ApiKeyRepository(Repository):
    async def create(
        self,
        *,
        project_id: str,
        key_hash: str,
        key_prefix: str,
        name: str | None = None,
        scopes: str = "core",
        rate_limit_per_min: int = 60,
    ) -> dict[str, Any]:
        key_id = new_id("k")
        await self.db.execute(
            "INSERT INTO api_keys (id, project_id, key_hash, key_prefix, name, scopes,"
            " rate_limit_per_min) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key_id, project_id, key_hash, key_prefix, name, scopes, rate_limit_per_min),
        )
        row = await self.get_by_hash(key_hash)
        assert row is not None
        return row

    async def get_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        return await self.db.fetch_one("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,))

    async def revoke(self, key_id: str) -> int:
        return await self.db.execute(
            "UPDATE api_keys SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            " WHERE id = ? AND revoked_at IS NULL",
            (key_id,),
        )


class SessionRepository(Repository):
    async def create(
        self,
        *,
        project_id: str,
        external_user_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = new_id("s")
        await self.db.execute(
            "INSERT INTO sessions (id, project_id, external_user_id, title, metadata_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_id, project_id, external_user_id, title, json.dumps(metadata or {})),
        )
        row = await self.get(session_id, project_id=project_id)
        assert row is not None
        return row

    async def get(self, session_id: str, *, project_id: str) -> dict[str, Any] | None:
        # 跨 project 一律查不到（调用方转 404，不泄漏存在性）
        return await self.db.fetch_one(
            "SELECT * FROM sessions WHERE id = ? AND project_id = ?", (session_id, project_id)
        )

    async def list_by_project(
        self, project_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        return await self.db.fetch_all(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )

    async def get_by_title(self, project_id: str, title: str) -> dict[str, Any] | None:
        return await self.db.fetch_one(
            "SELECT * FROM sessions WHERE project_id = ? AND title = ? ORDER BY created_at LIMIT 1",
            (project_id, title),
        )

    async def get_or_create_by_title(
        self, project_id: str, title: str, *, external_user_id: str | None = None
    ) -> dict[str, Any]:
        row = await self.get_by_title(project_id, title)
        if row is not None:
            return row
        return await self.create(
            project_id=project_id, title=title, external_user_id=external_user_id
        )

    async def touch(self, session_id: str) -> None:
        await self.db.execute(
            "UPDATE sessions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (session_id,),
        )


class MessageRepository(Repository):
    """会话消息（模型回放的唯一真相）。content_json 存 ``{"text": ...}``，为多模态块预留。"""

    async def append(
        self,
        session_id: str,
        *,
        role: str,
        text: str | None = None,
        tool_calls: list[ToolCallWire] | None = None,
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        assert role in ("user", "assistant", "tool", "summary"), f"role {role} 不落库"
        # seq 分配与写入都在 Database 单锁内完成（fetch + execute 各持锁一次，
        # 但单进程内所有调用都经同一把锁串行化，无竞态）
        row = await self.db.fetch_one(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM messages WHERE session_id = ?",
            (session_id,),
        )
        seq = int(row["max_seq"]) + 1 if row else 1
        message_id = new_id("m")
        await self.db.execute(
            "INSERT INTO messages (id, session_id, seq, role, content_json, tool_calls_json,"
            " tool_call_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                session_id,
                seq,
                role,
                json.dumps({"text": text}) if text is not None else None,
                json.dumps(tool_calls) if tool_calls else None,
                tool_call_id,
            ),
        )
        result = await self.get(message_id)
        assert result is not None
        return result

    async def get(self, message_id: str) -> dict[str, Any] | None:
        return await self.db.fetch_one("SELECT * FROM messages WHERE id = ?", (message_id,))

    async def list_for_session(
        self, session_id: str, *, limit: int = 200, before_seq: int | None = None
    ) -> list[dict[str, Any]]:
        """按 seq 升序返回（模型重放顺序）；before_seq 用于分页取更早的消息。"""
        if before_seq is None:
            rows = await self.db.fetch_all(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY seq DESC LIMIT ?",
                (session_id, limit),
            )
            return list(reversed(rows))
        rows = await self.db.fetch_all(
            "SELECT * FROM messages WHERE session_id = ? AND seq < ? ORDER BY seq DESC LIMIT ?",
            (session_id, before_seq, limit),
        )
        return list(reversed(rows))


def rows_to_chat_messages(rows: list[dict[str, Any]]) -> list[ChatMessage]:
    """DB 行 → Provider wire 消息（assistant 的 tool_calls / tool 的 tool_call_id 还原）。"""
    wire: list[ChatMessage] = []
    for row in rows:
        text = None
        if row["content_json"]:
            payload = json.loads(row["content_json"])
            text = payload.get("text")
        message = ChatMessage(role=row["role"], content=text)
        if row["tool_calls_json"]:
            message["tool_calls"] = cast(
                list[ToolCallWire], json.loads(row["tool_calls_json"])
            )
        if row["tool_call_id"]:
            message["tool_call_id"] = row["tool_call_id"]
        wire.append(message)
    return wire


class RunRepository(Repository):
    TERMINAL_STATUSES = ("completed", "failed", "cancelled", "interrupted")

    async def create(
        self, *, session_id: str, project_id: str, model: str | None = None
    ) -> dict[str, Any]:
        run_id = new_id("r")
        await self.db.execute(
            "INSERT INTO runs (id, session_id, project_id, status, model)"
            " VALUES (?, ?, ?, 'queued', ?)",
            (run_id, session_id, project_id, model),
        )
        row = await self.get(run_id)
        assert row is not None
        return row

    async def get(self, run_id: str) -> dict[str, Any] | None:
        return await self.db.fetch_one("SELECT * FROM runs WHERE id = ?", (run_id,))

    async def set_status(self, run_id: str, status: str) -> int:
        if status not in ("queued", "running", *self.TERMINAL_STATUSES):
            raise ValueError(f"unknown run status: {status}")
        return await self.db.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))

    async def finish(
        self,
        run_id: str,
        status: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: dict[str, Any] | None = None,
    ) -> int:
        """写终态 + 用量 + 结束时间（错误信息仅在失败/取消时携带）。"""
        if status not in self.TERMINAL_STATUSES:
            raise ValueError(f"finish 只接受终态，收到 {status}")
        return await self.db.execute(
            "UPDATE runs SET status = ?, input_tokens = ?, output_tokens = ?, error_json = ?,"
            " finished_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (status, input_tokens, output_tokens, json.dumps(error) if error else None, run_id),
        )

    async def recover_interrupted(self) -> int:
        """启动时收敛状态机：上次进程死掉时遗留的 running 全部标记 interrupted。"""
        return await self.db.execute(
            "UPDATE runs SET status = 'interrupted',"
            " finished_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            " WHERE status IN ('queued', 'running')"
        )


class ToolCallRepository(Repository):
    async def record(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        name: str,
        args_json: str,
        result_preview: str | None,
        status: str,
        duration_ms: int,
    ) -> None:
        await self.db.execute(
            "INSERT INTO tool_calls (id, run_id, tool_call_id, name, args_json, result_preview,"
            " status, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("tc"),
                run_id,
                tool_call_id,
                name,
                args_json,
                (result_preview or "")[:500] or None,
                status if status in ("ok", "error", "timeout") else "error",
                duration_ms,
            ),
        )

    async def list_by_run(self, run_id: str) -> list[dict[str, Any]]:
        return await self.db.fetch_all(
            "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY created_at, id", (run_id,)
        )


class RunEventRepository(Repository):
    """控制类事件（delta/reasoning.delta 不入库），SSE 回放的真相源。"""

    async def append(self, run_id: str, seq: int, type_: str, payload: dict[str, Any]) -> None:
        await self.db.execute(
            "INSERT INTO run_events (run_id, seq, type, payload_json) VALUES (?, ?, ?, ?)",
            (run_id, seq, type_, json.dumps(payload, ensure_ascii=False)),
        )

    async def list_after(self, run_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        return await self.db.fetch_all(
            "SELECT * FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, after_seq),
        )

    async def max_seq(self, run_id: str) -> int:
        row = await self.db.fetch_one(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM run_events WHERE run_id = ?",
            (run_id,),
        )
        return int(row["max_seq"]) if row else 0


class IdempotencyRepository(Repository):
    """创建 run 的 Idempotency-Key（5 分钟窗口）。"""

    WINDOW_MINUTES = 5

    async def find_run(self, key: str) -> str | None:
        row = await self.db.fetch_one(
            "SELECT run_id FROM idempotency_keys WHERE key = ?"
            " AND created_at > datetime('now', ?)",
            (key, f"-{self.WINDOW_MINUTES} minutes"),
        )
        return str(row["run_id"]) if row else None

    async def bind(self, key: str, *, run_id: str, session_id: str) -> None:
        # 顺手清理过期键（单实例量级小，无需独立任务）
        await self.db.execute(
            "DELETE FROM idempotency_keys WHERE created_at < datetime('now', ?)",
            (f"-{2 * self.WINDOW_MINUTES} minutes",),
        )
        await self.db.execute(
            "INSERT INTO idempotency_keys (key, run_id, session_id) VALUES (?, ?, ?)",
            (key, run_id, session_id),
        )


class UsageRepository(Repository):
    async def record(
        self,
        *,
        project_id: str,
        run_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        await self.db.execute(
            "INSERT INTO usage_records (id, project_id, run_id, model, input_tokens, output_tokens)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (new_id("u"), project_id, run_id, model, input_tokens, output_tokens),
        )

    async def totals_by_project(self, project_id: str) -> dict[str, Any]:
        row = await self.db.fetch_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(input_tokens),0) AS input_tokens,"
            " COALESCE(SUM(output_tokens),0) AS output_tokens"
            " FROM usage_records WHERE project_id = ?",
            (project_id,),
        )
        return row or {"n": 0, "input_tokens": 0, "output_tokens": 0}
