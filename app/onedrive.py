"""build 21 OneDrive 定期备份：Microsoft Graph 设备码登录 + 应用专属文件夹（approot）+ 加密备份 / 恢复。

- 登录：设备码流程（/consumers 或 /common），scope 只有 Files.ReadWrite.AppFolder offline_access，
  只能读写 OneDrive「应用/<你的 Azure 应用名>」这一个文件夹，看不到网盘里其他文件。
  client_id 由用户在 Azure 门户注册自己的公共客户端应用后填写（见 docs/api-credentials.md）。
- refresh token、备份密码都用面板现有的 Fernet（data/fernet.key）加密后存在 settings 表：
  定时备份要无人值守运行，所以密码必须能被面板自己解开；能读到 data/ 的人本来就能读到全部云凭证。
  上传到 OneDrive 的备份文件只用备份密码加密，与 fernet.key 无关，OneDrive 上的文件没有密码打不开。
- 备份文件格式（.tcod）：header = b"TCOD1" | ver(1) | log2(N)(1) | r(1) | p(1) | salt(16) | nonce(12)，
  之后是 AES-256-GCM(scrypt(密码, salt, N, r, p), nonce, zip, aad=header) 的密文。
  zip 里是 tricloud.db（SQLite backup API 一致快照）、fernet.key、meta.json。
  离线解密：python -m tools.decrypt_backup 文件 [密码] 输出目录（只依赖 cryptography）。
"""
import datetime as dt
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import zipfile

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import core

SCOPE = "Files.ReadWrite.AppFolder offline_access"
TENANTS = ("consumers", "common")
LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
DEVICE_LOGIN_URL = "https://microsoft.com/devicelogin"
SIMPLE_MAX = 4 * 1024 * 1024            # ≤4MB 直接 PUT，否则用 upload session
CHUNK = 320 * 1024 * 10                 # upload session 分片须是 320 KiB 的整数倍（3.125 MiB）
MAX_DOWNLOAD = 512 * 1024 * 1024        # 恢复时最多下载 512MB
PW_MIN = 1                              # build 22：不限长度 / 复杂度，只要求不为空（两次输入一致由 password2 校验）
KEEP_DEFAULT, KEEP_MAX = 30, 365
NAME_RE = re.compile(r"^tricloud-backup-\d{8}-\d{6}(-\d+)?\.tcod$")   # 只管理自己生成的文件，保留策略不会删别的
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

MAGIC = b"TCOD1"
FMT_VER = 1
KDF_LOG2N, KDF_R, KDF_P = 15, 8, 1
HDR_LEN = len(MAGIC) + 4 + 16 + 12

# settings 键
K_CLIENT, K_TENANT, K_TOKEN, K_PENDING, K_PW, K_CFG, K_STATE = (
    "onedrive_client_id", "onedrive_tenant", "onedrive_token", "onedrive_pending", "onedrive_password", "onedrive_cfg", "onedrive_state")
CFG_DEFAULT = {"enabled": True, "freq": "daily", "time": "03:30", "weekday": 0, "keep": KEEP_DEFAULT}

# 测试替换点
_transport = None          # httpx.MockTransport
_sleep = time.sleep
_lock = threading.RLock()
_access = {"token": None, "exp": 0}


class ODError(ValueError):
    """给用户看的 OneDrive 错误（common.call 会转成 400）。kind：config / auth / graph / crypto / busy。"""

    def __init__(self, msg, kind="graph"):
        super().__init__(msg)
        self.kind = kind


# ---------------- 设置 ----------------
def client_id():
    return (core.get_setting(K_CLIENT, "") or "").strip()


def tenant():
    t = core.get_setting(K_TENANT, "consumers") or "consumers"
    return t if t in TENANTS else "consumers"


def cfg():
    c = dict(CFG_DEFAULT)
    c.update({k: v for k, v in (core.get_setting(K_CFG) or {}).items() if k in CFG_DEFAULT})
    return c


def state():
    return core.get_setting(K_STATE) or {}


def set_state(**kw):
    s = state()
    s.update(kw)
    core.set_setting(K_STATE, s)
    return s


