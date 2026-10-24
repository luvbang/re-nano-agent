#!/usr/bin/env bash
# 在线备份（M5 D2）：SQLite backup API（WAL 一致快照，服务运行中可用）
# + workspace 打包（含 .runs 工具结果落盘）+ 校验和 + 保留轮转。
#
# 用法（容器内或部署机）：
#   DATA_DIR=/data BACKUP_DIR=/var/backups/agentd [KEEP=7] bash deploy/backup.sh
# 定时（VPS cron，每天 03:30）：
#   30 3 * * * DATA_DIR=/data BACKUP_DIR=/var/backups/agentd bash /opt/re-nano-agent/deploy/backup.sh
# 异地：把 BACKUP_DIR 放到独立盘，或自备 rsync/rclone 同步到对象存储（见 docs/ops.md）。
set -euo pipefail

DATA_DIR="${DATA_DIR:?需要 DATA_DIR（含 agentd.db 与 workspace/）}"
BACKUP_DIR="${BACKUP_DIR:?需要 BACKUP_DIR}"
KEEP="${KEEP:-7}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_DIR/$STAMP"
mkdir -p "$DEST"

# 1) SQLite 在线备份（backup API，不锁写入方）
DB_PATH="${AGENTD_DB_PATH:-$DATA_DIR/agentd.db}"
PYTHON_BIN="${PYTHON_BIN:-python}"
DATA_DIR="$DB_PATH" BACKUP_DB="$DEST/agentd.db" "$PYTHON_BIN" - <<'PY'
import os
import sqlite3

src = sqlite3.connect(os.environ["DATA_DIR"])
dst = sqlite3.connect(os.environ["BACKUP_DB"])
with dst:
    src.backup(dst)
dst.close()
src.close()
PY

# 2) workspace 打包
if [ -d "$DATA_DIR/workspace" ]; then
    # cd 后用相对文件名：避免 Windows 盘符被 GNU tar 当作 host:file 远程语法
    (cd "$DEST" && tar -czf workspace.tar.gz -C "$DATA_DIR" workspace)
fi

# 3) 校验和
(
    cd "$DEST"
    sha256sum ./* > SHA256SUMS
)

# 4) 保留轮转（最新 KEEP 份）
if [ "$(ls -1d "$BACKUP_DIR"/*/ 2>/dev/null | wc -l)" -gt "$KEEP" ]; then
    ls -1d "$BACKUP_DIR"/*/ | sort | head -n -"$KEEP" | xargs -r rm -rf
fi

echo "backup ok: $DEST ($(du -sh "$DEST" | cut -f1))"
