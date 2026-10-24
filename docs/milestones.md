# 里程碑（M0–M8）

> 每个里程碑 = 1 周（M0 为 3–5 天）。结束时打 tag `v0.1.0-mN`、更新 `CHANGELOG.md`、录 1 分钟 demo、登记技术债。

| 里程碑 | 时间 | 主题 | 核心交付 | DoD 摘要 | 状态 |
|---|---|---|---|---|---|
| M0 | Week 0 | 范围冻结 + 骨架 + 部署链 | 仓库/CI/FastAPI 空壳/SQLite 迁移/线上 hello | 线上 `/healthz` 可用；CI 绿 | 完成（线上 VPS 部署待执行） |
| M1 | Week 1 | Provider + Runner + 流式 | LLM 对话循环、工具调用回路、CLI demo | CLI 多轮+工具调用；取消不悬挂 | 完成（真实模型连通待人工验收） |
| M2 | Week 2 | 会话持久化 + 上下文 + 真工具 + 安全 | 文件/shell/web 工具、路径/SSRF guard、重启续聊 | 安全测试全绿；重启恢复 | 完成（安全 36 例全绿，重启续聊已验证） |
| M3 | Week 3 | 平台 API + 鉴权 + 并发 | sessions/runs/SSE/取消/限流/OpenAPI | curl 全流程；20 并发无 5xx | 完成（20 并发无 5xx；真实服务器冒烟待人工跑 smoke.sh） |
| M4 | Week 4 | SDK + 计量 + 审计 + 压缩 | Python SDK、usage/audit、摘要压缩 | 外部人员 30 分钟接入 | 完成（真人接入验证待人工执行，quickstart.md 已备） |
| M5 | Week 5 | 部署硬化 + 运维 + 可观测 | 非 root 镜像、备份恢复、metrics、安全复查 | 新机 30 分钟部署；备份演练 | 完成（线上演练项待 VPS，security-checklist 已分离标注） |
| M6 | Week 6 | 控制台（P1）+ 文档 + RC | Playground/Key/Usage（可砍）、文档站、v0.1.0-rc | 3 个内测用户按文档接入 | 完成（浏览器实测全链路；内测邀请待人工，见 human-checklist） |
| M7 | Week 7 | 内测迭代 + 稳定性 | 修 P0/P1、性能、故障演练、runbook | 连续 5 天无 P0；成功率>98% | 待开始 |
| M8 | Week 8 | 上线 + 复盘 | v0.1.0 上线、7 天稳定运行、复盘与 v0.2 | 上线检查单全绿 | 待开始 |

## 用 gh 批量建 issue

```bash
# 需先 gh auth login
bash scripts/create-milestones.sh <owner>/<repo>
```

脚本会为 M0–M8 各建一个 milestone + 每个里程碑在建一个 tracking issue（标签 `milestone`）。M0 已完成；若仓库尚未创建，脚本会失败，请在 `gh auth login` 之后重跑。
