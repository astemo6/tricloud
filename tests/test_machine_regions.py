"""build 25：账号列表显示「有机器的区域」，打开账号默认选中机器最多的区域（不再固定显示 AWS 默认 us-east-1）。
复用 build 24 的总览扫描（/api/accounts/{id}/overview）：每次汇总后把有机器的区域持久化到 settings.machine_regions，
GET /api/accounts 直接带上（只读本地记录，不调用云 API）。全部用假客户端，不连接任何真实云。"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

from fastapi.testclient import TestClient

from app import core, main, overview, services, tasks, telegram
from app.providers.aws_provider import AWSProvider
from app.providers.azure_provider import AzureProvider
from app.providers.oci_provider import OCIProvider

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


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ================= 假 provider =================
# AWS：scan_all_regions 返回 rows（与真实 AWSProvider.scan_all_regions 同结构）；记录调用次数
AWS_ROWS = {}     # acc_id -> rows
AWS_CALLS = []


class FakeAws:
    def __init__(self, acc_id):
        self.acc_id = acc_id

    def scan_all_regions(self, regions=None, keep=()):
        AWS_CALLS.append((self.acc_id, tuple(regions) if regions else None))
        rows = AWS_ROWS.get(self.acc_id, [])
        if regions:
            rows = [r for r in rows if r["region"] in regions] or [{"region": rg, "ec2": 0, "ec2_running": 0, "lightsail": 0, "lightsail_running": 0}
                                                                  for rg in regions]
        return [dict(r) for r in rows]


def row(rg, ec2=0, ec2_run=0, ls=0, ls_run=0, **kw):
    return dict(region=rg, ec2=ec2, ec2_running=ec2_run, lightsail=ls, lightsail_running=ls_run, **kw)


OCI_WORLD = {"us-sanjose-1": ["RUNNING", "RUNNING", "RUNNING"], "ap-tokyo-1": []}
OCI_SUBS = [("us-sanjose-1", "READY"), ("ap-tokyo-1", "READY")]


class FakeCompute:
    def __init__(self, rg):
        self.rg = rg

    def list_instances(self, compartment_id=None, **kw):
        return Obj(data=[Obj(lifecycle_state=s) for s in OCI_WORLD.get(self.rg, [])], has_next_page=False, next_page=None)


def fake_oci():
    p = OCIProvider.__new__(OCIProvider)
    p.cfg = {"tenancy": "ocid1.tenancy.oc1..t", "region": "ap-tokyo-1"}
    p.compartment = "ocid1.tenancy.oc1..t"
    p.identity = Obj(list_region_subscriptions=lambda t: Obj(data=[Obj(region_name=r, status=s) for r, s in OCI_SUBS]))
    p._c = lambda cls, cfg=None: FakeCompute((cfg or p.cfg)["region"])
    return p


AZ_VMS = [("eastasia", "running"), ("japaneast", "running")]


def fake_az():
    p = AzureProvider.__new__(AzureProvider)
    p.compute = Obj(virtual_machines=Obj(list_all=lambda status_only=None: [
        Obj(location=loc, instance_view=Obj(statuses=[Obj(code="PowerState/" + st)])) for loc, st in AZ_VMS]))
    return p


with TestClient(main.app) as c:
    anon = TestClient(main.app)
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        a1 = c.post("/api/accounts", json={"provider": "aws", "name": "aws-1", "cred": {"access_key": "AKIAFAKE00000001", "secret_key": "x", "region": "us-east-1"}}).json()["id"]
        a2 = c.post("/api/accounts", json={"provider": "aws", "name": "aws-2", "cred": {"access_key": "AKIAFAKE00000002", "secret_key": "x", "region": "us-east-1"}}).json()["id"]
        a3 = c.post("/api/accounts", json={"provider": "aws", "name": "aws-3", "cred": {"access_key": "AKIAFAKE00000003", "secret_key": "x", "region": "us-east-1"}}).json()["id"]
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}), \
            mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)):
        o1 = c.post("/api/accounts", json={"provider": "oci", "name": "oci-1", "cred": {
            "user": "ocid1.user.oc1..fakeuser123456", "tenancy": "ocid1.tenancy.oc1..faketen654321", "fingerprint": "aa:bb",
            "key_content": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n", "region": "ap-tokyo-1"}}).json()["id"]
    with mock.patch.object(AzureProvider, "test", return_value={"ok": True}), \
            mock.patch.object(AzureProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)):
        z1 = c.post("/api/accounts", json={"provider": "azure", "name": "az-1", "cred": {
            "tenant_id": "t", "client_id": "c", "client_secret": "s", "subscription_id": "sub"}}).json()["id"]
    ok("setup: 5 accounts", all(isinstance(x, int) for x in (a1, a2, a3, o1, z1)))

    def prov(acc_id, region=None):
        if acc_id in (a1, a2, a3):
            return FakeAws(acc_id)
        if acc_id == o1:
            return fake_oci()
        return fake_az()

    def accs():
        return {a["id"]: a for a in c.get("/api/accounts").json()}

    import oci
    with mock.patch.object(services, "provider", prov), \
            mock.patch.object(oci.pagination, "list_call_get_all_results", lambda fn, *a, **kw: fn(*a, **kw)):
        overview.clear()
        AWS_ROWS.update({
            a1: [row("ap-northeast-1", ec2=1, ec2_run=1), row("us-east-1"), row("eu-west-1")],                      # 机器只在东京
            a2: [row("us-east-1"), row("ap-northeast-1"), row("us-west-2")],                                      # 没有机器
            a3: [row("ap-southeast-1", ec2=1), row("ap-northeast-1", ec2=2, ec2_run=1, ls=1, ls_run=1), row("us-east-1")],  # 两个区域
        })

        # ---------- 1. 还没扫描过：null，列表不触发任何云调用 ----------
        AWS_CALLS.clear()
        A = accs()
        ok("list: machine_regions null before any scan", all(A[x]["machine_regions"] is None for x in (a1, a2, a3, o1, z1)))
        ok("list: never scanned -> stale true, at null", A[a1]["machine_regions_stale"] is True and A[a1]["machine_regions_at"] is None)
        ok("list: GET /accounts makes no cloud calls", AWS_CALLS == [])
        ok("list: configured default region unchanged", A[a1]["region"] == "us-east-1")

        # ---------- 2. 总览一次后，列表带上有机器的区域 ----------
        for x in (a1, a2, a3, o1, z1):
            r = c.get(f"/api/accounts/{x}/overview")
            ok(f"overview {x}: 200", r.status_code == 200)
        AWS_CALLS.clear()
        A = accs()
        ok("list: still no cloud calls after scans", AWS_CALLS == [])
        ok("aws#1: machine_regions = [ap-northeast-1 ×1 running 1]",
           A[a1]["machine_regions"] == [{"region": "ap-northeast-1", "count": 1, "running": 1, "ec2": 1, "lightsail": 0}])
        ok("aws#1: default region still us-east-1 (not overwritten)", A[a1]["region"] == "us-east-1")
        ok("aws#1: fresh -> not stale, at set", A[a1]["machine_regions_stale"] is False and re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d$", A[a1]["machine_regions_at"] or ""))
        ok("aws#2: scanned, no machines -> []", A[a2]["machine_regions"] == [])
        ok("aws#3: most machines first (东京 3 then 新加坡 1)",
           [(r["region"], r["count"]) for r in A[a3]["machine_regions"]] == [("ap-northeast-1", 3), ("ap-southeast-1", 1)])
        ok("aws#3: lightsail counted in region total", A[a3]["machine_regions"][0]["lightsail"] == 1 and A[a3]["machine_regions"][0]["running"] == 2)
        ok("oci#1: machine region is us-sanjose-1 (default ap-tokyo-1 has none)",
           [(r["region"], r["count"], r["running"]) for r in A[o1]["machine_regions"]] == [("us-sanjose-1", 3, 3)])
        ok("oci#1: no ec2/lightsail keys", "ec2" not in A[o1]["machine_regions"][0])
        ok("azure#1: subscription-wide locations",
           sorted(r["region"] for r in A[z1]["machine_regions"]) == ["eastasia", "japaneast"])
        ok("helper machine_region()", overview.machine_region(a1) == "ap-northeast-1" and overview.machine_region(a2) is None
           and overview.machine_region(a3) == "ap-northeast-1")

        # ---------- 3. 持久化：内存缓存清空（模拟重启）后仍在 ----------
        overview.clear()
        A = accs()
        ok("persisted across cache clear (restart)", A[a1]["machine_regions"][0]["region"] == "ap-northeast-1" and A[a2]["machine_regions"] == [])
        raw = core.get_setting(overview.HINT_KEY)
        ok("stored only region/count data (no credentials)", "AKIA" not in json.dumps(raw) and "secret" not in json.dumps(raw))
        ok("stored keyed by account id", set(raw) >= {str(a1), str(a2), str(o1), str(z1)})
        ok("drop_provider_cache (cred/proxy/test) keeps hint", (services.drop_provider_cache(a1), overview.machine_region(a1))[1] == "ap-northeast-1")

        # ---------- 4. 过期标记 ----------
        h = overview.hint_fields(a1, now=time.time() + overview.FULL_TTL + 5)
        ok("stale after FULL_TTL", h["machine_regions_stale"] is True and h["machine_regions"])
        ok("not stale before FULL_TTL", overview.hint_fields(a1)["machine_regions_stale"] is False)

        # ---------- 5. 机器移到别的区域后，下一次汇总更新 ----------
        AWS_ROWS[a1] = [row("ap-northeast-1"), row("us-west-2", ec2=2, ec2_run=2), row("us-east-1")]
        c.get(f"/api/accounts/{a1}/overview?refresh=true")
        ok("moved: hint follows to us-west-2", overview.machine_region(a1) == "us-west-2")

        # ---------- 6. 部分区域失败：失败区域沿用上次记录 ----------
        before = core.get_setting(overview.HINT_KEY)[str(a3)]["regions"]
        AWS_ROWS[a3] = [row("ap-southeast-1", ec2=1), row("ap-northeast-1", ec2_error="ConnectTimeoutError"), row("us-east-1")]
        c.get(f"/api/accounts/{a3}/overview?refresh=true")
        A = accs()
        ok("partial: failed region keeps previous machines",
           [(r["region"], r["count"]) for r in A[a3]["machine_regions"]] == [("ap-northeast-1", 3), ("ap-southeast-1", 1)] and before)
        ok("partial: marked stale (so clients re-check later)", A[a3]["machine_regions_stale"] is True)
        AWS_ROWS[a3] = [row("ap-southeast-1", ec2=1), row("ap-northeast-1"), row("us-east-1")]
        time.sleep(0)
        overview._full.pop(a3, None)
        overview.MIN_FULL_GAP, _gap = 0, overview.MIN_FULL_GAP
        c.get(f"/api/accounts/{a3}/overview?refresh=true")
        overview.MIN_FULL_GAP = _gap
        A = accs()
        ok("recovered: machines really gone from 东京 -> only 新加坡", [r["region"] for r in A[a3]["machine_regions"]] == ["ap-southeast-1"]
           and A[a3]["machine_regions_stale"] is False)

        # ---------- 7. 全部区域失败：不写记录（保留上次） ----------
        prev = core.get_setting(overview.HINT_KEY)[str(a1)]
        AWS_ROWS[a1] = [row("us-east-1", ec2_error="AuthFailure"), row("us-west-2", ec2_error="AuthFailure")]
        overview._full.pop(a1, None)
        r = c.get(f"/api/accounts/{a1}/overview?refresh=true")
        ok("all failed: overview 400", r.status_code == 400)
        ok("all failed: hint untouched", core.get_setting(overview.HINT_KEY)[str(a1)] == prev)

        # ---------- 8. 写入节流：区域没变 10 分钟内不重写 ----------
        writes = []
        real = core.set_setting
        with mock.patch.object(core, "set_setting", lambda k, v: (writes.append(k), real(k, v))):
            d = {"provider": "aws", "regions": [{"region": "eu-west-1", "count": 1, "running": 1, "ec2": 1, "lightsail": 0}], "errors": []}
            overview.remember(a2, d)
            overview.remember(a2, d)
            overview.remember(a2, d, now=time.time() + overview.HINT_MIN_WRITE + 1)
        ok("remember: unchanged within HINT_MIN_WRITE -> one write; after -> rewrite", writes.count(overview.HINT_KEY) == 2)
        ok("remember: zero-count regions dropped", overview._hint_rows({"provider": "oci", "regions": [{"region": "x-1", "count": 0, "running": 0}]}) == [])
        ok("remember: sort count desc, running desc, code asc",
           [r["region"] for r in overview._hint_rows({"provider": "oci", "regions": [
               {"region": "b", "count": 1, "running": 0}, {"region": "a", "count": 1, "running": 0}, {"region": "c", "count": 1, "running": 1},
               {"region": "d", "count": 2, "running": 0}]})] == ["d", "c", "a", "b"])
        ok("remember: corrupt setting tolerated", (core.set_setting(overview.HINT_KEY, "garbage"), overview.hint_fields(a1)["machine_regions"])[1] is None)
        c.get(f"/api/accounts/{o1}/overview?refresh=true")
        ok("remember: recovers after corrupt setting", overview.machine_region(o1) == "us-sanjose-1")

        # ---------- 9. 删除账号同时删记录 ----------
        with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
            a4 = c.post("/api/accounts", json={"provider": "aws", "name": "aws-4", "cred": {"access_key": "AKIAFAKE00000004", "secret_key": "x", "region": "us-east-1"}}).json()["id"]
        AWS_ROWS[a4] = [row("ap-northeast-1", ec2=1)]

        def prov2(acc_id, region=None):
            return FakeAws(acc_id) if acc_id == a4 else prov(acc_id, region)
        with mock.patch.object(services, "provider", prov2):
            c.get(f"/api/accounts/{a4}/overview")
        ok("delete: hint present before", str(a4) in core.get_setting(overview.HINT_KEY))
        r = c.delete(f"/api/accounts/{a4}?confirm=true")
        if r.status_code >= 400:
            r = c.request("DELETE", f"/api/accounts/{a4}", json={"confirm": True})
        ok("delete: 200", r.status_code == 200)
        ok("delete: hint removed", str(a4) not in core.get_setting(overview.HINT_KEY))

    ok("route: /accounts unauthenticated -> 401", anon.get("/api/accounts").status_code == 401)
    ok("route: no new /api routes (hint rides on GET /accounts)", sum(1 for r in main.app.routes if getattr(r, "path", "").startswith("/api")) == 178)

# ================= 三端：源码 =================
P = {k: os.path.join(ROOT, v) for k, v in {
    "core": "web/js/core.js", "inst": "web/js/instances.js", "accounts": "web/js/accounts.js", "router": "web/js/router.js", "home": "web/js/home.js",
    "rj": "android/app/src/main/java/com/tricloud/app/Regions.java", "acts": "android/app/src/main/java/com/tricloud/app/AccountsActivity.java",
    "act": "android/app/src/main/java/com/tricloud/app/AccountActivity.java", "main": "android/app/src/main/java/com/tricloud/app/MainActivity.java",
    "rs": "ios/TriCloud/Regions.swift", "home_s": "ios/TriCloud/HomePages.swift", "acc_s": "ios/TriCloud/AccountPage.swift",
    "main_s": "ios/TriCloud/MainPage.swift", "mig_s": "ios/TriCloud/AccountPage+Migrate.swift", "app_s": "ios/TriCloud/TriCloudApp.swift",
    "mock": "demo/mock.js", "gradle": "android/app/build.gradle", "pyml": "ios/project.yml"}.items()}
S = {k: open(v, encoding="utf-8").read() for k, v in P.items()}
ok("web regionOf: stored > machineRegion > acc.region",
   'localStorage.getItem("tc_region_" + acc.id) || machineRegion(acc) || acc.region' in S["core"])
ok("android region(): Regions.current", "String region() { return Regions.current(acc); }" in S["act"]
   and "static String regionOf(JSONObject a) { return Regions.current(a); }" in S["main"])
ok("ios region(): Regions.current", "func region() -> String { Regions.current(acc) }" in S["acc_s"])
ok("no client reads Prefs region_ with acc region fallback any more",
   'Api.pref("region_" + id, str(acc, "region"' not in S["act"] and 'Prefs.get("region_\\(id)", str(acc, "region"' not in S["acc_s"]
   and 'str(to, "region", ""))' not in S["mig_s"])
ok("account lists use accountText on all three",
   "accountRegionText" in S["accounts"] and "accountRegionText" in S["router"] and "Regions.accountText(acc)" in S["acts"]
   and "Regions.accountText(acc)" in S["home_s"] and "Regions.accountText(acc)" in S["main_s"])
ok("ios accounts tab: no hard-coded default region subtitle", 'var d = p == "azure" ? "" : Regions.label(str(acc, "region", "-"))' not in S["home_s"])
ok("lazy refresh one at a time on all three",
   "mrChain = mrChain.then(" in S["core"] and "for (int id : todo)" in S["rj"] and "next(i + 1)" in S["rs"])
ok("open account: locate first (web/android/ios)", "ensureMachineRegion(acc)" in S["inst"] and "if (needLocate()) { locate(); return; }" in S["act"]
   and "if needLocate() { locate(); return }" in S["acc_s"])
ok("locate waits at most 8 s", "timeout = 8000" in S["core"] and "postDelayed(go, 8000)" in S["act"] and "later(8)" in S["acc_s"])
ok("locate runs once (no loop when overview fails)", "located = true" in S["act"] and "located = true" in S["acc_s"])
ok("no-region tabs list identical on three ends",
   all('"cloudfront", "quota", "billing", "subscription", "regions", "credit"' in S[k] for k in ("inst", "act", "acc_s")))
ok("home overview feeds hints (applyOverview / Regions.apply)", "applyOverview(a, o)" in S["home"] and "Regions.apply(acc.optInt(\"id\"), o)" in S["main"]
   and "Regions.apply(acc.optInt(\"id\"), o)" in S["home_s"])
ok("hints reset when /accounts reloads (android/ios)", "Regions.HINTS.clear()" in S["acts"] and "Regions.HINTS.clear()" in S["main"] and "Regions.hints = [:]" in S["app_s"])
ok("same texts on three ends", all(all(t in S[k] for t in ("无机器 · 默认 ", "（默认区域）", "\"无机器\"")) for k in ("core", "rj", "rs")))
ok("demo /accounts carries machine_regions", "machine_regions: o.regions" in S["mock"] and "function ovOf(id)" in S["mock"])
vc = re.search(r"versionCode (\d+)", S["gradle"]).group(1)
ok("version: Android versionCode 26 == iOS build 26", vc == "26" and 'CURRENT_PROJECT_VERSION: "26"' in S["pyml"])

# ================= JS 助手实际输出 =================
node = shutil.which("node")
ok("node available", node)
if node:
    core_js = S["core"]
    esc = re.search(r"^export const esc = [^\n]*\n", core_js, re.M).group(0)
    m = re.search(r"export const REGION_CITY = .*?export const regionOpt = [^\n]*\n", core_js, re.S)
    h = re.search(r"// 总览卡片（/accounts/\{id\}/overview）.*?export const overviewCount = .*?\n\};\n", core_js, re.S)
    b = re.search(r"// build 25：GET /accounts 每个账号带 machine_regions.*?\nexport function applyOverview.*?\n\}\n", core_js, re.S)
    ok("core.js: build 25 helper block present", m and h and b)
    js = re.sub(r"^export ", "", esc + m.group(0) + h.group(0) + b.group(0), flags=re.M)
    probe = "const _ls = {}; const localStorage = { getItem: (k) => _ls[k] ?? null, setItem: (k, v) => { _ls[k] = v; } };\n" + js + r"""
