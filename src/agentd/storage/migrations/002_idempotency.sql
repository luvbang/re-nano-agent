-- schema 002：run 幂等键（M3 D2）。同 key 5 分钟内返回同一 run。
CREATE TABLE idempotency_keys (
    key        TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_idempotency_created ON idempotency_keys (created_at);
