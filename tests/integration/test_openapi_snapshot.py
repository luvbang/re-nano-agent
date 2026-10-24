"""OpenAPI 契约快照（M3 技术债）：接口变更必须显式更新快照。

快照文件：tests/fixtures/openapi.json。重生成：
    uv run python tests/integration/test_openapi_snapshot.py --regen
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agentd.config import Settings
from agentd.main import create_app

SNAPSHOT = Path(__file__).parent.parent / "fixtures" / "openapi.json"


def build_schema() -> dict[str, object]:
    settings = Settings(env="test", log_level="WARNING", admin_api_key="snap")
    app = create_app(settings)
    schema = app.openapi()
    return schema


def canonical(schema: dict[str, object]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def test_openapi_matches_snapshot() -> None:
    schema = build_schema()
    if not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(canonical(schema), encoding="utf-8")
        raise AssertionError(f"快照不存在，已生成初版：{SNAPSHOT}（提交它）")
    expected = SNAPSHOT.read_text(encoding="utf-8")
    actual = canonical(schema)
    if actual != expected:
        hint = SNAPSHOT.with_suffix(".actual.json")
        hint.write_text(actual, encoding="utf-8")
        raise AssertionError(
            "OpenAPI 契约与快照不一致（已写出 "
            f"{hint}）。确认是预期变更后重生成快照：\n"
            "    uv run python tests/integration/test_openapi_snapshot.py --regen"
        )
    # 关键端点在位（防意外整段消失的底线检查）
    paths: dict[str, object] = schema.get("paths", {})  # type: ignore[assignment]
    for must in (
        "/v1/sessions",
        "/v1/sessions/{session_id}/runs",
        "/v1/runs/{run_id}/events",
        "/v1/admin/keys",
        "/metrics",
    ):
        assert must in paths, f"契约缺失端点：{must}"


if __name__ == "__main__" and "--regen" in sys.argv:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(canonical(build_schema()), encoding="utf-8")
    print(f"snapshot regenerated: {SNAPSHOT}")
