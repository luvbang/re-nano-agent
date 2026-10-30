# API 参考

> 完整交互式文档由 FastAPI 自动生成并随服务提供：`/docs`（Swagger UI）与 `/openapi.json`。
> 本文是人工维护的速查：端点、SSE 事件、错误码。契约以 `docs/api-contract.md` 为准（M0 冻结，只加不破）。

## 认证

`Authorization: Bearer agd_...` —— key 绑定唯一 project，跨 project 访问一律 404。管理端点用管理员 key（环境变量 `AGENTD_ADMIN_API_KEY`，或 DB 里带 `admin` scope 的 key）。明文 key 仅创建时返回一次。

## 端点速查

> 下表与实现逐条对齐（`app.openapi()` 实际导出 19 条路径，另加 `/openapi.json` `/docs` `/redoc`）；
> 变更端点/字段须同步 `tests/fixtures/openapi.json` 快照（显式 `--regen`）。

| 端点 | 说明 |
|---|---|
| `POST /v1/sessions` / `GET /v1/sessions` | 建 / 列会话（倒序；`limit` 1–100，默认 50） |
| `GET /v1/sessions/{id}` / `GET /v1/sessions/{id}/messages` | 详情 / 消息（seq 升序，`limit` 1–200 + `before_seq` 翻页，返回 `{items, has_more}`；每条消息含 `tool_calls`，见下文） |
| `PATCH /v1/sessions/{id}` / `DELETE /v1/sessions/{id}` | 重命名（改 title）/ 删除（204，级联删消息与 runs，用量记录保留，见下文） |
| `POST /v1/sessions/{id}/runs` | 创建 run → `202 {run_id, status}`；可带 `model` 选模型（见下文）；`Idempotency-Key` 5 分钟窗口 |
| `GET /v1/runs/{id}` | 状态/用量/错误 |
| `GET /v1/runs/{id}/events` | SSE 事件流（`Last-Event-ID` 续传，15s 心跳） |
| `POST /v1/runs/{id}/cancel` | 取消（终态后 409） |
| `GET /v1/models` / `GET /v1/usage` | 模型列表 / 用量聚合（`group_by=day\|model`，日期过滤，含 cost_usd） |
| `GET/POST /v1/memories`、`DELETE /v1/memories/{id}` | 长期记忆（v0.2-3，project 作用域，见下文） |
| `POST/GET /v1/admin/projects` | project 管理（管理员） |
| `POST/GET /v1/admin/keys`、`POST /v1/admin/keys/{id}/revoke` | key 管理（撤销立即生效） |
| `GET /v1/admin/stats` / `GET /v1/admin/audit` | 运行概况 / 审计日志（管理员） |
| `GET /healthz` / `GET /readyz` / `GET /metrics` | 存活 / 就绪 / Prometheus 指标（metrics 需管理员） |

## 会话重命名与删除（v0.2）

```http
PATCH /v1/sessions/{id}
Content-Type: application/json
{"title": "新的会话名"}
200 {"id":"s_...","project_id":"p_...","title":"新的会话名","external_user_id":null,
     "created_at":"...","updated_at":"..."}
400 {"error":{"code":"invalid_request",...}}     # title 为空/全空白/超过 200 字符
404 {"error":{"code":"not_found",...}}           # 会话不存在或跨 project

DELETE /v1/sessions/{id}
204                                              # 无响应体
404 {"error":{"code":"not_found",...}}
```

`title` 长度 1–200；服务端先 `strip()`，空串按 `invalid_request` 拒绝。删除是硬删除会话本身，并由外键级联清理消息、runs、run 事件与工具调用记录；usage 表中的记录保留，`run_id` 置空（用量对账不因删会话丢账）。

## 会话消息与工具调用回放（v0.2）

```http
GET /v1/sessions/{id}/messages?limit=50&before_seq=120
200 {"items":[{"id":"m_...","seq":121,"role":"assistant","content":"我查一下时间",
              "tool_calls":[{"id":"call_1","type":"function",
                             "function":{"name":"get_time","arguments":"{}"}}],
              "tool_call_id":null,"created_at":"..."},
             {"id":"m_...","seq":122,"role":"tool","content":"utc=...",
              "tool_calls":null,"tool_call_id":"call_1","created_at":"..."}],
     "has_more":true}
404 {"error":{"code":"not_found",...}}     # 会话不存在或跨 project
```

- `tool_calls` 只在 `role=assistant` 且该轮确实发起工具调用时非空，形状是模型侧的 wire 列表原样透出；控制台据此把历史轮次重建成「参数 + 结果」工具卡（结果在紧随其后的 `role=tool` 消息的 `content` 里）。
- `limit` 1–200（默认 50）；`before_seq` 为 1 基序号，取该序号之前的更早消息。`has_more` 表示还有更早的消息可翻。

## 长期记忆（v0.2-3）

project 作用域，Bearer key 鉴权 + 限流；跨 project 一律 404（不泄漏存在性）。记忆在 run 组装上下文时按 score / last_seen 排序、预算内并入 system 提示段。

