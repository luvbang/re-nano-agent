# API 契约草案（M0 冻结，后续只加不破）

> 冻结时间：M0-D1。后续里程碑只允许**新增**字段/端点，不允许修改已有语义。
> 变更流程：改 OpenAPI 快照 + 更新本文档 + CHANGELOG 标注 breaking。

## 1. 认证与资源模型

- 请求头：`Authorization: Bearer agd_<key>`。
- key 绑定唯一 project；服务端只存 `sha256(key)` + 前 12 位 prefix（展示用）。
- 所有业务资源嵌套在 project 下：`/v1/sessions`、`/v1/runs`、`/v1/usage`。
- 管理操作（创建/撤销 key）用管理员 key（环境变量或独立 scope），v0.1 不做用户体系。
- 每个请求可带 `X-Request-Id`；未带则服务端生成 `req_<hex>`，响应头回显，日志与错误体贯穿。

## 2. 核心端点

```http
POST   /v1/sessions                       # {external_user_id?, metadata?, title?} -> {id, ...}
GET    /v1/sessions/{id}                  # 会话信息
PATCH  /v1/sessions/{id}                  # {title} 重命名 -> {id, ...}
DELETE /v1/sessions/{id}                  # 204；级联删消息与 runs，用量记录保留
GET    /v1/sessions/{id}/messages         # ?limit=&before_seq= 分页
POST   /v1/sessions/{id}/runs             # {input, stream?, model?, tools?, metadata?}
                                          # -> 202 {run_id}（配合 events 端点）
GET    /v1/runs/{id}                      # {status, usage, error, ...}
GET    /v1/runs/{id}/events               # SSE；支持 Last-Event-ID
POST   /v1/runs/{id}/cancel               # 取消
GET    /v1/models                         # 可用模型与能力
GET    /v1/usage                          # ?group_by=day|model&date_from=&date_to=
GET    /v1/admin/keys                     # 管理员：创建/撤销 key
GET    /healthz  /readyz  /metrics        # 运维
```

> 参数名以实现为准（M0 草案里的 `before` / `from` / `to` 落地时定为 `before_seq` /
> `date_from` / `date_to`，见 `src/agentd/api/routes/sessions.py` 与 `routes/platform.py`）。
> `tools` 为契约保留位，当前 `RunCreate` 未接收该字段（工具集由服务端配置决定）。

M0 已实现：`/healthz`、`/readyz`。M3 已实现：`/v1/sessions*`、`/v1/sessions/{id}/runs`、`/v1/runs/{id}`、`/v1/runs/{id}/events`、`/v1/runs/{id}/cancel`、`/v1/models`、`/v1/usage`、`/v1/admin/projects`、`/v1/admin/keys`、`/v1/admin/keys/{id}/revoke`、`/v1/admin/stats`（本节为 M3 新增的管理端点）。M4 落地 SDK；未配置模型 key 时 runs 相关端点返回 502 model_error。

v0.2 增量（只加不破）：`PATCH/DELETE /v1/sessions/{id}`（会话重命名/删除）、
`GET/POST /v1/memories` 与 `DELETE /v1/memories/{id}`（长期记忆）、run 创建时的
请求级 `model`、`messages[].tool_calls` 字段、`tool.completed.result` 事件字段。
全量清单与错误码见 `docs/api-reference.md`（含实际路由与状态码）。

### 2.1 运维端点（M0 已实现）

```http
GET /healthz
200 {"status":"ok","version":"0.1.0","uptime_s":12.34}

GET /readyz
200 {"status":"ready","checks":{"db":"ok"}}
503 {"status":"not_ready","checks":{"db":"unavailable"}}
```

`/healthz` 只表达进程存活（不碰 IO）；`/readyz` 检查 DB 可写可读，用于负载均衡摘流。

### 2.2 长期记忆（v0.2-3 已实现；project 作用域，Bearer key 鉴权 + 限流）

```http
GET /v1/memories?status=active&limit=100
200 [{"id":"mem_...","content":"...","status":"active","score":1.0,
      "created_at":"...","last_seen_at":"..."}]

POST /v1/memories
201 {"id":"mem_...","content":"用户偏好深色主题","status":"active",...}    # 同内容去重（bump last_seen）
400 {"error":{"code":"invalid_request",...}}                              # 空/超长内容

DELETE /v1/memories/{id}
204                                                                       # 归档（幂等；跨 project 一律 404）
```

