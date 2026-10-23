# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循里程碑 tag（`v0.1.0-mN`）。

## [Unreleased]

## [v0.1.0-m0] - 2026-10-23

M0：范围冻结 + 工程骨架 + 部署链。

### Added

- 范围与契约：`V0.1-SCOPE.md`（P0/non-goals/上线标准）、`docs/architecture.md`（分层、run 生命周期、状态机、数据模型）、`docs/api-contract.md`（M0 冻结的端点/SSE 事件/错误码）、`docs/milestones.md`（M0–M8）
- 工程骨架：`src/agentd`（`main/create_app`、`config`、`log`、`cli`）、ruff/mypy/pytest 配置、`.pre-commit-config.yaml`、GitHub Actions CI（lint → type → test → docker build）、issue 模板与 `scripts/create-milestones.sh`
- HTTP 层：`/healthz`（存活，不碰 IO）、`/readyz`（DB 可用性）、统一错误信封（`invalid_request/unauthorized/forbidden/not_found/conflict/rate_limited/model_error/tool_error/timeout/internal`）、纯 ASGI request-id 中间件（响应头 + 错误体 + 日志贯穿）
- 日志：JSON 单行输出，`request_id`/`run_id` 由 `ContextVar` 注入；关闭 uvicorn access log 避免重复
- 存储：schema v1（projects/api_keys/sessions/messages/runs/run_events/tool_calls/usage_records/audit_logs/schema_version）、幂等迁移 runner（单事务 + 版本表）、`Database`（WAL、foreign_keys、busy_timeout、单写者）、`repositories.py`（project/api_key/session/run + 启动状态收敛）
- 部署：多阶段非 root `deploy/Dockerfile`、`deploy/entrypoint.sh`（先迁移后起服务、exec 保证 SIGTERM 优雅退出）、`docker-compose.yml`（app + Caddy，仅暴露 80/443）、`deploy/Caddyfile`（自动 TLS、安全头、SSE 直通）、`Makefile` + `scripts/tasks.py`、`docs/deploy.md`
- 测试：27 个用例（健康检查/错误信封/request-id/迁移幂等与约束/Repository 往返/配置解析/日志格式）

### Known issues

- 线上 `/healthz` 未验收：本机 Docker 守护进程未运行且无 VPS/域名（详见 `docs/deploy.md` §9）
- 远程仓库与 9 个 milestone 未创建：环境无 `gh`，GitHub connector 需重新授权；`scripts/create-milestones.sh` 已就绪
