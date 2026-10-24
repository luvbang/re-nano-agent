"""SDK 异步示例（M4）：创建会话 → 流式 run → 查用量。

    AGENTD_BASE_URL=http://127.0.0.1:8000 AGENTD_API_KEY=agd_... \
        uv run python examples/sdk_quickstart.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from agentd_client import AsyncClient


async def main() -> int:
    base_url = os.environ.get("AGENTD_BASE_URL", "http://127.0.0.1:8000")
    api_key = os.environ.get("AGENTD_API_KEY", "")
    if not api_key:
        print("请设置 AGENTD_API_KEY（见 docs/quickstart.md）", file=sys.stderr)
        return 2

    async with AsyncClient(base_url, api_key=api_key) as client:
        session = await client.create_session(title="sdk-demo")
        print(f"session={session['id']}")

        created = await client.create_run(session["id"], input="用一句话介绍你自己")
        run_id = created["run_id"]
        answer = ""
        async for event in client.stream(run_id):
            if event.type == "message.delta":
                print(event.data["delta"], end="", flush=True)
            elif event.type == "message.completed":
                answer = event.data["content"]  # 以 completed 为准
            elif event.type == "tool.started":
                print(f"\n[tool] {event.data['name']}")
        print()
        print(f"answer={answer[:80]}...")

        run = await client.get_run(run_id)
        print(f"status={run['status']} usage={run['input_tokens']}+{run['output_tokens']}")
        usage = await client.usage(group_by="model")
        print(f"usage={usage['items']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
