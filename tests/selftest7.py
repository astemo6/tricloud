"""v1.5 自测：串口控制台已移除、TG 内联按钮（假 Bot）、已删账号回收站、代理账密、默认创建参数、OCI 安全组（批量端口 /
对公网放行二次确认 / 按内容删除）、OCI 删除 IPv6、AWS CloudFront（moto：新建 / 读取与修改配置 / 启停 / 缓存刷新 / 删除前自动停用；
套餐用假的 pricing-plan-manager 客户端）、实例「开放端口」（OCI 假 VNET / AWS moto / Azure 假 NSG）、账号编辑回显、旧版 Token、抢机任务断点续抢、旧版数据迁移脚本。
全部用 mock / moto，不连接任何真实云或 Telegram。"""
import asyncio
import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123",
                  AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

import oci  # noqa: F401
from fastapi.testclient import TestClient
from moto import mock_aws

from app import core, main, services, tasks, telegram
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
sent = []


async def fake_send(text, *a, **k):
    sent.append(text)
    return True
telegram.send = fake_send

# OCI / Azure 构造函数不连云
mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()
mock.patch.object(AzureProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()


def run_task(tid):
    t = core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)
    asyncio.run(tasks._dispatch(t))


# ---------------- 假 OCI 网络（安全列表 / IPv6） ----------------
class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeVnet:
    def __init__(self):
        self.lists = {"sl-1": Obj(id="sl-1", display_name="Default Security List", ingress_security_rules=[
            OCIProvider._make_rule("ingress", "tcp", "0.0.0.0/0", "22", "ssh")], egress_security_rules=[
            OCIProvider._make_rule("egress", "all", "0.0.0.0/0")])}
        self.updates, self.ipv6, self.deleted_v6 = 0, [Obj(id="v6-1", ip_address="2001:db8::1"), Obj(id="v6-2", ip_address="2001:db8::2")], []

    def get_security_list(self, sl_id):
        return Obj(data=self.lists[sl_id])

    def update_security_list(self, sl_id, d):
        self.updates += 1
        if d.ingress_security_rules is not None:
            self.lists[sl_id].ingress_security_rules = d.ingress_security_rules
        if d.egress_security_rules is not None:
            self.lists[sl_id].egress_security_rules = d.egress_security_rules

    def list_ipv6s(self, vnic_id):
        return Obj(data=list(self.ipv6))

    def delete_ipv6(self, i):
        self.deleted_v6.append(i)
        self.ipv6 = [x for x in self.ipv6 if x.id != i]


VNET = FakeVnet()


def fake_oci(acc_id, region=None):
    p = OCIProvider.__new__(OCIProvider)
    p.cred, p.vnet = {}, VNET
    p._subnet_of = lambda inst_id: Obj(security_list_ids=["sl-1"])
    p._primary_vnic = lambda inst_id: Obj(id="vnic-1")
    return p


# ---------------- 假 Telegram Bot ----------------
class Bot:
    def __init__(self):
        self.calls = []

    async def call(self, method, body):
        self.calls.append((method, body))
        return {"ok": True}

    def last(self, method=None):
        return [c for c in self.calls if not method or c[0] == method][-1][1]

    def btn(self, part):
        mk = [c for c in self.calls if c[1].get("reply_markup")][-1][1]["reply_markup"]["inline_keyboard"]
        return [b for r in mk for b in r if part in b["text"]][0]["callback_data"]

    def texts(self):
        return [b["text"] for r in self.last()["reply_markup"]["inline_keyboard"] for b in r]


MSG = {"message_id": 7, "chat": {"id": 42}}


def cbq(bot, data, chat=42):
    asyncio.run(telegram.handle_callback(bot, "42", {"id": "q", "data": data, "message": dict(MSG, chat={"id": chat})}))


