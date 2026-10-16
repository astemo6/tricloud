"""build 21 OneDrive 定期备份：设备码绑定、加密格式、上传（小文件 PUT / 大文件 upload session）、保留 N 份、定时、
立即备份任务、失败 TG、恢复（本地快照 + 替换 db/key + 保留当前绑定 + 重启）、解绑、API Token 403、TG /backup、离线解密工具。
Microsoft 登录与 Graph 全部用 httpx.MockTransport 假服务器，不连接任何真实服务。"""
import asyncio
import datetime as dt
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from urllib.parse import parse_qs, unquote

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123", TRICLOUD_RESTART_AFTER_RESTORE="1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from app import core, main, onedrive, security, services, tasks, telegram
from app.routers import onedrive as rod

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


async def noop():
    await asyncio.sleep(3600)


for f in ("task_loop", "monitor_loop", "schedule_loop"):
    setattr(tasks, f, noop)
telegram.poll_loop = noop
SENT = []


async def fake_send(text, *a, **kw):
    SENT.append(text)
    return True
telegram.send = fake_send
onedrive._sleep = lambda s: None
EXITS = []
onedrive._exit = lambda code: EXITS.append(code)

CID = "11111111-2222-3333-4444-555555555555"


# ---------------- 假 Microsoft 登录 + Graph ----------------
class Fake:
    def __init__(self):
        self.files = {}          # name -> {"id", "data", "created"}
        self.sessions = {}
        self.poll = []           # 设备码轮询依次返回的结果
        self.reqs = []
        self.rt_n = 0
        self.refresh_error = None
        self.fail_put = 0        # 前 n 次 PUT 返回 503
        self.fail_upload = False
        self.chunk_ranges = []
        self.devicecode_error = None
        self.scopes = []
        self.next_id = 1

    def new_rt(self):
        self.rt_n += 1
        return f"rt-{self.rt_n}"

    def handler(self, req: httpx.Request):
        u = req.url
        self.reqs.append((req.method, str(u), dict(req.headers)))
        host, path = u.host, unquote(u.path)
        if host == "login.microsoftonline.com":
            form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            if "scope" in form:
                self.scopes.append(form["scope"])
            if path.endswith("/devicecode"):
                if self.devicecode_error:
                    return httpx.Response(400, json=self.devicecode_error)
                return httpx.Response(200, json={"device_code": "DEV-CODE", "user_code": "ABCD-EFGH", "verification_uri": "https://microsoft.com/devicelogin",
                                                 "expires_in": 900, "interval": 5, "message": "..."})
            if path.endswith("/token"):
                if form.get("grant_type") == "urn:ietf:params:oauth:grant-type:device_code":
                    r = self.poll.pop(0) if self.poll else "ok"
                    if r == "ok":
                        return httpx.Response(200, json={"access_token": "at-1", "refresh_token": self.new_rt(), "expires_in": 3600, "scope": "Files.ReadWrite.AppFolder"})
                    return httpx.Response(400, json={"error": r, "error_description": "AADSTS: " + r})
                if form.get("grant_type") == "refresh_token":
                    if self.refresh_error:
                        return httpx.Response(400, json={"error": self.refresh_error, "error_description": "AADSTS70000: bad"})
                    self.last_refresh_rt = form.get("refresh_token")
                    return httpx.Response(200, json={"access_token": "at-r", "refresh_token": self.new_rt(), "expires_in": 3600})
            return httpx.Response(404, json={"error": "nf"})
        if host == "upload.example":
            if "authorization" in {k.lower() for k in req.headers}:
                return httpx.Response(400, json={"error": {"code": "auth_header_not_allowed"}})
            sid = path.rsplit("/", 1)[-1]
            s = self.sessions[sid]
            if req.method == "DELETE":
                self.sessions.pop(sid, None)
                return httpx.Response(204)
            if self.fail_upload:
                return httpx.Response(400, json={"error": {"code": "invalidRange", "message": "bad"}})
            rng = req.headers["content-range"]
            self.chunk_ranges.append(rng)
            a, b, tot = map(int, re.match(r"bytes (\d+)-(\d+)/(\d+)", rng).groups())
            assert a == len(s["data"]) and b - a + 1 == len(req.content)
            s["data"] += req.content
            if len(s["data"]) == tot:
                it = self._put(s["name"], bytes(s["data"]))
                return httpx.Response(201, json=it)
            return httpx.Response(202, json={"nextExpectedRanges": [f"{len(s['data'])}-"]})
        if host == "graph.microsoft.com":
            if req.headers.get("authorization", "")[:7] != "Bearer ":
                return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})
            p = path[len("/v1.0"):]
            if p == "/me/drive/special/approot" and req.method == "GET":
                return httpx.Response(200, json={"id": "ROOT", "name": "TriCloud Backup", "parentReference": {"driveType": "personal"}})
            m = re.match(r"^/me/drive/special/approot:/(.+):/content$", p)
            if m and req.method == "PUT":
                if self.fail_put > 0:
                    self.fail_put -= 1
                    return httpx.Response(503, headers={"Retry-After": "1"}, json={"error": {"code": "serviceNotAvailable", "message": "busy"}})
                return httpx.Response(201, json=self._put(m[1], req.content))
            m = re.match(r"^/me/drive/special/approot:/(.+):/createUploadSession$", p)
            if m and req.method == "POST":
                sid = f"s{len(self.sessions) + 1}"
                self.sessions[sid] = {"name": m[1], "data": bytearray()}
                self.session_body = json.loads(req.content)
                return httpx.Response(200, json={"uploadUrl": f"https://upload.example/up/{sid}"})
            if p == "/me/drive/special/approot/children" and req.method == "GET":
                items = [{"id": v["id"], "name": k, "size": len(v["data"]), "createdDateTime": v["created"], "file": {}} for k, v in sorted(self.files.items())]
                items.append({"id": "FOLDER", "name": "tricloud-backup-20200101-000000.tcod", "folder": {}})   # 文件夹不算
                skip = int(parse_qs(u.query.decode()).get("skip", ["0"])[0])
                page = items[skip:skip + 3]
                j = {"value": page}
                if skip + 3 < len(items):
                    j["@odata.nextLink"] = f"https://graph.microsoft.com/v1.0/me/drive/special/approot/children?skip={skip + 3}"
                return httpx.Response(200, json=j)
            m = re.match(r"^/me/drive/items/([^/]+)(/content)?$", p)
            if m:
                name = next((k for k, v in self.files.items() if v["id"] == m[1]), None)
                if req.method == "DELETE":
                    if name:
                        self.files.pop(name)
                        return httpx.Response(204)
                    return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
                if not name:
                    return httpx.Response(404, json={"error": {"code": "itemNotFound", "message": "nf"}})
                if m[2]:
                    return httpx.Response(302, headers={"Location": f"https://dl.example/{m[1]}"})
                return httpx.Response(200, json={"id": m[1], "name": name, "size": len(self.files[name]["data"])})
        if host == "dl.example":
            if "authorization" in {k.lower() for k in req.headers}:
                return httpx.Response(400)
            fid = path.rsplit("/", 1)[-1]
            name = next(k for k, v in self.files.items() if v["id"] == fid)
            return httpx.Response(200, content=self.files[name]["data"])
        return httpx.Response(404)

    def _put(self, name, data):
        fid = self.files.get(name, {}).get("id") or f"ID{self.next_id}"
        self.next_id += 1
        self.files[name] = {"id": fid, "data": bytes(data), "created": "2026-10-16T00:00:00Z"}
        return {"id": fid, "name": name, "size": len(data)}


