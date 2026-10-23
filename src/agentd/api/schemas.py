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
