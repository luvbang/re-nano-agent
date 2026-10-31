# API 接口测试文档

> 面向**接口验收 / 回归测试 / 联调排障**的实操手册。
> 所有端点、字段、状态码取自 `tests/fixtures/openapi.json` 快照（受 CI 守护），
> 所有示例响应均为**本地实跑采集**，非手写示意。

关联文档：[API 参考](api-reference.md)（端点清单）· [接口契约](api-contract.md)（语义约束）· [快速接入](quickstart.md)（首次接入）

---

## 0. 准备

### 0.1 起一个可测服务

测试不需要真实模型 key，用 fake provider 即可覆盖全部端点：

```bash
cd <repo>
uv sync --all-groups
uv run python scripts/tasks.py migrate

# 固定管理员 key，便于脚本化；不设则每次启动随机生成并打印
AGENTD_ADMIN_API_KEY=test-admin-key .venv/Scripts/python.exe scripts/serve_fake.py --port 8199
```

> Windows 用 `.venv/Scripts/python.exe`；Linux/macOS 用 `uv run python`。

### 0.2 三类凭据（**最容易踩的坑**）

| 凭据 | 用途 | 能做什么 |
|---|---|---|
| **管理员 key**（`AGENTD_ADMIN_API_KEY`） | 管理端点 | `/v1/admin/*`、`/metrics` |
| **项目 key**（`POST /v1/admin/keys` 返回，`agd_` 前缀） | 业务端点 | 会话 / run / 记忆 / 用量 |
| 无 | — | `/healthz`、`/readyz`、`/openapi.json` |

> ⚠️ **管理员 key 不能跑业务**：拿它调 `/v1/sessions` 会返回 `401 {"message":"key 不存在"}`
> （管理员 key 不在 API key 表里）。这是设计如此，不是 bug。

### 0.3 环境变量（下文脚本复用）

```bash
BASE=http://127.0.0.1:8199
ADMIN=test-admin-key
```

---

## 1. 冒烟测试（5 分钟，先确认服务活着）

### 1.1 存活与就绪

```bash
curl -s $BASE/healthz
# {"status":"ok","version":"0.1.0","uptime_s":8.78}

curl -s $BASE/readyz
# {"status":"ready","checks":{"db":"ok"}}
```

| 检查点 | 期望 |
|---|---|
| `healthz` 返回 200 且 `status=ok` | 进程活着（**不碰 IO**，DB 挂了也应 200） |
| `readyz` 返回 200 且 `checks.db=ok` | DB 可读写（LB 摘流依据） |
| `readyz` 返回 **503** + 错误信封 | DB 不可用（这是正确行为，不是故障） |
| OpenAPI 可访问 | `curl -s $BASE/openapi.json \| head -c 100` |

### 1.2 建测试用 project + key

```bash
# 建 project
PROJ=$(curl -s -X POST $BASE/v1/admin/projects \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"name":"api-test"}')
echo "$PROJ"
# {"id":"p_80b269914297fa19","name":"api-test","created_at":"2026-10-31T05:07:28.686Z"}

PID=$(echo "$PROJ" | python -c "import json,sys;print(json.load(sys.stdin)['id'])")

# 建 key（明文只返回这一次，务必保存）
KEYJ=$(curl -s -X POST $BASE/v1/admin/keys \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d "{\"project_id\":\"$PID\",\"name\":\"ci\",\"rate_limit_per_min\":60}")
echo "$KEYJ"
# {"key":"agd_369DBLP...","detail":{"id":"k_c4f4...","key_prefix":"agd_369DBLPi",...}}

KEY=$(echo "$KEYJ" | python -c "import json,sys;print(json.load(sys.stdin)['key'])")
```

| 检查点 | 期望 |
|---|---|
| `POST /v1/admin/projects` → **201** | 重名 project → **409** `conflict` |
| `POST /v1/admin/keys` → **201** | `key` 字段**仅此一次**返回；列表接口只有 `key_prefix` |
| `key` 形如 `agd_` + 43 字符 | 总长约 47 字符 |
| `detail.rate_limit_per_min` = 传入值 | 不传默认 60 |

---

## 2. 核心链路测试（会话 → run → SSE）

### 2.1 建会话

