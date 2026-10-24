# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循里程碑 tag（`v0.1.0-mN`）。

## [Unreleased]

### Added（M4：Python SDK + 计量审计 + 压缩 + 日志脱敏）

- Python SDK（`agentd.sdk`，顶层 `from agentd import Client`）：同步 + 异步双 API、SSE 流式（`client.runs.stream` / `stream_async`，事件 dataclass 带 `type` 字段，契约 §5 示例代码原样可跑）、错误类型对应契约错误码（`AuthenticationError`/`RateLimitError`(带 retry_after_s)/`ConflictError`/…）、自动重试仅对 retryable（429/502/504/网络错误，指数退避 + Retry-After 优先）、`Idempotency-Key` 透传
- 审计：`AuditRepository` + 关键操作落库（session.created / run.created / run.cancelled / key.created / key.revoked，含 actor key 与 IP）+ 工具调用审计（`tool_calls` 表一行一次调用）+ `GET /v1/admin/audit` 查询
- 摘要压缩：`load_history(summarizer=…)` —— 活历史超预算时把被丢弃轮次（连同上一份摘要）压成 role=summary 消息落库，上下文 = [摘要] + 保留轮；summarizer 由当前 provider 扮演；压缩失败退化为整轮丢弃（不失败 run）
- 日志脱敏：`log.redact()` —— JSON 输出层擦除 `agd_*` key、`Bearer` token、`api_key/token/password/secret` 字段值（含嵌套转义 JSON）
- `examples/quickstart.py` / `examples/async_stream.py`：契约冻结用法的一分钟上手示例（实跑验证）

### Added（M3：平台 API + 鉴权 + 并发）

- 鉴权：`api/auth.py`（Bearer → sha256 → key 行；撤销立即生效；scope 区分 core/admin）、`services/keys.py`（`agd_` key 生成、`AGENTD_ADMIN_API_KEY` 启动引导 admin scope key + default 项目）
- 限流：`security/ratelimit.py` 进程内滑动窗口（每 key RPM，超限 429 错误信封 + Retry-After）
- run 编排：`services/runs.py` RunService —— 后台任务执行、事件编 seq、控制类事件落 `run_events`（delta 不落库）、订阅队列广播、终态收敛（completed/failed/cancelled）、usage_records 计量、成功轮经 ConversationService 落库、进程收尾 shutdown
- 端点（契约 §2）：`POST/GET /v1/sessions`、`GET /v1/sessions/{id}(/messages)`（seq 游标分页）、`POST /v1/sessions/{id}/runs`（202 + `Idempotency-Key` 5 分钟幂等 + 同会话并发 409）、`GET /v1/runs/{id}`、`POST /v1/runs/{id}/cancel`、`GET /v1/runs/{id}/events`（SSE：Last-Event-ID 回放、15s 心跳、终态关流）、`GET /v1/admin/keys`（创建一次性 secret/列表/撤销）、`GET /v1/usage`（day/model 聚合）、`GET /v1/models`
- provider 装配：`provider=auto`（配 key 走真实模型，无 key 回退 fake 离线全链路）
- OpenAPI：全部 /v1 端点带 pydantic 响应模型（`/openapi.json`）

### Added（M2：会话持久化 + 上下文 + 真工具 + 安全）

- 安全边界：`security/paths.py`（workspace 路径关押：拒绝绝对路径/`..`/软链逃逸/盘符相对路径）、`security/ssrf.py`（DNS 全记录公网校验、IPv4-mapped 解包、每跳重定向校验、字面量 IP 直判）
- 真工具：`read_file`/`write_file`/`list_dir`（读写上限与截断）、`run_command`（默认关闭，`AGENTD_ENABLE_SHELL_TOOL=1` 才注册；超时封顶 30s）、`web_fetch`（SSRF 校验、仅文本 Content-Type、128KB 截断、≤3 跳重定向）
- 会话持久化：`MessageRepository`（seq 游标分页）、`ConversationService`（按整轮粒度的 token 预算裁剪、完整工具交换落库与无损重建）
- Runner 暴露 `last_exchange`（成功轮的完整消息交换）；失败轮不落库（沿 M1 语义）
- CLI `chat --session <label>`：同一标签跨进程续聊同一 DB 会话（重启恢复）
- Settings：`context_token_budget`、`enable_shell_tool`、`web_fetch_*`

