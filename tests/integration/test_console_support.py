"""控制台后端支撑测试（M6 D0）：sessions 列表 + 静态托管。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.fake import FakeChatProvider, demo_turn

ADMIN_KEY = "admin-console-test"


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
    app = create_app(make_settings(tmp_path), provider=FakeChatProvider(turn_fn=demo_turn))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def issue_key(client: AsyncClient) -> dict[str, str]:
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    project = (
        await client.post("/v1/admin/projects", json={"name": "p"}, headers=admin)
    ).json()
    key = (
        await client.post("/v1/admin/keys", json={"project_id": project["id"]}, headers=admin)
    ).json()["key"]
    return {"Authorization": f"Bearer {key}"}


async def test_sessions_listed_newest_first(client: AsyncClient) -> None:
    headers = await issue_key(client)
    first = await client.post("/v1/sessions", json={"title": "一号"}, headers=headers)
    second = await client.post("/v1/sessions", json={"title": "二号"}, headers=headers)
    assert first.status_code == 201 and second.status_code == 201

    listed = await client.get("/v1/sessions", headers=headers)
    assert listed.status_code == 200
    titles = [item["title"] for item in listed.json()]
    assert titles == ["二号", "一号"]  # 倒序
    # 别的 project 看不到
    other = await client.get("/v1/sessions", headers={"Authorization": "Bearer agd_none"})
    assert other.status_code == 401


async def test_static_console_mounted_after_api(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>console</html>", encoding="utf-8")
    app = create_app(
        make_settings(tmp_path, static_dir=dist),
        provider=FakeChatProvider(turn_fn=demo_turn),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        page = await c.get("/")
        assert page.status_code == 200
        assert "console" in page.text
        # API 未被遮蔽
        health = await c.get("/healthz")
        assert health.status_code == 200
        denied = await c.get("/v1/sessions")
        assert denied.status_code == 401


async def test_no_static_dir_is_fine(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, static_dir=tmp_path / "absent")
    app = create_app(settings, provider=FakeChatProvider(turn_fn=demo_turn))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        root = await c.get("/")
        assert root.status_code == 404  # 显式指向不存在目录 = 不挂载，不影响 API
