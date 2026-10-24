"""平台杂项端点（M3 D3）：/v1/models、/v1/usage、/v1/admin/stats。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from agentd.api.auth import AdminAuth, ProjectAuth, RateLimitedAuth
from agentd.api.deps import DbDep, SettingsDep

router = APIRouter(prefix="/v1", tags=["platform"])


@router.get("/models", summary="可用模型列表")
async def list_models(
    auth: ProjectAuth, _limit: RateLimitedAuth, settings: SettingsDep
) -> list[dict[str, Any]]:
    del auth, _limit
    return [{"id": settings.llm_model, "object": "model", "tools": True}]


@router.get("/usage", summary="用量聚合（按天或模型）")
async def usage(
    auth: ProjectAuth,
    _limit: RateLimitedAuth,
    db: DbDep,
    group_by: Annotated[str, Query(pattern="^(day|model)$")] = "day",
    date_from: Annotated[str | None, Query()] = None,
    date_to: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    del _limit
    project_id = str(auth.project["id"])
    column = "strftime('%Y-%m-%d', created_at)" if group_by == "day" else "model"
    where = "project_id = ?"
    params: list[Any] = [project_id]
    if date_from:
        where += " AND created_at >= ?"
        params.append(date_from)
    if date_to:
        where += " AND created_at < date(?, '+1 day')"
        params.append(date_to)
    rows = await db.fetch_all(
        f"SELECT {column} AS bucket, COUNT(*) AS runs,"
        " COALESCE(SUM(input_tokens),0) AS input_tokens,"
        " COALESCE(SUM(output_tokens),0) AS output_tokens,"
        " COALESCE(SUM(cost_usd),0) AS cost_usd"
        f" FROM usage_records WHERE {where} GROUP BY bucket ORDER BY bucket",
        tuple(params),
    )
    return {
        "group_by": group_by,
        "items": [
            {
                "bucket": str(row["bucket"]),
                "runs": int(row["runs"]),
                "input_tokens": int(row["input_tokens"]),
                "output_tokens": int(row["output_tokens"]),
                "cost_usd": round(float(row["cost_usd"]), 6),
            }
            for row in rows
        ],
    }


@router.get("/admin/stats", summary="系统状态（管理员）：run/会话/用量/DB 体量")
async def admin_stats(auth: AdminAuth, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    del auth
    runs_by_status = {
        str(row["status"]): int(row["n"])
        for row in await db.fetch_all(
            "SELECT status, COUNT(*) AS n FROM runs GROUP BY status"
        )
    }
    totals = await _all_usage_totals(db)
    db_path = settings.db_path
    db_size = db_path.stat().st_size if db_path and db_path.exists() else 0
    sessions = await db.fetch_one("SELECT COUNT(*) AS n FROM sessions")
    return {
        "runs_by_status": runs_by_status,
        "sessions": int(sessions["n"]) if sessions else 0,
        "usage": totals,
        "db_size_bytes": db_size,
        "workspace_root": str(settings.workspace_root),
    }


async def _all_usage_totals(db: DbDep) -> dict[str, Any]:
    row = await db.fetch_one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(input_tokens),0) AS input_tokens,"
        " COALESCE(SUM(output_tokens),0) AS output_tokens,"
        " COALESCE(SUM(cost_usd),0) AS cost_usd FROM usage_records"
    )
    return {
        "records": int(row["n"]) if row else 0,
        "input_tokens": int(row["input_tokens"]) if row else 0,
        "output_tokens": int(row["output_tokens"]) if row else 0,
        "cost_usd": round(float(row["cost_usd"]), 6) if row else 0.0,
    }
