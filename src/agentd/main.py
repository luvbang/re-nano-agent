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
from agentd.providers.base import Provider
from agentd.services.run_manager import RunManager
from agentd.storage.db import Database
from agentd.storage.repositories import RunRepository

logger = logging.getLogger(__name__)


def _build_run_manager(
    settings: Settings, db: Database, provider: Provider | None
) -> RunManager | None:
    """无模型配置时返回 None（/v1/runs 返回 502 model_error，健康检查不受影响）。"""
    from agentd.providers.openai_compat import OpenAICompatProvider
    from agentd.providers.retry import RetryingProvider
    from agentd.runtime.context import ContextBuilder
    from agentd.tools.builtin import BUILTIN_TOOLS
    from agentd.tools.filesystem import filesystem_tools
    from agentd.tools.registry import ToolRegistry

    if provider is None:
        api_key = settings.llm_api_key.get_secret_value()
        if not api_key:
            return None
        provider = RetryingProvider(
            OpenAICompatProvider(
                api_key=api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                timeout_s=settings.llm_timeout_s,
            ),
            max_retries=settings.llm_retries,
        )
        model = settings.llm_model
    else:
        model = getattr(provider, "model", "custom")
    assert settings.workspace_root is not None
    tools = (
        ToolRegistry(
            tool_timeout_s=settings.run_tool_timeout_s,
            overflow_root=settings.workspace_root / ".runs",
        )
        .register_all(BUILTIN_TOOLS)
        .register_all(filesystem_tools(settings.workspace_root))
    )
    from agentd.services.usage_service import UsageService, parse_price_table

    return RunManager(
        db,
        provider,
        tools=tools,
        model=model,
        usage_service=UsageService(db, parse_price_table(settings.llm_price_table)),
        runner_kwargs={
            "max_iterations": settings.run_max_iterations,
            "timeout_s": settings.run_timeout_s,
            "context_builder": ContextBuilder(
                context_window=settings.llm_context_window, max_output=settings.llm_max_output
            ),
        },
        global_concurrency=settings.run_global_concurrency,
        project_concurrency=settings.run_project_concurrency,
    )


def create_app(settings: Settings | None = None, *, provider: Provider | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    settings.ensure_dirs()

    db = Database(settings.db_path or settings.data_dir / "agentd.db",
                  busy_timeout_ms=settings.sqlite_busy_timeout_ms)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.auto_migrate:
            applied = await asyncio.to_thread(db.migrate)
            if applied:
                logger.info("db.migrated", extra={"versions": applied})
        # 崩溃恢复：上次进程遗留的 queued/running 一律收敛为 interrupted（SSE 订阅侧合成终态）
        recovered = await RunRepository(db).recover_interrupted()
        if recovered:
            logger.warning("runs.interrupted", extra={"count": recovered})
        app.state.run_manager = _build_run_manager(settings, db, provider)
        from agentd.security.ratelimit import RateLimiter

        app.state.rate_limiter = RateLimiter(global_per_min=settings.ratelimit_global_per_min)
        logger.info(
            "app.started",
            extra={"env": settings.env, "version": APP_VERSION, "db_path": str(db.path)},
        )
        try:
            yield
        finally:
            manager = getattr(app.state, "run_manager", None)
            if manager is not None:
                await manager.shutdown()
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
    from fastapi import Depends

    from agentd.api.auth import enforce_rate_limit
    from agentd.api.routes.admin import router as admin_router
    from agentd.api.routes.platform import router as platform_router
    from agentd.api.routes.runs import router as runs_router
    from agentd.api.routes.sessions import router as sessions_router

    throttled = [Depends(enforce_rate_limit)]
    app.include_router(admin_router)
    app.include_router(sessions_router, dependencies=throttled)
    app.include_router(runs_router, dependencies=throttled)
    app.include_router(platform_router)
    return app
