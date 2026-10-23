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
