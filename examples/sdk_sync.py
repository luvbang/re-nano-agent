"""SDK 同步示例（M4）：与异步示例同一流程，展示同步 API。

    AGENTD_BASE_URL=http://127.0.0.1:8000 AGENTD_API_KEY=agd_... \
        uv run python examples/sdk_sync.py
"""

from __future__ import annotations

import os
import sys

from agentd_client import Client


def main() -> int:
    base_url = os.environ.get("AGENTD_BASE_URL", "http://127.0.0.1:8000")
    api_key = os.environ.get("AGENTD_API_KEY", "")
    if not api_key:
        print("请设置 AGENTD_API_KEY（见 docs/quickstart.md）", file=sys.stderr)
        return 2

    with Client(base_url, api_key=api_key) as client:
        session = client.create_session(title="sdk-sync-demo")
        created = client.create_run(session["id"], input="现在几点了？")
        for event in client.stream(created["run_id"]):
            if event.type == "tool.started":
                print(f"[tool] {event.data['name']} {event.data['args']}")
            elif event.type == "tool.completed":
                data = event.data
                print(f"[tool] {data['name']} {data['status']} {data['duration_ms']}ms")
            elif event.type == "message.completed":
                print("answer:", event.data["content"])
        run = client.get_run(created["run_id"])
        print(f"status={run['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
