#!/usr/bin/env bash
# API 契约冒烟测试：验证鉴权 / 资源不存在 / request_id 一致性 / 安全基线。
#
# 用法：
#   BASE=http://127.0.0.1:8199 ADMIN=test-admin-key bash scripts/api_smoke_test.sh
#
# 前置：服务已启动（scripts/serve_fake.py），且 ADMIN 与服务端 AGENTD_ADMIN_API_KEY 一致。
# 退出码：0 = 全通过，1 = 有失败项（可直接用于 CI）。
set -uo pipefail

BASE=${BASE:-http://127.0.0.1:8000}
ADMIN=${ADMIN:?需要管理员 key（与服务端 AGENTD_ADMIN_API_KEY 一致）}

# JSON 解析用哪个 python：优先仓库 venv（Windows 下 .venv/Scripts/python.exe）
if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"; else PY=python; fi

PASS=0
FAIL=0
ok() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
no() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }
chk() { if [ "$2" = "$3" ]; then ok "$1"; else no "$1 (期望 $3, 实际 $2)"; fi; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

echo "== 健康检查 =="
chk "healthz 200" "$(code "$BASE/healthz")" 200
chk "readyz 200" "$(code "$BASE/readyz")" 200
chk "openapi 200" "$(code "$BASE/openapi.json")" 200

echo "== 鉴权 =="
chk "无 token -> 401" "$(code "$BASE/v1/sessions")" 401
chk "错误 token -> 401" "$(code -H 'Authorization: Bearer agd_wrong' "$BASE/v1/sessions")" 401
chk "管理员 key 跑业务 -> 401" "$(code -H "Authorization: Bearer $ADMIN" "$BASE/v1/sessions")" 401

echo "== 管理端点（管理员应可用）=="
chk "admin projects 200" "$(code -H "Authorization: Bearer $ADMIN" "$BASE/v1/admin/projects")" 200
chk "admin stats 200" "$(code -H "Authorization: Bearer $ADMIN" "$BASE/v1/admin/stats")" 200
chk "metrics 200" "$(code -H "Authorization: Bearer $ADMIN" "$BASE/metrics")" 200

echo "== 建项目 key（业务端点需要项目 key，管理员 key 不行）=="
PROJ_ID=$(curl -s -X POST "$BASE/v1/admin/projects" \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d "{\"name\":\"smoke-$$\"}" \
  | $PY -c "import json,sys;print(json.load(sys.stdin, ).get('id',''))" 2>/dev/null)
PROJ_KEY=$(curl -s -X POST "$BASE/v1/admin/keys" \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PROJ_ID\"}" \
  | $PY -c "import json,sys;print(json.load(sys.stdin).get('key',''))" 2>/dev/null)
chk "建项目成功" "$([ -n "$PROJ_ID" ] && echo yes || echo no)" "yes"
chk "建 key 成功" "$([ -n "$PROJ_KEY" ] && echo yes || echo no)" "yes"

echo "== 资源不存在 -> 404 而非 500 =="
chk "不存在 session 404" \
  "$(code -H "Authorization: Bearer $PROJ_KEY" "$BASE/v1/sessions/s_nope")" 404

echo "== request_id 一致性（契约第 4 节）=="
# 用脚本同目录的相对路径做临时文件：MSYS 的 /tmp 与原生 Windows python 不互通
TMP=".api_smoke_body.$$"
HDR=$(curl -s -D - -o "$TMP" -H "Authorization: Bearer $PROJ_KEY" "$BASE/v1/sessions/s_nope" \
  | grep -i '^x-request-id:' | tr -d '\r' | awk '{print $2}')
BODY=$($PY -c "import json;print(json.load(open('$TMP',encoding='utf-8'))['error']['request_id'])" 2>/dev/null)
chk "body.request_id == X-Request-Id" "$BODY" "$HDR"
chk "request_id 非空" "$([ -n "$BODY" ] && echo yes || echo no)" "yes"
rm -f "$TMP"

echo
echo "通过 $PASS / 失败 $FAIL"
[ "$FAIL" -eq 0 ]
