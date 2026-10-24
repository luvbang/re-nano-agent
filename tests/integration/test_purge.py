"""purge 命令测试（go-live 数据保留项）：级联删除、审计保留、其他 project 不受影响。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentd.cli import main as cli_main
from agentd.config import Settings, get_settings
from agentd.storage.db import Database
from agentd.storage.repositories import (
    MessageRepository,
    ProjectRepository,
    SessionRepository,
)


async def seed(tmp_path: Path) -> tuple[str, str]:
    """建两个 project：A 有消息+审计挂钩，B 只有空壳。返回 (A_id, B_id)。"""
    settings = Settings(
        env="test", data_dir=tmp_path, log_level="WARNING", log_json=False
    )
    db = Database(settings.db_path or tmp_path / "agentd.db")
    db.migrate()
    a = await ProjectRepository(db).create(name="A", workspace_path="/tmp/a")
    b = await ProjectRepository(db).create(name="B", workspace_path="/tmp/b")
    session = await SessionRepository(db).create(project_id=str(a["id"]))
    await MessageRepository(db).append(str(session["id"]), role="user", text="数据")
    await db.execute(
        "INSERT INTO audit_logs (id, project_id, actor, action)"
        " VALUES ('a_1', ?, 'test', 'purge.proof')",
        (str(a["id"]),),
    )
    db.close()
    return str(a["id"]), str(b["id"])


async def run_purge(tmp_path: Path, *extra: str) -> tuple[int, Database]:
    """让 CLI 的 get_settings 指向 tmp 数据目录后执行命令，返回 (rc, 新 db 句柄)。"""
    import os

    old = os.environ.get("AGENTD_DATA_DIR")
    os.environ["AGENTD_DATA_DIR"] = str(tmp_path)
    get_settings.cache_clear()
    try:
        # cli 内部 asyncio.run 不能在测试事件循环里执行 → 丢到无循环线程
        rc = await asyncio.to_thread(cli_main, ["purge", *extra])
    finally:
        get_settings.cache_clear()
        if old is None:
            os.environ.pop("AGENTD_DATA_DIR", None)
        else:
            os.environ["AGENTD_DATA_DIR"] = old
    db = Database(tmp_path / "agentd.db")
    return rc, db


async def test_purge_plan_without_yes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_a, _b = await seed(tmp_path)
    rc, db = await run_purge(tmp_path, "--project", project_a)
    assert rc == 2
    assert "--yes" in capsys.readouterr().out
    db.close()


async def test_purge_deletes_cascade_keeps_audit_and_others(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_a, project_b = await seed(tmp_path)
    rc, db = await run_purge(tmp_path, "--project", project_a, "--yes")
    assert rc == 0
    assert "purged" in capsys.readouterr().out
    assert await ProjectRepository(db).get(project_a) is None
    assert await ProjectRepository(db).get(project_b) is not None
    messages = await db.fetch_one("SELECT COUNT(*) n FROM messages")
    assert messages is not None and int(messages["n"]) == 0
    audit = await db.fetch_one("SELECT project_id FROM audit_logs WHERE id = 'a_1'")
    assert audit is not None and audit["project_id"] is None  # 审计保留但脱钩
    db.close()


async def test_purge_unknown_project(tmp_path: Path) -> None:
    _a, _b = await seed(tmp_path)
    rc, db = await run_purge(tmp_path, "--project", "p_nope")
    assert rc == 1
    db.close()
