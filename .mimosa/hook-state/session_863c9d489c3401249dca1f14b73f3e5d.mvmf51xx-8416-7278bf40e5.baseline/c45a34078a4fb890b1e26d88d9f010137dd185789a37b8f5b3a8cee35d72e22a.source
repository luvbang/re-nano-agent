"""运维端点：/healthz（存活，不碰 IO）与 /readyz（DB 可用性，供 LB 摘流）。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agentd.api.deps import DbDep
from agentd.api.schemas import ErrorEnvelope, HealthResponse, ReadyResponse
from agentd.config import APP_VERSION

router = APIRouter(tags=["ops"])


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz(request: Request) -> HealthResponse:
    started_at: float = request.app.state.started_at
    return HealthResponse(
        status="ok", version=APP_VERSION, uptime_s=round(time.monotonic() - started_at, 3)
    )


@router.get(
    "/readyz",
    response_model=ReadyResponse,
    summary="Readiness probe (DB reachable and writable)",
    responses={503: {"model": ErrorEnvelope, "description": "依赖不可用"}},
)
async def readyz(db: DbDep) -> ReadyResponse | JSONResponse:
    try:
        await db.fetch_one("SELECT 1 AS ok")
    except Exception:
        return JSONResponse(
            status_code=503, content={"status": "not_ready", "checks": {"db": "unavailable"}}
        )
    return ReadyResponse(status="ready", checks={"db": "ok"})
