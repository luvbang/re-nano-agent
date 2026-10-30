#!/usr/bin/env bash
# 全链路冒烟（M3 D5）：对着运行中的服务用 curl 走完 建项目→发 key→建会话→跑 run→SSE→用量。
# 用法：BASE_URL=http://127.0.0.1:8000 ADMIN_KEY=agd_xxx bash scripts/smoke.sh
# 依赖：curl、python（用于解析 JSON，避免 jq）。
# 注意：本脚本的 ADMIN_KEY 是「传进脚本」的变量名（可自定义），
# 服务端读的是 AGENTD_ADMIN_API_KEY（config.py: admin_api_key + AGENTD_ 前缀），
# 两者名字不同别搞混——服务端设错名字会读不到值。
set -euo pipefail

BASE="${BASE_URL:-http://127.0.0.1:8000}"
ADMIN="${ADMIN_KEY:?请通过环境变量提供 ADMIN_KEY（服务端的 AGENTD_ADMIN_API_KEY）}"
AUTH="Authorization: Bearer ${ADMIN}"

jsonget() { python -c "import json,sys;print(json.load(sys.stdin)[sys.argv[1]])" "$1"; }

echo "[1/7] healthz"
curl -fsS "${BASE}/healthz" | python -m json.tool

echo "[2/7] 创建 project"
PROJECT=$(curl -fsS -X POST "${BASE}/v1/admin/projects" -H "${AUTH}" \
  -H 'Content-Type: application/json' -d "{\"name\":\"smoke-$(date +%s)\"}")
PID=$(echo "$PROJECT" | jsonget id)
echo "  project=${PID}"

echo "[3/7] 创建 API key（明文仅此一次）"
KEY=$(curl -fsS -X POST "${BASE}/v1/admin/keys" -H "${AUTH}" \
  -H 'Content-Type: application/json' -d "{\"project_id\":\"${PID}\"}" | jsonget key)
KEYAUTH="Authorization: Bearer ${KEY}"

echo "[4/7] 创建 session"
SID=$(curl -fsS -X POST "${BASE}/v1/sessions" -H "${KEYAUTH}" \
  -H 'Content-Type: application/json' -d '{"title":"smoke"}' | jsonget id)
echo "  session=${SID}"

echo "[5/7] 创建 run"
RID=$(curl -fsS -X POST "${BASE}/v1/sessions/${SID}/runs" -H "${KEYAUTH}" \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: smoke-1' \
  -d '{"input":"用一句话介绍你自己"}' | jsonget run_id)
echo "  run=${RID}"

echo "[6/7] SSE 事件流（最多等 60s）"
curl -fsS -N --max-time 60 "${BASE}/v1/runs/${RID}/events" -H "${KEYAUTH}" | tee /tmp/agentd-smoke-sse.txt | grep -E '^event: (run.completed|run.failed)' || {
  echo "!! 未收到终态事件"; exit 1
}

echo "[7/7] run 详情与用量"
curl -fsS "${BASE}/v1/runs/${RID}" -H "${KEYAUTH}" | python -m json.tool
curl -fsS "${BASE}/v1/usage" -H "${KEYAUTH}" | python -m json.tool

echo "SMOKE OK"
