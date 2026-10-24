from __future__ import annotations

from httpx import AsyncClient


async def test_app_error_maps_to_envelope(probe_client: AsyncClient) -> None:
    resp = await probe_client.get("/conflict")
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "conflict"
    assert error["message"] == "session busy"
    assert error["retryable"] is False
    assert error["request_id"].startswith("req_")


async def test_validation_error_is_invalid_request(probe_client: AsyncClient) -> None:
    resp = await probe_client.post("/payload", json={"n": "not-an-int"})
    assert resp.status_code == 400
    error = resp.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"], "validation details should be present"
    assert "loc" in error["details"][0] and "msg" in error["details"][0]


async def test_unhandled_exception_hides_details(probe_client: AsyncClient) -> None:
    resp = await probe_client.get("/boom")
    assert resp.status_code == 500
    error = resp.json()["error"]
    assert error["code"] == "internal"
    assert error["message"] == "Internal server error"
    assert "boom" not in resp.text or "Traceback" not in resp.text
