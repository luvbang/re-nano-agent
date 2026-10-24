"""Process configuration. All values come from env vars with the ``AGENTD_`` prefix or ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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

    # 模型接入（OpenAI-compatible 单 provider，M1）
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: float = Field(default=120.0, gt=0)
    llm_retries: int = Field(default=3, ge=0)
    llm_context_window: int = Field(default=128_000, ge=4_096)
    llm_max_output: int = Field(default=4_096, ge=256)

    # 运行时上限（M1）
    run_max_iterations: int = Field(default=8, ge=1)
    run_timeout_s: float = Field(default=600.0, gt=0)
    run_tool_timeout_s: float = Field(default=60.0, gt=0)

    # shell 工具（M2 D4）：默认关闭；开启 = 信任调用方
    run_shell_enabled: bool = False
    run_shell_allowlist: str = ""  # 逗号分隔的命令前缀，如 "git,python -m pytest"
    run_shell_timeout_s: float = Field(default=30.0, gt=0)

    # 平台 API（M3）
    admin_api_key: SecretStr = SecretStr("")  # env 管理员 key（引导用；DB admin scope 亦可）
    # 价格表（M4）：JSON {"模型": {"input": $/1M, "output": $/1M}}；空=不记成本
    llm_price_table: str = ""
    run_global_concurrency: int = Field(default=8, ge=1)
    run_project_concurrency: int = Field(default=4, ge=1)
    ratelimit_global_per_min: int = Field(default=240, ge=1)

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