F = Fake()
onedrive._transport = httpx.MockTransport(F.handler)

c = TestClient(main.app)
c.__enter__()
lr = c.post("/api/login", json={"password": "devpassword123", "client": "app"})
c.cookies.clear()   # 只用 Bearer，便于测未登录 401
H = {"Authorization": "Bearer " + lr.json()["token"]} if lr.status_code == 200 and "token" in lr.json() else {}
if not H:
    H = {}
ok("login", lr.status_code == 200)


def g(p):
    return c.get(p, headers=H)


def post(p, body=None):
    return c.post(p, json=body or {}, headers=H)


# ================= 1. 路由与默认状态 =================
api = [r for r in main.app.routes if getattr(r, "path", "").startswith("/api/onedrive")]
ok("routes: 8 onedrive routes", len(api) == 8)
s = g("/api/onedrive").json()
ok("status: defaults (unbound, daily 03:30, keep 30, enabled, consumers)",
   s["bound"] is False and s["cfg"] == {"enabled": True, "freq": "daily", "time": "03:30", "weekday": 0, "keep": 30}
   and s["tenant"] == "consumers" and s["password_set"] is False and s["next_run"] is None and s["pending"] is None)
ok("status: scope is exactly Files.ReadWrite.AppFolder offline_access", s["scope"] == "Files.ReadWrite.AppFolder offline_access")
ok("status: timezone defaults to Asia/Shanghai", s["timezone"] == "Asia/Shanghai")
r = post("/api/onedrive/bind")
ok("bind without client_id → 400", r.status_code == 400 and "client_id" in r.json()["detail"])

# ================= 2. 设置校验 =================
ok("config: bad client_id 400", post("/api/onedrive/config", {"client_id": "not-a-guid"}).status_code == 400)
ok("config: bad tenant 400", post("/api/onedrive/config", {"tenant": "organizations"}).status_code == 400)
ok("config: bad freq 400", post("/api/onedrive/config", {"freq": "hourly"}).status_code == 400)
ok("config: bad time 400", post("/api/onedrive/config", {"time": "25:00"}).status_code == 400)
ok("config: bad keep 400 (0 / 366 / x)", all(post("/api/onedrive/config", {"keep": v}).status_code == 400 for v in (0, 366, "x")))
ok("config: bad weekday 400", post("/api/onedrive/config", {"weekday": 7}).status_code == 400)
ok("config: whitespace-only password 400 (不能为空)", post("/api/onedrive/config", {"password": "   "}).status_code == 400
   and "不能为空" in post("/api/onedrive/config", {"password": "   "}).json()["detail"])
r0 = post("/api/onedrive/config", {"password": "a", "password2": "a"})
ok("config: 1-char password accepted (no length / complexity rule, build 22)", r0.status_code == 200 and "password" in r0.json()["changed"]
   and onedrive.password() == "a")
ok("format: short password encrypt/decrypt round trip", onedrive.decrypt_blob(onedrive.encrypt_blob(b"x", "a"), "a") == b"x")
ok("config: password mismatch 400", post("/api/onedrive/config", {"password": "abc", "password2": "abd"}).status_code == 400)
r = post("/api/onedrive/config", {"client_id": CID, "tenant": "consumers", "password": "correct horse battery", "keep": 3})
j = r.json()
ok("config: saved client_id / password / keep", r.status_code == 200 and j["client_id"] == CID and j["password_set"] and j["cfg"]["keep"] == 3
   and "password" in j["changed"])
