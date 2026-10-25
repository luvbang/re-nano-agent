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
from agentd.api.metrics import Metrics
from agentd.api.middleware import RequestIDMiddleware
from agentd.api.routes.health import router as health_router
from agentd.config import APP_VERSION, Settings, get_settings
from agentd.log import configure_logging
from agentd.providers.base import Provider
from agentd.services.run_manager import RunManager
from agentd.storage.db import Database
from agentd.storage.repositories import AuditRepository, RunRepository

logger = logging.getLogger(__name__)


async def _build_run_manager(
    settings: Settings,
    db: Database,
    provider: Provider | None,
    *,
    metrics: Metrics | None = None,
) -> RunManager | None:
    """无模型配置时返回 None（/v1/runs 返回 502 model_error，健康检查不受影响）。"""
    from agentd.providers.factory import build_provider
    from agentd.runtime.context import ContextBuilder
    from agentd.tools.builtin import BUILTIN_TOOLS
    from agentd.tools.filesystem import filesystem_tools
    from agentd.tools.mcp import parse_mcp_config
    from agentd.tools.registry import ToolRegistry

    if provider is None:
        provider, model = build_provider(settings)
        if provider is None:
            return None
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
    mcp_config = parse_mcp_config(settings.mcp_servers)
    if mcp_config:
        from agentd.tools.mcp import load_mcp_tools

        for tool in await load_mcp_tools(mcp_config):
            tools.register(tool)  # 同名冲突时让位给内置（register 抛错则跳过）
    from agentd.runtime.compaction import HistoryCompactor
    from agentd.services.memory import MemoryService
    from agentd.services.usage_service import UsageService, parse_price_table

    context_builder = ContextBuilder(
        context_window=settings.llm_context_window, max_output=settings.llm_max_output
    )
    memory = MemoryService(
        db,
        budget_tokens=settings.memory_budget_tokens,
        max_active=settings.memory_max_active,
        stale_days=settings.memory_stale_days,
        audit=AuditRepository(db),
    )
    return RunManager(
        db,
        provider,
        tools=tools,
        model=model,
        usage_service=UsageService(db, parse_price_table(settings.llm_price_table)),
        compactor=HistoryCompactor(db, provider, context_builder=context_builder),
        memory=memory,
        memory_extract_enabled=settings.memory_extract_enabled,
        metrics=metrics,
        runner_kwargs={
            "max_iterations": settings.run_max_iterations,
            "timeout_s": settings.run_timeout_s,
            "context_builder": context_builder,
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
        app.state.run_manager = await _build_run_manager(
            settings, db, provider, metrics=app.state.metrics
        )
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
    app.state.metrics = Metrics()
    app.state.started_at = time.monotonic()

    from agentd.api.body_limit import BodySizeLimitMiddleware

    app.add_middleware(RequestIDMiddleware, header_name=settings.request_id_header)
    app.add_middleware(
        BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes
    )
    if settings.cors_origins.strip():
        from fastapi.middleware.cors import CORSMiddleware

        origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
            max_age=600,
        )
    register_error_handlers(app)
    app.include_router(health_router)
    from fastapi import Depends

    from agentd.api.auth import enforce_rate_limit
    from agentd.api.routes.admin import router as admin_router
    from agentd.api.routes.memories import router as memories_router
    from agentd.api.routes.platform import router as platform_router
    from agentd.api.routes.runs import router as runs_router
    from agentd.api.routes.sessions import router as sessions_router

    throttled = [Depends(enforce_rate_limit)]
    app.include_router(admin_router)
    app.include_router(sessions_router, dependencies=throttled)
    app.include_router(runs_router, dependencies=throttled)
    app.include_router(memories_router, dependencies=throttled)
    app.include_router(platform_router)
    _mount_console(app, settings)
    return app


def _mount_console(app: FastAPI, settings: Settings) -> None:
    """web/dist 存在则由本服务同源托管（API 路由已先注册，不会被遮蔽）。

    SPA 回退：前端路由（/playground 等）没有实体文件，GET/HEAD 404 时回退
    index.html；/v1 前缀除外——API 404 错误信封是契约行为（M0 DoD 有测试守护）。
    """
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.responses import Response
    from starlette.types import Scope

    class SPAStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope: Scope) -> Response:
            fallback = (
                scope.get("method") in ("GET", "HEAD")
                and not str(scope.get("path", "")).startswith("/v1")
            )
            try:
                response = await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if fallback and exc.status_code == 404:
                    return await super().get_response("./index.html", scope)
                raise
            if fallback and response.status_code == 404:
                return await super().get_response("./index.html", scope)
            return response

    if settings.static_dir is not None:
        # 显式指定：存在才挂，不回退（测试可用不存在路径表达"未构建"）
        candidates = [settings.static_dir]
    else:
        candidates = [Path.cwd() / "web" / "dist"]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            app.mount("/", SPAStaticFiles(directory=str(candidate), html=True), name="console")
            logger.info("console.mounted", extra={"path": str(candidate)})
            return
    logger.info("console.not_built")
