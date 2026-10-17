"""build 24：总览按「所有有机器的区域」统计实例（GET /api/accounts/{id}/overview）。
以前总览只查账号默认区域（AWS us-east-1），机器在东京等其他区域时显示 0 台。
全部用假客户端，不连接任何真实云。"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app import core, main, overview, services, tasks, telegram
from app.providers import aws_provider
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


def cerr(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "Op")


# ================= 假 AWS =================
# 每个区域的机器：EC2 状态列表、Lightsail 状态列表
WORLD = {}
CALLS = []
CONC = {"now": 0, "max": 0}
CL = threading.Lock()
MODE = {"describe_regions": "ok", "list_regions": "ok", "ls_fail": set(), "ec2_fail": set(), "optin": set(), "slow": 0.0}
ENABLED = ["ap-east-2", "ap-northeast-1", "ap-southeast-1", "eu-west-1", "us-east-1", "us-west-2"]


class FakeEc2:
    def __init__(self, rg):
        self.rg = rg

    def describe_regions(self):
        CALLS.append(("describe_regions", self.rg))
        if MODE["describe_regions"] != "ok":
            raise cerr("UnauthorizedOperation")
        return {"Regions": [{"RegionName": x} for x in ENABLED]}

    def get_paginator(self, name):
        rg = self.rg

        def paginate():
            with CL:
                CONC["now"] += 1
                CONC["max"] = max(CONC["max"], CONC["now"])
            try:
                CALLS.append(("describe_instances", rg))
                if MODE["slow"]:
                    time.sleep(MODE["slow"])
                if rg in MODE["optin"]:
                    raise cerr("AuthFailure")
                if rg in MODE["ec2_fail"]:
                    raise cerr("RequestLimitExceeded")
                sts = WORLD.get(rg, {}).get("ec2", [])
                # 两页：验证分页都计入
                return [{"Reservations": [{"Instances": [{"State": {"Name": s}} for s in sts[:1]]}]},
                        {"Reservations": [{"Instances": [{"State": {"Name": s}} for s in sts[1:]]}]}]
            finally:
                with CL:
                    CONC["now"] -= 1
        return Obj(paginate=paginate)


class FakeLs:
    def __init__(self, rg):
        self.rg = rg

    def get_regions(self):
        return {"regions": [{"name": x} for x in ("ap-northeast-1", "ap-southeast-1", "eu-west-1", "us-east-1", "us-west-2")]}

    def get_instances(self, pageToken=None):
        CALLS.append(("get_instances", self.rg))
        if self.rg in MODE["ls_fail"]:
            raise cerr("AccessDeniedException")
        sts = WORLD.get(self.rg, {}).get("ls", [])
        if pageToken is None and len(sts) > 1:
            return {"instances": [{"state": {"name": sts[0]}}], "nextPageToken": "p2"}
        return {"instances": [{"state": {"name": s}} for s in (sts[1:] if pageToken else sts)]}


class FakeAccount:
    def list_regions(self, MaxResults=50, NextToken=None):
        CALLS.append(("list_regions", "us-east-1"))
        if MODE["list_regions"] != "ok":
            raise cerr("AccessDeniedException")
        return {"Regions": [{"RegionName": x, "RegionOptStatus": "ENABLED_BY_DEFAULT"} for x in ENABLED]
                + [{"RegionName": "af-south-1", "RegionOptStatus": "DISABLED"}]}


class FakeSession:
    def client(self, svc, region_name=None, config=None):
        return {"ec2": FakeEc2, "lightsail": FakeLs, "account": lambda r: FakeAccount()}[svc](region_name)


PROVS = {}


def fake_aws(acc_id, region="us-east-1"):
    key = (acc_id, region)
    if key not in PROVS:
        p = AWSProvider({"access_key": "AKIAFAKE", "secret_key": "fake", "region": "us-east-1"}, region)
        p.session = FakeSession()
        PROVS[key] = p
    return PROVS[key]


def reset(world=None, **mode):
    WORLD.clear()
    WORLD.update(world or {})
    CALLS.clear()
    CONC.update(now=0, max=0)
    MODE.update(describe_regions="ok", list_regions="ok", ls_fail=set(), ec2_fail=set(), optin=set(), slow=0.0)
    MODE.update(mode)
    overview.clear()
    aws_provider._LS_GETREGIONS.clear()


def n_calls(kind, rg=None):
    return sum(1 for c in CALLS if c[0] == kind and (rg is None or c[1] == rg))


# ================= 假 OCI / Azure =================
OCI_WORLD = {"us-sanjose-1": ["RUNNING", "RUNNING", "STOPPED", "TERMINATED"], "ap-tokyo-1": ["RUNNING"]}
OCI_SUBS = [("us-sanjose-1", "READY"), ("ap-tokyo-1", "READY"), ("ap-osaka-1", "IN_PROGRESS")]
OCI_FAIL = set()


class FakeCompute:
    def __init__(self, rg):
        self.rg = rg

    def list_instances(self, compartment_id=None, **kw):
        if self.rg in OCI_FAIL:
            raise RuntimeError("NotAuthorizedOrNotFound")
        return Obj(data=[Obj(lifecycle_state=s) for s in OCI_WORLD.get(self.rg, [])], has_next_page=False, next_page=None)


def fake_oci():
    p = OCIProvider.__new__(OCIProvider)
    p.cfg = {"tenancy": "ocid1.tenancy.oc1..t", "region": "us-sanjose-1"}
    p.compartment = "ocid1.tenancy.oc1..t"
    p.identity = Obj(list_region_subscriptions=lambda t: Obj(data=[Obj(region_name=r, status=s, is_home_region=r == "us-sanjose-1")
                                                                   for r, s in OCI_SUBS]))
    p._c = lambda cls, cfg=None: FakeCompute((cfg or p.cfg)["region"])
    return p


AZ_VMS = [("japaneast", "running"), ("eastasia", "running"), ("japaneast", "deallocated")]
AZ_CALLS = []


def fake_az():
    p = AzureProvider.__new__(AzureProvider)

    def list_all(status_only=None):
        AZ_CALLS.append(status_only)
        return [Obj(location=loc, instance_view=Obj(statuses=[Obj(code="ProvisioningState/succeeded"), Obj(code="PowerState/" + st)]))
                for loc, st in AZ_VMS]
    p.compute = Obj(virtual_machines=Obj(list_all=list_all))
    return p


# ================= 1. 后端：AWS =================
with TestClient(main.app) as c:
    anon = TestClient(main.app)
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        a1 = c.post("/api/accounts", json={"provider": "aws", "name": "aws-1", "cred": {"access_key": "AKIAFAKE00000001", "secret_key": "x", "region": "us-east-1"}}).json()["id"]
        a2 = c.post("/api/accounts", json={"provider": "aws", "name": "aws-2", "cred": {"access_key": "AKIAFAKE00000002", "secret_key": "x", "region": "us-east-1"}}).json()["id"]
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}), \
            mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)):
        o1 = c.post("/api/accounts", json={"provider": "oci", "name": "oci-1", "cred": {
            "user": "ocid1.user.oc1..fakeuser123456", "tenancy": "ocid1.tenancy.oc1..faketen654321", "fingerprint": "aa:bb",
            "key_content": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n", "region": "us-sanjose-1"}}).json()["id"]
    with mock.patch.object(AzureProvider, "test", return_value={"ok": True}), \
            mock.patch.object(AzureProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)):
        z1 = c.post("/api/accounts", json={"provider": "azure", "name": "az-1", "cred": {
            "tenant_id": "t", "client_id": "c", "client_secret": "s", "subscription_id": "sub"}}).json()["id"]
    ok("setup: 4 accounts", all(isinstance(x, int) for x in (a1, a2, o1, z1)))

    def prov(acc_id, region=None):
        if acc_id in (a1, a2):
            return fake_aws(acc_id, region or "us-east-1")
        if acc_id == o1:
            return fake_oci()
        return fake_az()

    import oci
    with mock.patch.object(services, "provider", prov), \
            mock.patch.object(oci.pagination, "list_call_get_all_results", lambda fn, *a, **kw: fn(*a, **kw)):
        # --- 机器只在东京：以前显示 0，现在显示东京 ---
        reset({"ap-northeast-1": {"ec2": ["running"]}})
        r = c.get(f"/api/accounts/{a1}/overview")
        o = r.json()
        ok("aws: 200", r.status_code == 200)
        ok("aws: machine in Tokyo counted although default region is us-east-1", o["total"] == 1 and o["running"] == 1 and o["ec2"] == 1)
        ok("aws: regions = [ap-northeast-1] only", [x["region"] for x in o["regions"]] == ["ap-northeast-1"])
        ok("aws: region row has count/running/ec2/lightsail", o["regions"][0] == {"region": "ap-northeast-1", "count": 1, "running": 1, "ec2": 1, "lightsail": 0})
        ok("aws: default_region us-east-1 kept for empty fallback", o["default_region"] == "us-east-1")
        ok("aws: all enabled regions scanned (EC2)", o["scanned"] == len(ENABLED) and all(n_calls("describe_instances", g) == 1 for g in ENABLED))
        ok("aws: lightsail only in supported regions (no Taipei)", n_calls("get_instances", "ap-east-2") == 0 and n_calls("get_instances", "ap-northeast-1") == 1)
        ok("aws: provider/account_id/scope/cached fields", o["provider"] == "aws" and o["account_id"] == a1 and o["scope"] == "all" and o["cached"] is False)
        ok("aws: concurrency ≤ SCAN_WORKERS (4)", 1 <= CONC["max"] <= AWSProvider.SCAN_WORKERS == 4)

        # --- 缓存：2 分钟内不再打云 ---
        CALLS.clear()
        o = c.get(f"/api/accounts/{a1}/overview").json()
        ok("cache: second call within HOT_TTL makes no cloud call", not CALLS and o["cached"] is True and o["total"] == 1)

        # --- HOT_TTL 过期：只重查已知有机器的区域 + 默认区域 ---
        overview._sum[a1]["ts"] -= overview.HOT_TTL + 1
        WORLD["ap-northeast-1"]["ec2"] = ["running", "stopped"]
        CALLS.clear()
        o = c.get(f"/api/accounts/{a1}/overview").json()
        ok("hot: only Tokyo + us-east-1 re-queried", sorted({x[1] for x in CALLS if x[0] == "describe_instances"}) == ["ap-northeast-1", "us-east-1"])
        ok("hot: no DescribeRegions on hot path", n_calls("describe_regions") == 0)
        ok("hot: new count picked up (2 / running 1)", o["total"] == 2 and o["running"] == 1 and o["scope"] == "known")

        # --- refresh=true：全量扫描，但 60 秒内不重复全量 ---
        WORLD["eu-west-1"] = {"ls": ["running", "stopped", "running"]}
        CALLS.clear()
        o = c.get(f"/api/accounts/{a1}/overview?refresh=true").json()
        ok("refresh within MIN_FULL_GAP: no new full scan (hot regions only)", n_calls("describe_regions") == 0)
        overview._full[a1]["ts"] -= overview.MIN_FULL_GAP + 1
        CALLS.clear()
        o = c.get(f"/api/accounts/{a1}/overview?refresh=true").json()
        ok("refresh after gap: full scan", n_calls("describe_regions") == 1 and n_calls("describe_instances") == len(ENABLED))
        ok("refresh: Lightsail in Ireland found (paginated, 3 / running 2)",
           any(x["region"] == "eu-west-1" and x["lightsail"] == 3 and x["running"] == 2 for x in o["regions"]))
        ok("multi-region: sorted by count desc (Ireland 3 before Tokyo 2)", [x["region"] for x in o["regions"]] == ["eu-west-1", "ap-northeast-1"])
        ok("multi-region: totals EC2 2 + Lightsail 3 = 5, running 3", o["total"] == 5 and o["ec2"] == 2 and o["lightsail"] == 3 and o["running"] == 3)

        # --- FULL_TTL 过期：自动全量扫描（新区域的机器能出现） ---
        WORLD["ap-southeast-1"] = {"ec2": ["running"]}
        overview._full[a1]["ts"] -= overview.FULL_TTL + 1
        overview._sum[a1]["ts"] -= overview.HOT_TTL + 1
        CALLS.clear()
        o = c.get(f"/api/accounts/{a1}/overview").json()
        ok("full TTL expired: full scan finds Singapore", n_calls("describe_regions") == 1 and any(x["region"] == "ap-southeast-1" for x in o["regions"]))

        # --- /aws/scan 与总览共用缓存 ---
        CALLS.clear()
        s = c.get(f"/api/accounts/{a1}/aws/scan").json()
        ok("aws/scan: reuses overview full-scan cache (no cloud call)", not CALLS and any(x["region"] == "ap-southeast-1" and x["ec2"] == 1 for x in s["regions"]))
        ok("aws/scan: row keeps old fields (ec2/ec2_running/lightsail) + updated_at", all({"region", "ec2", "ec2_running", "lightsail"} <= set(x) for x in s["regions"]) and s.get("updated_at"))
        ok("aws/scan: Taipei lightsail None (shown -)", next(x for x in s["regions"] if x["region"] == "ap-east-2")["lightsail"] is None)

        # --- 新建实例：记下区域，下次重查带上 ---
        WORLD["us-west-2"] = {"ec2": ["pending"]}
        overview.invalidate(a1, "us-west-2")
        CALLS.clear()
        o = c.get(f"/api/accounts/{a1}/overview").json()
        ok("invalidate(region): sum cache dropped, us-west-2 re-queried without full scan",
           n_calls("describe_regions") == 0 and n_calls("describe_instances", "us-west-2") == 1 and any(x["region"] == "us-west-2" for x in o["regions"]))
        ok("invalidate: extra regions consumed", a1 not in overview._extra)

        # --- 实例操作 → 汇总缓存作废 ---
        services.instance_action.__globals__  # noqa: B018
        with mock.patch.object(AWSProvider, "action", lambda self, i, a: {"ok": True}):
            c.post(f"/api/accounts/{a1}/instances/action", json={"instance_id": "i-1", "action": "stop", "region": "ap-northeast-1"})
        ok("instance action: overview sum cache dropped", a1 not in overview._sum)
        ok("instance action: region queued for re-query", "ap-northeast-1" in overview._extra.get(a1, set()))
        # --- 创建成功 → _created 作废 ---
        from app.routers.common import _created
        overview.summary(a1)
        _created(a1, {"id": "i-9", "name": "n"}, None)
        ok("_created without region: full scan cache dropped", a1 not in overview._full and a1 not in overview._sum)
        overview.summary(a1)
        _created(a1, {"id": "i-9", "name": "n"}, "eu-west-1")
        ok("_created with region: region queued, full cache kept", a1 in overview._full and "eu-west-1" in overview._extra.get(a1, set()))
        # --- 凭证变更 → 全部作废 ---
        services.drop_provider_cache(a1)
        ok("drop_provider_cache: overview caches cleared", a1 not in overview._full and a1 not in overview._sum)

        # --- 账号 2：IAM 不给 DescribeRegions（线上第二个 AWS 账号就是这样） ---
        reset({"ap-northeast-1": {"ec2": ["running"]}}, describe_regions="deny")
        o = c.get(f"/api/accounts/{a2}/overview").json()
        ok("no DescribeRegions: falls back to account:ListRegions", n_calls("list_regions") == 1 and o["total"] == 1
           and o["scanned"] == len(ENABLED) and n_calls("describe_instances", "af-south-1") == 0)
        reset({"ap-northeast-1": {"ec2": ["running"]}}, describe_regions="deny", list_regions="deny",
              optin={"af-south-1", "ap-east-1", "me-south-1", "il-central-1"})
        o = c.get(f"/api/accounts/{a2}/overview").json()
        static = aws_provider.boto3.session.Session().get_available_regions("ec2")
        ok("no DescribeRegions/ListRegions: botocore static list scanned", n_calls("describe_instances") == len(static) and len(static) >= 30)
        ok("static: not-enabled opt-in regions (AuthFailure) skipped, not errors", o["errors"] == [] and o["scanned"] == len(static) - 4)
        ok("static: Tokyo machine still found", o["total"] == 1 and o["regions"][0]["region"] == "ap-northeast-1")
        s = c.get(f"/api/accounts/{a2}/aws/scan").json()
        ok("static: aws/scan rows exclude not-enabled regions", not any(x["region"] == "af-south-1" for x in s["regions"]))

        # --- 部分失败 ---
        reset({"ap-northeast-1": {"ec2": ["running"]}}, ec2_fail={"eu-west-1"}, ls_fail={"us-east-1"})
        o = c.get(f"/api/accounts/{a1}/overview").json()
        ok("partial: EC2 failure in one region listed in errors", o["errors"] == [{"region": "eu-west-1", "error": "RequestLimitExceeded"}])
        ok("partial: Lightsail failure -> lightsail_failed, not a region error", o["lightsail_failed"] is True and o["total"] == 1)
        # --- Lightsail 全部无权限：EC2 照常，不报「所有区域失败」 ---
        reset({}, ls_fail=set(ENABLED))
        r = c.get(f"/api/accounts/{a1}/overview")
        ok("lightsail denied everywhere + no machines: still 200 with 0", r.status_code == 200 and r.json()["total"] == 0 and r.json()["lightsail_failed"])
        # --- EC2 全部失败 → 400 ---
        reset({}, ec2_fail=set(ENABLED))
        r = c.get(f"/api/accounts/{a1}/overview")
        ok("all regions EC2 failed -> 400 with reason", r.status_code == 400 and "所有区域查询失败" in r.json().get("detail", ""))

        # --- 同一账号并发请求只扫一次（锁） ---
        reset({"ap-northeast-1": {"ec2": ["running"]}}, slow=0.05)
        import concurrent.futures as cf
        with cf.ThreadPoolExecutor(4) as ex:
            outs = list(ex.map(lambda _: overview.summary(a1), range(4)))
        ok("concurrent: one full scan for 4 simultaneous requests", n_calls("describe_regions") == 1 and all(x["total"] == 1 for x in outs))

        # ================= 2. OCI / Azure =================
        reset()
        o = c.get(f"/api/accounts/{o1}/overview").json()
        ok("oci: READY subscribed regions scanned (osaka IN_PROGRESS skipped)", o["scanned"] == 2)
        ok("oci: Tokyo + San Jose, TERMINATED excluded", o["total"] == 4 and o["running"] == 3
           and [x["region"] for x in o["regions"]] == ["us-sanjose-1", "ap-tokyo-1"])
        ok("oci: default_region = account region", o["default_region"] == "us-sanjose-1")
        overview.clear()
        OCI_FAIL.add("ap-tokyo-1")
        o = c.get(f"/api/accounts/{o1}/overview").json()
        ok("oci: one region failing -> errors listed, others counted", o["total"] == 3 and len(o["errors"]) == 1 and o["errors"][0]["region"] == "ap-tokyo-1")
        overview.clear()
        OCI_FAIL.update({"us-sanjose-1"})
        r = c.get(f"/api/accounts/{o1}/overview")
        ok("oci: all regions failing -> 400", r.status_code == 400)
        OCI_FAIL.clear()
        overview.clear()

        o = c.get(f"/api/accounts/{z1}/overview").json()
        ok("azure: one status_only list call (no per-VM NIC lookups)", AZ_CALLS == ["true"])
        ok("azure: grouped by location (japaneast 2 / eastasia 1), running 2",
           o["total"] == 3 and o["running"] == 2 and [(x["region"], x["count"]) for x in o["regions"]] == [("japaneast", 2), ("eastasia", 1)])
        ok("azure: default_region None", o["default_region"] is None)
        AZ_CALLS.clear()
        c.get(f"/api/accounts/{z1}/overview")
        ok("azure: cached within HOT_TTL", AZ_CALLS == [])

    # ================= 3. 路由 =================
    ok("route: unauthenticated -> 401", anon.get(f"/api/accounts/{a1}/overview").status_code == 401)
    ok("route: unknown account -> 404", c.get("/api/accounts/9999/overview").status_code == 404)
    ok("route: GET only, not audited", not core.q("SELECT 1 FROM audit_log WHERE path LIKE '%/overview%'") if
       core.q("SELECT name FROM sqlite_master WHERE name='audit_log'") else True)

# ================= 4. 三端显示 =================
SRC = {p: open(os.path.join(ROOT, p), encoding="utf-8").read() for p in (
    "web/js/core.js", "web/js/home.js", "android/app/src/main/java/com/tricloud/app/MainActivity.java",
    "android/app/src/main/java/com/tricloud/app/Regions.java", "ios/TriCloud/HomePages.swift", "ios/TriCloud/Regions.swift")}
home, core_js = SRC["web/js/home.js"], SRC["web/js/core.js"]
ok("web home: uses /overview, no per-region instances calls", "/overview" in home and "instances?kind=lightsail" not in home and "/instances?" not in home)
ok("web home: rescan button sends refresh=true", "ovRescan" in home and "refresh=true" in home)
ok("android home: uses /overview, no per-region instances calls", "/overview" in SRC["android/app/src/main/java/com/tricloud/app/MainActivity.java"]
   and "instances?kind=lightsail" not in SRC["android/app/src/main/java/com/tricloud/app/MainActivity.java"])
ok("ios home: uses /overview, no per-region instances calls", "/overview" in SRC["ios/TriCloud/HomePages.swift"]
   and "instances?kind=lightsail" not in SRC["ios/TriCloud/HomePages.swift"])
ok("all three: 重新扫描区域 action", all("重新扫描区域" in SRC[p] for p in ("web/js/home.js", "android/app/src/main/java/com/tricloud/app/MainActivity.java", "ios/TriCloud/HomePages.swift")))
ok("android/ios: brief/dist/count helpers present", all(x in SRC["android/app/src/main/java/com/tricloud/app/Regions.java"] for x in ("static String brief(", "static String dist(", "static String count("))
   and all(x in SRC["ios/TriCloud/Regions.swift"] for x in ("static func brief(", "static func dist(", "static func count(")))
for p in ("android/app/src/main/java/com/tricloud/app/Regions.java", "ios/TriCloud/Regions.swift"):
    ok(f"{p.split('/')[-1]}: same texts as core.js (等 N 个区域 / 部分区域失败 / 个区域查询失败)",
       all(x in SRC[p] for x in (" 等 ", " 个区域", "（部分区域失败）", "查询失败", " 个区域查询失败", " 台（运行 ", "· ", " · ")))

# JS 助手实际输出
node = shutil.which("node")
ok("node available", node)
if node:
    m = re.search(r"export const REGION_CITY = .*?export const regionOpt = [^\n]*\n", core_js, re.S)
    h = re.search(r"// 总览卡片（/accounts/\{id\}/overview）.*?export const overviewCount = .*?\n\};\n", core_js, re.S)
    ok("core.js: overview helpers block present", m and h)
    esc = re.search(r"^export const esc = [^\n]*\n", core_js, re.M).group(0)
    js = re.sub(r"^export ", "", esc + m.group(0) + h.group(0), flags=re.M)
    probe = js + r"""
