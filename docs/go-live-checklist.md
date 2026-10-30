# 上线 Checklist（M8 D1 逐项签收）

> 沿用 ROADMAP §9 结构。〔✅ 机器已验 ｜ ☐ 人工待办〕。全部勾完才打 v0.1.0。

## 功能

- ✅ Quickstart 从零跑通路径（quickstart.md 已含计时栏；真人耗时待记录 → ☐ M4 D5 人工项）
- ☐ SSE 流式、工具调用、取消、重连在**线上域名**人工验证一遍（本地/进程内已全测）
- ✅ 崩溃恢复演练（kill -9）自动化；☐ 线上 `docker kill` 复演一次留记录
- ✅ SDK 安装/示例/错误处理验证（测试 + examples）

## 安全

- ✅ 安全测试套件全绿（36 例，CI 阻塞）；✅ pip-audit 0 漏洞
- ☐ `.env` 0600；✅ 密钥不落日志/审计（脱敏测试）；key 明文仅创建返回
- ☐ CORS 白名单线上配置（如控制台跨域使用）；✅ 安全响应头（M0 已验）
- ✅ shell 默认关闭；✅ workspace 越界测试
- ✅ 限流生效；✅ 管理端点仅管理员

## 运维

- ☐ 全新 VPS 30 分钟内部署完成（deploy.md 步骤 + 计时）
- ☐ 每日备份 cron 就位 + 一次线上恢复演练记录
- ☐ health_watch/uptime 探针 + 磁盘告警接线
- ☐ 升级/回滚演练（<5 分钟）记录
- ✅ 容量基线：20 并发无 5xx、TTFT P95=59ms（fake）；☐ 真实模型 P95 补测

## 交付物

- ✅ 文档集：quickstart / sdk-guide / api-reference / faq / deploy / ops / runbook / security-checklist / perf-baseline / stability-report
- ✅ 2 个可运行示例（examples/）+ smoke.sh + loadtest.py + perf.py
- ☐ CHANGELOG 定稿 + v0.1.0 tag + 镜像 tag（本清单全绿后）
- ☐ 隐私/数据保留说明上线页脚。**删除命令已实装**（v0.2，`58a96eb`）：`docker exec … python -m agentd.cli purge --project <id> [--yes]`，用法与级联范围见 `docs/operations.md` §数据保留与删除。注意「数据默认保留 90 天」目前只是**记忆陈旧阈值**（`AGENTD_MEMORY_STALE_DAYS`，供 `agentd dream` 归档判定），**不是全库保留策略**——页脚措辞别把两者混为一谈。
- ☐ 支持渠道（公告中填写）
