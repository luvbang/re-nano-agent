"""API key 服务（M3）：生成、哈希、管理员引导。

- key 明文 ``agd_<32hex>``，服务端只存 sha256（契约 §1）
- 启动引导：``AGENTD_ADMIN_API_KEY`` 环境变量 → 确保 default 项目 + admin scope
  key 行存在（幂等），控制台/管理端点由此 key 鉴权
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from agentd.config import Settings
from agentd.storage.db import Database
from agentd.storage.repositories import ApiKeyRepository, ProjectRepository

ADMIN_SCOPES = "core,admin"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key() -> tuple[str, str, str]:
    """返回 (明文 secret, sha256, 展示前缀)；明文只在创建响应里出现一次。"""
    secret = f"agd_{secrets.token_hex(16)}"
    return secret, hash_key(secret), secret[:8]


async def ensure_default_project(db: Database, settings: Settings) -> dict[str, Any]:
    projects = ProjectRepository(db)
    project = await projects.get_by_name("default")
    if project is None:
        workspace = settings.workspace_root or settings.data_dir / "workspace"
        project = await projects.create(name="default", workspace_path=str(workspace))
    return project


async def ensure_admin_key(db: Database, settings: Settings) -> str | None:
    """按环境变量引导管理员 key；未配置则返回 None（管理端点将不可用）。"""
    project = await ensure_default_project(db, settings)
    raw = settings.admin_api_key.get_secret_value()
    if not raw:
        return None
    keys = ApiKeyRepository(db)
    existing = await keys.get_by_hash(hash_key(raw))
    if existing is None:
        await keys.create(
            project_id=project["id"],
            key_hash=hash_key(raw),
            key_prefix=raw[:8],
            name="admin (env)",
            scopes=ADMIN_SCOPES,
            rate_limit_per_min=600,
        )
    return raw
