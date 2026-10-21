"""OCI 安全组按子网（security-subnets、security-rules?subnet_id，兼容旧 instance_id）+ 审计日志一键清空（DELETE /api/audit）。
全部用假客户端，不连接任何真实云。"""
import asyncio
import os
import sys
import tempfile

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
import sys as _s; _s.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _l10n_src  # noqa: E402
sys.path.insert(0, ROOT)
from unittest import mock

import oci  # noqa: F401
from fastapi.testclient import TestClient

from app import core, main, security, services, tasks, telegram
from app.providers.oci_provider import OCIProvider

R = []
core.init_db()
mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()


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


SUB_A, SUB_B, SUB_X = "ocid1.subnet.oc1.ap-tokyo-1.aaa", "ocid1.subnet.oc1.ap-tokyo-1.bbb", "ocid1.subnet.oc1.ap-tokyo-1.xother"
CALLS = []


class FakeCompute:
    def list_instances(self, compartment_id, **kw):
        CALLS.append("list_instances")
        return page([Obj(id="i-arm01", display_name="arm01", lifecycle_state="RUNNING"),
                     Obj(id="i-amd01", display_name="amd01", lifecycle_state="STOPPED"),
                     Obj(id="i-arm02", display_name="arm02", lifecycle_state="RUNNING"),
                     Obj(id="i-gone", display_name="gone", lifecycle_state="TERMINATED"),
                     Obj(id="i-far", display_name="far01", lifecycle_state="RUNNING")])

    def list_vnic_attachments(self, compartment_id, **kw):
        CALLS.append(("list_vnic_attachments", tuple(sorted(kw))))
        return page([Obj(instance_id="i-arm01", vnic_id="v1", subnet_id=SUB_A, lifecycle_state="ATTACHED"),
                     Obj(instance_id="i-arm01", vnic_id="v1b", subnet_id=SUB_A, lifecycle_state="ATTACHED"),   # 同实例第二块网卡同子网：只算一次
                     Obj(instance_id="i-amd01", vnic_id="v2", subnet_id=SUB_A, lifecycle_state="ATTACHED"),
                     Obj(instance_id="i-arm02", vnic_id="v3", subnet_id=SUB_A, lifecycle_state="ATTACHED"),
                     Obj(instance_id="i-gone", vnic_id="v4", subnet_id=SUB_B, lifecycle_state="ATTACHED"),
                     Obj(instance_id="i-arm02", vnic_id="v5", subnet_id=SUB_B, lifecycle_state="DETACHED"),
                     Obj(instance_id="i-far", vnic_id="v6", subnet_id=SUB_X, lifecycle_state="ATTACHED")])


class FakeVnet:
    def __init__(self):
        self.lists = {"sl-a": Obj(id="sl-a", display_name="Default Security List", ingress_security_rules=[
            OCIProvider._make_rule("ingress", "tcp", "0.0.0.0/0", "22", "ssh")], egress_security_rules=[]),
            "sl-b": Obj(id="sl-b", display_name="Private SL", ingress_security_rules=[
                OCIProvider._make_rule("ingress", "tcp", "10.0.0.0/16", "5432", "pg")], egress_security_rules=[])}
        self.subnets = {SUB_A: Obj(id=SUB_A, display_name="subnet-public", cidr_block="10.0.0.0/24", ipv6_cidr_blocks=["2603:c020::/64"],
                                   vcn_id="vcn-1", security_list_ids=["sl-a"], lifecycle_state="AVAILABLE"),
                        SUB_B: Obj(id=SUB_B, display_name="subnet-private", cidr_block="10.0.1.0/24", ipv6_cidr_blocks=None,
                                   vcn_id="vcn-1", security_list_ids=["sl-b"], lifecycle_state="AVAILABLE"),
                        SUB_X: Obj(id=SUB_X, display_name="shared-subnet", cidr_block="172.16.0.0/24", ipv6_cidr_blocks=[],
                                   vcn_id="vcn-x", security_list_ids=[], lifecycle_state="AVAILABLE")}
        self.vnics = {"v1": ["nsg-web"], "v1b": ["nsg-web", "nsg-db"], "v2": [], "v3": None, "v6": ["nsg-noname"]}

    def get_vnic(self, vid):
        if vid not in self.vnics:
            raise RuntimeError("vnic not found")
        sub = SUB_X if vid == "v6" else SUB_A
        return Obj(data=Obj(id=vid, subnet_id=sub, nsg_ids=self.vnics[vid]))

    def list_subnets(self, compartment_id, **kw):
        return page([self.subnets[SUB_A], self.subnets[SUB_B]])   # SUB_X 在别的区间，需要单独 get_subnet

    def get_subnet(self, sid):
        CALLS.append(("get_subnet", sid))
        if sid not in self.subnets:
            raise RuntimeError("NotAuthorizedOrNotFound")
        return Obj(data=self.subnets[sid])

    def list_vcns(self, compartment_id, **kw):
        return page([Obj(id="vcn-1", display_name="vcn-main")])

    def get_vcn(self, vid):
        return Obj(data=Obj(id=vid, display_name="vcn-shared"))

    def get_network_security_group(self, nid):
        CALLS.append(("get_nsg", nid))
        if nid == "nsg-noname":
            raise RuntimeError("denied")
        return Obj(data=Obj(id=nid, display_name={"nsg-web": "web-nsg", "nsg-db": "db-nsg"}[nid]))

    def get_security_list(self, sl_id):
        return Obj(data=self.lists[sl_id])

    def update_security_list(self, sl_id, d):
        if d.ingress_security_rules is not None:
            self.lists[sl_id].ingress_security_rules = d.ingress_security_rules
        if d.egress_security_rules is not None:
            self.lists[sl_id].egress_security_rules = d.egress_security_rules


