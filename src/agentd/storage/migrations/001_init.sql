-- schema v1：项目 / 密钥 / 会话 / 消息 / run / 事件 / 工具调用 / 用量 / 审计
-- 时间戳统一 ISO-8601 UTC 字符串，便于直接读库与跨语言处理。

CREATE TABLE projects (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    workspace_path TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE api_keys (
    id                 TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    key_hash           TEXT NOT NULL UNIQUE,          -- sha256(key)，明文永不落库
    key_prefix         TEXT NOT NULL,                 -- 前 8 位，仅用于展示
    name               TEXT,
    scopes             TEXT NOT NULL DEFAULT 'core',  -- 逗号分隔 scope
    rate_limit_per_min INTEGER NOT NULL DEFAULT 60,
    revoked_at         TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_api_keys_project ON api_keys (project_id);

CREATE TABLE sessions (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    external_user_id TEXT,
    title            TEXT,
    metadata_json    TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_sessions_project ON sessions (project_id, created_at DESC);

CREATE TABLE messages (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool', 'summary')),
    content_json    TEXT,                              -- 结构化内容（文本/多模态块）
    tool_calls_json TEXT,
    tool_call_id    TEXT,
    meta_json       TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (session_id, seq)
);

CREATE INDEX idx_messages_session ON messages (session_id, seq);

CREATE TABLE runs (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    project_id    TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    status        TEXT NOT NULL CHECK (
                      status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'interrupted')
                  ),
    model         TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    error_json    TEXT,
    started_at    TEXT,
    finished_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_runs_session ON runs (session_id, created_at DESC);
CREATE INDEX idx_runs_project ON runs (project_id, created_at DESC);
CREATE INDEX idx_runs_status ON runs (status);

-- 仅控制类事件（run.started / tool.* / message.completed / run.*），delta 不入库用于回放
CREATE TABLE run_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    type         TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (run_id, seq)
);

CREATE INDEX idx_run_events_run ON run_events (run_id, seq);

CREATE TABLE tool_calls (
    id             TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    tool_call_id   TEXT NOT NULL,
    name           TEXT NOT NULL,
    args_json      TEXT NOT NULL DEFAULT '{}',
    result_preview TEXT,
    status         TEXT NOT NULL CHECK (status IN ('ok', 'error', 'timeout')),
    duration_ms    INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_tool_calls_run ON tool_calls (run_id);

CREATE TABLE usage_records (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    run_id        TEXT REFERENCES runs (id) ON DELETE SET NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_usage_project_created ON usage_records (project_id, created_at);

CREATE TABLE audit_logs (
    id          TEXT PRIMARY KEY,
    project_id  TEXT REFERENCES projects (id) ON DELETE SET NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    ip          TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_audit_project_created ON audit_logs (project_id, created_at);
