# FAQ

**Q：数据存在哪里？会丢吗？**
SQLite（WAL）+ workspace 文件，都在 `AGENTD_DATA_DIR`（容器内 /data 卷）。每日备份脚本（`deploy/backup.sh`）+ 恢复演练见 `docs/ops.md`；kill -9 后重启未完成 run 标 interrupted，会话可继续。

**Q：支持哪些模型？**
任何 OpenAI-compatible 的 `/chat/completions` 端点（OpenAI/DeepSeek/通义/本地 vLLM/Ollama 兼容层均可）：配 `AGENTD_LLM_BASE_URL` + `AGENTD_LLM_API_KEY` + `AGENTD_LLM_MODEL`。v0.2 起还可选 `AGENTD_LLM_PROVIDER=openai|responses|anthropic`（后两者走 Responses API 与 Anthropic Messages 原生），并用 `AGENTD_LLM_FALLBACKS` 配故障切换链——主 provider 重试耗尽且尚未输出任何增量时整链切换，已输出的不切换（避免重复回答）。

**Q：怎么选模型？**
平台部署时定一个模型（`AGENTD_LLM_MODEL`）。调用方可在创建 run 时带 `model` 覆盖：`POST /v1/sessions/{id}/runs {"input":"...","model":"..."}`。注意 **SDK 的 `create_run()` 目前没有 `model` 形参**，需要请求级覆盖时直接发 HTTP。当前是单模型配置，传的值必须与平台模型一致，否则 400 `invalid_request`（可用值查 `GET /v1/models`）；多 provider 放开后放宽为白名单。控制台 composer 上有 chip 选择器，选中的模型会显示在工具条上。

**Q：怎么接 MCP 工具？**
服务端配 `AGENTD_MCP_SERVERS`（单行 JSON，形如 `{"fetch": {"url": "https://mcp.example.com/mcp", "token": "可选"}}`），重启后对每个服务器做 Streamable HTTP 握手与 `tools/list`，工具以原名注册进统一工具管线（超时/审计/截断/错误映射与内置一致）；单个服务器握手失败只记日志并跳过，不影响启动。MCP 工具不受 workspace/SSRF 限制，只接可信服务器。详见 `docs/mcp.md`。

**Q：断线后流式回答能续传吗？**
控制类事件（工具调用、完成、失败）从 `run_events` 回放；增量文本不落库，续传不补发——**以 `message.completed` 的全文为准**（SDK 已内置该语义）。运行中的 run 重连后继续收新事件。

**Q：工具能做什么？安全吗？**
v0.1 内置：echo、get_time、read_file/write_file/edit_file/list_dir（锁在 project workspace 内，路径穿越/软链全拒）、web_fetch（仅公网，SSRF 全段拦截）。shell 默认关闭，开启需 allowlist（详见 `docs/security-checklist.md`）。

**Q：怎么算钱？**
`AGENTD_LLM_PRICE_TABLE` 配每百万 token 单价后，每条 run 记录 cost_usd 并按天/模型聚合（`GET /v1/usage`）；未配价格表时只记 token 数。

**Q：多租户/多用户能吗？**
v0.1 是单管理员自托管：project 做数据隔离（key 绑 project，跨 project 一律 404），没有用户体系与计费。对外卖服务场景 v0.2 再议。

**Q：并发上限？**
单实例 SQLite：全局 8 / 单 project 4 个并发 run（`AGENTD_RUN_GLOBAL_CONCURRENCY` / `AGENTD_RUN_PROJECT_CONCURRENCY`，可配），超了排队（保持 `queued`）；同 session 串行（忙时 409）。另有全局 RPM 桶 `AGENTD_RATELIMIT_GLOBAL_PER_MIN`（默认 240）与 per-key RPM。20 并发压测无 5xx（M3 证据）。扛不住时迁 Postgres + 多实例（v0.2 路线图第 5 项，Repository 抽象已就位）。

**Q：控制台怎么开？**
镜像自带（构建时打进 `/home/agentd/web/dist`）；本地开发 `web/` 下 `npm run dev`（Vite 代理到 :8000）或 `uv run python scripts/serve_fake.py` 离线体验。登录用管理员 key；Playground 另需项目 key（Keys 页一键创建绑定）。

**Q：怎么升级/回滚？**
`git pull && docker compose up -d --build`（entrypoint 自动迁移）；回滚 checkout 上一 tag 重建。升级前先跑 backup.sh。

**Q：SDK 什么时候发 PyPI？**
现在仍是仓库内 workspace 成员，用 git 子目录安装（见 quickstart）。PyPI 发布是 v0.2 路线图第 7 项，进行中（打包元数据与 sdist 白名单正在补齐）；发布前请继续用 git 子目录安装。