VNET = FakeVnet()


def fake_oci(acc_id, region=None):
    p = OCIProvider.__new__(OCIProvider)
    p.cred, p.vnet, p.compute, p.compartment = {}, VNET, FakeCompute(), "ocid1.compartment.x"
    p._subnet_of = lambda inst_id: VNET.subnets[SUB_A]   # 旧接口：实例 → 主 VNIC 所在子网
    return p


# ================= 1. provider.security_subnets =================
r = fake_oci(1).security_subnets()
subs = {s["id"]: s for s in r["subnets"]}
ok("subnets: each subnet once (A, B, X)", sorted(subs) == sorted([SUB_A, SUB_B, SUB_X]) and len(r["subnets"]) == 3)
a = subs[SUB_A]
ok("subnets: A has VCN / name / CIDR / IPv6 / list count", a["vcn_name"] == "vcn-main" and a["name"] == "subnet-public" and a["cidr"] == "10.0.0.0/24"
   and a["ipv6_cidrs"] == ["2603:c020::/64"] and a["security_list_count"] == 1)
ok("subnets: A instances deduped + sorted (amd01, arm01, arm02)", [i["name"] for i in a["instances"]] == ["amd01", "arm01", "arm02"])
nsg = {i["name"]: [n["name"] for n in i["nsgs"]] for i in a["instances"]}
ok("subnets: NSG names merged across VNICs (arm01 web+db), none for others", nsg == {"amd01": [], "arm01": ["web-nsg", "db-nsg"], "arm02": []})
ok("subnets: terminated / detached ignored -> B has no instances", subs[SUB_B]["instances"] == [])
ok("subnets: subnet in other compartment fetched (get_subnet) with VCN name", subs[SUB_X]["vcn_name"] == "vcn-shared" and ("get_subnet", SUB_X) in CALLS
   and [i["name"] for i in subs[SUB_X]["instances"]] == ["far01"])
ok("subnets: unreadable NSG name -> OCID tail", subs[SUB_X]["instances"][0]["nsgs"][0]["name"].endswith("noname"[-6:]) or "…" in subs[SUB_X]["instances"][0]["nsgs"][0]["name"])
ok("subnets: subnets with instances first, empty last", r["subnets"][-1]["id"] == SUB_B)
ok("subnets: vnic attachments listed once for whole compartment (no instance filter)", [c for c in CALLS if isinstance(c, tuple) and c[0] == "list_vnic_attachments"] == [("list_vnic_attachments", ())])
ok("subnets: NSG name fetched once per NSG", sum(1 for c in CALLS if c == ("get_nsg", "nsg-web")) == 1)
VNET.vnics.pop("v2")
r2 = fake_oci(1).security_subnets()
ok("subnets: unreadable VNIC still grouped via attachment subnet, error reported",
   "amd01" in [i["name"] for i in {s["id"]: s for s in r2["subnets"]}[SUB_A]["instances"]] and any("VNIC" in e for e in r2["errors"]))
VNET.vnics["v2"] = []

