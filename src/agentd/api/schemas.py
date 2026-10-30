"""Response models for the ops endpoints (M0). Business models land with M3."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    version: str = Field(examples=["0.1.0"])
    uptime_s: float = Field(examples=[12.34])


class ReadyResponse(BaseModel):
    status: str = Field(examples=["ready"])
    checks: dict[str, str] = Field(examples=[{"db": "ok"}])


class ErrorBody(BaseModel):
    code: str = Field(examples=["invalid_request"])
    message: str = Field(examples=["Request validation failed"])
    retryable: bool = Field(examples=[False])
    request_id: str = Field(examples=["req_1a2b3c4d5e6f7a8b"])
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


# ---------- v1 平台资源（M3 D1） ----------


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    external_user_id: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SessionOut(BaseModel):
    id: str
    project_id: str
    title: str | None
    external_user_id: str | None
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: str
    seq: int
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None
    created_at: str


class MessagePage(BaseModel):
    items: list[MessageOut]
    has_more: bool


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, value: str) -> str:
        """全空白 content 在 schema 层就拒掉（400 invalid_request）。

        原先只靠 `min_length=1` 挡不住 "   "：长度合规、strip 后为空，一路落到
        MemoryService.add 抛裸 ValueError，被兜底 handler 变成 500。strip 后的值
        直接作为规范化输入保存（与 PATCH /v1/sessions 对 title 的处理一致）。
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("content 不能为空或全空白")
        return stripped


class MemoryOut(BaseModel):
    id: str
    content: str
    status: str
    score: float
    created_at: str
    last_seen_at: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProjectOut(BaseModel):
    id: str
    name: str
    created_at: str


class ApiKeyCreate(BaseModel):
    project_id: str
    name: str | None = Field(default=None, max_length=100)
    rate_limit_per_min: int = Field(default=60, ge=1, le=10_000)


class ApiKeyOut(BaseModel):
    id: str
    project_id: str
    name: str | None
    key_prefix: str
    scopes: str
    rate_limit_per_min: int
    revoked_at: str | None
    created_at: str


class ApiKeyCreated(BaseModel):
    key: str  # 明文仅此一次返回
    detail: ApiKeyOut
