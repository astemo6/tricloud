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
        if "edu_expires_at" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN edu_expires_at REAL")
        if "monitor_ip_check" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN monitor_ip_check INTEGER DEFAULT 0")
        if "auto_change_ip" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN auto_change_ip INTEGER DEFAULT 0")
        # 迁移：账号表加代理出口配置（老库升级）
        if "proxy_url" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN proxy_url TEXT DEFAULT ''")
        if "proxy_user" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN proxy_user TEXT DEFAULT ''")
        if "proxy_pass_enc" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN proxy_pass_enc BLOB")
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
# ---------- 账号级代理出口 ----------
# 代理配置独立存列（proxy_pass_enc 用 Fernet 加密），不混入 creds 加密块；
# 读取账号时由 _merge_proxy 注入 creds，供 provider 创建客户端使用。
_PROXY_CREDS_KEYS = ("proxy_url", "proxy_user", "proxy_pass")


def _norm_proxy(proxy: dict | None) -> dict:
    """归一化代理配置：{"proxy_url", "proxy_user", "proxy_pass_enc"}。"""
    p = proxy or {}
    url = (p.get("proxy_url") or "").strip()
    if not url:
        return {"proxy_url": "", "proxy_user": "", "proxy_pass_enc": None}
    pwd = p.get("proxy_pass") or ""
    return {
        "proxy_url": url,
        "proxy_user": (p.get("proxy_user") or "").strip(),
        "proxy_pass_enc": encrypt_secret(pwd) if pwd else None,
    }


def _merge_proxy(acc: dict) -> None:
    """把账号的代理配置注入 creds（仅当配置了代理；未配置时 creds 原样返回）。"""
    url = (acc.get("proxy_url") or "").strip()
    creds = acc.get("creds")
    if not url or not isinstance(creds, dict):
        return
    creds["proxy_url"] = url
    if acc.get("proxy_user"):
        creds["proxy_user"] = acc["proxy_user"]
    if acc.get("proxy_pass_enc"):
        try:
            creds["proxy_pass"] = decrypt_secret(acc["proxy_pass_enc"])
        except Exception:  # noqa: BLE001 - 解密失败按无密码处理
            pass


def account_list(provider: str | None = None) -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, provider, name, created_at, credit_total, cloud_created_at,"
            " edu_expires_at, proxy_url, proxy_user FROM accounts"
            + (" WHERE provider=?" if provider else "")
            + " ORDER BY id",
            (provider,) if provider else (),
        ).fetchall()
        return [dict(r) for r in rows]


def account_get(account_id: int) -> dict | None:
    """返回账号，含解密后的 creds（及注入的代理配置）。"""
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["creds"] = json.loads(decrypt_secret(d.pop("creds_enc")))
        _merge_proxy(d)
        return d


def account_create(provider: str, name: str, creds: dict,
                   proxy: dict | None = None) -> int:
    now = time.time()
    blob = encrypt_secret(json.dumps(creds))
    p = _norm_proxy(proxy)
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO accounts(provider, name, creds_enc, proxy_url, proxy_user,"
            " proxy_pass_enc, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (provider, name, blob, p["proxy_url"], p["proxy_user"],
             p["proxy_pass_enc"], now, now),
        )
        return cur.lastrowid


def account_update(account_id: int, name: str, creds: dict | None = None,
                   proxy: dict | None = None) -> bool:
    """更新账号。creds 为 None 时不改凭证；proxy 为 None 时不改代理配置
    （传空 dict {"proxy_url": ""} 表示清除代理）。"""
    sets = ["name=?", "updated_at=?"]
    vals: list = [name, time.time()]
    if creds is not None:
        # 代理配置独立存列，防止混入 creds 加密块
        clean = {k: v for k, v in creds.items()
                 if k not in _PROXY_CREDS_KEYS}
        sets.append("creds_enc=?")
        vals.append(encrypt_secret(json.dumps(clean)))
    if proxy is not None:
        p = _norm_proxy(proxy)
        sets += ["proxy_url=?", "proxy_user=?", "proxy_pass_enc=?"]
        vals += [p["proxy_url"], p["proxy_user"], p["proxy_pass_enc"]]
    with _lock, _connect() as conn:
        cur = conn.execute(
            f"UPDATE accounts SET {', '.join(sets)} WHERE id=?",
            (*vals, account_id),
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


def account_set_edu_expires_at(account_id: int, ts: float | None) -> bool:
    """设置 Azure 教育优惠到期日（unix 时间戳，传 None 清除）。"""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE accounts SET edu_expires_at=?, updated_at=? WHERE id=?",
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
            "SELECT r.*, a.provider, a.creds_enc, a.name as account_name,"
            " a.proxy_url, a.proxy_user, a.proxy_pass_enc"
            " FROM traffic_rules r JOIN accounts a ON r.account_id=a.id"
            " WHERE r.enabled=1").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            from .crypto import decrypt
            d["creds"] = json.loads(decrypt(d.pop("creds_enc")))
            _merge_proxy(d)
            out.append(d)
        return out


