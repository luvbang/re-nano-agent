# 稳定性报告（M7 D5，v0.1.0-rc2）

> 状态：**本地/CI 全绿**；「连续 5 天无 P0」与「成功率 >98%」需线上运行数据（部署后从 /metrics 与审计回填，见文末待填表）。

## 测试与门禁

- **191 个自动化测试全绿**：unit 90 / integration 65 / security 36（CI 阻塞）；前端 vitest 5 例、tsc 零错
- ruff + mypy(strict, 87 文件) 全绿；分支覆盖率 89%
- CI（GitHub Actions）：lint → type → test(coverage) → web(typecheck/test/build) → docker build

## 关键场景证据（均可复现）

| 场景 | 证据 |
|---|---|
| 20 并发无 5xx、取消无残留 | `test_concurrency.py` |
| kill -9 恢复（interrupted 收敛 + SSE 合成终态） | `test_recovery.py` |
| 优雅停机（活跃 run 落 cancelled） | 同上 + docker stop 实拍 |
| 上游断流/重试耗尽不悬挂、会话可继续 | `test_fault_drills.py`（M7 注入） |
| 备份→毁数据→恢复可用 | `test_backup_restore.py` |
| 路径穿越/软链/SSRF/shell 边界 | `tests/security/` 36 例 + security-checklist |
| 平台性能开销 TTFT P95=59ms（预算 3000ms） | `docs/perf-baseline.md` |
| 限流 429+Retry-After、鉴权撤销即效、跨 project 404 | `test_api_*` |

## 已知限制（对外文档已注明）

- SSE 续传不重放增量文本（以 message.completed 为准）；DNS rebinding 残余窗口（v0.2 pinned transport）；指标/限流为进程内存态（重启清零，单实例可接受）。

## 线上运行数据（部署后回填）

| 日期区间 | run 数 | 成功率 | P0 次数 | TTFT P95(真实模型) |
|---|---|---|---|---|
| — | 待填 | 待填 | 待填 | 待填 |
