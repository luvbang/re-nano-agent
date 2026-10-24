from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agentd.storage.db import Database
from agentd.storage.repositories import (
    ApiKeyRepository,
    ProjectRepository,
    RunRepository,
    SessionRepository,
)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "repo.db")
    database.migrate()
    yield database
    database.close()


async def test_project_and_session_roundtrip(db: Database) -> None:
    projects = ProjectRepository(db)
    project = await projects.create(name="demo", workspace_path="/ws/demo")
    assert project["id"].startswith("p_")
    assert await projects.get_by_name("demo") == project

    sessions = SessionRepository(db)
    session = await sessions.create(
        project_id=project["id"], external_user_id="u_1", metadata={"k": "v"}
    )
    assert session["project_id"] == project["id"]
    assert session["metadata_json"] == '{"k": "v"}'
    assert [row["id"] for row in await sessions.list_by_project(project["id"])] == [session["id"]]


async def test_session_lookup_is_project_scoped(db: Database) -> None:
    projects = ProjectRepository(db)
    owner = await projects.create(name="owner", workspace_path="/ws/a")
    other = await projects.create(name="other", workspace_path="/ws/b")
    session = await SessionRepository(db).create(project_id=owner["id"])

    sessions = SessionRepository(db)
    assert await sessions.get(session["id"], project_id=owner["id"]) is not None
    assert await sessions.get(session["id"], project_id=other["id"]) is None


async def test_api_key_hash_lookup_and_revoke(db: Database) -> None:
    project = await ProjectRepository(db).create(name="demo", workspace_path="/ws/demo")
    keys = ApiKeyRepository(db)
    key = await keys.create(
        project_id=project["id"], key_hash="hash-1", key_prefix="agd_abcd", name="ci"
    )
    assert key["revoked_at"] is None
    assert await keys.revoke(key["id"]) == 1
    revoked = await keys.get_by_hash("hash-1")
    assert revoked is not None and revoked["revoked_at"] is not None


async def test_run_creation_and_recovery(db: Database) -> None:
    project = await ProjectRepository(db).create(name="demo", workspace_path="/ws/demo")
    session = await SessionRepository(db).create(project_id=project["id"])
    runs = RunRepository(db)

    run = await runs.create(session_id=session["id"], project_id=project["id"], model="m")
    assert run["status"] == "queued"

    await runs.set_status(run["id"], "running")
    assert await runs.recover_interrupted() == 1
    recovered = await runs.get(run["id"])
    assert recovered is not None
    assert recovered["status"] == "interrupted"
    assert recovered["finished_at"] is not None


async def test_set_status_rejects_unknown_status(db: Database) -> None:
    with pytest.raises(ValueError, match="unknown run status"):
        await RunRepository(db).set_status("r_1", "exploded")
