"""JSON structured logging with request_id / run_id correlation.

Uses stdlib logging only: one JSON object per line on stdout, so Docker log drivers
and any log shipper can parse it without an extra dependency.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)

# LogRecord 自带字段，其余字段视作业务附加字段（extra=...）
_RESERVED = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
        "pathname", "process", "processName", "relativeCreated", "stack_info",
        "thread", "threadName", "taskName",
    }
)


_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Bearer token（Authorization 头）
    (re.compile(r"(?i)\b(bearer)\s+\S+"), r"\1 ***"),
    # JSON 字段里的密钥类值（含转义引号的嵌套 JSON）
    (re.compile(r'((?:\\?")(?:api_key|token|password|secret)(?:\\?")\s*:\s*(?:\\?"))[^"\\]*(?:\\?")'),
     r"\1***"),
    # agd_ 开头的 API key 明文（保留前缀便于对账）
    (re.compile(r"agd_[A-Za-z0-9]{6,}"), "agd_***"),
)


def redact(text: str) -> str:
    """脱敏（M4 D3）：日志输出前擦掉 key/token/密码模式；不影响原始数据。"""
    for pattern, replacement in _REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        run_id = getattr(record, "run_id", None) or run_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        if run_id:
            payload["run_id"] = run_id
        for key, value in record.__dict__.items():
            if key in _RESERVED or key in payload or key.startswith("_"):
                continue
            if key.startswith("color_"):  # uvicorn 的 ANSI 包装，不是业务字段
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, ensure_ascii=False, default=str))


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        return f"{base} request_id={request_id}" if request_id else base


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Idempotent: safe to call from create_app() and from the CLI."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(PlainFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.handlers = [handler]
    # uvicorn 自己装 handler 会破坏 JSON 单行结构，统一交给 root；
    # access 日志由 RequestIDMiddleware 输出（带 request_id），这里彻底关掉避免重复。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