row = core.q("SELECT v FROM settings WHERE k='onedrive_password'", one=True)
ok("password stored Fernet-encrypted (no plaintext in DB)", row and "correct horse" not in row["v"] and core.decrypt(json.loads(row["v"])) == "correct horse battery")
ok("status never returns password", "correct horse" not in json.dumps(g("/api/onedrive").json()))

# ================= 3. 设备码绑定 =================
r = post("/api/onedrive/bind")
j = r.json()
ok("bind: device code returned (user_code + devicelogin url + interval)", r.status_code == 200 and j["user_code"] == "ABCD-EFGH"
   and j["verification_uri"] == "https://microsoft.com/devicelogin" and j["interval"] == 5 and "device_code" not in j)
ok("bind: requested scope only AppFolder + offline_access", F.scopes and all(sc == "Files.ReadWrite.AppFolder offline_access" for sc in F.scopes))
ok("bind: consumers endpoint used", any("login.microsoftonline.com/consumers/oauth2/v2.0/devicecode" in u for _, u, _h in F.reqs))
ok("status shows pending (no device_code leak)", g("/api/onedrive").json()["pending"]["user_code"] == "ABCD-EFGH" and "DEV-CODE" not in g("/api/onedrive").text)
F.poll = ["authorization_pending", "slow_down", "ok"]
n_audit = core.q("SELECT COUNT(*) n FROM audit", one=True)["n"]
p1 = post("/api/onedrive/bind/poll").json()
p2 = post("/api/onedrive/bind/poll").json()
ok("poll: pending then slow_down (+5s interval)", p1["status"] == "pending" and p2["status"] == "slow_down" and p2["interval"] == 10)
p3 = post("/api/onedrive/bind/poll").json()
ok("poll: ok → bound, folder name from approot", p3["status"] == "ok" and p3["account"].get("folder") == "TriCloud Backup")
s = g("/api/onedrive").json()
ok("status: bound + ready + next_run + pending cleared", s["bound"] and s["ready"] and s["next_run"] and s["pending"] is None)
tok_row = core.q("SELECT v FROM settings WHERE k='onedrive_token'", one=True)["v"]
ok("refresh token stored Fernet-encrypted", "rt-1" not in tok_row and core.decrypt(json.loads(tok_row))["refresh_token"] == "rt-1")
acts = [a["action"] for a in core.q("SELECT action FROM audit ORDER BY id")]
ok("poll requests not audited each time; bind success audited once", acts.count("onedrive-bind") == 1 and not any("bind/poll" in a for a in acts))
# 拒绝 / 过期
post("/api/onedrive/bind")
F.poll = ["authorization_declined"]
ok("poll: declined", post("/api/onedrive/bind/poll").json()["status"] == "declined")
post("/api/onedrive/bind")
F.poll = ["expired_token"]
ok("poll: expired", post("/api/onedrive/bind/poll").json()["status"] == "expired")
post("/api/onedrive/bind")
core.set_secret_setting("onedrive_pending", dict(core.get_secret_setting("onedrive_pending"), expires_at=int(time.time()) - 1))
ok("poll: locally expired pending", post("/api/onedrive/bind/poll").json()["status"] == "expired")
ok("still bound after failed re-bind attempts", onedrive.bound())
F.devicecode_error = {"error": "unauthorized_client", "error_description": "AADSTS7000218: public client"}
r = post("/api/onedrive/bind")
ok("bind: public client flow disabled → friendly hint", r.status_code == 400 and "允许公共客户端流" in r.json()["detail"])
F.devicecode_error = {"error": "invalid_client", "error_description": "AADSTS700016: not found"}
ok("bind: invalid client → hint about personal accounts", "个人 Microsoft" in post("/api/onedrive/bind").json()["detail"])
F.devicecode_error = None

# ================= 4. 加密格式 =================
blob = onedrive.encrypt_blob(b"hello world" * 100, "correct horse battery")
ok("format: magic TCOD1 + header 37 bytes + scrypt N=2^15 r=8 p=1", blob[:5] == b"TCOD1" and blob[5:9] == bytes([1, 15, 8, 1]) and len(blob) == 37 + 1100 + 16)
ok("format: decrypt roundtrip", onedrive.decrypt_blob(blob, "correct horse battery") == b"hello world" * 100)
for bad, label in ((lambda b: b[:40] + bytes([b[40] ^ 1]) + b[41:], "ciphertext"), (lambda b: b[:10] + bytes([b[10] ^ 1]) + b[11:], "salt/header")):
    try:
        onedrive.decrypt_blob(bad(blob), "correct horse battery")
        ok(f"format: tampered {label} rejected", False)
    except onedrive.ODError as e:
        ok(f"format: tampered {label} rejected", "密码错误或文件已损坏" in str(e))
try:
    onedrive.decrypt_blob(blob, "wrong password!!")
    ok("format: wrong password rejected", False)
except onedrive.ODError as e:
    ok("format: wrong password rejected", "密码错误" in str(e))
try:
    onedrive.decrypt_blob(b"TCBK1" + b"x" * 80, "x")
    ok("format: other magic rejected", False)
except onedrive.ODError:
    ok("format: other magic rejected", True)
ok("format: two encryptions differ (random salt + nonce)", onedrive.encrypt_blob(b"a", "correct horse battery") != onedrive.encrypt_blob(b"a", "correct horse battery"))

# ================= 5. 立即备份（任务）+ 小文件 PUT =================
core.ex("INSERT INTO accounts(provider,name,region,cred_enc,created) VALUES('aws','A1','us-east-1',?,?)",
        (core.encrypt({"access_key": "AKIAOLD", "secret_key": "s", "region": "us-east-1"}), int(time.time())))