# ================= 2. 路由 =================
with TestClient(main.app) as c:
    anon = TestClient(main.app)
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}):
        oid = c.post("/api/accounts", json={"provider": "oci", "name": "oci-tokyo", "cred": {
            "user": "ocid1.user.oc1..fakeuser123456", "tenancy": "ocid1.tenancy.oc1..faketen654321", "fingerprint": "aa:bb",
            "key_content": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n", "region": "ap-tokyo-1"}}).json()["id"]
    with mock.patch.object(services, "provider", fake_oci):
        j = c.get(f"/api/accounts/{oid}/oci/security-subnets?region=ap-tokyo-1")
        ok("route security-subnets: 200 + subnets", j.status_code == 200 and len(j.json()["subnets"]) == 3)
        ok("route security-subnets: needs login", anon.get(f"/api/accounts/{oid}/oci/security-subnets").status_code == 401)
        g = c.get(f"/api/accounts/{oid}/security-rules?subnet_id={SUB_B}")
        ok("rules by subnet_id: that subnet's list (5432)", g.status_code == 200 and [x["port"] for x in g.json()["rules"]] == ["5432"]
           and g.json()["lists"] == [{"id": "sl-b", "name": "Private SL"}])
        g2 = c.get(f"/api/accounts/{oid}/security-rules?instance_id=i-arm01")
        ok("rules by instance_id still works (App compatibility)", g2.status_code == 200 and [x["port"] for x in g2.json()["rules"]] == ["22"])
        ok("rules: neither subnet_id nor instance_id -> 400", c.get(f"/api/accounts/{oid}/security-rules").status_code == 400)
        ok("rules: bad subnet_id -> 400", c.get(f"/api/accounts/{oid}/security-rules?subnet_id=sl-a").status_code == 400)
        ok("rules: subnet_id wins over instance_id", [x["port"] for x in c.get(f"/api/accounts/{oid}/security-rules?subnet_id={SUB_B}&instance_id=i-arm01").json()["rules"]] == ["5432"])
        p = c.post(f"/api/accounts/{oid}/security-rules", json={"subnet_id": SUB_B, "direction": "ingress", "protocol": "tcp", "cidr": "10.0.5.0/24", "ports": "6379, 6380"})
        ok("add by subnet_id: written to that subnet's list", p.status_code == 200 and p.json()["added"] == 2 and p.json()["sl_id"] == "sl-b"
           and len(VNET.lists["sl-b"].ingress_security_rules) == 3 and len(VNET.lists["sl-a"].ingress_security_rules) == 1)
        p = c.post(f"/api/accounts/{oid}/security-rules", json={"subnet_id": SUB_B, "sl_id": "sl-a", "direction": "ingress", "protocol": "tcp", "cidr": "10.0.5.0/24", "ports": "1"})
        ok("add by subnet_id: sl_id of another subnet refused", p.status_code == 400 and "所选子网" in p.json()["detail"])
        p = c.post(f"/api/accounts/{oid}/security-rules", json={"subnet_id": SUB_X, "direction": "ingress", "protocol": "tcp", "cidr": "10.0.5.0/24", "ports": "1"})
        ok("add by subnet_id: subnet without security list -> 400", p.status_code == 400 and "没有安全列表" in p.json()["detail"])
        p = c.post(f"/api/accounts/{oid}/security-rules", json={"subnet_id": SUB_B, "direction": "ingress", "protocol": "tcp", "cidr": "0.0.0.0/0", "ports": "443"})
        ok("add by subnet_id: public still needs confirm (409)", p.status_code == 409)
        p = c.post(f"/api/accounts/{oid}/security-rules", json={"instance_id": "i-arm01", "direction": "ingress", "protocol": "tcp", "cidr": "10.9.0.0/16", "ports": "8080"})
        ok("add by instance_id still works (App)", p.status_code == 200 and p.json()["sl_id"] == "sl-a")
        ok("add: neither id -> 400", c.post(f"/api/accounts/{oid}/security-rules", json={"direction": "ingress", "protocol": "tcp", "cidr": "10.0.0.0/8", "ports": "1"}).status_code == 400)
        dl = c.request("DELETE", f"/api/accounts/{oid}/security-rules", json={"subnet_id": SUB_B, "direction": "ingress", "protocol": "tcp", "cidr": "10.0.5.0/24", "port_min": 6379, "port_max": 6379})
        ok("delete by subnet_id", dl.status_code == 200 and dl.json()["sl_id"] == "sl-b" and len(VNET.lists["sl-b"].ingress_security_rules) == 2)
        dl = c.request("DELETE", f"/api/accounts/{oid}/security-rules", json={"instance_id": "i-arm01", "direction": "ingress", "protocol": "tcp", "cidr": "10.9.0.0/16", "port_min": 8080, "port_max": 8080})
        ok("delete by instance_id still works (App)", dl.status_code == 200 and dl.json()["sl_id"] == "sl-a")
        ok("delete: neither id -> 400", c.request("DELETE", f"/api/accounts/{oid}/security-rules", json={"direction": "ingress", "protocol": "tcp", "cidr": "10.0.0.0/8"}).status_code == 400)

    # ================= 3. 审计日志一键清空 =================
    for i in range(5):
        security.audit("192.0.2.9", "session", f"POST /api/x{i}", "HTTP 200")
    n0 = core.q("SELECT COUNT(*) n FROM audit", one=True)["n"]
    ok("audit clear: needs login (401), nothing deleted", anon.delete("/api/audit?confirm=true").status_code == 401
       and core.q("SELECT COUNT(*) n FROM audit", one=True)["n"] >= n0)
    r0 = c.delete("/api/audit")
    ok("audit clear: without confirm -> 400, nothing deleted", r0.status_code == 400 and "confirm" in r0.json()["detail"]
       and core.q("SELECT COUNT(*) n FROM audit", one=True)["n"] >= n0)
    ok("audit clear: confirm=false -> 400", c.delete("/api/audit?confirm=false").status_code == 400)
    n1 = core.q("SELECT COUNT(*) n FROM audit", one=True)["n"]
    r1 = c.delete("/api/audit?confirm=true", headers={"X-Forwarded-For": "198.51.100.77"})
    rows = core.q("SELECT * FROM audit")
    ok("audit clear: 200 + deleted count", r1.status_code == 200 and r1.json()["deleted"] == n1 and n1 > 5)
    ok("audit clear: only the audit-clear record remains", len(rows) == 1 and rows[0]["action"] == "audit-clear" and rows[0]["detail"] == f"清空了 {n1} 条")
    ok("audit clear: record keeps who / when / IP", rows[0]["actor"] == "session" and rows[0]["ts"] > 0 and rows[0]["ip"])
    lst = c.get("/api/audit").json()
    ok("audit clear: GET /api/audit shows just that record", len(lst) == 1 and lst[0]["action"] == "audit-clear")
    tok = c.post("/api/tokens", json={"name": "bot", "scope": "full"}).json()["token"]
    tc = TestClient(main.app)
    rt = tc.delete("/api/audit?confirm=true", headers={"Authorization": f"Bearer {tok}"})
    ok("audit clear: API Token refused (403), GET still allowed", rt.status_code == 403 and tc.get("/api/audit", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
       and any(x["action"] == "audit-clear" for x in core.q("SELECT * FROM audit")))
    ok("audit clear: other writes still audited after clear", any(x["action"] == "POST /api/tokens" for x in core.q("SELECT * FROM audit")))
    ok("audit clear: failed (400) attempt is audited by middleware", (c.delete("/api/audit") and True)
       and any(x["action"] == "DELETE /api/audit" and "400" in x["detail"] for x in core.q("SELECT * FROM audit")))

# ================= 4. Web / demo 静态检查 =================
W = _l10n_src.read(os.path.join(ROOT, "web", "js", "oci.js"))
S = _l10n_src.read(os.path.join(ROOT, "web", "js", "settings.js"))
M = open(os.path.join(ROOT, "demo", "mock.js"), encoding="utf-8").read()
ok("web: secgroup uses subnet dropdown + security-subnets, no instance dropdown", 'id="sgSub"' in W and "/oci/security-subnets?" in W and 'id="sgInst"' not in W)
ok("web: rules / add / delete use subnet_id", "security-rules?subnet_id=" in W and W.count("subnet_id: sid") == 2)
ok("web: NSG read-only hint + localStorage tc_sgsub_", "此实例另挂 NSG：" in W and '"tc_sgsub_"' in W)
ok("web: audit clear button + red confirm + DELETE confirm=true", 'id="auClr"' in S and "不可恢复" in S and '"/audit?confirm=true", { method: "DELETE" }' in S)
ok("demo mock: security-subnets + audit DELETE", "/oci\\/security-subnets$/" in M and 'p === "/audit" && method === "DELETE"' in M)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
