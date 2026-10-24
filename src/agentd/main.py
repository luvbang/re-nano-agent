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
from pathlib import Path

from fastapi import FastAPI

from agentd.api.errors import register_error_handlers
from agentd.api.middleware import RequestIDMiddleware
from agentd.api.routes import health_router, v1_router
from agentd.config import APP_VERSION, Settings, get_settings
from agentd.log import configure_logging
from agentd.providers.base import Provider
from agentd.providers.fake import FakeChatProvider, demo_turn
from agentd.providers.openai_compat import OpenAICompatProvider
from agentd.providers.retry import RetryingProvider
from agentd.security.ratelimit import SlidingWindowLimiter
from agentd.services.keys import ensure_admin_key
from agentd.services.runs import RunService
from agentd.storage.db import Database
from agentd.storage.repositories import RunRepository
from agentd.tools import build_workspace_tools
from agentd.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def _build_provider(settings: Settings) -> Provider:
    """provider=auto：配了 key 走真实模型，否则 fake（离线全链路可跑，web-architecture §7）。"""
    if settings.provider == "fake":
        return FakeChatProvider(turn_fn=demo_turn)
    api_key = settings.llm_api_key.get_secret_value()
    if not api_key:
        if settings.provider == "openai":
            logger.warning("provider=openai 但未配置 AGENTD_LLM_API_KEY，回退 fake")
        return FakeChatProvider(turn_fn=demo_turn)
    inner = OpenAICompatProvider(
        api_key=api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_s,
    )
    return RetryingProvider(inner, max_retries=settings.llm_retries)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    settings.ensure_dirs()

    db = Database(settings.db_path or settings.data_dir / "agentd.db",
                  busy_timeout_ms=settings.sqlite_busy_timeout_ms)
    tools = ToolRegistry(tool_timeout_s=settings.run_tool_timeout_s).register_all(
        build_workspace_tools(
            Path(settings.workspace_root or settings.data_dir / "workspace"),
            enable_shell=settings.enable_shell_tool,
            web_fetch=settings.web_fetch_enabled,
        )
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.auto_migrate:
            applied = await asyncio.to_thread(db.migrate)
            if applied:
                logger.info("db.migrated", extra={"versions": applied})
        # 崩溃恢复：上次进程遗留的 queued/running 一律收敛为 interrupted
        recovered = await RunRepository(db).recover_interrupted()
        if recovered:
            logger.warning("runs.interrupted", extra={"count": recovered})
        admin_key = await ensure_admin_key(db, settings)
        if admin_key:
            logger.info("admin.key_bootstrapped")
        else:
            logger.warning("admin.key_missing", extra={"hint": "设置 AGENTD_ADMIN_API_KEY"})
        logger.info(
            "app.started",
            extra={"env": settings.env, "version": APP_VERSION, "db_path": str(db.path)},
        )
        try:
            yield
        finally:
            await app.state.runs.shutdown()
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
    app.state.provider = _build_provider(settings)
    app.state.tools = tools
    app.state.runs = RunService(db)
    app.state.rate_limiter = SlidingWindowLimiter()
    app.state.idempotency = {}

    app.add_middleware(RequestIDMiddleware, header_name=settings.request_id_header)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router)
    _mount_web_console(app)
    return app


def _mount_web_console(app: FastAPI) -> None:
    """构建产物存在则由后端同源服务（web-architecture §8）；无 dist 时静默跳过。

    - 带 hash 的 assets/ 回 immutable 长缓存；index.html 与 SPA 路由不缓存
    - /v1、运维端点之外的未知路径回 index.html（前端路由刷新不 404）
    """
    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if not (dist / "index.html").is_file():
        return

    from fastapi.responses import FileResponse

    from agentd.api.errors import AppError, ErrorCode

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_or_asset(full_path: str) -> FileResponse:
        if full_path.startswith(("v1/", "v1", "healthz", "readyz", "metrics")):
            # API 面的 404 必须走错误信封，不能吞成 index.html
            raise AppError(ErrorCode.NOT_FOUND, f"unknown path: /{full_path}")
        candidate = dist / full_path
        if full_path and candidate.is_file():
            cache = (
                "public, max-age=31536000, immutable"
                if full_path.startswith("assets/")
                else "no-cache"
            )
            return FileResponse(candidate, headers={"Cache-Control": cache})
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