```bash
curl -s -X POST $BASE/v1/sessions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"title":"接口测试会话"}'
```

实测响应：

```json
{
  "id": "s_abc0efe97ccff58e",
  "project_id": "p_80b269914297fa19",
  "title": "接口测试会话",
  "external_user_id": null,
  "created_at": "2026-10-31T05:07:28.692Z",
  "updated_at": "2026-10-31T05:07:28.692Z"
}
```

**请求体（全可选）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string \| null | 会话标题 |
| `external_user_id` | string \| null | 对接方自己的用户标识 |
| `metadata` | object | 任意附加信息 |

### 2.2 发起 run

```bash
RUN=$(curl -s -X POST $BASE/v1/sessions/$SID/runs \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"input":"现在几点了？"}')
# {"run_id":"r_5d3538b746066328","status":"queued"}
```

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `input` | string | ✅ | 用户输入 |
| `model` | string \| null | — | 请求级模型覆盖；未知模型 → **400** |
| `stream` | boolean | — | 默认 `true` |
| `metadata` | object | — | 附加信息 |

**可选请求头** `Idempotency-Key`

> 5 分钟内同 key + 同请求 → 返回**同一个 `run_id`**。实测第二次返回
> `{"run_id":"r_35cbcda6a2089261","status":"running"}`（id 相同、状态推进），
> 不是新建 run。用于客户端超时重试防重复计费。

### 2.3 订阅 SSE 事件流（核心）

```bash
curl -N $BASE/v1/runs/$RUN_ID/events -H "Authorization: Bearer $KEY"
```

**实测原始输出（完整一次 run）**：

```
event: run.started
id: 1
data: {"run_id": "r_1409fc0c52c8857e", "session_id": "s_abc0efe97ccff58e"}

event: tool.started
id: 2
data: {"tool_call_id": "call_demo_1", "name": "get_time", "args": {}}

event: tool.completed
id: 3
data: {"tool_call_id": "call_demo_1", "name": "get_time", "status": "ok", "duration_ms": 0, "result": "utc=2026-10-31T05:07:36Z local=2026-10-31T13:07:36+08:00"}

event: message.delta
id: 4
data: {"delta": "工具 call_demo_1 的结果是：utc=..."}

event: message.completed
id: 5
data: {"content": "工具 call_demo_1 的结果是：utc=...", "usage": {"input_tokens": 14, "output_tokens": 14}}

event: run.completed
id: 6
data: {"run_id": "r_1409fc0c52c8857e", "usage": {"input_tokens": 14, "output_tokens": 14}}
```

**事件类型全表**（取自 `run_manager._EVENT_NAMES`）

| `event:` | 说明 | 关键 `data` 字段 |
|---|---|---|
| `run.started` | run 开始 | `run_id`, `session_id` |
| `message.delta` | 增量文本 | `delta` |
| `reasoning.delta` | 推理增量（推理模型） | — |
| `tool.started` | 工具开始 | `tool_call_id`, `name`, `args` |
| `tool.completed` | 工具结束 | `tool_call_id`, `name`, `status`, `duration_ms`, `result` |
| `message.completed` | 终稿（**以此为准**） | `content`, `usage` |
| `run.completed` | run 成功结束 | `run_id`, `usage` |
| `run.failed` | run 失败 | `error{code,message,retryable}` |

**验收要点**

| 检查点 | 期望 |
|---|---|
| `id:` 从 1 单调递增 | 用作 `Last-Event-ID` 续传游标 |
| 顺序 | `run.started` 首个，`run.completed`/`run.failed` 末个 |
| `message.delta` 拼接 == `message.completed.content` | 不一致说明丢帧 |
| 心跳 | 15s 无事件时发注释行保活（长时间思考期间正常） |
| 断线续传 | 带 `Last-Event-ID: 3` 重连，应从 `id: 4` 继续 |
| 非法 `Last-Event-ID` | **400** `invalid_request`「Last-Event-ID 必须是整数」 |

### 2.4 查询 run 终态

```bash
curl -s $BASE/v1/runs/$RUN_ID -H "Authorization: Bearer $KEY"
```