def run_task(tid):
    t = core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)
    asyncio.run(tasks._dispatch(t))
    return core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)


r = post("/api/onedrive/backup")
tid = r.json().get("task_id")
ok("backup now: task created (account_id 0, type onedrive_backup)", r.status_code == 200 and tid
   and core.q("SELECT type, account_id FROM tasks WHERE id=?", (tid,), one=True) == {"type": "onedrive_backup", "account_id": 0})
ok("backup now: second call while running → 409", post("/api/onedrive/backup").status_code == 409)
SENT.clear()
t = run_task(tid)
ok("backup task done, message names file", t["status"] == "done" and "tricloud-backup-" in t["message"], )
names = sorted(F.files)
ok("uploaded one .tcod with timestamp name to approot", len(names) == 1 and re.match(r"^tricloud-backup-\d{8}-\d{6}\.tcod$", names[0]))
ok("small file used simple PUT (no upload session)", not F.sessions and any(m == "PUT" and "approot:/tricloud-backup-" in u for m, u, _h in F.reqs))
ok("success: audit onedrive-backup written", core.q("SELECT 1 FROM audit WHERE action='onedrive-backup'", one=True) is not None)
ok("success (manual): no TG message", not SENT)
st = onedrive.state()
ok("state: last_ok / last_file / last_size", st["last_result"] == "done" and st["last_file"] == names[0] and st["last_size"] == len(F.files[names[0]]["data"]))
logs = " ".join(x["msg"] for x in tasks.get_logs(tid))
ok("task log: snapshot / encrypt / upload lines", "SQLite backup API" in logs and "AES-256-GCM" in logs and "上传完成" in logs)
tk = c.get(f"/api/tasks/{tid}", headers=H).json()
ok("task detail: type_name OneDrive 备份, account_name null", tk["type_name"] == "OneDrive 备份" and tk["account_name"] is None)
# 内容可解：db + key + meta，且 db 是一致快照（含刚插入的账号）
raw = onedrive.decrypt_blob(F.files[names[0]]["data"], "correct horse battery")
z = zipfile.ZipFile(io.BytesIO(raw))
ok("payload zip: tricloud.db + fernet.key + meta.json", set(z.namelist()) == {"tricloud.db", "fernet.key", "meta.json"})
ok("payload: fernet.key equals data/fernet.key", z.read("fernet.key") == open(core.KEY_PATH, "rb").read().strip())
tmpdb = os.path.join(D, "chk.db")
open(tmpdb, "wb").write(z.read("tricloud.db"))
ok("payload: db snapshot opens and contains account A1", sqlite3.connect(tmpdb).execute("SELECT name FROM accounts").fetchall() == [("A1",)])
ok("no leftover snapshot temp files in data/", not [f for f in os.listdir(D) if f.startswith(".od-")])

# ================= 6. 大文件 upload session（>4MB），不带 Authorization =================
big = os.urandom(9 * 1024 * 1024)
it = onedrive.upload("tricloud-backup-20261001-010101.tcod", big)
ok("upload session used for >4MB", F.sessions and F.files["tricloud-backup-20261001-010101.tcod"]["data"] == big and it["size"] == len(big))
ok("upload session conflictBehavior replace", F.session_body == {"item": {"@microsoft.graph.conflictBehavior": "replace"}})
ok("chunks are multiples of 320 KiB (except last)", all((int(r.split("-")[1].split("/")[0]) - int(r.split()[1].split("-")[0]) + 1) % (320 * 1024) == 0
                                                         for r in F.chunk_ranges[:-1]) and len(F.chunk_ranges) == 3)
ok("uploadUrl requests carry no Authorization header", not any(u.startswith("https://upload.example") and "authorization" in {k.lower() for k in h}
                                                               for m, u, h in F.reqs))
F.fail_upload = True
try:
    onedrive.upload("tricloud-backup-20261001-020202.tcod", big)
    ok("failed chunk → error + session cancelled", False)
except onedrive.ODError:
    ok("failed chunk → error + session cancelled", any(m == "DELETE" and u.startswith("https://upload.example") for m, u, _h in F.reqs))
F.fail_upload = False
# 503 重试
F.fail_put = 2
onedrive.upload("tricloud-backup-20261001-030303.tcod", b"x" * 10)
ok("PUT 503 retried (Retry-After) then success", "tricloud-backup-20261001-030303.tcod" in F.files)

# ================= 7. 列表 + 保留 N 份 =================
F.files["notes.txt"] = {"id": "OTHER", "data": b"keep me", "created": "x"}
for i in range(5):
    F._put(f"tricloud-backup-2026090{i + 1}-000000.tcod", b"old")
lst = g("/api/onedrive/backups").json()
ok("list: only TriCloud .tcod files (no folder / other file), newest first, pagination followed",
   [x["name"] for x in lst["items"]] == sorted([n for n in F.files if n.startswith("tricloud-backup-")], reverse=True)
   and all("time" in x and "size" in x for x in lst["items"]) and lst["keep"] == 3)
ok("list: time parsed from name", lst["items"][-1]["time"] == "2026-09-01 00:00:00")
gone = onedrive.prune(3)
left = sorted(n for n in F.files if n.startswith("tricloud-backup-"))
ok("prune: keep newest 3 by timestamp, others deleted", len(left) == 3 and left == sorted(left)[-3:] and len(gone) == 5 and not set(gone) & set(left))
ok("prune: never touches other files", "notes.txt" in F.files)
r = post("/api/onedrive/backup")
run_task(r.json()["task_id"])
ok("backup task applies keep=3 after upload", len([n for n in F.files if n.startswith("tricloud-backup-")]) == 3)

