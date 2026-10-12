"""v1.6 自测：绿云 GreenCloud（SolusVM v1 客户 API）。
全部用 httpx.MockTransport 假装 SolusVM 面板，不连接任何真实服务；示例 IP 只用 203.0.113.x / 2001:db8::。
覆盖：地址拼接、类 XML 解析、动作映射、错误处理（SSL / 超时 / HTTP / 非 SolusVM 返回）、凭证不泄露（打码回显 + 打码 PATCH 沿用原值）、
不支持的操作 400、流量守护联动（bw.used / bw.total → 自动关机 + TG 文本）、监控、TG、粘贴识别 / 批量导入、
「启用绿云」开关（/api/meta、列表 / 流量守护 / 监控 / TG 隐藏，数据保留，重新打开恢复）、可拆卸（钩子都标 # greencloud）。"""
import asyncio
import hashlib
import os
import re
import sys
import tempfile
from urllib.parse import parse_qs

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123",
                  AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from app import accounts_import, core, main, services, tasks, telegram, traffic_guard
from app.providers import greencloud_provider as gcp

R = []
core.init_db()


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


async def noop():
    await asyncio.sleep(3600)


for f in ("task_loop", "monitor_loop", "schedule_loop"):
    setattr(tasks, f, noop)
telegram.poll_loop = noop


