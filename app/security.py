"""安全：TOTP 二次验证、API Token、审计日志、加密备份 / 恢复（原 extras.py 拆分）。
全部在本机完成，不依赖任何第三方中转服务。"""
import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import struct
import time
import zipfile

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import core

# ---------------- TOTP（RFC 6238） ----------------


def totp_new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _totp_at(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000)


def totp_verify(secret, code, window=1, now=None):
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit() or len(code) != 6:
        return False
    c = int((now or time.time()) // 30)
    # 防重放：同一时间片的验证码只能用一次
    last = core.get_setting("totp_last_counter", 0) or 0
    for d in range(-window, window + 1):
        if c + d > last and hmac.compare_digest(_totp_at(secret, c + d), code):
            core.set_setting("totp_last_counter", c + d)
            return True
    return False


def totp_uri(secret, label="TriCloud"):
    return f"otpauth://totp/{label}?secret={secret}&issuer=TriCloud&digits=6&period=30"


def totp_enabled():
    return bool(core.get_secret_setting("totp_secret"))


# ---------------- API Token ----------------
def token_hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


def new_api_token(name, scope="full"):
    t = "tc_" + secrets.token_urlsafe(32)
    core.ex("INSERT INTO api_tokens(name,token_hash,prefix,scope,created,last_used) VALUES(?,?,?,?,?,0)",
            (name, token_hash(t), t[:10], scope, int(time.time())))
    return t


def check_api_token(t, method="GET"):
    """返回匹配的 Token 行（真值）或 False。tc_ 开头为本面板签发；v1.5 起也接受从旧版迁移来的 Token
    （prefix='legacy'，同为 sha256(明文) 十六进制哈希）。"""
    if not t or len(t) < 20:
        return False
    r = core.q("SELECT * FROM api_tokens WHERE token_hash=?", (token_hash(t),), one=True)
    if not r or (not t.startswith("tc_") and r.get("prefix") != "legacy"):
        return False
    if r["scope"] == "read" and method not in ("GET", "HEAD"):
        return False
    core.ex("UPDATE api_tokens SET last_used=? WHERE id=?", (int(time.time()), r["id"]))
    return r


# ---------------- 审计 ----------------
def audit(ip, actor, action, detail=""):
    core.ex("INSERT INTO audit(ts,ip,actor,action,detail) VALUES(?,?,?,?,?)",
            (int(time.time()), ip, actor, action, (detail or "")[:500]))
    core.ex("DELETE FROM audit WHERE ts<?", (int(time.time()) - 180 * 86400,))   # 保留 180 天


# ---------------- 加密备份 / 恢复 ----------------
BACKUP_MAGIC = b"TCBK1"


def _kdf(passphrase, salt):
    return base64.urlsafe_b64encode(Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode()))


def make_backup(passphrase) -> bytes:
    """数据库 + fernet.key 打包，再用口令派生密钥整体加密。没有口令无法解开。"""
    if len(passphrase or "") < 10:
        raise ValueError("备份口令至少 10 位")
    buf = io.BytesIO()
    snap = os.path.join(core.DATA_DIR, ".backup.tmp.db")
    with core.db() as c:
        dst = sqlite3.connect(snap)
        c.backup(dst)
        dst.close()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "tricloud.db")
            z.write(core.KEY_PATH, "fernet.key")
            z.writestr("meta.json", json.dumps({"ts": int(time.time()), "format": 1}))
    finally:
        os.remove(snap)
    salt = secrets.token_bytes(16)
    return BACKUP_MAGIC + salt + Fernet(_kdf(passphrase, salt)).encrypt(buf.getvalue())


def restore_backup(blob: bytes, passphrase):
    if not blob.startswith(BACKUP_MAGIC):
        raise ValueError("不是 TriCloud 备份文件")
    salt, data = blob[5:21], blob[21:]
    try:
        raw = Fernet(_kdf(passphrase, salt)).decrypt(data)
    except InvalidToken:
        raise ValueError("口令错误或文件损坏")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = set(z.namelist())
        if not {"tricloud.db", "fernet.key"} <= names:
            raise ValueError("备份内容不完整")
        db_bytes, key = z.read("tricloud.db"), z.read("fernet.key")
    key = key.strip()
    Fernet(key)   # 校验 key 格式
    # 先校验备份 DB 可读且表结构完整，解密失败/损坏在这里就报错，不动现有数据
    tmp = os.path.join(core.DATA_DIR, ".restore.tmp.db")
    try:
        with open(tmp, "wb") as f:
            f.write(db_bytes)
        src = sqlite3.connect(tmp)
        try:
            src.execute("SELECT count(*) FROM accounts").fetchone()
        finally:
            src.close()
    except sqlite3.Error as e:
        raise ValueError(f"备份数据库损坏: {e}")
    # 先把当前 DB 与 key 备份到临时位置，恢复失败可回滚
    bak_db = os.path.join(core.DATA_DIR, ".restore.bak.db")
    bak_key = os.path.join(core.DATA_DIR, ".restore.bak.key")
    try:
        with core.db() as c:
            bak = sqlite3.connect(bak_db)
            try:
                c.backup(bak)
            finally:
                bak.close()
        if os.path.exists(core.KEY_PATH):
            with open(core.KEY_PATH, "rb") as f:
                old_key = f.read()
            with open(bak_key, "wb") as f:
                f.write(old_key)
        try:
            # 写入新 DB
            src = sqlite3.connect(tmp)
            try:
                with core.db() as c:
                    src.backup(c)
            finally:
                src.close()
            # 写新 key：先写临时文件再原子重命名，避免写一半崩溃
            tmp_key = core.KEY_PATH + ".tmp"
            with open(tmp_key, "wb") as f:
                f.write(key)
            os.chmod(tmp_key, 0o600)
            os.replace(tmp_key, core.KEY_PATH)
            core._fernet = None
            core.migrate()
            # 验证恢复后的 DB 可读
            with core.db() as c:
                c.execute("SELECT count(*) FROM accounts").fetchone()
        except Exception:
            # 回滚：恢复旧 DB 与旧 key
            try:
                rb = sqlite3.connect(bak_db)
                try:
                    with core.db() as c:
                        rb.backup(c)
                finally:
                    rb.close()
                if os.path.exists(bak_key):
                    with open(bak_key, "rb") as f:
                        rk = f.read()
                    with open(core.KEY_PATH, "wb") as f:
                        f.write(rk)
                    os.chmod(core.KEY_PATH, 0o600)
            finally:
                core._fernet = None
            raise
    finally:
        for p in (tmp, bak_db, bak_key):
            try:
                os.remove(p)
            except OSError:
                pass
    return True