# ================= 8. 失败：TG 通知、状态、不重复推送 =================
SENT.clear()
F.refresh_error = "invalid_grant"
onedrive._access.update(token=None, exp=0)
r = post("/api/onedrive/backup")
t = run_task(r.json()["task_id"])
ok("failure: task failed with re-bind hint", t["status"] == "failed" and "重新绑定" in t["message"])
ok("failure: exactly one TG message 'OneDrive 备份失败'", len(SENT) == 1 and "OneDrive 备份失败" in SENT[0])
ok("failure: state last_result failed + auth_error", onedrive.state()["last_result"] == "failed" and onedrive.state().get("auth_error"))
ok("status shows auth_error", g("/api/onedrive").json()["state"]["auth_error"])
F.refresh_error = None
# token 轮换后保存新 refresh token
onedrive._access.update(token=None, exp=0)
onedrive.list_backups()
ok("refresh token rotated and re-saved encrypted", onedrive.token()["refresh_token"] == f"rt-{F.rt_n}" and F.last_refresh_rt != onedrive.token()["refresh_token"])
ok("auth_error cleared after successful refresh", not onedrive.state().get("auth_error"))

# ================= 9. 定时 =================
TZ = services.tz()
c0 = {"enabled": True, "freq": "daily", "time": "03:30", "weekday": 0, "keep": 30}
n1 = dt.datetime(2026, 10, 16, 2, 0, tzinfo=TZ)
ok("slot daily before time → yesterday 03:30", onedrive.slot_key(c0, n1) == "2026-10-15 03:30")
ok("slot daily after time → today 03:30", onedrive.slot_key(c0, dt.datetime(2026, 10, 16, 4, 0, tzinfo=TZ)) == "2026-10-16 03:30")
ok("next_run daily", onedrive.next_run(c0, n1).strftime("%Y-%m-%d %H:%M") == "2026-10-16 03:30")
cw = dict(c0, freq="weekly", weekday=0)   # 周一
fri = dt.datetime(2026, 10, 16, 12, 0, tzinfo=TZ)   # 2026-10-16 是周五
ok("slot weekly → last Monday 03:30", onedrive.slot_key(cw, fri) == "2026-10-12 03:30")
ok("next_run weekly → next Monday", onedrive.next_run(cw, fri).strftime("%Y-%m-%d") == "2026-10-19")
ok("slot weekly on the day before time → previous week", onedrive.slot_key(cw, dt.datetime(2026, 10, 19, 3, 0, tzinfo=TZ)) == "2026-10-12 03:30")
core.set_setting("onedrive_state", {})
core.set_setting("onedrive_cfg", c0)
ok("due: first call only initialises slot (no catch-up)", onedrive.due(n1) is None and onedrive.state()["slot"] == "2026-10-15 03:30")
ok("due: same slot → None", onedrive.due(dt.datetime(2026, 10, 16, 3, 0, tzinfo=TZ)) is None)
k = onedrive.due(dt.datetime(2026, 10, 16, 3, 31, tzinfo=TZ))
ok("due: new slot after 03:30 → key", k == "2026-10-16 03:30")
onedrive.mark_try(k)
onedrive.set_state(last_result="failed", failed_slot=k)
ok("due: failed slot not retried within 1h", onedrive.due(dt.datetime(2026, 10, 16, 3, 40, tzinfo=TZ)) is None)
onedrive.set_state(last_try=int(time.time()) - 3700)
ok("due: failed slot retried after 1h", onedrive.due(dt.datetime(2026, 10, 16, 4, 40, tzinfo=TZ)) == k)
onedrive.set_state(failed_slot="2026-10-15 03:30")
ok("due: failure of another slot (e.g. manual / old period) not retried", onedrive.due(dt.datetime(2026, 10, 16, 4, 40, tzinfo=TZ)) is None)
onedrive.set_state(failed_slot=k, slot_tries=3)
ok("due: max 3 tries per slot", onedrive.due(dt.datetime(2026, 10, 16, 6, 0, tzinfo=TZ)) is None)
core.set_setting("onedrive_cfg", dict(c0, enabled=False))
ok("due: disabled → None", onedrive.due(dt.datetime(2026, 10, 17, 6, 0, tzinfo=TZ)) is None)
core.set_setting("onedrive_cfg", c0)
post("/api/onedrive/config", {"freq": "weekly", "weekday": 2, "time": "05:00"})
ok("config change resets slot to current period (no immediate run)", onedrive.due(services.now_local()) is None)
s = g("/api/onedrive").json()
ok("status next_run weekly Wednesday 05:00", s["next_run"] and dt.date.fromisoformat(s["next_run"][:10]).weekday() == 2 and s["next_run"].endswith("05:00"))
post("/api/onedrive/config", {"freq": "daily", "time": "03:30"})
# 调度器循环里的一段：due → 建任务（真实 schedule_loop 片段只跑一轮）
ok("schedule_loop wired to onedrive.due + create_task onedrive_backup",
   "onedrive.due(now)" in open(os.path.join(ROOT, "app", "tasks.py"), encoding="utf-8").read()
   and 'create_task("onedrive_backup", 0, {"name": "OneDrive 备份", "trigger": "schedule"})' in open(os.path.join(ROOT, "app", "tasks.py"), encoding="utf-8").read())
