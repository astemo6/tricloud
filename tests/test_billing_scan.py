"""保号账单「先检测已有存储」自测：各存储层汇总、>10 GB 判断、补足大小计算、size_gb 范围、跨区域 / 区间扫描、
Bucket 列表大小 / 对象数 / 存储层、扫描接口缓存与失效，以及 Web / demo 静态检查。全部用假客户端，不连接任何真实云。"""
import asyncio
import json
import os
import sys
import tempfile

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

import oci
from fastapi.testclient import TestClient

from app import core, main, services, tasks, telegram
from app.providers import oci_more
from app.providers.oci_more import ceil01, fill_size_gb, summarize_storage
from app.providers.oci_provider import OCIProvider
from app.routers import oci as oci_routes

R = []
core.init_db()
G = 1024 ** 3


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


def page(data):
    return Obj(data=data, has_next_page=False, next_page=None, headers={}, status=200, request=None)


# ================= 1. 补足大小 / 汇总（纯函数） =================
ok("fill: nothing stored -> 11", fill_size_gb(0) == 11)
ok("fill: 3.2 used -> 7.8", fill_size_gb(3.2) == 7.8)
ok("fill: rounds UP to 0.1 (8.71 used -> 2.3)", fill_size_gb(8.71) == 2.3)
ok("fill: float noise does not over-round (7.0 used -> 4.0, 3.04 -> 8.0)", fill_size_gb(7.0) == 4.0 and fill_size_gb(3.04) == 8.0)
ok("fill: minimum 0.5 (10.6 / 10.95 / 30 used -> 0.5)", fill_size_gb(10.6) == 0.5 and fill_size_gb(10.95) == 0.5 and fill_size_gb(30) == 0.5)
ok("fill: None used treated as 0", fill_size_gb(None) == 11)
ok("ceil01: exact tenths stay, negatives -> 0", ceil01(0.3) == 0.3 and ceil01(6.8) == 6.8 and ceil01(-2) == 0)

bs = [{"name": "alive", "region": "us-sanjose-1", "size": int(3.2 * G), "count": 1, "storage_tier": "Standard", "auto_tiering": "Disabled"},
      {"name": "media", "region": "us-sanjose-1", "size": int(1.5 * G), "count": 9, "storage_tier": "Standard", "auto_tiering": "InfrequentAccess"},
      {"name": "cold", "region": "ap-tokyo-1", "size": 2 * G, "count": 1, "storage_tier": "Archive", "auto_tiering": None},
      {"name": "broken", "region": "ap-tokyo-1", "size": None, "count": None, "storage_tier": None, "auto_tiering": None, "error": "403"},
      {"name": "small", "region": "ap-tokyo-1", "size": 512 * 1024 ** 2, "count": 3, "storage_tier": "Standard", "auto_tiering": None}]
s = summarize_storage(bs)
ok("summary: standard = only Standard buckets without auto-tiering (alive + small)", abs(s["standard_gb"] - 3.7) < 1e-3 and s["bytes"]["standard"] == int(3.2 * G) + 512 * 1024 ** 2)
ok("summary: auto-tiering bucket flagged separately, not counted as standard", abs(s["autotier_gb"] - 1.5) < 1e-3
   and next(b for b in s["buckets"] if b["name"] == "media")["tier"] == "autotier")
ok("summary: archive separate", s["archive_gb"] == 2 and next(b for b in s["buckets"] if b["name"] == "cold")["tier"] == "archive")
ok("summary: unreadable bucket -> unknown, counted, not summed", s["unknown_count"] == 1 and next(b for b in s["buckets"] if b["name"] == "broken")["tier"] == "unknown")
ok("summary: < 10 GB -> not over, short 6.3, fill 7.3", not s["over_free"] and s["short_gb"] == 6.3 and s["fill_gb"] == 7.3 and s["free_gb"] == 10)
ok("summary: sorted by size desc", [b["name"] for b in s["buckets"]][:2] == ["alive", "cold"])
s2 = summarize_storage([{"name": "alive", "size": int(10.9 * G), "storage_tier": "Standard", "auto_tiering": "Disabled"}])
ok("summary: > 10 GB standard -> over_free, short 0, fill min 0.5", s2["over_free"] and s2["short_gb"] == 0 and s2["fill_gb"] == 0.5)
s3 = summarize_storage([{"name": "x", "size": 10 * G, "storage_tier": "Standard"}])
ok("summary: exactly 10 GB is NOT over (free covers it), short >= 0.1", not s3["over_free"] and s3["short_gb"] == 0.1 and s3["fill_gb"] == 1)
s4 = summarize_storage([{"name": "m", "size": 15 * G, "storage_tier": "Standard", "auto_tiering": "InfrequentAccess"}])
ok("summary: 15 GB only in auto-tiering bucket -> not counted as over", not s4["over_free"] and s4["fill_gb"] == 11)
ok("summary: empty account", summarize_storage([])["standard_gb"] == 0 and summarize_storage([])["fill_gb"] == 11)