```json
{
  "id": "r_5d3538b746066328",
  "session_id": "s_abc0efe97ccff58e",
  "status": "completed",
  "model": "custom",
  "input_tokens": 14,
  "output_tokens": 14,
  "error": null,
  "created_at": "2026-10-31T05:07:28.709Z",
  "finished_at": "2026-10-31T05:07:28.866Z"
}
```

**`status` 取值**：`queued` → `running` → `completed` / `failed` / `cancelled`
（服务重启时进行中的 run 落 `interrupted`）。

**取消 run（实测）**

```bash
curl -s -X POST $BASE/v1/runs/$RUN_ID/cancel -H "Authorization: Bearer $KEY"
```

| 场景 | 实测结果 |
|---|---|
| run 进行中 | 200，run 落 `cancelled` |
| **run 已终态** | **409** `{"code":"conflict","message":"run 已是终态：completed"}` |
| run 不存在 | 404 `run 不存在：r_nope` |

### 2.5 会话消息（含工具调用回放）

```bash
curl -s "$BASE/v1/sessions/$SID/messages?limit=50" -H "Authorization: Bearer $KEY"
```

```json
{
  "items": [
    {"id":"m_d247...","seq":1,"role":"user","content":"现在几点了？","tool_calls":null,"tool_call_id":null,"created_at":"..."},
    {"id":"m_2f99...","seq":2,"role":"assistant","content":null,
     "tool_calls":[{"id":"call_demo_1","type":"function","function":{"name":"get_time","arguments":"{}"}}],
     "tool_call_id":null,"created_at":"..."}
  ],
  "has_more": false
}
```

| 字段 | 说明 |
|---|---|
| `seq` | 会话内自增序号，游标分页依据 |
| `tool_calls` | assistant 发起的历史工具调用（array 或 null） |
| `tool_call_id` | `role=tool` 时指向对应调用 |

**游标分页**（实测）

```bash
# limit=1 → 最新 1 条
curl -s "$BASE/v1/sessions/$SID/messages?limit=1" ...
# {"items":[{"seq":9,...}],"has_more":true}

# before_seq=9 → 取 9 之前的 10 条
curl -s "$BASE/v1/sessions/$SID/messages?limit=10&before_seq=9" ...
# {"items":[{seq:1},...,{seq:8}],"has_more":false}
```

> `before_seq` 是**严格小于**；用最后一条的 `seq` 作为下一页游标。

---

## 3. 端点测试清单（19 个，全部覆盖）

> 详细字段见各节；此处是**逐项勾选表**，适合做验收记录。

### 3.1 公开端点（无需鉴权）

| # | 方法 | 路径 | 期望 | ☐ |
|---|---|---|---|---|
| 1 | GET | `/healthz` | 200 `{status,version,uptime_s}` | ☐ |
| 2 | GET | `/readyz` | 200 `{status,checks.db}`；DB 挂 → 503 | ☐ |
| 3 | GET | `/metrics` | 200 text/plain（**需管理员 Bearer**） | ☐ |

> 📌 **响应结构约定**：列表类端点中，`/v1/sessions`、`/v1/admin/projects`、
> `/v1/admin/keys`、`/v1/admin/audit`、`/v1/memories`、`/v1/models` 返回**纯数组**；
> 只有 `/v1/sessions/{id}/messages`（`{items,has_more}`）和 `/v1/usage`
> （`{group_by,items}`）是信封结构。写测试时别统一按 `items` 取。

### 3.2 管理端点（管理员 key）

| # | 方法 | 路径 | 期望 | ☐ |
|---|---|---|---|---|
| 4 | GET | `/v1/admin/projects` | 200 数组 | ☐ |
| 5 | POST | `/v1/admin/projects` | 201；重名 409 | ☐ |
| 6 | GET | `/v1/admin/keys` | 200，**不含明文** | ☐ |
| 7 | POST | `/v1/admin/keys` | 201，明文仅此一次 | ☐ |
| 8 | POST | `/v1/admin/keys/{id}/revoke` | 200 带 `revoked_at`；再调幂等 | ☐ |
| 9 | GET | `/v1/admin/audit` | 200，倒序；支持 `project_id`/`action`/`limit` | ☐ |
| 10 | GET | `/v1/admin/stats` | 200 run/会话/用量/DB 体量 | ☐ |

### 3.3 业务端点（项目 key）

