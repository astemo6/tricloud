"""build 19：OCI 子网 / VCN 改名（PATCH /oci/subnets/{id}、/oci/vcns/{id}）+ Lightsail 区域（/regions?service=lightsail，
不支持的区域友好 400，区域扫描跳过）。全部用假客户端，不连接任何真实云。"""
import asyncio
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

import oci  # noqa: F401
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient

from app import core, main, services, tasks, telegram
from app.providers import aws_provider
from app.providers.aws_provider import AWSProvider
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


SUB, VCN = "ocid1.subnet.oc1.ap-tokyo-1.aaaa1111", "ocid1.vcn.oc1.ap-tokyo-1.vvvv2222"
OCALLS = []


class FakeVnet:
    def __init__(self):
        self.names = {SUB: "subnet-public", VCN: "vcn-main"}
        self.rules_touched = False

    def get_subnet(self, sid):
        if sid not in self.names:
            raise RuntimeError("NotAuthorizedOrNotFound")
        return Obj(data=Obj(id=sid, display_name=self.names[sid]))

    def update_subnet(self, sid, d):
        OCALLS.append(("update_subnet", sid, type(d).__name__, d.display_name, getattr(d, "security_list_ids", None)))
        self.names[sid] = d.display_name
        return Obj(data=Obj(id=sid, display_name=d.display_name))

    def get_vcn(self, vid):
        return Obj(data=Obj(id=vid, display_name=self.names[vid]))

    def update_vcn(self, vid, d):
        OCALLS.append(("update_vcn", vid, type(d).__name__, d.display_name))
        self.names[vid] = d.display_name
        return Obj(data=Obj(id=vid, display_name=d.display_name))

    def update_security_list(self, *a, **kw):
        self.rules_touched = True


VNET = FakeVnet()


def fake_oci():
    p = OCIProvider.__new__(OCIProvider)
    p.cred, p.vnet, p.compartment = {}, VNET, "ocid1.compartment.x"
    return p


# ================= 1. provider 改名 =================
r = fake_oci().rename_subnet(SUB, "web-subnet")
ok("provider rename_subnet: UpdateSubnetDetails(display_name) only", OCALLS[-1][:4] == ("update_subnet", SUB, "UpdateSubnetDetails", "web-subnet")
   and OCALLS[-1][4] is None)
ok("provider rename_subnet: returns old + new name", r == {"id": SUB, "old_name": "subnet-public", "name": "web-subnet"})
r = fake_oci().rename_vcn(VCN, "vcn-prod")
ok("provider rename_vcn: UpdateVcnDetails + old/new", OCALLS[-1] == ("update_vcn", VCN, "UpdateVcnDetails", "vcn-prod") and r["old_name"] == "vcn-main")
ok("provider rename: security lists untouched", not VNET.rules_touched)

# ================= 2. Lightsail 区域（provider） =================
LCALLS = []
EC2_REGIONS = ["ap-east-2", "ap-northeast-1", "ap-southeast-1", "us-east-1", "us-west-2", "eu-south-1"]
LS_REGIONS = ["ap-northeast-1", "ap-southeast-1", "us-east-1", "us-west-2", "eu-central-1"]


class FakeEc2:
    def __init__(self, rg):
        self.rg = rg

    def describe_regions(self):
        return {"Regions": [{"RegionName": x} for x in EC2_REGIONS]}

    def get_paginator(self, name):
        rg = self.rg
        return Obj(paginate=lambda: [{"Reservations": [{"Instances": [{"State": {"Name": "running"}}]}] if rg == "ap-east-2" else []}])


class FakeLs:
    def __init__(self, rg):
        self.rg = rg

    def get_regions(self):
        LCALLS.append(("get_regions", self.rg))
        if FAIL_GETREGIONS[0]:
            raise RuntimeError("AccessDenied")
        return {"regions": [{"name": x} for x in LS_REGIONS]}

    def get_instances(self):
        LCALLS.append(("get_instances", self.rg))
        return {"instances": [{"name": "ls1"}] if self.rg == "ap-northeast-1" else []}


FAIL_GETREGIONS = [False]


class FakeSession:
    def client(self, svc, region_name=None, config=None):
        return {"ec2": FakeEc2, "lightsail": FakeLs}[svc](region_name)


def fake_aws(region="ap-northeast-1"):
    p = AWSProvider({"access_key": "AKIAFAKE", "secret_key": "fake", "region": "ap-northeast-1"}, region)
    p.session = FakeSession()
    return p


ok("static lightsail regions from botocore: has ap-northeast-1, not ap-east-2",
   "ap-northeast-1" in aws_provider.ls_static_regions() and "ap-east-2" not in aws_provider.ls_static_regions())
aws_provider._LS_GETREGIONS.clear()
rs = fake_aws().ls_regions()
ok("ls_regions: enabled ∩ GetRegions (no ap-east-2, no not-enabled eu-central-1, no eu-south-1)",
   rs == ["ap-northeast-1", "ap-southeast-1", "us-east-1", "us-west-2"])
