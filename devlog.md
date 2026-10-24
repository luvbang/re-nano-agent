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

---

## 2026-10-24（M4 D1–D5 合并执行）

**完成**
- D1 SDK：sdk/agentd_client（uv workspace 成员）——AsyncClient（REST+SSE、断流 Last-Event-ID 自动重连）、Client 同步包装（后台事件循环线程 + 队列交接）、错误信封→类型化异常（RateLimitError 带 Retry-After）、retryable 指数退避、POST runs 自动幂等键；examples/ 两个示例
- D2 计量：AGENTD_LLM_PRICE_TABLE（坏配置退化不炸）、UsageService 成本双写（usage_records + runs.cost_usd）、/v1/usage 与 admin/stats 回报 cost_usd
- D3 审计与脱敏：AuditRepository + 接线（project/key/run/tool 全链路）、GET /v1/admin/audit（project/action 过滤）、JsonFormatter 输出前 redact（agd_/sk-/Bearer/敏感赋值四模式）
- D4 压缩 v1：HistoryCompactor（>60% 预算且足够长→LLM 摘要，role=summary checkpoint 带 covers_up_to；失败回退 builder 裁剪）；修复 checkpoint 行尾追加导致保留尾巴被丢的缺陷（按 seq 取视图）
- D5 文档：docs/quickstart.md（外部 5 分钟接入，含计时与卡点记录栏）

**证据**
- `ruff`/`mypy`（80 files）/`pytest` 全绿；176 测试（unit 87 + integration 50 + security 36 + sdk 6），分支覆盖 90%
- SDK 同步端到端对真实 uvicorn 线程跑通；429 重试、401 不重试、Retry-After 透传有专测
- 审计：project→key→run→tool 链路条目齐全，明文 key 不出现在审计 JSON 与日志输出
- 压缩：超限摘要落库、二次不重复摘要、provider 失败不落库不炸 run

**明日 3 件（M5 D1）**
1. 镜像优化：HEALTHCHECK、层缓存复核、SIGTERM drain SSE 验证
2. 备份/恢复：SQLite Online Backup + workspace 打包脚本、restore.sh、恢复演练
3. 反代加固：CORS 白名单、请求体大小限制、安全头复核

**阻塞（人工项，见 docs/human-checklist.md）**
- D5 真人接入验证：需外部同事只拿 quickstart.md 接入并记录卡点（文档已备计时栏）
- VPS 部署与真实模型 key（M1 起遗留）

**技术债（只登记不修）**
- SDK 未发 PyPI（quickstart 用 git subdirectory 安装）
- 审计的 actor 粒度粗（"api"/"admin"/"run:<id>"，无终端用户身份——M3 契约本就只有 external_user_id）
- 压缩摘要无异步预热（触发时同步等待一轮 LLM）

---

## 2026-10-24（M5 D1–D5 合并执行）

**完成**
- D1 硬化复核：HEALTHCHECK/非 root/246MB 均 M0 已备；docker stop 实拍优雅退出（Waiting→app.stopped→干净重启 healthy）
- D2 备份：deploy/backup.sh（SQLite backup API 在线快照 + workspace tar + SHA256SUMS + KEEP 轮转，PYTHON_BIN 可覆盖）、restore.sh（校验和强校验）；tar 一律 cd 后相对文件名（Windows 盘符会被 GNU tar 当 host:file）
- D3 边界：BodySizeLimitMiddleware（Content-Length 直接 413；分块预读缓冲——截断异常会被框架吞成 400）、AGENTD_CORS_ORIGINS 白名单（CORSMiddleware 最外层）、Caddy request_body 2MB 粗筛
- D4 可观测：api/metrics.py（零依赖 Prometheus 文本）+ 埋点（HTTP 请求/延迟、run 终态/时长、SSE 订阅 gauge、DB 体量）+ 裸 /metrics（管理员）+ scripts/health_watch.py + docs/ops.md
- D5 安全复查：pip-audit 0 漏洞；docs/security-checklist.md（已验证 vs 待线上分离）

**证据**
- 186 测试全绿（新增 backup 3 + body/CORS 5 + metrics 2）；mypy 85 files
- 恢复演练自动化：备份→毁数据→恢复后消息/workspace 完好；轮转 KEEP=2 生效
- /metrics：流量后 runs_total{completed}/duration 直方图/db_size 齐全
- 跨平台脚本测试要点：subprocess env 在 WSL bash 下不透传——显式挑 git-bash + bash -c 内联变量

