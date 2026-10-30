# 架构决策记录（ADR）

> 只记录"为什么"，不重复"怎么做"（怎么做见代码与 docs/architecture.md）。
> 每条：背景 → 决策 → 代价 → 何时该翻案。

## ADR-001 用 FastAPI + uvicorn 做接入层

- **背景**：平台能力以 HTTP/SSE 交付，OpenAPI 文档本身就是交付物（外部团队要照着接）。
- **决策**：FastAPI。`create_app()` 工厂而非模块级 app，避免导入副作用（建目录/连库）。
- **代价**：FastAPI 依赖 pydantic 生态，版本升级需跟；框架层异常需自己映射成契约错误码（已由 `api/errors.py` 兜住）。
- **翻案条件**：不需要 OpenAPI/文档、或需要裸 ASGI 极致控制时。

## ADR-002 SSE 而不是 WebSocket

- **背景**：服务端单向推送为主，客户端只需要发"创建 run / 取消 run"这类普通 POST。
- **决策**：SSE（`StreamingResponse` 手写，M3 落地）。中间件用纯 ASGI 实现，避免 `BaseHTTPMiddleware` 对流式响应的缓冲；Caddy 侧 `flush_interval -1`。
- **代价**：断线续传要自己做（`Last-Event-ID` + `run_events` 回放）；delta 不落库，续传不补历史增量（写进对外文档的限制）。
- **翻案条件**：需要客户端→服务端实时双向（如 mid-turn 注入），v0.2 再评估 WebSocket。

## ADR-003 SQLite（WAL）+ 手写迁移，不用 ORM

- **背景**：单实例、自托管、零运维优先；v0.1 没有 DBA。
- **决策**：`sqlite3` + `isolation_level=None` 显式事务；单连接 + 一把 `asyncio.Lock` + `asyncio.to_thread` 做**单写者**；迁移是带编号的 `.sql` 文件 + `schema_version` 表，幂等。
- **代价**：写并发上限就是单写者；所有 DB 调用串行化（读也被串行化，牺牲一部分并发）。多实例不可行。
- **翻案条件**：单实例扛不住并发或数据量 → 通过 `repositories.py` 换 Postgres（SQL 只出现在 Repository 层）。

## ADR-004 schema 里"模型历史"与"事件历史"分表

- **背景**：SSE 回放需要事件轨迹；模型回放只需要干净的 messages。
- **决策**：`messages` 是模型 prompt 的唯一真相；`run_events` 只存控制类事件（`run.started`/`tool.*`/`message.completed`/`run.*`），`delta` 不入库。
- **代价**：断线期间丢失的增量文本无法补发（客户端以 `message.completed` 为准）。
- **翻案条件**：产品需要"逐字复现历史回答"→ 加 delta 环形缓冲或落库。

## ADR-005 日志用 stdlib + 自定义 JSON Formatter，不引入 structlog

- **背景**：需要一个 JSON 单行、带 request_id/run_id 的日志，且能在极简镜像里跑。
- **决策**：`logging` + `JsonFormatter` + `ContextVar`。uvicorn 的 logger 统一 propagate 到 root，关闭其 access log（访问日志由 request-id 中间件输出，避免重复且自带 request_id）。
- **代价**：没有 structlog 的 processor 链（脱敏/采样要自己写，M4 做）。
- **翻案条件**：需要复杂日志管道（多 sink、采样、字段脱敏策略）时换 structlog。

## ADR-006 单写者 + 启动时收敛状态机

- **背景**：`kill -9` 后 DB 里会留 `running` 的 run，客户端会永远等不到终态。
- **决策**：run 状态机 `queued → running → completed|failed|cancelled|interrupted`；进程启动在 lifespan 里把 `queued`/`running` 一律置为 `interrupted` 并写 `finished_at`。
- **代价**：未完成的 run 不可续跑，只能重新发一轮（v0.1 接受）。
- **翻案条件**：需要"断点续跑"时，M7 之后加 checkpoint 重放。

## ADR-007 任务入口同时提供 Makefile 与 scripts/tasks.py

- **背景**：CI 与 Linux 部署机习惯 `make`；本地是 Windows，没有 `make`/`gh`。
- **决策**：真逻辑写在 `scripts/tasks.py`（无第三方依赖），Makefile 只做薄壳转发。CI 用 `uv run`，本地用 `uv run python scripts/tasks.py`。
- **代价**：两套入口要一起维护（但 Makefile 只有一行转发）。
- **翻案条件**：全面改用 `uv run` + `just`，或 CI/开发环境统一到 Linux。

## ADR-008 控制台前端：同仓同源，React+Vite+shadcn，消费 SSE 而非 WebSocket

- **背景**：M6 需要一个 P1 的极简控制台（Playground/Keys/Usage/Status）；参考对象 nanobot WebUI 是 Vite + React 18 + TS + Tailwind + shadcn/ui，但其复杂度（WS 多路复用、19 通道投影、两阶段提交）来自我们不存在的需求。
- **决策**：前端放仓库 `web/`，构建产物由 FastAPI StaticFiles 同源服务（用户零 Node 依赖）；栈与 nanobot 同族（React 18 + Vite + Tailwind + shadcn/ui）；数据面只消费自己的契约（REST + SSE）；SSE 用 fetch 流解析（EventSource 带不了 Authorization 头）；服务器状态 TanStack Query、流式状态页面内 hook、全局仅 auth key 一个 context。设计详见 `docs/web-architecture.md`。
- **代价**：多一条 npm 构建链（CI 加 Node 步骤、Docker 加 builder 阶段，`NPM_REGISTRY` 参数化应对网络受限）；React 18 而非 19（与参考实现同代，升级留给 v0.2）。
- **翻案条件**：M5 末评审若砍控制台（P1 降级），本文档与目录结构保留到 v0.2；若 v0.2 需要多 run 全局活动流/双向交互，重估 WebSocket（同时翻 ADR-002）。

