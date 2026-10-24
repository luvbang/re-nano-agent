# RETRO 复盘（M8 D5）

> 项目侧复盘基于 M0–M7 执行记录（单人全职口径，实际：M0–M7 于 2026-10-23/24 两日完成——远快于 8 周排期，因为执行者是编码代理且跳过了所有人工等待项）。线上运营数据待部署后回填。

## 交付复盘（对照 V0.1-SCOPE）

- **P0 十项全部落地**：流式对话（SSE+续传）、工具调用（文件/web，shell 白名单）、会话持久化、多项目隔离、崩溃恢复、平台 API（鉴权/限流/错误码/OpenAPI/取消）、Python SDK（同步+异步+重试）、计量与审计、部署运维（一键起/备份恢复/健康/指标）、安全测试套件全绿。
- **P1 控制台保留并交付**（浏览器实测全链路），未动用砍单预案。
- 计划外完成：Web 控制台提前到 M6 一次成型；性能/故障基线脚本化。

## 执行数据（本地可测部分）

| 指标 | 值 |
|---|---|
| 测试 | 191 自动化（全绿）+ 前端 5 例 |
| 覆盖率（分支） | 89% |
| 平台 TTFT P95 | 59ms（预算 3000ms） |
| 20 并发 | 0 5xx，82 runs/s |
| 已知漏洞 | 0（pip-audit） |
| 提交 | 每里程碑逐步推送，tag m0…m5/rc/rc2 |

## 接入耗时

- 机器侧（quickstart 流程演练）：SDK/HTTP 全链路自动测试即等效路径，0 卡点。
- ☐ 真人接入实测：___ 分钟（M4 D5 人工项，quickstart 计时栏）。
- ☐ 内测用户数 / 首 run 成功率：待回填。

## 失败原因 Top（线上回填）

待部署后从 `agentd_runs_total{status="failed"}` 分解：model_error / rate_limited / timeout 占比 → 决定 v0.2 重心（备用 provider 自动切换 vs 限流调参）。

## 经验教训

- 提前量决定论：M0 冻结契约后，M1–M6 几乎零返工；两处唯一的设计返工（compaction covers_up_to、SSE 路由前缀）都在「先写测试」环节当场暴露。
- 工具链坑集中在「跨平台执行环境」（WSL/git-bash、CRLF、镜像源），而非业务逻辑——把这些固化成测试与文档后，后续里程碑零复发。
- 人工依赖项集中在三类：VPS/域名、真实 key、真人内测——代理无法替代，全部显式落在 human-checklist。

## v0.2 Roadmap（优先级序）

1. **MCP 支持**（外部工具生态，预期价值最高）
2. 多 provider（Anthropic 原生/Responses）+ 失败自动切换 + SSRF pinned transport
3. 记忆与自动整理（参考 nanobot Memory/Dream 思路，按需裁剪）
4. 控制台完善（文件预览/多会话切换/用量看板/移动端打磨/Playwright 冒烟进 CI）
5. Postgres + 多实例（Repository 抽象已就位，压测触发时启动）
6. 多通道接入（Telegram/Discord，产品需要时）
7. PyPI 发布 SDK 与 agentd 主包