# ---------- Cloudflare DNS 映射 ----------

def dns_mapping_list(account_id: int | None = None) -> list[dict]:
    with _lock, _connect() as conn:
        if account_id:
            rows = conn.execute(
                "SELECT * FROM dns_mappings WHERE account_id=? ORDER BY id DESC",
                (account_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dns_mappings ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def dns_mapping_get(mapping_id: int, account_id: int | None = None) -> dict | None:
    with _lock, _connect() as conn:
        if account_id:
            row = conn.execute(
                "SELECT * FROM dns_mappings WHERE id=? AND account_id=?",
                (mapping_id, account_id)).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM dns_mappings WHERE id=?", (mapping_id,)).fetchone()
        return dict(row) if row else None


def dns_mapping_add(account_id: int, instance_id: str,
                    zone_name: str, record_name: str) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO dns_mappings(account_id, instance_id, zone_name,"
            " record_name, created_at) VALUES (?,?,?,?,?)",
            (account_id, instance_id, zone_name, record_name, time.time()))
        return cur.lastrowid


def dns_mapping_update(mapping_id: int, account_id: int | None,
                       fields: dict) -> bool:
    allowed = {"instance_id", "zone_name", "record_name"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return False
    with _lock, _connect() as conn:
        if account_id:
            cur = conn.execute(
                f"UPDATE dns_mappings SET {', '.join(sets)}"
                " WHERE id=? AND account_id=?",
                (*vals, mapping_id, account_id))
        else:
            cur = conn.execute(
                f"UPDATE dns_mappings SET {', '.join(sets)} WHERE id=?",
                (*vals, mapping_id))
        return cur.rowcount > 0


def dns_mapping_delete(mapping_id: int, account_id: int | None = None) -> bool:
    with _lock, _connect() as conn:
        if account_id:
            cur = conn.execute(
                "DELETE FROM dns_mappings WHERE id=? AND account_id=?",
                (mapping_id, account_id))
        else:
            cur = conn.execute(
                "DELETE FROM dns_mappings WHERE id=?", (mapping_id,))
        return cur.rowcount > 0


def dns_mapping_delete_by_account(account_id: int) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM dns_mappings WHERE account_id=?", (account_id,))


def dns_mappings_for_instance(account_id: int | None, instance_id: str) -> list[dict]:
    """按实例查 DNS 映射（换 IP 联动用）。"""
    with _lock, _connect() as conn:
        if account_id:
            rows = conn.execute(
                "SELECT * FROM dns_mappings WHERE account_id=? AND instance_id=?",
                (account_id, instance_id)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dns_mappings WHERE instance_id=?",
                (instance_id,)).fetchall()
        return [dict(r) for r in rows]


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
            _merge_proxy(d)
            out.append(d)
        return out


def account_set_monitor(account_id: int, alert: bool, restart: bool) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE accounts SET monitor_alert=?, monitor_restart=?, updated_at=? WHERE id=?",
            (1 if alert else 0, 1 if restart else 0, time.time(), account_id),
        )


# ---------- IP 连通性检测 / 不通自动换 IP ----------
AUTO_CHANGE_IP_DAILY_LIMIT = 3  # 每个账号每天最多自动换 IP 次数


def account_set_ip_check(account_id: int, ip_check: bool,
                         auto_change: bool) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE accounts SET monitor_ip_check=?, auto_change_ip=?,"
            " updated_at=? WHERE id=?",
            (1 if ip_check else 0, 1 if auto_change else 0,
             time.time(), account_id),
        )


def account_list_ip_checked() -> list[dict]:
    """列出开启了 IP 连通性检测的账号（含解密凭证）。"""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE monitor_ip_check=1").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["creds"] = json.loads(decrypt_secret(d.pop("creds_enc")))
            _merge_proxy(d)
            out.append(d)
        return out


def ip_change_daily_count(account_id: int, day: str) -> int:
    """当日自动换 IP 次数（day 为 YYYY-MM-DD）。"""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT count FROM ip_change_daily WHERE account_id=? AND day=?",
            (account_id, day)).fetchone()
        return int(row["count"]) if row else 0


