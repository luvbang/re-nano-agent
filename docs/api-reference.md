# API 参考

> 完整交互式文档由 FastAPI 自动生成并随服务提供：`/docs`（Swagger UI）与 `/openapi.json`。
> 本文是人工维护的速查：端点、SSE 事件、错误码。契约以 `docs/api-contract.md` 为准（M0 冻结，只加不破）。

## 认证

`Authorization: Bearer agd_...` —— key 绑定唯一 project，跨 project 访问一律 404。管理端点用管理员 key（`AGENTD_ADMIN_KEY` 或 admin scope）。明文 key 仅创建时返回一次。

## 端点速查

| 端点 | 说明 |
|---|---|
| `POST /v1/sessions` / `GET /v1/sessions` | 建 / 列会话（倒序） |
| `GET /v1/sessions/{id}` / `GET /v1/sessions/{id}/messages` | 详情 / 消息（seq 升序，`before_seq` 翻页） |
| `PATCH /v1/sessions/{id}` / `DELETE /v1/sessions/{id}` | 重命名 / 删除（级联删消息与 runs，用量记录保留） |
| `POST /v1/sessions/{id}/runs` | 创建 run → `202 {run_id, status}`；`Idempotency-Key` 5 分钟窗口 |
| `GET /v1/runs/{id}` | 状态/用量/错误 |
| `GET /v1/runs/{id}/events` | SSE 事件流（`Last-Event-ID` 续传，15s 心跳） |
| `POST /v1/runs/{id}/cancel` | 取消（终态后 409） |
| `GET /v1/models` / `GET /v1/usage` | 模型列表 / 用量聚合（`group_by=day\|model`，日期过滤，含 cost_usd） |
| `POST/GET /v1/admin/projects` | project 管理（管理员） |
| `POST/GET /v1/admin/keys`、`POST /v1/admin/keys/{id}/revoke` | key 管理（撤销立即生效） |
| `GET /v1/admin/stats` / `GET /v1/admin/audit` | 运行概况 / 审计日志（管理员） |
| `GET /healthz` / `GET /readyz` / `GET /metrics` | 存活 / 就绪 / Prometheus 指标（metrics 需管理员） |

## SSE 事件（`event:` + `id: seq` + `data: JSON`）

```
run.started        {run_id, session_id}
message.delta      {delta}                    # 不落库，续传不重放
reasoning.delta    {delta}                    # 模型支持时
tool.started       {tool_call_id, name, args}
tool.completed     {tool_call_id, name, status, duration_ms}
message.completed  {content, usage}           # ★ 客户端以此为准
run.completed      {run_id, usage}
run.failed         {error:{code, message, retryable}}
run.cancelled      {run_id, reason}           # M3 新增
: ping                                        # 15s 心跳
```

## 错误码（错误信封 `{"error":{code,message,retryable,request_id}}`）

| code | HTTP | retryable | 触发 |
|---|---|---|---|
| `invalid_request` | 400 | 否 | 参数校验/JSON/请求体超限(413)/上下文装不下 |
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
