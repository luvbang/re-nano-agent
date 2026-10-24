"""路由包：health（M0）+ /v1（M3：sessions / runs+SSE / admin keys+usage+models）。"""

from __future__ import annotations

from fastapi import APIRouter

from agentd.api.routes import admin, health, runs, sessions

health_router = health.router
v1_router = APIRouter()
v1_router.include_router(sessions.router)
v1_router.include_router(runs.router)
v1_router.include_router(admin.router)

__all__ = ["health_router", "v1_router"]