def token():
    return core.get_secret_setting(K_TOKEN, None) or None


def bound():
    t = token()
    return bool(t and t.get("refresh_token"))


def password():
    return core.get_secret_setting(K_PW, "") or ""


def validate_cfg(body):
    """校验并返回要合并进 onedrive_cfg 的字段（只含 body 里给了的）。"""
    out = {}
    if "enabled" in body:
        v = body["enabled"]
        out["enabled"] = v.strip().lower() not in ("0", "false", "no", "off", "") if isinstance(v, str) else bool(v)
    if "freq" in body:
        if body["freq"] not in ("daily", "weekly"):
            raise ODError("频率只能是 daily（每天）或 weekly（每周）", "config")
        out["freq"] = body["freq"]
    if "time" in body:
        if not TIME_RE.match(str(body["time"] or "")):
            raise ODError("时间格式应为 HH:MM（24 小时制）", "config")
        out["time"] = str(body["time"])
    if "weekday" in body:
        try:
            wd = int(body["weekday"])
        except (TypeError, ValueError):
            raise ODError("星期需为 0（周一）~6（周日）", "config")
        if not 0 <= wd <= 6:
            raise ODError("星期需为 0（周一）~6（周日）", "config")
        out["weekday"] = wd
    if "keep" in body:
        try:
            k = int(body["keep"])
        except (TypeError, ValueError):
            raise ODError(f"保留份数需为 1~{KEEP_MAX} 的整数", "config")
        if not 1 <= k <= KEEP_MAX:
            raise ODError(f"保留份数需为 1~{KEEP_MAX}", "config")
        out["keep"] = k
    return out


def save_config(body):
    """POST /api/onedrive/config：client_id / tenant / 频率 / 时间 / 保留 / 密码。返回改了哪些项（不含密码明文）。"""
    changed = []
    if "client_id" in body:
        cid = str(body.get("client_id") or "").strip()
        if cid and not GUID_RE.match(cid):
            raise ODError("client_id 应为 Azure 应用的「应用程序(客户端) ID」，形如 00000000-0000-0000-0000-000000000000", "config")
        if cid != client_id():
            core.set_setting(K_CLIENT, cid)
            changed.append("client_id")
            if bound():   # 换了应用，旧 token 属于旧应用，不能再用
                unbind()
                changed.append("unbound")
    if "tenant" in body:
        tn = body.get("tenant") or "consumers"
        if tn not in TENANTS:
            raise ODError("登录端点只能是 consumers（个人账号）或 common", "config")
        if tn != tenant():
            core.set_setting(K_TENANT, tn)
            changed.append("tenant")
    if body.get("password_clear"):
        core.set_secret_setting(K_PW, "")
        changed.append("password_clear")
    elif body.get("password"):
        pw = str(body["password"])
        if not pw.strip():
            raise ODError("备份密码不能为空", "config")
        if "password2" in body and body.get("password2") != pw:
            raise ODError("两次输入的备份密码不一致", "config")
        core.set_secret_setting(K_PW, pw)
        changed.append("password")
    upd = validate_cfg(body)
    if upd:
        c = cfg()
        c.update(upd)
        core.set_setting(K_CFG, c)
        changed += sorted(upd)
        # 改了计划：从当前这一期开始算，不补跑已过去的那次
        set_state(slot=slot_key(c, now_local()), slot_tries=0)
    return changed


def now_local():
    from . import services
    return services.now_local()


# ---------------- HTTP ----------------
def _client(timeout=60):
    kw = {"timeout": timeout, "follow_redirects": True}
    if _transport is not None:
        kw["transport"] = _transport
    return httpx.Client(**kw)


def _err_text(r):
    try:
        j = r.json()
    except ValueError:
        return (r.text or "")[:200]
    if isinstance(j.get("error"), dict):
        e = j["error"]
        return f"{e.get('code', '')}: {e.get('message', '')}"[:300]
    return f"{j.get('error', '')}: {j.get('error_description', '')}"[:300]