const one = [{ region: "ap-northeast-1", count: 1 }], two = [{ region: "ap-northeast-1", count: 2 }, { region: "ap-southeast-1", count: 1 }];
const unk = [{ region: "xx-test-9", count: 3 }, { region: "eastasia", count: 1 }];
console.log(JSON.stringify({ b0: regionsBrief([]), bn: regionsBrief(null), b1: regionsBrief(one), b2: regionsBrief(two), bu: regionsBrief(unk),
  d2: regionsDist(two), du: regionsDist(unk),
  c1: overviewCount({ provider: "aws", total: 3, running: 2, ec2: 2, lightsail: 1, lightsail_failed: false, errors: [] }),
  c2: overviewCount({ provider: "aws", total: 2, running: 2, ec2: 2, lightsail: 0, lightsail_failed: true, errors: [{ region: "eu-west-1" }] }),
  c3: overviewCount({ provider: "aws", total: 3, running: 3, ec2: 2, lightsail: 1, lightsail_failed: true, errors: [] }),
  c4: overviewCount({ provider: "oci", total: 3, running: 3, errors: [] }) }));
"""
    out = json.loads(subprocess.run([node, "-e", probe], capture_output=True, text=True, check=True).stdout)
    ok("js brief: none -> ''", out["b0"] == "" and out["bn"] == "")
    ok("js brief: one region -> 'ap-northeast-1 · 东京'", out["b1"] == "ap-northeast-1 · 东京")
    ok("js brief: two regions -> '东京 等 2 个区域'", out["b2"] == "东京 等 2 个区域")
    ok("js brief: unknown code falls back to code", out["bu"] == "xx-test-9 等 2 个区域")
    ok("js dist: '东京 2 · 新加坡 1'", out["d2"] == "东京 2 · 新加坡 1" and out["du"] == "xx-test-9 3 · 香港 1")
    ok("js count: aws '3 台（运行 2）· EC2 2 · Lightsail 1'", out["c1"] == "3 台（运行 2）· EC2 2 · Lightsail 1")
    ok("js count: lightsail failed + region error", out["c2"] == "2 台（运行 2）· EC2 2 · Lightsail 查询失败 · 1 个区域查询失败")
    ok("js count: lightsail partial failure", out["c3"] == "3 台（运行 3）· EC2 2 · Lightsail 1（部分区域失败）")
    ok("js count: oci has no EC2/Lightsail part", out["c4"] == "3 台（运行 3）")


# 区域城市表三端一致（core.js REGION_CITY / OCI_KEY == Regions.java == Regions.swift）
def js_maps():
    rc = re.search(r"export const REGION_CITY = (\{.*?\});", core_js, re.S).group(1)
    ok_ = re.search(r"const OCI_KEY = (\{.*?\});", core_js, re.S).group(1)
    return json.loads(subprocess.run([node, "-e", f"console.log(JSON.stringify([{rc}, {ok_}]))"], capture_output=True, text=True, check=True).stdout)


def java_map(name):
    d = {}
    for blk in re.findall(r"put\(%s,(.*?)\);" % name, SRC["android/app/src/main/java/com/tricloud/app/Regions.java"], re.S):
        xs = re.findall(r'"((?:[^"\\]|\\.)*)"', blk)
        d.update(dict(zip(xs[::2], xs[1::2])))
    return d


def swift_map(name):
    b = re.search(r"static let %s: \[String: String\] = \[(.*?)\n    \]" % name, SRC["ios/TriCloud/Regions.swift"], re.S).group(1)
    return dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', b))


if node:
    jc, jk = js_maps()
    ok("region map: core.js == Regions.java (city)", jc == java_map("CITY") and len(jc) >= 120)
    ok("region map: core.js == Regions.swift (city)", jc == swift_map("city"))
    ok("region map: OCI key table identical on all three", jk == java_map("OCI_KEY") == swift_map("ociKey") and len(jk) >= 40)

passed = sum(1 for _, x in R if x)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
