# devlog

每天收尾 15–30 分钟：写清「完成 / 明日 3 件 / 阻塞 / 技术债」。跨天只追加，不改历史。

## 模板

```md
## YYYY-MM-DD（Mx Dy）

**完成**
- ...

**证据**
- `make check` 通过；测试数 xx；关键 curl 输出 ...

**明日 3 件**
1. ...
2. ...
3. ...

**阻塞**
- ...

**技术债（只登记不修）**
- ...
```

---

## 2026-10-23（M0 D1–D5 合并执行）

**完成**
- D1 范围冻结：`V0.1-SCOPE.md`、`docs/architecture.md`、`docs/api-contract.md`、`docs/milestones.md`、issue 模板、`scripts/create-milestones.sh`
- D2 工程骨架：`uv` 项目（Python 3.12）、`create_app`、`/healthz` `/readyz`、错误信封、request-id、JSON 日志、ruff/mypy/pytest、pre-commit、CI
- D3 存储：schema v1 迁移（幂等）、`Database`（WAL/单写者）、`repositories.py`、tmp DB fixture
- D4 部署链：多阶段非 root Dockerfile、entrypoint、compose、Caddyfile、Makefile/tasks.py、`docs/deploy.md`
- D5 收尾：`DECISIONS.md`（7 条 ADR）、README、CHANGELOG、tag `v0.1.0-m0`

**证据**
- `ruff check .` → All checks passed；`mypy` → Success (28 files)；`pytest` → 27 passed
- 新克隆验证：`git clone` 到临时目录 → `uv sync` → `tasks.py migrate`（applied 001_init）→ `tasks.py check` 全绿
- `curl /healthz` → `{"status":"ok","version":"0.1.0","uptime_s":4.765}`，响应头带 `x-request-id`
- `curl /readyz` → `{"status":"ready","checks":{"db":"ok"}}`
- `curl /v1/nope` → 404 且 body 为错误信封、`request_id` 与响应头一致
- `tasks.py migrate` 连跑两次：`applied=none`（幂等）
- 镜像：`agentd:m0` 246MB；`docker exec id` → uid=10001（非 root）；`/data` 下 agentd.db + workspace；`docker stop` 日志出现 `app.stopped`；重启后 readyz 仍 ok
- compose 全栈：app healthy → caddy 启动；`http→https` 308；`curl -sk https://localhost:18443/healthz` 200 且带 HSTS/X-Frame-Options 等头

**明日 3 件（M1 D1）**
1. `Provider` 协议 + OpenAI-compatible SSE 解析（delta/tool_calls/usage/finish_reason）
2. respx 录制 fixture：纯文本流、工具调用流、429、断流
3. 错误归一化（model_error/timeout/rate_limited）

**阻塞**
- 无 VPS/域名 → 线上 `https://<domain>/healthz` 与「新机 30 分钟部署」耗时未验收
- 无 `gh`，GitHub connector 需授权 → 远程仓库与 milestone 未创建
- Docker Hub 直连不通（registry-1.docker.io 超时）→ 构建需带镜像源 build-arg（已参数化，`.env.example` 有示例）

**技术债（只登记不修）**
- `Database` 单连接把读也串行化了；M3 压测若发现读瓶颈，再拆读连接池
- 日志脱敏（key/token/password 模式）未实现 → M4 D3
- 未做 OpenAPI/SSE schema 快照测试 → M3 契约层补
- `docs/api-contract.md` 的 `/v1/*` 端点仅文档，代码尚未落地（M1–M4）
