"""备份/恢复：整个 SQLite 库文件用密码派生密钥加密。

文件格式：salt(16字节) + Fernet密文。
备份密码绝不存服务器、不记日志。
"""
import base64
import hashlib
import os
import sqlite3
import tempfile

from cryptography.fernet import Fernet

_PBKDF2_ITERATIONS = 200_000
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _derive_key(password: str, salt: bytes) -> bytes:
    raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                              _PBKDF2_ITERATIONS, dklen=32)
    return base64.urlsafe_b64encode(raw)


def encrypt_db_file(data: bytes, password: str) -> bytes:
    """加密数据库文件内容，返回 salt + 密文。"""
    salt = os.urandom(16)
    return salt + Fernet(_derive_key(password, salt)).encrypt(data)


def decrypt_db_file(blob: bytes, password: str) -> bytes:
    """解密备份文件，密码错或文件损坏抛 ValueError。"""
    if len(blob) < 17:
        raise ValueError("备份文件损坏或不是有效的备份")
    salt, token = blob[:16], blob[16:]
    try:
        return Fernet(_derive_key(password, salt)).decrypt(token)
    except Exception as e:  # noqa: BLE001 - 密码错/文件损坏统一提示
        raise ValueError("密码错误或备份文件损坏") from e


def inspect_db(data: bytes) -> dict:
    """校验解密后的 SQLite 内容，返回备份信息（账号数/记录时间）。"""
    if not data.startswith(_SQLITE_MAGIC):
        raise ValueError("备份内容不是有效的 SQLite 数据库")
    fd, path = tempfile.mkstemp(suffix=".db")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "accounts" not in tables or "meta" not in tables:
                raise ValueError("备份内容不是 TriCloud 数据库")
            accounts = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            latest = conn.execute(
                "SELECT MAX(updated_at) FROM accounts").fetchone()[0] or 0
        finally:
            conn.close()
    finally:
        os.unlink(path)
    return {"accounts": accounts, "latest_record_at": latest}
