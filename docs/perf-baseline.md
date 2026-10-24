# 性能基线（M7 D3）

> 测量工具：`scripts/perf.py`（建会话→建 run→SSE 首事件→终态，分位统计）。
> 口径：**fake provider**，即「平台自身开销」——Go/No-Go 的「首 token P95 < 3s（模型自身延迟除外）」正是此口径；真实模型延迟叠加后另行在 VPS 复测（人工项）。

## 基线（2026-10-24，本机 Windows / uvicorn 单进程 / SQLite WAL）

| 指标 | P50 | P95 | P99 |
|---|---|---|---|
| run 创建（POST → 202） | 119 ms | 209 ms | 210 ms |
| **首事件（TTFT，202→SSE 首个事件）** | **50 ms** | **59 ms** | **60 ms** |
| 完成（202→终态事件） | 58 ms | 70 ms | 78 ms |

- 并发 20 × 60 runs：全部成功（0 失败 / 0 5xx），吞吐 82 runs/s，墙钟 0.73s
- 会话串行锁、全局/项目信号量在 20 并发下无死锁（与 M3 压测一致）

结论：平台开销对「首 token <3s」预算的占用可忽略（~2%）；线上 P95 将由模型侧延迟主导。

## 复测方法

```bash
uv run python scripts/serve_fake.py --port 8738 &
uv run python scripts/perf.py --base-url http://127.0.0.1:8738 \
  --admin-key admin-local-demo --concurrency 20 --runs 60
```

线上（真实模型）：对 VPS 跑同一脚本（ADMIN_KEY 换管理员 key），把结果追加到下表。

| 日期 | 环境 | 并发 | TTFT P95 | 备注 |
|---|---|---|---|---|
| 2026-10-24 | 本机 fake | 20×60 | 59ms | 平台开销基线 |
| — | VPS 真实模型 | — | 待测 | 人工项 |