def raises(fn, *a, text="", exc=Exception, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return text in str(e)
    return False


# ---------------- 假 SolusVM 面板 ----------------
K1, H1 = "ABCDE-FGHIJ-KLMNO", "0123456789abcdef0123456789abcdef01234567"
K2, H2 = "PQRST-UVWXY-Z1234", "89abcdef0123456789abcdef0123456789abcdef"
K3, H3 = "NEWKY-NEWKY-NEWKY", "fedcba9876543210fedcba9876543210fedcba98"
G = 1024 ** 3


class Panel:
    def __init__(self):
        self.vms = {K1: {"hash": H1, "state": "online", "ip": "203.0.113.61", "ips": "203.0.113.61,2001:db8:61::1",
                         "bw": [1000 * G, 384 * G]},
                    K2: {"hash": H2, "state": "offline", "ip": "203.0.113.62", "ips": "203.0.113.62,203.0.113.63",
                         "bw": [500 * G, 100 * G]},
                    K3: {"hash": H3, "state": "online", "ip": "203.0.113.64", "ips": "203.0.113.64", "bw": [100 * G, 1 * G]}}
        self.calls, self.kw, self.urls, self.mode = [], [], [], None

    def handler(self, req):
        self.urls.append(str(req.url))
        f = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        self.calls.append((f.get("key"), f.get("action"), {k: v for k, v in f.items() if k not in ("key", "hash", "action")}))
        if self.mode == "ssl":
            raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
        if self.mode == "timeout":
            raise httpx.ReadTimeout("timed out")
        if self.mode == "http500":
            return httpx.Response(500, text="oops")
        if self.mode == "html":
            return httpx.Response(200, text="<html><body>Login</body></html>")
        if self.mode == "redirect":
            return httpx.Response(302, headers={"location": "/login"})
        vm = self.vms.get(f.get("key"))
        if not vm or vm["hash"] != f.get("hash"):
            return httpx.Response(200, text="<status>error</status><statusmsg>Invalid key or hash</statusmsg>")
        a = f.get("action")
        if a == "boot":
            vm["state"] = "online"
            return httpx.Response(200, text="<status>success</status><statusmsg>booted</statusmsg>")
        if a == "shutdown":
            vm["state"] = "offline"
            return httpx.Response(200, text="<status>success</status><statusmsg>shutdown</statusmsg>")
        if a == "reboot":
            return httpx.Response(200, text="<status>success</status><statusmsg>rebooted</statusmsg>")
        if a == "status":
            return httpx.Response(200, text=f"<status>success</status>\n<statusmsg>{vm['state']}</statusmsg>")
        if a == "info":
            t, u = vm["bw"]
            body = (f"  <STATUS>success</STATUS><statusmsg>{vm['state']}</statusmsg><vmstat>{vm['state']}</vmstat>\n"
                    f"<hostname>vm&amp;1.example.com</hostname><ipaddress>{vm['ip']}</ipaddress><hdd></hdd><mem></mem>")
            if f.get("ipaddr"):
                body += f"<ipaddr>{vm['ips']}</ipaddr>"
            if f.get("bw"):
                body += f"<bw>{t},{u},{t - u},{round(u / t * 100, 2)}</bw>"
            return httpx.Response(200, text=body)
        return httpx.Response(200, text="<status>error</status><statusmsg>Invalid action</statusmsg>")


PANEL = Panel()
_RealClient = httpx.Client


def fake_client(**kw):
    PANEL.kw.append(kw)
    return _RealClient(transport=httpx.MockTransport(PANEL.handler))


mock.patch.object(gcp.httpx, "Client", fake_client).start()
SRV = [{"name": "LA 1", "key": K1, "hash": H1}, {"name": "LA-2", "key": K2, "hash": H2}]
CRED = {"api_url": "https://cp.example.com:5656", "servers": SRV}
ID1 = "gc-" + hashlib.sha1(K1.encode()).hexdigest()[:12]
ID2 = "gc-" + hashlib.sha1(K2.encode()).hexdigest()[:12]

# ================= 1. 地址 / 解析 =================
ok("endpoint: default host", gcp.endpoint("") == "https://cp.greencloudvps.com/api/client/command.php")
ok("endpoint: with port, trailing slash", gcp.endpoint("https://cp.example.com:5656/") == "https://cp.example.com:5656/api/client/command.php")
ok("endpoint: already ends with /api/client -> no duplicate", gcp.endpoint("https://cp.example.com/api/client") == "https://cp.example.com/api/client/command.php")
ok("endpoint: full command.php kept", gcp.endpoint("https://cp.example.com/api/client/command.php") == "https://cp.example.com/api/client/command.php")
ok("endpoint: bare host gets https://", gcp.endpoint("cp.example.com") == "https://cp.example.com/api/client/command.php")
ok("endpoint: http:// refused (key/hash must not go in clear)", raises(gcp.endpoint, "http://cp.example.com", text="https://", exc=ValueError))
d = gcp.parse_reply("junk <STATUS> success </STATUS>\n<statusmsg>online</statusmsg><hostname>a&amp;b</hostname><bw></bw> tail")
ok("parse_reply: case-insensitive tags, trims, unescapes, tolerates junk", d == {"status": "success", "statusmsg": "online", "hostname": "a&b", "bw": ""})
ok("parse_reply: nothing -> {}", gcp.parse_reply("Login page <br> please sign in") == {})
ok("parse_bw: total,used,free,percent", gcp.parse_bw("1000,250,750,25") == {"total": 1000, "used": 250, "free": 750, "percent": 25.0})
ok("parse_bw: percent missing -> computed", gcp.parse_bw("200,50,,")["percent"] == 25.0 and gcp.parse_bw("200,50")["free"] == 150)
ok("parse_bw: empty / garbage -> None", gcp.parse_bw("") is None and gcp.parse_bw(None) is None and gcp.parse_bw(",,,") is None)
ok("state_of: online/offline/other", gcp.state_of({"vmstat": "online"}) == "running" and gcp.state_of({"statusmsg": "offline"}) == "stopped"
   and gcp.state_of({"statusmsg": "weird"}) == "unknown")
sv = gcp.parse_servers_text(f"# comment\nLA 1 {K1} {H1}\n\nLA-2,{K2},{H2}\n")
ok("servers_text: spaces / commas, names with spaces, comments skipped", sv == SRV)
ok("servers_text: bad line reports line number, no secret echo",
   raises(gcp.parse_servers_text, f"ok {K1} {H1}\nonly-two {K2}", text="第 2 行", exc=ValueError)
   and not raises(gcp.parse_servers_text, f"x {K2}", text=K2, exc=ValueError))
ok("normalize: default api_url, servers_text parsed", gcp.normalize_cred({"servers_text": f"a {K1} {H1}"})["api_url"] == gcp.DEFAULT_API_URL)
ok("normalize: duplicate key refused", raises(gcp.normalize_cred, {"servers_text": f"a {K1} {H1}\nb {K1} {H2}"}, text="重复", exc=ValueError))
ok("normalize: illegal characters refused", raises(gcp.normalize_cred, {"servers": [{"name": "a", "key": "k<>y12", "hash": "h" * 10}]}, text="非法", exc=ValueError))

# ================= 2. Provider（mock HTTP） =================
p = gcp.GreenCloudProvider(CRED)
lst = p.list_instances()
a, b = lst
ok("list: id = gc- + sha1(key)[:12], contract fields",
   a["id"] == ID1 and set(a) >= {"id", "name", "state", "public_ip", "ipv6", "ips", "shape", "region", "zone", "hostname", "bw", "created"}
   and a["shape"] == a["region"] == a["zone"] == "-" and a["created"] == "")
ok("list: state / ip / ipv6 split / ips / hostname", a["state"] == "running" and b["state"] == "stopped" and a["public_ip"] == "203.0.113.61"
   and a["ipv6"] == ["2001:db8:61::1"] and b["ips"] == ["203.0.113.62", "203.0.113.63"] and a["hostname"] == "vm&1.example.com")
ok("list: bw bytes {total, used, percent}", a["bw"] == {"total": 1000 * G, "used": 384 * G, "percent": 38.4})
ok("list: info asks ipaddr/bw/status", any(c[1] == "info" and c[2].get("ipaddr") == "true" and c[2].get("bw") == "true" for c in PANEL.calls))
ok("http: POST to command.php, key/hash only in body, SSL verify on",
   all("key=" not in u and "hash=" not in u for u in PANEL.urls) and PANEL.urls[-1] == "https://cp.example.com:5656/api/client/command.php"
   and all(k.get("verify") is True for k in PANEL.kw))
ok("regions -> ['-']", p.regions() == ["-"])
PANEL.calls.clear()
p.action(ID2, "start")
p.action(ID1, "stop")
p.action(ID1, "reboot")
ok("actions: start->boot, stop->shutdown, reboot->reboot", [(c[0], c[1]) for c in PANEL.calls] == [(K2, "boot"), (K1, "shutdown"), (K1, "reboot")])
ok("get_state via status", p.get_state(ID1) == "stopped" and p.get_state(ID2) == "running")
ok("terminate -> Unsupported (绿云 API 不支持)", raises(p.action, ID1, "terminate", text="绿云 API 不支持", exc=gcp.Unsupported))
ok("unknown instance -> LookupError", raises(p.get_state, "gc-000000000000", exc=LookupError))
t = p.traffic(ID1)
ok("traffic: used/total GB from bw", t["used_gb"] == 384.0 and t["total_gb"] == 1000.0 and t["out_gb"] == 384.0 and t["in_gb"] == 0.0)
ok("traffic: rolling window unsupported", raises(p.traffic, ID1, "vm", start=1, text="不支持", exc=gcp.Unsupported))
ok("test(): ok for all servers", p.test() == {"ok": True, "servers": 2})
bad = gcp.GreenCloudProvider({"servers": [SRV[0], {"name": "坏机器", "key": K2, "hash": "0" * 40}]})
ok("test(): stops at the failing VPS and names it", raises(bad.test, text="VPS「坏机器」测试失败：Invalid key or hash", exc=gcp.GreenCloudError))
ok("list: one bad VPS does not break the list", [i.get("error") is not None for i in bad.list_instances()] == [False, True]
   and bad.list_instances()[1]["state"] == "unknown")
for mode, frag in (("ssl", "SSL 证书校验失败"), ("timeout", "超时"), ("http500", "HTTP 500"), ("html", "无法识别"), ("redirect", "跳转")):
    PANEL.mode = mode
    ok(f"error handling: {mode} -> clear message", raises(p.get_state, ID1, text=frag, exc=gcp.GreenCloudError)
       and not raises(p.get_state, ID1, text=K1) and not raises(p.get_state, ID1, text=H1))
PANEL.mode = None

# ================= 3. 接口 =================
with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    ok("/api/meta: providers incl. greencloud (default on)", c.get("/api/meta").json() == {"providers": ["oci", "aws", "azure", "greencloud"]})
    ok("settings: enable_greencloud defaults to true", c.get("/api/settings").json()["enable_greencloud"] is True)
    r = c.post("/api/accounts", json={"provider": "greencloud", "name": "绿云 洛杉矶", "api_url": "https://cp.example.com:5656",
                                      "servers_text": f"LA 1 {K1} {H1}\nLA-2, {K2}, {H2}"})
    ok("add account: {provider, name, api_url, servers_text}", r.status_code == 200 and r.json()["test"]["servers"] == 2)
    aid = r.json()["id"]
    raw = core.q("SELECT cred_enc FROM accounts WHERE id=?", (aid,), one=True)["cred_enc"]
    ok("cred stored Fernet-encrypted (no key/hash in DB row)", K1 not in raw and H1 not in raw
       and core.get_account(aid, with_cred=True)["cred"]["servers"][0]["key"] == K1)
    PANEL.vms[K2]["hash"] = "x"
    r = c.post("/api/accounts", json={"provider": "greencloud", "name": "bad", "servers_text": f"ok {K1} {H1}\nbad {K2} {H2}"})
    ok("add account: failing VPS named in error", r.status_code == 400 and "VPS「bad」" in r.json()["detail"])
    PANEL.vms[K2]["hash"] = H2
    r = c.post("/api/accounts", json={"provider": "greencloud", "name": "x", "api_url": "http://cp.example.com", "servers_text": f"a {K1} {H1}"})
    ok("add account: http:// panel refused 400", r.status_code == 400 and "https://" in r.json()["detail"])
    r = c.post("/api/accounts", json={"provider": "greencloud", "name": "x", "servers_text": "a b"})
    ok("add account: bad servers_text -> 400 line number", r.status_code == 400 and "第 1 行" in r.json()["detail"])
    accs = c.get("/api/accounts").text
    det = c.get(f"/api/accounts/{aid}/detail").json()
    ok("GET /accounts + detail never return key/hash", K1 not in accs and H1 not in accs and K1 not in str(det) and H1 not in str(det))
    ok("detail: api_url plain + servers_text masked ****last4", det["fields"]["api_url"] == "https://cp.example.com:5656"
       and det["fields"]["servers_text"] == f"LA 1 ****{K1[-4:]} ****{H1[-4:]}\nLA-2 ****{K2[-4:]} ****{H2[-4:]}"
       and det["servers"][0]["id"] == ID1)
    PANEL.calls.clear()
    r = c.patch(f"/api/accounts/{aid}", json={"cred": {"api_url": "https://cp.example.com:5656", "servers_text": det["fields"]["servers_text"]}})
    ok("PATCH with unchanged masked text: no change, no test call", r.status_code == 200 and not PANEL.calls)
    txt = det["fields"]["servers_text"].replace("LA-2", "LA 二号") + f"\nLA-3 {K3} {H3}"
    r = c.patch(f"/api/accounts/{aid}", json={"cred": {"servers_text": txt}})
    cr = core.get_account(aid, with_cred=True)["cred"]
    ok("PATCH: masked key/hash keep originals, rename + new VPS added (tested)",
       r.status_code == 200 and [s["key"] for s in cr["servers"]] == [K1, K2, K3] and cr["servers"][1]["name"] == "LA 二号"
       and cr["servers"][1]["hash"] == H2 and any(x[1] == "status" for x in PANEL.calls))
    r = c.patch(f"/api/accounts/{aid}", json={"cred": {"servers_text": "ghost ****zzzz ****yyyy"}})
    ok("PATCH: masked value that matches nothing -> 400", r.status_code == 400 and "打码" in r.json()["detail"])
    r = c.patch(f"/api/accounts/{aid}", json={"cred": {"servers_text": f"LA 1 ****{K1[-4:]} ****{H1[-4:]}\nLA 二号 ****{K2[-4:]} ****{H2[-4:]}"}})
    ok("PATCH: dropping a line removes that VPS", r.status_code == 200 and len(core.get_account(aid, with_cred=True)["cred"]["servers"]) == 2)
    insts = c.get(f"/api/accounts/{aid}/instances").json()
    ok("GET instances via API", [i["id"] for i in insts] == [ID1, ID2] and insts[0]["bw"]["total"] == 1000 * G)
    ok("regions -> ['-']", c.get(f"/api/accounts/{aid}/regions").json() == ["-"])
    PANEL.calls.clear()
    r = c.post(f"/api/accounts/{aid}/instances/action", json={"instance_id": ID1, "action": "start"})
    ok("API action start -> boot", r.status_code == 200 and PANEL.calls[-1][:2] == (K1, "boot"))
    r = c.post(f"/api/accounts/{aid}/instances/action", json={"instance_id": ID1, "action": "terminate", "confirm": True})
    ok("API terminate -> 400 绿云 API 不支持", r.status_code == 400 and "绿云 API 不支持" in r.json()["detail"])
    unsup = [c.post(f"/api/accounts/{aid}/instances/change-ip", json={"instance_id": ID1}),
             c.post(f"/api/accounts/{aid}/instances/resize", json={"instance_id": ID1}),
             c.post(f"/api/accounts/{aid}/instances/rename", json={"instance_id": ID1, "new_name": "x"}),
             c.post(f"/api/accounts/{aid}/instances/{ID1}/open-port", json={"port": "443"}),
             c.post(f"/api/accounts/{aid}/instances/reinstall", json={"instance_id": ID1, "confirm": True})]
    ok("change-ip / resize / rename / open-port / reinstall -> 400 绿云 API 不支持",
       all(x.status_code == 400 and "绿云 API 不支持" in x.json()["detail"] for x in unsup))
    ok("oci-only route on greencloud -> 400", c.get(f"/api/accounts/{aid}/oci/limits").status_code == 400)
    b = c.get(f"/api/accounts/{aid}/billing").json()
    ok("billing: stub, no provider call", b["unsupported"] is True and b["total"] is None)
    ok("account-type: 绿云 KVM", c.get(f"/api/accounts/{aid}/account-type").json()["label"] == "绿云 KVM")
    ok("test endpoint ok", c.post(f"/api/accounts/{aid}/test").json()["ok"] is True)
    ok("account-health computes without error", c.post("/api/account-health/refresh", json={"account_id": aid}).json()[0].get("score") == 100)
    PANEL.mode = "html"
    r = c.get(f"/api/accounts/{aid}/traffic?instance_id={ID1}")
    ok("GreenCloudError -> 502 with message (no secrets)", r.status_code == 502 and "无法识别" in r.json()["detail"] and K1 not in r.text)
    PANEL.mode = None

    # 粘贴识别 / 批量导入
    pr = c.post("/api/accounts/parse", json={"text": f"绿云 圣何塞\nhttps://cp.example.com:5656\nsj-1 {K3} {H3}"}).json()["items"]
    ok("parse: greencloud recognised with name, api_url, servers_text", pr and pr[0]["provider"] == "greencloud" and pr[0]["name"] == "圣何塞"
       and pr[0]["cred"] == {"api_url": "https://cp.example.com:5656", "servers_text": f"sj-1 {K3} {H3}"} and pr[0]["missing"] == [])
    ok("sniff: strict SolusVM format recognised without brand word", accounts_import.parse(f"la {K3} {H3}")[0]["provider"] == "greencloud")
    ok("sniff: AWS paste not mistaken for greencloud",
       accounts_import.parse("Access key ID: AKIAIOSFODNN7EXAMPLE\nSecret access key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")[0]["provider"] == "aws")
    r = c.post("/api/accounts/batch", json={"text": '{"provider": "greencloud", "name": "批量绿云", "api_url": "https://cp.example.com", '
                                                   f'"servers_text": "b1 {K3} {H3}"}}\n{{"name": "推断", "servers": [{{"name": "b2", "key": "{K2}", "hash": "{H2}"}}]}}'})
    ok("batch: JSON provider=greencloud + inferred from servers", r.status_code == 200 and r.json()["ok"] == 2)
    r = c.post("/api/accounts/batch", json={"text": f"绿云\nb3 {K1} {H1}", "dry_run": True})
    ok("batch: pasted text recognised as greencloud (dry run)", r.status_code == 200 and r.json()["results"][0]["provider"] == "greencloud" and r.json()["ok"] == 1)

    # 流量守护
    r = c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": ID1, "name": "LA 1", "mode": "rolling", "window_hours": 6})
    ok("traffic guard: rolling refused 400", r.status_code == 400 and "滚动窗口" in r.json()["detail"])
    r = c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": ID1, "name": "LA 1", "action": "stop", "warn_pct": 80})
    gid = r.json().get("id")
    gl = core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True)
    ok("traffic guard: saved, limit follows bw.total, usage = bw.used", r.status_code == 200 and gl["limit_gb"] == 1000.0 and gl["last_gb"] == 384.0
       and gl["last_pct"] == 38.4)
    gv = [x for x in c.get("/api/traffic-guards").json() if x["id"] == gid][0]
    ok("traffic guard view: scope 本计费周期", gv["scope"] == gcp.SCOPE_TEXT and gv["provider"] == "greencloud")
    PANEL.vms[K1]["bw"] = [1000 * G, 1000 * G]
    PANEL.vms[K1]["state"] = "online"
    PANEL.calls.clear()
    txt = traffic_guard.check(core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True))
    gl = core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True)
    ok("traffic guard: at 100% -> shutdown sent + TG text", (K1, "shutdown") in [x[:2] for x in PANEL.calls] and "流量已达上限" in (txt or "")
       and "本计费周期" in txt and "已自动停机" in txt and gl["state"] == "tripped" and PANEL.vms[K1]["state"] == "offline")
    with mock.patch.object(services, "now_local", lambda: services.dt.datetime(2099, 1, 5, tzinfo=services.tz())):
        PANEL.calls.clear()
        txt2 = traffic_guard.check(core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True))
    ok("traffic guard: month change does not re-trigger (own billing cycle)", txt2 is None and not any(x[1] == "shutdown" for x in PANEL.calls))
    PANEL.vms[K1]["bw"] = [2000 * G, 10 * G]
    traffic_guard.check(core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True))
    gl = core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True)
    ok("traffic guard: cycle reset -> limit synced to new total, state back to ok", gl["limit_gb"] == 2000.0 and gl["state"] == "ok" and gl["notified"] == 0)
    ok("traffic guard: due() includes greencloud rule", any(g["id"] == gid for g in (core.ex("UPDATE traffic_guards SET checked_at=0"), traffic_guard.due())[1]))

    # 监控
    r = c.post("/api/monitors", json={"account_id": aid, "instance_id": ID1, "name": "LA 1", "auto_start": True, "check_port": 22, "auto_change_ip": True})
    m = core.q("SELECT * FROM monitors WHERE account_id=?", (aid,), one=True)
    ok("monitor: added, auto_change_ip forced off (no IP change on GreenCloud)", r.status_code == 200 and m["auto_change_ip"] == 0 and m["auto_start"] == 1)
    ok("monitor: get_state works for monitor loop", services.get_state(aid, ID1, None, "vm") == "stopped")

    # TG
    core.set_secret_setting("tg_token", "1:x")
    core.set_setting("tg_chat_id", "42")

    class Bot:
        def __init__(self):
            self.calls = []

        async def call(self, method, body):
            self.calls.append((method, body))
            return {"ok": True}

        def kb(self):
            return [bt for c in self.calls if c[1].get("reply_markup") for r in c[1]["reply_markup"]["inline_keyboard"] for bt in r][-40:]

    bot = Bot()
    asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "/start"}))
    home = [bt["text"] for bt in bot.kb()]
    ok("tg: /start shows GreenCloud when a greencloud account exists", any("GreenCloud" in x for x in home))
    MSG = {"message_id": 7, "chat": {"id": 42}}

    def cbq(data):
        asyncio.run(telegram.handle_callback(bot, "42", {"id": "q", "data": data, "message": MSG}))

    def btn(part):
        return [bt for bt in bot.kb() if part in bt["text"]][-1]["callback_data"]
    cbq(btn("GreenCloud"))
    cbq(btn("绿云 洛杉矶"))
    ok("tg: account menu has 实例 + 测活, no 账单", any("实例" in x["text"] for x in bot.kb()[-4:]) and not any("账单" in x["text"] for x in bot.kb()[-4:]))
    cbq(btn("实例"))
    rows = [x["text"] for x in bot.kb()]
    ok("tg: instance list shows traffic percent", any("LA 1" in x and "%" in x for x in rows))
    cbq(btn("LA 1"))
    last = bot.calls[-1][1]
    ops = [x["text"] for x in last["reply_markup"]["inline_keyboard"][0]]
    ok("tg: instance view: 启动 / 停止 / 重启 only + 流量 line", ops == ["启动", "停止", "重启"] and "流量：" in last["text"]
       and "换 IP" not in str(last["reply_markup"]))
    PANEL.vms[K1]["bw"] = [2000 * G, 500 * G]
    cbq(btn("刷新状态"))
    ok("tg: refresh updates traffic via info", "500.0 / 2000 GB（25%）" in bot.calls[-1][1]["text"])
    cbq(btn("启动"))
    cbq(btn("确认启动"))
    ok("tg: start -> boot", "指令已发送" in bot.calls[-2][1]["text"] or "指令已发送" in str(bot.calls[-3:]))
    ok("tg: billing report skips greencloud", "绿云" not in telegram.billing_report())

    # ================= 4. 「启用绿云」开关 =================
    r = c.post("/api/settings", json={"enable_greencloud": False})
    ok("switch off: /api/meta drops greencloud", r.status_code == 200 and c.get("/api/meta").json() == {"providers": ["oci", "aws", "azure"]})
    ok("switch off: settings reports false", c.get("/api/settings").json()["enable_greencloud"] is False)
    ok("switch off: PROVIDERS / REQUIRED unregistered", "greencloud" not in services.PROVIDERS and "greencloud" not in main.REQUIRED)
    ok("switch off: /api/accounts hides greencloud accounts", not [a for a in c.get("/api/accounts").json() if a["provider"] == "greencloud"])
    r = c.post("/api/accounts", json={"provider": "greencloud", "name": "y", "servers_text": f"a {K3} {H3}"})
    ok("switch off: adding greencloud refused 400", r.status_code == 400)
    ok("switch off: account routes 404", c.get(f"/api/accounts/{aid}/instances").status_code == 404)
    ok("switch off: traffic guards / monitors lists skip greencloud",
       not [g for g in c.get("/api/traffic-guards").json() if g["account_id"] == aid] and not [m for m in c.get("/api/monitors").json() if m["account_id"] == aid])
    core.ex("UPDATE traffic_guards SET checked_at=0")
    ok("switch off: traffic guard loop skips", not [g for g in traffic_guard.due() if g["account_id"] == aid])
    ok("switch off: health list skips", not [h for h in c.get("/api/account-health").json() if h["provider"] == "greencloud"])
    bot.calls.clear()
    asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "/start"}))
    ok("switch off: TG home hides GreenCloud", not any("GreenCloud" in x["text"] for x in bot.kb()))
    ok("switch off: paste no longer recognised as greencloud", not [i for i in accounts_import.parse(f"绿云\nla {K3} {H3}") if i.get("provider") == "greencloud" and not i.get("error")])
    ok("switch off: data kept in DB", core.q("SELECT COUNT(*) AS n FROM accounts WHERE provider='greencloud'", one=True)["n"] >= 1
       and core.q("SELECT COUNT(*) AS n FROM traffic_guards WHERE account_id=?", (aid,), one=True)["n"] == 1)
    c.post("/api/settings", json={"enable_greencloud": True})
    ok("switch on again: everything back", c.get("/api/meta").json()["providers"][-1] == "greencloud"
       and [a for a in c.get("/api/accounts").json() if a["id"] == aid] and c.get(f"/api/accounts/{aid}/instances").status_code == 200
       and [g for g in c.get("/api/traffic-guards").json() if g["account_id"] == aid])
    r = c.delete(f"/api/accounts/{aid}")
    ok("delete greencloud account -> deleted_accounts record", r.status_code == 200 and c.get("/api/recycle-bin").json()["stats"]["by_provider"].get("greencloud") == 1)

