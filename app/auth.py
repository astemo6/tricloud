"""面板登录鉴权：PBKDF2 哈希存密码，DB 会话 + HttpOnly Cookie。"""
import hashlib
import hmac
import os

from . import config, db

_HASH_ITERATIONS = 210_000


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _HASH_ITERATIONS).hex()


def ensure_password_initialized() -> None:
    """首次启动时用环境变量 PANEL_PASSWORD 初始化密码哈希。"""
    if db.meta_get("password_hash"):
        return
    if not config.PANEL_PASSWORD:
        raise RuntimeError("首次启动必须设置环境变量 PANEL_PASSWORD")
    salt = os.urandom(16)
    db.meta_set("password_salt", salt.hex())
    db.meta_set("password_hash", _hash_password(config.PANEL_PASSWORD, salt))


def verify_password(password: str) -> bool:
    salt_hex = db.meta_get("password_salt")
    want = db.meta_get("password_hash")
    if not salt_hex or not want:
        return False
    got = _hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(got, want)


def set_password(password: str) -> None:
    salt = os.urandom(16)
    db.meta_set("password_salt", salt.hex())
    db.meta_set("password_hash", _hash_password(password, salt))
