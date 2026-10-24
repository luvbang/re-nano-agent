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

---

## 2026-10-24（M1 D1–D5 合并执行）

**完成**
- D1 Provider：`providers/base.py`（协议/事件/错误归一化）+ `openai_compat.py`（httpx 手写 SSE、tool_calls 按 index 累积、usage、断流判定）+ `fake.py`（脚本化回放）
- D2 工具与 Runner：`tools/`（Tool 协议、注册表：存在性/JSON 解析/wait_for 超时/异常兜底/16k 截断、echo/get_time）+ `runtime/runner.py`（system+history+user、≤8 迭代、工具回路 wire 消息、usage 跨轮累计）
- D3 生命周期：`runtime/events.py`（契约事件类型）、`providers/retry.py`（未产出事件才重试、Retry-After 优先、指数退避封顶）、`runtime/tokens.py`（tiktoken 惰性加载 + 离线 fallback）、Settings 增 `llm_*/run_*`
- D4 CLI：`agentd chat --session demo [--fake]`（流式输出/工具事件/usage；失败轮不写回历史）；CI pytest 接入 --cov
- D5 闭环演示：`--fake` 下 模型→get_time/echo→模型→回答 全链路

**证据**
- `ruff check .` / `mypy`（44 files）/ `pytest` 73 passed；分支覆盖率 91%（TOTAL）
- CLI 实跑（`chat --fake`）：`[tool] get_time ok` → `工具 call_demo_1 的结果是：utc=2026-10-24T10:27:04Z ...`；usage 两轮累计 in=14
- 取消语义：aclose 与 Task.cancel 后 `provider.open_streams == 0`、无 pending task
- 退避可测：sleep spy 断言 [0.5, 1.0]，Retry-After 覆盖退避，封顶 2.5

**明日 3 件（M2 D1）**
1. schema v2 落地会话历史读写（messages repo）+ run 状态机接线
2. ContextBuilder：token 预算、超限裁剪旧工具结果、工具结果落盘
3. 文件工具 + workspace path resolver（路径穿越/软链测试先行）

**阻塞**
- 无 VPS/域名 → 线上部署验收与「新机 30 分钟」耗时仍欠（清单见 docs/human-checklist.md）
- 无真实 LLM key → openai_compat 仅 respx fixture 验证，真模型连通透传待人工

**技术债（只登记不修）**
- SSE 心跳/seq 编号属 M3 API 层；runner 事件目前无 seq
- 工具 JSON Schema 校验（additionalProperties）未做 → M2 随真工具补
- `Database` 读串行化、日志脱敏等 M0 遗留项不变

---

## 2026-10-24（M2 D1–D5 合并执行）

**完成**
- D1 持久化：MessageRepository（seq/分页/wire 还原）、RunRepository.finish、ToolCallRepository、UsageRepository；AgentRunner on_message 钩子；ChatService（run 状态机 + 消息/用量/工具调用落库）；CLI 会话落库
- D2 上下文：ContextBuilder 三级预算处置（裁旧 tool 结果→截断超长→报错）、Runner 映射 RunFailed(invalid_request)、工具结果 >16k 落盘 workspace/.runs/<run_id>/tool-results/
- D3 文件工具：WorkspacePathResolver（resolve containment + 逐段软链拒绝 + 盘符/UNC 拒绝）、read/write/edit/list 四工具带限额
- D4 安全：security/ssrf.py（全私网段/元数据/混合解析拒绝，resolve 可注入）、web_fetch 逐跳重定向校验、shell 工具默认关（allowlist 前缀 + cwd 锁定 + 超时 kill + 并发信号量）
- D5 闭环：读→改→总结 e2e + 安全套件汇整

