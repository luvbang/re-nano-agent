# OPERATIONS 运营手册（M8 D4）

> 面向「接手维护的人」。技术细节见 docs/ops.md（日常）与 docs/runbook.md（故障）。

## 值班与响应

单人自托管：无轮值。约定——P0（服务不可用/数据风险）当日处理；P1 48h；P2 周清。外部报告入口 = 公告中的反馈渠道，处理进 GitHub Issues（标 P0/P1/P2）。

## 日常巡检（5 分钟）

1. `/healthz` `/readyz` 绿（uptime 探针代劳，人工每周点一次控制台 Status 页）
2. `agentd_runs_total{status="failed"}` 周环比；审计页扫 `run.cancelled` 异常量
3. 磁盘 <80%；备份目录有今天的目录

## 模型切换 / 降级

改 `AGENTD_LLM_BASE_URL` + `AGENTD_LLM_MODEL`（+价格表同步），`docker compose up -d`。进行中的 run 落 cancelled/interrupted，客户端可重发。上游整体故障时同法切备用网关；SDK 侧对 retryable 已自动退避。

## 限流调整

- 单 key：控制台 Keys 页重建 key 时设 RPM（或 admin API）
- 全局：`AGENTD_RATELIMIT_GLOBAL_PER_MIN`（重启生效）
- 并发：`AGENTD_RUN_GLOBAL_CONCURRENCY` / `AGENTD_RUN_PROJECT_CONCURRENCY`

## 数据看板与对账

- 控制台 Usage 页（按天/模型，含成本）；/metrics 接 Grafana（ops.md 有抓取配置）
- 月度对账：`GET /v1/usage?group_by=model&date_from=月初` 与上游账单核对；偏差大时检查价格表配置

## 数据保留与删除

默认全量保留。删除某 project 全部数据：备份一次 → `sqlite3 /data/agentd.db "DELETE FROM projects WHERE id='<pid>'"`（级联清 sessions/runs/messages/usage）→ 重启。v0.1.0 后补内置 purge 命令（技术债已登记）。

## 升级 / 降级 / 回滚

见 docs/ops.md §升级；不可逆迁移以 CHANGELOG 为准。发布节奏：rc → 内测 5 天无 P0 → v0.1.0；此后小版本周发、破坏性变更提前一周公告。

## 密钥轮换

管理员 key（env）：改 `.env` 重启。项目 key：控制台新建 → 分发 → 撤销旧 key（撤销即生效，无需重启）。
