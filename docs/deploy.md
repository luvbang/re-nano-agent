# 部署（单 VPS，目标 ≤30 分钟）

拓扑：`Internet → Caddy(80/443, 自动 TLS) → app:8000 → /data`（SQLite + workspace + 后续备份）。

## 0. 前置

- 一台 2–4 vCPU / 4–8 GB 的 VPS（Debian/Ubuntu）
- 一个解析到该 IP 的域名（A 记录）
- Docker + Docker Compose 插件

## 1. 装 Docker（一次性）

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker
docker compose version
```

## 2. 防火墙

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80,443/tcp
sudo ufw allow 443/udp      # HTTP/3
sudo ufw --force enable
```

只开 22/80/443：app 的 8000 不对公网暴露（compose 里只有 `expose`）。

## 3. 取代码 + 配置

```bash
git clone <repo> agent-platform && cd agent-platform
cp .env.example .env
$EDITOR .env
```

`.env` 生产最小集：

```ini
AGENTD_ENV=prod
AGENTD_LOG_JSON=true
AGENTD_DOMAIN=agent.example.com
AGENTD_IMAGE_TAG=0.1.0
ACME_EMAIL=you@example.com
```

## 4. 起服务

```bash
make up          # 无 make 时：uv run python scripts/tasks.py up
docker compose ps
```

迁移在容器启动时自动执行（`entrypoint.sh` 先 `agentd migrate` 再起 uvicorn；迁移失败容器不会起）。

## 5. 验收

```bash
curl -sS https://agent.example.com/healthz     # {"status":"ok",...}
curl -sS https://agent.example.com/readyz      # {"status":"ready",...}
curl -sS https://agent.example.com/openapi.json | head -c 200
docker compose logs -f app                     # JSON 单行日志
```

证书：Caddy 自动申请，首次约 10–30s；失败看 `docker compose logs caddy`。

## 6. 升级

```bash
git pull
# 若有新迁移，容器启动时自动应用（先备份 DB 再升级，见 M5）
docker compose up -d --build
docker compose ps
```

回滚：把 `AGENTD_IMAGE_TAG` 改回上一版本并 `docker compose up -d`（镜像需已推送；M5 落 CI 推送）。

## 7. 本地验证同样的镜像（可选）

```bash
docker compose build
docker compose up -d
curl -sS http://127.0.0.1/healthz -H 'Host: localhost'
```

## 8. 已知待办（M5 补齐）

- 每日备份（SQLite Online Backup + workspace 打包）与 `restore.sh` 演练
- `/metrics` 与告警
- 镜像瘦身至 <400MB、CI 推送镜像到 registry

## 9. 本机部署链的当前状态（M0 记录）

M0 期间本机 Docker 守护进程未运行（`docker info` 连接 `dockerDesktopLinuxEngine` 失败）、也无可用 VPS/域名，因此：

- 已交付：`deploy/Dockerfile`、`deploy/entrypoint.sh`、`docker-compose.yml`、`deploy/Caddyfile`、本节部署手册
- 已验证：`docker compose config` 语法通过；服务以 `uvicorn` 本机直跑通过 `/healthz`、`/readyz`、404 错误信封与 JSON 日志验收
- **未验证**：真实镜像构建、容器非 root 运行、Caddy 自动 HTTPS、线上 `/healthz`

阻塞解除步骤：启动 Docker Desktop（或装 Docker Engine）→ `make up` → `curl http://127.0.0.1:8000/healthz`；有域名后按 §3–§5 完成线上验收。