ok("task registry has onedrive_backup, NO_ACCOUNT_TYPES", "onedrive_backup" in tasks.ONCE_HANDLERS and tasks.NO_ACCOUNT_TYPES == {"onedrive_backup"})
# 定时失败的 TG 文案带重试说明
SENT.clear()
F.fail_put = 99
tid = tasks.create_task("onedrive_backup", 0, {"name": "OneDrive 备份", "trigger": "schedule"})
onedrive.mark_try(onedrive.slot_key(onedrive.cfg(), services.now_local()))
run_task(tid)
F.fail_put = 0
ok("schedule failure TG mentions 定时 + retry", SENT and "定时" in SENT[-1] and "重试" in SENT[-1])

# ================= 10. API Token 规则 =================
tok_full = security.new_api_token("bot", "full")
TH = {"Authorization": "Bearer " + tok_full}
ok("token: GET status 200", c.get("/api/onedrive", headers=TH).status_code == 200)
ok("token: GET backups 200", c.get("/api/onedrive/backups", headers=TH).status_code == 200)
r = c.post("/api/onedrive/backup", headers=TH)
ok("token: backup now allowed", r.status_code == 200)
run_task(r.json()["task_id"])
ok("token: restore 403", c.post("/api/onedrive/restore", json={"item_id": "x", "password": "y", "confirm": True}, headers=TH).status_code == 403)
ok("token: unbind 403", c.delete("/api/onedrive/bind?confirm=true", headers=TH).status_code == 403)
ok("token: bind / config / poll 403", all(c.post(p, json={}, headers=TH).status_code == 403 for p in ("/api/onedrive/bind", "/api/onedrive/config", "/api/onedrive/bind/poll")))
ok("token: still bound after 403s", onedrive.bound())
ok("unauthenticated 401", c.get("/api/onedrive").status_code == 401 and c.post("/api/onedrive/restore", json={}).status_code == 401)

# ================= 11. TG /backup =================
txt = telegram.backup_command("status")
ok("tg /backup status: bound + plan + keep, no task created", "已绑定" in txt and "每天 03:30" in txt and "保留 30 份" in txt)
n_before = core.q("SELECT COUNT(*) n FROM tasks WHERE type='onedrive_backup'", one=True)["n"]
txt = telegram.backup_command("")
ok("tg /backup: starts a task + shows status", "已开始备份" in txt and core.q("SELECT COUNT(*) n FROM tasks WHERE type='onedrive_backup'", one=True)["n"] == n_before + 1)
txt2 = telegram.backup_command("")
ok("tg /backup while running: says already running", "已有备份在运行" in txt2)
SENT.clear()
run_task(rod.running_task())
ok("tg-triggered success sends completion message", SENT and "OneDrive 备份完成" in SENT[-1])
ok("tg HELP lists /backup", "/backup" in telegram.HELP)


class FakeBot:
    def __init__(self):
        self.out = []

    async def call(self, method, body):
        self.out.append(body.get("text", ""))
        return {"ok": True, "result": {"message_id": 1}}


bot = FakeBot()
asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "/backup status"}))
ok("tg handle_message routes /backup", bot.out and "OneDrive 备份" in bot.out[-1])

# ================= 12. 恢复 =================
# 制造「备份时」的数据：账号 A1；之后改成 A2 + 换 key 的效果用不同账号名体现
post("/api/onedrive/backup")
run_task(rod.running_task())
bk = g("/api/onedrive/backups").json()["items"][0]
core.ex("UPDATE accounts SET name='CHANGED-AFTER-BACKUP'")
core.ex("INSERT INTO accounts(provider,name,region,cred_enc,created) VALUES('oci','NEW',NULL,?,?)", (core.encrypt({"x": 1}), int(time.time())))
cur_rt = onedrive.token()["refresh_token"]
ok("restore: confirm required", post("/api/onedrive/restore", {"item_id": bk["id"], "password": "correct horse battery"}).status_code == 400)
ok("restore: password required", post("/api/onedrive/restore", {"item_id": bk["id"], "confirm": True}).status_code == 400)
r = post("/api/onedrive/restore", {"item_id": bk["id"], "password": "wrong password!!", "confirm": True})
ok("restore: wrong password → 400, data untouched", r.status_code == 400 and "密码错误" in r.json()["detail"]
   and core.q("SELECT COUNT(*) n FROM accounts", one=True)["n"] == 2)
ok("restore: wrong password → no local snapshot made", not [f for f in os.listdir(D) if f.startswith("pre-restore-")])
ok("restore: unknown item → 400", post("/api/onedrive/restore", {"item_id": "NOPE", "password": "x", "confirm": True}).status_code == 400)
EXITS.clear()
old_key = open(core.KEY_PATH, "rb").read()
r = post("/api/onedrive/restore", {"item_id": bk["id"], "password": "correct horse battery", "confirm": True})
j = r.json()
ok("restore: 200 + restart flag + snapshot name", r.status_code == 200 and j["restart"] is True and j["snapshot"].startswith("pre-restore-") and j["name"] == bk["name"])
snapdir = os.path.join(D, j["snapshot"])
ok("restore: local pre-restore snapshot has db + key (0600, dir 0700)", os.path.isfile(os.path.join(snapdir, "tricloud.db"))
   and open(os.path.join(snapdir, "fernet.key"), "rb").read().strip() == old_key.strip()
   and oct(os.stat(os.path.join(snapdir, "tricloud.db")).st_mode & 0o777) == "0o600" and oct(os.stat(snapdir).st_mode & 0o777) == "0o700")
