"""SQLite 连接、单写者与迁移。

约束（docs/architecture.md §5）：
- 单连接 + 一把 asyncio.Lock：所有 DB 调用串行化并跑在 ``asyncio.to_thread``，
  彻底避免 ``database is locked`` 与跨线程使用同一连接的问题。
- WAL + busy_timeout：崩溃恢复友好、外部进程（备份）读取互不阻塞。
- 迁移幂等：``schema_version`` 记录已应用版本，重复执行为空操作。
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_VERSION_RE = re.compile(r"^[0-9A-Za-z_]+$")

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""


class Database:
    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    # ---------- lifecycle ----------

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self.path,
                timeout=self.busy_timeout_ms / 1000,
                isolation_level=None,  # 显式事务，避免隐式 BEGIN 与迁移脚本冲突
                check_same_thread=False,  # 实际调用被 _lock 串行化到单线程语义
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            # busy_timeout 由 connect(timeout=…) 设置（同一 busy handler），无需再发 PRAGMA
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ---------- migrations（同步；启动阶段在 to_thread 里跑） ----------

    def migrate(self) -> list[str]:
        """应用未执行的迁移，返回本次应用的版本列表；重复调用返回空列表。"""
        conn = self.connect()
        conn.execute(_SCHEMA_VERSION_DDL)
        applied = {row["version"] for row in conn.execute("SELECT version FROM schema_version")}
        newly_applied: list[str] = []
        for script_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = script_path.stem
            if version in applied:
                continue
            if not _VERSION_RE.match(version):
                raise RuntimeError(f"invalid migration name: {script_path.name}")
            sql = script_path.read_text(encoding="utf-8")
            statement = (
                "BEGIN;\n"
                f"{sql}\n"
                f"INSERT INTO schema_version(version, applied_at) VALUES ('{version}', "
                "strftime('%Y-%m-%dT%H:%M:%fZ','now'));\n"
                "COMMIT;"
            )
            try:
                conn.executescript(statement)
            except sqlite3.Error:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                logger.exception("migration.failed", extra={"version": version})
                raise
            newly_applied.append(version)
            logger.info("migration.applied", extra={"version": version})
        return newly_applied

    def applied_versions(self) -> list[str]:
        conn = self.connect()
        conn.execute(_SCHEMA_VERSION_DDL)
        rows = conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
        return [row["version"] for row in rows]

    # ---------- 同步实现（被 to_thread 调用；勿在事件循环里直接使用） ----------

    def query_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        conn = self.connect()
        return [dict(row) for row in conn.execute(sql, params)]

    def execute_sync(self, sql: str, params: Sequence[Any] = ()) -> int:
        conn = self.connect()
        cursor = conn.execute(sql, params)
        return max(int(cursor.rowcount), 0)

    # ---------- 异步 API（业务层唯一入口） ----------

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(self.query_all, sql, params)

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = await self.fetch_all(sql, params)
        return rows[0] if rows else None

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        async with self._lock:
            return await asyncio.to_thread(self.execute_sync, sql, params)