# ================= 2. provider：跨区域 / 区间扫描 =================
def se(status):
    return oci.exceptions.ServiceError(status, "Err", {}, "x")


class FakeOS:
    def __init__(self, region, store):
        self.region, self.store, self.calls = region, store, []

    def get_namespace(self, **kw):
        return Obj(data="ns1")

    def list_buckets(self, ns, comp, **kw):
        self.calls.append(("list_buckets", comp))
        if (self.region, comp) == ("ap-osaka-1", "c-denied"):
            raise se(400)           # 不可重试的错误（500 会被 SDK 分页器自动重试）
        return page([Obj(name=n, time_created="2025-06-27 08:30:00") for n in self.store.get((self.region, comp), {})])

    def get_bucket(self, ns, name, **kw):
        self.calls.append(("get_bucket", name, tuple(kw.get("fields") or ())))
        for (rg, _c), bs_ in self.store.items():
            if rg == self.region and name in bs_:
                v = bs_[name]
                if v == "fail":
                    raise se(403)
                return Obj(data=Obj(name=name, approximate_size=v[0], approximate_count=v[1], storage_tier=v[2], auto_tiering=v[3]))
        raise se(404)

    def list_objects(self, *a, **kw):
        raise AssertionError("scan must not list objects")


STORE = {("us-sanjose-1", "ocid1.tenancy.x"): {"alive": (int(3.2 * G), 1, "Standard", "Disabled")},
         ("ap-tokyo-1", "ocid1.tenancy.x"): {"tricloud-billing-keep": (0, 0, "Standard", "Disabled"), "flaky": "fail"},
         ("ap-tokyo-1", "c-child"): {"archive1": (2 * G, 4, "Archive", None)},
         ("ap-osaka-1", "c-child"): {"auto1": (G, 2, "Standard", "InfrequentAccess")}}


def prov(comps_fail=False):
    p = OCIProvider.__new__(OCIProvider)
    p.cred, p.compartment, p.cfg, p.proxy = {}, "ocid1.tenancy.x", {"tenancy": "ocid1.tenancy.x", "region": "ap-osaka-1"}, None
    clients = {}

    def lc(t, **kw):
        if comps_fail:
            raise se(404)
        return page([Obj(id="c-child"), Obj(id="c-denied")])
    p.identity = Obj(list_region_subscriptions=lambda t: Obj(data=[Obj(region_name="ap-osaka-1", is_home_region=False, status="READY"),
                                                                    Obj(region_name="ap-tokyo-1", is_home_region=True, status="READY"),
                                                                    Obj(region_name="us-sanjose-1", is_home_region=False, status="READY"),
                                                                    Obj(region_name="eu-paris-1", is_home_region=False, status="IN_PROGRESS")]),
                     list_compartments=lc)
    p._c = lambda cls, cfg=None: clients.setdefault(cfg["region"], FakeOS(cfg["region"], STORE))
    p._clients_seen = clients
    return p


p = prov()
r = p.storage_scan()
names = {b["name"]: b for b in r["buckets"]}
ok("scan: all READY subscribed regions, home first, not-ready skipped", r["regions"] == ["ap-tokyo-1", "ap-osaka-1", "us-sanjose-1"] and r["home"] == "ap-tokyo-1")
ok("scan: root + child compartments scanned", r["compartments"] == 3 and not r["compartments_truncated"])
ok("scan: finds bucket in another region (alive, us-sanjose-1) and counts it as standard", names["alive"]["region"] == "us-sanjose-1"
   and names["alive"]["tier"] == "standard" and abs(r["standard_gb"] - 3.2) < 1e-3)
ok("scan: child-compartment archive + auto-tiering buckets classified", names["archive1"]["tier"] == "archive" and names["auto1"]["tier"] == "autotier"
   and r["archive_gb"] == 2 and r["autotier_gb"] == 1)
