"""凭证加密：Fernet 对称加密，密钥来自环境变量或 data/fernet.key（600 权限）。"""
import os
import stat

from cryptography.fernet import Fernet

from . import config

_KEY_PATH = os.path.join(config.DATA_DIR, "fernet.key")
_fernet: Fernet | None = None


def _load_or_create_key() -> bytes:
    if config.FERNET_KEY:
        key = config.FERNET_KEY.encode()
        Fernet(key)  # 校验格式
        return key
    os.makedirs(config.DATA_DIR, exist_ok=True)
    if os.path.exists(_KEY_PATH):
        with open(_KEY_PATH, "rb") as f:
            key = f.read().strip()
        Fernet(key)
        return key
    key = Fernet.generate_key()
    with open(_KEY_PATH, "wb") as f:
        f.write(key)
    os.chmod(_KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)
    return key


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt_secret(plaintext: str) -> bytes:
    return get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(token: bytes) -> str:
    return get_fernet().decrypt(token).decode("utf-8")
