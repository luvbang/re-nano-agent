-- 003_memories：长期记忆（v0.2-3 记忆与自动整理）
-- 作用域 = project（与 sessions/runs 一致的隔离边界）。
-- status: active（注入上下文）/ archived（Dream 或手动归档，不再注入）。
-- last_seen_at：注入/再次确认时刷新，Dream 据此判定陈旧。

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