ok("scan: own billing-keep bucket marked", names["tricloud-billing-keep"]["billing_keep"] and not names["alive"]["billing_keep"])
ok("scan: GetBucket failure -> size None (—), not fatal", names["flaky"]["size"] is None and r["unknown_count"] == 1)
ok("scan: ListBuckets error in one region/compartment reported, scan continues", any(e["region"] == "ap-osaka-1" for e in r["errors"]) and len(r["buckets"]) == 5)
ok("scan: verdict short 6.8 / fill 7.8", not r["over_free"] and r["short_gb"] == 6.8 and r["fill_gb"] == 7.8)
gb_calls = [c for cl in p._clients_seen.values() for c in cl.calls if c[0] == "get_bucket"]
lb_calls = [c for cl in p._clients_seen.values() for c in cl.calls if c[0] == "list_buckets"]
ok("scan: GetBucket asks for approximateSize + approximateCount", all("approximateSize" in c[2] and "approximateCount" in c[2] for c in gb_calls) and len(gb_calls) == 5)
ok("scan: request count = regions×compartments ListBuckets + buckets GetBucket", len(lb_calls) == 9 and r["requests"] == 9 + 5)
r2 = prov(comps_fail=True).storage_scan()
ok("scan: no compartment inspect permission -> falls back to configured compartment only", r2["compartments"] == 1 and {b["name"] for b in r2["buckets"]} == {"alive", "tricloud-billing-keep", "flaky"})
src = open(os.path.join(ROOT, "app", "providers", "oci_more.py"), encoding="utf-8").read()
seg = src[src.index("def storage_scan"):src.index("def _bk_bucket")]
ok("scan: read-only (no create/delete/update/put)", not any(x in seg for x in ("create_", "delete_", "update_", "put_", "abort_")))

# Bucket 列表：大小 / 对象数 / 存储层
p = prov()
p._os, p._ns = FakeOS("ap-tokyo-1", STORE), "ns1"
p.compartment = "ocid1.tenancy.x"
bl = p.buckets()
rows = {b["name"]: b for b in bl["buckets"]}
ok("buckets: rows carry size / count / storage tier", rows["tricloud-billing-keep"]["size"] == 0 and rows["tricloud-billing-keep"]["count"] == 0
   and rows["tricloud-billing-keep"]["storage_tier"] == "Standard" and rows["tricloud-billing-keep"]["created"] == "2025-06-27 08:30")
ok("buckets: one GetBucket failing -> None values + error, list still returned", rows["flaky"]["size"] is None and rows["flaky"]["count"] is None and rows["flaky"].get("error"))
ok("buckets: no buckets -> no GetBucket", (lambda q: (setattr(q, "_os", FakeOS("eu-x", {})), setattr(q, "_ns", "ns1"), q.buckets()["buckets"])[2])(prov()) == [])


# ================= 3. 路由：/billing-keep/scan 缓存与失效、size_gb 范围 =================
class FP:
    def __init__(self):
        self.n = 0

    def storage_scan(self):
        self.n += 1
        return dict(summarize_storage([{"name": "alive", "region": "us-sanjose-1", "size": int(3.2 * G), "storage_tier": "Standard", "auto_tiering": "Disabled"}]),
                    regions=["ap-tokyo-1", "us-sanjose-1"], home="ap-tokyo-1", compartments=1, compartments_truncated=False, errors=[], requests=3)

    def billing_keep_status(self):
        return {"region": "ap-tokyo-1", "bucket": "tricloud-billing-keep", "object": "billing-keep.bin", "exists": False, "size": 0, "pending_uploads": []}

    def billing_keep_delete(self):
        return {"ok": True, "deleted": True}

    def create_bucket(self, name, public=False):
        return {"ok": True}


mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()