const A1 = { id: 1, provider: "aws", region: "us-east-1", machine_regions: [{ region: "ap-northeast-1", count: 1, running: 1 }] };
const A2 = { id: 2, provider: "aws", region: "us-east-1", machine_regions: [] };
const A3 = { id: 3, provider: "aws", region: "us-east-1", machine_regions: [{ region: "ap-northeast-1", count: 3, running: 2 }, { region: "ap-southeast-1", count: 1, running: 0 }] };
const A0 = { id: 4, provider: "aws", region: "us-east-1", machine_regions: null };
const O1 = { id: 5, provider: "oci", region: "ap-tokyo-1", machine_regions: [{ region: "us-sanjose-1", count: 3, running: 3 }] };
const Z1 = { id: 6, provider: "azure", region: null, machine_regions: [{ region: "japaneast", count: 1, running: 1 }, { region: "eastasia", count: 1, running: 1 }] };
const Z0 = { id: 7, provider: "azure", region: null, machine_regions: [] }, Zn = { id: 8, provider: "azure", region: null };
const out = { t1: accountRegionText(A1), t2: accountRegionText(A2), t3: accountRegionText(A3), t0: accountRegionText(A0), to: accountRegionText(O1),
  tz: accountRegionText(Z1), tz0: accountRegionText(Z0), tzn: accountRegionText(Zn),
  r1: regionOf(A1), r2: regionOf(A2), r3: regionOf(A3), r0: regionOf(A0), ro: regionOf(O1), mz: machineRegion(Z1) };
