# 多阶段 + 非 root。构建上下文 = 仓库根目录：
#   docker build -f deploy/Dockerfile -t agentd:dev .
#
# 网络受限（Docker Hub 直连不通）时用 build-arg 换基础镜像/索引源，无需改 daemon.json：
#   docker build -f deploy/Dockerfile -t agentd:dev \
#     --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim-bookworm \
#     --build-arg UV_IMAGE=ghcr.m.daocloud.io/astral-sh/uv:0.11.16 \
#     --build-arg UV_INDEX_URL=https://pypi.org/simple .

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.16
# 注意：用于 FROM 的 ARG 必须声明在第一个 FROM 之前（全局作用域）；
# 夹在两个 stage 之间的 ARG 在 buildx 下解析为空（base name should not be blank）
ARG NODE_IMAGE=node:22-alpine

# ---------- 构建阶段：只装依赖 + 项目本体，不带走构建工具 ----------
FROM ${UV_IMAGE} AS uv-bin

FROM ${PYTHON_IMAGE} AS builder

COPY --from=uv-bin /uv /usr/local/bin/uv
ARG UV_INDEX_URL=https://pypi.org/simple
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_INDEX_URL=${UV_INDEX_URL}

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python --no-cache .

# ---------- 控制台阶段：构建 web/dist（网络受限时用 NPM_REGISTRY 换源） ----------
FROM ${NODE_IMAGE} AS console
ARG NPM_REGISTRY=https://registry.npmjs.org/
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm config set registry ${NPM_REGISTRY} && npm ci --no-audit --no-fund
COPY web ./
RUN npm run build

# ---------- 运行阶段：非 root、只带 venv ----------
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    AGENTD_ENV=prod \
    AGENTD_STATIC_DIR=/home/agentd/web/dist \
    AGENTD_HOST=0.0.0.0 \
    AGENTD_PORT=8000 \
    AGENTD_DATA_DIR=/data

RUN groupadd --gid 10001 agentd \
    && useradd --uid 10001 --gid agentd --create-home --shell /usr/sbin/nologin agentd \
    && mkdir -p /data \
    && chown -R agentd:agentd /data

COPY --from=builder /opt/venv /opt/venv
COPY --from=console /web/dist /home/agentd/web/dist
COPY --chmod=0755 deploy/entrypoint.sh /usr/local/bin/entrypoint.sh

USER agentd
WORKDIR /home/agentd
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request;assert urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
