from __future__ import annotations

from pathlib import Path

from agentd.config import Settings


def test_paths_are_resolved_and_derive_from_data_dir(tmp_path: Path) -> None:
    settings = Settings(env="test", data_dir=tmp_path)
    assert settings.data_dir.is_absolute()
    assert settings.db_path == tmp_path / "agentd.db"
    assert settings.workspace_root == tmp_path / "workspace"


def test_env_prefix_override(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENTD_DATA_DIR", str(tmp_path / "custom"))
    monkeypatch.setenv("AGENTD_LOG_JSON", "false")
    monkeypatch.setenv("AGENTD_PORT", "9001")
    settings = Settings()
    assert settings.data_dir == (tmp_path / "custom").resolve()
    assert settings.log_json is False
    assert settings.port == 9001


def test_ensure_dirs_creates_data_and_workspace(tmp_path: Path) -> None:
    settings = Settings(env="test", data_dir=tmp_path / "runtime")
    settings.ensure_dirs()
    assert (tmp_path / "runtime").is_dir()
    assert (tmp_path / "runtime" / "workspace").is_dir()
