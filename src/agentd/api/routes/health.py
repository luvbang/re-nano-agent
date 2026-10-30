"""运维端点：/healthz（存活，不碰 IO）与 /readyz（DB 可用性，供 LB 摘流）。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from agentd.api.auth import AdminAuth
from agentd.api.deps import DbDep, SettingsDep
from agentd.api.metrics import Metrics
from agentd.api.schemas import ErrorEnvelope, HealthResponse, ReadyResponse
from agentd.config import APP_VERSION
from agentd.storage.repositories import ping

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
        await ping(db)
    except Exception:
        return JSONResponse(
            status_code=503, content={"status": "not_ready", "checks": {"db": "unavailable"}}
        )
    return ReadyResponse(status="ready", checks={"db": "ok"})


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus 文本指标（管理员；抓取端配 Bearer admin key）",
)
async def metrics_endpoint(
    request: Request, auth: AdminAuth, settings: SettingsDep
) -> PlainTextResponse:
    del auth
    registry: Metrics | None = getattr(request.app.state, "metrics", None)
    if registry is None:
        return PlainTextResponse("# metrics unavailable\n")
    db_path = settings.db_path
    if db_path and db_path.exists():
        registry.gauge("agentd_db_size_bytes", db_path.stat().st_size)
    return PlainTextResponse(
        registry.render(), media_type="text/plain; version=0.0.4; charset=utf-8"
    )
