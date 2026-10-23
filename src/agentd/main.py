"""FastAPI 装配入口。

用工厂而不是模块级 app：导入 ``agentd.main`` 不应该产生副作用（建目录/连库）。
启动命令：``uvicorn agentd.main:create_app --factory``。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentd.api.errors import register_error_handlers
from agentd.api.middleware import RequestIDMiddleware
from agentd.api.routes.health import router as health_router
from agentd.config import APP_VERSION, Settings, get_settings
from agentd.log import configure_logging
from agentd.storage.db import Database
from agentd.storage.repositories import RunRepository

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    settings.ensure_dirs()

    db = Database(settings.db_path or settings.data_dir / "agentd.db",
                  busy_timeout_ms=settings.sqlite_busy_timeout_ms)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.auto_migrate:
            applied = await asyncio.to_thread(db.migrate)
            if applied:
                logger.info("db.migrated", extra={"versions": applied})
        # 崩溃恢复：上次进程遗留的 queued/running 一律收敛为 interrupted（M2 接 run 续跑逻辑）
        recovered = await RunRepository(db).recover_interrupted()
        if recovered:
            logger.warning("runs.interrupted", extra={"count": recovered})
        logger.info(
            "app.started",
            extra={"env": settings.env, "version": APP_VERSION, "db_path": str(db.path)},
        )
        try:
            yield
        finally:
            db.close()
            logger.info("app.stopped")

    app = FastAPI(
        title="Agent Platform",
        version=APP_VERSION,
        summary="Self-hostable agent runtime: HTTP/SSE API",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.started_at = time.monotonic()

    app.add_middleware(RequestIDMiddleware, header_name=settings.request_id_header)
    register_error_handlers(app)
    app.include_router(health_router)
    return app
