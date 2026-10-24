# 运维一页（M5；随 M7 补充为完整 RUNBOOK）

> 单 VPS 拓扑下的日常：健康、指标、备份、告警、升级/回滚。

## 健康

- `GET /healthz`：进程存活（不碰 IO）；`GET /readyz`：DB 可写可读（LB 摘流用）
- 容器自带 HEALTHCHECK；compose 以 healthy 才起 Caddy

## 指标（/metrics，Prometheus 文本，需 Bearer admin key）

| 指标 | 含义 |
|---|---|
| `agentd_http_requests_total{status}` | HTTP 请求计数（按状态码） |
| `agentd_http_request_duration_seconds` | 请求延迟直方图 |
| `agentd_runs_total{status}` | run 终态计数（completed/failed/cancelled/…） |
| `agentd_run_duration_seconds` | run 时长直方图 |
| `agentd_sse_active_subscribers` | 当前 SSE 订阅数（并发观测） |
| `agentd_db_size_bytes` | SQLite 文件体量 |

Prometheus 抓取示例（prometheus.yml）：

```yaml
scrape_configs:
  - job_name: agentd
    authorization:
      credentials: agd_管理员key
    static_configs:
      - targets: ["agent.example.com:443"]
    scheme: https
```

人工速览用 `GET /v1/admin/stats`（JSON：run 状态分布/用量/成本/DB 体量）。

## 告警（最小实现）

`scripts/health_watch.py`：轮询 `/healthz`，连续 N 次失败 → 日志 + 可选 webhook，退出码 1。

```bash
# systemd/cron 每 5 分钟跑一次（--once 单次模式，失败即非零退出）
*/5 * * * * uv --project /opt/re-nano-agent run python scripts/health_watch.py \
  --base-url http://127.0.0.1:8000 --once --fail-after 1 \
  --webhook https://hooks.example/your-channel
```

外部 uptime 探针（推荐同时配一个）盯 `https://<域名>/healthz`。磁盘告警在 VPS 侧配（>80% 告警）。

## 备份（每日）

```bash
30 3 * * * DATA_DIR=/data BACKUP_DIR=/var/backups/agentd bash /opt/re-nano-agent/deploy/backup.sh
```

- 在线备份（SQLite backup API，服务不停）；产物 = agentd.db + workspace.tar.gz + SHA256SUMS
- 默认保留 7 份自动轮转；异地：把 BACKUP_DIR 放独立盘，或自备 rclone 同步到对象存储
- **每月至少一次恢复演练**：`deploy/restore.sh`（先 `docker compose stop app`）

## 升级 / 回滚

```bash
cd /opt/re-nano-agent && git pull --ff-only
docker compose up -d --build        # entrypoint 先迁移（失败不起服务）
# 回滚：git checkout <上一 tag> && docker compose up -d --build
```

升级前先跑一次 backup.sh；迁移不可逆时（CHANGELOG 会标注）从备份恢复。

## 日志

JSON 单行到 stdout（Docker 日志驱动轮转）；request_id/run_id 贯穿；key/token/password 已脱敏。关键错误检索：`level":"error`、`run.task_failed`、`runs.interrupted`。
