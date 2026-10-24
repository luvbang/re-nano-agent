# FAQ

**Q：数据存在哪里？会丢吗？**
SQLite（WAL）+ workspace 文件，都在 `AGENTD_DATA_DIR`（容器内 /data 卷）。每日备份脚本（`deploy/backup.sh`）+ 恢复演练见 `docs/ops.md`；kill -9 后重启未完成 run 标 interrupted，会话可继续。

**Q：支持哪些模型？**
任何 OpenAI-compatible 的 `/chat/completions` 端点（OpenAI/DeepSeek/通义/本地 vLLM/Ollama 兼容层均可）：配 `AGENTD_LLM_BASE_URL` + `AGENTD_LLM_API_KEY` + `AGENTD_LLM_MODEL`。v0.1 单 provider；Anthropic 原生/Responses 协议 v0.2。

**Q：断线后流式回答能续传吗？**
控制类事件（工具调用、完成、失败）从 `run_events` 回放；增量文本不落库，续传不补发——**以 `message.completed` 的全文为准**（SDK 已内置该语义）。运行中的 run 重连后继续收新事件。

**Q：工具能做什么？安全吗？**
v0.1 内置：echo、get_time、read_file/write_file/edit_file/list_dir（锁在 project workspace 内，路径穿越/软链全拒）、web_fetch（仅公网，SSRF 全段拦截）。shell 默认关闭，开启需 allowlist（详见 `docs/security-checklist.md`）。

**Q：怎么算钱？**
`AGENTD_LLM_PRICE_TABLE` 配每百万 token 单价后，每条 run 记录 cost_usd 并按天/模型聚合（`GET /v1/usage`）；未配价格表时只记 token 数。

**Q：多租户/多用户能吗？**
v0.1 是单管理员自托管：project 做数据隔离（key 绑 project，跨 project 一律 404），没有用户体系与计费。对外卖服务场景 v0.2 再议。

**Q：并发上限？**
单实例 SQLite：全局 8 / 单 project 4 个并发 run（可配），超了排队；同 session 串行（忙时 409）。20 并发压测无 5xx（M3 证据）。扛不住时 v0.2 迁 Postgres（Repository 抽象已留）。

**Q：控制台怎么开？**
镜像自带（构建时打进 `/home/agentd/web/dist`）；本地开发 `web/` 下 `npm run dev`（Vite 代理到 :8000）或 `uv run python scripts/serve_fake.py` 离线体验。登录用管理员 key；Playground 另需项目 key（Keys 页一键创建绑定）。

**Q：怎么升级/回滚？**
`git pull && docker compose up -d --build`（entrypoint 自动迁移）；回滚 checkout 上一 tag 重建。升级前先跑 backup.sh。

**Q：SDK 什么时候发 PyPI？**
v0.1-rc 阶段用 git 子目录安装（见 quickstart）；v0.1.0 正式发布时随主包发 PyPI。
