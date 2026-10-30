# SDK 指南（agentd-client）

> Python ≥ 3.12。同步与异步同能力：会话（含重命名/删除）、流式 run、取消、用量、类型化错误、自动重试。

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
            print("[tool]", event.data["name"], event.data["status"], event.data.get("result"))
        elif event.type == "message.completed":
            print("answer:", event.data["content"])
```

同步实现：专属后台事件循环线程 + 线程安全队列交接 SSE；`close()` 可省略（daemon 线程）。

## 会话管理

```python
session = client.create_session(title="草稿", external_user_id="u_123")
detail  = client.get_session(session["id"])                  # {"id","project_id","title",...}
renamed = client.rename_session(session["id"], title="周报草稿")   # PATCH /v1/sessions/{id}
client.delete_session(session["id"])                          # DELETE，204 无响应体 → 返回 {}
```

- `rename_session()` 走 `PATCH /v1/sessions/{id}`，`title` 是**仅限关键字参数**，长度 1–200；空/全空白会得到 `ValidationError`（400 `invalid_request`），会话不存在或跨 project 得 `NotFoundError`（404）。
- `delete_session()` 走 `DELETE /v1/sessions/{id}`，服务端 204 无响应体，SDK 因此返回空 dict（不要读字段）。删除会级联清掉该会话的消息与 runs 及其事件，usage 记录保留（`run_id` 置空），对账不受影响。
- 两个方法在 `AsyncClient` 与 `Client` 上都有，签名一致（同步版只是阻塞封装）。

## 选模型

服务端已支持请求级 `model`（`POST /v1/sessions/{id}/runs` 的 body 字段，见 `docs/api-reference.md`），但 **SDK 的 `create_run()` 目前还没有 `model` 形参**（`AsyncClient` 与 `Client` 都只有 `input` / `idempotency_key`），它固定只发 `{"input": ...}`。想选模型有两条路：

```python
# 1) 直接用 HTTP（错误仍是标准错误信封，可照常解析）
import httpx

async with httpx.AsyncClient(
    base_url=BASE, headers={"Authorization": f"Bearer {key}"}
) as h:
    r = await h.post(f"/v1/sessions/{sid}/runs", json={"input": "你好", "model": "..."})
    run_id = r.json()["run_id"]

# 2) 不传 model，用平台默认模型（最常见）
client.create_run(session_id, input="你好")
```

- 平台当前是**单模型配置**：`model` 必须与平台模型一致（来自 `AGENTD_LLM_MODEL`，也可用 `client.models()` 查 `[{"id": ..., "tools": True}]`），否则服务端返回 400 `invalid_request`。多 provider 放开后语义不变（不认识就 400）。
- 选定的模型落在 run 档上：`client.get_run(rid)["model"]` 与 `client.usage(group_by="model")` 都能看到。

## 关键语义

| 主题 | 行为 |
|---|---|
| SSE 续传 | 断流自动带 `Last-Event-ID` 重连（≤3 次）；增量不重放，**以 `message.completed` 全文为准** |
| 自动重试 | `retryable` 错误指数退避（429 的 `Retry-After` 优先），默认最多 3 次 |
| 幂等 | `create_run` 自动生成 `Idempotency-Key`（可显式传 `idempotency_key=`），重试不会重复创建 run |
| 错误 | `AuthenticationError` / `RateLimitError`（`.retry_after_s`）/ `ModelError` / `ConflictError` / `ValidationError` / `NotFoundError` / `PermissionDeniedError` / `ServerTimeoutError`；`NetworkError` 覆盖传输层 |
| 工具 | 平台内置 echo/get_time/read_file/write_file/edit_file/list_dir/web_fetch（可配 MCP 工具）；事件里 `tool.started/completed` 可见，`tool.completed` 带 `result` 输出预览（≤2000 字符，超长截断标注） |

## 常用 API 一览

```python
client.create_session(title=..., external_user_id=...)   # 建会话
client.get_session(sid) / client.list_messages(sid, limit=50, before_seq=None)
client.rename_session(sid, title="新名字")                # PATCH，返回更新后的会话
client.delete_session(sid)                                # DELETE 204，返回 {}
client.create_run(sid, input=..., idempotency_key=None)  # 202 {run_id, status}；暂不支持 model 形参
client.get_run(rid) / client.cancel_run(rid)             # 终态后取消得 409
client.stream(rid)                                        # SSE 事件迭代器
client.usage(group_by="day"|"model", date_from=..., date_to=...)
client.models()
```

## 尚未覆盖的能力

长期记忆（`/v1/memories`）**目前只有 HTTP 端点，SDK 没有对应方法**——不要去找 `client.memories` / `client.create_memory`，它们不存在。需要时按 `docs/api-reference.md` 的记忆段直接发 HTTP，或等后续版本补 SDK 封装。同理，MCP 是服务端配置（`AGENTD_MCP_SERVERS`），SDK 侧不需要也不存在开关。

## 排障

- 同一 session 并发 run → `409 ConflictError`（per-session 串行），等上一轮完成
- 长输入被拒 → `413`（默认 1MB 上限）
- 传了 `model` 但返回 400 `invalid_request` → 与平台模型不一致，用 `client.models()` 取可用值
- 完整可运行示例见仓库 `examples/sdk_quickstart.py`（异步）与 `examples/sdk_sync.py`
