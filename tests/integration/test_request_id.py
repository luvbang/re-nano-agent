from __future__ import annotations

import re

from httpx import AsyncClient

REQ_ID = re.compile(r"^req_[0-9a-f]{16}$")


async def test_request_id_is_generated_and_echoed(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    request_id = resp.headers["X-Request-Id"]
    assert REQ_ID.match(request_id)


async def test_client_supplied_request_id_is_reused(client: AsyncClient) -> None:
    resp = await client.get("/healthz", headers={"X-Request-Id": "req_abc123"})
    assert resp.headers["X-Request-Id"] == "req_abc123"


async def test_unsafe_request_id_is_replaced(client: AsyncClient) -> None:
    resp = await client.get("/healthz", headers={"X-Request-Id": "bad id\twith spaces"})
    assert REQ_ID.match(resp.headers["X-Request-Id"])


async def test_error_body_carries_same_request_id(probe_client: AsyncClient) -> None:
    resp = await probe_client.get("/conflict", headers={"X-Request-Id": "req_ffffffffffffffff"})
    assert resp.status_code == 409
    assert resp.json()["error"]["request_id"] == "req_ffffffffffffffff"
    assert resp.headers["X-Request-Id"] == "req_ffffffffffffffff"


async def test_404_uses_error_envelope(client: AsyncClient) -> None:
    resp = await client.get("/v1/does-not-exist")
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert error["code"] == "not_found"
    assert error["retryable"] is False
    assert REQ_ID.match(error["request_id"])