```http
GET /v1/memories?status=active&limit=100
200 [{"id":"mem_...","content":"用户偏好深色主题","status":"active","score":1.0,
      "created_at":"...","last_seen_at":"..."}]

POST /v1/memories
{"content":"用户偏好深色主题"}
201 {"id":"mem_...","content":"用户偏好深色主题","status":"active","score":1.0,...}
# 同 project 同内容（strip 后）已存在且为 active 时去重：不新建，只刷新 last_seen 并返回原行
# 注意：去重时 HTTP 仍是 201，响应无法区分「新建」还是「命中既有行」——要区分就比对 id
400 {"error":{"code":"invalid_request",...}}     # content 为空 / 纯空白 / 超过 2000 字符

DELETE /v1/memories/{id}
204                                              # 归档（不物理删除；幂等，重复归档仍 204）
404 {"error":{"code":"not_found",...}}           # 记忆不存在或跨 project
```

- `content` 在 schema 层就做 `strip()` 并拒绝全空白（返回 400 `invalid_request`，不是 500）；落库的是 strip 后的值。
- `status` 可选值 `active` / `archived`；不传则返回最近创建的全部状态记录（`limit` 1–200，默认 100）。**过滤在数据库取回后按状态做**，因此 `status=archived` 的结果也受 `limit` 约束——active 记忆多时 archived 会被挤出窗口，要拿全就调大 `limit`。
- 归档后不再注入上下文，但记录保留供 Dream 与审计追溯；写入与归档分别记审计 `memory.created` / `memory.archived`。
- 自动提取：run 成功后由 provider 从对话中旁路提取事实，受 `AGENTD_MEMORY_EXTRACT_ENABLED` 控制（默认关闭）；提取失败只记日志，绝不影响 run 结果。
- 整理：`uv run agentd dream [--project <id>]` 做规则版去重与陈旧归档（LLM 语义合并留待后续）。

## run 的模型选择（v0.2-4）

```http
POST /v1/sessions/{id}/runs
{"input":"你好","model":"deepseek-chat"}
202 {"run_id":"r_...","status":"queued"}

400 {"error":{"code":"invalid_request","message":"未知模型：gpt-4（可用：deepseek-chat）"}}
```

- `model` 可选；不传则用平台当前模型（`AGENTD_LLM_MODEL`）。请求级 model 随 run 档落库，并经 `AgentRunner` 传导到 `provider.chat(..., model=...)`，最终体现在 `GET /v1/runs/{id}` 的 `model` 字段与 usage 聚合的 model 维度上。
- 当前平台为单模型配置：传了 `model` 且与平台模型不一致时返回 400 `invalid_request`（不是 404 也不是 502）。可用值以 `GET /v1/models` 为准，它返回 `[{"id":"<平台模型>","object":"model","tools":true}]`。
- 多 provider 上线后该校验会放宽为白名单，语义（不认识就 400）不变。

## SSE 事件（`event:` + `id: seq` + `data: JSON`）

```
run.started        {run_id, session_id}
message.delta      {delta}                    # 不落库，续传不重放
reasoning.delta    {delta}                    # 模型支持时
tool.started       {tool_call_id, name, args}
tool.completed     {tool_call_id, name, status, duration_ms, result}
message.completed  {content, usage}           # ★ 客户端以此为准
run.completed      {run_id, usage}
run.failed         {error:{code, message, retryable}}
run.cancelled      {run_id, reason}           # M3 新增
: ping                                        # 15s 心跳
```

`tool.completed` 的 `result` 是工具输出预览（v0.2-4 增补，契约只加不破）：工具管线本身已把结果截到 16k，事件序列化时再封顶 2000 字符，超长时在末尾追加 `…（已截断，共 N 字符）`；持久化回放与实时推送走同一序列化，重连前后看到的内容一致。`status` 为 `ok` / `error`，`error` 时 `result` 为错误信息。

## 错误码（错误信封 `{"error":{code,message,retryable,request_id}}`）

| code | HTTP | retryable | 触发 |
|---|---|---|---|
| `invalid_request` | 400 | 否 | 参数校验/JSON/请求体超限(413)/上下文装不下/未知模型 |
| `unauthorized` | 401 | 否 | 缺 key/key 不存在/已撤销 |
| `forbidden` | 403 | 否 | 非管理员访问管理端点 |
| `not_found` | 404 | 否 | 资源不存在或跨 project |
| `conflict` | 409 | 否 | 同 session 已有 run 在跑；取消已终态 run |
| `rate_limited` | 429 | 是 | 限流（带 `Retry-After` 秒） |
| `model_error` | 502 | 是 | 上游模型故障/未配置模型 |
| `tool_error` | 422 | 否 | 预留（工具失败以 ToolCompleted(error) 事件呈现） |
| `timeout` | 504 | 是 | run 超时 |
| `internal` | 500 | 否 | 未预期错误 |

## curl 最小闭环

```bash
SID=$(curl -fsS -X POST $BASE/v1/sessions -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{"title":"demo"}' | jq -r .id)
RID=$(curl -fsS -X POST $BASE/v1/sessions/$SID/runs -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{"input":"你好"}' | jq -r .run_id)
curl -N -sS "$BASE/v1/runs/$RID/events" -H "Authorization: Bearer $KEY"
```