### Added（M6 前置：Web 控制台）

- `web/`：Vite 7 + React 18 + TypeScript(strict) + Tailwind 3 + TanStack Query 5 + react-router 7 + recharts（架构冻结见 docs/web-architecture.md）
- 六页面：Login（管理员 key，sessionStorage）/ Playground（SSE 流式渲染、工具调用折叠卡、usage 徽标、失败条）/ Sessions（分页+续聊跳转）/ Keys（一次性 secret 展示、撤销）/ Usage（按天柱状图+按模型占比）/ Status（healthz/readyz）
- `sse/run-stream.ts`：fetch+ReadableStream 手写 SSE 解析（EventSource 无法带 Bearer）、Last-Event-ID 重连、45s 心跳超时、指数退避封顶
- `projection/run-projection.ts`：纯函数事件投影（message.completed 全文覆盖 delta、工具轮后开新段）
- **离线演示模式**：M3 `/v1` 端点落地前，登录页一键进入内置演示数据（脚本化事件流含工具回路），全部页面可体验
- FastAPI 同源服务 `web/dist`（SPA 路由回退、assets immutable 缓存、API 404 仍走错误信封）；CI 新增 `web` job（Node 22：npm ci + vitest + tsc/vite build）

### Changed

- `Database`：去掉冗余的 `PRAGMA busy_timeout`（`connect(timeout=…)` 等价设置，且避免拼接 SQL）
- CLI chat 工具集升级为 workspace 工具（read_file/write_file/list_dir/web_fetch/echo/get_time）

### DoD 证据

- 后端：`ruff` / `mypy`（68 files）/ `pytest` **141 passed**（M4 新增 9 个：SDK 同步全流程（真 uvicorn 随机端口）/错误类型/异步流式、审计链、tool_calls 落库、摘要压缩往返、无 summarizer 退化、脱敏两例、SSE 解析前向兼容）
- examples 实跑：`quickstart.py`（会话→流式+工具卡→usage→keys 全链路）与 `async_stream.py` 对真实服务跑通
- M3 回归：12 个 /v1 集成测试绿（晚连接收不到 delta 为契约已知限制，测试对齐）
- 前端（M6 前置，见下）：`vitest` 14 passed；`tsc --noEmit && vite build` 通过，bundle gzip 194.63KB（< 250KB 预算）；演示模式六页面浏览器实测通过
- `agentd serve` 实测：`/`、`/playground`、`/keys` 200（SPA 回退）；`/v1/nope` 错误信封；assets `cache-control: immutable`、index `no-cache`

## [v0.1.0-m1] - 2026-10-24

M1：Provider + Runner + 流式（核心闭环）。

### Added

- Provider 抽象（`providers/base.py`）：ChatMessage/ToolDefinition wire 类型、流式事件（TextDelta/ReasoningDelta/ToolCallCompleted/StreamEnd/Usage）、错误归一化（RateLimited/ServerError/Timeout/Protocol/Rejected，retryable + retry_after）
- `openai_compat.py`：httpx 流式 SSE 解析（不引 OpenAI SDK）、tool_calls 分片累积、`stream_options.include_usage` 采集；断流判定 = 无 [DONE] 且无 finish_reason 即报错
- `fake.py`：脚本化 FakeChatProvider + demo_turn（CLI 离线演示脚本）
- `retry.py`：RetryingProvider —— 仅未产出事件时重试、Retry-After 优先、指数退避封顶、sleep 可注入
- 工具层（`tools/`）：Tool 协议 + 注册表（存在性检查/JSON 解析/wait_for 超时/异常转错误结果/16k 截断）+ 内置 echo、get_time
- Runner（`runtime/runner.py`）：system+history+user 组装、≤8 次模型调用、工具调用回路（assistant.tool_calls + tool 结果回填）、usage 跨轮累计、契约错误码映射、run 级超时、显式 aclose 链（取消无悬挂）
- 事件类型（`runtime/events.py`）：对齐 api-contract §3 的 8 种事件
- token 估算（`runtime/tokens.py`）：tiktoken 惰性加载，离线降级 len/4
- CLI：`agentd chat --session demo [--fake] [--model]`，多轮流式对话 + 工具事件；失败轮不写回历史
- CI：pytest 接入 `--cov`（分支覆盖 91%）；依赖新增 tiktoken、pytest-cov

