# 发布公告草稿（v0.1.0，M8 D5 用；发布时替换占位符）

---

**agentd v0.1.0 发布：可自托管的 Agent 运行时**

一行介绍：外部团队用自己的 API Key，通过 HTTP/SSE 或 Python SDK 创建会话，获得带工具调用（文件/web，可选 shell 白名单）的流式 Agent 回答；崩溃后会话可恢复，用量与审计可查，一条 `docker compose up` 完成部署。

**五分钟接入**：docs/quickstart.md（计时实测：___ 分钟）。同步 + 异步 SDK、断线续传、类型化错误与自动重试开箱即用。

**内置控制台**：登录即用——Playground 流式对话（工具调用实时可见）、API Keys 管理、用量图表、系统状态。

**自托管友好**：单 VPS + SQLite，每日在线备份与恢复脚本、Prometheus 指标、审计日志、路径/SSRF/shell 安全边界全套内置（安全清单逐条可验）。

**路线**：v0.2 聚焦 MCP 工具生态、多 provider、Postgres 多实例（详见 RETRO）。

试用入口：________（部署地址）· 文档：________ · 反馈渠道：________

---

（内测期公告可先用此稿，标题改为「agentd v0.1.0-rc 开放内测」。）
