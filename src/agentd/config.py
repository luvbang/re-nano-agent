"""Process configuration. All values come from env vars with the ``AGENTD_`` prefix or ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    """Runtime settings.

    Paths are resolved once at construction so that relative env values (``./var``)
    behave the same regardless of the current working directory later on.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    log_json: bool = True

    data_dir: Path = Path("var")
    db_path: Path | None = None
    workspace_root: Path | None = None
    auto_migrate: bool = True

    sqlite_busy_timeout_ms: int = Field(default=5000, ge=0)
    request_id_header: str = "X-Request-Id"

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        self.data_dir = self.data_dir.expanduser().resolve()
        self.db_path = (self.db_path or self.data_dir / "agentd.db").expanduser().resolve()
        workspace = self.workspace_root or self.data_dir / "workspace"
        self.workspace_root = workspace.expanduser().resolve()
        return self

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        assert self.workspace_root is not None
        self.workspace_root.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
