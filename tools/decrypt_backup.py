"""离线解密 TriCloud OneDrive 备份（.tcod）。只依赖 cryptography（pip install cryptography），不需要面板在运行。

用法（在仓库根目录）：
    python -m tools.decrypt_backup tricloud-backup-20261016-033000.tcod 输出目录
    python -m tools.decrypt_backup tricloud-backup-20261016-033000.tcod 备份密码 输出目录
不在命令行写密码时会提示输入（不回显，也不会留在 shell 历史里）。也可以用环境变量 TRICLOUD_BACKUP_PASSWORD。

输出目录里得到 tricloud.db、fernet.key、meta.json。手动恢复：停掉面板，把 tricloud.db 和 fernet.key
复制到 data/（覆盖前先备份原文件），chmod 600，再启动面板。

文件格式：b"TCOD1" | ver | log2(N) | r | p | salt(16) | nonce(12) | AES-256-GCM 密文（aad = 前 37 字节头），
密钥 = scrypt(密码, salt, N, r, p, 32 字节)，明文是 zip。
"""
import getpass
import io
import os
import sys
import zipfile

MAGIC = b"TCOD1"
HDR_LEN = 37


def decrypt(blob: bytes, password: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if len(blob) < HDR_LEN + 16 or not blob.startswith(MAGIC):
        raise ValueError("不是 TriCloud OneDrive 备份文件（.tcod）")
    ver, log2n, r, p = blob[5], blob[6], blob[7], blob[8]
    if ver != 1 or not (10 <= log2n <= 20 and 1 <= r <= 16 and 1 <= p <= 4):
        raise ValueError("备份文件版本不受支持")
    hdr = blob[:HDR_LEN]
    key = Scrypt(salt=hdr[9:25], length=32, n=2 ** log2n, r=r, p=p).derive(password.encode("utf-8"))
    try:
        return AESGCM(key).decrypt(hdr[25:37], blob[HDR_LEN:], hdr)
    except InvalidTag:
        raise ValueError("备份密码错误或文件已损坏")


def extract(blob: bytes, password: str, out_dir: str):
    raw = decrypt(blob, password)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if not {"tricloud.db", "fernet.key"} <= set(names):
            raise ValueError("备份内容不完整")
        os.makedirs(out_dir, mode=0o700, exist_ok=True)
        written = []
        for n in ("tricloud.db", "fernet.key", "meta.json"):
            if n not in names:
                continue
            p = os.path.join(out_dir, n)
            if os.path.exists(p):
                raise ValueError(f"{p} 已存在，请换一个空目录")
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(z.read(n))
            written.append(p)
    return written


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) == 2:
        src, out = a
        pw = os.environ.get("TRICLOUD_BACKUP_PASSWORD") or getpass.getpass("备份密码：")
    elif len(a) == 3:
        src, pw, out = a
    else:
        print(__doc__)
        return 2
    try:
        with open(src, "rb") as f:
            files = extract(f.read(), pw, out)
    except (OSError, ValueError) as e:
        print(f"失败：{e}", file=sys.stderr)
        return 1
    print("已解密：\n  " + "\n  ".join(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
