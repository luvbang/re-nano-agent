"""CORS 白名单与请求体限制测试（M5 D3）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.fake import FakeChatProvider, demo_turn

ADMIN_KEY = "admin-d3-test"


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path,
        log_level="WARNING",
        log_json=False,
        admin_api_key=ADMIN_KEY,
        **overrides,  # type: ignore[arg-type]
    )


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = create_app(
        make_settings(
            tmp_path,
            cors_origins="https://console.example.com, https://ops.example.com",
            max_request_body_bytes=1_000,
        ),
        provider=FakeChatProvider(turn_fn=demo_turn),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def auth_headers(client: AsyncClient) -> dict[str, str]:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (
        await client.post("/v1/admin/projects", json={"name": "p"}, headers=admin)
    ).json()
    key = (
        await client.post(
            "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin
        )
    ).json()["key"]
    return {"Authorization": f"Bearer {key}"}


async def test_cors_preflight_allowed_origin(client: AsyncClient) -> None:
    preflight = await client.options(
        "/v1/sessions",
        headers={
            "Origin": "https://console.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "https://console.example.com"
    assert "authorization" in preflight.headers.get("access-control-allow-headers", "").lower()


async def test_cors_disallowed_origin_gets_no_allow_header(client: AsyncClient) -> None:
    response = await client.get(
        "/healthz", headers={"Origin": "https://evil.example"}
    )
    assert "access-control-allow-origin" not in response.headers


async def test_oversized_content_length_rejected_413(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    response = await client.post(
        "/v1/sessions",
        headers={**headers, "Content-Length": "5000"},
        content=b"x" * 5000,
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "invalid_request"
    assert "too large" in response.json()["error"]["message"]


async def test_chunked_oversize_rejected(client: AsyncClient) -> None:
    headers = await auth_headers(client)

    async def stream_body() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"y" * 400  # 分块累计 2000 > 1000 上限

    response = await client.post(
        "/v1/sessions", headers=headers, content=stream_body()
    )
    assert response.status_code == 413


async def test_normal_size_unaffected(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    session = await client.post(
        "/v1/sessions", json={"title": "ok"}, headers=headers
    )
    assert session.status_code == 201
