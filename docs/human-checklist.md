# 人工执行清单（M0/M1 遗留 + 无法自动化的事项）

> 生成于 2026-10-24（M1 完成后）。按优先级排序；每项标明了来源里程碑与预计耗时。
> 代码侧能自动做的都已做完并推送（`luvbang/re-nano-agent`，main + tag `v0.1.0-m1`）。

## 已跳过项（机器执行不了，原因标注）

| 跳过项 | 来源 | 原因 | 状态 |
|---|---|---|---|
| 线上 `/healthz` 验收 | M0 D4 DoD | 无 VPS/域名 | 本机已走通 Caddy HTTPS → app → SQLite 全链路；线上步骤见 `docs/deploy.md` §1–§5 |
| 真实模型连通 | M1 D5 DoD | 无 LLM API key | Provider 已用 respx fixture 全覆盖（文本流/工具流/429/5xx/超时/断流）；真 key 冒烟待人工 |
| M1 demo 视频 | 约定（每里程碑） | 需录屏 | 脚本见下方 §3 |
| GitHub milestones/issues | M0 D1 遗留 | 本机无 `gh` | `scripts/create-milestones.sh` 已就绪，待有 gh 的环境执行 |
| CI secrets / 镜像推送 | M5 预告 | 仓库设置页操作 | 属 M5，到时一起做 |

## 1. 真实模型冒烟（~10 分钟，建议先做）

```bash
cd D:/git-project/agent-platform
# .env 里取消注释并填入（或用环境变量）：
#   AGENTD_LLM_API_KEY=sk-...
#   AGENTD_LLM_BASE_URL=https://api.openai.com/v1   # 或任何 OpenAI 兼容网关
#   AGENTD_LLM_MODEL=gpt-4o-mini
uv run python -m agentd.cli chat --session smoke
# 验收：能流式回答；问"现在几点"若模型不调用工具属正常（工具调用取决于模型）；
# Ctrl+C 中断、exit 退出、失败提示 [failed:...] 均符合预期。
```

不需要 key 的离线体验：`uv run python -m agentd.cli chat --fake`。

## 2. VPS + 域名线上部署（~30 分钟，M0 遗留 DoD）

前置：一台全新 VPS（Ubuntu 22.04+，2C4G 起步）+ 一个域名（A 记录指到 VPS）。
完整步骤：`docs/deploy.md` §1–§5（已按 30 分钟目标写好），要点：

```bash
# VPS 上（示例；细节以 deploy.md 为准）
curl -fsSL https://get.docker.com | sh
git clone git@github.com:luvbang/re-nano-agent.git && cd re-nano-agent
cp .env.example .env && nano .env        # AGENTD_DOMAIN=你的域名、ACME_EMAIL=邮箱
docker compose up -d --build
curl https://<你的域名>/healthz           # DoD：返回 {"status":"ok",...}
```

验收后在 `docs/deploy.md` §10 勾掉对应项，并在 devlog 记录实际耗时（Go/No-Go 指标「新机 30 分钟」）。

## 3. 录 M1 demo 视频（~5 分钟）

30–60 秒，建议脚本：`uv run python -m agentd.cli chat --fake` → 输入「现在几点了？」展示 `[tool] get_time ok` 与回答 → 输入 `/echo 演示` → exit。存到 `docs/demos/` 或外部（视频不入 git）。

## 4. GitHub 仓库设置（~10 分钟）

- **Milestones**：在有 `gh` 的机器上 `gh auth login` 后运行 `bash scripts/create-milestones.sh luvbang/re-nano-agent`；或网页手动建 M0–M8（名字见脚本）。
- **分支保护**（建议）：Settings → Branches → `main`：要求 CI 通过才可合并（单人 trunk-based 也值得开，防自己直推坏提交）。
- **CI 确认**：Actions 页确认最新提交（`feat(m1): chat REPL command...`）的 lint/type/test(coverage) 与 docker build 全绿。

## 5. 网络备注（本机环境）

- GitHub SSH 22 端口间歇被 reset；备用通道已配好：
  `git push ssh://git@ssh.github.com:443/luvbang/re-nano-agent.git main`（主机密钥已入 known_hosts）。
- Docker 构建若拉镜像超时：`.env` 里启用 daocloud 镜像源（`.env.example` 有全部示例）。

## 4.5 真人接入验证（M4 D5，~30 分钟 + 当天修文档）

找 1 位外部同事/朋友，只给 `docs/quickstart.md`（不给口头帮助）：

- 记录开始/完成时间（文档末尾有计时栏）与每个卡点
- 当天根据卡点修文档或代码，把耗时写回 devlog
- 30 分钟内完成即达成 Go/No-Go 指标；超时也照实记录

## 4.7 M5 线上硬化项（VPS 就绪后，~40 分钟）

- 部署机上 `chmod 600 .env`
- `crontab -e` 加每日备份（命令见 docs/ops.md §备份）+ health_watch 定时（§告警）
- https://www.ssllabs.com/ssltest/ 跑 TLS 评级（目标 A）
- 防火墙只放行 80/443/SSH：`ufw allow 80,443/tcp && ufw enable`
- （可选）`docker run --rm -i aquasec/trivy image agentd:m5` 镜像扫描

## 4.9 内测邀请（M6 D5，~1 小时）

邀请 2–3 个内部/朋友团队，每人发三样东西：

1. 平台地址 + 管理员为他们建的 project key（你操作：控制台 Keys 页或 admin API）
2. `docs/quickstart.md`（5 分钟接入，含计时栏）
3. `docs/faq.md` 链接

收集：接入耗时、卡点、首次 run 是否成功。P0 问题当天修（M7 triage 素材）。

## 完成后

把各项结果（成功/失败/实际耗时）记进 `devlog.md` 对应日期条目；M2 起按 `docs/milestones.md` 继续。