| # | 方法 | 路径 | 期望 | ☐ |
|---|---|---|---|---|
| 11 | GET | `/v1/sessions` | 200，按创建时间倒序；`limit` 默认 50 | ☐ |
| 12 | POST | `/v1/sessions` | 201 | ☐ |
| 13 | GET | `/v1/sessions/{id}` | 200；跨 project → 404 | ☐ |
| 14 | PATCH | `/v1/sessions/{id}` | 200；空/超 200 字符 → 400 | ☐ |
| 15 | DELETE | `/v1/sessions/{id}` | 204；级联删消息与 runs，用量保留 | ☐ |
| 16 | GET | `/v1/sessions/{id}/messages` | 200 `{items,has_more}`；`limit`/`before_seq` | ☐ |
| 17 | POST | `/v1/sessions/{id}/runs` | 202；支持 `Idempotency-Key` | ☐ |
| 18 | GET | `/v1/runs/{id}` | 200 含 status/usage/error | ☐ |
| 19 | GET | `/v1/runs/{id}/events` | 200 SSE；`Last-Event-ID` 续传 | ☐ |
| 20 | POST | `/v1/runs/{id}/cancel` | 200；已终态 → 409 | ☐ |
| 21 | GET | `/v1/memories` | 200；`status`/`limit` 过滤 | ☐ |
| 22 | POST | `/v1/memories` | 201；同内容去重 | ☐ |
| 23 | DELETE | `/v1/memories/{id}` | 204；再调幂等 204 | ☐ |
| 24 | GET | `/v1/models` | 200 模型数组 | ☐ |
| 25 | GET | `/v1/usage` | 200；`group_by=day\|model` | ☐ |

---

## 4. 错误契约测试（**必须全过**）

### 4.1 统一信封

任何错误体都长这样，且 `request_id` **必须等于** `X-Request-Id` 响应头（契约 §4）：

```json
{"error": {"code": "not_found", "message": "run 不存在：r_nope", "retryable": false, "request_id": "req_82782840475b1139"}}
```

**验证脚本（建议纳入回归）**：

```bash
# 任取一个错误响应，比对 body 与 header 的 request_id
HDR=$(curl -s -D - -o /tmp/body.json $BASE/v1/runs/r_nope -H "Authorization: Bearer $KEY" \
  | grep -i "^x-request-id:" | tr -d '\r' | awk '{print $2}')
BODY=$(python -c "import json;print(json.load(open('/tmp/body.json'))['error']['request_id'])")
[ "$HDR" = "$BODY" ] && echo "PASS" || echo "FAIL: $HDR != $BODY"
```

### 4.2 错误码全表（`ErrorCode` 枚举，实测）

| `code` | HTTP | `retryable` | 触发条件 | 实测响应 message |
|---|---|---|---|---|
| `invalid_request` | 400 | false | 参数校验失败 / 语义非法 | `Request validation failed`、`content 不能为空或全空白`、`Last-Event-ID 必须是整数` |
| `unauthorized` | 401 | false | 无 token / token 无效 | `Bearer key 为空`、`key 不存在` |
| `forbidden` | 403 | false | 权限不足 | — |
| `not_found` | 404 | false | 资源不存在**或跨 project** | `session 不存在：s_nope` |
| `conflict` | 409 | false | 重名 / run 已终态 | — |
| `rate_limited` | 429 | **true** | 超 RPM 或并发上限 | `请求过于频繁，请稍后重试` |
| `model_error` | 502 | **true** | 上游模型故障 | — |
| `tool_error` | 422 | false | 工具执行失败 | — |
| `timeout` | 504 | **true** | 上游超时 | — |
| `internal` | 500 | false | 未预期异常 | `Internal Server Error` |

### 4.3 实测错误用例（可直接抄进测试）

