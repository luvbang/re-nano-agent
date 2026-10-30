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

默认全量保留。删除某 project 全部数据用内置命令（v0.2 起可用，替代手写 SQL）：

```bash
docker exec -it <app容器> python -m agentd.cli purge --project <pid>           # 只打印计划与各表行数
docker exec -it <app容器> python -m agentd.cli purge --project <pid> --yes     # 真正执行
```

- 先跑 `deploy/backup.sh`；执行后**审计日志保留**（`project_id` 置空，不随 project 消失）。
- 级联删除 sessions/runs/messages/run_events/tool_calls/usage_records/api_keys/memories（统计口径见 `ProjectRepository._CASCADE_COUNT_SQL`）。memories 的 `ON DELETE CASCADE` 由迁移 `004_memories_fk.sql` 补上（SQLite 不能 ALTER 外键，走重建表）。
- **workspace 目录不删**：命令结束会提示手动清理 `workspace/<project_id>`（避免误删仍在用的文件）。
- 退出码：0 成功 / 1 project 不存在 / 2 未加 `--yes`（只打了计划）。
- 会话级删除走 `DELETE /v1/sessions/{id}`（级联清消息与 runs，**usage 记录保留**、`run_id` 置空，对账不丢账）。

## 升级 / 降级 / 回滚

见 docs/ops.md §升级；不可逆迁移以 CHANGELOG 为准。发布节奏：rc → 内测 5 天无 P0 → v0.1.0；此后小版本周发、破坏性变更提前一周公告。

## 密钥轮换

管理员 key（env）：改 `.env` 重启。项目 key：控制台新建 → 分发 → 撤销旧 key（撤销即生效，无需重启）。
