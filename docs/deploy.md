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

## 7. 网络受限时用镜像源构建（无需改 daemon.json）

Docker Hub / ghcr.io 直连不通（或很慢）时，在 `.env` 里加：

```ini
PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim-bookworm
UV_IMAGE=ghcr.m.daocloud.io/astral-sh/uv:0.11.16
CADDY_IMAGE=docker.m.daocloud.io/library/caddy:2-alpine
UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```

`docker compose up -d --build` 会自动把这些值作为 build args 传进去。直接 `docker build` 时用：

```bash
docker build -f deploy/Dockerfile -t agentd:dev \
  --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim-bookworm \
  --build-arg UV_IMAGE=ghcr.m.daocloud.io/astral-sh/uv:0.11.16 \
  --build-arg UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .
```

本地端口被占用时：`HTTP_PORT=18080 HTTPS_PORT=18443`（`AGENTD_DOMAIN=localhost` 时 Caddy 走内部 CA，自签证书，`curl -k` 访问）。

## 8. 已在 M0 验证过的东西（可复现）

```bash
docker build -f deploy/Dockerfile -t agentd:m0 --build-arg ... .   # 成功，镜像 246MB
docker run -d --name agentd-m0 -p 8124:8000 agentd:m0
curl -s http://127.0.0.1:8124/healthz        # {"status":"ok",...}
curl -s http://127.0.0.1:8124/readyz         # {"status":"ready","checks":{"db":"ok"}}
docker exec agentd-m0 id                     # uid=10001(agentd) 非 root
docker exec agentd-m0 ls /data               # agentd.db + workspace（迁移已应用）
docker stop agentd-m0                        # 日志出现 app.stopped（优雅关闭）
docker start agentd-m0                       # 重启后 readyz 仍 ok，数据未丢
docker compose up -d --build                 # app healthy → caddy 启动
curl -sk https://localhost:18443/healthz      # 经 Caddy 的 HTTPS 200，带安全响应头
```

## 9. 待补齐（M5）

- 每日备份（SQLite Online Backup + workspace 打包）与 `restore.sh` 演练
- `/metrics` 与告警
- CI 推送镜像到 registry 并支持 `AGENTD_IMAGE_TAG` 回滚

## 10. 尚未验收：真实 VPS 与域名

M0 期间没有可用 VPS/域名，因此以下两项目前**只有本地等价验证，没有线上证据**：

- 线上 `https://<domain>/healthz`（本地已验证 Caddy HTTPS + 自签证书路径）
- 「全新 VPS 30 分钟内从零部署」的实际耗时

解除方式：拿到 VPS + 域名后按 §1–§5 执行一遍，记录实际耗时写回本节。

