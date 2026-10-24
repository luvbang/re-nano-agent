"""统一错误信封与异常处理器。

对外契约（docs/api-contract.md §4）：
    {"error": {"code": "...", "message": "...", "retryable": bool, "request_id": "req_..."}}
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agentd.log import request_id_var

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    MODEL_ERROR = "model_error"
    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


#: code -> (http status, retryable)
_SPEC: dict[ErrorCode, tuple[int, bool]] = {
    ErrorCode.INVALID_REQUEST: (400, False),
    ErrorCode.UNAUTHORIZED: (401, False),
    ErrorCode.FORBIDDEN: (403, False),
    ErrorCode.NOT_FOUND: (404, False),
    ErrorCode.CONFLICT: (409, False),
    ErrorCode.RATE_LIMITED: (429, True),
    ErrorCode.MODEL_ERROR: (502, True),
    ErrorCode.TOOL_ERROR: (422, False),
    ErrorCode.TIMEOUT: (504, True),
    ErrorCode.INTERNAL: (500, False),
}


class AppError(Exception):
    """业务异常。抛出即被转换为标准错误信封，不返回堆栈。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}
        self.status_code, self.retryable = _SPEC[code]


def error_response(
    *,
    code: ErrorCode,
    message: str,
    status_code: int | None = None,
    retryable: bool | None = None,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    spec_status, spec_retryable = _SPEC[code]
    body: dict[str, Any] = {
        "code": code.value,
        "message": message,
        "retryable": spec_retryable if retryable is None else retryable,
        "request_id": request_id_var.get() or "",
    }
    if details is not None:
        body["details"] = details
    return JSONResponse(
        status_code=spec_status if status_code is None else status_code,
        content={"error": body},
        headers=headers,
    )


#: 框架层 4xx/5xx -> 契约错误码
_HTTP_STATUS_TO_CODE = {
    400: ErrorCode.INVALID_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.INVALID_REQUEST,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.INVALID_REQUEST,
    422: ErrorCode.INVALID_REQUEST,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL,
    502: ErrorCode.MODEL_ERROR,
    503: ErrorCode.INTERNAL,
    504: ErrorCode.TIMEOUT,
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "request.failed", extra={"code": exc.code.value, "status": exc.status_code}
        )
        return error_response(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            retryable=exc.retryable,
            details=exc.details,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 只回显字段路径与原因，避免把整段输入写进响应
        details = [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg", "")} for err in exc.errors()
        ]
        return error_response(
            code=ErrorCode.INVALID_REQUEST, message="Request validation failed", details=details
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL)
        return error_response(
            code=code,
            message=str(exc.detail),
            status_code=exc.status_code,
            headers=dict(exc.headers or {}),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("request.unhandled", extra={"error_type": type(exc).__name__})
        return error_response(code=ErrorCode.INTERNAL, message="Internal server error")
