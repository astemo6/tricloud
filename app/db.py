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
CREATE TABLE IF NOT EXISTS jobs (
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
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)
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
            "SELECT id, provider, name, created_at FROM accounts"
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


def account_delete(account_id: int) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        return cur.rowcount > 0


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
