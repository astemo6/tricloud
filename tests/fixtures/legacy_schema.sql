-- 旧版 TriCloud（线上无 git 版本）app/db.py 的建表 SQL，原样复制，仅用于迁移脚本自测。
-- 下方 ALTER 来自旧版 init_db() 的老库升级语句（同样原样复制）。
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    name TEXT NOT NULL,
    creds_enc BLOB NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS account_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    amount REAL NOT NULL,
    expires_at REAL,
    created_at REAL NOT NULL
);CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    provider TEXT NOT NULL,
    account_id INTEGER,
    title TEXT NOT NULL,
    status TEXT NOT NULL,          -- queued|running|success|failed|stopped|interrupted
    log TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS traffic_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    instance_key TEXT NOT NULL,
    instance_name TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    metric TEXT NOT NULL DEFAULT 'out',
    window_hours INTEGER NOT NULL DEFAULT 24,
    limit_gb REAL NOT NULL,
    duration_hours INTEGER NOT NULL DEFAULT 24,
    enabled INTEGER NOT NULL DEFAULT 1,
    notify_trigger INTEGER NOT NULL DEFAULT 1,
    notify_recover INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'normal',
    triggered_at REAL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS recycle_bin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    name TEXT NOT NULL,
    est_cost_usd REAL DEFAULT 0,
    lifecycle_days REAL DEFAULT 0,
    deleted_at REAL NOT NULL
);CREATE TABLE IF NOT EXISTS billing_cache (
    account_id INTEGER PRIMARY KEY,
    data TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS dns_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    instance_id TEXT NOT NULL,
    zone_name TEXT NOT NULL,
    record_name TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ip_change_daily (
    account_id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,          -- YYYY-MM-DD，跨天计数自然清零
    count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    ip TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS login_attempts (
    ip TEXT PRIMARY KEY,
    fail_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,               -- ISO 时间，可空；过期自动解锁
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS script_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    os_type TEXT NOT NULL DEFAULT 'linux',   -- linux | windows
    content TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS instance_passwords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    instance_id TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    password_enc BLOB NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS password_vault (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    instance_name TEXT NOT NULL DEFAULT '',
    account_id INTEGER,
    password_enc BLOB NOT NULL,             -- Fernet 加密后的开机密码
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,        -- sha256 hex，绝不存明文
    scope TEXT NOT NULL DEFAULT 'readonly', -- readonly | full
    created_at REAL NOT NULL,
    last_used_at REAL
);
ALTER TABLE accounts ADD COLUMN monitor_alert INTEGER DEFAULT 0;
ALTER TABLE accounts ADD COLUMN monitor_restart INTEGER DEFAULT 0;
ALTER TABLE accounts ADD COLUMN credit_total REAL;
ALTER TABLE accounts ADD COLUMN cloud_created_at REAL;
ALTER TABLE accounts ADD COLUMN edu_expires_at REAL;
ALTER TABLE accounts ADD COLUMN monitor_ip_check INTEGER DEFAULT 0;
ALTER TABLE accounts ADD COLUMN auto_change_ip INTEGER DEFAULT 0;
ALTER TABLE accounts ADD COLUMN proxy_url TEXT DEFAULT '';
ALTER TABLE accounts ADD COLUMN proxy_user TEXT DEFAULT '';
ALTER TABLE accounts ADD COLUMN proxy_pass_enc BLOB;
ALTER TABLE account_credits ADD COLUMN start_at REAL;
ALTER TABLE account_credits ADD COLUMN ce_baseline REAL;
