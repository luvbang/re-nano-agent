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
}


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def test_migrate_creates_schema(db: Database) -> None:
    applied = db.migrate()
    assert applied == ["001_init", "002_idempotency"]

    rows = db.query_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    assert {row["name"] for row in rows} >= EXPECTED_TABLES
    assert db.applied_versions() == ["001_init", "002_idempotency"]


def test_migrate_is_idempotent(db: Database) -> None:
    db.migrate()
    assert db.migrate() == []
    assert db.applied_versions() == ["001_init", "002_idempotency"]


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
