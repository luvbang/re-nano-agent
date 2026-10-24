# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循里程碑 tag（`v0.1.0-mN`）。

## [Unreleased]

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