| 场景 | 请求 | 实测结果 |
|---|---|---|
| 无 token | `GET /v1/sessions` | 401 `Bearer key 为空` |
| 无效 token | `GET /v1/sessions` (`agd_wrong`) | 401 `key 不存在` |
| **管理员 key 跑业务** | `GET /v1/sessions` (admin) | 401 `key 不存在` |
| 不存在的 session | `GET /v1/sessions/s_nope` | 404 `session 不存在：s_nope` |
| 空 title | `PATCH /v1/sessions/{id}` `{"title":""}` | 400 `String should have at least 1 character` |
| 超长 title | `{"title":"x"*201}` | 400 `String should have at most 200 characters` |
| 空白 memory | `POST /v1/memories` `{"content":"   "}` | 400 `content 不能为空或全空白` |
| 不存在的 run | `GET /v1/runs/r_nope` | 404 `run 不存在：r_nope` |
| 非法 Last-Event-ID | `GET .../events` + `Last-Event-ID: abc` | 400 `Last-Event-ID 必须是整数` |
| 撤销后的 key | 先 revoke 再请求 | 401 |

---

## 5. 安全与隔离测试（不能漏）

### 5.1 跨 project 隔离（**一律 404，不泄漏存在性**）

```bash
# 用 project B 的 key 访问 project A 的 session
curl -s $BASE/v1/sessions/$SESSION_A -H "Authorization: Bearer $KEY_B"
# 404 {"error":{"code":"not_found","message":"session 不存在：s_abc0efe97ccff58e",...}}
```

| 检查点 | 期望 |
|---|---|
| 跨 project 读 session / run / memory | **404**（不是 403，避免暴露 id 是否存在） |
| 跨 project 删 memory | 404 |
| 撤销 key 后立即失效 | 401（无缓存延迟） |

### 5.2 限流

每个 key 有 `rate_limit_per_min`（默认 60），另有全局限流桶。

```bash
# 建 rate=1 的 key，连打 2 次
for i in 1 2; do
  curl -s -D - -o /dev/null $BASE/v1/models -H "Authorization: Bearer $LOW_RATE_KEY" \
    | grep -iE "^HTTP|retry-after"
done
```

实测：

```
HTTP/1.1 200 OK
HTTP/1.1 429 Too Many Requests
retry-after: 60
```

| 检查点 | 期望 |
|---|---|
| 超限 → 429 `rate_limited` | `retryable=true` |
| **`Retry-After` 响应头存在** | 整数秒（实测 `60`） |
| 桶按秒回填 | 等待后自动恢复，无需重启 |

### 5.3 SSE 鉴权与越权

| 检查点 | 期望 |
|---|---|
| 无 token 订阅 events | 401 |
| 用别的 project 的 key 订阅 | 404 |
| 订阅已结束 run | 立即回放全部事件后关闭 |

### 5.4 安全响应头（**注意：由 Caddy 施加，不是应用**）

> ⚠️ 这是一个容易误判的点：安全响应头配在 `deploy/Caddyfile` 的 `header` 块里，
> **应用本身不设置**。因此：
>
> - 经 Caddy（线上 / `docker compose up`）→ 有这些头
> - 直连 `app:8000`（本地 `serve_fake.py` / `tasks.py dev`）→ **没有**这些头
>
> 在本地直接测这些头会失败，那是预期行为，不代表配置缺失。

```bash
# 必须经过 Caddy 才有效（线上域名）
curl -s -D - -o /dev/null https://<你的域名>/healthz | grep -iE "x-content-type|x-frame|referrer|strict-transport"
```

| 头 | 期望值（`deploy/Caddyfile`） |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` |
| `Cross-Origin-Opener-Policy` | `same-origin` |
| `Server` | **被移除**（`-Server`） |

**其他 Caddy 层约束**（同样只在经代理时生效）：

| 配置 | 值 | 说明 |
|---|---|---|
| `request_body max_size` | `2MB` | 外层粗筛；应用层另有精确限制 |
| `flush_interval` | `-1` | **SSE 必须**，否则 delta 被缓冲到连接结束 |
| `read_timeout` | `0` | 配合长连接 SSE |

---

## 6. 记忆端点专项（v0.2 新增）

### 6.1 写入与去重

```bash
curl -s -X POST $BASE/v1/memories \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"content":"用户偏好中文回复"}'
# 201 {"id":"mem_5bbc85af","content":"用户偏好中文回复","status":"active",
#       "score":1.0,"created_at":"2026-10-31 05:07:31","last_seen_at":"2026-10-31 05:07:31"}
```

| 检查点 | 期望 |
|---|---|
| 首次写入 | **201** + 新 `id` |
| **同内容再写** | 仍 **201**，但返回**同一个 `id`**（刷新 `last_seen_at`，不新建） |
| 空白内容 | 400 `invalid_request` |
| 内容前后空格 | 自动 strip 后入库 |

> ⚠️ 去重的副作用：响应**无法区分**"新建"与"命中已有"，两者都是 201 且同结构。
> 需要区分请比对 `id` 或 `created_at`。

### 6.2 列表与归档

```bash
# 注意：返回的是纯数组，不是 {items:[...]} 信封
curl -s "$BASE/v1/memories?status=active&limit=100" -H "Authorization: Bearer $KEY"
# [{"id":"mem_5bbc85af","content":"用户偏好中文回复","status":"active",
#   "score":1.0,"created_at":"2026-10-31 05:07:31","last_seen_at":"..."}]