ok("restore: pre-restore snapshot contains the pre-restore data", sorted(x[0] for x in sqlite3.connect(os.path.join(snapdir, "tricloud.db")).execute("SELECT name FROM accounts")) == ["CHANGED-AFTER-BACKUP", "NEW"])
ok("restore: db replaced with backup content", [a["name"] for a in core.q("SELECT name FROM accounts")] == ["A1"])
ok("restore: credentials decrypt with restored key", core.get_account(1, with_cred=True)["cred"]["access_key"] == "AKIAOLD")
ok("restore: current OneDrive binding preserved (rotated refresh token kept)", onedrive.bound() and onedrive.token()["refresh_token"] == cur_rt and onedrive.client_id() == CID)
ok("restore: backup password still usable for schedule", onedrive.password() == "correct horse battery")
ok("restore: all sessions dropped (must log in again)", core.q("SELECT COUNT(*) n FROM sessions", one=True)["n"] == 0 and g("/api/onedrive").status_code == 401)
ok("restore: audit onedrive-restore in restored DB", core.q("SELECT 1 FROM audit WHERE action='onedrive-restore'", one=True) is not None)
time.sleep(2)
ok("restore: process exit scheduled (docker restart policy brings it back)", EXITS == [onedrive.RESTART_CODE])
ok("restore: running backup task inside snapshot marked done (doesn't block)", rod.running_task() is None)
ok("restore: no temp files left", not [f for f in os.listdir(D) if f.startswith(".od-")])
lr = c.post("/api/login", json={"password": "devpassword123", "client": "app"})
c.cookies.clear()
H.clear()
H.update({"Authorization": "Bearer " + lr.json()["token"]})
ok("login again after restore works", g("/api/onedrive").status_code == 200)
# 不在 Docker 且未设置环境变量 → 不重启
with mock.patch.dict(os.environ, {}, clear=False):
    os.environ.pop("TRICLOUD_RESTART_AFTER_RESTORE", None)
    with mock.patch("os.path.exists", side_effect=lambda p: False if p == "/.dockerenv" else os.path.isfile(p) or os.path.isdir(p)):
        ok("restart_enabled: false outside docker without env", onedrive.restart_enabled() is False)
    with mock.patch("os.path.exists", side_effect=lambda p: True if p == "/.dockerenv" else os.path.isfile(p) or os.path.isdir(p)):
        ok("restart_enabled: true inside docker", onedrive.restart_enabled() is True)
os.environ["TRICLOUD_RESTART_AFTER_RESTORE"] = "1"
# key 不匹配的备份被拒绝
dbb, key = onedrive.snapshot_files()
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zz:
    zz.writestr("tricloud.db", dbb)
    zz.writestr("fernet.key", __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key())
F._put("tricloud-backup-20991231-235959.tcod", onedrive.encrypt_blob(buf.getvalue(), "correct horse battery"))
bad = next(x for x in g("/api/onedrive/backups").json()["items"] if x["name"] == "tricloud-backup-20991231-235959.tcod")
r = post("/api/onedrive/restore", {"item_id": bad["id"], "password": "correct horse battery", "confirm": True})
ok("restore: backup whose key doesn't match DB → 400, nothing replaced", r.status_code == 400 and "不匹配" in r.json()["detail"]
   and [a["name"] for a in core.q("SELECT name FROM accounts")] == ["A1"])
F._put("tricloud-backup-20991231-235958.tcod", onedrive.encrypt_blob(b"not a zip", "correct horse battery"))
bad = next(x for x in g("/api/onedrive/backups").json()["items"] if x["name"] == "tricloud-backup-20991231-235958.tcod")
ok("restore: corrupt payload → 400", post("/api/onedrive/restore", {"item_id": bad["id"], "password": "correct horse battery", "confirm": True}).status_code == 400)

# ================= 13. 离线解密工具 =================
from tools import decrypt_backup as tool
name = bk["name"]
blob = F.files[name]["data"]
p = os.path.join(D, "dl.tcod")
open(p, "wb").write(blob)
out = os.path.join(D, "out1")
ok("tool: decrypt() matches app format", tool.decrypt(blob, "correct horse battery") == onedrive.decrypt_blob(blob, "correct horse battery"))
r = subprocess.run([sys.executable, "-m", "tools.decrypt_backup", p, "correct horse battery", out], cwd=ROOT, capture_output=True, text=True)
ok("tool: python -m tools.decrypt_backup file password outdir → exit 0 + files", r.returncode == 0 and
   sorted(os.listdir(out)) == ["fernet.key", "meta.json", "tricloud.db"])
ok("tool: output files 0600", all(oct(os.stat(os.path.join(out, f)).st_mode & 0o777) == "0o600" for f in os.listdir(out)))
r = subprocess.run([sys.executable, "-m", "tools.decrypt_backup", p, "wrong password!!", os.path.join(D, "out2")], cwd=ROOT, capture_output=True, text=True)
ok("tool: wrong password → exit 1 + message", r.returncode == 1 and "密码错误" in r.stderr)
r = subprocess.run([sys.executable, "-m", "tools.decrypt_backup", p, os.path.join(D, "out3")], cwd=ROOT, capture_output=True, text=True,
                   env=dict(os.environ, TRICLOUD_BACKUP_PASSWORD="correct horse battery"))
ok("tool: password from env when omitted", r.returncode == 0 and os.path.exists(os.path.join(D, "out3", "tricloud.db")))
r = subprocess.run([sys.executable, "-m", "tools.decrypt_backup", p, "correct horse battery", out], cwd=ROOT, capture_output=True, text=True)
ok("tool: refuses to overwrite existing output", r.returncode == 1 and "已存在" in r.stderr)
tsrc = open(os.path.join(ROOT, "tools", "decrypt_backup.py"), encoding="utf-8").read()
ok("tool: standalone (no app import)", "from app" not in tsrc and "import app" not in tsrc)