with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}):
        oid = c.post("/api/accounts", json={"provider": "oci", "name": "payg", "cred": {
            "user": "ocid1.user.oc1..fakeuser123456", "tenancy": "ocid1.tenancy.oc1..faketen654321", "fingerprint": "aa:bb",
            "key_content": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n", "region": "ap-tokyo-1"}}).json()["id"]
    core.ex("UPDATE accounts SET acct_type=? WHERE id=?", (json.dumps({"plan_type": "PAYG"}), oid))
    fp = FP()
    U = f"/api/accounts/{oid}/oci/billing-keep"
    with mock.patch.object(services, "provider", lambda acc_id, region=None: fp):
        j = c.get(U + "/scan").json()
        ok("route scan: summary + verdict fields", abs(j["standard_gb"] - 3.2) < 1e-3 and j["fill_gb"] == 7.8 and j["short_gb"] == 6.8
           and j["over_free"] is False and j["buckets"][0]["name"] == "alive" and not j["cached"] and j.get("scanned_at"))
        j2 = c.get(U + "/scan").json()
        ok("route scan: second call within TTL served from cache (no new OCI scan)", j2["cached"] and fp.n == 1)
        ok("route scan: refresh=true bypasses cache", not c.get(U + "/scan?refresh=true").json()["cached"] and fp.n == 2)
        ts, cached = oci_routes._BK_SCAN[oid]
        oci_routes._BK_SCAN[oid] = (ts - oci_routes.BK_SCAN_TTL - 1, cached)
        ok("route scan: expires after TTL (5 min)", not c.get(U + "/scan").json()["cached"] and fp.n == 3 and oci_routes.BK_SCAN_TTL == 300)
        oci_routes._BK_SCAN.clear()
        c.get(U + "/scan")
        n0 = fp.n
        c.post(f"/api/accounts/{oid}/oci/buckets", json={"op": "create", "name": "new1"})
        ok("route scan: bucket create invalidates cache", not c.get(U + "/scan").json()["cached"] and fp.n == n0 + 1)
        c.delete(U + "?confirm=true")
        ok("route scan: billing-keep DELETE invalidates cache", not c.get(U + "/scan").json()["cached"])
        r = c.post(U, json={"confirm": True, "size_gb": 7.8})
        t = core.q("SELECT * FROM tasks WHERE id=?", (r.json().get("task_id"),), one=True)
        ok("route: fill size 7.8 accepted -> task with 7.8 GiB", t and json.loads(t["params"])["size_bytes"] == round(7.8 * G))
        ok("route: POST invalidates scan cache", oid not in oci_routes._BK_SCAN)
        tasks._update(t["id"], status="done", message="ok", result={"size": 1})
        ok("route: 0.5 accepted, 0.49 / 20.1 refused, still needs confirm",
           c.post(U, json={"size_gb": 0.49, "confirm": True}).status_code == 400 and c.post(U, json={"size_gb": 20.1, "confirm": True}).status_code == 400
           and c.post(U, json={"size_gb": 0.5}).status_code == 400 and c.post(U, json={"size_gb": 0.5, "confirm": True}).status_code == 200)
        j = c.get(U).json()
        ok("route GET: min_gb 0.5, max 20, note mentions existing buckets", j["min_gb"] == 0.5 and j["max_gb"] == 20 and "已有 Bucket" in j["note"])
        core.ex("UPDATE accounts SET acct_type=? WHERE id=?", (json.dumps({"plan_type": "FREE_TIER"}), oid))
        r = c.post(U, json={"size_gb": 1, "confirm": True})
        ok("route: free account still refused with original hint", r.status_code == 400 and "免费号 20GB 内不收费，无需操作" in r.json()["detail"])
        core.ex("UPDATE accounts SET acct_type=? WHERE id=?", (json.dumps({"plan_type": "PAYG"}), oid))

        def boom():
            raise se(500)
        fp.storage_scan = boom
        oci_routes._BK_SCAN.clear()
        ok("route scan: OCI ServiceError -> 400 (not 500)", c.get(U + "/scan").status_code == 400)
        from app.providers.aws_provider import AWSProvider
        with mock.patch.object(AWSProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)), \
                mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
            aws = c.post("/api/accounts", json={"provider": "aws", "name": "a", "cred": {"access_key": "AKIAFAKEFAKE1234", "secret_key": "s", "region": "us-east-1"}})
        ok("route scan: OCI only", c.get(f"/api/accounts/{aws.json()['id']}/oci/billing-keep/scan").status_code == 400)

ok("constants: target 11, free 10", oci_more.BK_TARGET_GB == 11 and oci_more.PAYG_STD_FREE_GB == 10)

# ================= 4. Web / demo 静态检查 =================
web = open(os.path.join(ROOT, "web", "js", "oci.js"), encoding="utf-8").read()
mockjs = open(os.path.join(ROOT, "demo", "mock.js"), encoding="utf-8").read()
demo = open(os.path.join(ROOT, "demo", "index.html"), encoding="utf-8").read()
ok("web: bucket list has size / count / tier columns with — fallback", "<th>大小</th><th>对象数</th><th>存储层</th>" in web and '"—"' in web)
ok("web: card scans first and shows verdict", "正在检测已有存储…" in web and "/billing-keep/scan" in web and "已满足" in web and "还差" in web
   and "标准层已用" in web and "补足后标准层合计约" in web)
ok("web: over 10 GB -> secondary button + extra confirm", "无需生成" in web and '"btn ${over ? "" : "primary"}"' in web)
ok("web: client fill formula mirrors backend (min 0.5, ceil 0.1)", "export function bkFill" in web and "Math.max(0.5" in web)
ok("demo: mock covers scan + bucket sizes, demo rebuilt", "billing-keep\\/scan$/" in mockjs and "bucketsOther" in mockjs and "alive" in demo
   and "正在检测已有存储" in demo and "0.5–20" in mockjs)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
