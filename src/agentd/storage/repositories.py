"""Repository 层：所有 SQL 只出现在这里，服务层不拼 SQL（M3 迁 Postgres 时只改本文件）。"""

from __future__ import annotations

import json
import secrets
from typing import Any

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

    async def touch(self, session_id: str) -> None:
        await self.db.execute(
            "UPDATE sessions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (session_id,),
        )


class AuditRepository(Repository):
    """审计日志（M4）：关键操作（key/run/session）落库；prompt 全文不入审计。"""

    async def append(
        self,
        *,
        project_id: str | None,
        actor: str,
        action: str,
        target: str | None = None,
        detail: dict[str, Any] | None = None,
        ip: str | None = None,
    ) -> dict[str, Any]:
        audit_id = new_id("a")
        await self.db.execute(
            "INSERT INTO audit_logs (id, project_id, actor, action, target, detail_json, ip)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                project_id,
                actor,
                action,
                target,
                json.dumps(detail or {}, ensure_ascii=False),
                ip,
            ),
        )
        row = await self.db.fetch_one("SELECT * FROM audit_logs WHERE id = ?", (audit_id,))
        assert row is not None
        return row

    async def list_by_project(
        self, project_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return await self.db.fetch_all(
            "SELECT * FROM audit_logs WHERE project_id = ? ORDER BY created_at DESC, id DESC"
            " LIMIT ?",
            (project_id, limit),
        )


class MessageRepository(Repository):
    """会话消息（M2）：seq 在 session 内单调递增，单写者串行化下 max+1 安全。"""

    async def append(
        self,
        session_id: str,
        *,
        role: str,
        content: str | None = None,
        tool_calls_json: str | None = None,
        tool_call_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = await self.db.fetch_one(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM messages WHERE session_id = ?",
            (session_id,),
        )
        assert row is not None
        message_id = new_id("m")
        await self.db.execute(
            "INSERT INTO messages (id, session_id, seq, role, content_json, tool_calls_json,"
            " tool_call_id, meta_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                session_id,
                int(row["next"]),
                role,
                json.dumps(content) if content is not None else None,
                tool_calls_json,
                tool_call_id,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        appended = await self.get(message_id)
        assert appended is not None
        return appended

    async def get(self, message_id: str) -> dict[str, Any] | None:
        return await self.db.fetch_one("SELECT * FROM messages WHERE id = ?", (message_id,))

    async def list_by_session(
        self,
        session_id: str,
        *,
        before_seq: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """按 seq 升序返回；before_seq 提供“游标分页”（取更早的消息）。"""
        if before_seq is None:
            rows = await self.db.fetch_all(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY seq DESC LIMIT ?",
                (session_id, limit),
            )
        else:
            rows = await self.db.fetch_all(
                "SELECT * FROM messages WHERE session_id = ? AND seq < ? ORDER BY seq DESC LIMIT ?",
                (session_id, before_seq, limit),
            )
        return rows[::-1]

    async def count(self, session_id: str) -> int:
        row = await self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?", (session_id,)
        )
        return int(row["n"]) if row else 0


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

    async def recover_interrupted(self) -> int:
        """启动时收敛状态机：上次进程死掉时遗留的 running 全部标记 interrupted。"""
        return await self.db.execute(
            "UPDATE runs SET status = 'interrupted',"
            " finished_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            " WHERE status IN ('queued', 'running')"
        )