def _post_form(url, data):
    with _client(30) as cl:
        r = cl.post(url, data=data, headers={"Accept": "application/json"})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"error": "bad_response", "error_description": (r.text or "")[:200]}


# ---------------- 设备码登录 ----------------
def bind_start():
    cid = client_id()
    if not cid:
        raise ODError("请先填写 Azure 应用的 client_id（应用程序(客户端) ID）", "config")
    st, j = _post_form(f"{LOGIN}/{tenant()}/oauth2/v2.0/devicecode", {"client_id": cid, "scope": SCOPE})
    if st != 200 or not j.get("device_code"):
        raise ODError(_friendly_auth(j), "auth")
    now = int(time.time())
    pend = {"device_code": j["device_code"], "user_code": j["user_code"],
            "verification_uri": j.get("verification_uri") or DEVICE_LOGIN_URL,
            "interval": int(j.get("interval") or 5), "expires_at": now + int(j.get("expires_in") or 900), "started": now}
    core.set_secret_setting(K_PENDING, pend)
    return pending_view(pend)


def pending_view(p=None):
    p = p if p is not None else (core.get_secret_setting(K_PENDING, None) or None)
    if not p or p.get("expires_at", 0) <= time.time():
        return None
    return {"user_code": p["user_code"], "verification_uri": p["verification_uri"], "interval": p["interval"],
            "expires_at": p["expires_at"], "expires_in": max(0, int(p["expires_at"] - time.time()))}


def _friendly_auth(j):
    e = j.get("error") or ""
    d = (j.get("error_description") or "").split("\r\n")[0][:200]
    if e == "unauthorized_client" or "AADSTS70002" in d or "AADSTS7000218" in d:
        return "该应用未启用「允许公共客户端流」，请在 Azure 门户 → 身份验证 → 高级设置里打开（见教程）"
    if e == "invalid_client" or "AADSTS700016" in d:
        return "client_id 不存在或不支持个人 Microsoft 账号（注册时要选「任何组织目录中的帐户和个人 Microsoft 帐户」或「仅个人 Microsoft 帐户」）"
    if e == "invalid_scope":
        return "应用不接受 Files.ReadWrite.AppFolder 权限，请检查应用的 API 权限设置"
    return f"Microsoft 登录接口返回：{e} {d}".strip()


def bind_poll():
    """轮询一次设备码。返回 {status: pending/slow_down/ok/expired/declined/none, ...}。"""
    p = core.get_secret_setting(K_PENDING, None) or None
    if not p:
        return {"status": "ok" if bound() else "none"}
    if p.get("expires_at", 0) <= time.time():
        core.set_secret_setting(K_PENDING, "")
        return {"status": "expired", "message": "设备码已过期，请重新绑定"}
    st, j = _post_form(f"{LOGIN}/{tenant()}/oauth2/v2.0/token",
                       {"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": client_id(),
                        "device_code": p["device_code"]})
    if st == 200 and j.get("refresh_token"):
        core.set_secret_setting(K_PENDING, "")
        _store_token(j)
        info = _account_info()
        t = token() or {}
        t["account"] = info
        core.set_secret_setting(K_TOKEN, t)
        set_state(bound_at=int(time.time()), auth_error="")
        return {"status": "ok", "account": info}
    e = j.get("error")
    if e == "authorization_pending":
        return {"status": "pending", "interval": p["interval"]}
    if e == "slow_down":
        p["interval"] = int(p["interval"]) + 5
        core.set_secret_setting(K_PENDING, p)
        return {"status": "slow_down", "interval": p["interval"]}
    core.set_secret_setting(K_PENDING, "")
    if e == "authorization_declined":
        return {"status": "declined", "message": "你在 Microsoft 页面上拒绝了授权"}
    if e in ("expired_token", "code_expired"):
        return {"status": "expired", "message": "设备码已过期，请重新绑定"}
    return {"status": "error", "message": _friendly_auth(j)}


def bind_cancel():
    core.set_secret_setting(K_PENDING, "")


