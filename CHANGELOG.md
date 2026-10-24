# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循里程碑 tag（`v0.1.0-mN`）。

## [Unreleased]

### Added（v0.2 进行中）

- **MCP 工具支持**：`AGENTD_MCP_SERVERS`（JSON）挂接任意 MCP 服务器的工具——Streamable HTTP 握手（initialize/会话头/notifications）、`tools/list` 发现、`tools/call` 桥接（isError 映射工具错误）；单服务器故障跳过不影响启动；走统一工具管线（超时/审计/截断）。`docs/mcp.md`
- `agentd purge --project <id> [--yes]`：go-live 数据保留项——级联删除 project 数据、审计脱钩保留、无 --yes 只打印计划
- OpenAPI 契约快照守护（`tests/fixtures/openapi.json`，变更须显式 --regen）

## [v0.1.0-rc2] - 2026-10-24

M7：内测稳定性（机器可执行部分）。

### Added

- 性能基线：`scripts/perf.py`（TTFT/完成延迟分位 + Go/No-Go 自动判定）；`docs/perf-baseline.md`——平台开销 TTFT P95=59ms（预算 3000ms），20 并发 82rps 零失败
- 故障演练：上游中途断流/重试耗尽注入测试（不悬挂、事件可回放、会话可恢复、审计留痕）
- `docs/runbook.md`：七类故障（上游/DB 锁/磁盘满/OOM/证书/SSE 重连/数据恢复）的症状-判定-处置
- `docs/stability-report.md`（证据矩阵 + 线上待填表）、`docs/announcement-draft.md`
- M8 预置：`docs/go-live-checklist.md`（机器已验/人工待办分离）、`docs/operations.md` 运营手册、`docs/retro.md`（复盘 + v0.2 优先级：MCP > 多 provider > 记忆 > 控制台完善 > Postgres > 多通道 > PyPI）

### Known issues

- 「连续 5 天无 P0/成功率>98%」与真实模型 TTFT 需线上数据；v0.1.0 待 go-live-checklist 人工签收后发布

## [v0.1.0-rc] - 2026-10-24

M6：极简控制台 + 文档 + RC。

### Added

- Web 控制台 `web/`（React18+Vite+Tailwind+TanStack Query）：登录（管理员+项目双 key）、Playground（SSE 流式渲染、message.completed 全文覆盖、工具卡展开参数）、Sessions、Keys（project/key 创建、明文一次性显示、一键绑定 Playground、撤销）、Usage（按天/模型条形图+日期过滤）、Status（health/ready 徽章 + 运行概况）；事件投影纯函数 + vitest
- 构建链：Dockerfile `node:22-alpine` 阶段（`NPM_REGISTRY` 可换源，dist 打进镜像）、CI web job（typecheck/vitest/build）；bundle gzip 79.5KB
- API：`GET /v1/sessions` 列表（契约补齐）；`_mount_console` 同源静态托管（显式 `AGENTD_STATIC_DIR`）
- `scripts/serve_fake.py`：零配置本地演示（fake provider + 控制台）
- 文档：`docs/sdk-guide.md`、`docs/faq.md`、`docs/api-reference.md`；README 更新至 rc 状态与文档导航

### DoD 证据

- 浏览器实测全链路：登录→建 key→Playground 流式对话（get_time 工具卡）→Sessions/Usage/Status；189 测试全绿

### Known issues

- 控制台浏览器测试未进 CI（人工验收）；线上 HTTPS 下 SSE 待 VPS 验证

## [v0.1.0-m5] - 2026-10-24

M5：部署硬化 + 运维 + 可观测。

### Added

- 备份/恢复：`deploy/backup.sh`（SQLite backup API 在线一致快照 + workspace 打包 + SHA256SUMS + 保留轮转，`PYTHON_BIN` 可覆盖）、`deploy/restore.sh`（校验和强校验）；恢复演练自动化测试
- 请求边界：BodySizeLimitMiddleware（纯 ASGI；Content-Length 超限直接 413，分块预读缓冲后转发；`AGENTD_MAX_REQUEST_BODY_BYTES` 默认 1MB）；Caddy `request_body 2MB` 外层粗筛
- CORS 白名单：`AGENTD_CORS_ORIGINS`（空=同源不加头；CORSMiddleware 最外层先于鉴权应答预检）
- 指标：`api/metrics.py`（进程内 counters/gauge/直方图，零依赖 Prometheus 文本）+ HTTP 请求/延迟、run 终态/时长、SSE 订阅数、DB 体量埋点；裸 `GET /metrics`（管理员，抓取端配 Bearer）
- 告警：`scripts/health_watch.py`（轮询 /healthz，连续失败→日志+可选 webhook，--once 供 cron）
- 运维文档：`docs/ops.md`（健康/指标/告警/备份/升级回滚/日志）；`docs/security-checklist.md`（已验证 vs 待线上分离签收）

### DoD 证据

- docker stop 实拍优雅退出；恢复演练/轮转/413/CORS/metrics 自动化测试全绿；pip-audit 0 已知漏洞

### Known issues

- TLS 评级/备份 cron/异地副本/trivy 待 VPS 人工执行（human-checklist）；指标重启清零（单实例可接受）

## [v0.1.0-m4] - 2026-10-24

M4：SDK + 计量 + 审计 + 压缩（真正可交付）。

### Added

