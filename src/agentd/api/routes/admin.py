"""管理端点（M3 D1）：/v1/admin/projects 与 /v1/admin/keys。

管理员 = env 管理员 key（AGENTD_ADMIN_KEY）或 DB 中 scopes 含 admin 的 key。
创建 key 的明文只在创建响应里出现一次；撤销立即生效（每个请求实时查库）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from agentd.api.auth import AdminAuth, generate_api_key
from agentd.api.deps import DbDep, SettingsDep
from agentd.api.errors import AppError, ErrorCode
from agentd.api.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ErrorEnvelope,
    ProjectCreate,
    ProjectOut,
)
from agentd.storage.repositories import ApiKeyRepository, ProjectRepository

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _project_out(row: dict[str, Any]) -> ProjectOut:
    return ProjectOut(id=str(row["id"]), name=str(row["name"]), created_at=str(row["created_at"]))


def _key_out(row: dict[str, Any]) -> ApiKeyOut:
    return ApiKeyOut(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        name=row["name"],
        key_prefix=str(row["key_prefix"]),
        scopes=str(row["scopes"]),
        rate_limit_per_min=int(row["rate_limit_per_min"]),
        revoked_at=row["revoked_at"],
        created_at=str(row["created_at"]),
    )


@router.post(
    "/projects",
    status_code=201,
    response_model=ProjectOut,
    summary="创建 project（管理员）",
    responses={403: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
)
async def create_project(
    body: ProjectCreate, auth: AdminAuth, db: DbDep, settings: SettingsDep
) -> ProjectOut:
    del auth  # 鉴权已由依赖完成
    existing = await ProjectRepository(db).get_by_name(body.name)
    if existing is not None:
        raise AppError(ErrorCode.CONFLICT, f"project 已存在：{body.name}")
    row = await ProjectRepository(db).create(name=body.name, workspace_path="pending")
    assert settings.workspace_root is not None
    workspace = settings.workspace_root / str(row["id"])
    await db.execute(
        "UPDATE projects SET workspace_path = ? WHERE id = ?", (str(workspace), row["id"])
    )
    row["workspace_path"] = str(workspace)
    return _project_out(row)


@router.get("/projects", response_model=list[ProjectOut], summary="project 列表（管理员）")
async def list_projects(auth: AdminAuth, db: DbDep) -> list[ProjectOut]:
    del auth
    rows = await db.fetch_all("SELECT * FROM projects ORDER BY created_at")
    return [_project_out(row) for row in rows]


@router.post(
    "/keys",
    status_code=201,
    response_model=ApiKeyCreated,
    summary="创建 API key（管理员；明文仅返回一次）",
    responses={403: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
)
async def create_key(
    body: ApiKeyCreate, auth: AdminAuth, db: DbDep, settings: SettingsDep
) -> ApiKeyCreated:
    del auth, settings
    project = await ProjectRepository(db).get(body.project_id)
    if project is None:
        raise AppError(ErrorCode.NOT_FOUND, f"project 不存在：{body.project_id}")
    plaintext, key_hash, prefix = generate_api_key()
    row = await ApiKeyRepository(db).create(
        project_id=body.project_id,
        key_hash=key_hash,
        key_prefix=prefix,
        name=body.name,
        scopes="core",
        rate_limit_per_min=body.rate_limit_per_min,
    )
    return ApiKeyCreated(key=plaintext, detail=_key_out(row))


@router.get("/keys", response_model=list[ApiKeyOut], summary="key 列表（管理员，不含明文）")
async def list_keys(auth: AdminAuth, db: DbDep) -> list[ApiKeyOut]:
    del auth
    rows = await db.fetch_all("SELECT * FROM api_keys ORDER BY created_at")
    return [_key_out(row) for row in rows]


@router.post(
    "/keys/{key_id}/revoke",
    response_model=ApiKeyOut,
    summary="撤销 key（立即生效）",
    responses={404: {"model": ErrorEnvelope}},
)
async def revoke_key(key_id: str, auth: AdminAuth, db: DbDep) -> ApiKeyOut:
    del auth
    row = await db.fetch_one("SELECT * FROM api_keys WHERE id = ?", (key_id,))
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, f"key 不存在：{key_id}")
    if row["revoked_at"] is None:
        await ApiKeyRepository(db).revoke(key_id)
    fresh = await db.fetch_one("SELECT * FROM api_keys WHERE id = ?", (key_id,))
    assert fresh is not None
    return _key_out(fresh)
