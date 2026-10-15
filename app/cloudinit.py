"""开机密码与 cloud-init：随机密码、cloud-config 生成、脚本模板解析、开机密码留存（原 extras.py 拆分）。"""
import base64
import json
import re
import secrets
import time

from . import core

# ---------------- 开机密码 + cloud-init ----------------
_ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def gen_password(n=20):
    """强随机密码：大小写+数字+符号各至少一个，满足 Azure 复杂度要求。"""
    while True:
        p = "".join(secrets.choice(_ALPHA) for _ in range(n - 2)) + secrets.choice("!@#%^*-_+=") + secrets.choice("23456789")
        p = "".join(secrets.SystemRandom().sample(p, len(p)))
        if any(c.islower() for c in p) and any(c.isupper() for c in p) and any(c.isdigit() for c in p):
            return p


def cloud_init(password=None, user="root", script=None, ssh_key=None, allow_password_ssh=True, hostname=None):
    """生成 cloud-config。不硬编码任何默认密码；密码由面板随机生成并加密留存。
    不在开机时 curl|bash 第三方脚本，用户自己的脚本原样执行。
    v1.5：hostname（须已规范化为 a-z0-9-）→ 系统主机名默认等于实例名。"""
    lines = ["#cloud-config"]
    if hostname and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname):
        lines += [f"hostname: {hostname}", f"fqdn: {hostname}", "preserve_hostname: false"]
    if password:
        lines += ["ssh_pwauth: true" if allow_password_ssh else "ssh_pwauth: false",
                  "chpasswd:", "  expire: false", "  list: |", f"    {user}:{password}"]
        if user != "root":
            lines.append(f"    root:{password}")   # root 同密码，便于救援
    if ssh_key:
        lines += ["ssh_authorized_keys:", f"  - {ssh_key.strip()}"]
    run = []
    if password and allow_password_ssh:
        run += [
            "sed -i 's/^#\\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config",
            "sed -i 's/^#\\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config",
            "rm -f /etc/ssh/sshd_config.d/60-cloudimg-settings.conf /etc/ssh/sshd_config.d/50-cloud-init.conf",
            "systemctl restart ssh || systemctl restart sshd || service ssh restart",
        ]
    if script and script.strip():
        lines += ["write_files:", "  - path: /root/tricloud-init.sh", "    permissions: '0700'", "    encoding: b64",
                  f"    content: {base64.b64encode(script.encode()).decode()}"]
        run.append("bash /root/tricloud-init.sh > /root/tricloud-init.log 2>&1")
    if run:
        lines.append("runcmd:")
        lines += [f"  - {json.dumps(['bash', '-c', c], ensure_ascii=False)}" for c in run]
    return "\n".join(lines) + "\n"


def resolve_script(p):
    """创建参数里 script_id 优先，其次 script 原文。"""
    if p.get("script_id"):
        r = core.q("SELECT content FROM scripts WHERE id=?", (int(p["script_id"]),), one=True)
        return r["content"] if r else None
    return p.get("script") or p.get("user_data")


def save_instance_secret(acc_id, inst_id, name, username, password):
    core.ex("INSERT INTO instance_secrets(account_id,instance_id,name,username,password_enc,created) VALUES(?,?,?,?,?,?)",
            (acc_id, inst_id, name, username, core.encrypt(password), int(time.time())))
