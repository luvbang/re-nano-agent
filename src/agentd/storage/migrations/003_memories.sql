-- 003_memories：长期记忆（v0.2-3 记忆与自动整理）
-- 作用域 = project（与 sessions/runs 一致的隔离边界）。
-- status: active（注入上下文）/ archived（Dream 或手动归档，不再注入）。
-- last_seen_at：注入/再次确认时刷新，Dream 据此判定陈旧。
--
-- 注意：本文件的 project_id 外键漏了 ON DELETE CASCADE（项目一有记忆，purge 的
-- DELETE FROM projects 就会被 FK 挡住），已由 004_memories_fk 重建表修正。
-- 保留原文是为了迁移可重放、不扰动既有库的 schema_version 序列；
-- 新库按序执行 003 → 004 后即得到正确 schema。

CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects (id),
    content TEXT NOT NULL,
    source_session_id TEXT,
    source_run_id TEXT,
    score REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_memories_project_active
    ON memories (project_id, status, score DESC, last_seen_at DESC);