**证据**
- `ruff`/`mypy`（58 files）/`pytest` 全绿；测试 122（unit 74 + integration 12 + security 36）
- 重启续聊：两个独立 CLI 进程同 session，DB 4 条消息按序、两条 run completed 带用量
- e2e：模型脚本化 read_file→edit_file→总结，notes.txt 真实从 draft 改为 final，6 条消息全落库
- 安全 36 例（DoD ≥15）：穿越/绝对路径/盘符/软链逃逸/越界写不落盘/SSRF 段/元数据/混合 IP/重定向入内网/shell 默认关/allowlist/cwd/超时击杀等；3 例软链在本机 Windows 跳过（CI Linux 执行）
- 覆盖率（分支）：88%

**明日 3 件（M3 D1）**
1. API 资源与鉴权：projects/api_keys/sessions 路由 + Bearer→project + 撤销即时生效
2. runs API：创建（Idempotency-Key）、状态、cancel、per-session 串行、并发信号量
3. SSE 端点：事件序列化 + seq + Last-Event-ID 回放 + 15s 心跳

**阻塞**
- 与 M1 相同：无 VPS/域名、无真实模型 key（docs/human-checklist.md）

**技术债（只登记不修）**
- SSRF 的 DNS rebinding 残余窗口（校验与连接间）→ v0.2 pinned transport
- 工具 JSON Schema 校验（additionalProperties）仍未做 → M3
- `tests/security` 的软链用例依赖类 Unix，Windows 开发机本地跳过（CI 全跑）

---

## 2026-10-24（M3 D1–D5 合并执行）

**完成**
- D1 鉴权：Bearer→project（实时查库，撤销即效）、agd_ key（sha256+prefix，明文仅创建返回一次）、admin 双通道（env key / DB admin scope）、/v1/admin/projects|keys、/v1/sessions(+messages 分页)
- D2 runs：RunManager（per-session 锁忙时 409、全局+项目信号量、事件先落库再广播）、POST runs（Idempotency-Key，迁移 002）、GET run、cancel、SSE 端点（契约事件名+seq、Last-Event-ID 回放、15s 心跳、run.cancelled 新增契约事件）
- D3 限流与平台端点：令牌桶（per-key RPM + 全局，惰性结算）、429+Retry-After、/v1/usage（day|model 聚合+日期过滤）、/v1/models、/v1/admin/stats
- D4 恢复：kill -9 场景（新进程收敛 interrupted + SSE 合成 run.failed(interrupted)）、活跃 run 中途重连不丢终态、优雅停机兜底扫描（未调度任务不留 queued）
- D5 冒烟与压测：scripts/smoke.sh（curl 全链路）、scripts/loadtest.py（asyncio 并发+分位延迟）、进程内 20 并发测试进 CI

**证据**
- `ruff`/`mypy`（70 files）/`pytest` 全绿；152 测试（unit 74 + integration 42 + security 36），分支覆盖 89%
- 20 并发（20 key × 各自 session）全部 completed 无 5xx；取消后同 session 可续跑（无残留锁）
- kill -9 模拟：DB 留 running + run.started 落库 → 新进程 GET run=interrupted、SSE 回放+合成终态
- SSE 重连：Last-Event-ID=1 不重复 run.started，终态全文到达

**明日 3 件（M4 D1）**
1. Python SDK：Client/Sessions/Runs/Usage 同步+异步、SSE 迭代器、错误映射、自动重试
2. usage 价格表配置（$/1M tokens）+ cost_usd 填充 + 按日聚合
3. audit log（run 创建/取消、key 创建/撤销、工具调用）+ 日志脱敏

**阻塞**
- 同 M1/M2：无 VPS/域名、无真实模型 key（human-checklist）
- smoke.sh/loadtest.py 需要跑在真实服务器上（本地 fake 已覆盖同等形态）

**技术债（只登记不修）**
- OpenAPI/SSE schema 快照测试未做 → M6 文档阶段补
- SSE 心跳 15s 在测试中未显式覆盖（超时路径代码简单）
- 限流器为进程内存态：重启清零（单实例可接受）；多实例需换 Redis（v0.2）
