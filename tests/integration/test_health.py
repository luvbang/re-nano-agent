from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient


async def test_healthz_reports_ok(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["uptime_s"] >= 0


async def test_readyz_checks_db(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"db": "ok"}}


async def test_readyz_returns_503_when_db_broken(app: FastAPI, client: AsyncClient) -> None:
    async def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("db is gone")

    app.state.db.fetch_one = boom  # type: ignore[method-assign]
    resp = await client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json() == {"status": "not_ready", "checks": {"db": "unavailable"}}


async def test_openapi_exposes_ops_endpoints(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert "/healthz" in schema["paths"]
    assert "/readyz" in schema["paths"]
