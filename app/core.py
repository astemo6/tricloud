"""配置、SQLite、Fernet 加密、密码与会话。"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

from cryptography.fernet import Fernet

DATA_DIR = os.environ.get("TRICLOUD_DATA", os.path.join(os.path.dirname(__file__), "..", "data"))
DATA_DIR = os.path.abspath(DATA_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "tricloud.db")
KEY_PATH = os.path.join(DATA_DIR, "fernet.key")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
SESSION_TTL = int(os.environ.get("SESSION_TTL_HOURS", "168")) * 3600
PBKDF2_ITER = 210_000

# 登录失败锁定（NFR-01 加固）
LOGIN_MAX_FAIL = int(os.environ.get("LOGIN_MAX_FAIL", "5"))
LOGIN_LOCK_SECONDS = int(os.environ.get("LOGIN_LOCK_MINUTES", "15")) * 60

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, name TEXT NOT NULL,
  region TEXT, cred_enc TEXT NOT NULL, created INTEGER);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, expires INTEGER);
CREATE TABLE IF NOT EXISTS login_fail(ip TEXT PRIMARY KEY, count INTEGER, first INTEGER, locked_until INTEGER);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, account_id INTEGER, params TEXT,
  status TEXT, attempts INTEGER DEFAULT 0, message TEXT, created INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS billing_cache(account_id INTEGER PRIMARY KEY, data TEXT, fetched_at INTEGER);
CREATE TABLE IF NOT EXISTS aws_credits(
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, name TEXT, amount REAL,
  start_date TEXT, expire_date TEXT);
CREATE TABLE IF NOT EXISTS monitors(
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, instance_id TEXT, region TEXT,
  kind TEXT DEFAULT 'vm', name TEXT, auto_start INTEGER DEFAULT 0, last_state TEXT,
  UNIQUE(account_id, instance_id));
CREATE TABLE IF NOT EXISTS instance_secrets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, instance_id TEXT, name TEXT,
  username TEXT, password_enc TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS scripts(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, content TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS dns_bindings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, instance_id TEXT, name TEXT,
  zone_id TEXT, zone_name TEXT, record TEXT, proxied INTEGER DEFAULT 0, v4 INTEGER DEFAULT 1, v6 INTEGER DEFAULT 0,
  UNIQUE(account_id, instance_id, record));
CREATE TABLE IF NOT EXISTS api_tokens(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, token_hash TEXT UNIQUE, prefix TEXT, scope TEXT,
  created INTEGER, last_used INTEGER);
CREATE TABLE IF NOT EXISTS account_health(account_id INTEGER PRIMARY KEY, score INTEGER, data TEXT, checked_at INTEGER);
CREATE TABLE IF NOT EXISTS traffic_guards(
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, instance_id TEXT, region TEXT, kind TEXT DEFAULT 'vm', name TEXT,
  limit_gb REAL, warn_pct INTEGER DEFAULT 80, action TEXT DEFAULT 'notify', count_in INTEGER DEFAULT 0,
  month TEXT, notified INTEGER DEFAULT 0, last_gb REAL, last_pct REAL, checked_at INTEGER DEFAULT 0, UNIQUE(account_id, instance_id));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, ip TEXT, actor TEXT, action TEXT, detail TEXT);
"""