**明日 3 件（M6 D1）**
1. 控制台骨架：登录 + Sessions + Playground（docs/web-architecture.md 已冻结）
2. Keys/Usage/Status 页
3. 打磨与构建产物进镜像（或按 P1 降级砍单——M5 末评审：进度未延期，保留）

**阻塞（人工项）**
- TLS 评级 / .env 0600 / 备份 cron / 异地副本 / trivy —— 全部待 VPS（security-checklist「待线上」段）
- 真人接入验证（M4 遗留）

**技术债（只登记不修）**
- 指标进程内存态（重启清零）；告警为脚本级（无 Prometheus AlertManager 集成）
- body-limit 中间件对无 Content-Length 请求采用预读缓冲（v0.1 请求皆小 JSON，可接受）

---

## 2026-10-24（M6 D0–D5 合并执行）

**完成**
- D0 后端支撑：GET /v1/sessions（rowid 决胜同毫秒稳定性）、_mount_console（显式 static_dir 优先，未构建无害）
- D1-D3 控制台 web/：React18+Vite+Tailwind+TanStack Query+react-router 六页——登录（双 key：管理员+项目）、Playground（SSE fetch 流式、completed 全文覆盖、工具卡展开）、Sessions、Keys（建 project/key/一次性明文/一键绑定/撤销）、Usage（CSS 条形图）、Status（health 徽章+stats）；投影纯函数 + vitest
- D3 构建链：Dockerfile node:22-alpine 阶段（NPM_REGISTRY 换源、dist 进镜像）、CI web job；ADR-008 裁剪：shadcn→手写原语、recharts→CSS 条（devlog 记录理由）
- D4 文档：sdk-guide / faq / api-reference / README 更新至 rc 状态（文档导航+离线体验入口）
- D5 发布 v0.1.0-rc

**证据**
- 189 测试全绿（后端 186 + 控制台支撑 3）；前端 vitest 5 例、tsc 零错；bundle gzip 79.5KB（预算 250KB）
- 浏览器实测（IAB）：登录→建 key→Playground「现在几点了？」→ get_time 工具卡(ok,0ms)+流式回答+用量 in14/out14 → Sessions/Usage/Status 全通；截图留 artifacts
- serve_fake.py 本地零配置演示（admin-local-demo）

**明日 3 件（M7）**
1. 内测 triage：收集卡点建 issue，修 P0
2. 性能：冷启动/SSE 批处理观察（P95 记录）
3. 故障演练补 RUNBOOK（上游断流/DB 锁/磁盘满）

**阻塞（人工项）**
- 邀请 2–3 个内测用户（quickstart.md + 项目 key）；真人接入验证（M4 遗留）
- VPS 部署后控制台线上可用性确认（HTTPS 下 SSE）

**技术债（只登记不修）**
- 控制台无端到端浏览器测试进 CI（本次人工验收；Playwright 冒烟 v0.2）
- Usage 图表无虚拟化（单实例量级小）；Keys 页无 project 重命名

---

## 2026-10-24（M7 + M8 机器可执行部分合并执行）

**完成**
- M7-D3 性能：scripts/perf.py（建会话→run→SSE 首事件→终态分位计时，TTFT 对照 Go/No-Go 自动判 PASS）+ docs/perf-baseline.md（本机基线 TTFT P95=59ms/预算 3000ms；吞吐 82rps；60/60 无失败）
- M7-D4 故障：断流/重试耗尽注入测试（run 落终态、事件可回放、会话可继续、审计留痕）+ docs/runbook.md（上游/DB 锁/磁盘满/OOM/证书/SSE 重连/数据恢复 七类处置）
- M7-D5 稳定性：docs/stability-report.md（证据矩阵+线上待填表）、announcement-draft.md；tag v0.1.0-rc2
- M8：docs/go-live-checklist.md（机器已验 vs 人工待办分离签收）、docs/operations.md（值班/巡检/模型切换/限流/对账/保留删除/轮换）、docs/retro.md（复盘+v0.2 优先级）

**证据**
- 191 测试全绿（+故障注入 2）；TTFT P95=59ms；docker stop/kill 路径全有自动化或实拍

**剩余 = 纯人工项（human-checklist 汇总）**
1. VPS+域名部署（≤30min 计时）→ 线上 HTTPS/控制台/SSE 验证
2. M5 线上硬化（.env 0600/备份 cron/TLS 评级/防火墙/trivy）
3. 真人接入验证（计时+卡点）与内测邀请 2–3 团队
4. 线上 5 天稳定运行数据回填 stability-report → 全绿后按 go-live-checklist 打 v0.1.0