def ip_change_daily_inc(account_id: int, day: str) -> int:
    """当日计数 +1 并返回自增后的值；day 变化（跨天）时自动清零。"""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT day, count FROM ip_change_daily WHERE account_id=?",
            (account_id,)).fetchone()
        if row and row["day"] == day:
            new = int(row["count"]) + 1
            conn.execute(
                "UPDATE ip_change_daily SET count=? WHERE account_id=?",
                (new, account_id))
        else:
            new = 1
            conn.execute(
                "INSERT INTO ip_change_daily(account_id, day, count)"
                " VALUES (?,?,1)"
                " ON CONFLICT(account_id) DO UPDATE SET day=?, count=1",
                (account_id, day, day))
        return new


# ---------- 审计日志 ----------
def audit_add(ip: str, action: str, detail: str = "") -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO audit_log(ts, ip, action, detail) VALUES (?,?,?,?)",
            (time.time(), ip or "", action, detail or ""),
        )


def audit_list(limit: int = 200) -> list[dict]:
    """按时间倒序取审计日志。"""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- 抢机随机密码（密码保险箱，Fernet 加密存储） ----------
def password_save(account_id: int, instance_id: str,
                  username: str, password_enc: bytes) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO instance_passwords(account_id, instance_id,"
            " username, password_enc, created_at) VALUES (?,?,?,?,?)",
            (account_id, instance_id, username, password_enc, time.time()),
        )
        return cur.lastrowid


def password_get(instance_id: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM instance_passwords WHERE instance_id=?",
            (instance_id,), ).fetchone()
        return dict(row) if row else None


# ---------- 开机脚本模板 ----------
_OS_TYPES = ("linux", "windows")


def script_template_list(os_type: str | None = None) -> list[dict]:
    with _lock, _connect() as conn:
        if os_type in _OS_TYPES:
            rows = conn.execute(
                "SELECT * FROM script_templates WHERE os_type=? ORDER BY id",
                (os_type,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM script_templates ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def script_template_add(name: str, os_type: str, content: str) -> int:
    if os_type not in _OS_TYPES:
        raise ValueError("os_type 只能是 linux 或 windows")
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO script_templates(name, os_type, content, created_at)"
            " VALUES (?,?,?,?)",
            (name.strip(), os_type, content, time.time()),
        )
        return cur.lastrowid


def script_template_update(tpl_id: int, fields: dict) -> bool:
    allowed = {"name", "os_type", "content"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "os_type" and v not in _OS_TYPES:
            raise ValueError("os_type 只能是 linux 或 windows")
        if k == "name":
            v = (v or "").strip()
            if not v:
                raise ValueError("模板名称不能为空")
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return False
    with _lock, _connect() as conn:
        cur = conn.execute(
            f"UPDATE script_templates SET {', '.join(sets)} WHERE id=?",
            (*vals, tpl_id))
        return cur.rowcount > 0


def script_template_delete(tpl_id: int) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM script_templates WHERE id=?", (tpl_id,))
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


def job_list_by_type(job_type: str, account_id: int | None = None,
                     limit: int = 100) -> list[dict]:
    """按任务类型（可加账号过滤）取任务列表，时间倒序。"""
    with _lock, _connect() as conn:
        if account_id is not None:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE type=? AND account_id=?"
                " ORDER BY created_at DESC LIMIT ?",
                (job_type, account_id, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE type=?"
                " ORDER BY created_at DESC LIMIT ?",
                (job_type, limit)).fetchall()
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


def billing_cache_get(account_id: int):
    """取 AWS 账单缓存，返回 (data_dict|None, fetched_at_timestamp)。"""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "SELECT data, fetched_at FROM billing_cache WHERE account_id=?",
            (account_id,))
        row = cur.fetchone()
    if not row:
        return None, 0
    try:
        return json.loads(row[0]), row[1]
    except Exception:  # noqa: BLE001
        return None, 0


def billing_cache_set(account_id: int, data: dict) -> None:
    """写入 AWS 账单缓存。"""
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO billing_cache(account_id, data, fetched_at)"
            " VALUES (?,?,?)",
            (account_id, json.dumps(data), time.time()))
