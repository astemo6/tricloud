"""SQLite 持久层：账号（凭证加密存储）、任务、会话、元信息。"""
import json
import os
import secrets
import sqlite3
import threading
import time

from . import config
from .crypto import encrypt_secret, decrypt_secret

_lock = threading.RLock()
_DB_PATH = os.path.join(config.DATA_DIR, "tricloud.db")

SCHEMA = """
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
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)
        # 迁移：账号表加监控开关字段（老库升级）
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
        if "monitor_alert" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN monitor_alert INTEGER DEFAULT 0")
        if "monitor_restart" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN monitor_restart INTEGER DEFAULT 0")
        if "credit_total" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN credit_total REAL")
        if "cloud_created_at" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN cloud_created_at REAL")
        # account_credits 表老库升级：加 start_at（credit 生效日期）
        ccols = {r["name"] for r in conn.execute("PRAGMA table_info(account_credits)")}
        if "start_at" not in ccols:
            conn.execute("ALTER TABLE account_credits ADD COLUMN start_at REAL")
        if "ce_baseline" not in ccols:
            conn.execute("ALTER TABLE account_credits ADD COLUMN ce_baseline REAL")
    # 启动时把上次异常中断的任务标记出来
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status='interrupted', finished_at=? "
            "WHERE status IN ('queued','running')",
            (time.time(),),
        )


# ---------- meta ----------
def meta_get(key: str) -> str | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def meta_set(key: str, value: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))


# ---------- accounts ----------
def account_list(provider: str | None = None) -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, provider, name, created_at, credit_total, cloud_created_at FROM accounts"
            + (" WHERE provider=?" if provider else "")
            + " ORDER BY id",
            (provider,) if provider else (),
        ).fetchall()
        return [dict(r) for r in rows]


def account_get(account_id: int) -> dict | None:
    """返回账号，含解密后的 creds。"""
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["creds"] = json.loads(decrypt_secret(d.pop("creds_enc")))
        return d


def account_create(provider: str, name: str, creds: dict) -> int:
    now = time.time()
    blob = encrypt_secret(json.dumps(creds))
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO accounts(provider, name, creds_enc, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (provider, name, blob, now, now),
        )
        return cur.lastrowid


def account_update(account_id: int, name: str, creds: dict | None) -> bool:
    with _lock, _connect() as conn:
        if creds is None:
            cur = conn.execute(
                "UPDATE accounts SET name=?, updated_at=? WHERE id=?",
                (name, time.time(), account_id),
            )
        else:
            blob = encrypt_secret(json.dumps(creds))
            cur = conn.execute(
                "UPDATE accounts SET name=?, creds_enc=?, updated_at=? WHERE id=?",
                (name, blob, time.time(), account_id),
            )
        return cur.rowcount > 0


def account_set_credit_total(account_id: int, total: float | None) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE accounts SET credit_total=?, updated_at=? WHERE id=?",
            (total, time.time(), account_id),
        )
        return cur.rowcount > 0


def account_set_cloud_created_at(account_id: int, ts: float | None) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE accounts SET cloud_created_at=?, updated_at=? WHERE id=?",
            (ts, time.time(), account_id),
        )
        return cur.rowcount > 0


# ---------- 手动维护的 credit ----------

def credit_list(account_id: int) -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, amount, expires_at, start_at, ce_baseline FROM account_credits"
            " WHERE account_id=? ORDER BY expires_at IS NULL, expires_at",
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def credit_add(account_id: int, name: str, amount: float,
               expires_at: float | None, start_at: float | None = None,
               ce_baseline: float = 0.0) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO account_credits(account_id, name, amount, expires_at, start_at, ce_baseline, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (account_id, name, amount, expires_at, start_at, ce_baseline, time.time()),
        )
        return cur.lastrowid


def credit_delete(credit_id: int, account_id: int) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM account_credits WHERE id=? AND account_id=?",
            (credit_id, account_id),
        )
        return cur.rowcount > 0


def credit_update(credit_id: int, account_id: int, fields: dict) -> bool:
    allowed = {"name", "amount", "expires_at", "start_at", "ce_baseline"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return False
    with _lock, _connect() as conn:
        cur = conn.execute(
            f"UPDATE account_credits SET {', '.join(sets)} WHERE id=? AND account_id=?",
            (*vals, credit_id, account_id))
        return cur.rowcount > 0


def credit_get(credit_id: int, account_id: int) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM account_credits WHERE id=? AND account_id=?",
            (credit_id, account_id)).fetchone()
        return dict(row) if row else None


def account_delete(account_id: int) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        return cur.rowcount > 0


# ---------- 流量控制规则 ----------

def traffic_rule_list(account_id: int | None = None) -> list[dict]:
    with _lock, _connect() as conn:
        if account_id:
            rows = conn.execute(
                "SELECT * FROM traffic_rules WHERE account_id=? ORDER BY id DESC",
                (account_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM traffic_rules ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def traffic_rule_add(rule: dict) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO traffic_rules(account_id, instance_key, instance_name, name,"
            " metric, window_hours, limit_gb, duration_hours, enabled,"
            " notify_trigger, notify_recover, state, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,'normal',?)",
            (rule["account_id"], rule["instance_key"], rule.get("instance_name", ""),
             rule["name"], rule.get("metric", "out"), rule.get("window_hours", 24),
             rule["limit_gb"], rule.get("duration_hours", 24),
             1 if rule.get("enabled", True) else 0,
             1 if rule.get("notify_trigger", True) else 0,
             1 if rule.get("notify_recover", True) else 0,
             time.time()),
        )
        return cur.lastrowid


def traffic_rule_update(rule_id: int, fields: dict) -> bool:
    allowed = {"name", "metric", "window_hours", "limit_gb", "duration_hours",
               "enabled", "notify_trigger", "notify_recover", "state", "triggered_at"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return False
    with _lock, _connect() as conn:
        cur = conn.execute(
            f"UPDATE traffic_rules SET {', '.join(sets)} WHERE id=?",
            (*vals, rule_id))
        return cur.rowcount > 0


def traffic_rule_delete(rule_id: int) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM traffic_rules WHERE id=?", (rule_id,))
        return cur.rowcount > 0


def traffic_rule_enabled() -> list[dict]:
    """列出所有启用的规则（含账号凭证，供后台巡检）。"""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT r.*, a.provider, a.creds_enc, a.name as account_name"
            " FROM traffic_rules r JOIN accounts a ON r.account_id=a.id"
            " WHERE r.enabled=1").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            from .crypto import decrypt
            d["creds"] = decrypt(d.pop("creds_enc"))
            out.append(d)
        return out


# ---------- 回收站 ----------

def recycle_add(provider: str, name: str, est_cost_usd: float = 0,
                lifecycle_days: float = 0) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO recycle_bin(provider, name, est_cost_usd, lifecycle_days, deleted_at)"
            " VALUES (?,?,?,?,?)",
            (provider, name, est_cost_usd, lifecycle_days, time.time()))
        return cur.lastrowid


def recycle_list() -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM recycle_bin ORDER BY deleted_at DESC").fetchall()
        return [dict(r) for r in rows]


def recycle_stats() -> dict:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c, MAX(lifecycle_days) max_days,"
            " MAX(est_cost_usd) max_cost FROM recycle_bin").fetchone()
        return {"count": row["c"] or 0,
                "max_lifecycle_days": row["max_days"] or 0,
                "max_cost_usd": row["max_cost"] or 0}


def account_list_monitored() -> list[dict]:
    """列出开启了监控告警或自动重启的账号（含解密凭证）。"""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE monitor_alert=1 OR monitor_restart=1"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["creds"] = json.loads(decrypt_secret(d.pop("creds_enc")))
            out.append(d)
        return out


def account_set_monitor(account_id: int, alert: bool, restart: bool) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE accounts SET monitor_alert=?, monitor_restart=?, updated_at=? WHERE id=?",
            (1 if alert else 0, 1 if restart else 0, time.time(), account_id),
        )


# ---------- sessions ----------
def session_create(ttl: int) -> str:
    token = secrets.token_hex(32)
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO sessions(token, created_at, expires_at) VALUES (?,?,?)",
            (token, now, now + ttl),
        )
    return token


def session_valid(token: str | None) -> bool:
    if not token:
        return False
    now = time.time()
    with _lock, _connect() as conn:
        row = conn.execute("SELECT expires_at FROM sessions WHERE token=?", (token,)).fetchone()
        if not row:
            return False
        if row["expires_at"] < now:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            return False
        # 滑动过期
        conn.execute(
            "UPDATE sessions SET expires_at=? WHERE token=?",
            (now + config.SESSION_TTL_SECONDS, token),
        )
        return True


def session_delete(token: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))


def session_cleanup() -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))


# ---------- jobs ----------
def job_create(job_id: str, job_type: str, provider: str, account_id: int | None, title: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO jobs(id, type, provider, account_id, title, status, created_at)"
            " VALUES (?,?,?,?,?,'queued',?)",
            (job_id, job_type, provider, account_id, title, time.time()),
        )


def job_get(job_id: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def job_list(limit: int = 100) -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def job_update(job_id: str, **fields) -> None:
    if not fields:
        return
    keys = ", ".join(f"{k}=?" for k in fields)
    with _lock, _connect() as conn:
        conn.execute(f"UPDATE jobs SET {keys} WHERE id=?", (*fields.values(), job_id))


def job_append_log(job_id: str, message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}\n"
    with _lock, _connect() as conn:
        conn.execute("UPDATE jobs SET log = log || ? WHERE id=?", (line, job_id))


def job_delete(job_id: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM jobs WHERE id=? AND status NOT IN ('queued','running')", (job_id,)
        )
        return cur.rowcount > 0