localStorage.setItem("tc_region_1", "eu-west-1"); out.rs = regionOf(A1);
const B = { id: 9, provider: "aws", region: "us-east-1" };
applyOverview(B, { regions: [{ region: "us-west-2", count: 1, running: 0 }, { region: "ap-northeast-1", count: 2, running: 1 }, { region: "x", count: 0 }], errors: [] });
out.ap = B.machine_regions; out.apr = regionOf(B); out.aps = B.machine_regions_stale;
applyOverview(B, { regions: [], errors: [{ region: "eu-west-1" }] }); out.ap2 = B.machine_regions; out.aps2 = B.machine_regions_stale;
applyOverview(B, null); applyOverview(B, { error: "x" }); out.ap3 = B.machine_regions;
console.log(JSON.stringify(out));
"""
    out = json.loads(subprocess.run([node, "-e", probe], capture_output=True, text=True, check=True).stdout)
    ok("js text: one region -> 'ap-northeast-1 · 东京'", out["t1"] == "ap-northeast-1 · 东京")
    ok("js text: no machines -> '无机器 · 默认 us-east-1 · 弗吉尼亚北部'", out["t2"] == "无机器 · 默认 us-east-1 · 弗吉尼亚北部")
    ok("js text: two regions -> '东京 等 2 个区域'", out["t3"] == "东京 等 2 个区域")
    ok("js text: never scanned -> 'us-east-1 · 弗吉尼亚北部（默认区域）'", out["t0"] == "us-east-1 · 弗吉尼亚北部（默认区域）")
    ok("js text: oci -> 'us-sanjose-1 · 圣何塞'", out["to"] == "us-sanjose-1 · 圣何塞")
    ok("js text: azure -> brief / 无机器 / ''", out["tz"] == "东日本 等 2 个区域" and out["tz0"] == "无机器" and out["tzn"] == "")
    ok("js regionOf: machine region beats default", out["r1"] == "ap-northeast-1" and out["r3"] == "ap-northeast-1" and out["ro"] == "us-sanjose-1")
    ok("js regionOf: no machines / never scanned -> default", out["r2"] == "us-east-1" and out["r0"] == "us-east-1")
    ok("js regionOf: manual choice wins", out["rs"] == "eu-west-1")
    ok("js machineRegion: azure -> ''", out["mz"] == "")
    ok("js applyOverview: sorted desc, zero dropped", [r["region"] for r in out["ap"]] == ["ap-northeast-1", "us-west-2"] and out["apr"] == "ap-northeast-1"
       and out["aps"] is False)
    ok("js applyOverview: errors -> stale", out["ap2"] == [] and out["aps2"] is True)
    ok("js applyOverview: bad input ignored", out["ap3"] == [])

passed = sum(1 for _, x in R if x)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
