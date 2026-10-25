"""会话与消息端点（M3 D1）：/v1/sessions。"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Query

from agentd.api.auth import ProjectAuth
from agentd.api.deps import DbDep
from agentd.api.errors import AppError, ErrorCode
from agentd.api.schemas import (
    ErrorEnvelope,
    MessageOut,
    MessagePage,
    SessionCreate,
    SessionOut,
    SessionUpdate,
)
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
    "",
    response_model=list[SessionOut],
    summary="会话列表（按创建时间倒序）",
)
async def list_sessions(
    auth: ProjectAuth,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[SessionOut]:
    rows = await SessionRepository(db).list_by_project(str(auth.project["id"]), limit=limit)
    return [_session_out(row) for row in rows]


@router.get(
    "/{session_id}",
    response_model=SessionOut,
    summary="会话详情",
    responses={404: {"model": ErrorEnvelope}},
)
async def get_session(session_id: str, auth: ProjectAuth, db: DbDep) -> SessionOut:
    return _session_out(await _get_session(db, session_id, str(auth.project["id"])))


@router.patch(
    "/{session_id}",
    response_model=SessionOut,
    summary="重命名会话",
    responses={400: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
)
async def rename_session(
    session_id: str, body: SessionUpdate, auth: ProjectAuth, db: DbDep
) -> SessionOut:
    title = body.title.strip()
    if not title:
        raise AppError(ErrorCode.INVALID_REQUEST, "标题不能为空")
    row = await SessionRepository(db).rename(
        session_id, project_id=str(auth.project["id"]), title=title
    )
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, f"session 不存在：{session_id}")
    return _session_out(row)


@router.delete(
    "/{session_id}",
    status_code=204,
    summary="删除会话（级联删除消息与 runs；用量记录保留）",
    responses={404: {"model": ErrorEnvelope}},
)
async def delete_session(session_id: str, auth: ProjectAuth, db: DbDep) -> None:
    deleted = await SessionRepository(db).delete(session_id, project_id=str(auth.project["id"]))
    if not deleted:
        raise AppError(ErrorCode.NOT_FOUND, f"session 不存在：{session_id}")


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
        # assistant 的工具调用 wire 列表原样透出（控制台据此重建历史工具卡）
        tool_calls = None
        if row["tool_calls_json"]:
            tool_calls = json.loads(row["tool_calls_json"])
        items.append(
            MessageOut(
                id=str(row["id"]),
                seq=int(row["seq"]),
                role=str(row["role"]),
                content=text,
                tool_calls=tool_calls,
                tool_call_id=row["tool_call_id"],
                created_at=str(row["created_at"]),
            )
        )
    return MessagePage(items=items, has_more=has_more)