# ================= 14. 解绑 / 换 client_id =================
ok("unbind: confirm required", c.delete("/api/onedrive/bind", headers=H).status_code == 400)
r = c.delete("/api/onedrive/bind?confirm=true", headers=H)
ok("unbind: token deleted, files on OneDrive untouched", r.status_code == 200 and not onedrive.bound() and len(F.files) > 0)
ok("unbind: status unbound, next_run none", g("/api/onedrive").json()["bound"] is False and g("/api/onedrive").json()["next_run"] is None)
ok("unbind: list → 400 not bound", g("/api/onedrive/backups").status_code == 400)
ok("unbind: backup now → 400", post("/api/onedrive/backup").status_code == 400)
ok("unbind: cfg / client_id / password kept", onedrive.client_id() == CID and onedrive.password())
post("/api/onedrive/bind")
F.poll = ["ok"]
post("/api/onedrive/bind/poll")
ok("re-bind works", onedrive.bound())
j = post("/api/onedrive/config", {"client_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}).json()
ok("changing client_id unbinds old token", "unbound" in j["changed"] and not onedrive.bound())
post("/api/onedrive/bind")
ok("cancel pending binding (pending_only)", c.delete("/api/onedrive/bind?pending_only=true", headers=H).status_code == 200 and g("/api/onedrive").json()["pending"] is None)
post("/api/onedrive/config", {"tenant": "common"})
post("/api/onedrive/bind")
ok("tenant common uses /common endpoint", any("/common/oauth2/v2.0/devicecode" in u for _, u, _h in F.reqs))
ok("password clear", "password_clear" in post("/api/onedrive/config", {"password_clear": True}).json()["changed"] and not onedrive.password())

# ================= 15. 静态检查：Web / mock / 文档 / App =================
W = open(os.path.join(ROOT, "web", "js", "onedrive.js"), encoding="utf-8").read()
SJ = open(os.path.join(ROOT, "web", "js", "settings.js"), encoding="utf-8").read()
CO = open(os.path.join(ROOT, "web", "js", "core.js"), encoding="utf-8").read()
RT = open(os.path.join(ROOT, "web", "js", "router.js"), encoding="utf-8").read()
M = open(os.path.join(ROOT, "demo", "mock.js"), encoding="utf-8").read()
DOC = open(os.path.join(ROOT, "docs", "api-credentials.md"), encoding="utf-8").read()
ok("web: OneDrive page + settings card + route", "export async function pageOneDrive" in W and 'id="odCard"' in W and "odSettingsCard()" in SJ
   and '"onedrive"' in RT and "#/onedrive" in RT and "pageOneDrive()" in RT)
ok("web: restore = password modal then red confirm", W.index('modal("从 OneDrive 恢复"') < W.index('confirmBox("确认恢复"') and "confirm: true" in W)
ok("web: unbind red confirm + DELETE confirm=true", '"/onedrive/bind?confirm=true", { method: "DELETE" }' in W)
ok("web: build 22 bind button primary + hint + save toast + no ≥10", 'class="btn primary" id="odBind"' in W and "已保存，点「绑定 OneDrive」获取代码" in W
   and "点右边蓝色「绑定 OneDrive」获取代码" in W and "≥10" not in W and "两次输入的备份密码不一致" in W)
ok("docs: step 2 says click blue bind button after save; password no length rule", "保存后点右边蓝色「绑定 OneDrive」按钮，下方弹出代码" in DOC
   and "≥10 位" not in DOC.split("OneDrive 备份")[1])
ok("web: polling stops when leaving page", 'if (!document.getElementById("odPend")) return;' in W)
ok("web: device code + devicelogin link + polling", "/onedrive/bind/poll" in W and "microsoft.com/devicelogin" in W)
ok("web: restore double confirm + password", "/onedrive/restore" in W and W.count("confirmBox(") >= 1 and "备份密码" in W)
ok("web: task type name", "onedrive_backup" in CO or "onedrive_backup" in open(os.path.join(ROOT, "web", "js", "tasks.js"), encoding="utf-8").read())
ok("demo mock: onedrive routes", "/onedrive/bind/poll" in M and "/onedrive/restore" in M and "/onedrive/backups" in M)
ok("docs: Azure app registration tutorial (public client, personal accounts, AppFolder)", "OneDrive 备份" in DOC and "允许公共客户端流" in DOC
   and "个人 Microsoft 帐户" in DOC and "Files.ReadWrite.AppFolder" in DOC)
AJ = open(os.path.join(ROOT, "android", "app", "src", "main", "java", "com", "tricloud", "app", "OneDriveActivity.java"), encoding="utf-8").read()
IS = open(os.path.join(ROOT, "ios", "TriCloud", "OneDrivePage.swift"), encoding="utf-8").read()
for nm, src_ in (("android", AJ), ("ios", IS)):
    ok(f"{nm}: status / bind poll / config / backup / list / restore / unbind endpoints",
       all(x in src_ for x in ("/onedrive", "/onedrive/bind/poll", "/onedrive/config", "/onedrive/backup", "/onedrive/backups", "/onedrive/restore", "confirm=true")))
    ok(f"{nm}: devicelogin link", "microsoft.com/devicelogin" in src_)
    ok(f"{nm}: build 22 bind hint after save + no ≥10 password rule", "已保存，点「绑定 OneDrive」获取代码" in src_ and "≥10" not in src_
       and "两次输入的备份密码不一致" in src_ and "备份密码不能为空" in src_)
c.__exit__(None, None, None)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
