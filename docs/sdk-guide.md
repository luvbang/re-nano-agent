# SDK 指南（agentd-client）

> Python ≥ 3.12。同步与异步同能力：会话、流式 run、取消、用量、类型化错误、自动重试。

## 安装

```bash
pip install git+https://github.com/luvbang/re-nano-agent.git#subdirectory=sdk/agentd_client
```

仓库内开发：workspace 成员（`uv sync --all-groups` 后 `import agentd_client`）。

## 快速开始（异步）

```python
import asyncio
from agentd_client import AsyncClient

async def main():
    client = AsyncClient("https://agent.example.com", api_key="agd_...")
    session = await client.create_session(title="demo")
    created = await client.create_run(session["id"], input="总结一下这个项目")

    answer = ""
    async for event in client.stream(created["run_id"]):
        if event.type == "message.delta":
            print(event.data["delta"], end="", flush=True)
        elif event.type == "tool.started":
            print(f"\n[tool] {event.data['name']}")
        elif event.type == "message.completed":
            answer = event.data["content"]   # 契约规定以此为准
    print("\n答案：", answer)
    await client.aclose()

asyncio.run(main())
```

## 同步版

```python
from agentd_client import Client

with Client("https://agent.example.com", api_key="agd_...") as client:
    session = client.create_session()
    run = client.create_run(session["id"], input="现在几点了？")
    for event in client.stream(run["run_id"]):
        if event.type == "tool.completed":
            print("[tool]", event.data["name"], event.data["status"])
        elif event.type == "message.completed":
            print("answer:", event.data["content"])
```

同步实现：专属后台事件循环线程 + 线程安全队列交接 SSE；`close()` 可省略（daemon 线程）。

## 关键语义

| 主题 | 行为 |
|---|---|
| SSE 续传 | 断流自动带 `Last-Event-ID` 重连（≤3 次）；增量不重放，**以 `message.completed` 全文为准** |
| 自动重试 | `retryable` 错误指数退避（429 的 `Retry-After` 优先），默认最多 3 次 |
| 幂等 | `create_run` 自动生成 `Idempotency-Key`（可显式传 `idempotency_key=`），重试不会重复创建 run |
| 错误 | `AuthenticationError` / `RateLimitError`（`.retry_after_s`）/ `ModelError` / `ConflictError`…；`NetworkError` 覆盖传输层 |
| 工具 | 平台内置 echo/get_time/read_file/write_file/edit_file/list_dir/web_fetch；事件里 `tool.started/completed` 可见 |

## 常用 API 一览

```python
client.create_session(title=..., external_user_id=...)   # 建会话
client.get_session(sid) / client.list_messages(sid, limit=50, before_seq=None)
client.create_run(sid, input=..., idempotency_key=None)  # 202 {run_id, status}
client.get_run(rid) / client.cancel_run(rid)             # 终态后取消得 409
client.stream(rid)                                        # SSE 事件迭代器
client.usage(group_by="day"|"model", date_from=..., date_to=...)
client.models()
```

## 排障

- 同一 session 并发 run → `409 ConflictError`（per-session 串行），等上一轮完成
- 长输入被拒 → `413`（默认 1MB 上限）
- 完整可运行示例见仓库 `examples/sdk_quickstart.py`（异步）与 `examples/sdk_sync.py`