n0 = sum(1 for c in LCALLS if c[0] == "get_regions")
fake_aws().ls_regions()
ok("ls_regions: GetRegions cached (no second call)", sum(1 for c in LCALLS if c[0] == "get_regions") == n0 == 1)
aws_provider._LS_GETREGIONS.clear()
FAIL_GETREGIONS[0] = True
rs2 = fake_aws().ls_regions()
ok("ls_regions: GetRegions fails -> botocore table ∩ enabled, still no ap-east-2",
   "ap-east-2" not in rs2 and "ap-northeast-1" in rs2 and set(rs2) <= set(EC2_REGIONS))
FAIL_GETREGIONS[0] = False
aws_provider._LS_GETREGIONS.clear()
fake_aws().ls_regions()
try:
    fake_aws("ap-east-2").c("lightsail")
    ok("client guard: lightsail in ap-east-2 refused", False)
except core.LightsailRegionError as e:
    ok("client guard: lightsail in ap-east-2 -> LightsailRegionError with city", str(e) == "Lightsail 不支持该区域（台北 ap-east-2），请换区域")
ok("client guard: ec2 in ap-east-2 still fine", isinstance(fake_aws("ap-east-2").c("ec2"), FakeEc2))
ok("client guard: lightsail in ap-northeast-1 fine", isinstance(fake_aws().c("lightsail"), FakeLs))
ok("LightsailRegionError is ValueError (call() wrappers give 400)", issubclass(core.LightsailRegionError, ValueError))
LCALLS.clear()
with mock.patch.object(aws_provider.time, "sleep", lambda s: None):
    scan = {x["region"]: x for x in fake_aws().scan_all_regions()}
ok("scan: ap-east-2 EC2 counted, lightsail None (shown -), no error", scan["ap-east-2"]["ec2"] == 1 and scan["ap-east-2"]["lightsail"] is None
   and "error" not in scan["ap-east-2"])
ok("scan: no lightsail call to unsupported regions", ("get_instances", "ap-east-2") not in LCALLS and ("get_instances", "eu-south-1") not in LCALLS)
ok("scan: supported region lightsail counted", scan["ap-northeast-1"]["lightsail"] == 1)

# EndpointConnectionError 兜底（区域表没覆盖到时）
resp = asyncio.run(main.err(None, EndpointConnectionError(endpoint_url="https://lightsail.ap-east-2.amazonaws.com/")))
ok("error handler: lightsail EndpointConnectionError -> friendly 400", resp.status_code == 400 and "Lightsail 不支持该区域（台北 ap-east-2）" in resp.body.decode())
resp = asyncio.run(main.err(None, EndpointConnectionError(endpoint_url="https://ec2.xx-1.amazonaws.com/")))
ok("error handler: other EndpointConnectionError unchanged (500)", resp.status_code == 500)