curl -s -X DELETE $BASE/v1/memories/$MID -H "Authorization: Bearer $KEY"   # 204
curl -s -X DELETE $BASE/v1/memories/$MID -H "Authorization: Bearer $KEY"   # 204（幂等）
```

| 检查点 | 期望 |
|---|---|
| 响应体是**数组** | 直接 `[{...}]`，无 `items` 包装 |
| `status=active` / `archived` | 过滤生效 |
| `limit` 默认 100，范围 **1–200** | `limit=0` 或 `limit=201` → 400 |
| 归档 = 软删 | `status` 变 `archived`，记录仍在 |
| **归档两次** | 都返回 **204**（幂等） |
| 跨 project 归档 | 404 |

> ⚠️ `GET ?status=archived` 是「先取最近 `limit` 条、再按状态过滤」，
> 不是"在全部归档里取 limit 条"。归档多而 active 更多时可能取不到期望的那条。

---

## 7. 用量与统计

### 7.1 用量聚合

```bash
curl -s "$BASE/v1/usage?group_by=day" -H "Authorization: Bearer $KEY"
# {"group_by":"day","items":[{"bucket":"2026-10-31","runs":1,
#   "input_tokens":14,"output_tokens":14,"cost_usd":0.0}]}

curl -s "$BASE/v1/usage?group_by=model&date_from=2026-10-01&date_to=2026-10-31" \
  -H "Authorization: Bearer $KEY"
# {"group_by":"model","items":[{"bucket":"custom","runs":3,
#   "input_tokens":34,"output_tokens":34,"cost_usd":0.0}]}
```

| 参数 | 取值 | 说明 |
|---|---|---|
| `group_by` | `day`（默认）/ `model` | 聚合维度；`bucket` 承载分组值 |
| `date_from` / `date_to` | `YYYY-MM-DD` | 闭区间过滤 |

| 检查点 | 期望 |
|---|---|
| run 完成后 `runs` +1 | 计数与 token 累加 |
| 删除会话后用量**仍在** | 用量记录保留、`run_id` 置空 |
| `cost_usd` | 由定价表计算；未知模型为 0 |

### 7.2 系统状态（管理员）

```bash
curl -s $BASE/v1/admin/stats -H "Authorization: Bearer $ADMIN"
```

```json
{
  "runs_by_status": {"completed": 90},
  "sessions": 87,
  "usage": {"records": 90, "input_tokens": 580, "output_tokens": 580, "cost_usd": 0.0},
  "db_size_bytes": 397312,
  "workspace_root": ".../var/workspace"
}
```

### 7.3 模型列表

```bash
curl -s $BASE/v1/models -H "Authorization: Bearer $KEY"
# [{"id":"deepseek-flash","object":"model","tools":true}]
```

| 字段 | 说明 |
|---|---|
| `id` | 模型标识，可直接用于 `RunCreate.model` |
| `tools` | 是否支持工具调用 |

### 7.4 审计日志（管理员）

```bash
curl -s "$BASE/v1/admin/audit?limit=2" -H "Authorization: Bearer $ADMIN"
```

```json
[{"id":"a_b1db5e80","project_id":"p_3f1f...","actor":"admin","action":"key.created",
  "target":"k_e6a61e...","detail":{"prefix":"agd_FZe7NJES","name":null},
  "created_at":"2026-10-31T05:08:14.469Z"}]
