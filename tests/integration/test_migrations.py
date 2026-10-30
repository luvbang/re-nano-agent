from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from agentd.storage.db import Database

EXPECTED_TABLES = {
    "projects",
    "api_keys",
    "sessions",
    "messages",
    "runs",
    "run_events",
    "tool_calls",
    "usage_records",
    "audit_logs",
    "schema_version",
    "idempotency_keys",
    "memories",
}

ALL_MIGRATIONS = ["001_init", "002_idempotency", "003_memories", "004_memories_fk"]


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def test_migrate_creates_schema(db: Database) -> None:
    applied = db.migrate()
    assert applied == ALL_MIGRATIONS

    rows = db.query_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    assert {row["name"] for row in rows} >= EXPECTED_TABLES
    assert db.applied_versions() == ALL_MIGRATIONS


def test_migrate_is_idempotent(db: Database) -> None:
    db.migrate()
    assert db.migrate() == []
    assert db.applied_versions() == ALL_MIGRATIONS


def test_wal_and_foreign_keys_enabled(db: Database) -> None:
    conn = db.connect()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_run_status_check_constraint(db: Database) -> None:
    db.migrate()
    db.execute_sync(
        "INSERT INTO projects (id, name, workspace_path) VALUES ('p_1', 'demo', '/tmp/ws')"
    )
    db.execute_sync(
        "INSERT INTO sessions (id, project_id) VALUES ('s_1', 'p_1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute_sync(
            "INSERT INTO runs (id, session_id, project_id, status)"
            " VALUES ('r_1', 's_1', 'p_1', 'bogus')"
        )


def test_memories_fk_has_on_delete_cascade(db: Database) -> None:
    """004 重建表后 memories.project_id 必须带 ON DELETE CASCADE（003 曾漏）。"""
    db.migrate()
    fks = db.query_all("PRAGMA foreign_key_list(memories)")
    project_fks = [row for row in fks if row["table"] == "projects"]
    assert project_fks, fks
    assert project_fks[0]["on_delete"] == "CASCADE"


def test_memories_index_survives_rebuild(db: Database) -> None:
    """重建表会连带 DROP 索引，004 末尾必须重建（否则 Dream/注入查询退化）。"""
    db.migrate()
    rows = db.query_all(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'memories'"
    )
    assert "idx_memories_project_active" in {row["name"] for row in rows}


def test_memories_cascade_actually_deletes(db: Database) -> None:
    """行为验证：删 project 时记忆被级联清掉，不再抛 FK 错误。"""
    db.migrate()
    db.execute_sync(
        "INSERT INTO projects (id, name, workspace_path) VALUES ('p_1', 'demo', '/tmp/ws')"
    )
    db.execute_sync(
        "INSERT INTO memories (id, project_id, content) VALUES ('mem_1', 'p_1', 'x')"
    )
    assert db.execute_sync("DELETE FROM projects WHERE id = 'p_1'") == 1
    assert db.query_all("SELECT id FROM memories") == []
