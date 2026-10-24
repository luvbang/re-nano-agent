"""会话与消息端点（M3 D1）：/v1/sessions。"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Query

from agentd.api.auth import ProjectAuth
from agentd.api.deps import DbDep
from agentd.api.errors import AppError, ErrorCode
from agentd.api.schemas import ErrorEnvelope, MessageOut, MessagePage, SessionCreate, SessionOut
from agentd.storage.repositories import MessageRepository, SessionRepository

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


def _session_out(row: dict[str, Any]) -> SessionOut:
    return SessionOut(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        title=row["title"],
        external_user_id=row["external_user_id"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


async def _get_session(db: Any, session_id: str, project_id: str) -> dict[str, Any]:
    row = await SessionRepository(db).get(session_id, project_id=project_id)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, f"session 不存在：{session_id}")
    return row


@router.post(
    "",
    status_code=201,
    response_model=SessionOut,
    summary="创建会话",
    responses={401: {"model": ErrorEnvelope}},
)
async def create_session(body: SessionCreate, auth: ProjectAuth, db: DbDep) -> SessionOut:
    row = await SessionRepository(db).create(
        project_id=str(auth.project["id"]),
        title=body.title,
        external_user_id=body.external_user_id,
        metadata=body.metadata,
    )
    return _session_out(row)


@router.get(
    "/{session_id}",
    response_model=SessionOut,
    summary="会话详情",
    responses={404: {"model": ErrorEnvelope}},
)
async def get_session(session_id: str, auth: ProjectAuth, db: DbDep) -> SessionOut:
    return _session_out(await _get_session(db, session_id, str(auth.project["id"])))


@router.get(
    "/{session_id}/messages",
    response_model=MessagePage,
    summary="会话消息（模型历史，按 seq 升序）",
    responses={404: {"model": ErrorEnvelope}},
)
async def list_messages(
    session_id: str,
    auth: ProjectAuth,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_seq: Annotated[int | None, Query(ge=1)] = None,
) -> MessagePage:
    await _get_session(db, session_id, str(auth.project["id"]))
    rows = await MessageRepository(db).list_for_session(
        session_id, limit=limit + 1, before_seq=before_seq
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for row in rows:
        text = None
        if row["content_json"]:
            text = json.loads(row["content_json"]).get("text")
        items.append(
            MessageOut(
                id=str(row["id"]),
                seq=int(row["seq"]),
                role=str(row["role"]),
                content=text,
                tool_call_id=row["tool_call_id"],
                created_at=str(row["created_at"]),
            )
        )
    return MessagePage(items=items, has_more=has_more)
