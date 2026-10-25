"""长期记忆端点（v0.2-3）：/v1/memories，project 作用域。

GET：列出（默认全部状态，最近创建优先）；POST：手动写入（去重 bump last_seen）；
DELETE：归档（不物理删除，Dream 与审计保留痕迹）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from agentd.api.auth import ProjectAuth, RateLimitedAuth
from agentd.api.deps import DbDep
from agentd.api.errors import AppError, ErrorCode
from agentd.api.schemas import ErrorEnvelope, MemoryCreate, MemoryOut
from agentd.services.memory import MemoryService
from agentd.storage.repositories import AuditRepository

router = APIRouter(prefix="/v1/memories", tags=["memories"])


def _memory_out(row: dict[str, Any]) -> MemoryOut:
    return MemoryOut(
        id=str(row["id"]),
        content=str(row["content"]),
        status=str(row["status"]),
        score=float(row["score"]),
        created_at=str(row["created_at"]),
        last_seen_at=str(row["last_seen_at"]),
    )


def _service(db: DbDep) -> MemoryService:
    return MemoryService(db, audit=AuditRepository(db))


@router.get(
    "",
    response_model=list[MemoryOut],
    summary="记忆列表（最近创建优先，可按状态过滤）",
    responses={401: {"model": ErrorEnvelope}},
)
async def list_memories(
    auth: ProjectAuth,
    db: DbDep,
    _limit: RateLimitedAuth,
    status: Annotated[str | None, Query(pattern="^(active|archived)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[MemoryOut]:
    project_id = str(auth.project["id"])
    rows = await _service(db).memories.list_recent(project_id, limit=limit)
    if status is not None:
        rows = [r for r in rows if str(r["status"]) == status]
    return [_memory_out(r) for r in rows]


@router.post(
    "",
    status_code=201,
    response_model=MemoryOut,
    summary="写入记忆（同内容去重：已存在则刷新 last_seen）",
    responses={401: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
)
async def create_memory(
    body: MemoryCreate, auth: ProjectAuth, db: DbDep, _limit: RateLimitedAuth
) -> MemoryOut:
    project_id = str(auth.project["id"])
    row, _created = await _service(db).add(
        project_id, body.content, actor=f"key:{auth.key['id']}"
    )
    return _memory_out(row)


@router.delete(
    "/{memory_id}",
    status_code=204,
    summary="归档记忆（跨 project 一律 404，不泄漏存在性）",
    responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
)
async def archive_memory(
    memory_id: str, auth: ProjectAuth, db: DbDep, _limit: RateLimitedAuth
) -> None:
    project_id = str(auth.project["id"])
    archived = await _service(db).archive(project_id, memory_id, actor=f"key:{auth.key['id']}")
    if not archived:
        raise AppError(ErrorCode.NOT_FOUND, f"memory 不存在：{memory_id}")
