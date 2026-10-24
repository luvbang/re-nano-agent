"""/v1/runs 路由（M3）：创建（202+幂等）/详情/取消/SSE 事件流。

SSE 语义（契约 §3）：seq 单调递增；Last-Event-ID 回放控制类事件（delta 不落库）；
run 已终态时回放后即关流；仍在运行则先回放再接实时队列；15s 心跳注释行。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import StreamingResponse

from agentd.api.auth import AuthDep
from agentd.api.deps import DbDep, SettingsDep
from agentd.api.errors import AppError, ErrorCode
from agentd.api.routes.sessions import audit, get_session_or_404
from agentd.api.schemas import CreateRunIn, RunIdOut, RunOut
from agentd.api.serialize import is_terminal_status, run_out
from agentd.providers.base import Provider
from agentd.services.runs import RunService
from agentd.storage.db import Database
from agentd.storage.repositories import RunRepository
from agentd.tools.registry import ToolRegistry

router = APIRouter(prefix="/v1", tags=["runs"])

IDEMPOTENCY_TTL_S = 300.0
SSE_HEARTBEAT_S = 15.0


async def _get_run_or_404(db: Database, run_id: str, project_id: str) -> dict[str, Any]:
    row = await RunRepository(db).get(run_id)
    if row is None or str(row["project_id"]) != project_id:
        raise AppError(ErrorCode.NOT_FOUND, "run 不存在")
    return row


@router.post("/sessions/{session_id}/runs", response_model=RunIdOut, status_code=202)
async def create_run(
    session_id: str,
    body: CreateRunIn,
    request: Request,
    response: Response,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> RunIdOut:
    session = await get_session_or_404(db, session_id, auth.project_id)
    idem_key = request.headers.get("idempotency-key")
    store: dict[str, tuple[str, float]] = request.app.state.idempotency
    now = time.monotonic()
    if idem_key:
        hit = store.get(idem_key)
        if hit and hit[1] > now:
            response.headers["Idempotency-Replayed"] = "true"
            return RunIdOut(run_id=hit[0])
    service: RunService = request.app.state.runs
    provider: Provider = request.app.state.provider
    tools: ToolRegistry | None = request.app.state.tools
    run = await service.create_run(
        session=session,
        input=body.input,
        provider=provider,
        tools=tools,
        settings=settings,
    )
    await audit(
        db,
        project_id=auth.project_id,
        actor=auth.key_id,
        action="run.created",
        target=str(run["id"]),
        detail={"session_id": str(session["id"])},
        ip=request.client.host if request.client else None,
    )
    if idem_key:
        store[idem_key] = (str(run["id"]), now + IDEMPOTENCY_TTL_S)
        _evict_expired(store, now)
    return RunIdOut(run_id=str(run["id"]))


def _evict_expired(store: dict[str, tuple[str, float]], now: float) -> None:
    for key in [k for k, (_, exp) in store.items() if exp <= now]:
        store.pop(key, None)


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: str, auth: AuthDep, db: DbDep) -> RunOut:
    row = await _get_run_or_404(db, run_id, auth.project_id)
    return run_out(row)


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: str, request: Request, auth: AuthDep, db: DbDep
) -> RunOut:
    await _get_run_or_404(db, run_id, auth.project_id)
    service: RunService = request.app.state.runs
    row = await service.cancel(run_id)
    await audit(
        db,
        project_id=auth.project_id,
        actor=auth.key_id,
        action="run.cancelled",
        target=run_id,
        ip=request.client.host if request.client else None,
    )
    return run_out(row)


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    await _get_run_or_404(db, run_id, auth.project_id)
    service: RunService = request.app.state.runs
    after_seq = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def stream() -> Any:
        queue = service.subscribe(run_id)
        last_seq = after_seq
        try:
            for ev in await service.replay(run_id, after_seq=after_seq):
                last_seq = max(last_seq, int(ev["seq"]))
                yield _format_sse(ev)
            row = await RunRepository(db).get(run_id)
            if row is not None and is_terminal_status(str(row["status"])) and queue.empty():
                return
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_S)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    return
                if int(item["seq"]) > last_seq:
                    last_seq = int(item["seq"])
                    yield _format_sse(item)
        finally:
            service.unsubscribe(run_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _format_sse(envelope: dict[str, Any]) -> str:
    return (
        f"event: {envelope['type']}\n"
        f"data: {json.dumps(envelope, ensure_ascii=False)}\n"
        f"id: {envelope['seq']}\n\n"
    )
