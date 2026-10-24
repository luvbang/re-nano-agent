"""备份/恢复演练（M5 D2 DoD：从备份恢复后会话可用）。"""

from __future__ import annotations

import shlex
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from agentd.storage.db import Database
from agentd.storage.repositories import (
    MessageRepository,
    ProjectRepository,
    SessionRepository,
)

requires_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="需要 bash")


def _find_git_bash() -> str:
    """Windows 上 subprocess 可能拿到 System32 的 WSL bash（Linux！），必须挑 git-bash。"""
    import os

    if os.name != "nt":
        return "bash"
    home = Path.home()
    candidates = [
        Path(os.environ.get("AGENTD_TEST_BASH", "nonexistent")),
        Path("C:/Program Files/Git/bin/bash.exe"),
        Path("C:/Program Files/Git/usr/bin/bash.exe"),
        home / "AppData/Local/Programs/Git/bin/bash.exe",
        home / "AppData/Local/Programs/Git/usr/bin/bash.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "bash"


BASH = _find_git_bash()


def run_script(script: str, **env_vars: str) -> subprocess.CompletedProcess[str]:
    """bash -c 内联环境变量（WSL bash 不透传 Windows env/路径；CI Linux 同样适用）。"""
    python_bin = Path(sys.executable).as_posix()
    if len(python_bin) > 1 and python_bin[1] == ":":
        # git-bash 直接 exec 用 MSYS 风格（D:/x → /d/x）更稳；Linux 上原样
        python_bin = "/" + python_bin[0].lower() + python_bin[2:]
    env_vars.setdefault("PYTHON_BIN", python_bin)
    assignments = " ".join(f"{k}={shlex.quote(v)}" for k, v in env_vars.items())
    return subprocess.run(
        [BASH, "-c", f"{assignments} bash {script}"],
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture
async def data_dir(tmp_path: Path) -> Path:
    """带真实数据的 DATA_DIR：project/session/消息 + workspace 文件。"""
    root = tmp_path / "data"
    root.mkdir()
    db = Database(root / "agentd.db")
    db.migrate()
    project = await ProjectRepository(db).create(name="p", workspace_path=str(root))
    session = await SessionRepository(db).create(
        project_id=str(project["id"]), title="backup-test"
    )
    await MessageRepository(db).append(str(session["id"]), role="user", text="备份前写入")
    db.close()
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("工作区内容", encoding="utf-8")
    return root


@requires_bash
def test_backup_then_restore_recovers_session(tmp_path: Path, data_dir: Path) -> None:
    backup_root = tmp_path / "backups"
    # 备份期间模拟写入中状态：附加 WAL 未合并也能得到一致快照（backup API 保证）
    run = run_script(
        "deploy/backup.sh", DATA_DIR=data_dir.as_posix(), BACKUP_DIR=backup_root.as_posix()
    )
    assert run.returncode == 0, run.stderr
    assert "backup ok" in run.stdout
    stamps = list(backup_root.iterdir())
    assert len(stamps) == 1
    stamp = stamps[0]
    assert (stamp / "agentd.db").exists()
    assert (stamp / "workspace.tar.gz").exists()
    assert (stamp / "SHA256SUMS").exists()

    # “灾难”：删掉数据目录
    shutil.rmtree(data_dir)

    # 恢复到原位置
    run = run_script(
        "deploy/restore.sh", DATA_DIR=data_dir.as_posix(), BACKUP_DIR=stamp.as_posix()
    )
    assert run.returncode == 0, run.stderr

    # 会话可用：直接读库验证
    conn = sqlite3.connect(data_dir / "agentd.db")
    roles = [r[0] for r in conn.execute("SELECT role FROM messages ORDER BY seq")]
    conn.close()
    assert roles == ["user"]
    assert (data_dir / "workspace" / "notes.txt").read_text(encoding="utf-8") == "工作区内容"


@requires_bash
def test_backup_rotation_keeps_last_n(tmp_path: Path, data_dir: Path) -> None:
    backup_root = tmp_path / "backups"
    for _ in range(4):
        run = run_script(
            "deploy/backup.sh",
            DATA_DIR=data_dir.as_posix(),
            BACKUP_DIR=backup_root.as_posix(),
            KEEP="2",
        )
        assert run.returncode == 0, run.stderr
    # 同秒内多次备份可能同名目录；轮转后总数不超过 KEEP
    assert len(list(backup_root.iterdir())) <= 2


@requires_bash
def test_restore_rejects_missing_backup(tmp_path: Path) -> None:
    empty = tmp_path / "empty-backup"
    empty.mkdir()
    run = run_script(
        "deploy/restore.sh", DATA_DIR=(tmp_path / "data").as_posix(), BACKUP_DIR=empty.as_posix()
    )
    assert run.returncode != 0
    assert "agentd.db" in run.stderr