def _store_token(j):
    old = token() or {}
    t = {"refresh_token": j.get("refresh_token") or old.get("refresh_token"), "scope": j.get("scope") or SCOPE,
         "account": old.get("account") or {}, "obtained": int(time.time())}
    core.set_secret_setting(K_TOKEN, t)
    _access.update(token=j.get("access_token"), exp=time.time() + int(j.get("expires_in") or 3600) - 120)


def unbind():
    """删除本地 token（OneDrive 上的备份文件不动）。"""
    with _lock:
        core.set_secret_setting(K_TOKEN, "")
        core.set_secret_setting(K_PENDING, "")
        _access.update(token=None, exp=0)


def _access_token():
    with _lock:
        if _access["token"] and _access["exp"] > time.time():
            return _access["token"]
        t = token()
        if not t or not t.get("refresh_token"):
            raise ODError("尚未绑定 OneDrive", "auth")
        st, j = _post_form(f"{LOGIN}/{tenant()}/oauth2/v2.0/token",
                           {"grant_type": "refresh_token", "client_id": client_id(), "refresh_token": t["refresh_token"],
                            "scope": SCOPE})
        if st != 200 or not j.get("access_token"):
            if j.get("error") in ("invalid_grant", "interaction_required"):
                set_state(auth_error="OneDrive 授权已失效（被撤销或长期未使用），请重新绑定")
                raise ODError("OneDrive 授权已失效（被撤销或长期未使用），请解绑后重新绑定", "auth")
            raise ODError("刷新 OneDrive 授权失败：" + _friendly_auth(j), "auth")
        _store_token(j)
        if state().get("auth_error"):
            set_state(auth_error="")
        return _access["token"]


def _graph(method, path, ok=(200, 201, 202, 204), retries=3, **kw):
    """调用 Graph（带 token）。429 / 5xx 按 Retry-After 重试，401 刷新一次 token。"""
    url = path if path.startswith("https://") else GRAPH + path
    refreshed = False
    for i in range(retries + 1):
        h = dict(kw.pop("headers", None) or {})
        h["Authorization"] = "Bearer " + _access_token()
        with _client(120) as cl:
            r = cl.request(method, url, headers=h, **kw)
        kw["headers"] = {k: v for k, v in h.items() if k != "Authorization"}
        if r.status_code in ok:
            return r
        if r.status_code == 401 and not refreshed:
            refreshed = True
            _access.update(token=None, exp=0)
            continue
        if (r.status_code == 429 or r.status_code >= 500) and i < retries:
            try:
                wait = min(30, max(1, int(r.headers.get("Retry-After") or 2 ** i)))
            except ValueError:
                wait = 2 ** i
            _sleep(wait)
            continue
        raise ODError(f"OneDrive 接口 {method} 返回 HTTP {r.status_code}：{_err_text(r)}", "graph")
    raise ODError("OneDrive 接口多次重试失败", "graph")


def _account_info():
    """只用 AppFolder 权限能拿到的信息：approot 文件夹名、网盘类型；拿不到不影响绑定。"""
    info = {}
    try:
        j = _graph("GET", "/me/drive/special/approot?$select=id,name,parentReference", retries=1).json()
        info["folder"] = j.get("name") or ""
        info["drive_type"] = (j.get("parentReference") or {}).get("driveType") or ""
    except Exception as e:   # noqa: BLE001
        info["error"] = str(e)[:120]
    return info


# ---------------- 文件操作 ----------------
def _q(name):
    from urllib.parse import quote
    return quote(name, safe="")