```

| 参数 | 说明 |
|---|---|
| `project_id` | 按 project 过滤 |
| `action` | 按动作过滤（`key.created` / `run.cancelled` / `memory.created` …） |
| `limit` | 默认 100 |

| 检查点 | 期望 |
|---|---|
| 倒序（最新在前） | 按 `created_at` 降序 |
| `detail` 内**不出现密钥明文** | 只有 `prefix` |

---

## 8. 回归测试脚本（可直接跑）

保存为 `scripts/api_smoke_test.sh`，CI 或本地一键验证核心契约：

### 8.1 一键冒烟脚本

仓库已自带并**实跑通过**（14/14）：`scripts/api_smoke_test.sh`。

```bash
# 用法
BASE=http://127.0.0.1:8199 ADMIN=<管理员key> bash scripts/api_smoke_test.sh
```

覆盖：健康检查 / 鉴权（含"管理员 key 跑业务应 401"）/ 管理端点 /
资源不存在 404 / **`body.request_id == X-Request-Id`**。
退出码 0 = 全通过，可直接接 CI。

<details>
<summary>脚本内容（点击展开）</summary>

```bash
#!/usr/bin/env bash
# API 契约冒烟测试：验证鉴权 / 资源不存在 / request_id 一致性 / 安全基线。
#
# 用法：
#   BASE=http://127.0.0.1:8199 ADMIN=test-admin-key bash scripts/api_smoke_test.sh
#
# 前置：服务已启动（scripts/serve_fake.py），且 ADMIN 与服务端 AGENTD_ADMIN_API_KEY 一致。
# 退出码：0 = 全通过，1 = 有失败项（可直接用于 CI）。
set -uo pipefail

