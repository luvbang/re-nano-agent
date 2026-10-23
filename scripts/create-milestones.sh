#!/usr/bin/env bash
# 为 M0–M8 创建 GitHub milestone 与 tracking issue。
# 前置：gh auth login；仓库已创建（默认当前仓库，可传 $1=owner/repo）。
set -euo pipefail

REPO="${1:-}"
GH=(gh)
[ -n "$REPO" ] && GH+=(--repo "$REPO")

milestones=(
  "M0 范围冻结+骨架+部署链"
  "M1 Provider+Runner+流式"
  "M2 持久化+上下文+真工具+安全"
  "M3 平台 API+鉴权+并发"
  "M4 SDK+计量+审计+压缩"
  "M5 部署硬化+运维+可观测"
  "M6 控制台(P1)+文档+RC"
  "M7 内测迭代+稳定性"
  "M8 上线+复盘"
)

for title in "${milestones[@]}"; do
  if "${GH[@]}" api "repos/${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}/milestones" >/dev/null 2>&1; then
    :
  fi
  echo "==> creating milestone: $title"
  "${GH[@]}" api --method POST \
    "repos/$( [ -n "$REPO" ] && echo "$REPO" || gh repo view --json nameWithOwner -q .nameWithOwner)/milestones" \
    -f "title=$title" >/dev/null || echo "   (已存在或失败，跳过)"
done

for title in "${milestones[@]}"; do
  echo "==> creating issue: $title"
  "${GH[@]}" issue create \
    --title "[$title] tracking" \
    --body "里程碑 tracking issue。验收标准见 docs/milestones.md 与 ROADMAP。" \
    --label "milestone" \
    --milestone "$title" >/dev/null || echo "   (跳过)"
done
