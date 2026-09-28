-- Portable SQL (runs on PostgreSQL and SQLite). Timestamps are ISO-8601 UTC strings.
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE api_keys (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX idx_api_keys_user ON api_keys(user_id);

CREATE TABLE widgets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES users(id),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    button_text TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    options_json TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_widgets_tenant ON widgets(tenant_id);

CREATE TABLE submissions (
    id TEXT PRIMARY KEY,
    widget_id TEXT NOT NULL REFERENCES widgets(id),
    tenant_id TEXT NOT NULL,
    data_json TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT,
    origin TEXT,
    geo_country TEXT,
    geo_country_code TEXT,
    geo_region TEXT,
    geo_city TEXT,
    geo_provider TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL,
    created_date TEXT NOT NULL
);
CREATE INDEX idx_submissions_tenant_created ON submissions(tenant_id, created_at);
CREATE INDEX idx_submissions_widget_created ON submissions(widget_id, created_at);
CREATE INDEX idx_submissions_tenant_date ON submissions(tenant_id, created_date);
CREATE UNIQUE INDEX uq_submissions_idem ON submissions(widget_id, idempotency_key);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    next_run_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_jobs_due ON jobs(status, next_run_at);
