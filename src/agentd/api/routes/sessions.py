"""/v1/sessions 路由（M3）：创建/列表/详情/消息分页（契约 §2，列表端点为新增）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from agentd.api.auth import AuthDep
from agentd.api.deps import DbDep
from agentd.api.errors import AppError, ErrorCode
from agentd.api.schemas import CreateSessionIn, MessageOut, SessionOut
from agentd.api.serialize import message_out, session_out
from agentd.storage.db import Database
from agentd.storage.repositories import AuditRepository, MessageRepository, SessionRepository

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


async def audit(
    db: Database,
    *,
    project_id: str,
    actor: str,
    action: str,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    await AuditRepository(db).append(
        project_id=project_id, actor=actor, action=action, target=target, detail=detail, ip=ip
    )


async def get_session_or_404(db: Database, session_id: str, project_id: str) -> dict[str, Any]:
    row = await SessionRepository(db).get(session_id, project_id=project_id)
    if row is None:
        # 跨 project 一律 404，不泄漏存在性（契约 §4）
        raise AppError(ErrorCode.NOT_FOUND, "session 不存在")
    return row


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(
    body: CreateSessionIn,
    request: Request,
    auth: AuthDep,
    db: DbDep,
) -> SessionOut:
    row = await SessionRepository(db).create(
        project_id=auth.project_id,
        external_user_id=body.external_user_id,
        title=body.title,
        metadata=body.metadata,
    )
    await audit(
        db,
        project_id=auth.project_id,
        actor=auth.key_id,
        action="session.created",
        target=str(row["id"]),
        ip=request.client.host if request.client else None,
    )
    return session_out(row)


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    auth: AuthDep,
    db: DbDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SessionOut]:
    rows = await SessionRepository(db).list_by_project(auth.project_id, limit=limit)
    return [session_out(row) for row in rows]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, auth: AuthDep, db: DbDep) -> SessionOut:
    row = await get_session_or_404(db, session_id, auth.project_id)
    return session_out(row)


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: str,
    auth: AuthDep,
    db: DbDep,
    limit: int = Query(default=100, ge=1, le=1000),
    before: int | None = Query(default=None, ge=1),
) -> list[MessageOut]:
    await get_session_or_404(db, session_id, auth.project_id)
    rows = await MessageRepository(db).list_by_session(
        session_id, before_seq=before, limit=limit
    )
    return [message_out(row) for row in rows]
