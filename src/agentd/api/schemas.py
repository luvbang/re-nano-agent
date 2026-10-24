"""Response models for the ops endpoints (M0). Business models land with M3."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    tool_call_id: str | None
    created_at: str


class MessagePage(BaseModel):
    items: list[MessageOut]
    has_more: bool


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
