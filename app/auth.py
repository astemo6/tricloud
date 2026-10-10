"""面板登录鉴权：PBKDF2 哈希存密码，DB 会话 + HttpOnly Cookie，TOTP 二次验证。"""
import base64
import hashlib
import hmac
import io
import os

import pyotp
import qrcode

from . import config, db
from .crypto import decrypt_secret, encrypt_secret

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


# ---------- TOTP 二次验证 ----------

def totp_enabled() -> bool:
    return db.meta_get("totp_enabled") == "1"


def totp_setup() -> dict:
    """生成新的 TOTP 密钥并暂存；确认前 totp_enabled 保持 '0'。

    返回 {secret 明文, otpauth_uri, qr_data_uri}，只出现这一次，明文不落库。
    """
    secret = pyotp.random_base32()
    db.meta_set("totp_secret", encrypt_secret(secret).hex())
    db.meta_set("totp_enabled", "0")
    totp = pyotp.TOTP(secret)
    otpauth_uri = totp.provisioning_uri(name="TriCloud", issuer_name="TriCloud")
    img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return {"secret": secret, "otpauth_uri": otpauth_uri, "qr_data_uri": qr_data_uri}


def _load_totp() -> pyotp.TOTP | None:
    secret_hex = db.meta_get("totp_secret")
    if not secret_hex:
        return None
    try:
        secret = decrypt_secret(bytes.fromhex(secret_hex))
    except Exception:  # noqa: BLE001 - 密文损坏视为未配置
        return None
    return pyotp.TOTP(secret)


def totp_verify(code: str) -> bool:
    """验证当前 TOTP 码，容忍前后 1 个时间窗口。"""
    totp = _load_totp()
    if not totp:
        return False
    return totp.verify((code or "").strip(), valid_window=1)


def totp_confirm_enable(code: str) -> bool:
    """验证一次当前码，成功后正式启用 TOTP。"""
    if not totp_verify(code):
        return False
    db.meta_set("totp_enabled", "1")
    return True


def totp_disable() -> None:
    db.meta_set("totp_secret", "")
    db.meta_set("totp_enabled", "0")
