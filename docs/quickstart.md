# Quickstart（目标 5 分钟接入）

> 面向外部接入方：只靠本文档，从拿 Key 到收到第一条流式回答。
> 全部命令可复制；遇到任何卡点请记录下来反馈给平台管理员（我们要的正是这个反馈）。

## 0. 前置

- Python ≥ 3.12
- 平台地址（下称 `BASE_URL`，形如 `https://agent.example.com`）与你的 API Key（`agd_` 开头）

## 1. 安装 SDK

```bash
# 从平台仓库安装（PyPI 发布前）
pip install git+https://github.com/luvbang/re-nano-agent.git#subdirectory=sdk/agentd_client
```

## 2. 第一条流式回答（Python）

```python
import asyncio
from agentd_client import AsyncClient

async def main():
    client = AsyncClient("https://agent.example.com", api_key="agd_你的key")
    session = await client.create_session(title="first-run")
    created = await client.create_run(session["id"], input="用一句话介绍你自己")
    answer = ""
    async for event in client.stream(created["run_id"]):
        if event.type == "message.delta":
            print(event.data["delta"], end="", flush=True)
        elif event.type == "message.completed":
            answer = event.data["content"]   # 以 completed 为准
    print("\n---", answer[:50])
    await client.aclose()

asyncio.run(main())
```

同步版（同样能力）：

```python
from agentd_client import Client

with Client("https://agent.example.com", api_key="agd_你的key") as client:
    session = client.create_session()
    run = client.create_run(session["id"], input="现在几点了？")
    for event in client.stream(run["run_id"]):
        if event.type == "tool.started":
            print("[tool]", event.data["name"])
        elif event.type == "message.completed":
            print("answer:", event.data["content"])
```

## 3. curl 裸调用（不装任何东西）

```bash
BASE=https://agent.example.com
KEY=agd_你的key

# 会话
SID=$(curl -fsS -X POST $BASE/v1/sessions -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{"title":"curl"}' | python -c 'import json,sys;print(json.load(sys.stdin)["id"])')

# run + SSE（-N 关缓冲）
RID=$(curl -fsS -X POST $BASE/v1/sessions/$SID/runs -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{"input":"你好"}' | python -c 'import json,sys;print(json.load(sys.stdin)["run_id"])')
curl -N -sS "$BASE/v1/runs/$RID/events" -H "Authorization: Bearer $KEY"
```

## 4. 常用能力速查

| 能力 | 用法 |
|---|---|
| 历史消息 | `client.list_messages(session_id, limit=50, before_seq=None)`（seq 升序，返回 `{items, has_more}`；每条消息含 `tool_calls`，可据此重建历史工具调用） |
| 取消 run | `client.cancel_run(run_id)`（终态后取消会 409） |
| 断线续传 | `client.stream()` 自动带 Last-Event-ID 重连；增量不重放，以 `message.completed` 为准 |
| 用量 | `client.usage(group_by="day", date_from="2026-10-01", date_to="2026-10-31")`（`group_by` 取 `"day"` 或 `"model"`；日期参数是服务端字段名） |
| 会话管理 | `client.rename_session(sid, title="新名字")` 改标题；`client.delete_session(sid)` 删除（204，级联清消息与 runs，用量记录保留） |
| 选模型 | `POST /v1/sessions/{id}/runs` 带 `{"model": "..."}`；先 `GET /v1/models` 查可用值，传了不认识的模型得 400 `invalid_request`。**SDK 的 `create_run()` 暂不支持 `model` 形参**，需要时直接发 HTTP |
| 错误 | 类型化异常：`AuthenticationError` / `RateLimitError(retry_after_s)` / `ModelError`…；`retryable` 的自动重试 |
| 工具 | 平台内置 echo/get_time/read_file/write_file/edit_file/list_dir/web_fetch（平台还可挂 MCP 工具）；回答里 `tool.started/completed` 事件可见，`tool.completed` 带 `result` 输出预览 |
| 长期记忆 | `client.create_memory(content="用户偏好深色主题")` 写入；`client.list_memories(status="active")` 列出（`status=None` 含 archived）；`client.archive_memory(mid)` 归档（软删，幂等）。project 作用域，跨 project 一律 404 |
| 记忆的三个坑 | ① `status="archived"` 是**先取最近 limit 条再按状态过滤**，active 多时会漏，拿全请调大 `limit`；② 同内容 `create_memory` 不新建、返回**既有行**，HTTP 仍是 201，判断是否新建要比对 id；③ `limit` 越界或 content 为空/纯空白，SDK 本地抛 `ValidationError`、不发请求 |

## 5. 排障

- `401 unauthorized`：key 错或已被撤销（撤销立即生效）
- `409 conflict`：同一 session 已有 run 在跑（per-session 串行），等它完成或换 session
- `429 rate_limited`：带 `Retry-After` 秒数；SDK 自动退避重试
- `502 model_error`：平台侧模型未配置或上游故障，可重试
- `400 invalid_request` 且消息里有「未知模型」：`model` 与平台模型不一致，用 `GET /v1/models` 取可用值

## 接入计时（管理员填写）

开始 ___:___ → 收到第一条流式回答 ___:___，耗时 ___ 分钟。卡点记录：
