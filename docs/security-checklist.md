# 安全检查清单（M5 D5；上线签收在 M8 复核）

> 「已验证」条目都有自动化测试或本地实证；「待线上」条目需要 VPS 环境人工执行（见 human-checklist）。

## 输入与传输

- [x] 请求体大小限制：应用层 1MB（413 错误信封；分块预读拦截）——`test_body_limit_cors.py`
- [x] Caddy 外层 2MB 粗筛 + gzip——`deploy/Caddyfile`
- [x] CORS 白名单（默认同源不加头；预检只放行白名单源）——`test_body_limit_cors.py`
- [x] 安全响应头：HSTS / X-Content-Type-Options / X-Frame-Options DENY / Referrer-Policy / COOP——M0 已验证 curl 响应头
- [ ] TLS 评级 A（SSL Labs）——待线上域名后人工跑

## 认证与密钥

- [x] API key 只存 sha256 + 前 12 位；明文仅创建时返回一次——`test_api_auth.py`
- [x] 撤销立即生效（每请求实时查库）——`test_api_auth.py`
- [x] 跨 project 资源一律 404 不泄漏存在性——sessions/runs 均有测试
- [x] `AGENTD_ADMIN_API_KEY` 常量时间比较；admin scope 走 DB
- [x] 日志脱敏：agd_/sk- key、Bearer、password/token/secret 赋值 → [REDACTED]——`test_audit_and_redaction.py`
- [x] 审计：project/key/run/tool 全链路可查——`GET /v1/admin/audit`
- [ ] `.env` 权限 0600（部署机）——待线上人工设置

## 工具与执行边界

- [x] workspace containment：`..`/绝对路径/盘符/UNC/软链（含中间目录、指向域内）全拒；越界写不落盘——`tests/security/`（36 例）
- [x] SSRF：私网/回环/CGNAT/链路本地（含 169.254.169.254）/组播/保留/ULA 拒绝；DNS 全地址校验；混合公私 IP 拒；逐跳重定向校验——`test_ssrf.py`
- [x] shell 默认关闭；开启需 allowlist 前缀 + cwd 锁定 + 超时 kill + 并发信号量——`test_shell_tool.py`
- [x] 工具结果 16k 截断 + 超限落盘（不进上下文）
- [ ] DNS rebinding 残余窗口（校验与连接间）——**v0.2 已清偿**：`security/pinned.py` 把校验阶段解析到的公网 IP 钉进连接层（TLS SNI/证书校验与 Host 头保持原主机名），`tests/security/test_pinned.py` 覆盖

## 数据与恢复

- [x] 备份在线一致快照（SQLite backup API）+ SHA256SUMS + 轮转；恢复演练自动化——`test_backup_restore.py`
- [x] 崩溃恢复：running→interrupted 收敛 + SSE 合成终态——`test_recovery.py`
- [x] 优雅停机：活跃 run 落 cancelled（docker stop 实拍干净退出）
- [ ] 每日备份 cron + 异地副本——待线上人工配置（docs/ops.md 有命令）
- [ ] 每月恢复演练——流程已自动化，待线上执行

## 依赖与镜像

- [x] pip-audit：**0 已知漏洞**（2026-10-24，uv run --with pip-audit）
- [x] 运行镜像非 root（uid 10001）、多阶段、246MB（<400 预算）
- [ ] trivy 镜像扫描——本机无 trivy，待 CI/线上（建议加到 VPS 部署流程）

## 限流与滥用

- [x] per-key RPM（key 级配置）+ 全局桶；429 + Retry-After——`test_api_platform.py`
- [x] per-session 串行（忙时 409）、全局/项目并发信号量——`test_api_runs.py`
- [x] run 时长上限（runner timeout）与迭代上限