# 老库升级：只加列，不删数据
MIGRATIONS = [
    "ALTER TABLE monitors ADD COLUMN auto_change_ip INTEGER DEFAULT 0",
    "ALTER TABLE monitors ADD COLUMN check_port INTEGER DEFAULT 0",
    "ALTER TABLE monitors ADD COLUMN fail_count INTEGER DEFAULT 0",
    "ALTER TABLE monitors ADD COLUMN public_ip TEXT",
    # ---- v1.4 ----
    # 任务追加式日志 + 结果
    "CREATE TABLE IF NOT EXISTS task_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, ts INTEGER, level TEXT, msg TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id, id)",
    "ALTER TABLE tasks ADD COLUMN result TEXT",
    # 账号：云上创建日期、Credit 总额、Azure 教育优惠到期日、最近一次测活
    "ALTER TABLE accounts ADD COLUMN cloud_created_at TEXT",
    "ALTER TABLE accounts ADD COLUMN credit_total REAL",
    "ALTER TABLE accounts ADD COLUMN edu_expires_at TEXT",
    "ALTER TABLE accounts ADD COLUMN last_test_ok INTEGER",
    "ALTER TABLE accounts ADD COLUMN last_test_ms INTEGER",
    "ALTER TABLE accounts ADD COLUMN last_test_at INTEGER",
    "ALTER TABLE accounts ADD COLUMN last_test_error TEXT",
    # 手动 Credit（沿用 aws_credits 表，三家云通用）：手填已用额度
    "ALTER TABLE aws_credits ADD COLUMN used_manual REAL",
    # OCI / Azure 每月账单记录（免费接口，用于估算 Credit 已用额度）
    "CREATE TABLE IF NOT EXISTS billing_months(account_id INTEGER, month TEXT, total REAL, currency TEXT, updated INTEGER, "
    "PRIMARY KEY(account_id, month))",
    # 流量守护：滚动窗口 / 方向 / 关机 M 小时后自动开机 / 启停
    "ALTER TABLE traffic_guards ADD COLUMN mode TEXT DEFAULT 'monthly'",
    "ALTER TABLE traffic_guards ADD COLUMN window_hours INTEGER DEFAULT 24",
    "ALTER TABLE traffic_guards ADD COLUMN direction TEXT",
    "ALTER TABLE traffic_guards ADD COLUMN enabled INTEGER DEFAULT 1",
    "ALTER TABLE traffic_guards ADD COLUMN shutdown_hours REAL DEFAULT 0",
    "ALTER TABLE traffic_guards ADD COLUMN state TEXT DEFAULT 'ok'",
    "ALTER TABLE traffic_guards ADD COLUMN tripped_at INTEGER",
    "ALTER TABLE traffic_guards ADD COLUMN resume_at INTEGER",
    "ALTER TABLE traffic_guards ADD COLUMN state_msg TEXT",
    # 换 IP 记录（自动换 IP 每日限次）
    "CREATE TABLE IF NOT EXISTS ip_changes(id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, instance_id TEXT, "
    "ts INTEGER, day TEXT, auto INTEGER DEFAULT 0, task_id INTEGER)",
    # ---- v1.5 ----
    # 已删账号（删除账号时留档：名称、云、存活天数、预估费用）。与 AWS「闲置资源」估算（/api/accounts/{id}/recycle）无关
    "CREATE TABLE IF NOT EXISTS deleted_accounts(id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, name TEXT, region TEXT, "
    "lifecycle_days REAL, age_basis TEXT, est_cost REAL, currency TEXT, cost_basis TEXT, created INTEGER, deleted_at INTEGER, "
    "source TEXT DEFAULT 'panel')",
    # ---- v1.6 ----
    # 账号停用（被封号一键禁用：不测活、不监控、不跑流量守护，运行中的任务停止）+ 账号类型缓存
    "ALTER TABLE accounts ADD COLUMN disabled INTEGER DEFAULT 0",
    "ALTER TABLE accounts ADD COLUMN disabled_reason TEXT",
    "ALTER TABLE accounts ADD COLUMN acct_type TEXT",
]


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


_conn = None


def init_db():
    global _conn
    _conn = _connect()
    migrate()
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def migrate():
    _conn.executescript(SCHEMA)
    for m in MIGRATIONS:
        try:
            _conn.execute(m)
        except sqlite3.OperationalError:
            pass   # 列已存在
    _conn.commit()


@contextmanager
def db():
    with _lock:
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise


def q(sql, args=(), one=False):
    with db() as c:
        cur = c.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]
        return (rows[0] if rows else None) if one else rows


