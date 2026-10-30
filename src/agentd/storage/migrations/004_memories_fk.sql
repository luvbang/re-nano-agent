-- 004_memories_fk：修正 003 遗漏的 ON DELETE CASCADE（purge 被记忆外键挡住）。
--
-- 003_memories.sql 的 project_id 只写了 REFERENCES projects (id)，漏了 ON DELETE CASCADE。
-- 后果：项目一旦有记忆，`agentd purge --project <id>` 的 DELETE FROM projects 直接抛
-- FOREIGN KEY constraint failed（SQLite 的 FK 默认 RESTRICT）。其余 11 处 FK 都带
-- CASCADE/SET NULL，只有这一处漏了，属于实现与「级联」契约不符。
--
-- SQLite 不支持 ALTER TABLE 改外键，只能重建表：
--   CREATE memories_new（带上正确的 FK）→ 拷数据 → DROP 旧表 → RENAME。
-- 迁移执行器（db.py）把本文件包在 BEGIN ... COMMIT 里（executescript，显式事务），
-- 且连接上 PRAGMA foreign_keys=ON。重建期间：DROP TABLE memories 时若仍有子表引用它
-- 会失败——memories 没有任何子表（全仓只有它引用 projects），所以无需临时关 FK。
-- 索引跟着旧表一起被 DROP，必须在 RENAME 之后重建（见文件末尾）。

CREATE TABLE memories_new (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    source_session_id TEXT,
    source_run_id TEXT,
    score REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO memories_new (
    id, project_id, content, source_session_id, source_run_id,
    score, status, created_at, updated_at, last_seen_at
)
SELECT
    id, project_id, content, source_session_id, source_run_id,
    score, status, created_at, updated_at, last_seen_at
FROM memories;

DROP TABLE memories;

ALTER TABLE memories_new RENAME TO memories;

-- 重建 003 里的索引（原索引随旧表 DROP 一起消失）
CREATE INDEX idx_memories_project_active
    ON memories (project_id, status, score DESC, last_seen_at DESC);