注入语义：run 组装上下文时 active 记忆按 score/last_seen 排序、预算内并入
system（实现见 `src/agentd/services/memory.py` 的 `prompt_block()`；端点与错误码的
速查见 `docs/api-reference.md` §长期记忆）。整理语义：`agentd dream`
做规则版去重与陈旧归档（LLM 语义合并留待后续）。

## 3. SSE 事件（对外契约）

```text
event: run.started        data: {"seq":1,"run_id":"r_...","session_id":"s_..."}
event: message.delta      data: {"seq":2,"delta":"你"}
event: reasoning.delta    data: {"seq":3,"delta":"..."}          # 若模型支持
event: tool.started       data: {"seq":4,"tool_call_id":"t_1","name":"read_file","args":{...}}
event: tool.completed     data: {"seq":5,"tool_call_id":"t_1","status":"ok","duration_ms":12,"result":"..."}  # v0.2-4 增补 result：工具输出预览（≤2000 字符，超长截断标注）
event: message.completed  data: {"seq":6,"content":"完整回答","usage":{"input_tokens":...}}
event: run.completed      data: {"seq":7,"run_id":"r_...","usage":{...}}
event: run.failed         data: {"seq":8,"error":{"code":"model_error","message":"...","retryable":true}}
event: run.cancelled      data: {"seq":9,"run_id":"r_...","reason":"cancelled"}   # M3 新增
: ping                                                                # 每 15s
```

- **seq 单调递增**，同 run 内唯一；`Last-Event-ID` = 最后收到的 seq。
- **重连**：带 `Last-Event-ID` 重连，服务端从 `run_events` 回放控制类事件（delta 不落库）：run 已完成则直接给 `message.completed` 全文；仍在运行则从当前状态继续推送新 delta。
- **已知限制（对外文档必须写明）**：续传不重放已丢失的增量文本；客户端以 `message.completed` 的完整内容为准。
- **幂等**：创建 run 支持 `Idempotency-Key`，5 分钟内同 key 返回同一 run。

## 4. 错误格式与错误码

```json
{"error": {"code": "rate_limited", "message": "Too many requests", "retryable": true, "request_id": "req_..."}}
```

| code | HTTP | retryable | 触发条件 |
|---|---|---|---|
| `invalid_request` | 400 | false | 参数/JSON Schema 校验失败、字段缺失 |
| `unauthorized` | 401 | false | 缺 key、key 不存在或已撤销 |
| `forbidden` | 403 | false | key 无权访问该 project / 管理端点 |
| `not_found` | 404 | false | 资源不存在（跨 project 一律 404，不泄漏存在性） |
| `conflict` | 409 | false | 同 session 并发 run、幂等键冲突 |
| `rate_limited` | 429 | true | 超 RPM / 并发上限，响应带 `Retry-After` |
| `model_error` | 502 | true | 上游模型 5xx / 断流 / 无法解析 |
| `tool_error` | 422 | false | 工具执行失败（run 继续，错误回灌模型） |
| `timeout` | 504 | true | run 超最大时长 / 上游超时 |
| `internal` | 500 | false | 未预期异常（不返回堆栈） |

约定：

- 任何错误体都含 `request_id`，且与响应头 `X-Request-Id` 一致。
- 未知路由/方法由框架 404/405 处理，映射为 `not_found` / `invalid_request`，同样走错误信封。
- 不在错误体里回显密钥、prompt 全文、堆栈。

## 5. Python SDK 目标形态

```python
from agentd import Client

client = Client(base_url="https://agent.example.com", api_key="agd_...")

session = client.sessions.create(external_user_id="u_123")
with client.runs.stream(session.id, input="帮我总结这个仓库的结构") as stream:
    for event in stream:
        if event.type == "message.delta":
            print(event.delta, end="")
        elif event.type == "tool.started":
            print(f"\n[tool] {event.name}")
print("\nusage:", stream.result.usage)
```

要求：同步 + 异步双 API；异常类型对应错误码；自动重试仅对 `retryable`；类型注解完整；`examples/` 有可运行示例。