with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    ok("version 1.6.0", c.get("/api/health").json()["version"] == "1.6.0")

    # ================= 1. 串口控制台已移除 =================
    paths = [getattr(r, "path", "") for r in main.app.routes]
    ok("console: no console / serial routes registered", not [p for p in paths if "console" in p or "serial" in p])
    ok("console: old endpoints 404", c.get("/api/accounts/1/aws/serial").status_code == 404
       and c.get("/api/accounts/1/azure/serial-log?instance_id=x").status_code == 404)
    web = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
    ok("console: web UI has no xterm / console entry", "xterm" not in web.lower() and "openConsole" not in web
       and not os.path.exists(os.path.join(ROOT, "web", "vendor", "xterm.js")))
    ok("console: paramiko dependency removed", "paramiko" not in open(os.path.join(ROOT, "requirements.txt")).read())

    # ---- 账号 ----
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}):
        oid = c.post("/api/accounts", json={"provider": "oci", "name": "oci-tokyo", "cred": {
            "user": "ocid1.user.oc1..fakeuser123456", "tenancy": "ocid1.tenancy.oc1..faketen654321", "fingerprint": "aa:bb",
            "key_content": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n", "region": "ap-tokyo-1"}}).json()["id"]
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        aid = c.post("/api/accounts", json={"provider": "aws", "name": "aws-main", "cred": {
            "access_key": "AKIAFAKEFAKE1234", "secret_key": "s3cr3t-fake", "region": "us-east-1",
            "proxy": "http://proxy.example.test:3128", "proxy_user": "u@1", "proxy_pass": "p:ss/w0rd"}}).json()["id"]

    # ================= 2. 代理：URL + 单独账密 =================
    raw = core.q("SELECT cred_enc FROM accounts WHERE id=?", (aid,), one=True)["cred_enc"]
    ok("proxy: password stored encrypted (not in DB plaintext)", "p:ss/w0rd" not in raw and "proxy.example" not in raw)
    acc_row = [a for a in c.get("/api/accounts").json() if a["id"] == aid][0]
    ok("proxy: list shows host + user + pass_set, never the password",
       acc_row["proxy"].endswith("proxy.example.test:3128") and acc_row["proxy_user"] == "u@1" and acc_row["proxy_pass_set"] is True
       and "p:ss/w0rd" not in json.dumps(acc_row))
    rc = core.runtime_cred(core.get_account(aid, with_cred=True)["cred"])
    ok("proxy: runtime proxy composed & url-quoted", rc["proxy"] == "http://u%401:p%3Ass%2Fw0rd@proxy.example.test:3128"
       and "proxy_user" not in rc and "proxy_pass" not in rc)
    services.drop_provider_cache(aid)
    ok("proxy: provider factory receives composed proxy", services.provider(aid).cfg.proxies["https"] == rc["proxy"])
    c.patch(f"/api/accounts/{aid}", json={"proxy_pass": ""})
    ok("proxy: empty proxy_pass = unchanged", core.get_account(aid, with_cred=True)["cred"].get("proxy_pass") == "p:ss/w0rd")
    c.patch(f"/api/accounts/{aid}", json={"proxy_pass": "newpass"})
    ok("proxy: new proxy_pass saved", core.get_account(aid, with_cred=True)["cred"]["proxy_pass"] == "newpass")
    c.patch(f"/api/accounts/{aid}", json={"proxy_pass_clear": True})
    ok("proxy: proxy_pass_clear removes password", "proxy_pass" not in core.get_account(aid, with_cred=True)["cred"])
    c.patch(f"/api/accounts/{aid}", json={"proxy": "socks5://old:fmt@198.51.100.7:1080", "proxy_user": ""})
    ok("proxy: legacy URL with embedded user:pass still works",
       core.runtime_cred(core.get_account(aid, with_cred=True)["cred"])["proxy"] == "socks5://old:fmt@198.51.100.7:1080"
       and [a for a in c.get("/api/accounts").json() if a["id"] == aid][0]["proxy_user"] == "old")
    ok("proxy: user without proxy url rejected", c.patch(f"/api/accounts/{oid}", json={"proxy_user": "x"}).status_code == 400)
    c.patch(f"/api/accounts/{aid}", json={"proxy": ""})
    cr = core.get_account(aid, with_cred=True)["cred"]
    ok("proxy: empty proxy clears url/user/pass", not ({"proxy", "proxy_user", "proxy_pass"} & set(cr)))

    # ================= 3. 账号编辑回显 =================
    det = c.get(f"/api/accounts/{oid}/detail").json()
    ok("detail: non-sensitive echoed, ids masked, key only 'set'", det["fields"]["region"] == "ap-tokyo-1"
       and det["fields"]["key_content"] == {"set": True} and det["fields"]["user"]["hint"] == "…123456"
       and "FAKE" not in json.dumps(det) and "fakeuser" not in json.dumps(det))
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}) as t:
        c.patch(f"/api/accounts/{oid}", json={"cred": {"key_content": "", "region": "ap-osaka-1", "compartment": "ocid1.compartment.oc1..x"}})
        cr = core.get_account(oid, with_cred=True)["cred"]
        ok("edit: blank secret kept, region/compartment updated after test", t.called and cr["key_content"].startswith("-----BEGIN")
           and cr["region"] == "ap-osaka-1" and core.get_account(oid)["region"] == "ap-osaka-1")
    with mock.patch.object(OCIProvider, "test", side_effect=RuntimeError("401 NotAuthenticated")):
        r = c.patch(f"/api/accounts/{oid}", json={"cred": {"fingerprint": "zz:zz"}})
        ok("edit: failed credential test -> 400, nothing saved", r.status_code == 400
           and core.get_account(oid, with_cred=True)["cred"]["fingerprint"] == "aa:bb")
    ok("edit: empty region rejected", c.patch(f"/api/accounts/{oid}", json={"cred": {"region": ""}}).status_code == 400)
    c.patch(f"/api/accounts/{oid}", json={"region": "ap-tokyo-1"})

    # ================= 4. 默认创建参数 =================
    ok("create-defaults: empty by default", c.get("/api/create-defaults/oci").json() == {})
    r = c.put("/api/create-defaults", json={"provider": "oci", "defaults": {"shape": "VM.Standard.A1.Flex", "ocpus": "2",
                                                                            "memory_gb": "12", "password": "x", "ssh_key": "ssh-ed25519 AAAA"}})
    g = c.get("/api/create-defaults/oci").json()
    ok("create-defaults: saved per provider, password stripped", r.status_code == 200 and g["ocpus"] == "2" and "password" not in g)
    c.put("/api/create-defaults", json={"provider": "lightsail", "defaults": {"bundle": "nano_3_0"}})
    s = c.get("/api/settings").json()["default_create"]
    ok("create-defaults: same data as settings.default_create (both kept)", s["oci"]["shape"] == "VM.Standard.A1.Flex"
       and s["lightsail"]["bundle"] == "nano_3_0")
    ok("create-defaults: bad provider 400", c.get("/api/create-defaults/gcp").status_code == 400
       and c.put("/api/create-defaults", json={"provider": "gcp", "defaults": {}}).status_code == 400)

    # ================= 5. OCI 安全组 =================
    with mock.patch.object(services, "provider", fake_oci):
        lst = c.get(f"/api/accounts/{oid}/security-rules?instance_id=ocid1.instance.x").json()
        ok("secgroup: flat list with list id/name, ports", len(lst["rules"]) == 2 and lst["rules"][0]["sl_id"] == "sl-1"
           and lst["rules"][0]["port_min"] == 22 and lst["lists"][0]["name"] == "Default Security List")
        r = c.post(f"/api/accounts/{oid}/security-rules", json={"instance_id": "x", "rule": {
            "direction": "ingress", "protocol": "tcp", "source": "203.0.113.0/24", "ports": "80, 443\n8000-8100"}}).json()
        ing = VNET.lists["sl-1"].ingress_security_rules
        ok("secgroup: batch ports -> one rule per range, single update", r["added"] == 3 and len(ing) == 4 and VNET.updates == 1
           and ing[-1].tcp_options.destination_port_range.min == 8000)
        r = c.post(f"/api/accounts/{oid}/security-rules", json={"instance_id": "x", "direction": "ingress", "protocol": "tcp",
                                                                "cidr": "203.0.113.0/24", "ports": "80,2222"}).json()
        ok("secgroup: existing rules skipped (dedupe)", r["added"] == 1 and r["skipped"] == 1)
        r = c.post(f"/api/accounts/{oid}/security-rules", json={"instance_id": "x", "direction": "ingress", "protocol": "tcp",
                                                                "cidr": "0.0.0.0/0", "ports": "443"})
        ok("secgroup: 0.0.0.0/0 needs confirm (409 + warning)", r.status_code == 409 and r.json()["detail"]["public_warning"])
        r = c.post(f"/api/accounts/{oid}/security-rules", json={"instance_id": "x", "direction": "ingress", "protocol": "tcp",
                                                                "cidr": "0.0.0.0/0", "ports": "443", "confirm_public": True})
        ok("secgroup: 0.0.0.0/0 accepted after confirm", r.status_code == 200 and r.json()["added"] == 1)
        bad = [c.post(f"/api/accounts/{oid}/security-rules", json=dict(b, instance_id="x", direction="ingress", confirm_public=True)).status_code
               for b in ({"protocol": "all", "cidr": "0.0.0.0/0"}, {"protocol": "tcp", "cidr": "0.0.0.0/0"},
                         {"protocol": "udp", "cidr": "::/0", "ports": "1-65535"})]
        ok("secgroup: open-all-ports to public still refused", bad == [400, 400, 400])
        ok("secgroup: invalid port 400", c.post(f"/api/accounts/{oid}/security-rules", json={
            "instance_id": "x", "protocol": "tcp", "cidr": "10.0.0.0/8", "ports": "80,70000"}).status_code == 400)
        # v1.5.0：旧实例安全列表的“一键放行”已删除，改为放行指定端口
        u = f"/api/accounts/{oid}/oci/security"
        ok("oci/security: op=open_all removed", c.post(u, json={"op": "open_all", "confirm": True, "sl_id": "sl-1"}).status_code == 400
           and not hasattr(OCIProvider, "open_all"))
        ok("oci/security add_ports: ports required", c.post(u, json={"op": "add_ports", "sl_id": "sl-1", "instance_id": "x",
                                                                    "ports": "", "confirm_public": True}).status_code == 400)
        ok("oci/security add_ports: 1-65535 to public refused", c.post(u, json={"op": "add_ports", "sl_id": "sl-1", "instance_id": "x",
                                                                    "ports": "1-65535", "confirm_public": True}).status_code == 400)
        r = c.post(u, json={"op": "add_ports", "sl_id": "sl-1", "instance_id": "x", "ports": "8443"})
        ok("oci/security add_ports: 0.0.0.0/0 needs confirm", r.status_code == 409 and r.json()["detail"]["public_warning"])
        r = c.post(u, json={"op": "add_ports", "sl_id": "sl-1", "instance_id": "x", "ports": "8443, 9000-9001",
                            "protocols": ["tcp", "udp"], "confirm_public": True})
        ok("oci/security add_ports: tcp+udp, one rule per range", r.status_code == 200 and r.json()["added"] == 4)
        bad = [c.post(u, json=dict(b, op="add", sl_id="sl-1", direction="ingress", confirm_public=True)).status_code
               for b in ({"protocol": "all", "cidr": "0.0.0.0/0"}, {"protocol": "tcp", "cidr": "::/0"})]
        ok("oci/security add: open-all-ports to public refused", bad == [400, 400])
        ok("oci/security add: 0.0.0.0/0 single port needs confirm", c.post(u, json={"op": "add", "sl_id": "sl-1", "direction": "ingress",
           "protocol": "tcp", "cidr": "0.0.0.0/0", "port": "8080"}).status_code == 409)
        n0 = len(VNET.lists["sl-1"].ingress_security_rules)
        r = c.request("DELETE", f"/api/accounts/{oid}/security-rules", json={"instance_id": "x", "rule": {
            "direction": "ingress", "protocol": "tcp", "source": "203.0.113.0/24", "port_min": 443, "port_max": 443}})
        left = [OCIProvider._rule_key(x, "ingress") for x in VNET.lists["sl-1"].ingress_security_rules]
        ok("secgroup: delete by content removes exactly that rule", r.status_code == 200 and len(left) == n0 - 1
           and ("6", "203.0.113.0/24", 443, 443) not in left and ("6", "203.0.113.0/24", 80, 80) in left)
        r = c.request("DELETE", f"/api/accounts/{oid}/security-rules", json={"instance_id": "x", "direction": "ingress",
                                                                             "protocol": "udp", "cidr": "203.0.113.0/24"})
        ok("secgroup: delete non-existing -> 404", r.status_code == 404)
        ok("secgroup: AWS account rejected", c.get(f"/api/accounts/{aid}/security-rules?instance_id=x").status_code == 400)
        # ---- OCI 删除 IPv6 ----
        ok("ipv6 delete: needs confirm", c.post(f"/api/accounts/{oid}/oci/ipv6/delete", json={"instance_id": "x"}).status_code == 400)
        r = c.post(f"/api/accounts/{oid}/oci/ipv6/delete", json={"instance_id": "x", "confirm": True}).json()
        ok("ipv6 delete: all addresses on primary VNIC removed", VNET.deleted_v6 == ["v6-1", "v6-2"] and len(r["deleted"]) == 2)
        ok("ipv6 delete: none left -> 404", c.post(f"/api/accounts/{oid}/oci/ipv6/delete", json={"instance_id": "x", "confirm": True}).status_code == 404)

    # ================= 5b. 实例操作「开放端口」（三家云） =================
    from urllib.parse import quote
    op_url = lambda acc, iid: f"/api/accounts/{acc}/instances/{quote(iid, safe='')}/open-port"   # noqa: E731
    # ---- OCI：子网安全列表（假 VNET） ----
    with mock.patch.object(services, "provider", fake_oci):
        u = op_url(oid, "ocid1.instance.oc1..x")
        n_up = VNET.updates
        r = c.post(u, json={"port": "7000"})
        ok("open-port: no confirm_public -> 409 + public_warning, nothing written", r.status_code == 409
           and r.json()["detail"]["public_warning"] is True and VNET.updates == n_up)
        bad = [c.post(u, json=dict(b, confirm_public=True)).status_code for b in (
            {"port": ""}, {}, {"port": "1-65535"}, {"port": "0"}, {"port": "80,70000"}, {"port": "80", "protocol": "icmp"},
            {"port": "1-65535", "protocol": "udp"})]
        ok("open-port: empty / 1-65535 / invalid port / bad protocol -> 400", bad == [400] * 7 and VNET.updates == n_up)
        r = c.post(u, json={"port": "22, 7000-7001", "confirm_public": True})
        j = r.json()
        last = VNET.lists["sl-1"].ingress_security_rules[-1]
        ok("open-port OCI: security list, existing skipped, source 0.0.0.0/0", r.status_code == 200 and j["added"] == 1
           and j["skipped"] == 1 and j["groups"][0]["name"] == "Default Security List" and last.source == "0.0.0.0/0"
           and last.tcp_options.destination_port_range.min == 7000 and last.tcp_options.destination_port_range.max == 7001
           and "新增 1 条" in j["msg"] and "跳过 1 条" in j["msg"])
        r = c.post(u, json={"port": 7000, "protocol": "udp", "confirm_public": True}).json()
        last = VNET.lists["sl-1"].ingress_security_rules[-1]
        ok("open-port OCI: numeric port + udp", r["added"] == 1 and last.protocol == "17"
           and last.udp_options.destination_port_range.min == 7000)
    # ---- AWS：实例关联的全部安全组（moto） ----
    with mock_aws():
        services.drop_provider_cache(aid)
        import boto3
        ec2 = boto3.client("ec2", region_name="us-east-1")
        sg1 = ec2.create_security_group(GroupName="tc-web", Description="web")["GroupId"]
        sg2 = ec2.create_security_group(GroupName="tc-app", Description="app")["GroupId"]
        ec2.authorize_security_group_ingress(GroupId=sg1, IpPermissions=[{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                                                                         "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
        ami = ec2.describe_images()["Images"][0]["ImageId"]
        ec2_iid = ec2.run_instances(ImageId=ami, MinCount=1, MaxCount=1, InstanceType="t3.micro",
                                    SecurityGroupIds=[sg1, sg2])["Instances"][0]["InstanceId"]
        u = op_url(aid, ec2_iid)
        ok("open-port AWS: needs confirm (409)", c.post(u, json={"port": "8080"}).status_code == 409)
        r = c.post(u, json={"port": "443, 8000-8100", "confirm_public": True})
        j = r.json()
        g = {x["id"]: x for x in j.get("groups", [])}
        perms = {x["GroupId"]: x["IpPermissions"] for x in ec2.describe_security_groups(GroupIds=[sg1, sg2])["SecurityGroups"]}
        has = lambda sg, a, b, pr="tcp": any(p["IpProtocol"] == pr and p.get("FromPort") == a and p.get("ToPort") == b and  # noqa: E731
                                            any(x["CidrIp"] == "0.0.0.0/0" for x in p.get("IpRanges", [])) for p in perms[sg])
        ok("open-port AWS: all security groups written, duplicates skipped", r.status_code == 200 and j["added"] == 3
           and j["skipped"] == 1 and g[sg1]["added"] == 1 and g[sg1]["skipped"] == 1 and g[sg2]["added"] == 2
           and g[sg2]["name"] == "tc-app" and has(sg1, 8000, 8100) and has(sg2, 443, 443) and has(sg2, 8000, 8100))
        r = c.post(u, json={"port": "443,8000-8100", "protocol": "tcp", "confirm_public": True}).json()
        ok("open-port AWS: repeat -> all skipped", r["added"] == 0 and r["skipped"] == 4)
        r = c.post(u, json={"port": "443", "protocol": "udp", "confirm_public": True}).json()
        perms = {x["GroupId"]: x["IpPermissions"] for x in ec2.describe_security_groups(GroupIds=[sg1, sg2])["SecurityGroups"]}
        ok("open-port AWS: udp is a separate rule", r["added"] == 2 and has(sg1, 443, 443, "udp") and has(sg2, 443, 443, "udp"))
        ok("open-port AWS: Lightsail rejected", c.post(u, json={"port": "80", "kind": "lightsail", "confirm_public": True}).status_code == 400)
        services.drop_provider_cache(aid)

    # ---- Azure：网卡 NSG + 子网 NSG（假 client） ----
    class FakePoller:
        def __init__(self, v):
            self.v = v

        def result(self):
            return self.v

    class FakeRules:
        def __init__(self):
            def R(name, prio, port=None, ports=None, src="*", srcs=None, proto="Tcp", access="Allow", direction="Inbound"):
                return Obj(name=name, priority=prio, protocol=proto, access=access, direction=direction, source_address_prefix=src,
                           source_address_prefixes=srcs, destination_port_range=port, destination_port_ranges=ports)
            self.nsg = {("rg1", "nsg-nic"): [R("SSH", 100, "22"), R("tricloud-tcp-8443", 110, "8443", src="10.0.0.0/8"),
                                              R("web", 120, ports=["80", "443"], src="Internet"),
                                              R("deny9000", 130, "9000-9001", access="Deny")],
                        ("rg-net", "nsg-sub"): []}
            self.created = []

        def list(self, rg, nsg):
            return list(self.nsg[(rg, nsg)])

        def begin_create_or_update(self, rg, nsg, name, rule):
            rule.name = name
            self.nsg[(rg, nsg)].append(rule)
            self.created.append((nsg, name, rule))
            return FakePoller(rule)

    SUB = "/subscriptions/00000000-0000-0000-0000-000000000000"
    AZ_VM = f"{SUB}/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
    AZR = FakeRules()
    seen_subnet = []

    def fake_az(acc_id, region=None):
        p = AzureProvider.__new__(AzureProvider)
        p.cred = {}
        p.compute = Obj(virtual_machines=Obj(get=lambda rg, n: Obj(network_profile=Obj(network_interfaces=[
            Obj(id=f"{SUB}/resourceGroups/rg1/providers/Microsoft.Network/networkInterfaces/vm1-nic", primary=True)]))))
        p.network = Obj(
            network_interfaces=Obj(get=lambda rg, n: Obj(
                network_security_group=Obj(id=f"{SUB}/resourceGroups/rg1/providers/Microsoft.Network/networkSecurityGroups/nsg-nic"),
                ip_configurations=[Obj(subnet=Obj(id=f"{SUB}/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/default"))])),
            subnets=Obj(get=lambda rg, v, s: seen_subnet.append((rg, v, s)) or Obj(network_security_group=Obj(
                id=f"{SUB}/resourceGroups/rg-net/providers/Microsoft.Network/networkSecurityGroups/nsg-sub"))),
            security_rules=AZR)
        return p

    with mock.patch.object(AzureProvider, "test", return_value={"ok": True}):
        zid = c.post("/api/accounts", json={"provider": "azure", "name": "az-open", "cred": {
            "tenant_id": "t", "client_id": "c", "client_secret": "s", "subscription_id": "00000000-0000-0000-0000-000000000000"}}).json()["id"]
    with mock.patch.object(services, "provider", fake_az):
        u = op_url(zid, AZ_VM)
        ok("open-port Azure: needs confirm (409) / empty port 400", c.post(u, json={"port": "443"}).status_code == 409
           and c.post(u, json={"port": " ", "confirm_public": True}).status_code == 400 and not AZR.created)
        r = c.post(u, json={"port": "443, 8443, 9000-9001", "confirm_public": True})
        j = r.json()
        g = {x["name"]: x for x in j.get("groups", [])}
        nic_new = {n: rl for nsg, n, rl in AZR.created if nsg == "nsg-nic"}
        sub_new = [rl for nsg, n, rl in AZR.created if nsg == "nsg-sub"]
        ok("open-port Azure: NIC + subnet NSG, covered port skipped", r.status_code == 200 and seen_subnet == [("rg-net", "vnet1", "default")]
           and g["nsg-nic"]["added"] == 2 and g["nsg-nic"]["skipped"] == 1 and g["nsg-sub"]["added"] == 3 and j["added"] == 5)
        ok("open-port Azure: unique rule name, free priority, inbound allow 0.0.0.0/0",
           set(nic_new) == {"tricloud-tcp-8443-2", "tricloud-tcp-9000-9001"} and nic_new["tricloud-tcp-8443-2"].priority == 140
           and nic_new["tricloud-tcp-9000-9001"].priority == 150 and [x.priority for x in sub_new] == [100, 110, 120]
           and all(x.access == "Allow" and x.direction == "Inbound" and x.protocol == "Tcp" and x.source_address_prefix == "0.0.0.0/0"
                   for x in sub_new + list(nic_new.values())))
        r = c.post(u, json={"port": "443,8443,9000-9001", "confirm_public": True}).json()
        ok("open-port Azure: repeat -> all skipped", r["added"] == 0 and r["skipped"] == 6 and len(AZR.created) == 5)
        r = c.post(op_url(zid, "-"), json={"instance_id": AZ_VM, "port": "51820", "protocol": "udp", "confirm_public": True}).json()
        ok("open-port Azure: udp + instance_id in body", r["added"] == 2 and AZR.created[-1][2].protocol == "Udp"
           and AZR.created[-1][1] == "tricloud-udp-51820")
    ok("open-port: route registered for all clouds", any(getattr(x, "path", "").endswith("/instances/{iid:path}/open-port")
                                                         for x in main.app.routes))

    # ================= 6. AWS CloudFront（moto） =================
    with mock_aws():
        services.drop_provider_cache(aid)
        r = c.post(f"/api/accounts/{aid}/cloudfront", json={"op": "create", "origin": "https://origin.example.com/",
                                                             "comment": "site", "price_class": "100", "cache_mode": "optimized",
                                                             "compress": False}).json()
        did = r["id"]
        cfg = services.provider(aid)._cf().get_distribution_config(Id=did)["DistributionConfig"]
        ok("cloudfront: create with price class / cache mode / compress", cfg["PriceClass"] == "PriceClass_100"
           and cfg["DefaultCacheBehavior"]["CachePolicyId"] == "658327ea-f89d-4fab-a63d-7e88639e58f6"
           and cfg["DefaultCacheBehavior"]["Compress"] is False and cfg["Origins"]["Items"][0]["DomainName"] == "origin.example.com")
        r2 = c.post(f"/api/accounts/{aid}/cloudfront", json={"op": "create", "origin": "legacy.example.com"}).json()
        cfg2 = services.provider(aid)._cf().get_distribution_config(Id=r2["id"])["DistributionConfig"]
        ok("cloudfront: v1.4 create defaults unchanged", cfg2["PriceClass"] == "PriceClass_All"
           and cfg2["DefaultCacheBehavior"]["CachePolicyId"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad")
        ok("cloudfront: bad origin 400", c.post(f"/api/accounts/{aid}/cloudfront", json={"op": "create", "origin": ""}).status_code == 400)
        lst = c.get(f"/api/accounts/{aid}/cloudfront").json()
        ok("cloudfront: list has price_class + plan field", {d["id"] for d in lst} == {did, r2["id"]}
           and [d for d in lst if d["id"] == did][0]["price_class"] == "100" and "plan" in lst[0])
        g = c.get(f"/api/accounts/{aid}/cloudfront/{did}/config").json()
        ok("cloudfront: GET config", g["comment"] == "site" and g["origin_domain"] == "origin.example.com" and g["enabled"] is True)
        u = c.put(f"/api/accounts/{aid}/cloudfront/{did}", json={"comment": "new", "price_class": "200", "default_root_object": "/index.html",
                                                                  "origin_protocol": "https-only"})
        g = c.get(f"/api/accounts/{aid}/cloudfront/{did}/config").json()
        ok("cloudfront: PUT config", u.status_code == 200 and g["comment"] == "new" and g["price_class"] == "200"
           and g["default_root_object"] == "index.html" and g["origin_protocol"] == "https-only")
        ok("cloudfront: PUT validation", c.put(f"/api/accounts/{aid}/cloudfront/{did}", json={"price_class": "300"}).status_code == 400
           and c.put(f"/api/accounts/{aid}/cloudfront/{did}", json={}).status_code == 400)
        r = c.post(f"/api/accounts/{aid}/cloudfront/invalidate", json={"distribution_id": did, "paths": "index.html\n/css/*,/a"}).json()
        ok("cloudfront: invalidate normalizes paths", r["paths"] == ["/index.html", "/css/*", "/a"] and r["invalidation_id"])
        r = c.post(f"/api/accounts/{aid}/cloudfront/invalidate", json={"distribution_id": did}).json()
        ok("cloudfront: invalidate default /*", r["paths"] == ["/*"])
        ok("cloudfront: invalidate >100 paths refused", c.post(f"/api/accounts/{aid}/cloudfront/invalidate", json={
            "distribution_id": did, "paths": [f"/p{i}" for i in range(101)]}).status_code == 400)
        c.post(f"/api/accounts/{aid}/cloudfront/toggle", json={"distribution_id": r2["id"], "enabled": False})
        ok("cloudfront: toggle disable", services.provider(aid).cf_state(r2["id"])["enabled"] is False)
        ok("cloudfront: delete needs confirm", c.delete(f"/api/accounts/{aid}/cloudfront/{did}").status_code == 400)
        r = c.delete(f"/api/accounts/{aid}/cloudfront/{r2['id']}?confirm=true").json()
        ok("cloudfront: disabled+Deployed deleted directly", r["deleted"] is True
           and r2["id"] not in [d["id"] for d in c.get(f"/api/accounts/{aid}/cloudfront").json()])
        r = c.delete(f"/api/accounts/{aid}/cloudfront/{did}?confirm=true").json()
        ok("cloudfront: enabled dist -> background task (disable first)", r["deleted"] is False and r["task_id"])
        real_state, calls = AWSProvider.cf_state, {"n": 0}

        def slow_state(self, d):   # 模拟停用后部署需要一段时间：前 2 次查询为 InProgress
            st = real_state(self, d)
            if not st["enabled"] and calls["n"] < 2:
                calls["n"] += 1
                st["status"] = "InProgress"
            return st
        with mock.patch.object(AWSProvider, "cf_state", slow_state), mock.patch.object(tasks, "CF_POLL_SECONDS", 0):
            run_task(r["task_id"])
        t = c.get(f"/api/tasks/{r['task_id']}").json()
        ok("cloudfront: task disables, waits for Deployed, then deletes", t["status"] == "done" and calls["n"] == 2
           and did not in [d["id"] for d in c.get(f"/api/accounts/{aid}/cloudfront").json()]
           and any("先停用" in x["msg"] for x in t["logs"]) and any("等待停用部署完成" in x["msg"] for x in t["logs"]))

        # ---- 套餐（pricing-plan-manager：moto 不支持，用假客户端） ----
        class PPM:
            def __init__(self):
                self.subs, self.created, self.disassoc = [], [], []

            def get_paginator(self, name):
                outer = self
                return Obj(paginate=lambda: [{"subscriptionSummaries": outer.subs}])

            def create_subscription(self, **kw):
                self.created.append(kw)
                self.subs.append({"arn": "arn:sub/1", "planFamily": "CloudFront", "planTier": kw["planTier"], "status": "ACTIVE",
                                  "resourceArns": kw["resourceArns"]})
                return {"subscription": {"status": "ACTIVE"}}

            def disassociate_resources_from_subscription(self, **kw):
                self.disassoc.append(kw)
                self.subs.clear()
        ppm = PPM()
        r3 = c.post(f"/api/accounts/{aid}/cloudfront", json={"op": "create", "origin": "plan.example.com"}).json()
        with mock.patch.object(AWSProvider, "_ppm", lambda self: ppm):
            ok("cf plan: paid tier needs confirm", c.post(f"/api/accounts/{aid}/cloudfront/plan", json={
                "distribution_id": r3["id"], "plan_tier": "PRO"}).status_code == 400 and not ppm.created)
            ok("cf plan: bad tier 400", c.post(f"/api/accounts/{aid}/cloudfront/plan", json={
                "distribution_id": r3["id"], "plan_tier": "GOLD"}).status_code == 400)
            r = c.post(f"/api/accounts/{aid}/cloudfront/plan", json={"distribution_id": r3["id"], "plan_tier": "pro", "confirm": True}).json()
            ok("cf plan: subscribe PRO with distribution ARN", r["plan"] == "PRO" and ppm.created[0]["planFamily"] == "CloudFront"
               and ppm.created[0]["resourceArns"][0].endswith(f":distribution/{r3['id']}"))
            ok("cf plan: list shows plan", [d for d in c.get(f"/api/accounts/{aid}/cloudfront").json() if d["id"] == r3["id"]][0]["plan"] == "PRO")
            r = c.post(f"/api/accounts/{aid}/cloudfront/plan", json={"distribution_id": r3["id"], "plan_tier": "paygo"}).json()
            ok("cf plan: back to pay-as-you-go (disassociate)", r["plan"] == "PAYGO" and ppm.disassoc)

    # ================= 7. 已删账号回收站 =================
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        a2 = c.post("/api/accounts", json={"provider": "aws", "name": "aws-old", "cloud_created_at": "2026-01-01",
                                           "cred": {"access_key": "AK2", "secret_key": "s", "region": "us-east-1"}}).json()["id"]
    core.ex("INSERT INTO billing_cache(account_id,data,fetched_at) VALUES(?,?,?)",
            (a2, json.dumps({"period": "2026-10", "total": 3.21, "currency": "USD"}), int(time.time())))
    core.ex("INSERT INTO billing_months(account_id,month,total,currency,updated) VALUES(?,?,?,?,?)", (oid, "2026-10", 1.5, "USD", 0))
    with mock.patch.object(services, "billing", side_effect=AssertionError("must not call cloud")):
        c.delete(f"/api/accounts/{a2}")
        c.delete(f"/api/accounts/{oid}")
    rb = c.get("/api/recycle-bin").json()
    it = {x["name"]: x for x in rb["items"]}
    ok("deleted-accounts: entries recorded on delete (no cloud call)", set(it) == {"aws-old", "oci-tokyo"})
    ok("deleted-accounts: AWS cost from billing cache, age from cloud date", it["aws-old"]["est_cost"] == 3.21
       and it["aws-old"]["age_basis"] == "云上创建日期" and it["aws-old"]["lifecycle_days"] > 200)
    ok("deleted-accounts: OCI cost from billing month, age from panel time", it["oci-tokyo"]["est_cost"] == 1.5
       and it["oci-tokyo"]["age_basis"] == "面板添加时间")
    st = c.get("/api/recycle-bin/stats").json()
    ok("deleted-accounts: stats", st["count"] == 2 and st["by_provider"] == {"aws": 1, "oci": 1} and st["total_est_cost_usd"] == 4.71)
    ok("deleted-accounts: AWS idle-resource estimate route still separate",
       any(p == "/api/accounts/{acc_id}/recycle" for p in paths) and "/api/recycle-bin" in paths)
    ok("deleted-accounts: clear needs confirm", c.delete("/api/recycle-bin").status_code == 400)
    c.delete(f"/api/recycle-bin/{it['aws-old']['id']}")
    ok("deleted-accounts: delete one record", c.get("/api/recycle-bin/stats").json()["count"] == 1)

    # ================= 8. TG 内联按钮 =================
    core.set_setting("tg_chat_id", "42")
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}):
        oid2 = c.post("/api/accounts", json={"provider": "oci", "name": "oci-osaka", "cred": {
            "user": "u", "tenancy": "t", "fingerprint": "f", "key_content": "k", "region": "ap-osaka-1"}}).json()["id"]
    bot = Bot()
    asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "/start"}))
    ok("tg: /start shows button menu with 3 clouds", sum(1 for t in bot.texts() if t.startswith("☁️")) == 3
       and any("一键测活" in t for t in bot.texts()))
    asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 99}, "text": "/start"}))
    ok("tg: other chat_id ignored (message)", len(bot.calls) == 1)
    cbq(bot, bot.btn("Oracle"), chat=99)
    ok("tg: other chat_id refused (callback)", bot.calls[-1][0] == "answerCallbackQuery" and bot.calls[-1][1].get("text") == "未授权")
    cbq(bot, bot.btn("Oracle"))
    ok("tg: cloud -> account list", "oci-osaka" in " ".join(bot.texts()))
    cbq(bot, bot.btn("oci-osaka"))
    ok("tg: account menu (instances / billing / test)", {"🖥 实例", "💰 账单", "⚡ 测活"} <= set(bot.texts()))
    inst = [{"id": "ocid1.instance.a", "name": "web1", "state": "running", "public_ip": "203.0.113.9", "region": "ap-osaka-1"}]
    with mock.patch.object(services, "list_instances", return_value=inst):
        cbq(bot, bot.btn("实例"))
    ok("tg: instance list", any("web1" in t and "203.0.113.9" in t for t in bot.texts()))
    cbq(bot, bot.btn("web1"))
    ok("tg: instance view with start/stop/reboot/changeip/ipv6/terminate",
       {"启动", "停止", "重启", "换 IP", "加 IPv6", "删 IPv6", "终止", "🔄 刷新状态"} <= set(bot.texts()))
    with mock.patch.object(services, "get_state", return_value="stopped"):
        cbq(bot, bot.btn("刷新状态"))
    ok("tg: refresh state", "stopped" in bot.last()["text"])
    cbq(bot, bot.btn("终止"))
    ok("tg: danger op asks confirm with warning", "不可恢复" in bot.last()["text"] and {"✅ 确认终止", "取消"} <= set(bot.texts()))
    did = []
    with mock.patch.object(services, "instance_action", side_effect=lambda *a: did.append(a)):
        cbq(bot, bot.btn("取消"))
        ok("tg: cancel goes back, nothing executed", not did and "启动" in bot.texts())
        cbq(bot, bot.btn("重启"))
        cbq(bot, bot.btn("确认"))
    ok("tg: confirmed op executes with region & kind", did == [(oid2, "ocid1.instance.a", "reboot", "ap-osaka-1", "vm")])
    cbq(bot, bot.btn("« 实例"))
    cbq(bot, bot.btn("换 IP"))
    cbq(bot, bot.btn("确认"))
    tid = core.q("SELECT id, params FROM tasks WHERE type='change_ip' ORDER BY id DESC LIMIT 1", one=True)
    ok("tg: change IP creates task", tid and json.loads(tid["params"])["instance_id"] == "ocid1.instance.a" and f"#{tid['id']}" in bot.last()["text"])
    cbq(bot, bot.btn("« 实例"))
    with mock.patch.object(OCIProvider, "delete_ipv6", lambda self, i: {"deleted": ["2001:db8::9"]}):
        cbq(bot, bot.btn("删 IPv6"))
        cbq(bot, bot.btn("确认"))
    ok("tg: delete IPv6 after confirm", "2001:db8::9" in bot.last()["text"])
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}):
        cbq(bot, telegram._key({"t": "test", "a": oid2}))
    ok("tg: test account", "✅ oci-osaka" in bot.last()["text"])
    cbq(bot, telegram._key({"t": "tasks"}))
    ok("tg: recent tasks button", "最近" in bot.last()["text"])
    cbq(bot, "deadbeef")
    ok("tg: expired button handled", "过期" in bot.last()["text"])
    asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "/tasks"}))
    asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "/help"}))
    ok("tg: existing commands kept", "最近" in bot.calls[-2][1]["text"] and all(x in bot.last()["text"] for x in
       ("/bill", "/tasks", "/credits", "/health", "/traffic")))

    # ---- TG：实例操作「开放端口」：先回复端口号，再二次确认 ----
    cbq(bot, telegram._key({"t": "inst", "a": oid2, "p": "oci", "i": "ocid1.instance.a", "k": "vm", "n": "web1", "s": "running",
                            "ip": "203.0.113.9", "r": "ap-osaka-1"}))
    ok("tg open-port: button in instance view", "开放端口" in bot.texts())
    opened = []
    with mock.patch.object(OCIProvider, "open_ports", lambda self, i, pr, rg: opened.append((i, pr, rg)) or {
            "added": 1, "skipped": 0, "groups": [{"kind": "安全列表", "name": "Default Security List", "added": 1, "skipped": 0}]}):
        cbq(bot, bot.btn("开放端口"))
        ok("tg open-port: asks for port reply", "回复端口号" in bot.last()["text"] and not opened)
        asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "1-65535"}))
        ok("tg open-port: all ports refused, can retry", "全部端口" in bot.last()["text"] and "42" in telegram._await_port)
        asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "udp 51820, 8000-8001"}))
        ok("tg open-port: confirm with public warning, nothing executed yet", "0.0.0.0/0" in bot.last()["text"]
           and "UDP" in bot.last()["text"] and "✅ 确认开放端口" in bot.texts() and not opened)
        cbq(bot, bot.btn("确认开放端口"))
        ok("tg open-port: executed after confirm", opened == [("ocid1.instance.a", "udp", [(51820, 51820), (8000, 8001)])]
           and "新增 1 条" in bot.last()["text"])
        cbq(bot, bot.btn("« 实例"))
        cbq(bot, bot.btn("开放端口"))
        asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "/cancel"}))
        asyncio.run(telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "8443"}))
        ok("tg open-port: /cancel clears pending (next text is not a port)", len(opened) == 1 and "/start" in bot.last()["text"])
    ok("tg open-port: Lightsail has no open-port", "openport" not in telegram._inst_ops("aws", "lightsail")
       and "openport" in telegram._inst_ops("azure", "vm"))

    class FailEdit(Bot):
        async def call(self, method, body):
            self.calls.append((method, body))
            return {"ok": False, "description": "message can't be edited"} if method == "editMessageText" else {"ok": True}
    fb = FailEdit()
    cbq(fb, telegram._key({"t": "home"}))
    ok("tg: edit failure falls back to new message", fb.calls[-1][0] == "sendMessage")

    # ================= 9. 旧版 API Token =================
    legacy_plain = "Lg" + "x" * 41
    core.ex("INSERT INTO api_tokens(name,token_hash,prefix,scope,created,last_used) VALUES(?,?,?,?,?,0)",
            ("old", hashlib.sha256(legacy_plain.encode()).hexdigest(), "legacy", "read", 1))
    core.ex("INSERT INTO api_tokens(name,token_hash,prefix,scope,created,last_used) VALUES(?,?,?,?,?,0)",
            ("weird", hashlib.sha256(b"notlegacy-token-0000000000").hexdigest(), "abc", "full", 1))
    anon = TestClient(main.app)
    ok("legacy token: migrated read token works for GET", anon.get("/api/accounts", headers={"Authorization": f"Bearer {legacy_plain}"}).status_code == 200)
    ok("legacy token: read scope cannot write", anon.post("/api/accounts/test-all", json={},
                                                          headers={"Authorization": f"Bearer {legacy_plain}"}).status_code == 401)
    ok("legacy token: non-tc_ token without legacy prefix rejected",
       anon.get("/api/accounts", headers={"Authorization": "Bearer notlegacy-token-0000000000"}).status_code == 401)
    ok("legacy token: audit records id, not token text", not any(legacy_plain[:10] in (a["actor"] or "") for a in c.get("/api/audit").json()))

