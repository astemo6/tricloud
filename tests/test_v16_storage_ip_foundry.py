"""v1.6 自测：重装系统、块存储卷、区域订阅、附加 IP / 预留 IP、IP 质量、账号类型与停用、Azure 磁盘、
免费 AMD 下行 500Mbps、对象存储、Lightsail 静态 IP / 防火墙、免费额度体检。
全部用假客户端 / mock，不连接任何真实云，也不访问 proxycheck / ip-api。"""
import asyncio
import json
import os
import sys
import tempfile

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123",
                  AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

import oci
from fastapi.testclient import TestClient

from app import cloudinit, core, main, net, services, tasks, telegram
from app.routers import accounts as account_routes
from app.providers import oci_more
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


def raises(fn, *a, text="", exc=Exception, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return text in str(e)
    return False


def bare_oci():
    p = OCIProvider.__new__(OCIProvider)
    p.cred, p.compartment, p.cfg, p.proxy = {}, "ocid1.compartment.x", {"tenancy": "ocid1.tenancy.x", "region": "ap-tokyo-1"}, None
    return p


# ================= 1. Run Command 固定脚本 =================
w = oci_more.as_root(oci_more.GROW_ROOT)
ok("as_root: sudo -n fallback and single quotes escaped", w.startswith('if [ "$(id -u)" = 0 ]') and "sudo -n sh -c" in w
   and "'\\''[0-9]*$'\\''" in w)
ok("grow script: growpart + resize2fs / xfs_growfs, no user input", "growpart" in oci_more.GROW_ROOT and "xfs_growfs" in oci_more.GROW_ROOT
   and "{" not in oci_more.GROW_ROOT.replace("${", ""))


# ================= 2. OCI 重装系统 =================
class RCompute:
    def __init__(self):
        self.upd = []

    def get_instance(self, iid):
        return Obj(data=Obj(shape="VM.Standard.A1.Flex", display_name="Web Box", metadata={"ssh_authorized_keys": "ssh-ed25519 AAA"}))

    def update_instance(self, iid, d):
        self.upd.append(d)


p = bare_oci()
p.compute = RCompute()
p._pick_image = lambda shape, os_name, ver, image_id: "ocid1.image.new"
p.boot_volume = lambda iid: {"size_gb": 50}
r = p.reinstall("ocid1.instance.x", "Canonical Ubuntu", "22.04")
d = p.compute.upd[0]
ok("oci reinstall: replaces boot volume via UpdateInstanceSourceViaImageDetails, old volume not kept",
   isinstance(d.source_details, oci.core.models.UpdateInstanceSourceViaImageDetails) and d.source_details.image_id == "ocid1.image.new"
   and d.source_details.is_preserve_boot_volume_enabled is False and d.source_details.boot_volume_size_in_gbs == 50)
ok("oci reinstall: new random password + keeps ssh key + hostname in user_data", r["password"] and r["username"] == "root"
   and d.metadata["ssh_authorized_keys"] == "ssh-ed25519 AAA" and "hostname: web-box" in __import__("base64").b64decode(d.metadata["user_data"]).decode())
ok("oci reinstall: cannot shrink boot volume", raises(p.reinstall, "i", disk_gb=40, text="不能小于"))


# ================= 3. 块存储卷 =================
class BS:
    def __init__(self):
        self.created, self.updated, self.deleted = [], [], []

    def create_volume(self, d):
        self.created.append(d)
        return Obj(data=Obj(id="vol-1", display_name=d.display_name))

    def get_volume(self, vid):
        return Obj(data=Obj(size_in_gbs=100, display_name="data", lifecycle_state="AVAILABLE"))

    def update_volume(self, vid, d):
        self.updated.append(d)

    def delete_volume(self, vid):
        self.deleted.append(vid)


class VCompute:
    def __init__(self, attached=False):
        self.attached, self.att = attached, []

    def get_instance(self, iid):
        return Obj(data=Obj(availability_domain="AD-2"))

    def attach_volume(self, d):
        self.att.append(d)
        return Obj(data=Obj(id="att-1"))

    def list_volume_attachments(self, **kw):
        return Obj(data=[Obj(lifecycle_state="ATTACHED")] if self.attached else [])


p = bare_oci()
p._bs, p.compute = BS(), VCompute()
r = p.create_volume("data-1", 60, 10, "ocid1.instance.x")
ok("volume create: AD follows instance, then paravirtualized attach", p._bs.created[0].availability_domain == "AD-2"
   and p._bs.created[0].size_in_gbs == 60 and p.compute.att[0].type == "paravirtualized" and r["attach"]["attachment_id"] == "att-1")
ok("volume create: size < 50 / bad VPU rejected", raises(p.create_volume, "x", 20, text="50") and raises(p.create_volume, "x", 60, 15, text="VPU"))
ok("volume update: shrink rejected, expand flagged", raises(p.update_volume, "v", 80, text="只能扩容")
   and p.update_volume("v", 150)["expanded"] and p._bs.updated[-1].size_in_gbs == 150)
ok("volume delete: refuses attached volume", raises(lambda: (setattr(p.compute, "attached", True), p.delete_volume("v"))[1], text="先卸载"))
p.compute.attached = False
ok("volume delete: detached volume deleted", p.delete_volume("v")["ok"] and p._bs.deleted == ["v"])


# ================= 4. 区域订阅 =================
class Ident:
    def __init__(self):
        self.subs = []

    def list_region_subscriptions(self, t):
        return Obj(data=[Obj(region_name="ap-tokyo-1", is_home_region=True, status="READY")])

    def list_regions(self):
        return Obj(data=[Obj(name="ap-tokyo-1", key="NRT"), Obj(name="ap-seoul-1", key="ICN")])

    def create_region_subscription(self, d, t):
        self.subs.append(d.region_key)
        return Obj(data=Obj(region_name="ap-seoul-1", status="IN_PROGRESS"))


p = bare_oci()
p.identity = Ident()
p._c = lambda cls, cfg=None: p.identity
rs = p.region_subscriptions()
ok("region subs: home + subscribed flags", rs["home"] == "ap-tokyo-1" and [x["subscribed"] for x in rs["regions"]] == [False, True])
ok("region subscribe: key validated, call goes to home region client", raises(p.subscribe_region, "nrt; rm", text="不合法")
   and p.subscribe_region("ICN")["region"] == "ap-seoul-1" and p.identity.subs == ["ICN"])


# ================= 5. 预留 IP / 辅助 IP =================
class VN:
    def __init__(self):
        self.calls = []

    def list_private_ips(self, vnic_id):
        return Obj(data=[Obj(id="pip-1", is_primary=True, ip_address="10.0.0.2")])

    def get_public_ip_by_private_ip_id(self, d):
        return Obj(data=Obj(id="eph-1", lifetime="EPHEMERAL", ip_address="203.0.113.1"))

    def delete_public_ip(self, i):
        self.calls.append(("del", i))

    def update_public_ip(self, i, d):
        self.calls.append(("upd", i, d.private_ip_id))

    def get_private_ip(self, i):
        return Obj(data=Obj(is_primary=i == "pip-1"))

    def create_private_ip(self, d):
        return Obj(data=Obj(id="pip-2", ip_address="10.0.0.9"))

    def create_public_ip(self, d):
        self.calls.append(("new", d.lifetime, d.private_ip_id))
        return Obj(data=Obj(ip_address="203.0.113.99"))


p = bare_oci()
p.vnet = VN()
p._primary_vnic = lambda iid: Obj(id="vnic-1", subnet_id="sub-1")
with mock.patch("app.providers.oci_more.time.sleep", lambda s: None):
    p.assign_reserved_ip("res-1", "ocid1.instance.x")
ok("reserved assign: ephemeral deleted first, reserved bound to primary private IP", p.vnet.calls == [("del", "eph-1"), ("upd", "res-1", "pip-1")])
r = p.add_secondary_ip("ocid1.instance.x")
ok("secondary IP: private + ephemeral public, OS hint returned", r["private_ip"] == "10.0.0.9" and r["public_ip"] == "203.0.113.99"
   and ("new", "EPHEMERAL", "pip-2") in p.vnet.calls and "ip addr add" in r["hint"])
ok("secondary IP: primary private IP cannot be deleted", raises(p.delete_private_ip, "pip-1", text="主私网"))


# ================= 6. IP 质量 =================
ok("quality_ok: risk / country rules", net.quality_ok({"risk": 20, "country_code": "US"}, 50, "us,jp") == (True, "")
   and not net.quality_ok({"risk": 80, "country_code": "US"}, 50)[0] and "不在" in net.quality_ok({"risk": 1, "country_code": "DE"}, None, "US")[1]
   and not net.quality_ok({"risk": None}, 50)[0])


class HR:
    def __init__(self, j):
        self.j = j

    def json(self):
        return self.j


def fake_get(url, params=None, timeout=None):
    if "proxycheck" in url:
        ok("quality: only the IP is sent (no key when unset)", "key" not in (params or {}))
        return HR({"status": "ok", "203.0.113.5": {"risk": "12", "type": "Business", "proxy": "no", "isocode": "JP", "country": "Japan", "provider": "Oracle"}})
    return HR({"status": "success", "countryCode": "JP", "country": "Japan", "isp": "Oracle", "as": "AS31898 Oracle", "hosting": True})


with mock.patch("app.net.httpx.get", fake_get):
    q = net.ip_quality("203.0.113.5")
ok("ip_quality: merges proxycheck risk + ip-api hosting/asn", q["risk"] == 12 and q["country_code"] == "JP" and q["hosting"] is True and q["asn"] == "AS31898")
ok("ip_quality: invalid IP rejected", raises(net.ip_quality, "1.2.3.4; rm -rf", exc=ValueError))

# OCI 换 IP：带质量条件时重复更换
p = bare_oci()
p.vnet = Obj(list_private_ips=lambda vnic_id: Obj(data=[Obj(id="pip-1", is_primary=True)]))
p._primary_vnic = lambda iid: Obj(id="vnic-1")
seq = iter([("1.1.1.1", "2.2.2.2"), ("2.2.2.2", "3.3.3.3")])
p._rotate_ip_once = lambda primary: next(seq)
with mock.patch("app.providers.oci_provider.time.sleep", lambda s: None):
    r = p.change_ip("i", None, 5, None, 0, accept=lambda ip: (ip == "3.3.3.3", "风险分 90 > 50"))
ok("oci change_ip: accept() rejects first IP, keeps rotating until it passes", r["new_ip"] == "3.3.3.3" and r["tries"] == 2 and r["old_ip"] == "1.1.1.1")


# ================= 7. 账号类型 =================
class OSP:
    def list_subscriptions(self, osp_home_region, compartment_id):
        return Obj(data=Obj(items=[Obj(plan_type="PAYG", account_type="PERSONAL", upgrade_state="UPGRADED", time_start="2025-01-01T00:00:00",
                                       time_plan_upgrade="2025-02-01T00:00:00", currency_code="USD")]))


p = bare_oci()
p.identity = Obj(list_region_subscriptions=lambda t: Obj(data=[Obj(region_name="ap-tokyo-1", is_home_region=True)]),
                 get_tenancy=lambda t: Obj(data=Obj(name="ten")))
p._c = lambda cls, cfg=None: OSP()
r = p.account_type()
ok("oci account_type: PAYG -> 升级号, age_days computed", r["label"].startswith("升级号") and r["plan_type"] == "PAYG" and r["age_days"] > 300
   and r["time_start"] == "2025-01-01")


# ================= 8. 500Mbps =================
p = bare_oci()
p.compute = Obj(get_instance=lambda iid: Obj(data=Obj(shape="VM.Standard.A1.Flex", display_name="a1")))
ok("500m: only E2.1.Micro", raises(p.enable_500m, "i", text="E2.1.Micro"))
p.compute = Obj(get_instance=lambda iid: Obj(data=Obj(shape="VM.Standard.E2.1.Micro", display_name="m1")))
p.nlb_status = lambda iid: {"enabled": False}
p._nlbc = lambda: Obj(list_network_load_balancers=lambda compartment_id: Obj(data=Obj(items=[Obj(display_name="user-nlb", lifecycle_state="ACTIVE")])))
ok("500m: existing NLB is never deleted, user is told", raises(p.enable_500m, "i", text="user-nlb"))


# ================= 9. 对象存储 =================
p = bare_oci()
ok("object storage: bucket / object names validated", raises(p.create_bucket, "../x", text="Bucket") and raises(p.put_object, "b", "../etc/passwd", b"", text="对象名"))


# ================= 10. 免费额度体检 =================
p = bare_oci()
p.list_instances = lambda: [
    {"id": "a", "name": "a1-old", "shape": "VM.Standard.A1.Flex", "ocpus": 2, "memory_gb": 12, "state": "running", "created": "2025-01-01"},
    {"id": "b", "name": "a1-new", "shape": "VM.Standard.A1.Flex", "ocpus": 4, "memory_gb": 24, "state": "running", "created": "2026-01-01"},
    {"id": "c", "name": "m1", "shape": "VM.Standard.E2.1.Micro", "state": "running", "created": "2025"},
    {"id": "d", "name": "paid", "shape": "VM.Standard.E4.Flex", "state": "stopped", "created": "2025"}]
p.storage_usage = lambda: {"volume_gb": 250}
r = p.free_check((4, 24))   # 付费号额度
r_free = p.free_check()     # 缺省按免费号 2/12
ok("free check default (free tier) limit 2C/12G", r_free["a1"]["limit_ocpus"] == 2 and r_free["a1"]["limit_mem"] == 12)
ok("free check: A1 6C/36G over, storage over, paid listed", not r["ok"] and r["a1"]["ocpus"] == 6 and len(r["issues"]) == 4 and r["paid"][0]["name"] == "paid")
ok("free check: suggestion downsizes newest A1 to the remaining 2C/12G (only down)", r["suggestions"] == [
    {"id": "b", "name": "a1-new", "ocpus": 4.0, "memory_gb": 24.0, "to_ocpus": 2.0, "to_memory_gb": 12.0, "delete": False}])


# ================= 11. Azure 磁盘 =================
class Disks:
    def __init__(self):
        self.upd = []

    def get(self, rg, n):
        return Obj(disk_size_gb=64, sku=Obj(name="StandardSSD_LRS"), managed_by=None, id="d1", name=n)

    def begin_update(self, rg, n, u):
        self.upd.append(u)
        return Obj(result=lambda: None)


z = AzureProvider.__new__(AzureProvider)
z.compute = Obj(disks=Disks(), virtual_machines=Obj(get=lambda rg, n: Obj(id="/x")))
VM = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
DISK = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/disks/os1"
ok("azure disk: shrink / tier on non-premium rejected", raises(z.update_disk, VM, DISK, 32, text="只能扩大")
   and raises(z.update_disk, VM, DISK, None, None, "P10", text="Premium"))
z.update_disk(VM, DISK, 128, "Premium_LRS", "P10")
ok("azure disk: size + sku + tier sent", z.compute.disks.upd[-1] == {"disk_size_gb": 128, "sku": {"name": "Premium_LRS"}, "tier": "P10"})


# ================= 12. 接口 =================
class FP:
    def __init__(self):
        self.calls = []

    def __getattr__(self, n):
        def f(*a, **kw):
            self.calls.append((n, a))
            if n == "free_check":
                return {"ok": True, "issues": [], "suggestions": [], "a1": {}, "micro": {}, "storage": {}, "paid": []}
            if n == "account_type":
                return {"label": "免费试用 / 免费号", "plan_type": "FREE_TIER", "time_start": "2026-01-02"}
            return {"ok": True}
        return f


mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()
mock.patch.object(AzureProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()
with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}):
        oid = c.post("/api/accounts", json={"provider": "oci", "name": "oci-1", "cred": {
            "user": "ocid1.user.oc1..fakeuser123456", "tenancy": "ocid1.tenancy.oc1..faketen654321", "fingerprint": "aa:bb",
            "key_content": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n", "region": "ap-tokyo-1"}}).json()["id"]
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        aid = c.post("/api/accounts", json={"provider": "aws", "name": "aws-1", "cred": {
            "access_key": "AKIAFAKEFAKE1234", "secret_key": "s3cr3t-fake", "region": "us-east-1"}}).json()["id"]
    core.set_setting("free_guard", False)
    fp = FP()
    with mock.patch.object(services, "provider", lambda acc_id, region=None: fp):
        ok("route reinstall: needs confirm", c.post(f"/api/accounts/{oid}/instances/reinstall", json={"instance_id": "i"}).status_code == 400)
        ok("route reinstall: Lightsail refused", c.post(f"/api/accounts/{aid}/instances/reinstall",
                                                        json={"instance_id": "ls", "kind": "lightsail", "confirm": True}).status_code == 400)
        r = c.post(f"/api/accounts/{oid}/instances/reinstall", json={"instance_id": "i", "confirm": True, "os": "Oracle Linux", "os_version": "9"})
        t = core.q("SELECT * FROM tasks WHERE id=?", (r.json().get("task_id"),), one=True)
        ok("route reinstall: background task with params", r.status_code == 200 and t["type"] == "reinstall" and json.loads(t["params"])["os"] == "Oracle Linux")
        ok("route volumes: delete needs confirm / bad op 400", c.post(f"/api/accounts/{oid}/oci/volumes", json={"op": "delete", "volume_id": "v"}).status_code == 400
           and c.post(f"/api/accounts/{oid}/oci/volumes", json={"op": "nope"}).status_code == 400)
        ok("route volumes: OCI only", c.get(f"/api/accounts/{aid}/oci/volumes").status_code == 400)
        ok("route region subscribe: needs confirm", c.post(f"/api/accounts/{oid}/oci/region-subscriptions", json={"region_key": "ICN"}).status_code == 400)
        ok("route 500m: enabling needs confirm, then creates task", c.post(f"/api/accounts/{oid}/oci/500m", json={"instance_id": "i"}).status_code == 400
           and c.post(f"/api/accounts/{oid}/oci/500m", json={"instance_id": "i", "confirm": True}).json().get("task_id"))
        ok("route ip-quality: bad ip 400", c.get("/api/ip-quality?ip=not-an-ip").status_code == 400)
        ok("route change-ip: quality params validated", c.post(f"/api/accounts/{oid}/instances/change-ip", json={"instance_id": "i", "quality_max_risk": 300}).status_code == 400
           and c.post(f"/api/accounts/{oid}/instances/change-ip", json={"instance_id": "i", "quality_country": "USA!"}).status_code == 400)
        r = c.post(f"/api/accounts/{oid}/instances/change-ip", json={"instance_id": "i", "quality_max_risk": 50})
        t = core.q("SELECT * FROM tasks WHERE id=?", (r.json().get("task_id"),), one=True)
        ok("route change-ip: OCI with quality -> task (not sync)", t and json.loads(t["params"])["quality_max_risk"] == 50 and json.loads(t["params"])["max_tries"] == 20)
        ok("route lightsail ports: 0.0.0.0/0 needs confirm (409), all ports refused", c.post(f"/api/accounts/{aid}/lightsail/ports", json={
            "instance": "ls1", "protocol": "tcp", "from_port": 8443}).status_code == 409
           and c.post(f"/api/accounts/{aid}/lightsail/ports", json={"instance": "ls1", "protocol": "tcp", "from_port": 1, "to_port": 65535,
                                                                     "confirm_public": True}).status_code == 400
           and c.post(f"/api/accounts/{aid}/lightsail/ports", json={"instance": "ls1", "protocol": "tcp", "from_port": 8443, "confirm_public": True}).status_code == 200)
        ok("route object put: >100MB refused before reading", c.put(f"/api/accounts/{oid}/oci/objects?bucket=b&name=x",
                                                                    content=b"x", headers={"content-length": str(200 * 1024 * 1024)}).status_code == 413)
        r = c.put(f"/api/accounts/{oid}/oci/objects?bucket=b&name=a.txt", content=b"hello")
        ok("route object put: raw body streamed to provider", r.status_code == 200 and r.json()["size"] == 5 and fp.calls[-1][0] == "put_object")
        r = c.get(f"/api/accounts/{oid}/account-type")
        ok("route account-type: cached + fills cloud_created_at", r.json()["label"].startswith("免费") and
           core.q("SELECT cloud_created_at FROM accounts WHERE id=?", (oid,), one=True)["cloud_created_at"] == "2026-01-02")
        n = len(fp.calls)
        c.get(f"/api/accounts/{oid}/account-type")
        ok("route account-type: second call served from cache", len(fp.calls) == n)
        ok("route free-check: one row per OCI account", [x["name"] for x in c.get("/api/oci/free-check").json()] == ["oci-1"])
        tid = tasks.create_task("snatch", oid, {"name": "x"})
        r = c.post(f"/api/accounts/{oid}/disable", json={"reason": "被封号"})
        accs = {a["id"]: a for a in c.get("/api/accounts").json()}
        ok("route disable: running tasks stopped, flag + reason listed", tid in r.json()["stopped_tasks"]
           and not core.q("SELECT id FROM tasks WHERE account_id=? AND status='running'", (oid,)) and accs[oid]["disabled"] == 1
           and accs[oid]["disabled_reason"] == "被封号")
        async def fake_test(i):
            return {"account_id": i, "ok": True}
        with mock.patch.object(account_routes, "_test_with_timeout", fake_test):
            j = c.post("/api/accounts/test-all", json={}).json()
        ok("route disable: test-all skips disabled account", j["total"] == 1)
        ok("route disable: free-check skips disabled account", c.get("/api/oci/free-check").json() == [])
        c.post(f"/api/accounts/{oid}/disable", json={"disabled": False})
        ok("route enable: flag cleared", {a["id"]: a for a in c.get("/api/accounts").json()}[oid]["disabled"] == 0)
        ok("route settings: proxycheck key stored as secret, not echoed", c.post("/api/settings", json={"proxycheck_key": "pk-123"}).status_code == 200
           and c.get("/api/settings").json()["proxycheck_key_set"] is True and "pk-123" not in c.get("/api/settings").text)


# ================= 13. 重装任务 =================
class RP:
    def __init__(self):
        self.st = iter(["stopped", "running"])

    def reinstall(self, *a):
        return {"ok": True, "password": "Pw-123456789abc", "username": "root", "name": "web"}

    def get_state(self, iid):
        return next(self.st)

    _wait = staticmethod(OCIProvider._wait)


saved = []
t = core.q("SELECT * FROM tasks WHERE type='reinstall' ORDER BY id DESC LIMIT 1", one=True)
with mock.patch.object(services, "provider", lambda acc_id, region=None: RP()), mock.patch("app.providers.oci_provider.time.sleep", lambda s: None), \
        mock.patch.object(cloudinit, "save_instance_secret", lambda *a: saved.append(a)), mock.patch.object(telegram, "send", lambda *a, **k: asyncio.sleep(0)):
    asyncio.run(tasks._run_once(t))
t = core.q("SELECT * FROM tasks WHERE id=?", (t["id"],), one=True)
ok("task reinstall: done, new password saved to 开机密码", t["status"] == "done" and "开机密码" in t["message"] and saved and saved[0][4] == "Pw-123456789abc")

# ================= Foundry（Azure AI） =================
SUBID = "sub-123"
RID = f"/subscriptions/{SUBID}/resourceGroups/ai-rg/providers/Microsoft.CognitiveServices/accounts/ai1"
fz = AzureProvider.__new__(AzureProvider)
fz.sub = SUBID
calls = []


def fake_arm(method, path, body=None, timeout=60):
    calls.append((method, path, body))
    if path.endswith("/usages?api-version=2024-10-01"):
        return {"value": [{"name": {"localizedValue": "GPT-4o TPM"}, "currentValue": 30, "limit": 450}, {"name": {"value": "zero"}, "limit": 0}]}
    if "/models?" in path:
        return {"value": [{"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-11-20", "capabilities": {"chatCompletion": "true"},
                                     "skus": [{"name": "GlobalStandard"}], "isDefaultVersion": True}},
                          {"model": {"format": "OpenAI", "name": "old", "version": "1", "lifecycleStatus": "Deprecated", "capabilities": {"chatCompletion": "true"}, "skus": [{"name": "Standard"}]}},
                          {"model": {"format": "OpenAI", "name": "dall-e-3", "version": "3", "capabilities": {"imageGenerations": "true"}, "skus": [{"name": "Standard"}]}}]}
    if path.endswith("/accounts?api-version=2024-10-01"):
        return {"value": [{"id": RID, "name": "ai1", "kind": "AIServices", "location": "swedencentral", "sku": {"name": "S0"},
                           "properties": {"endpoint": "https://ai1.cognitiveservices.azure.com/", "provisioningState": "Succeeded"}},
                          {"id": RID.replace("ai1", "speech"), "name": "speech", "kind": "SpeechServices", "location": "x"}]}
    if path.endswith("/deployments?api-version=2024-10-01"):
        return {"value": [{"name": "gpt-4o", "sku": {"name": "GlobalStandard", "capacity": 30}, "properties": {"model": {"name": "gpt-4o", "version": "2024-11-20"}, "provisioningState": "Succeeded"}}]}
    if path.endswith("/listKeys?api-version=2024-10-01"):
        return {"key1": "k1", "key2": "k2"}
    if method == "GET":
        return {"name": "ai1", "properties": {"provisioningState": "Succeeded", "endpoint": "https://ai1.cognitiveservices.azure.com/", "customSubDomainName": "ai1"}}
    return {}


fz._arm = fake_arm
q = fz.foundry_quotas("swedencentral")
ok("foundry quotas: zero-limit rows dropped", len(q["quotas"]) == 1 and q["quotas"][0]["used"] == 30 and "swedencentral" in q["regions"])
ms = fz.foundry_models("swedencentral")["models"]
ok("foundry models: only chat/embedding, no deprecated", [m["name"] for m in ms] == ["gpt-4o"])
rs = fz.foundry_resources()
ok("foundry resources: AIServices only, with deployments", len(rs) == 1 and rs[0]["resource_group"] == "ai-rg" and rs[0]["deployments"][0]["capacity"] == 30)
k = fz.foundry_keys(RID)
ok("foundry keys: endpoint + openai base url", k["key1"] == "k1" and k["openai_base_url"] == "https://ai1.openai.azure.com/openai/v1/")
ok("foundry: foreign subscription / bad id rejected", raises(fz.foundry_keys, RID.replace(SUBID, "other"), text="无效")
   and raises(fz.foundry_delete_deployment, RID, "../x", text="无效"))
calls.clear()
r = fz.foundry_deploy({"name": "my-ai", "region": "swedencentral", "model": "gpt-4o", "version": "2024-11-20", "sku": "GlobalStandard", "capacity": 20})
puts = [x for x in calls if x[0] == "PUT"]
ok("foundry deploy: rg + AIServices S0 + deployment PUT", len(puts) == 3 and puts[1][2]["kind"] == "AIServices" and puts[1][2]["sku"]["name"] == "S0"
   and puts[2][1].endswith("/deployments/gpt-4o?api-version=2024-10-01") and puts[2][2]["sku"] == {"name": "GlobalStandard", "capacity": 20}
   and r["deployment"] == "gpt-4o")
ok("foundry deploy: validation", raises(fz.foundry_deploy, {"name": "x", "model": "gpt-4o"}, text="资源名称")
   and raises(fz.foundry_deploy, {"name": "ok-name", "model": "gpt-4o", "capacity": 5000}, text="容量")
   and raises(fz.foundry_deploy, {"name": "ok-name", "model": "gpt-4o", "sku": "Bad"}, text="部署类型"))
with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(AzureProvider, "test", return_value={"ok": True}):
        zid = c.post("/api/accounts", json={"provider": "azure", "name": "az-f", "cred": {"tenant_id": "t", "client_id": "c", "client_secret": "s", "subscription_id": SUBID}}).json()["id"]
    with mock.patch.object(services, "provider", lambda acc_id, region=None: fz):
        g = c.get(f"/api/accounts/{zid}/azure/foundry?region=swedencentral").json()
        ok("route foundry GET: quotas + resources + models", g["quotas"] and g["resources"] and g["models"])
        ok("route foundry keys/delete need confirm", c.post(f"/api/accounts/{zid}/azure/foundry", json={"op": "keys", "resource_id": RID}).status_code == 400
           and c.post(f"/api/accounts/{zid}/azure/foundry", json={"op": "delete_resource", "resource_id": RID}).status_code == 400)
        r = c.post(f"/api/accounts/{zid}/azure/foundry", json={"op": "deploy", "model": "gpt-4o", "name": "my-ai", "region": "swedencentral"})
        t = core.q("SELECT * FROM tasks WHERE id=?", (r.json().get("task_id"),), one=True)
        ok("route foundry deploy → background task", t and t["type"] == "foundry")
    with mock.patch.object(services, "provider", lambda acc_id, region=None: fz), mock.patch.object(telegram, "send", lambda *a, **k: asyncio.sleep(0)):
        asyncio.run(tasks._run_once(t))
    t = core.q("SELECT * FROM tasks WHERE id=?", (t["id"],), one=True)
    ok("task foundry: done with endpoint", t["status"] == "done" and "ai1.cognitiveservices" in t["message"])
    ok("foundry on non-azure account rejected", c.get("/api/accounts/1/azure/foundry").status_code in (400, 404))

# ================= 13b. OCI 流量汇总 =================
tp = bare_oci()
tp.list_instances = lambda: [{"id": "i1", "name": "a1", "state": "running", "public_ip": "203.0.113.5", "shape": "VM.Standard.A1.Flex", "region": "ap-tokyo-1"},
                             {"id": "i2", "name": "e2", "state": "stopped", "public_ip": None, "shape": "VM.Standard.E2.1.Micro", "region": "ap-tokyo-1"}]
def _tr(iid):
    if iid == "i2":
        raise RuntimeError("找不到主 VNIC")
    return {"out_gb": 12.5, "in_gb": 40.25, "period": "x"}
tp.traffic = _tr
ts = tp.traffic_summary()
ok("traffic_summary: totals skip failed instance", ts["out_gb"] == 12.5 and ts["in_gb"] == 40.25 and ts["free_out_gb"] == 10240)
ok("traffic_summary: per-instance error kept", ts["items"][1]["out_gb"] is None and "VNIC" in ts["items"][1]["error"] and ts["items"][0]["out_gb"] == 12.5)
with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(services, "provider", lambda acc_id, region=None: tp):
        r = c.get(f"/api/accounts/{oid}/oci/traffic-summary?region=ap-tokyo-1")
        ok("route traffic-summary 200", r.status_code == 200 and r.json()["out_gb"] == 12.5)
        ok("traffic-summary on aws account rejected", c.get(f"/api/accounts/{aid}/oci/traffic-summary").status_code in (400, 404))

# ================= 13c. OCI 账号创建日期自动读取 =================
with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    class _CP:
        def created_at(self): return "2025-04-27"
    with mock.patch.object(services, "provider", lambda acc_id, region=None: _CP()):
        r = c.post(f"/api/accounts/{oid}/detect-created")
        ok("detect-created oci saves date", r.status_code == 200 and core.get_account(oid)["cloud_created_at"] == "2025-04-27")
        ok("detect-created aws rejected", c.post(f"/api/accounts/{aid}/detect-created").status_code == 400)

# ================= 13d. 前端缓存版本号 / 云权限错误 =================
import re as _re
with TestClient(main.app, raise_server_exceptions=False) as c:
    r = c.get("/login")
    ok("login page assets versioned + no-cache", r.headers.get("cache-control") == "no-cache" and _re.search(r'/static/style\.css\?v=[0-9a-f]{10}"', r.text))
    c.post("/api/login", json={"password": "devpassword123"})
    r = c.get("/")
    ok("index app.js versioned", _re.search(r'/static/js/main\.js\?v=[0-9a-f]{10}"', r.text) is not None
       and _re.search(r'"/static/js/core\.js":"/static/js/core\.js\?v=[0-9a-f]{10}"', r.text) is not None)
    class _Deny:
        def regions(self):
            raise RuntimeError("An error occurred (UnauthorizedOperation) when calling the DescribeRegions operation: User: arn:aws:iam::0:user/x is not authorized to perform: ec2:DescribeRegions because no identity-based policy allows")
    with mock.patch.object(services, "provider", lambda acc_id, region=None: _Deny()):
        r = c.get(f"/api/accounts/{aid}/regions")
        ok("cloud permission error -> 403 with missing action", r.status_code == 403 and "ec2:DescribeRegions" in r.json()["detail"])

# ================= 14. 前端 / 演示 / 约束 =================
web = "".join(open(os.path.join(ROOT, "web", "js", f), encoding="utf-8").read() for f in sorted(os.listdir(os.path.join(ROOT, "web", "js"))) if f.endswith(".js"))
ok("web: new ops + tabs wired", all(s in web for s in ('["reinstall", "重装系统"]', '["ips", "附加 IP"]', '["net500", "500M 下行"]', '["disks", "磁盘"]',
                                                     '["lsports", "防火墙"]', '["quality", "IP 质量"]', '["storage", "存储"]', '["objects", "对象存储"]',
                                                     '["regionsub", "区域订阅"]', "pageFreeCheck", "QUALITY_FIELDS", "data-off", "proxycheck_key")))
ok("web: account list has no 停用 button (only 启用 for already-disabled)", '"启用" : "停用"' not in web and 'data-off="${a.id}">启用' in web)
ok("web: reinstall requires explicit confirm checkbox", 'name="confirm"' in web and "请先勾选确认" in web)
mockjs = open(os.path.join(ROOT, "demo", "mock.js"), encoding="utf-8").read().replace("\\/", "/")
ok("demo: mock covers v1.6 routes", all(s in mockjs for s in ("/oci/volumes", "/oci/buckets", "/oci/region-subscriptions", "/oci/ips", "/ip-quality",
                                                              "/instances/reinstall", "/lightsail/static-ips", "/oci/free-check", "/azure/disks", "/oci/500m", "/azure/foundry")))
ok("web/demo: info dialog auto-detects OCI created date", "ccDetect" in web and "/detect-created" in web and "detect-created" in mockjs)
ok("web: OCI limits free-left column", "免费剩余" in web and "free_left" in web and "free_left: 3" in mockjs)
ok("oci: FREE_LIMITS default free-tier A1 2/12 E2 2", OCIProvider.FREE_LIMITS == {"standard-a1-core-count": 2, "standard-a1-memory-count": 12, "standard-e2-micro-core-count": 2})
ok("web: OCI instance ops drop 流量守护, managed in 流量 tab", 'if (acc.provider !== "oci") ops.push(["traffic", "流量守护"])' in web and "data-tgdel" in web and "guardCell" in web)
ok("web/demo: OCI traffic tab wired", '["traffic", "流量"]' in web and "tabOciTraffic" in web and "/oci/traffic-summary" in mockjs)
ok("web: foundry tab wired", '["foundry", "Foundry"]' in web and "tabAzFoundry" in web)
src = "".join(open(os.path.join(ROOT, "app", "providers", f), encoding="utf-8").read() for f in ("oci_more.py", "aws_more.py", "azure_more.py"))
ok("no remote shell: no paramiko / ssh in new providers", "paramiko" not in src and "ssh -" not in src)
ok("500m never deletes NLBs it did not create", "delete_network_load_balancer(st[\"nlb_id\"])" in src and src.count("delete_network_load_balancer") == 1)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