## ADR-009 Postgres + 多实例：保留抽象、设触发条件、暂不实施

- **背景**：ADR-003 的翻案条件「单实例扛不住」一直没有量化口径，导致 Postgres 迁移处于「人人知道要做、没人知道何时做」的状态。同时排查发现 Repository 边界并非铁板一块：`api/routes/admin.py`、`api/routes/platform.py`、`api/routes/health.py`、`cli.py`、`services/usage_service.py` 里有直接拼 SQL 的 `db.execute`/`db.fetch_all`（本次已全部收敛进 `repositories.py`；工具装配也一并收口到 `tools/factory.py`，`main.py` 与 `cli.py` 不再各拼一份）。当前压测基线（`docs/perf-baseline.md`）：20 并发 × 60 runs 全部成功，吞吐 82 runs/s，TTFT P95 59ms（fake provider，即平台自身开销）；单进程内 `run_global_concurrency=8`、`run_project_concurrency=4` 两道信号量先把并发压住了——**瓶颈是进程内信号量，不是 SQLite**，换 Postgres 不会提高这两个数字。
- **决策**：**现在不做 Postgres，也不做多实例**；把迁移条件写死为可观测的四个阈值，任一**持续 2 周**命中才启动（避免单日毛刺触发一次高风险重构）：
  1. **写入吞吐**：写类接口（建 run / 建会话 / 消息落库）持续 > **50 write/s**，或 `database is locked` / busy_timeout 告警 > **1 次/天**。注意 82 runs/s 是「突发并发提交」不是稳态：每个 run 至少写 `runs`（状态 2 次 + 终态）+ `messages`（user/assistant）+ `tool_calls`/`run_events` + `usage_records` + `audit_logs` 十余行，稳态 50 write/s 约等于 **4~5 runs/s 持续满载**；本机实测单连接顺序写 **5736 rows/s**（WAL，500 行 87ms），余量约两个量级。
  2. **数据库体量**：`agentd_db_size_bytes` > **20 GB**，或单表（`run_events`/`messages`）> **5000 万行**——此时 WAL 增长与 VACUUM 开始影响运维窗口；`deploy/backup.sh` 用 SQLite 在线 backup API（不锁写入方），但每次仍是**全量拷贝**，RPO/RTO 随体量线性劣化。
  3. **并发 run 数**：**持续**撞满全局信号量（queued 队列 P95 等待 > **30s**），且已把 `run_global_concurrency` 调到单机 CPU/内存上限。
  4. **多副本成为硬需求**：需要零停机滚动发布、跨可用区容灾，或单机规格（当前假设 4C8G）不够用。**只有这一条不能靠调参绕过**——其余三条都可以先通过调信号量、归档旧数据、加索引解决。
  守住「保留抽象但不泛化」的边界：`repositories.py` 继续是唯一 SQL 层，新增 SQL 一律进 Repository；但**不预先写 dialect 分支、不做连接池抽象、不引入 SQLAlchemy**——真迁的时候一次性改，比维护两套半成品便宜。
- **代价**：**多实例不可行**（单写者 + 进程内信号量/限流器/指标都是内存态，两个实例会各算一份，限流失效且指标错乱）；**单机故障 = 服务中断**（无 HA，恢复靠 `deploy/backup.sh` + 重启，RTO 分钟级）；写入串行化在极端并发下会把读也一起排队（同一把 `asyncio.Lock`）。迁移本身的已知坑（真做时必须逐条处理）：自增主键 `run_events.id`（SQLite `AUTOINCREMENT` → Postgres `GENERATED ... AS IDENTITY`，且 SSE 续传只依赖 `(run_id, seq)` 不依赖该 id，可安全换）、**`rowid` 决胜排序**（`SessionRepository.list_by_project` 用 `ORDER BY created_at DESC, rowid DESC` 保证同毫秒稳定序，Postgres 无 `rowid`，要换成显式序列表或 `ctid` 之外的自增列）、时间戳（现有 SQL 用 `strftime(...)`/`datetime('now')` 生成 ISO-8601 **UTC 字符串**，Postgres 需改 `timestamptz` 或保留字符串以维持 OpenAPI 契约里 `created_at` 的字符串形态——**这是最容易破坏契约的一处**；另有 `datetime('now', '-5 minutes')` 这类相对时间修饰符要改写成 `now() - interval`）、`?` → `%s` 占位符、`INSERT OR IGNORE`/`ON CONFLICT` 语义、迁移文件的 dialect 分叉（建议 `migrations/postgres/` 平行目录而非单文件条件分支）、`Database._lock` 换成连接池、以及 `sqlite3.Row` → dict 的行工厂差异。
- **翻案条件**：上面四个阈值任一持续命中 2 周 → 按本 ADR 的迁移坑清单开工；在此之前，任何「顺手把 Repository 抽象成 SQLAlchemy/方言层」的提议一律驳回（YAGNI，且会让 ADR-003 的单写者优势变得难以推理）。
