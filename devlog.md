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

## 2026-10-24（M2 + M6 前端提前执行）

> 背景：用户指示"按 ROADMAP 执行完整后进行前端代码编写"。M2（前端依赖的持久化/真工具/安全）与 M6 控制台前端同日完成；M3 `/v1` 端点未动工，前端按 web-architecture §7 以离线演示模式交付。

**完成**

- M2 D1 持久化：`MessageRepository`（seq 游标）、`ConversationService`（整轮粒度 token 裁剪、工具交换无损往返）、Runner `last_exchange`、CLI `--session` 标签跨进程续聊
- M2 D3 安全+真工具：`security/paths.py`（穿越/绝对/软链/盘符相对拒绝）、`security/ssrf.py`（DNS 全记录公网校验、IPv4-mapped 解包、重定向逐跳）、`tools/filesystem.py`、`tools/shell.py`（默认关）、`tools/web.py`（SSRF+文本+128KB）
- M6 控制台（web/，35 源文件）：六页面全量、SSE fetch 解析器（Last-Event-ID 重连/45s 心跳/退避封顶）、run 投影纯函数、离线演示客户端（脚本化事件流含工具回路）、FastAPI 同源挂载（SPA 回退/immutable 缓存/API 404 信封不变）、CI `web` job
- 发现并修复两个真 bug：投影 `message.completed` 会清空同段工具卡；run 完成后不失效历史导致下一轮发送时上一轮从视图消失

**证据**

- 后端：ruff / mypy（53 files）/ pytest **119 passed**（含穿越/软链/SSRF 全保留段/重定向拦截/重启续聊）
- 前端：vitest **14 passed**；tsc + vite build 通过，gzip **194.63KB**（< 250KB 预算）
- 浏览器实测（IAB，离线演示模式）：六页面渲染 ✓；Playground 三轮流式回答（Enter 与按钮两种提交）✓；工具卡"成功 · 418ms" ✓；usage 徽标 ✓；创建 Key 一次性 secret ✓；Usage 柱状图视觉确认 ✓
- `agentd serve :18432`：`/playground`、`/keys` SPA 回退 200；`/v1/nope` 错误信封 `not_found`；assets `immutable`、index `no-cache`
- CLI 重启续聊实跑：第二次启动 `已载入 10 条历史消息`（含工具轮 4 条消息）

**技术债（只登记不修）**

- M3 `/v1` 端点未落地：前端真实模式当前必然 401/网络错误，切真端点后需联调一轮（SSE 重连/回放实测）
- SSRF 校验与实际连接间存在 TOCTOU 窗口（严格做法：pin IP 连接）
- `agentd serve` 的 SPA catch-all 只注册 GET（HEAD 405，无实际影响）
- recharts 体积占 bundle 大头，v0.2 若加页面再考虑 code-split
- 工具 JSON Schema 参数校验（additionalProperties）仍未做 → 随 M3 契约层

---

## 2026-10-24（M3：平台 API + 鉴权 + 并发）

**完成**

- 鉴权与限流：`api/auth.py`（Bearer→sha256→key 行，撤销立即生效，core/admin scope）、`services/keys.py`（`AGENTD_ADMIN_API_KEY` 启动引导）、`security/ratelimit.py`（每 key 滑动窗口 RPM）
- RunService：后台任务 + 事件编 seq + 控制类事件落 `run_events`（delta 不落库）+ 订阅队列广播 + 终态收敛（completed/failed/cancelled）+ usage_records 计量 + 成功轮落库 + shutdown 收敛
- 端点：sessions CRUD/messages 分页、runs 202+幂等（Idempotency-Key 5min）+并发 409+取消、SSE（Last-Event-ID 回放/15s 心跳/终态关流）、admin keys（一次性 secret）、usage day/model 聚合、models
- provider 装配：`provider=auto` 无 key 回退 fake —— 离线全链路可跑（前端真实模式的联调基础）

**证据**

- `ruff` / `mypy`（62 files）/ `pytest` **131 passed**（新增 12 个 /v1 集成测试）
- 真实链路浏览器联调：`AGENTD_ADMIN_API_KEY` + fake provider → 控制台真实 key 登录 → Playground 发"现在几点了？" → 真实 SSE 流式 + 真实 get_time 工具卡（服务器当前时间）→ Usage 图表渲染当日真实 run（截图确认）

**技术债（只登记不修）**

- create_run 的冲突检查与插入非原子（两个同时到达的请求可能都过检）；v0.1 单管理员可接受，M5 压测若暴露再加活跃 run 唯一约束
- 20 并发 DoD 压测未执行（需要 M5 的部署环境）；SSE 重连/回放的浏览器侧实测待真实网络环境
- 限流为进程内存态，多副本部署需换共享存储
