"""run_manager.serialize_event 的线上契约（v0.2-4）：tool.completed 携带结果预览并封顶。"""

from agentd.runtime.events import ToolCompleted
from agentd.services.run_manager import _TOOL_RESULT_PREVIEW_CAP, serialize_event


def test_tool_completed_carries_result_preview() -> None:
    name, payload = serialize_event(
        ToolCompleted(
            tool_call_id="t_1", name="read_file", status="ok", duration_ms=12, result="hello"
        )
    )
    assert name == "tool.completed"
    assert payload["result"] == "hello"
    assert payload["status"] == "ok"


def test_tool_completed_result_capped_with_marker() -> None:
    big = "x" * (_TOOL_RESULT_PREVIEW_CAP + 500)
    _, payload = serialize_event(
        ToolCompleted(tool_call_id="t_1", name="read_file", status="ok", duration_ms=1, result=big)
    )
    result = payload["result"]
    assert len(result) < len(big)
    assert result.startswith("x" * _TOOL_RESULT_PREVIEW_CAP)
    assert "已截断" in result and str(len(big)) in result
