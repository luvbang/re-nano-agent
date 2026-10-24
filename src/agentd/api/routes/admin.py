"""/v1 管理与查询路由（M3）：admin keys（创建/列表/撤销）、models、usage 聚合。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from agentd.api.auth import AdminDep, AuthDep
from agentd.api.deps import DbDep
from agentd.api.errors import AppError, ErrorCode
from agentd.api.schemas import (
    CreatedKeyOut,
    CreateKeyIn,
    KeyOut,
    ModelsOut,
    UsageItemOut,
    UsageOut,
)
from agentd.api.serialize import key_out
from agentd.services.keys import generate_key
from agentd.storage.repositories import ApiKeyRepository
from agentd.tools.registry import ToolRegistry

router = APIRouter(prefix="/v1", tags=["admin"])


@router.get("/admin/keys", response_model=list[KeyOut])
async def list_keys(admin: AdminDep, db: DbDep) -> list[KeyOut]:
    rows = await db.fetch_all(
        "SELECT * FROM api_keys WHERE project_id = ? ORDER BY created_at DESC",
        (admin.project_id,),
    )
    return [key_out(row) for row in rows]


@router.post("/admin/keys", response_model=CreatedKeyOut, status_code=201)
async def create_key(body: CreateKeyIn, admin: AdminDep, db: DbDep) -> CreatedKeyOut:
    secret, key_hash, prefix = generate_key()
    row = await ApiKeyRepository(db).create(
        project_id=admin.project_id,
        key_hash=key_hash,
        key_prefix=prefix,
        name=body.name,
        scopes="core",
        rate_limit_per_min=body.rate_limit_per_min,
    )
    return CreatedKeyOut(key=key_out(row), secret=secret)


@router.delete("/admin/keys/{key_id}", status_code=204)
async def revoke_key(key_id: str, admin: AdminDep, db: DbDep) -> None:
    row = await db.fetch_one(
        "SELECT * FROM api_keys WHERE id = ? AND project_id = ?",
        (key_id, admin.project_id),
    )
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "key 不存在")
    await ApiKeyRepository(db).revoke(key_id)


@router.get("/models", response_model=ModelsOut)
async def list_models(auth: AuthDep, request: Request) -> ModelsOut:
    tools: ToolRegistry | None = request.app.state.tools
    model_id: str = request.app.state.settings.llm_model
    return ModelsOut(items=[{"id": model_id, "tools": tools.names() if tools else []}])


@router.get("/usage", response_model=UsageOut)
async def usage(
    auth: AuthDep,
    db: DbDep,
    from_date: str = Query(alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    to_date: str = Query(alias="to", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    group_by: str = Query(default="day", pattern="^(day|model)$"),
) -> UsageOut:
    if group_by == "model":
        rows = await db.fetch_all(
            "SELECT model AS grp, COUNT(*) AS runs, SUM(input_tokens) AS input_tokens,"
            " SUM(output_tokens) AS output_tokens FROM usage_records"
            " WHERE project_id = ? AND substr(created_at, 1, 10) BETWEEN ? AND ?"
            " GROUP BY model ORDER BY model",
            (auth.project_id, from_date, to_date),
        )
    else:
        rows = await db.fetch_all(
            "SELECT substr(created_at, 1, 10) AS grp, COUNT(*) AS runs,"
            " SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens"
            " FROM usage_records WHERE project_id = ? AND substr(created_at, 1, 10)"
            " BETWEEN ? AND ? GROUP BY grp ORDER BY grp",
            (auth.project_id, from_date, to_date),
        )
    items = [
        UsageItemOut(
            group=str(row["grp"]),
            runs=int(row["runs"] or 0),
            input_tokens=int(row["input_tokens"] or 0),
            output_tokens=int(row["output_tokens"] or 0),
        )
        for row in rows
    ]
    return UsageOut(from_=from_date, to=to_date, group_by=group_by, items=items)