- Python SDK `agentd-client`（uv workspace 成员）：AsyncClient/Client 双 API、SSE 流式迭代（断流自动 Last-Event-ID 重连，增量不重放）、错误信封→类型化异常（RateLimitError 携带 Retry-After）、retryable 指数退避自动重试、POST runs 自动 Idempotency-Key；`examples/sdk_quickstart.py`、`examples/sdk_sync.py`
- 计量：`AGENTD_LLM_PRICE_TABLE`（JSON 模型→每百万 input/output 单价；坏配置退化空表不炸）；UsageService 成本双写 usage_records.cost_usd 与 runs.cost_usd；`/v1/usage`、`/v1/admin/stats` 回报 cost_usd
- 审计：AuditRepository 接线 project.created / key.created（只记 prefix）/ key.revoked / run.created / run.cancelled / tool.call（名称+状态+时长）；`GET /v1/admin/audit?project_id=&action=&limit=`
- 日志脱敏：JsonFormatter 输出前 redact（agd_/sk- key、Bearer、password/token/secret 赋值 → [REDACTED]）
- 压缩 v1：HistoryCompactor——超预算 60% 且足够长时 LLM 摘要，写 role=summary checkpoint（meta.covers_up_to 记录覆盖序号，prompt 视图按序号取）；失败/太短/未超阈值回退 ContextBuilder 三级裁剪
- `docs/quickstart.md`：外部 5 分钟接入文档（含计时与卡点记录栏，供真人验证）

### DoD 证据

- 176 测试全绿；SDK 同步端到端对真实 uvicorn 跑通；审计链路与脱敏有专测；压缩含失败回退用例

### Known issues

- SDK 未发布 PyPI；真人接入验证待执行（人工项）；压缩为同步触发

## [v0.1.0-m3] - 2026-10-24

M3：平台 API + 鉴权 + 并发（对外的门面）。

### Added

- 鉴权：`Authorization: Bearer agd_...` → project（每请求实时查库，撤销立即生效）；key 只存 sha256+前 12 位；管理员双通道（`AGENTD_ADMIN_KEY` 或 DB admin scope）
- 管理端点：`POST/GET /v1/admin/projects`、`POST/GET /v1/admin/keys`、`POST /v1/admin/keys/{id}/revoke`
- 会话端点：`POST/GET /v1/sessions`、`GET /v1/sessions/{id}/messages`（seq 升序 + before_seq 分页 + has_more）
- runs：`POST /v1/sessions/{id}/runs`（202 + `Idempotency-Key` 5 分钟窗口，迁移 002）、`GET /v1/runs/{id}`、`POST /v1/runs/{id}/cancel`；RunManager——per-session 串行（忙时 409）、全局+per-project 信号量（超并发保持 queued）、事件先落库再广播、优雅停机兜底
- SSE：`GET /v1/runs/{id}/events`——契约事件名 + id:seq、`Last-Event-ID` 回放（delta 不入库）、15s 心跳；新增契约事件 `run.cancelled`；kill -9 后新进程收敛 interrupted 并合成 `run.failed(interrupted)`
- 限流：令牌桶 per-key RPM（key 级配置）+ 全局；429 + Retry-After；admin 端点不限流
- 平台端点：`GET /v1/usage?group_by=day|model`（日期过滤）、`GET /v1/models`、`GET /v1/admin/stats`
- 工具：`scripts/smoke.sh`（curl 全链路冒烟）、`scripts/loadtest.py`（并发压测 + p50/p95）
- 未配置模型 key 时 /v1/runs 返回 502 model_error（健康检查不受影响）

### DoD 证据

- 152 测试全绿（分支覆盖 89%）；进程内 20 并发 run 无 5xx、取消后无残留；kill -9 恢复订阅与中途重连有集成测试

### Known issues

- 限流器进程内存态（重启清零）；OpenAPI/SSE schema 快照测试未做（M6）

## [v0.1.0-m2] - 2026-10-24

M2：会话持久化 + 上下文预算 + 真工具 + 安全边界。

### Added

- 持久化：MessageRepository（模型历史唯一真相，content_json={"text"}）、RunRepository.finish（终态+用量+error_json）、ToolCallRepository（500 字符预览）、UsageRepository（项目聚合）；AgentRunner `on_message` 钩子按序回调 user/assistant(tool_calls)/tool/最终 assistant
- ChatService：queued→running→终态状态机、历史装载、失败轮 user 落库/assistant 不落、session touch；M3 API 直接复用
- CLI `chat --session` 落库：重启后同 session 续聊（跨进程验证）
- ContextBuilder：预算 =(window−max_output)×90%，超限先裁最旧 tool 结果（保留 tool_call_id 配对）→ 截断历史超长单条（加标记）→ 仍超限 RunFailed(invalid_request)；工具结果 >16k 落盘 `workspace/.runs/<run_id>/tool-results/` 并回路径
- 文件工具 read_file/write_file/edit_file/list_dir：经 WorkspacePathResolver（resolve containment + 逐段 symlink 拒绝 + 绝对路径/盘符/UNC 拒绝）；限额 1MB/2000 行/500 条
- web_fetch：仅公网（security/ssrf.py：私网/CGNAT/链路本地/元数据/组播/保留/ULA 全拒、DNS 全地址校验、resolve 可注入）、逐跳重定向校验 ≤5 跳、Content-Type 白名单
- shell 工具：默认关闭；`AGENTD_RUN_SHELL_ENABLED=true` + `AGENTD_RUN_SHELL_ALLOWLIST`（前缀匹配）开启；cwd 锁 workspace、超时 kill、并发信号量、16k 截断
- 安全测试套件 36 例（tests/security/，CI 阻塞）

### DoD 证据

- 重启续聊跨进程验证；「读文件→改文件→总结」e2e 全程落库；122 测试全绿，分支覆盖 88%

### Known issues

- SSRF 存在校验-连接间的 DNS rebinding 窗口（v0.2 pinned transport）；TOCTOU 软链替换不在威胁模型（SECURITY 注明）

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
