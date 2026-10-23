from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agentd.api.errors import register_error_handlers
from agentd.api.middleware import RequestIDMiddleware
from agentd.config import Settings
from agentd.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(env="test", data_dir=tmp_path, log_level="WARNING", log_json=False)


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def make_probe_app() -> FastAPI:
    """最小 app：只装错误信封 + request-id 中间件，用于测 handler 本身。"""
    from agentd.api.errors import AppError, ErrorCode

    probe = FastAPI()
    probe.add_middleware(RequestIDMiddleware, header_name="X-Request-Id")
    register_error_handlers(probe)

    @probe.get("/conflict")
    async def conflict() -> dict[str, Any]:
        raise AppError(ErrorCode.CONFLICT, "session busy")

    @probe.post("/payload")
    async def payload(body: dict[str, int]) -> dict[str, int]:
        return body

    @probe.get("/boom")
    async def boom() -> dict[str, Any]:
        raise RuntimeError("boom")

    return probe


@pytest.fixture
def probe_app() -> FastAPI:
    return make_probe_app()


@pytest.fixture
async def probe_client(probe_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=probe_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://probe") as http:
        yield http
