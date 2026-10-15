"""v1.2 自测：免费额度护栏、账号健康度、跨云迁移（切 DNS / 复制监控 / 停源）。快照功能已在 1.5.0 移除，只验证旧任务兼容。"""
import asyncio
import json
import os
import sys
import tempfile
import time

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123",
                  AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from unittest import mock

from fastapi.testclient import TestClient
from moto import mock_aws

from app import cloudinit, core, dns, guard, health, main, services, tasks, telegram
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


def run_task(tid):
    t = core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)
    asyncio.run(tasks._dispatch(t))
    return core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)


with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}), \
         mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: None):
        oid = c.post("/api/accounts", json={"provider": "oci", "name": "oci1", "cred": {
            "user": "u", "tenancy": "t", "fingerprint": "f", "key_content": "k", "region": "ap-tokyo-1",
            "home_region": "ap-tokyo-1"}}).json()["id"]
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        aid = c.post("/api/accounts", json={"provider": "aws", "name": "aws1",
                                            "cred": {"access_key": "AK", "secret_key": "s", "region": "us-east-1"}}).json()["id"]

    # ---------- 免费额度护栏：OCI ----------
    a1 = [{"id": "i1", "shape": "VM.Standard.A1.Flex", "ocpus": 2, "memory_gb": 12, "state": "running"},
          {"id": "i2", "shape": "VM.Standard.E2.1.Micro", "state": "stopped"},
          {"id": "i3", "shape": "VM.Standard.E2.1.Micro", "state": "running"}]
    with mock.patch.object(services, "list_instances", return_value=a1), \
         mock.patch.object(OCIProvider, "storage_usage", return_value={"volume_gb": 150}, create=True), \
         mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: None):
        services.drop_provider_cache(oid)
        # 2026-06 起：免费号 A1 只含 2 OCPU / 12 GB；未识别类型按免费号算
        w = guard.check(oid, "create", {"create": {"shape": "VM.Standard.A1.Flex", "ocpus": 1, "memory_gb": 6, "disk_gb": 50}})
        ok("OCI free/unknown tenancy: 2+1C over 2C/12G warned", any("免费号免费的 2 OCPU / 12 GB" in x for x in w))
        core.ex("UPDATE accounts SET acct_type=? WHERE id=?", ('{"plan_type": "FREE_TIER"}', oid))
        ok("core.oci_a1_free FREE_TIER -> 2/12", core.oci_a1_free(oid) == (2, 12, "free"))
        core.ex("UPDATE accounts SET acct_type=? WHERE id=?", ('{"plan_type": "PAYG"}', oid))   # 下面按付费号 4/24 测
        ok("core.oci_a1_free PAYG -> 4/24", core.oci_a1_free(oid) == (4, 24, "paid"))
        w = guard.check(oid, "create", {"create": {"shape": "VM.Standard.A1.Flex", "ocpus": 2, "memory_gb": 12, "disk_gb": 50}})
        ok("OCI 2+2C/24G within A1, 150+50=200GB ok", w == [])
        w = guard.check(oid, "create", {"create": {"shape": "VM.Standard.A1.Flex", "ocpus": 3, "memory_gb": 18, "disk_gb": 50}})
        ok("OCI A1 over 4C/24G warned", any("A1 合计" in x for x in w))
        w = guard.check(oid, "create", {"create": {"shape": "VM.Standard.E2.1.Micro", "disk_gb": 50}})
        ok("OCI 3rd micro warned (stopped still counts)", any("E2.1.Micro 将有 3 台" in x for x in w))
        w = guard.check(oid, "create", {"create": {"shape": "VM.Standard.E4.Flex", "ocpus": 1, "memory_gb": 6, "disk_gb": 60}})
        ok("OCI paid shape + storage over 200GB warned", any("不是 Always Free" in x for x in w) and any("块存储" in x for x in w))
        w = guard.check(oid, "create", {"region": "us-ashburn-1", "create": {"shape": "VM.Standard.A1.Flex", "ocpus": 1, "memory_gb": 6}})
        ok("OCI non-home region warned", any("主区域" in x for x in w))
        w = guard.check(oid, "resize", {"instance_id": "i1", "ocpus": 4, "memory_gb": 24})
        ok("OCI resize own instance to 4C/24G ok (excludes self)", w == [])
        ok("OCI VPU>10 warned", any("VPU" in x for x in guard.check(oid, "bootvol", {"instance_id": "i1", "vpus_per_gb": 20})))
        # API：409 + 警告，带 confirm_overage 才放行
        with mock.patch.object(OCIProvider, "create_instance", return_value={"id": "new", "name": "n", "state": "PROVISIONING"}, create=True), \
             mock.patch.object(cloudinit, "resolve_script", return_value=None):
            r = c.post(f"/api/accounts/{oid}/oci/create", json={"create": {"shape": "VM.Standard.A1.Flex", "ocpus": 4, "memory_gb": 24}})
            ok("API create over quota -> 409 with guard list", r.status_code == 409 and r.json()["detail"]["guard"])
            r = c.post(f"/api/accounts/{oid}/oci/create", json={"confirm_overage": True,
                                                                "create": {"shape": "VM.Standard.A1.Flex", "ocpus": 4, "memory_gb": 24}})
            ok("API create with confirm_overage passes", r.status_code == 200)
            c.post("/api/settings", json={"free_guard": False})
            r = c.post(f"/api/accounts/{oid}/oci/create", json={"create": {"shape": "VM.Standard.A1.Flex", "ocpus": 4, "memory_gb": 24}})
            ok("guard can be turned off in settings", r.status_code == 200)
            c.post("/api/settings", json={"free_guard": True})
        r = c.post(f"/api/accounts/{oid}/oci/snatch", json={"create": {"shape": "VM.Standard.A1.Flex", "ocpus": 4, "memory_gb": 24}})
        ok("snatch also guarded", r.status_code == 409)
    with mock.patch.object(services, "list_instances", side_effect=RuntimeError("api down")), \
         mock.patch.object(OCIProvider, "storage_usage", side_effect=RuntimeError("x"), create=True), \
         mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: None):
        services.drop_provider_cache(oid)
        ok("guard never blocks when cloud API fails", guard.check(oid, "create", {"create": {"shape": "VM.Standard.A1.Flex"}}) == [])
    services.drop_provider_cache(oid)

    # ---------- 免费额度护栏：AWS（moto） ----------
    with mock_aws():
        import boto3
        ec2 = boto3.client("ec2", "us-east-1")
        ami = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
        services.drop_provider_cache(aid)
        mock.patch.object(AWSProvider, "_ami", lambda self, o, a: ami).start()
        ok("AWS paid type warned", any("不在免费套餐" in x for x in guard.check(aid, "create", {"type": "m5.large"})))
        r = c.post(f"/api/accounts/{aid}/aws/ec2-create", json={"name": "e1", "type": "t3.micro", "disk_gb": 10})
        iid = r.json()["id"]
        w = guard.check(aid, "create", {"type": "t3.micro", "disk_gb": 25})
        ok("AWS second free instance + EBS>30GB warned", any("750 小时" in x for x in w) and any("EBS" in x for x in w))
        # 快照功能已移除：路由不存在，旧的 snapshot 任务只显示名称、执行时安全失败
        ok("snapshot routes removed", c.get(f"/api/accounts/{aid}/snapshots").status_code in (404, 405)
           and c.post(f"/api/accounts/{aid}/snapshots", json={"instance_id": iid}).status_code in (404, 405))
        tid0 = tasks.create_task("snapshot", aid, {"instance_id": iid, "name": "e1"})
        t0 = run_task(tid0)
        tv = c.get(f"/api/tasks/{tid0}")
        ok("legacy snapshot task: no crash, shown as removed", t0["status"] == "failed" and tv.status_code == 200
           and tv.json()["type_name"] == "快照（已移除）")
        core.ex("DELETE FROM tasks WHERE id=?", (tid0,))

        # ---------- 账号健康度 ----------
        c.post("/api/monitors", json={"account_id": aid, "instance_id": iid, "name": "e1", "state": "running"})
        h = c.post("/api/account-health/refresh", json={"account_id": aid}).json()[0]
        ok("health first run healthy", h["score"] == 100 and h["level"] == "good")
        ec2.stop_instances(InstanceIds=[iid])
        core.ex("UPDATE monitors SET last_state='running' WHERE instance_id=?", (iid,))
        tid1 = tasks.create_task("change_ip", aid, {"instance_id": "x"})
        core.ex("UPDATE tasks SET status='failed', message='第 3 次：容量不足' WHERE id=?", (tid1,))
        tid2 = tasks.create_task("resize", aid, {"instance_id": "y"})
        core.ex("UPDATE tasks SET status='failed', message='AuthFailure' WHERE id=?", (tid2,))
        sent.clear()
        h = c.post("/api/account-health/refresh", json={"account_id": aid}).json()[0]
        bad = {i["name"] for i in h["items"] if not i["ok"]}
        ok("passive stop + non-capacity failure penalised, capacity ignored",
           "实例异常停机" in bad and "近 24 小时任务失败" in bad and h["score"] == 85)
        ok("health drop >=15 pushes TG", any("健康度下降" in s for s in sent))
        with mock.patch.object(AWSProvider, "test", side_effect=RuntimeError("AuthFailure: account suspended")):
            h = c.post("/api/account-health/refresh", json={"account_id": aid}).json()[0]
        ok("credential failure -> danger", h["level"] == "bad" and any("封禁" in i["detail"] for i in h["items"] if not i["ok"]))
        lst = c.get("/api/account-health").json()
        ok("health list includes all accounts", {x["account_id"] for x in lst} == {aid, oid} and
           next(x for x in lst if x["account_id"] == oid)["score"] is None)

        # ---------- 跨云迁移：AWS → OCI，切 DNS / 复制监控 / 停源 ----------
        ec2.start_instances(InstanceIds=[iid])
        core.ex("INSERT INTO dns_bindings(account_id,instance_id,name,zone_id,zone_name,record,v4) VALUES(?,?,?,?,?,?,1)",
                (aid, iid, "e1", "z", "example.com", "jp.example.com"))
        calls = []
        with mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: None), \
             mock.patch.object(OCIProvider, "create_instance", return_value={"id": "ocid.new", "name": "e1-oci", "state": "PROVISIONING",
                                                                             "password": "Pw1!xyzXYZ123", "username": "root"}, create=True), \
             mock.patch.object(OCIProvider, "wait_public_ip", return_value="203.0.113.50", create=True), \
             mock.patch.object(guard, "check", return_value=[]), \
             mock.patch.object(dns, "cf_upsert", lambda z, n, t, v, p=False: calls.append((n, t, v)) or f"{n} {t} → {v}"):
            services.drop_provider_cache(oid)
            ok("migrate same account rejected", c.post("/api/migrate", json={"from_account_id": aid, "to_account_id": aid,
                                                                              "instance_id": iid}).status_code == 400)
            r = c.post("/api/migrate", json={"from_account_id": aid, "to_account_id": oid, "instance_id": iid, "name": "e1",
                                             "create": {"name": "e1-oci", "shape": "VM.Standard.A1.Flex", "ocpus": 1, "memory_gb": 6},
                                             "switch_dns": True, "stop_source": True})
            t = run_task(r.json()["task_id"])
        b = core.q("SELECT * FROM dns_bindings WHERE record='jp.example.com'")
        st = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["State"]["Name"]
        ok("migrate done: DNS moved to new instance & synced", t["status"] == "done" and len(b) == 1 and b[0]["account_id"] == oid
           and b[0]["instance_id"] == "ocid.new" and calls == [("jp.example.com", "A", "203.0.113.50")])
        ok("migrate copies monitor, saves password, stops source",
           core.q("SELECT 1 FROM monitors WHERE account_id=? AND instance_id='ocid.new'", (oid,)) and
           core.q("SELECT 1 FROM instance_secrets WHERE instance_id='ocid.new'") and st in ("stopping", "stopped"))
        ok("migrate notifies TG", any("迁移完成" in s for s in sent))

    ok("version 1.2+", c.get("/api/health").json()["version"] >= "1.2.0")

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
