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


# ---------- 兜底 500 与 413 的 request_id（契约 §4：body 与响应头一致且非空） ----------


async def test_unhandled_500_carries_non_empty_request_id(probe_client: AsyncClient) -> None:
    """未捕获异常由 ServerErrorMiddleware 处理（在用户中间件之外），曾拿到空 request_id。"""
    resp = await probe_client.get("/boom")
    assert resp.status_code == 500
    error = resp.json()["error"]
    assert error["code"] == "internal"
    assert error["request_id"], "兜底 500 的 request_id 不能为空"
    assert REQ_ID.match(error["request_id"])


async def test_unhandled_500_header_matches_body(probe_client: AsyncClient) -> None:
    resp = await probe_client.get("/boom")
    error = resp.json()["error"]
    assert resp.headers["X-Request-Id"] == error["request_id"]
    # 头只能有一个（error_response 自带 + 中间件包装器不得重复追加）
    assert len(resp.headers.get_list("X-Request-Id")) == 1


async def test_unhandled_500_reuses_client_request_id(probe_client: AsyncClient) -> None:
    resp = await probe_client.get("/boom", headers={"X-Request-Id": "req_0123456789abcdef"})
    assert resp.json()["error"]["request_id"] == "req_0123456789abcdef"
    assert resp.headers["X-Request-Id"] == "req_0123456789abcdef"


async def test_oversized_body_413_carries_request_id(client: AsyncClient) -> None:
    """413 由 BodySizeLimitMiddleware 在最外层直接发出，同样要满足契约 §4。"""
    # Content-Length 由 httpx 按实际 body 覆盖，所以直接给一个超过默认上限的 body
    resp = await client.post(
        "/v1/sessions",
        headers={"X-Request-Id": "req_abcdefabcdefabcd"},
        content=b"x" * 2_000_000,
    )
    assert resp.status_code == 413, resp.text
    error = resp.json()["error"]
    assert error["request_id"] == "req_abcdefabcdefabcd"
    assert resp.headers["X-Request-Id"] == "req_abcdefabcdefabcd"
