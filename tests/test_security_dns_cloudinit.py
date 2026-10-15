"""v1.1 自测：TOTP、API Token、审计、备份恢复、开机密码、cloud-init、DNS 联动、脚本模板、
代理、OCI 指定网段换 IP、EC2 创建（moto）、区域扫描、IP 不通自动换 IP。"""
import asyncio
import base64
import os
import sys
import tempfile
import time

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123",
                  AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
sys.path.insert(0, "/workspace/projects/eaddfdd1-95d5-4717-aeac-26c5e0655a1d/tricloud")
from unittest import mock

from fastapi.testclient import TestClient
from moto import mock_aws

from app import cloudinit, core, dns, main, net, security, services, tasks, telegram
from app.providers.aws_provider import AWSProvider
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

with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})

    # ---------- TOTP ----------
    r = c.post("/api/2fa/setup").json()
    sec = r["secret"]
    code = security._totp_at(sec, int(time.time() // 30))
    ok("2FA wrong code rejected", c.post("/api/2fa/enable", json={"code": "000000"}).status_code == 400)
    ok("2FA enable with valid code", c.post("/api/2fa/enable", json={"code": code}).status_code == 200)
    c2 = TestClient(main.app)
    r = c2.post("/api/login", json={"password": "devpassword123"})
    ok("2FA login without otp -> asks otp", r.status_code == 401 and r.json()["detail"] == "需要二次验证码")
    ok("2FA replay of same code rejected", c2.post("/api/login", json={"password": "devpassword123", "otp": code}).status_code == 401)
    nxt = security._totp_at(sec, int(time.time() // 30) + 1)
    ok("2FA next-window code accepted", c2.post("/api/login", json={"password": "devpassword123", "otp": nxt}).status_code == 200)
    core.set_secret_setting("totp_secret", "")   # 关闭以便后续测试

    # ---------- API Token ----------
    tok_r = c.post("/api/tokens", json={"name": "bot", "scope": "read"}).json()["token"]
    tok_f = c.post("/api/tokens", json={"name": "bot2", "scope": "full"}).json()["token"]
    raw = core.q("SELECT token_hash FROM api_tokens")
    ok("API token stored hashed only", all(tok_r not in x["token_hash"] for x in raw))
    anon = TestClient(main.app)
    H = lambda t: {"Authorization": f"Bearer {t}"}
    ok("read token GET ok", anon.get("/api/accounts", headers=H(tok_r)).status_code == 200)
    ok("read token POST forbidden", anon.post("/api/monitors", headers=H(tok_r), json={}).status_code == 401)
    ok("full token cannot touch 2FA/backup/secrets", all(anon.post(p, headers=H(tok_f), json={}).status_code == 403
                                                        for p in ("/api/2fa/setup", "/api/backup", "/api/tokens")) and
       anon.get("/api/secrets", headers=H(tok_f)).status_code == 403)
    ok("bogus token 401", anon.get("/api/accounts", headers=H("tc_nope")).status_code == 401)

    # ---------- 账号 + 代理 ----------
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        aid = c.post("/api/accounts", json={"provider": "aws", "name": "aws1",
                                            "cred": {"access_key": "AKIDEMO", "secret_key": "s", "region": "us-east-1"}}).json()["id"]
    ok("proxy bad scheme rejected", c.patch(f"/api/accounts/{aid}", json={"proxy": "ftp://x"}).status_code == 400)
    c.patch(f"/api/accounts/{aid}", json={"proxy": "http://u:secretpw@10.0.0.1:3128"})
    acc = [a for a in c.get("/api/accounts").json() if a["id"] == aid][0]
    ok("proxy saved, password not echoed", acc["proxy"] == "10.0.0.1:3128" and "secretpw" not in str(acc))
    p = services.provider(aid)
    ok("AWS client uses per-account proxy", p.c("ec2")._client_config.proxies == {"http": "http://u:secretpw@10.0.0.1:3128",
                                                                                  "https": "http://u:secretpw@10.0.0.1:3128"})
    c.patch(f"/api/accounts/{aid}", json={"proxy": ""})
    ok("proxy cleared", services.provider(aid).cred.get("proxy") is None)

    # ---------- 审计 ----------
    logs = c.get("/api/audit").json()
    ok("audit records writes with actor", any(l["action"].startswith("PATCH /api/accounts") for l in logs) and
       any(l["actor"] == "session" for l in logs))

    # ---------- cloud-init ----------
    ud = cloudinit.cloud_init("Pw#123abcXYZ", "root", "echo hi")
    ok("cloud-init sets random pw, no curl|bash, runs user script", "root:Pw#123abcXYZ" in ud and "curl" not in ud and
       "tricloud-init.sh" in ud and base64.b64encode(b"echo hi").decode() in ud)
    pws = {cloudinit.gen_password() for _ in range(50)}
    ok("gen_password unique & complex", len(pws) == 50 and all(len(x) == 20 and any(ch.isupper() for ch in x)
                                                              and any(ch.isdigit() for ch in x) for x in pws))

    # ---------- 脚本模板 ----------
    sid = c.post("/api/scripts", json={"name": "bbr", "content": "#!/bin/bash\necho bbr"}).json()["id"]
    ok("script too long rejected", c.post("/api/scripts", json={"name": "x", "content": "a" * 17000}).status_code == 400)
    ok("resolve_script by id", cloudinit.resolve_script({"script_id": sid}) == "#!/bin/bash\necho bbr")

    # ---------- EC2 创建（moto）+ 开机密码 ----------
    with mock_aws():
        import boto3
        ami = boto3.client("ec2", "us-east-1").describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
        services.drop_provider_cache(aid)
        mock.patch.object(AWSProvider, "_ami", lambda self, o, a: ami).start()
        r = c.post(f"/api/accounts/{aid}/aws/ec2-create", json={"name": "e1", "type": "t3.micro", "os": "debian-12",
                                                                "ports": "80,443", "script_id": sid})
        j = r.json()
        ok("EC2 create returns one-time password", r.status_code == 200 and j.get("password") and j["username"] == "root")
        ec2 = boto3.client("ec2", "us-east-1")
        inst = ec2.describe_instances(InstanceIds=[j["id"]])["Reservations"][0]["Instances"][0]
        sg = ec2.describe_security_groups(GroupIds=[inst["SecurityGroups"][0]["GroupId"]])["SecurityGroups"][0]
        ports = sorted(x["FromPort"] for x in sg["IpPermissions"])
        ok("EC2 SG only 22 + requested (no open-all)", ports == [22, 80, 443])
        ok("EC2 IMDSv2 required", inst["MetadataOptions"]["HttpTokens"] == "required")
        udv = ec2.describe_instance_attribute(InstanceId=j["id"], Attribute="userData")["UserData"].get("Value", "")
        ok("EC2 user-data has template script", base64.b64encode(b"#!/bin/bash\necho bbr").decode() in base64.b64decode(udv).decode())
        secs = c.get("/api/secrets").json()
        raw = core.q("SELECT password_enc FROM instance_secrets")[0]["password_enc"]
        ok("instance secret encrypted at rest", j["password"] not in raw and secs[0]["name"] == "e1")
        ok("reveal needs panel password", c.post(f"/api/secrets/{secs[0]['id']}/reveal", json={"password": "x"}).status_code == 400)
        ok("reveal with password", c.post(f"/api/secrets/{secs[0]['id']}/reveal",
                                          json={"password": "devpassword123"}).json()["password"] == j["password"])
        scan = c.get(f"/api/accounts/{aid}/aws/scan").json()
        ok("all-region scan finds instance", any(x["region"] == "us-east-1" and x["ec2"] >= 1 for x in scan["regions"]))

    # ---------- DNS 联动 ----------
    calls = []
    with mock.patch.object(dns, "cf_upsert", lambda z, n, t, v, p=False: calls.append((n, t, v)) or f"{n} {t} → {v}"):
        r = c.post("/api/dns-bindings", json={"account_id": aid, "instance_id": "i-1", "name": "n1", "zone_id": "z",
                                              "zone_name": "example.com", "record": "evil.com"})
        ok("DNS record must belong to zone", r.status_code == 400)
        c.post("/api/dns-bindings", json={"account_id": aid, "instance_id": "i-1", "name": "n1", "zone_id": "z",
                                          "zone_name": "example.com", "record": "n1.example.com", "v6": True})
        out = dns.dns_sync(aid, "i-1", "1.2.3.4", "2001:db8::1")
        ok("dns_sync updates A + AAAA", calls == [("n1.example.com", "A", "1.2.3.4"), ("n1.example.com", "AAAA", "2001:db8::1")] and len(out) == 2)
        ok("dns_sync no binding -> noop", dns.dns_sync(aid, "i-other", "1.1.1.1") == [])

    # ---------- OCI 指定网段换 IP ----------
    seq = iter(["10.1.1.1", "10.2.2.2", "129.146.3.3"])
    fake = OCIProvider.__new__(OCIProvider)
    fake._primary_vnic = lambda i: type("V", (), {"id": "v"})()
    fake.vnet = mock.Mock()
    fake.vnet.list_private_ips.return_value.data = [type("P", (), {"is_primary": True, "id": "p"})()]
    fake._rotate_ip_once = lambda primary: ("9.9.9.9", next(seq))
    r = fake.change_ip("i", ["129.146.0.0/16"], 10, None, 0)
    ok("OCI change_ip loops until target CIDR", r["new_ip"] == "129.146.3.3" and r["tries"] == 3 and r["old_ip"] == "9.9.9.9")
    seq = iter(["10.1.1.1"] * 5)
    r = fake.change_ip("i", ["129.146.0.0/16"], 3, None, 0)
    ok("OCI change_ip stops at max_tries with warning", r["tries"] == 3 and "warning" in r)
    ok("bad CIDR rejected by API", c.post(f"/api/accounts/{aid}/instances/change-ip",
                                          json={"instance_id": "i", "cidrs": "abc"}).status_code == 400)

    # ---------- IP 不通 → 自动换 IP ----------
    c.post("/api/monitors", json={"account_id": aid, "instance_id": "i-9", "name": "m9", "public_ip": "203.0.113.9",
                                  "check_port": 22, "auto_change_ip": True, "state": "running"})
    m = core.q("SELECT * FROM monitors WHERE instance_id='i-9'", one=True)
    with mock.patch.object(net, "tcp_alive", return_value=False):
        for _ in range(4):
            asyncio.run(tasks._reachability(core.q("SELECT * FROM monitors WHERE id=?", (m["id"],), one=True), "running"))
    tk = core.q("SELECT * FROM tasks WHERE type='change_ip' AND params LIKE '%i-9%'")
    ok("unreachable x3 -> exactly one auto change_ip task + alert", len(tk) == 1 and any("IP 不通" in s for s in sent))
    with mock.patch.object(net, "tcp_alive", return_value=True):
        asyncio.run(tasks._reachability(core.q("SELECT * FROM monitors WHERE id=?", (m["id"],), one=True), "running"))
    ok("reachable resets fail count", core.q("SELECT fail_count FROM monitors WHERE id=?", (m["id"],), one=True)["fail_count"] == 0)
    ok("bad monitor port rejected", c.post("/api/monitors", json={"account_id": aid, "instance_id": "x", "check_port": 70000}).status_code == 400)

    # ---------- 备份 / 恢复 ----------
    ok("backup needs panel password", c.post("/api/backup", json={"password": "x", "passphrase": "longpassphrase"}).status_code == 400)
    ok("backup short passphrase rejected", c.post("/api/backup", json={"password": "devpassword123", "passphrase": "short"}).status_code == 400)
    r = c.post("/api/backup", json={"password": "devpassword123", "passphrase": "longpassphrase1"})
    blob = r.content
    ok("backup is encrypted (no plaintext key/db)", r.status_code == 200 and blob.startswith(b"TCBK1") and b"SQLite" not in blob
       and open(core.KEY_PATH, "rb").read().strip() not in blob)
    old_key = open(core.KEY_PATH, "rb").read()
    core.ex("DELETE FROM accounts")
    ok("restore wrong passphrase rejected", c.post("/api/restore", json={"password": "devpassword123", "passphrase": "wrongwrong1",
                                                                          "file_b64": base64.b64encode(blob).decode()}).status_code == 400)
    r = c.post("/api/restore", json={"password": "devpassword123", "passphrase": "longpassphrase1",
                                     "file_b64": base64.b64encode(blob).decode()})
    ok("restore brings accounts back & creds decrypt", r.status_code == 200 and core.get_account(aid, with_cred=True)["cred"]["access_key"] == "AKIDEMO"
       and open(core.KEY_PATH, "rb").read() == old_key)
    ok("restore logs out all sessions", c.get("/api/accounts").status_code == 401)

    # ---------- 版本 ----------
    ok("version 1.2+", c.get("/api/health").json()["version"] >= "1.2.0")

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
