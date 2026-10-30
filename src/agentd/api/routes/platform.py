"""平台杂项端点（M3 D3）：/v1/models、/v1/usage、/v1/admin/stats。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from agentd.api.auth import AdminAuth, ProjectAuth, RateLimitedAuth
from agentd.api.deps import DbDep, SettingsDep
from agentd.storage.repositories import RunRepository, SessionRepository, UsageRepository

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
    rows = await UsageRepository(db).aggregate(
        project_id, group_by=group_by, date_from=date_from, date_to=date_to
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
    runs_by_status = await RunRepository(db).count_by_status()
    totals = await _all_usage_totals(db)
    db_path = settings.db_path
    db_size = db_path.stat().st_size if db_path and db_path.exists() else 0
    sessions = await SessionRepository(db).count_all()
    return {
        "runs_by_status": runs_by_status,
        "sessions": sessions,
        "usage": totals,
        "db_size_bytes": db_size,
        "workspace_root": str(settings.workspace_root),
    }


async def _all_usage_totals(db: DbDep) -> dict[str, Any]:
    row = await UsageRepository(db).totals()
    return {
        "records": int(row["n"]) if row else 0,
        "input_tokens": int(row["input_tokens"]) if row else 0,
        "output_tokens": int(row["output_tokens"]) if row else 0,
        "cost_usd": round(float(row["cost_usd"]), 6) if row else 0.0,
    }
