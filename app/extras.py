"""v1.1 通用能力：TOTP 二次验证、开机密码与 cloud-init、Cloudflare DNS 联动、
加密备份/恢复、TCP 连通检测、API Token、审计日志。
全部在本机完成，不依赖任何第三方中转服务。"""
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import socket
import sqlite3
import struct
import time
import zipfile

import httpx
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


# ---------------- Cloudflare DNS ----------------
CF_API = "https://api.cloudflare.com/client/v4"


def _cf_headers():
    tok = core.get_secret_setting("cf_token")
    if not tok:
        raise RuntimeError("未配置 Cloudflare API Token（设置页）")
    return {"Authorization": f"Bearer {tok}"}


def _cf(method, path, **kw):
    r = httpx.request(method, CF_API + path, headers=_cf_headers(), timeout=20, **kw)
    j = r.json()
    if not j.get("success"):
        raise RuntimeError("Cloudflare: " + "; ".join(e.get("message", "") for e in j.get("errors", [])))
    return j["result"]


def cf_zones():
    return [{"id": z["id"], "name": z["name"]} for z in _cf("GET", "/zones", params={"per_page": 50})]


def cf_upsert(zone_id, name, rtype, content, proxied=False):
    recs = _cf("GET", f"/zones/{zone_id}/dns_records", params={"type": rtype, "name": name})
    body = {"type": rtype, "name": name, "content": content, "ttl": 60 if not proxied else 1, "proxied": bool(proxied)}
    if recs:
        _cf("PUT", f"/zones/{zone_id}/dns_records/{recs[0]['id']}", json=body)
        return f"{name} {rtype} → {content}（已更新）"
    _cf("POST", f"/zones/{zone_id}/dns_records", json=body)
    return f"{name} {rtype} → {content}（已创建）"


def dns_sync(acc_id, inst_id, ipv4=None, ipv6=None):
    """实例 IP 变化后，按绑定更新 Cloudflare 记录。返回说明文本列表；未绑定返回空。"""
    out = []
    for b in core.q("SELECT * FROM dns_bindings WHERE account_id=? AND instance_id=?", (acc_id, inst_id)):
        try:
            if not b["zone_id"]:   # v1.5：从旧版迁移来的绑定只有 zone_name，首次同步时查出 zone_id 并保存
                z = _cf("GET", "/zones", params={"name": b["zone_name"]})
                if not z:
                    raise RuntimeError(f"Cloudflare 中找不到域名 {b['zone_name']}")
                b["zone_id"] = z[0]["id"]
                core.ex("UPDATE dns_bindings SET zone_id=? WHERE id=?", (b["zone_id"], b["id"]))
            if ipv4 and b["v4"]:
                out.append(cf_upsert(b["zone_id"], b["record"], "A", ipv4, b["proxied"]))
            if ipv6 and b["v6"]:
                out.append(cf_upsert(b["zone_id"], b["record"], "AAAA", ipv6, b["proxied"]))
        except Exception as e:
            out.append(f"DNS 更新失败 {b['record']}: {str(e)[:120]}")
    return out


# ---------------- TCP 连通检测 ----------------
def tcp_alive(host, port=22, timeout=4, tries=2):
    for _ in range(tries):
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except OSError:
            time.sleep(1)
    return False


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
    Fernet(key.strip())   # 校验 key 格式
    tmp = os.path.join(core.DATA_DIR, ".restore.tmp.db")
    with open(tmp, "wb") as f:
        f.write(db_bytes)
    src = sqlite3.connect(tmp)
    src.execute("SELECT count(*) FROM accounts").fetchone()
    with core.db() as c:
        src.backup(c)
    src.close()
    os.remove(tmp)
    with open(core.KEY_PATH, "wb") as f:
        f.write(key.strip())
    os.chmod(core.KEY_PATH, 0o600)
    core._fernet = None
    core.migrate()
    return True