BASE=${BASE:-http://127.0.0.1:8000}
ADMIN=${ADMIN:?需要管理员 key（与服务端 AGENTD_ADMIN_API_KEY 一致）}

# JSON 解析用哪个 python：优先仓库 venv（Windows 下 .venv/Scripts/python.exe）
if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"; else PY=python; fi

PASS=0
FAIL=0
ok() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
no() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }
chk() { if [ "$2" = "$3" ]; then ok "$1"; else no "$1 (期望 $3, 实际 $2)"; fi; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

echo "== 健康检查 =="
chk "healthz 200" "$(code "$BASE/healthz")" 200
chk "readyz 200" "$(code "$BASE/readyz")" 200
chk "openapi 200" "$(code "$BASE/openapi.json")" 200

echo "== 鉴权 =="
chk "无 token -> 401" "$(code "$BASE/v1/sessions")" 401
chk "错误 token -> 401" "$(code -H 'Authorization: Bearer agd_wrong' "$BASE/v1/sessions")" 401
chk "管理员 key 跑业务 -> 401" "$(code -H "Authorization: Bearer $ADMIN" "$BASE/v1/sessions")" 401

echo "== 管理端点（管理员应可用）=="
chk "admin projects 200" "$(code -H "Authorization: Bearer $ADMIN" "$BASE/v1/admin/projects")" 200
chk "admin stats 200" "$(code -H "Authorization: Bearer $ADMIN" "$BASE/v1/admin/stats")" 200
chk "metrics 200" "$(code -H "Authorization: Bearer $ADMIN" "$BASE/metrics")" 200

echo "== 建项目 key（业务端点需要项目 key，管理员 key 不行）=="
PROJ_ID=$(curl -s -X POST "$BASE/v1/admin/projects" \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d "{\"name\":\"smoke-$$\"}" \
  | $PY -c "import json,sys;print(json.load(sys.stdin, ).get('id',''))" 2>/dev/null)
PROJ_KEY=$(curl -s -X POST "$BASE/v1/admin/keys" \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PROJ_ID\"}" \
  | $PY -c "import json,sys;print(json.load(sys.stdin).get('key',''))" 2>/dev/null)
chk "建项目成功" "$([ -n "$PROJ_ID" ] && echo yes || echo no)" "yes"
chk "建 key 成功" "$([ -n "$PROJ_KEY" ] && echo yes || echo no)" "yes"

echo "== 资源不存在 -> 404 而非 500 =="
chk "不存在 session 404" \
  "$(code -H "Authorization: Bearer $PROJ_KEY" "$BASE/v1/sessions/s_nope")" 404

echo "== request_id 一致性（契约第 4 节）=="
# 用脚本同目录的相对路径做临时文件：MSYS 的 /tmp 与原生 Windows python 不互通
TMP=".api_smoke_body.$$"
HDR=$(curl -s -D - -o "$TMP" -H "Authorization: Bearer $PROJ_KEY" "$BASE/v1/sessions/s_nope" \
  | grep -i '^x-request-id:' | tr -d '\r' | awk '{print $2}')
BODY=$($PY -c "import json;print(json.load(open('$TMP',encoding='utf-8'))['error']['request_id'])" 2>/dev/null)
chk "body.request_id == X-Request-Id" "$BODY" "$HDR"
chk "request_id 非空" "$([ -n "$BODY" ] && echo yes || echo no)" "yes"
rm -f "$TMP"

echo
echo "通过 $PASS / 失败 $FAIL"
[ "$FAIL" -eq 0 ]
```

</details>

> 说明：`scripts/api_smoke_test.sh` 依赖 `python` 解析 JSON，也可换成 `jq`。

---

## 9. 常见问题（踩坑记录）

| 现象 | 原因 | 处理 |
|---|---|---|
| `401 key 不存在` 但 key 明明对 | 用了**管理员 key** 调业务端点 | 改用 project key |
| `404 session 不存在` 但刚建过 | key 属于**别的 project** | 确认 key 与 session 同 project |
| 中文请求体报 `error parsing the body` | Windows shell/终端编码把 UTF-8 转坏 | 用 JSON 文件 `--data-binary @body.json`（文件存 UTF-8）或改用 Python/Postman |
| 429 但没有 `Retry-After` | 某些代理会剥头 | 查 `curl -D -` 原始响应；直连验证 |
| SSE 收不到 `message.delta` | 模型不产生增量 / 已被 `message.completed` 覆盖 | 以 `message.completed.content` 为准 |
| `message.delta` 拼接对不上终稿 | 网络丢帧 | 用 `Last-Event-ID` 续传补齐 |
| 建 key 后忘了保存明文 | 明文只返回一次 | revoke 旧 key，重建 |
| `cost_usd` 恒为 0 | fake provider / 未知模型无定价 | 配真实模型或补定价表 |

---

## 10. 自动化测试现状

| 层级 | 位置 | 数量 | 覆盖 |
|---|---|---|---|
| 契约快照 | `tests/fixtures/openapi.json` | 19 路径 | 端点/字段变更必须显式 `--regen` |
| 单元 | `tests/unit/` | — | 限流桶、路径守卫、SSRF、token 估算 |
| 集成 | `tests/integration/` | — | 全部 API 端点、SSE、幂等、隔离 |
| 安全 | `tests/security/` | 36 例 | 越权、注入、脱敏、密钥不落日志 |
| SDK | `tests/sdk/` | 14 | 同步/异步、重试、错误映射 |

本地全量：`uv run python scripts/tasks.py check`（ruff + mypy + pytest）。
CI 门禁：`.github/workflows/ci.yml` 的 `quality` job。

---

## 附：一次性全链路脚本

```bash
BASE=${BASE:-http://127.0.0.1:8199}; ADMIN=${ADMIN:-test-admin-key}
J() { python -c "import json,sys;d=json.load(sys.stdin);print(eval('d'+'$1'))"; }

PID=$(curl -s -X POST $BASE/v1/admin/projects -H "Authorization: Bearer $ADMIN" \
  -H 'Content-Type: application/json' -d '{"name":"e2e"}' | J "['id']")
KEY=$(curl -s -X POST $BASE/v1/admin/keys -H "Authorization: Bearer $ADMIN" \
  -H 'Content-Type: application/json' -d "{\"project_id\":\"$PID\"}" | J "['key']")
SID=$(curl -s -X POST $BASE/v1/sessions -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{"title":"e2e"}' | J "['id']")
RID=$(curl -s -X POST $BASE/v1/sessions/$SID/runs -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{"input":"现在几点？"}' | J "['run_id']")
echo "project=$PID session=$SID run=$RID"
curl -N $BASE/v1/runs/$RID/events -H "Authorization: Bearer $KEY"
```