def ex(sql, args=()):
    with db() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def get_setting(k, default=None):
    r = q("SELECT v FROM settings WHERE k=?", (k,), one=True)
    if not r:
        return default
    try:
        return json.loads(r["v"])
    except Exception:
        return r["v"]


def set_setting(k, v):
    ex("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))


# ---------------- Fernet ----------------
_fernet = None


def fernet():
    global _fernet
    if _fernet is None:
        if not os.path.exists(KEY_PATH):
            key = Fernet.generate_key()
            fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
        os.chmod(KEY_PATH, 0o600)
        with open(KEY_PATH, "rb") as f:
            _fernet = Fernet(f.read().strip())
    return _fernet


def encrypt(obj) -> str:
    return fernet().encrypt(json.dumps(obj).encode()).decode()


def decrypt(token: str):
    return json.loads(fernet().decrypt(token.encode()).decode())


# 设置里的敏感项（如 Bot Token）也加密
def set_secret_setting(k, v):
    set_setting(k, encrypt(v) if v else "")


def get_secret_setting(k, default=""):
    v = get_setting(k, "")
    if not v:
        return default
    try:
        return decrypt(v)
    except Exception:
        return default


# ---------------- 密码 ----------------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITER)
    return f"pbkdf2_sha256${PBKDF2_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def ensure_password():
    if get_setting("password_hash"):
        return None
    pw = os.environ.get("PANEL_PASSWORD") or secrets.token_urlsafe(12)
    set_setting("password_hash", hash_password(pw))
    if not os.environ.get("PANEL_PASSWORD"):
        print(f"[tricloud] 初始面板密码（仅显示一次，请登录后修改）: {pw}", flush=True)
    return pw


# ---------------- 会话 ----------------
def _th(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_session() -> str:
    token = secrets.token_urlsafe(32)
    ex("INSERT INTO sessions(token_hash, expires) VALUES(?,?)", (_th(token), int(time.time()) + SESSION_TTL))
    ex("DELETE FROM sessions WHERE expires<?", (int(time.time()),))
    return token


def check_session(token) -> bool:
    if not token:
        return False
    r = q("SELECT expires FROM sessions WHERE token_hash=?", (_th(token),), one=True)
    return bool(r and r["expires"] > time.time())


def drop_session(token):
    if token:
        ex("DELETE FROM sessions WHERE token_hash=?", (_th(token),))


def drop_all_sessions():
    ex("DELETE FROM sessions")


# ---------------- 登录限速 ----------------
def login_locked(ip) -> int:
    r = q("SELECT * FROM login_fail WHERE ip=?", (ip,), one=True)
    if r and r["locked_until"] and r["locked_until"] > time.time():
        return int(r["locked_until"] - time.time())
    return 0


def login_failed(ip):
    now = int(time.time())
    r = q("SELECT * FROM login_fail WHERE ip=?", (ip,), one=True)
    if not r or now - (r["first"] or 0) > LOGIN_LOCK_SECONDS:
        ex("INSERT OR REPLACE INTO login_fail(ip,count,first,locked_until) VALUES(?,?,?,0)", (ip, 1, now))
        return
    cnt = r["count"] + 1
    locked = now + LOGIN_LOCK_SECONDS if cnt >= LOGIN_MAX_FAIL else 0
    ex("UPDATE login_fail SET count=?, locked_until=? WHERE ip=?", (cnt, locked, ip))


def login_ok(ip):
    ex("DELETE FROM login_fail WHERE ip=?", (ip,))


# ---------------- 账号 ----------------
def get_account(acc_id, with_cred=False):
    r = q("SELECT * FROM accounts WHERE id=?", (acc_id,), one=True)
    if not r:
        return None
    if with_cred:
        r["cred"] = decrypt(r["cred_enc"])
    r.pop("cred_enc", None)
    return r


# ---------------- v1.5 代理：URL + 单独的用户名 / 密码 ----------------
PROXY_SCHEMES = ("http://", "https://", "socks5://", "socks5h://")


def compose_proxy(cred) -> str:
    """把 proxy（URL，可内嵌 user:pass，旧格式）与 proxy_user / proxy_pass（v1.5 单独填写）合成最终代理 URL。
    单独填写的用户名优先，会替换 URL 里内嵌的认证信息；没填用户名时原样使用 URL（兼容旧格式）。"""
    from urllib.parse import quote, urlsplit, urlunsplit
    url = (cred.get("proxy") or "").strip()
    if not url:
        return ""
    user = (cred.get("proxy_user") or "").strip()
    if not user:
        return url
    pw = cred.get("proxy_pass") or ""
    u = urlsplit(url)
    host = u.netloc.rsplit("@", 1)[-1]
    auth = quote(user, safe="") + (":" + quote(str(pw), safe="") if pw else "")
    return urlunsplit(u._replace(netloc=f"{auth}@{host}"))


def runtime_cred(cred):
    """交给 Provider 的凭证副本：proxy 已合成，proxy_user / proxy_pass 不再单独传下去。"""
    c = {k: v for k, v in (cred or {}).items() if k not in ("proxy_user", "proxy_pass")}
    px = compose_proxy(cred or {})
    if px:
        c["proxy"] = px
    else:
        c.pop("proxy", None)
    return c


def proxy_view(cred):
    """列表 / 详情回显：只给主机、用户名、是否设置了密码，不回显密码。"""
    from urllib.parse import unquote, urlsplit
    url = (cred.get("proxy") or "").strip()
    if not url:
        return {"proxy": "", "proxy_user": "", "proxy_pass_set": False}
    u = urlsplit(url)
    embedded_user = unquote(u.username) if u.username else ""
    return {"proxy": url.split("@")[-1], "proxy_user": (cred.get("proxy_user") or "").strip() or embedded_user,
            "proxy_pass_set": bool(cred.get("proxy_pass")) or u.password is not None}


def list_accounts():
    rows = q("SELECT id, provider, name, region, created, cloud_created_at, credit_total, edu_expires_at, "
             "last_test_ok, last_test_ms, last_test_at, last_test_error, COALESCE(disabled,0) AS disabled, disabled_reason, acct_type "
             "FROM accounts ORDER BY provider, id")
    return rows


class LightsailRegionError(ValueError):
    """Lightsail 不支持该区域（如台北 ap-east-2）：main.py 按 400 返回友好提示，而不是 EndpointConnectionError 原文。
    放在 core 里，main 注册异常处理时不必提前导入 boto3。"""


# ---------------- OCI Ampere A1 免费额度 ----------------
# 2026-06 起 Oracle 调整：Always Free（免费）租户 A1 只含 1500 OCPU 时 + 9000 GB 时/月 = 2 OCPU / 12 GB；
# 付费（PAYG 等）租户价格表仍为每月前 3000 OCPU 时 + 18000 GB 时免费 = 4 OCPU / 24 GB。
OCI_A1_FREE_TIER = (2, 12)
OCI_A1_PAID = (4, 24)


def oci_a1_free(acc_id):
    """按缓存的账号类型返回 (ocpus, mem_gb, basis)。未识别类型时按免费号的 2/12 保守计算。"""
    import json as _json
    plan = None
    try:
        row = q("SELECT acct_type FROM accounts WHERE id=?", (acc_id,), one=True)
        if row and row["acct_type"]:
            plan = (_json.loads(row["acct_type"]) or {}).get("plan_type")
    except Exception:
        plan = None
    if plan and plan != "FREE_TIER":
        return OCI_A1_PAID[0], OCI_A1_PAID[1], "paid"
    return OCI_A1_FREE_TIER[0], OCI_A1_FREE_TIER[1], "free" if plan == "FREE_TIER" else "unknown"
