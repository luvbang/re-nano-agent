"""API 鉴权与资源端点测试（M3 D1 DoD：错误 key 401；撤销立即生效）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.main import create_app

ADMIN_KEY = "admin-int-test-key"


@pytest.fixture
def admin_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path,
        log_level="WARNING",
        log_json=False,
        admin_api_key=ADMIN_KEY,
    )


@pytest.fixture
async def admin_app(admin_settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(admin_settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def admin_client(admin_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://t") as c:
        yield c


async def bootstrap(admin_client: AsyncClient) -> tuple[str, str]:
    """管理员建 project + key，返回 (project_id, api_key)。"""
    project = await admin_client.post(
        "/v1/admin/projects", json={"name": "p1"}, headers={"Authorization": f"Bearer {ADMIN_KEY}"}
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    created = await admin_client.post(
        "/v1/admin/keys",
        json={"project_id": project_id},
        headers={"Authorization": f"Bearer {ADMIN_KEY}"},
    )
    assert created.status_code == 201, created.text
    return project_id, created.json()["key"]


async def test_full_bootstrap_and_session_flow(admin_client: AsyncClient) -> None:
    _project_id, api_key = await bootstrap(admin_client)
    headers = {"Authorization": f"Bearer {api_key}"}

    session = await admin_client.post(
        "/v1/sessions", json={"title": "s1", "external_user_id": "u1"}, headers=headers
    )
    assert session.status_code == 201
    session_id = session.json()["id"]
    assert session.json()["title"] == "s1"

    detail = await admin_client.get(f"/v1/sessions/{session_id}", headers=headers)
    assert detail.status_code == 200 and detail.json()["id"] == session_id

    messages = await admin_client.get(f"/v1/sessions/{session_id}/messages", headers=headers)
    assert messages.status_code == 200 and messages.json() == {
        "items": [],
        "has_more": False,
    }


async def test_missing_or_wrong_key_is_401(admin_client: AsyncClient) -> None:
    no_auth = await admin_client.get("/v1/sessions/s_whatever")
    assert no_auth.status_code == 401
    assert no_auth.json()["error"]["code"] == "unauthorized"

    wrong = await admin_client.get(
        "/v1/sessions/s_whatever", headers={"Authorization": "Bearer agd_does_not_exist"}
    )
    assert wrong.status_code == 401


async def test_non_admin_key_cannot_use_admin_endpoints(admin_client: AsyncClient) -> None:
    _, api_key = await bootstrap(admin_client)
    forbidden = await admin_client.post(
        "/v1/admin/projects", json={"name": "x"}, headers={"Authorization": f"Bearer {api_key}"}
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


async def test_revocation_takes_effect_immediately(admin_client: AsyncClient) -> None:
    project_id, api_key = await bootstrap(admin_client)
    headers = {"Authorization": f"Bearer {api_key}"}
    keys = await admin_client.get(
        "/v1/admin/keys", headers={"Authorization": f"Bearer {ADMIN_KEY}"}
    )
    key_id = next(k["id"] for k in keys.json() if k["project_id"] == project_id)

    ok = await admin_client.post("/v1/sessions", json={"title": "x"}, headers=headers)
    assert ok.status_code == 201  # 撤销前正常
    revoked = await admin_client.post(
        f"/v1/admin/keys/{key_id}/revoke", headers={"Authorization": f"Bearer {ADMIN_KEY}"}
    )
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None

    after = await admin_client.post(
        "/v1/sessions", json={"title": "x"}, headers=headers
    )
    assert after.status_code == 401
    assert "撤销" in after.json()["error"]["message"]


async def test_cross_project_session_is_404(admin_client: AsyncClient) -> None:
    _, key_a = await bootstrap(admin_client)
    headers_a = {"Authorization": f"Bearer {key_a}"}
    session = await admin_client.post("/v1/sessions", json={"title": "mine"}, headers=headers_a)
    session_id = session.json()["id"]

    # 第二个 project 的 key 看不到 A 的 session（404 而不是 403，不泄漏存在性）
    project2 = await admin_client.post(
        "/v1/admin/projects", json={"name": "p2"}, headers={"Authorization": f"Bearer {ADMIN_KEY}"}
    )
    key2 = await admin_client.post(
        "/v1/admin/keys",
        json={"project_id": project2.json()["id"]},
        headers={"Authorization": f"Bearer {ADMIN_KEY}"},
    )
    other = await admin_client.get(
        f"/v1/sessions/{session_id}",
        headers={"Authorization": f"Bearer {key2.json()['key']}"},
    )
    assert other.status_code == 404


async def test_key_plaintext_only_returned_once(admin_client: AsyncClient) -> None:
    await bootstrap(admin_client)
    keys = await admin_client.get(
        "/v1/admin/keys", headers={"Authorization": f"Bearer {ADMIN_KEY}"}
    )
    assert keys.status_code == 200
    for item in keys.json():
        assert "key" not in item  # 列表只含 prefix，不含明文
        assert item["key_prefix"].startswith("agd_")
