# RUNBOOK（M7 D4）：故障处置手册

> 每种故障：症状 → 判定 → 处置。通用第一步永远是 `GET /healthz /readyz` 与 `docker logs agent-platform-app-1`（JSON，grep `level":"error`）。

## 1. 上游模型 429 / 超时 / 断流

- **症状**：`run.failed {code: rate_limited|timeout|model_error}` 事件增多；`agentd_runs_total{status="failed"}` 上升。
- **判定**：`/metrics` 看 run 失败率；审计 `action=run.created` 量正常但 completed 少。
- **处置**：SDK 侧已自动退避重试（Retry-After 优先）。持续 429 → 控制台 Keys 页调低该 key 的 RPM 或全局限流（`AGENTD_RATELIMIT_GLOBAL_PER_MIN`）；换备用模型端点：改 `AGENTD_LLM_BASE_URL/MODEL` 后 `docker compose up -d`（连接中的 run 会落 cancelled/interrupted，客户端可重发）。
- **演练证据**：`test_fault_drills.py`（断流注入：run 落 failed、事件可回放、会话可继续）。

## 2. SQLite 锁（database is locked）

- **症状**：日志出现 `database is locked`；/readyz 503。
- **判定**：单写者架构下罕见；多见于备份脚本与外部进程同时长写。
- **处置**：`AGENTD_SQLITE_BUSY_TIMEOUT_MS` 已设 5s；确认没有第二个 agentd 实例指向同一 DB；备份用 backup.sh（backup API 不抢写锁）。仍复现 → 重启 app 容器（WAL 自动恢复）。

## 3. 磁盘满

- **症状**：写入报错 `no space left on device`；`agentd_db_size_bytes` 暴涨或容器日志异常大。
- **处置**：`docker system prune -f` 清悬空层；旧备份轮转确认（BACKUP_DIR 的 KEEP）；日志轮转靠 Docker（`max-size` 建议部署时配 `50m`）。清出空间后重启 app。预防：VPS 侧磁盘 >80% 告警（人工项 4.7）。

## 4. OOM / 进程被杀

- **症状**：容器退出码 137；重启后 runs 出现 interrupted。
- **判定**：`docker inspect` 看 OOMKilled。
- **处置**：单 run 内存峰值主要来自工具结果与超长上下文（已有 16k 截断兜底）；仍复现 → 调小 `AGENTD_RUN_GLOBAL_CONCURRENCY`，或升配。interrupted 的 run 客户端以 `run.failed(interrupted)` 收尾，可重发（M3 语义）。

## 5. 证书过期 / Caddy 异常

- **症状**：浏览器/SDK TLS 报错；80/443 不通但容器内 /healthz 正常。
- **处置**：`docker logs agent-platform-caddy-1`（ACME 续期失败会写明原因；80 端口被占/域名 DNS 变更是常见根因）；`docker compose restart caddy`。Caddy 自动续期，一般无需人工。

## 6. 客户端断线重连失败（SSE）

- **症状**：接入方反馈流中断后收不到后续。
- **判定**：让客户端带最后 seq 的 `Last-Event-ID` 重连；控制台 Playground 自带重连可直接验证。
- **处置**：若 run 已终态 → 回放即完整；若仍 running → 继续收新事件；两者都不行为平台 bug，抓 request_id 反查日志并提 issue。

## 7. 误删 / 数据损坏恢复

- 处置：停 app → `deploy/restore.sh`（校验和）→ 起 app（自动迁移）→ 抽查会话可用。演练证据：`test_backup_restore.py`。

## 升级 / 回滚

见 `docs/ops.md` §升级；不可逆迁移会在 CHANGELOG 标注。
