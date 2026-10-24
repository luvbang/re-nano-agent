"""鉴权依赖（M3）：Bearer key → 项目上下文；撤销立即生效；超限 429。

401/403 由 AppError 统一走错误信封；前端收到 401/403 时清 key 跳登录
（web-architecture §6），语义闭环。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from agentd.api.errors import AppError, ErrorCode
from agentd.security.ratelimit import SlidingWindowLimiter
from agentd.services.keys import hash_key
from agentd.storage.db import Database
from agentd.storage.repositories import ApiKeyRepository


@dataclass(frozen=True)
class AuthContext:
    key_id: str
    project_id: str
    scopes: frozenset[str]
    rate_limit_per_min: int


def _db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


async def get_auth(request: Request) -> AuthContext:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or not header[7:].strip():
        raise AppError(ErrorCode.UNAUTHORIZED, "缺少 Authorization: Bearer <key>")
    raw = header[7:].strip()
    repo = ApiKeyRepository(_db(request))
    row = await repo.get_by_hash(hash_key(raw))
    if row is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "key 不存在")
    if row["revoked_at"] is not None:
        raise AppError(ErrorCode.UNAUTHORIZED, "key 已撤销")
    limiter: SlidingWindowLimiter = request.app.state.rate_limiter
    allowed, retry_after = limiter.check(str(row["id"]), int(row["rate_limit_per_min"]))
    if not allowed:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            f"超出每分钟 {row['rate_limit_per_min']} 次限制",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    return AuthContext(
        key_id=str(row["id"]),
        project_id=str(row["project_id"]),
        scopes=frozenset(str(row["scopes"]).split(",")),
        rate_limit_per_min=int(row["rate_limit_per_min"]),
    )


async def require_admin(auth: Annotated[AuthContext, Depends(get_auth)]) -> AuthContext:
    if "admin" not in auth.scopes:
        raise AppError(ErrorCode.FORBIDDEN, "该操作需要 admin 权限")
    return auth


AuthDep = Annotated[AuthContext, Depends(get_auth)]
AdminDep = Annotated[AuthContext, Depends(require_admin)]
