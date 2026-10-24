"""SDK 异步流式示例（M4）：async/await 消费 SSE。

    uv run python examples/async_stream.py <base_url> <agd_xxx>
"""

from __future__ import annotations

import asyncio
import sys

from agentd import AsyncClient


async def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    api_key = sys.argv[2] if len(sys.argv) > 2 else ""
    if not api_key:
        print("用法：python examples/async_stream.py <base_url> <agd_xxx>")
        return 2

    async with AsyncClient(base_url=base_url, api_key=api_key) as client:
        session = await client.sessions.create(title="async-quickstart")
        stream = await client.runs.stream_async(session.id, input="你好，介绍一下你自己")
        async with stream:
            async for event in stream:
                if event.type == "message.delta":
                    print(event.delta, end="", flush=True)
            print(f"\n[完成] status={stream.result.status if stream.result else '?'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
