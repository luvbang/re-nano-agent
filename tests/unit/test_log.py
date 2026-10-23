from __future__ import annotations

import json
import logging

from agentd.log import JsonFormatter, request_id_var, run_id_var


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="agentd.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_is_one_line_with_level() -> None:
    line = JsonFormatter().format(_record())
    assert "\n" not in line
    payload = json.loads(line)
    assert payload["msg"] == "hello world"
    assert payload["level"] == "info"
    assert payload["logger"] == "agentd.test"


def test_request_and_run_id_come_from_contextvars() -> None:
    req_token = request_id_var.set("req_deadbeef")
    run_token = run_id_var.set("r_123")
    try:
        payload = json.loads(JsonFormatter().format(_record()))
    finally:
        run_id_var.reset(run_token)
        request_id_var.reset(req_token)
    assert payload["request_id"] == "req_deadbeef"
    assert payload["run_id"] == "r_123"


def test_business_extras_are_preserved() -> None:
    payload = json.loads(JsonFormatter().format(_record(status=201, duration_ms=1.5)))
    assert payload["status"] == 201
    assert payload["duration_ms"] == 1.5
