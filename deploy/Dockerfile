# syntax=docker/dockerfile:1.7
# 多阶段 + 非 root。构建上下文 = 仓库根目录：
#   docker build -f deploy/Dockerfile -t agentd:dev .

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.11.16

# ---------- 构建阶段：只装依赖 + 项目本体，不带走构建工具 ----------
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-bin
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY --from=uv-bin /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python --no-cache .

# ---------- 运行阶段：非 root、只带 venv ----------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    AGENTD_ENV=prod \
    AGENTD_HOST=0.0.0.0 \
    AGENTD_PORT=8000 \
    AGENTD_DATA_DIR=/data

RUN groupadd --gid 10001 agentd \
    && useradd --uid 10001 --gid agentd --create-home --shell /usr/sbin/nologin agentd \
    && mkdir -p /data \
    && chown -R agentd:agentd /data

COPY --from=builder /opt/venv /opt/venv
COPY --chmod=0755 deploy/entrypoint.sh /usr/local/bin/entrypoint.sh

USER agentd
WORKDIR /home/agentd
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request;assert urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