# ================= 10. 断点续抢 =================
now = int(time.time())
t_sn = core.ex("INSERT INTO tasks(type,account_id,params,status,attempts,message,created,updated) VALUES(?,?,?,?,?,?,?,?)",
               ("snatch", oid2, json.dumps({"create": {"shape": "VM.Standard.A1.Flex"}, "interval": 60, "next_run": now + 9999}),
                "running", 37, "第 37 次：容量不足", now, now))
t_q = core.ex("INSERT INTO tasks(type,account_id,params,status,attempts,message,created,updated) VALUES(?,?,?,?,?,?,?,?)",
              ("snatch", oid2, json.dumps({"create": {}, "next_run": now}), "queued", 0, "排队中", now, now))
t_ip = core.ex("INSERT INTO tasks(type,account_id,params,status,attempts,message,created,updated) VALUES(?,?,?,?,?,?,?,?)",
               ("change_ip", oid2, json.dumps({"instance_id": "i", "next_run": 2 ** 40}), "running", 1, "执行中…", now, now))
t_done = core.ex("INSERT INTO tasks(type,account_id,params,status,attempts,message,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                 ("resize", oid2, "{}", "done", 1, "ok", now, now))
with TestClient(main.app) as c:     # 重新走一遍 lifespan = 模拟服务重启
    c.post("/api/login", json={"password": "devpassword123"})
    st = {r["id"]: r for r in core.q("SELECT * FROM tasks")}
    p_sn = json.loads(st[t_sn]["params"])
    ok("resume: running snatch requeued, attempts kept", st[t_sn]["status"] == "running" and st[t_sn]["attempts"] == 37
       and p_sn["next_run"] <= int(time.time()) + 10 and "断点续抢" in st[t_sn]["message"])
    ok("resume: queued snatch -> running", st[t_q]["status"] == "running")
    ok("resume: other running task -> interrupted", st[t_ip]["status"] == "interrupted" and st[t_done]["status"] == "done")
    ok("resume: interrupted can be deleted, not stopped", c.delete(f"/api/tasks/{t_ip}").status_code == 200
       and not core.q("SELECT 1 FROM tasks WHERE id=?", (t_ip,), one=True))

# ================= 11. 旧版数据迁移脚本 =================
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

L = tempfile.mkdtemp()
NEW = os.path.join(tempfile.mkdtemp(), "data")
legacy_key = Fernet.generate_key()
open(os.path.join(L, "fernet.key"), "wb").write(legacy_key)
LF = Fernet(legacy_key)
pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
FAKE = {
    "oci": {"tenancy_ocid": "ocid1.tenancy.oc1..aaaaaaaafaketenancy", "user_ocid": "ocid1.user.oc1..aaaaaaaafakeuser",
            "fingerprint": "12:34:56:78:9a:bc:de:f0:12:34:56:78:9a:bc:de:f0", "region": "ap-tokyo-1",
            "private_key": pem.replace("\n", "\\n"), "default_ssh_key": "ssh-ed25519 AAAAFAKEKEY test",
            "default_subnet_ocid": "ocid1.subnet.oc1.ap-tokyo-1.aaaaaaaafakesubnet", "legacy_extra": "drop-me"},
    "aws": {"access_key": "AKIAFAKELEGACY0001", "secret_key": "fakeSecretKeyLegacy/0001", "region": "ap-northeast-1"},
    "azure": {"client_id": "11111111-2222-3333-4444-555555555555", "client_secret": "fake~azure~secret",
              "tenant_id": "66666666-7777-8888-9999-000000000000", "subscription_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
}
ldb = os.path.join(L, "tricloud.db")
lc = sqlite3.connect(ldb)
lc.executescript(open(os.path.join(ROOT, "tests", "fixtures", "legacy_schema.sql"), encoding="utf-8").read())
T0 = 1767225600.0     # 2026-01-01 08:00 +08:00
lc.execute("INSERT INTO accounts(id,provider,name,creds_enc,created_at,updated_at,credit_total,cloud_created_at,edu_expires_at,"
           "proxy_url,proxy_user,proxy_pass_enc) VALUES(3,'oci','东京甲骨文',?,?,?,NULL,?,NULL,'socks5://proxy.example.test:1080','pu',?)",
           (LF.encrypt(json.dumps(FAKE["oci"]).encode()), T0, T0, T0, LF.encrypt(b"fake-proxy-pass")))
lc.execute("INSERT INTO accounts(id,provider,name,creds_enc,created_at,updated_at,credit_total,cloud_created_at) VALUES(5,'aws','AWS 主号',?,?,?,300,?)",
           (LF.encrypt(json.dumps(FAKE["aws"]).encode()), T0, T0, T0 + 86400))
lc.execute("INSERT INTO accounts(id,provider,name,creds_enc,created_at,updated_at,edu_expires_at) VALUES(8,'azure','学生订阅',?,?,?,?)",
           (LF.encrypt(json.dumps(FAKE["azure"]).encode()), T0, T0, T0 + 365 * 86400))
lc.execute("INSERT INTO account_credits(account_id,name,amount,expires_at,created_at,start_at,ce_baseline) VALUES(5,'教程奖励',100,?,?,?,12.5)",
           (T0 + 200 * 86400, T0, T0))
lc.execute("INSERT INTO audit_log(ts,ip,action,detail) VALUES(?,?,?,?)", (T0, "192.0.2.10", "login_ok", ""))
lc.execute("INSERT INTO audit_log(ts,ip,action,detail) VALUES(?,?,?,?)", (T0 + 5, "192.0.2.10", "account_create", "aws / AWS 主号"))
lc.execute("INSERT INTO script_templates(name,os_type,content,created_at) VALUES('bbr','linux','#!/bin/bash\necho bbr',?)", (T0,))
lc.execute("INSERT INTO script_templates(name,os_type,content,created_at) VALUES('rdp','windows','echo rdp',?)", (T0,))
lc.execute("INSERT INTO dns_mappings(account_id,instance_id,zone_name,record_name,created_at) VALUES(3,'ocid1.instance.oc1..i1','example.com','vps.example.com',?)", (T0,))
lc.execute("INSERT INTO traffic_rules(account_id,instance_key,instance_name,name,metric,window_hours,limit_gb,duration_hours,enabled,state,created_at) "
           "VALUES(3,'ocid1.instance.oc1..i1','web','10G/天','both',24,10,6,1,'triggered',?)", (T0,))
tok_plain = "legacyPlainToken_" + "y" * 26
lc.execute("INSERT INTO api_tokens(name,token_hash,scope,created_at,last_used_at) VALUES('ci',?,'readonly',?,NULL)",
           (hashlib.sha256(tok_plain.encode()).hexdigest(), T0))
lc.execute("INSERT INTO recycle_bin(provider,name,est_cost_usd,lifecycle_days,deleted_at) VALUES('aws','旧号',4.2,33.5,?)", (T0,))
lc.execute("INSERT INTO password_vault(instance_id,instance_name,account_id,password_enc,created_at) VALUES('ocid1.instance.oc1..i1','web',3,?,?)",
           (LF.encrypt(b"RootPw-Fake-1"), T0))
lc.execute("INSERT INTO sessions(token,created_at,expires_at) VALUES('s',1,2)")
lc.execute("INSERT INTO jobs(id,type,provider,account_id,title,status,created_at) VALUES('j','snatch','oci',3,'t','running',1)")
lc.execute("INSERT INTO login_attempts(ip,fail_count,updated_at) VALUES('192.0.2.1',2,'x')")
for k, v in {"tg_bot_token": "123456:FAKE-legacy-bot", "tg_chat_id": "424242",
             "cf_api_token": base64.b64encode(LF.encrypt(b"fake-cf-token")).decode(),
             "create_defaults_oci": json.dumps({"shape": "VM.Standard.E2.1.Micro"}), "daily_report": "1", "daily_report_hour": "8",
             "monitor_interval_min": "10", "password_hash": "x", "password_salt": "y"}.items():
    lc.execute("INSERT INTO meta(key,value) VALUES(?,?)", (k, v))
lc.commit()
lc.close()
legacy_sha = hashlib.sha256(open(ldb, "rb").read()).hexdigest()
MIG = os.path.join(ROOT, "tools", "migrate_from_legacy.py")
env = {k: v for k, v in os.environ.items() if k not in ("TRICLOUD_DATA", "FERNET_KEY")}

dry = subprocess.run([sys.executable, MIG, "--legacy-db", ldb, "--new-data", NEW, "--dry-run"], capture_output=True, text=True, env=env)
secrets_ = ["BEGIN PRIVATE", "fakeSecretKeyLegacy", "fake~azure~secret", "fake-proxy-pass", "123456:FAKE", "fake-cf-token", "RootPw-Fake",
            "AKIAFAKELEGACY", "aaaaaaaafakeuser"]
ok("migrate dry-run: counts + mapping printed, exit 0", dry.returncode == 0 and "tenancy_ocid→tenancy" in dry.stdout
   and "private_key→key_content" in dry.stdout and "proxy_url→proxy" in dry.stdout and "legacy_extra" in dry.stdout)
ok("migrate dry-run: no credential values printed", not [s for s in secrets_ if s in dry.stdout + dry.stderr])
ok("migrate dry-run: nothing written", not os.path.exists(NEW))
bad = subprocess.run([sys.executable, MIG, "--legacy-db", ldb, "--legacy-key", os.path.join(D, "fernet.key"), "--new-data", NEW, "--dry-run"],
                     capture_output=True, text=True, env=env)
ok("migrate: wrong legacy key -> clear error", bad.returncode == 1 and "无法解密" in bad.stdout)
os.rename(os.path.join(L, "fernet.key"), os.path.join(L, "k.bak"))
envk = dict(env, FERNET_KEY=legacy_key.decode())
run1 = subprocess.run([sys.executable, MIG, "--legacy-db", ldb, "--new-data", NEW], capture_output=True, text=True, env=envk)
ok("migrate: real run via FERNET_KEY env", run1.returncode == 0 and "迁移完成" in run1.stdout)
ok("migrate: legacy db untouched (opened read-only)", hashlib.sha256(open(ldb, "rb").read()).hexdigest() == legacy_sha)
run2 = subprocess.run([sys.executable, MIG, "--legacy-db", ldb, "--new-data", NEW], capture_output=True, text=True, env=envk)
ok("migrate: refuses non-empty new db", run2.returncode == 2 and "拒绝写入" in run2.stdout)
ok("migrate: new key differs from legacy key", open(os.path.join(NEW, "fernet.key"), "rb").read().strip() != legacy_key)

VERIFY = r'''
import json, os, sys, hashlib
sys.path.insert(0, sys.argv[1])
from unittest import mock
from app import core, services, main
from fastapi.testclient import TestClient
core.init_db()
out = {}
p = services.provider(3); out["oci"] = {"cfg": {k: p.cfg[k] for k in ("user", "tenancy", "fingerprint", "region", "key_content")},
    "proxy": p.proxy, "compartment": p.compartment, "cred": {k: p.cred.get(k) for k in ("default_ssh_key", "default_subnet_ocid", "legacy_extra")}}
p = services.provider(5); c = p.session.get_credentials()
out["aws"] = {"access_key": c.access_key, "secret_key": c.secret_key, "region": p.region}
p = services.provider(8); out["azure"] = {"sub": p.sub, "tenant": p.credential._tenant_id, "client": p.credential._client_id,
    "secret": p.cred["client_secret"]}
out["accounts"] = core.q("SELECT id, provider, name, region, created, cloud_created_at, credit_total, edu_expires_at FROM accounts ORDER BY id")
out["raw_proxy"] = {k: core.get_account(3, with_cred=True)["cred"].get(k) for k in ("proxy", "proxy_user", "proxy_pass")}
out["credits"] = core.q("SELECT account_id, name, amount, start_date, expire_date, used_manual FROM aws_credits")
out["audit"] = core.q("SELECT ts, ip, actor, action, detail FROM audit ORDER BY id")
out["scripts"] = core.q("SELECT name, content FROM scripts ORDER BY id")
out["dns"] = core.q("SELECT account_id, instance_id, name, zone_id, zone_name, record, v4, v6 FROM dns_bindings")
out["traffic"] = core.q("SELECT account_id, instance_id, name, limit_gb, action, mode, window_hours, direction, enabled, shutdown_hours, state FROM traffic_guards")
out["tokens"] = core.q("SELECT name, token_hash, prefix, scope FROM api_tokens")
out["deleted"] = core.q("SELECT provider, name, est_cost, lifecycle_days, currency, source FROM deleted_accounts")
out["secrets"] = [dict(r, password=core.decrypt(r.pop("password_enc"))) for r in core.q("SELECT account_id, instance_id, name, username, password_enc FROM instance_secrets")]
out["settings"] = {k: core.get_setting(k) for k in ("tg_chat_id", "default_create", "daily_report", "report_time", "monitor_interval")}
out["secret_settings"] = {"tg_token": core.get_secret_setting("tg_token"), "cf_token": core.get_secret_setting("cf_token")}
out["tg_token_encrypted"] = "FAKE-legacy" not in json.dumps(core.get_setting("tg_token"))
out["leftover"] = {t: core.q(f"SELECT COUNT(*) AS n FROM {t}", one=True)["n"] for t in ("sessions", "tasks", "login_fail")}
with mock.patch.object(core, "ensure_password", lambda: None):
    with TestClient(main.app) as cl:
        out["token_get"] = cl.get("/api/accounts", headers={"Authorization": "Bearer " + sys.argv[2]}).status_code
        out["token_post"] = cl.post("/api/accounts/test-all", json={}, headers={"Authorization": "Bearer " + sys.argv[2]}).status_code
print("JSON" + json.dumps(out, ensure_ascii=False, default=str))
'''
vr = subprocess.run([sys.executable, "-c", VERIFY, ROOT, tok_plain], capture_output=True, text=True, env=dict(env, TRICLOUD_DATA=NEW))
try:
    V = json.loads(vr.stdout.split("JSON", 1)[1])
except Exception:
    print(vr.stdout[-2000:], vr.stderr[-3000:])
    V = {}
o = FAKE["oci"]
ok("migrate/accounts: OCI fields via provider factory", V.get("oci", {}).get("cfg") == {
    "user": o["user_ocid"], "tenancy": o["tenancy_ocid"], "fingerprint": o["fingerprint"], "region": o["region"], "key_content": pem.strip() + "\n"}
   and V["oci"]["compartment"] == o["tenancy_ocid"])
ok("migrate/accounts: OCI default_ssh_key / default_subnet_ocid kept, unknown key dropped",
   V.get("oci", {}).get("cred") == {"default_ssh_key": o["default_ssh_key"], "default_subnet_ocid": o["default_subnet_ocid"], "legacy_extra": None})
ok("migrate/accounts: proxy url/user/pass -> proxy/proxy_user/proxy_pass, composed for provider",
   V.get("raw_proxy") == {"proxy": "socks5://proxy.example.test:1080", "proxy_user": "pu", "proxy_pass": "fake-proxy-pass"}
   and V["oci"]["proxy"] == "socks5://pu:fake-proxy-pass@proxy.example.test:1080")
ok("migrate/accounts: AWS fields via provider factory", V.get("aws") == {"access_key": FAKE["aws"]["access_key"],
   "secret_key": FAKE["aws"]["secret_key"], "region": "ap-northeast-1"})
ok("migrate/accounts: Azure fields via provider factory", V.get("azure") == {"sub": FAKE["azure"]["subscription_id"],
   "tenant": FAKE["azure"]["tenant_id"], "client": FAKE["azure"]["client_id"], "secret": FAKE["azure"]["client_secret"]})
accs = {a["id"]: a for a in V.get("accounts", [])}
ok("migrate/accounts: ids, names, dates, credit total kept", set(accs) == {3, 5, 8} and accs[3]["name"] == "东京甲骨文"
   and accs[3]["cloud_created_at"] == "2026-01-01" and accs[5]["cloud_created_at"] == "2026-01-02" and accs[5]["credit_total"] == 300
   and accs[8]["edu_expires_at"] == "2027-01-01" and accs[3]["created"] == int(T0) and accs[5]["region"] == "ap-northeast-1")
ok("migrate/credits", V.get("credits") == [{"account_id": 5, "name": "教程奖励", "amount": 100.0, "start_date": "2026-01-01",
                                            "expire_date": "2026-07-20", "used_manual": None}])
ok("migrate/audit", [a["action"] for a in V.get("audit", [])] == ["login_ok", "account_create"] and V["audit"][0]["actor"] == "legacy"
   and V["audit"][1]["detail"] == "aws / AWS 主号" and V["audit"][0]["ts"] == int(T0) and V["audit"][0]["ip"] == "192.0.2.10")
ok("migrate/scripts", V.get("scripts") == [{"name": "bbr", "content": "#!/bin/bash\necho bbr"}, {"name": "[Windows] rdp", "content": "echo rdp"}])
ok("migrate/dns", V.get("dns") == [{"account_id": 3, "instance_id": "ocid1.instance.oc1..i1", "name": "vps.example.com", "zone_id": "",
                                    "zone_name": "example.com", "record": "vps.example.com", "v4": 1, "v6": 0}])
ok("migrate/traffic", V.get("traffic") == [{"account_id": 3, "instance_id": "ocid1.instance.oc1..i1", "name": "web", "limit_gb": 10.0,
                                            "action": "stop", "mode": "rolling", "window_hours": 24, "direction": "both", "enabled": 1,
                                            "shutdown_hours": 6.0, "state": "ok"}])
ok("migrate/api_tokens: hash kept, scope mapped, token authenticates read-only",
   V.get("tokens") == [{"name": "ci", "token_hash": hashlib.sha256(tok_plain.encode()).hexdigest(), "prefix": "legacy", "scope": "read"}]
   and V.get("token_get") == 200 and V.get("token_post") == 401)
ok("migrate/recycle_bin -> deleted_accounts", V.get("deleted") == [{"provider": "aws", "name": "旧号", "est_cost": 4.2, "lifecycle_days": 33.5,
                                                                    "currency": "USD", "source": "legacy"}])
ok("migrate/password_vault -> instance_secrets (re-encrypted)", V.get("secrets") == [{"account_id": 3, "instance_id": "ocid1.instance.oc1..i1",
                                                                                     "name": "web", "username": "root", "password": "RootPw-Fake-1"}])
ok("migrate/settings: TG + Cloudflare (re-encrypted) + defaults + report", V.get("secret_settings") == {"tg_token": "123456:FAKE-legacy-bot",
   "cf_token": "fake-cf-token"} and V["tg_token_encrypted"] and V["settings"] == {"tg_chat_id": "424242",
   "default_create": {"oci": {"shape": "VM.Standard.E2.1.Micro"}}, "daily_report": True, "report_time": "08:00", "monitor_interval": 10})
ok("migrate: sessions / jobs / login_attempts not migrated", V.get("leftover") == {"sessions": 0, "tasks": 0, "login_fail": 0})
raw_new = open(os.path.join(NEW, "tricloud.db"), "rb").read()
ok("migrate: no plaintext secrets in new db file", not [s for s in (b"fakeSecretKeyLegacy", b"fake~azure~secret", b"fake-proxy-pass",
                                                                   b"123456:FAKE", b"fake-cf-token", b"RootPw-Fake", b"BEGIN PRIVATE") if s in raw_new])

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
