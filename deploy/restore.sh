#!/usr/bin/env bash
# 恢复（M5 D2）：把一份 backup.sh 产物还原到 DATA_DIR。
#
# 用法（先停服务：docker compose stop app）：
#   DATA_DIR=/data BACKUP_DIR=/var/backups/agentd/20261024T033000Z bash deploy/restore.sh
# 然后启动服务：docker compose up -d（entrypoint 自动迁移补齐 schema）
set -euo pipefail

DATA_DIR="${DATA_DIR:?需要 DATA_DIR}"
BACKUP_DIR="${BACKUP_DIR:?需要 BACKUP_DIR（指到具体那一份备份目录）}"

[ -f "$BACKUP_DIR/agentd.db" ] || { echo "备份缺 agentd.db：$BACKUP_DIR" >&2; exit 1; }

# 校验和（有 sha256sum 且备份带 SHA256SUMS 时强校验）
if [ -f "$BACKUP_DIR/SHA256SUMS" ] && command -v sha256sum >/dev/null; then
    (cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS --quiet)
fi

mkdir -p "$DATA_DIR"
cp "$BACKUP_DIR/agentd.db" "$DATA_DIR/agentd.db"
if [ -f "$BACKUP_DIR/workspace.tar.gz" ]; then
    rm -rf "$DATA_DIR/workspace"
    # cd 后用相对文件名：避免 Windows 盘符被 GNU tar 当作 host:file 远程语法
    (cd "$BACKUP_DIR" && tar -xzf workspace.tar.gz -C "$DATA_DIR")
fi

echo "restored to $DATA_DIR from $BACKUP_DIR"
echo "下一步：docker compose up -d（启动时自动跑迁移）"