### DoD 证据

- CLI `--fake` 十轮对话 + 工具闭环实跑通过；73 测试全绿（respx fixture 覆盖文本流/工具流/429/5xx/401/超时/断流/畸形 JSON；取消后无悬挂 task）

### Known issues

- 会话历史仅在 CLI 进程内存（M2 落库）；SSE 端点/取消 API 属 M3

## [v0.1.0-m0] - 2026-10-23

M0：范围冻结 + 工程骨架 + 部署链。

### Added

- 范围与契约：`V0.1-SCOPE.md`（P0/non-goals/上线标准）、`docs/architecture.md`（分层、run 生命周期、状态机、数据模型）、`docs/api-contract.md`（M0 冻结的端点/SSE 事件/错误码）、`docs/milestones.md`（M0–M8）
- 工程骨架：`src/agentd`（`main/create_app`、`config`、`log`、`cli`）、ruff/mypy/pytest 配置、`.pre-commit-config.yaml`、GitHub Actions CI（lint → type → test → docker build）、issue 模板与 `scripts/create-milestones.sh`
- HTTP 层：`/healthz`（存活，不碰 IO）、`/readyz`（DB 可用性）、统一错误信封（`invalid_request/unauthorized/forbidden/not_found/conflict/rate_limited/model_error/tool_error/timeout/internal`）、纯 ASGI request-id 中间件（响应头 + 错误体 + 日志贯穿）
- 日志：JSON 单行输出，`request_id`/`run_id` 由 `ContextVar` 注入；关闭 uvicorn access log 避免重复
- 存储：schema v1（projects/api_keys/sessions/messages/runs/run_events/tool_calls/usage_records/audit_logs/schema_version）、幂等迁移 runner（单事务 + 版本表）、`Database`（WAL、foreign_keys、busy_timeout、单写者）、`repositories.py`（project/api_key/session/run + 启动状态收敛）
- 部署：多阶段非 root `deploy/Dockerfile`（246MB，可 `--build-arg` 覆盖基础镜像/索引源以适配镜像加速）、`deploy/entrypoint.sh`（先迁移后起服务、exec 保证 SIGTERM 优雅退出）、`docker-compose.yml`（app + Caddy，仅暴露 80/443，镜像/端口可 env 覆盖）、`deploy/Caddyfile`（自动 TLS、安全头、SSE 直通）、`Makefile` + `scripts/tasks.py`、`docs/deploy.md`
- 测试：27 个用例（健康检查/错误信封/request-id/迁移幂等与约束/Repository 往返/配置解析/日志格式）
- 已验证（本机容器）：镜像构建、非 root（uid 10001）、容器内迁移落到 `/data`、`/healthz` `/readyz` 200、SIGTERM 优雅关闭、重启数据不丢、compose 全栈（Caddy HTTPS 200 + 安全响应头）

### Known issues

- 线上 `https://<domain>/healthz` 未验收：无可用 VPS/域名（本机已用 Caddy 内部 CA 走通 HTTPS 链路；线上步骤见 `docs/deploy.md` §3–§5）
- 远程仓库与 9 个 milestone 未创建：环境无 `gh`，GitHub connector 需重新授权；`scripts/create-milestones.sh` 已就绪
