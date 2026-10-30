# agentd-client

agentd 平台的 Python SDK（同步 + 异步、SSE 流式迭代、类型化错误、自动重试）。用法见仓库根 `examples/` 与 `docs/quickstart.md`。

```bash
pip install agentd-client            # 需要 Python >= 3.12
```

## 快速开始

```python
from agentd_client import Client

with Client("http://127.0.0.1:8000", api_key="agd_...") as client:
    session = client.create_session(title="demo")
    run = client.create_run(session["id"], input="你好")
    for event in client.stream(run["run_id"]):
        if event.type == "message.delta":
            print(event.data["delta"], end="")
```

异步版把 `Client` 换成 `AsyncClient`，方法同名，`async with` 收尾。

## 长期记忆（/v1/memories）

记忆是 **project 作用域**的：同一个 project 的 key 共享，跨 project 互不可见（跨 project 归档一律 404，不泄漏存在性）。

```python
# 写入：服务端同内容去重——已有 active 同内容行时不新增，只刷新 last_seen_at，
# 返回的 id 与既有行相同（HTTP 仍是 201，无法从响应区分新建还是命中）。
row = client.create_memory(content="用户偏好深色主题")
print(row["id"], row["status"])          # mem_xxx active

# 列出：status=None 表示全部状态；status 可选 "active" / "archived"。
# limit 1..200（默认 100），越界会抛 ValidationError——本地就拦，不发请求。
active = client.list_memories(status="active")
for m in active:
    print(m["content"], m["score"], m["last_seen_at"])

# 归档（软删除）：置 status=archived，不物理删除，Dream 与审计留痕。
# 服务端 204 无响应体 → SDK 统一返回 {}；对已归档的 id 再次归档是幂等的，不存在的 id 抛 NotFoundError。
client.archive_memory(row["id"])
```

异步版同名：

```python
import asyncio
from agentd_client import AsyncClient

async def main() -> None:
    async with AsyncClient("http://127.0.0.1:8000", api_key="agd_...") as client:
        await client.create_memory(content="项目使用 SQLite")
        rows = await client.list_memories(status="active")
        for m in rows:
            print(m["content"])

asyncio.run(main())
```

坑位提醒：

- `status="archived"` 是「先取最近 limit 条，再按状态过滤」，active 记忆多时可能被挤出窗口，拿不全就调大 `limit`（上限 200）。
- `content` 会被服务端 strip 后比较；**纯空白** content 服务端会 500，SDK 提前抛 `ValidationError` 拦住。长度上限 2000 字符（服务端校验，越界返回 400 `invalid_request`）。

## 错误与重试

所有错误都是 `AgentdError` 子类，由服务端错误信封统一映射（`ValidationError` / `AuthenticationError` / `NotFoundError` / `RateLimitError` / `NetworkError` …）；
`retryable` 错误自动指数退避重试（优先用 `Retry-After`），`create_run` 自动生成 `Idempotency-Key` 保证重试安全。

```python
from agentd_client import NotFoundError

try:
    client.archive_memory("mem_nope")
except NotFoundError:
    print("记忆不存在或属于其他 project")
```

## 类型

包内含 `py.typed`，下游 mypy/pyright 直接获得完整类型信息；公开 API 只增不改（向后兼容）。
