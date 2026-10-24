"""Response models for ops + /v1 endpoints. Business models align with the frozen contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


# ---------- /v1（M3，契约 docs/api-contract.md §2） ----------


class CreateSessionIn(BaseModel):
    external_user_id: str | None = None
    title: str | None = None
    metadata: dict[str, Any] | None = None


class SessionOut(BaseModel):
    id: str
    external_user_id: str | None
    title: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class ToolCallFunctionOut(BaseModel):
    name: str
    arguments: str


class ToolCallOut(BaseModel):
    id: str
    type: str
    function: ToolCallFunctionOut


class MessageOut(BaseModel):
    id: str
    seq: int
    role: str
    content: str | None
    tool_calls: list[ToolCallOut] | None
    tool_call_id: str | None
    created_at: str


class CreateRunIn(BaseModel):
    input: str = Field(min_length=1)
    model: str | None = None
    metadata: dict[str, Any] | None = None


class RunIdOut(BaseModel):
    run_id: str


class RunErrorOut(BaseModel):
    code: str
    message: str
    retryable: bool


class RunOut(BaseModel):
    id: str
    session_id: str
    status: str
    model: str | None
    input_tokens: int
    output_tokens: int
    error: RunErrorOut | None
    created_at: str
    finished_at: str | None


class KeyOut(BaseModel):
    id: str
    key_prefix: str
    name: str | None
    scopes: str
    rate_limit_per_min: int
    revoked_at: str | None
    created_at: str


class CreateKeyIn(BaseModel):
    name: str | None = None
    rate_limit_per_min: int = Field(default=60, ge=1, le=6000)


class CreatedKeyOut(BaseModel):
    key: KeyOut
    secret: str


class UsageItemOut(BaseModel):
    group: str
    runs: int
    input_tokens: int
    output_tokens: int


class UsageOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    group_by: str
    items: list[UsageItemOut]


class ModelOut(BaseModel):
    id: str
    tools: list[str]


class ModelsOut(BaseModel):
    items: list[ModelOut]
