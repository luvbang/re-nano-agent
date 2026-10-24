"""runs 端点（M3 D2）：创建（202）、详情、SSE 事件流、取消。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agentd.api.auth import ProjectAuth
from agentd.api.deps import DbDep
from agentd.api.errors import AppError, ErrorCode
from agentd.api.schemas import ErrorEnvelope
from agentd.services.run_manager import RunManager
from agentd.storage.repositories import IdempotencyRepository, RunRepository

router = APIRouter(prefix="/v1", tags=["runs"])

HEARTBEAT_S = 15.0


class RunCreate(BaseModel):
    input: str = Field(min_length=1, max_length=100_000)
    stream: bool = True  # 契约保留位：v0.1 事件一律走 /events 端点
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunCreated(BaseModel):
    run_id: str
    status: str


class RunOut(BaseModel):
    id: str
    session_id: str
    status: str
    model: str | None
    input_tokens: int
    output_tokens: int
    error: dict[str, Any] | None
    created_at: str
    finished_at: str | None


def _run_manager(request: Request) -> RunManager:
    manager: RunManager | None = getattr(request.app.state, "run_manager", None)
    if manager is None:
        raise AppError(ErrorCode.MODEL_ERROR, "模型未配置（AGENTD_LLM_API_KEY），runs 不可用")
    return manager


async def _get_run(db: Any, run_id: str, project_id: str) -> dict[str, Any]:
    row = await RunRepository(db).get(run_id)
    if row is None or str(row["project_id"]) != project_id:
        raise AppError(ErrorCode.NOT_FOUND, f"run 不存在：{run_id}")
    return row


def _sse(seq: int, type_: str, payload: dict[str, Any]) -> str:
    return f"event: {type_}\nid: {seq}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post(
    "/sessions/{session_id}/runs",
    status_code=202,
    response_model=RunCreated,
    summary="创建 run（可选 Idempotency-Key，5 分钟窗口）",
    responses={
        202: {"model": RunCreated},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
    },
)
async def create_run(
    session_id: str,
    body: RunCreate,
    auth: ProjectAuth,
    db: DbDep,
    request: Request,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> RunCreated:
    from agentd.storage.repositories import SessionRepository

    session = await SessionRepository(db).get(session_id, project_id=str(auth.project["id"]))
    if session is None:
        raise AppError(ErrorCode.NOT_FOUND, f"session 不存在：{session_id}")
    manager = _run_manager(request)
    if idempotency_key:
        existing = await IdempotencyRepository(db).find_run(idempotency_key)
        if existing:
            row = await RunRepository(db).get(existing)
            if row is not None:
                return RunCreated(run_id=existing, status=str(row["status"]))
    run = await manager.start(session_row=session, user_input=body.input)
    if idempotency_key:
        await IdempotencyRepository(db).bind(
            idempotency_key, run_id=str(run["id"]), session_id=session_id
        )
    return RunCreated(run_id=str(run["id"]), status=str(run["status"]))


@router.get(
    "/runs/{run_id}",
    response_model=RunOut,
    summary="run 详情（状态/用量/错误）",
    responses={404: {"model": ErrorEnvelope}},
)
async def get_run(run_id: str, auth: ProjectAuth, db: DbDep) -> RunOut:
    row = await _get_run(db, run_id, str(auth.project["id"]))
    return RunOut(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        status=str(row["status"]),
        model=row["model"],
        input_tokens=int(row["input_tokens"]),
        output_tokens=int(row["output_tokens"]),
        error=json.loads(row["error_json"]) if row["error_json"] else None,
        created_at=str(row["created_at"]),
        finished_at=row["finished_at"],
    )


@router.post(
    "/runs/{run_id}/cancel",
    summary="取消 run",
    responses={200: {"model": dict}, 404: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
)
async def cancel_run(run_id: str, auth: ProjectAuth, db: DbDep, request: Request) -> dict[str, Any]:
    await _get_run(db, run_id, str(auth.project["id"]))
    return await _run_manager(request).cancel(run_id)


@router.get(
    "/runs/{run_id}/events",
    summary="run 事件流（SSE；支持 Last-Event-ID 续传，15s 心跳）",
    response_class=StreamingResponse,
    responses={404: {"model": ErrorEnvelope}},
)
async def run_events(
    run_id: str,
    auth: ProjectAuth,
    db: DbDep,
    request: Request,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    row = await _get_run(db, run_id, str(auth.project["id"]))
    manager = _run_manager(request)
    from agentd.storage.repositories import RunEventRepository

    events_repo = RunEventRepository(db)
    after_seq = 0
    if last_event_id:
        try:
            after_seq = max(int(last_event_id), 0)
        except ValueError:
            raise AppError(ErrorCode.INVALID_REQUEST, "Last-Event-ID 必须是整数") from None

    async def generator() -> AsyncIterator[str]:
        replayed_max = after_seq
        rows = await events_repo.list_after(run_id, after_seq=after_seq)
        for event_row in rows:
            replayed_max = int(event_row["seq"])
            yield _sse(
                int(event_row["seq"]),
                str(event_row["type"]),
                json.loads(event_row["payload_json"]),
            )
        active = manager.get(run_id)
        if active is not None:
            queue = manager.subscribe(run_id)
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                    except TimeoutError:
                        yield ": ping\n\n"
                        continue
                    if item is None:
                        break
                    if int(item["seq"]) <= replayed_max:
                        continue  # 回放已覆盖（订阅先于回放的竞态保护）
                    yield _sse(int(item["seq"]), str(item["type"]), dict(item["payload"]))
            finally:
                manager.unsubscribe(run_id, queue)
        else:
            # run 不在本进程：若回放里没有终态事件（如 kill -9 后 interrupted），合成收尾
            types = {str(r["type"]) for r in rows}
            terminal = {"run.completed", "run.failed", "run.cancelled"}
            if not types & terminal:
                status = str(row["status"])
                if status == "interrupted":
                    payload = {
                        "error": {
                            "code": "interrupted",
                            "message": "进程重启导致 run 中断",
                            "retryable": True,
                        }
                    }
                else:
                    payload = {
                        "error": {
                            "code": "internal",
                            "message": f"run 状态异常：{status}",
                            "retryable": False,
                        }
                    }
                yield _sse(replayed_max + 1, "run.failed", payload)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