# ================= 5. 可拆卸 / 前端 / 演示 / 约束 =================
hooks = []
for fn in os.listdir(os.path.join(ROOT, "app")):
    if fn.endswith(".py"):
        for ln in open(os.path.join(ROOT, "app", fn), encoding="utf-8"):
            if re.search(r"greencloud|gcp\.", ln, re.I):
                hooks.append((fn, ln.rstrip()))
ok("removable: every backend hook line outside the provider is tagged '# greencloud'", hooks and all("# greencloud" in ln for _, ln in hooks)) \
    if all("# greencloud" in ln for _, ln in hooks) else ok("removable hooks tagged: " + "; ".join(f"{f}: {ln.strip()[:60]}" for f, ln in hooks if "# greencloud" not in ln)[:400], False)
web = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
blk = re.search(r"// =+ GC 块 BEGIN.*?// =+ GC 块 END =+", web, re.S)
ok("web: GreenCloud code sits in one GC block", blk and all(x in blk.group(0) for x in ("tabGcInstances", "gcTrafficDialog", "PLOGO.greencloud", 'PNAME.greencloud = "GreenCloud"', "TABS.greencloud")))
outside = [ln for ln in web[:blk.start()].splitlines() + web[blk.end():].splitlines() if re.search(r"greencloud|\bGC\.", ln)] if blk else ["?"]
ok("web: lines outside the GC block are tagged // greencloud", all("// greencloud" in ln for ln in outside))
ok("web: settings toggle + /meta driven add options", "enable_greencloud" in web and '"/meta"' in web and "META" in web)
ok("web: batch dropdown + add dropdown generated from META", "provOpts(" in web)
mockjs = open(os.path.join(ROOT, "demo", "mock.js"), encoding="utf-8").read()
ok("demo: greencloud sample account with 2 VPS on 203.0.113.x", 'provider: "greencloud"' in mockjs and "203.0.113.61" in mockjs and "203.0.113.62" in mockjs and '"/meta"' in mockjs)
gsrc = open(os.path.join(ROOT, "app", "providers", "greencloud_provider.py"), encoding="utf-8").read()
ok("provider: no ssh / paramiko, SSL verify always on", "paramiko" not in gsrc and "verify=True" in gsrc and "verify=False" not in gsrc)
docs = open(os.path.join(ROOT, "docs", "FEATURES.md"), encoding="utf-8").read()
ok("docs: 移除绿云 section", "移除绿云" in docs and "enable_greencloud" in docs and "grep" in docs)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