# ---------------- v1.4：换 IP 网段（支持 ! 排除） ----------------
def split_cidrs(cidrs):
    """把 ["129.146.0.0/16", "!129.146.10.0/24"] 拆成 (包含网段, 排除网段)。非法网段抛 ValueError。
    也接受逗号/换行分隔的字符串。只有排除网段时 = 任意 IP 只要不落在排除网段内即可。"""
    import ipaddress
    if isinstance(cidrs, str):
        cidrs = cidrs.replace("，", ",").replace("\n", ",").split(",")
    inc, exc = [], []
    for c in cidrs or []:
        c = str(c or "").strip()
        if not c:
            continue
        neg = c.startswith("!")
        c = c[1:].strip() if neg else c
        if not c:
            raise ValueError("! 后面缺少网段")
        (exc if neg else inc).append(ipaddress.ip_network(c, strict=False))
    return inc, exc


def ip_matches(ip, cidrs):
    """新 IP 是否满足网段要求：落在任一包含网段内（没有包含网段则不限），且不在任何排除网段内。"""
    import ipaddress
    inc, exc = split_cidrs(cidrs)
    if not ip:
        return False
    a = ipaddress.ip_address(ip)
    return (not inc or any(a in n for n in inc if n.version == a.version)) and not any(a in n for n in exc if n.version == a.version)


# ---------------- v1.6：IP 质量检测 ----------------
# 风险分来自 proxycheck.io（0~100，越低越干净；无 Key 每天 100 次，设置里可填免费 Key 提到 1000 次），
# 归属 / 机房标记来自 ip-api.com（免费、非商用）。只发送要检测的公网 IP，不发送任何凭证。
QUALITY_SOURCES = "proxycheck.io（风险分）+ ip-api.com（归属地 / ISP）"


def ip_quality(ip, timeout=8):
    import ipaddress
    ipaddress.ip_address(ip)   # 校验，非法直接抛 ValueError
    res = {"ip": ip, "risk": None, "type": None, "proxy": None, "country": None, "country_code": None,
           "isp": None, "asn": None, "hosting": None, "source": QUALITY_SOURCES}
    key = core.get_secret_setting("proxycheck_key") or ""
    try:
        r = httpx.get(f"https://proxycheck.io/v2/{ip}", params={"vpn": 1, "risk": 1, "asn": 1, **({"key": key} if key else {})},
                      timeout=timeout).json()
        d = r.get(ip) or {}
        if r.get("status") in ("ok", "warning") and d:
            res.update(risk=int(d["risk"]) if str(d.get("risk", "")).isdigit() else None, type=d.get("type"),
                       proxy=d.get("proxy") == "yes", country=d.get("country"), country_code=d.get("isocode"),
                       isp=d.get("provider") or d.get("organisation"), asn=d.get("asn"))
        elif r.get("message"):
            res["error"] = "proxycheck：" + str(r["message"])[:120]
    except Exception as e:
        res["error"] = f"proxycheck 查询失败：{str(e)[:80]}"
    try:
        g = httpx.get(f"http://ip-api.com/json/{ip}", params={"fields": "status,country,countryCode,isp,org,as,proxy,hosting"},
                      timeout=timeout).json()
        if g.get("status") == "success":
            res["country"] = res["country"] or g.get("country")
            res["country_code"] = res["country_code"] or g.get("countryCode")
            res["isp"] = res["isp"] or g.get("isp")
            res["asn"] = res["asn"] or (g.get("as") or "").split(" ")[0] or None
            res["org"] = g.get("org")
            res["hosting"] = bool(g.get("hosting"))
    except Exception:
        pass
    return res


def quality_ok(q, max_risk=None, country=None):
    """换 IP 的质量条件：风险分 ≤ max_risk；country（如 "US,JP"）非空时归属国家需在其中。查询失败视为不合格。"""
    why = []
    if max_risk not in (None, ""):
        if q.get("risk") is None:
            why.append("风险分查询失败")
        elif q["risk"] > int(max_risk):
            why.append(f"风险分 {q['risk']} > {int(max_risk)}")
    cc = [c.strip().upper() for c in str(country or "").replace("，", ",").split(",") if c.strip()]
    if cc and (q.get("country_code") or "").upper() not in cc:
        why.append(f"归属 {q.get('country_code') or '未知'} 不在 {','.join(cc)}")
    return not why, "；".join(why)
