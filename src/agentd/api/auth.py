"""API 鉴权（M3 D1）：Bearer key → project；admin 双通道（env 管理员 key / DB admin scope）。

- key 只存 sha256 + 前 12 位 prefix；明文仅在创建响应里出现一次
- 每个请求都实时查库校验（无缓存）→ 撤销立即生效
- 跨 project 访问一律 404（不泄漏存在性），由 Repository 的 project 过滤保证
"""

from __future__ import annotations

import hashlib
import math
import secrets
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Request

from agentd.api.deps import DbDep, SettingsDep
from agentd.api.errors import AppError, ErrorCode
from agentd.storage.db import Database
from agentd.storage.repositories import ApiKeyRepository, ProjectRepository

KEY_PREFIX = "agd_"


@dataclass(frozen=True, slots=True)
class AuthContext:
    key: dict[str, Any]  # api_keys 行
    project: dict[str, Any]  # projects 行


def generate_api_key() -> tuple[str, str, str]:
    """返回 (明文 key, sha256 hex, 展示用前缀)。明文不落库。"""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, hash_key(key), key[:12]


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _parse_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(ErrorCode.UNAUTHORIZED, "缺少 Authorization: Bearer <key>")
    key = authorization[len("Bearer ") :].strip()
    if not key:
        raise AppError(ErrorCode.UNAUTHORIZED, "Bearer key 为空")
    return key


async def _load_key(db: Database, key: str) -> dict[str, Any]:
    row = await ApiKeyRepository(db).get_by_hash(hash_key(key))
    if row is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "key 不存在")
    if row["revoked_at"] is not None:
        raise AppError(ErrorCode.UNAUTHORIZED, "key 已撤销")
    return row


async def _project_of(db: Database, key_row: dict[str, Any]) -> dict[str, Any]:
    project = await ProjectRepository(db).get(str(key_row["project_id"]))
    if project is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "key 所属 project 不存在")
    return project


async def require_project(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthContext:
    key = _parse_bearer(authorization)
    key_row = await _load_key(db, key)
    return AuthContext(key=key_row, project=await _project_of(db, key_row))


async def require_admin(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthContext:
    key = _parse_bearer(authorization)
    env_admin = settings.admin_api_key.get_secret_value()
    if env_admin and secrets.compare_digest(key, env_admin):
        # env 管理员不在 DB 里：管理操作本身不依赖 project，给个占位上下文
        row = await ApiKeyRepository(db).get_by_hash(hash_key(key))
        if row is not None and row["revoked_at"] is None:
            return AuthContext(key=row, project=await _project_of(db, row))
        return AuthContext(
            key={"id": "env_admin", "scopes": "admin"},
            project={"id": "env_admin", "name": "env-admin"},
        )
    key_row = await _load_key(db, key)
    if "admin" not in str(key_row["scopes"] or "").split(","):
        raise AppError(ErrorCode.FORBIDDEN, "需要管理员权限")
    return AuthContext(key=key_row, project=await _project_of(db, key_row))


ProjectAuth = Annotated[AuthContext, Depends(require_project)]
AdminAuth = Annotated[AuthContext, Depends(require_admin)]


async def enforce_rate_limit(
    request: Request, auth: ProjectAuth
) -> AuthContext:
    """per-key + 全局令牌桶；超限 429 并带 Retry-After（契约 §4）。"""
    from agentd.api.errors import AppError, ErrorCode
    from agentd.security.ratelimit import RateLimiter

    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return auth
    wait_s = limiter.check(auth.key)
    if wait_s is not None:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            "请求过于频繁，请稍后重试",
            headers={"Retry-After": str(max(1, math.ceil(wait_s)))},
        )
    return auth


RateLimitedAuth = Annotated[AuthContext, Depends(enforce_rate_limit)]