def upload(name, data: bytes):
    if len(data) <= SIMPLE_MAX:
        r = _graph("PUT", f"/me/drive/special/approot:/{_q(name)}:/content", content=data,
                   headers={"Content-Type": "application/octet-stream"})
        return r.json()
    r = _graph("POST", f"/me/drive/special/approot:/{_q(name)}:/createUploadSession",
               json={"item": {"@microsoft.graph.conflictBehavior": "replace"}})
    up = r.json()["uploadUrl"]
    total, pos = len(data), 0
    try:
        while pos < total:
            chunk = data[pos:pos + CHUNK]
            end = pos + len(chunk) - 1
            for i in range(4):
                # uploadUrl 自带授权，不能再带 Authorization 头
                with _client(300) as cl:
                    rr = cl.put(up, content=chunk, headers={"Content-Range": f"bytes {pos}-{end}/{total}",
                                                             "Content-Length": str(len(chunk))})
                if rr.status_code in (200, 201, 202):
                    break
                if (rr.status_code == 429 or rr.status_code >= 500) and i < 3:
                    _sleep(min(30, 2 ** i))
                    continue
                raise ODError(f"分片上传失败 HTTP {rr.status_code}：{_err_text(rr)}", "graph")
            pos = end + 1
            if rr.status_code in (200, 201):
                return rr.json()
        raise ODError("分片上传结束但 OneDrive 未返回文件信息", "graph")
    except Exception:
        try:
            with _client(30) as cl:
                cl.delete(up)
        except Exception:   # noqa: BLE001
            pass
        raise


def list_backups():
    """approot 下 TriCloud 生成的备份，新的在前。"""
    out, url = [], "/me/drive/special/approot/children?$select=id,name,size,createdDateTime,lastModifiedDateTime,file&$top=200"
    for _ in range(50):
        j = _graph("GET", url).json()
        for it in j.get("value") or []:
            if it.get("file") is not None and NAME_RE.match(it.get("name") or ""):
                out.append({"id": it["id"], "name": it["name"], "size": int(it.get("size") or 0),
                            "created": it.get("createdDateTime") or it.get("lastModifiedDateTime") or "",
                            "time": name_time(it["name"])})
        url = j.get("@odata.nextLink")
        if not url:
            break
    out.sort(key=lambda x: x["name"], reverse=True)
    return out


def name_time(name):
    m = re.match(r"^tricloud-backup-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})", name or "")
    return f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}:{m[6]}" if m else ""


def delete_item(item_id):
    _graph("DELETE", f"/me/drive/items/{_q(item_id)}", ok=(204, 200, 404))


def download(item_id):
    r = _graph("GET", f"/me/drive/items/{_q(item_id)}?$select=id,name,size")
    meta = r.json()
    if int(meta.get("size") or 0) > MAX_DOWNLOAD:
        raise ODError("备份文件超过 512MB，拒绝下载", "graph")
    if not NAME_RE.match(meta.get("name") or ""):
        raise ODError("这不是 TriCloud 生成的备份文件", "graph")
    r = _graph("GET", f"/me/drive/items/{_q(item_id)}/content")
    return meta, r.content


def prune(keep):
    """保留最近 keep 份（按文件名里的时间戳），删除更早的；返回删掉的文件名。"""
    items = list_backups()
    gone = []
    for it in items[keep:]:
        delete_item(it["id"])
        gone.append(it["name"])
    return gone


# ---------------- 加密格式 ----------------
def _kdf(pw, salt, log2n=KDF_LOG2N, r=KDF_R, p=KDF_P):
    return Scrypt(salt=salt, length=32, n=2 ** log2n, r=r, p=p).derive(pw.encode("utf-8"))


def encrypt_blob(payload: bytes, pw: str) -> bytes:
    if not pw:
        raise ODError("备份密码不能为空", "crypto")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    hdr = MAGIC + bytes([FMT_VER, KDF_LOG2N, KDF_R, KDF_P]) + salt + nonce
    return hdr + AESGCM(_kdf(pw, salt)).encrypt(nonce, payload, hdr)


def decrypt_blob(blob: bytes, pw: str) -> bytes:
    if len(blob) < HDR_LEN + 16 or not blob.startswith(MAGIC):
        raise ODError("不是 TriCloud OneDrive 备份文件（.tcod）", "crypto")
    ver, log2n, r, p = blob[5], blob[6], blob[7], blob[8]
    if ver != FMT_VER or not (10 <= log2n <= 20 and 1 <= r <= 16 and 1 <= p <= 4):
        raise ODError("备份文件版本不受支持", "crypto")
    hdr = blob[:HDR_LEN]
    salt, nonce = hdr[9:25], hdr[25:37]
    try:
        return AESGCM(_kdf(pw or "", salt, log2n, r, p)).decrypt(nonce, blob[HDR_LEN:], hdr)
    except InvalidTag:
        raise ODError("备份密码错误或文件已损坏", "crypto")