# ================= 3. 路由 =================
with TestClient(main.app) as c:
    anon = TestClient(main.app)
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}), \
            mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)):
        oid = c.post("/api/accounts", json={"provider": "oci", "name": "oci-tokyo", "cred": {
            "user": "ocid1.user.oc1..fakeuser123456", "tenancy": "ocid1.tenancy.oc1..faketen654321", "fingerprint": "aa:bb",
            "key_content": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n", "region": "ap-tokyo-1"}}).json()["id"]
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        aid = c.post("/api/accounts", json={"provider": "aws", "name": "aws-a", "cred": {"access_key": "AKIAFAKE00000000", "secret_key": "fake", "region": "ap-northeast-1"}}).json()["id"]

    def prov(acc_id, region=None):
        return fake_oci() if acc_id == oid else fake_aws(region or "ap-northeast-1")

    with mock.patch.object(services, "provider", prov):
        base = f"/api/accounts/{oid}/oci"
        j = c.patch(f"{base}/subnets/{SUB}", json={"display_name": "  app-subnet  ", "region": "ap-tokyo-1"})
        ok("route subnet rename: 200, trimmed", j.status_code == 200 and j.json()["name"] == "app-subnet" and VNET.names[SUB] == "app-subnet")
        ok("route subnet rename: old_name returned", j.json()["old_name"] == "web-subnet")
        au = core.q("SELECT * FROM audit WHERE action='oci-subnet-rename'")
        ok("route subnet rename: audit record with old → new", len(au) == 1 and "web-subnet → app-subnet" in au[0]["detail"] and au[0]["actor"] == "session")
        ok("route subnet rename: middleware audit too", any(x["action"].startswith("PATCH /api/accounts/") for x in core.q("SELECT * FROM audit")))
        ok("route subnet rename: empty -> 400", c.patch(f"{base}/subnets/{SUB}", json={"display_name": "   "}).status_code == 400)
        ok("route subnet rename: missing body name -> 400", c.patch(f"{base}/subnets/{SUB}", json={}).status_code == 400)
        r256 = c.patch(f"{base}/subnets/{SUB}", json={"display_name": "x" * 256})
        ok("route subnet rename: 256 chars -> 400", r256.status_code == 400 and "255" in r256.json()["detail"])
        ok("route subnet rename: 255 chars ok", c.patch(f"{base}/subnets/{SUB}", json={"display_name": "y" * 255}).status_code == 200)
        bad = c.patch(f"{base}/subnets/ocid1.vcn.oc1..x", json={"display_name": "a"})
        ok("route subnet rename: non-subnet OCID -> 400", bad.status_code == 400 and "子网 OCID" in bad.json()["detail"])
        nf = c.patch(f"{base}/subnets/ocid1.subnet.oc1..missing", json={"display_name": "a"})
        ok("route subnet rename: cloud error -> 400 with reason", nf.status_code == 400 and "NotAuthorizedOrNotFound" in nf.json()["detail"])
        ok("route subnet rename: needs login", anon.patch(f"{base}/subnets/{SUB}", json={"display_name": "a"}).status_code == 401)
        ok("route subnet rename: OCI only", c.patch(f"/api/accounts/{aid}/oci/subnets/{SUB}", json={"display_name": "a"}).status_code == 400)
        v = c.patch(f"{base}/vcns/{VCN}", json={"display_name": "vcn-new"})
        ok("route vcn rename: 200 + audit", v.status_code == 200 and VNET.names[VCN] == "vcn-new"
           and len(core.q("SELECT * FROM audit WHERE action='oci-vcn-rename'")) == 1)
        ok("route vcn rename: non-VCN OCID -> 400", c.patch(f"{base}/vcns/{SUB}", json={"display_name": "a"}).status_code == 400)
        ok("route rename: security list never updated", not VNET.rules_touched)

        aws_provider._LS_GETREGIONS.clear()
        g = c.get(f"/api/accounts/{aid}/regions?service=lightsail")
        ok("route /regions?service=lightsail: filtered list", g.status_code == 200 and g.json() == ["ap-northeast-1", "ap-southeast-1", "us-east-1", "us-west-2"])
        ok("route /regions (EC2) unchanged: includes ap-east-2", "ap-east-2" in c.get(f"/api/accounts/{aid}/regions").json())
        ok("route /regions: bad service -> 400", c.get(f"/api/accounts/{aid}/regions?service=foo").status_code == 400)
        li = c.get(f"/api/accounts/{aid}/instances?kind=lightsail&region=ap-east-2")
        ok("route lightsail list in ap-east-2: friendly 400", li.status_code == 400 and li.json()["detail"] == "Lightsail 不支持该区域（台北 ap-east-2），请换区域")
        si = c.get(f"/api/accounts/{aid}/lightsail/static-ips?region=ap-east-2")
        ok("route lightsail static-ips in ap-east-2: friendly 400", si.status_code == 400 and "Lightsail 不支持该区域" in si.json()["detail"])
        op = c.get(f"/api/accounts/{aid}/lightsail/options?region=ap-east-2")
        ok("route lightsail options in ap-east-2: friendly 400", op.status_code == 400 and "台北" in op.json()["detail"])

# ================= 4. Web / demo 静态检查 =================
W = open(os.path.join(ROOT, "web", "js", "oci.js"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "web", "js", "core.js"), encoding="utf-8").read()
I = open(os.path.join(ROOT, "web", "js", "instances.js"), encoding="utf-8").read()
M = open(os.path.join(ROOT, "demo", "mock.js"), encoding="utf-8").read()
ok("web: rename button next to subnet dropdown", 'id="sgRen"' in W and "renameSubnet(acc, s, reload)" in W)
ok("web: PATCH subnets + vcns, keeps selection", '/oci/subnets/${encodeURIComponent(s.id)}' in W and '/oci/vcns/${encodeURIComponent(s.vcn_id)}' in W
   and 'method: "PATCH"' in W and 'localStorage.setItem("tc_sgsub_" + acc.id, s.id)' in W)
ok("web: rename note says instances/IP/rules unaffected", "不影响子网里的实例、IP 和安全规则" in W)
ok("web: lightsail regions via service=lightsail + auto switch toast", "/regions?service=lightsail" in C and "Lightsail 不支持 ${regionLabel(cur)}，已切换到 ${regionLabel(to)}" in C)
ok("web: lightsail page ensures region before loading", 'if (kind === "lightsail") await ensureLsRegion(acc);' in I and 'kind === "lightsail" ? "lightsail" : undefined' in I)
ok("demo mock: subnet/vcn PATCH + lightsail regions + ap-east-2 refusal", '(subnets|vcns)' in M and 'q.get("service") === "lightsail"' in M and "Lightsail 不支持该区域（台北 ap-east-2）" in M)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
