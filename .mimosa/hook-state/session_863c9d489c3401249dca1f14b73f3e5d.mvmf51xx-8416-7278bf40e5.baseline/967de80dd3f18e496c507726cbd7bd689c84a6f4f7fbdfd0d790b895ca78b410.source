#!/bin/sh
# 容器入口：先迁移（失败即退出，绝不带着旧 schema 起服务），再 exec 起 uvicorn。
# exec 保证 uvicorn 是 PID 1，能收到 SIGTERM 做优雅关闭。
set -eu

echo "agentd: applying migrations"
python -m agentd.cli migrate

echo "agentd: starting uvicorn on ${AGENTD_HOST:-0.0.0.0}:${AGENTD_PORT:-8000}"
exec uvicorn agentd.main:create_app \
    --factory \
    --host "${AGENTD_HOST:-0.0.0.0}" \
    --port "${AGENTD_PORT:-8000}" \
    --no-access-log \
    --timeout-graceful-shutdown 20