def snapshot_files():
    """返回 (db_bytes, key_bytes)：数据库用 SQLite backup API 取一致快照。"""
    snap = os.path.join(core.DATA_DIR, f".od-snap-{secrets.token_hex(4)}.db")
    try:
        with core.db() as c:
            dst = sqlite3.connect(snap)
            c.backup(dst)
            dst.close()
        with open(snap, "rb") as f:
            dbb = f.read()
    finally:
        if os.path.exists(snap):
            os.remove(snap)
    with open(core.KEY_PATH, "rb") as f:
        key = f.read().strip()
    return dbb, key


def build_payload():
    from .routers.common import VERSION
    dbb, key = snapshot_files()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("tricloud.db", dbb)
        z.writestr("fernet.key", key)
        z.writestr("meta.json", json.dumps({"ts": int(time.time()), "format": 1, "kind": "onedrive", "version": VERSION,
                                            "db_size": len(dbb)}))
    return buf.getvalue()


def parse_payload(raw: bytes):
    """解开 zip，校验内容；返回 (db_bytes, key_bytes, meta)。"""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = set(z.namelist())
            if not {"tricloud.db", "fernet.key"} <= names:
                raise ODError("备份内容不完整（缺少 tricloud.db 或 fernet.key）", "crypto")
            dbb, key = z.read("tricloud.db"), z.read("fernet.key").strip()
            meta = json.loads(z.read("meta.json")) if "meta.json" in names else {}
    except zipfile.BadZipFile:
        raise ODError("备份内容损坏", "crypto")
    if not dbb.startswith(b"SQLite format 3\x00"):
        raise ODError("备份里的数据库文件无效", "crypto")
    try:
        Fernet(key)
    except Exception:   # noqa: BLE001
        raise ODError("备份里的 fernet.key 无效", "crypto")
    return dbb, key, meta


def backup_name(now=None):
    now = now or now_local()
    return f"tricloud-backup-{now:%Y%m%d-%H%M%S}.tcod"


def run_backup(trigger="manual", log=None):
    """生成快照 → 加密 → 上传 → 保留最近 N 份。返回 {name, size, pruned}。"""
    log = log or (lambda m, lv="info": None)
    if not bound():
        raise ODError("尚未绑定 OneDrive", "config")
    pw = password()
    if not pw:
        raise ODError("尚未设置备份密码", "config")
    c = cfg()
    log("生成数据库一致快照（SQLite backup API）…")
    payload = build_payload()
    blob = encrypt_blob(payload, pw)
    name = backup_name()
    log(f"已加密（scrypt + AES-256-GCM），{len(blob) / 1024:.1f} KB，上传 {name}"
        + ("（分片上传）" if len(blob) > SIMPLE_MAX else ""))
    item = upload(name, blob)
    log("上传完成", "ok")
    pruned = []
    try:
        pruned = prune(int(c["keep"]))
        if pruned:
            log(f"按保留 {c['keep']} 份删除了 {len(pruned)} 个旧备份：" + "、".join(pruned[:5]) + ("…" if len(pruned) > 5 else ""))
    except Exception as e:   # noqa: BLE001  清理失败不算备份失败
        log(f"清理旧备份失败（备份本身已成功）：{e}", "warn")
    set_state(last_ok=int(time.time()), last_file=name, last_size=len(blob), last_error="", last_result="done",
              last_trigger=trigger)
    return {"name": name, "size": len(blob), "id": item.get("id"), "pruned": pruned}


# ---------------- 恢复 ----------------
RESTORE_PRESERVE = (K_CLIENT, K_TENANT)
RESTORE_PRESERVE_SECRET = (K_TOKEN,)


