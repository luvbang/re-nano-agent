# agent-platform

可自托管的 Agent 运行时：外部团队用自己的 API Key，通过 **HTTP/SSE API** 或 **Python SDK** 创建会话、发送消息，获得带工具调用能力（文件 / shell / web）的流式 Agent 回答，并能在崩溃后恢复会话、查询用量与审计记录。

> 当前版本：**M0（骨架 + 部署链）**。已有：FastAPI 空服务（`/healthz` `/readyz`）、统一错误信封与 request-id 贯穿、JSON 日志、SQLite schema v1 + 幂等迁移、Repository 骨架、容器与部署手册、CI 门禁。
> 还没有（按里程碑推进）：Provider / Runner / 工具 / 业务 API / SDK。

范围与路线：[`V0.1-SCOPE.md`](V0.1-SCOPE.md) · [`docs/milestones.md`](docs/milestones.md) · 架构 [`docs/architecture.md`](docs/architecture.md) · 接口契约 [`docs/api-contract.md`](docs/api-contract.md) · 部署 [`docs/deploy.md`](docs/deploy.md)

## 快速开始（新克隆）

```bash
# 1) 依赖（需要 uv：https://docs.astral.sh/uv/）
uv sync --all-groups

# 2) 配置（可选，默认走 var/）
cp .env.example .env

# 3) 迁移 + 起服务
uv run python scripts/tasks.py migrate
uv run python scripts/tasks.py dev        # http://127.0.0.1:8000/docs

# 4) 验收
curl -s http://127.0.0.1:8000/healthz     # {"status":"ok","version":"0.1.0",...}
curl -s http://127.0.0.1:8000/readyz      # {"status":"ready","checks":{"db":"ok"}}
```

有 `make` 的环境（Linux/macOS/CI）等价写法：

```bash
make install && make migrate && make dev
make check        # ruff + mypy + pytest
```

Windows 无 `make` 时用 `uv run python scripts/tasks.py <task>`，任务名与 Makefile 一致（`install/migrate/dev/serve/test/lint/type/check/up/down/deploy/tag`）。

## 常用命令

| 任务 | 命令（make） | 命令（跨平台） |
|---|---|---|
| 建 venv + 装依赖 | `make install` | `uv sync --all-groups` |
| 迁移（幂等） | `make migrate` | `uv run python scripts/tasks.py migrate` |
| 开发服务（热重载） | `make dev` | `uv run python scripts/tasks.py dev` |
| 测试 / lint / 类型 | `make test` `make lint` `make type` | `... tasks.py test\|lint\|type` |
| 提交前全量 | `make check` | `uv run python scripts/tasks.py check` |
| 起容器（app + Caddy） | `make up` | `docker compose up -d --build` |
| 打里程碑 tag | `make tag VERSION=v0.1.0-m1` | `... tasks.py tag v0.1.0-m1` |

## 目录

```
src/agentd/
├── main.py            # create_app()：装配中间件、错误处理、路由、lifespan
├── config.py          # pydantic-settings（AGENTD_* 前缀 / .env）
├── log.py             # JSON 日志 + request_id/run_id 上下文
├── cli.py             # migrate / serve / version
├── api/               # deps / errors（错误信封） / middleware（request-id） / routes
├── storage/           # db（WAL、单写者、迁移） / migrations / repositories
├── runtime/           # M1
├── providers/         # M1
├── tools/ security/   # M2
└── services/          # M3+
deploy/                # Dockerfile（多阶段非 root） / entrypoint.sh / Caddyfile
docs/                  # architecture / api-contract / deploy / milestones
scripts/tasks.py       # 跨平台任务运行器（Makefile 的等价实现）
```

## 接口现状（M0）

```http
GET /healthz  200 {"status":"ok","version":"0.1.0","uptime_s":1.23}   # 存活，不碰 IO
GET /readyz   200 {"status":"ready","checks":{"db":"ok"}}             # DB 可用性；失败 503
GET /openapi.json                                                     # 自动生成的接口文档
```

错误统一为：

```json
{"error": {"code": "not_found", "message": "Not Found", "retryable": false, "request_id": "req_..."}}
```

每个响应都带 `X-Request-Id`（客户端可传入，非法值会被替换），日志与错误体使用同一个 id。

## 开发约定

- `main` 永远可部署；每个里程碑打 tag `v0.1.0-mN` 并更新 `CHANGELOG.md`。
- 合并前必须 `make check` 通过（CI 同样门禁：ruff → mypy → pytest → 镜像构建）。
- 接口只加不破：改 `docs/api-contract.md` + OpenAPI 快照 + CHANGELOG 才能动已有语义。
- 密钥/DB/workspace 一律不入库（`.gitignore` 已覆盖 `var/`、`*.db`、`.env`）。
