"""自测：VirtFusion 流量下次重置日（reset_at / days_left / reset_text）。
覆盖：/api/accounts/{id}/traffic 透传原字段并按面板时区补 reset_text、days_left；
流量守护（按月）记录 reset_at，/api/traffic-guards 返回 reset_text；滚动窗口不显示；
SolusVM（无重置日）不多出字段；前端三处接线（列表、流量弹窗、守护列表）。
全部 mock httpx，不连接任何真实面板。"""
import datetime as dt
import os
import re
import sys
import tempfile
import types

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

import httpx as real_httpx
from fastapi.testclient import TestClient

from app import core, main, services
from app.providers import solusvm_provider, virtfusion_provider
from app.providers.solusvm_provider import SolusVMProvider
from app.providers.virtfusion_provider import VirtFusionProvider

R = []


def ok(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if not cond and extra else ""))


SID = "6b32bae9-83e9-44f9-afd4-244f1fa27a49"
END = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)).replace(hour=23, minute=59, second=59, microsecond=999999)
START = END - dt.timedelta(days=30)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.%fZ")   # noqa: E731  真实 API 格式
SERVER = {"id": SID, "name": "vf1", "memory": "1024 MB", "cpu": "2 Core", "storage": [{"capacity": "10 GB", "primary": True}],
          "network": {"primary": {"limit": "2000 GB", "ipv4": [{"address": "203.0.113.20"}], "ipv6": []}, "secondary": []},
          "currentMonthlyPeriod": {"start": iso(START), "end": iso(END)}}
STATE = {"status": "running", "running": True, "network": {"primary": {"traffic": {"rx": 2 * 1024 ** 3, "tx": 3 * 1024 ** 3}}}}


class FakeResp:
    def __init__(self, p, status=200):
        self._p, self.status_code, self.content = p, status, b"x"

    def json(self):
        return self._p


class FakeClient:
    def __init__(self, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def request(self, method, url, json=None, params=None, headers=None):
        path = url.split("/api/")[1]
        if path == "connect":
            return FakeResp({})
        if path.startswith("server/"):
            return FakeResp({"data": dict(SERVER, state=STATE)})
        return FakeResp({"data": [SERVER], "next_page_url": None})


virtfusion_provider.httpx = types.SimpleNamespace(Client=FakeClient, HTTPError=real_httpx.HTTPError)
mock.patch.object(SolusVMProvider, "test", return_value={"ok": True}).start()
mock.patch.object(SolusVMProvider, "_info", return_value={"bw": "100000000000,5000000000,95000000000,5"}).start()

with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    c.post("/api/settings", json={"timezone": "Asia/Shanghai"})
    r = c.post("/api/accounts", json={"provider": "virtfusion", "name": "vf", "cred": {"panel_url": "https://cp.example.com", "api_token": "TOK"}})
    ok("add virtfusion account", r.status_code == 200, r.text)
    vf = r.json()["id"]
    r = c.post("/api/accounts", json={"provider": "solusvm", "name": "sv", "cred": {"panel_url": "https://cp.example.com", "key": "k", "hash": "h"}})
    sv = r.json().get("id")

    t = c.get(f"/api/accounts/{vf}/traffic", params={"instance_id": SID}).json()
    ok("traffic keeps old fields", {"in_gb", "out_gb", "used_gb", "total_gb", "period", "period_start", "period_end"} <= set(t), t)
    ok("period text YYYY-MM-DD ~ YYYY-MM-DD", re.fullmatch(r"\d{4}-\d\d-\d\d ~ \d{4}-\d\d-\d\d", t["period"] or ""), t.get("period"))
    reset = dt.datetime.fromisoformat(t["reset_at"])
    ok("reset_at = period end + 1 min (next 00:00 UTC)", reset == (END + dt.timedelta(minutes=1)).replace(second=0, microsecond=0), t["reset_at"])
    sh = reset.astimezone(services.tz())
    ok("reset_text in panel tz (Asia/Shanghai, 08:00)", t["reset_text"] == sh.strftime("%m-%d %H:%M") and t["reset_text"].endswith("08:00"), t.get("reset_text"))
    ok("days_left in panel tz", t["days_left"] == (sh.date() - services.now_local().date()).days and 5 <= t["days_left"] <= 7, t.get("days_left"))

    if sv:
        ts = c.get(f"/api/accounts/{sv}/traffic", params={"instance_id": "1"}).json()
        ok("solusvm: no reset fields", "reset_at" not in ts and "reset_text" not in ts, ts)

    g = c.post("/api/traffic-guards", json={"account_id": vf, "instance_id": SID, "name": "vf1", "limit_gb": 2000, "warn_pct": 80}).json()
    gl = [x for x in c.get("/api/traffic-guards").json() if x["instance_id"] == SID]
    ok("guard stored reset_at", gl and gl[0].get("reset_at") == t["reset_at"], gl)
    ok("guard list has reset_text + days_left", gl and gl[0].get("reset_text") == t["reset_text"] and gl[0].get("days_left") == t["days_left"], gl)
    core.ex("UPDATE traffic_guards SET mode='rolling' WHERE instance_id=?", (SID,))
    gl = [x for x in c.get("/api/traffic-guards").json() if x["instance_id"] == SID]
    ok("rolling guard: no reset_text", gl and not gl[0].get("reset_text"), gl)

js = {f: open(os.path.join(ROOT, "web/js", f), encoding="utf-8").read() for f in ("core.js", "instances.js", "monitors.js", "i18n.js")}
ok("core.resetText exported", "export const resetText" in js["core.js"])
ok("instances: list + dialog use resetText", js["instances.js"].count("resetText(td)") == 2)
ok("monitors: guard list uses resetText", "resetText(g)" in js["monitors.js"])
ok("i18n zh/en", js["i18n.js"].count('"inst.trafReset"') == 2 and "下次重置 {t} · 还有 {n} 天" in js["i18n.js"])

bad = [n for n, v in R if not v]
print(f"{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