def local_snapshot(tag="pre-restore"):
    """恢复前在 data/ 下保存一份当前数据库 + fernet.key（未加密，与 data/ 本身同等保护）。"""
    base = os.path.join(core.DATA_DIR, f"{tag}-{now_local():%Y%m%d-%H%M%S}")
    d, n = base, 1
    while os.path.exists(d):
        n += 1
        d = f"{base}-{n}"
    os.makedirs(d, mode=0o700)
    dbb, key = snapshot_files()
    for fn, b in (("tricloud.db", dbb), ("fernet.key", key)):
        p = os.path.join(d, fn)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(b)
    return d


def restore(item_id, pw):
    """下载 → 解密 → 校验 → 本地快照 → 替换 db + key（保留当前的 OneDrive 绑定）→ 重新加载。返回 {name, snapshot, meta}。"""
    meta, blob = download(item_id)
    raw = decrypt_blob(blob, pw)
    dbb, key, bmeta = parse_payload(raw)
    # 校验数据库：能打开、完整、有 accounts 表；用备份里的 key 试解一个账号凭证
    tmp = os.path.join(core.DATA_DIR, f".od-restore-{secrets.token_hex(4)}.db")
    with open(tmp, "wb") as f:
        f.write(dbb)
    src = None
    try:
        src = sqlite3.connect(tmp)
        if (src.execute("PRAGMA integrity_check").fetchone() or ["?"])[0] != "ok":
            raise ODError("备份里的数据库未通过完整性检查", "crypto")
        src.execute("SELECT count(*) FROM accounts").fetchone()
        row = src.execute("SELECT cred_enc FROM accounts LIMIT 1").fetchone()
        if row and row[0]:
            try:
                Fernet(key).decrypt(row[0].encode())
            except Exception:   # noqa: BLE001
                raise ODError("备份里的 fernet.key 与数据库不匹配", "crypto")
        with _lock:
            keep = {k: core.get_setting(k) for k in RESTORE_PRESERVE}
            keep_sec = {k: core.get_secret_setting(k, None) for k in RESTORE_PRESERVE_SECRET}
            cur_pw, cur_cfg = password(), core.get_setting(K_CFG)
            snap = local_snapshot()
            with core.db() as c:
                src.backup(c)
            fd = os.open(core.KEY_PATH + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
            os.replace(core.KEY_PATH + ".new", core.KEY_PATH)
            os.chmod(core.KEY_PATH, 0o600)
            core._fernet = None
            core.migrate()
            # 当前机器上正在用的绑定优先（refresh token 可能已轮换）；密码：当前没设就用这次恢复的密码
            for k, v in keep.items():
                if v not in (None, ""):
                    core.set_setting(k, v)
            for k, v in keep_sec.items():
                if v:
                    core.set_secret_setting(k, v)
            core.set_secret_setting(K_PENDING, "")
            # 快照是在备份任务运行中拍的，备份里那条 onedrive_backup 任务一定是 running：标成已完成，免得挡住后续备份
            core.ex("UPDATE tasks SET status='done', message=? WHERE type='onedrive_backup' AND status='running'",
                    ("（来自恢复的备份）这次备份正是被恢复的那一份",))
            core.set_secret_setting(K_PW, cur_pw or pw)
            if not core.get_setting(K_CFG) and cur_cfg:
                core.set_setting(K_CFG, cur_cfg)
            set_state(slot=slot_key(cfg(), now_local()), slot_tries=0, last_restore=int(time.time()),
                      last_restore_file=meta.get("name"))
    finally:
        if src is not None:
            src.close()
        if os.path.exists(tmp):
            os.remove(tmp)
    return {"name": meta.get("name"), "snapshot": snap, "meta": bmeta}


# 恢复后重启：Docker（restart 策略）里退出进程让容器被拉起，彻底重载后台循环与缓存。测试替换 _exit。
_exit = os._exit
RESTART_CODE = 75


def restart_enabled():
    v = os.environ.get("TRICLOUD_RESTART_AFTER_RESTORE")
    if v is not None:
        return v.strip().lower() in ("1", "true", "yes")
    return os.path.exists("/.dockerenv")


def schedule_restart(delay=1.5):
    t = threading.Timer(delay, lambda: _exit(RESTART_CODE))
    t.daemon = True
    t.start()
    return t


# ---------------- 定时 ----------------
def _hm(c):
    h, m = (c.get("time") or "03:30").split(":")
    return int(h), int(m)


def slot_dt(c, now):
    """当前所在这一期的计划时间（≤ now 的最近一次）。"""
    h, m = _hm(c)
    s = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if c.get("freq") == "weekly":
        s -= dt.timedelta(days=(now.weekday() - int(c.get("weekday") or 0)) % 7)
        if s > now:
            s -= dt.timedelta(days=7)
    elif s > now:
        s -= dt.timedelta(days=1)
    return s


def slot_key(c, now):
    return slot_dt(c, now).strftime("%Y-%m-%d %H:%M")


def next_run(c, now):
    s = slot_dt(c, now)
    return s + dt.timedelta(days=7 if c.get("freq") == "weekly" else 1)


RETRY_MAX, RETRY_GAP = 3, 3600


def due(now):
    """调度器每分钟调用：该跑返回 slot key，否则 None。失败的一期最多再试到 3 次（间隔 ≥1 小时）。"""
    c = cfg()
    if not c["enabled"] or not bound() or not password():
        return None
    key = slot_key(c, now)
    s = state()
    if not s.get("slot"):            # 第一次：从当前这一期开始算，不立刻补跑
        set_state(slot=key, slot_tries=0)
        return None
    if s.get("slot") != key:
        return key
    if s.get("last_result") == "failed" and s.get("failed_slot") == key and int(s.get("slot_tries") or 0) < RETRY_MAX \
            and time.time() - int(s.get("last_try") or 0) >= RETRY_GAP:
        return key
    return None


def mark_try(key):
    s = state()
    tries = int(s.get("slot_tries") or 0) + 1 if s.get("slot") == key else 1
    set_state(slot=key, slot_tries=tries, last_try=int(time.time()))


def status_view():
    c = cfg()
    s = state()
    t = token() or {}
    now = now_local()
    ready = bound() and bool(password()) and c["enabled"]
    nr = next_run(c, now) if ready else None
    return {"client_id": client_id(), "tenant": tenant(), "scope": SCOPE, "bound": bound(), "account": t.get("account") or {},
            "pending": pending_view(), "password_set": bool(password()), "cfg": c, "ready": ready,
            "next_run": nr.strftime("%Y-%m-%d %H:%M") if nr else None, "timezone": str(now.tzinfo),
            "state": {k: s.get(k) for k in ("last_ok", "last_file", "last_size", "last_error", "last_result", "last_try",
                                            "last_trigger", "auth_error", "last_restore", "last_restore_file", "bound_at")},
            "device_login_url": DEVICE_LOGIN_URL, "restart_after_restore": restart_enabled()}


def status_text():
    """TG /backup 用的状态文字（纯文本，调用方转义）。"""
    v = status_view()
    s = v["state"]
    lines = [f"绑定：{'已绑定' if v['bound'] else '未绑定'}" + (f"（{v['account'].get('folder')}）" if v["account"].get("folder") else ""),
             f"备份密码：{'已设置' if v['password_set'] else '未设置'}"]
    c = v["cfg"]
    plan = ("每天 " if c["freq"] == "daily" else f"每周{WEEKDAYS[int(c['weekday'])][1:]} ") + c["time"]
    lines.append(f"计划：{plan}（{v['timezone']}），保留 {c['keep']} 份，{'已启用' if c['enabled'] else '已停用'}")
    if v["next_run"]:
        lines.append(f"下次：{v['next_run']}")
    if s.get("last_ok"):
        lines.append(f"上次成功：{dt.datetime.fromtimestamp(s['last_ok'], now_local().tzinfo):%Y-%m-%d %H:%M} {s.get('last_file') or ''}"
                     + (f"（{(s.get('last_size') or 0) / 1024:.1f} KB）" if s.get("last_size") else ""))
    if s.get("last_result") == "failed" and s.get("last_error"):
        lines.append(f"上次失败：{s['last_error'][:150]}")
    if s.get("auth_error"):
        lines.append(s["auth_error"])
    return "\n".join(lines)
