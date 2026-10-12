import os, sys, json, tempfile, asyncio, time, datetime as dt
D = tempfile.mkdtemp(); os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123",
    AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY","HTTP_PROXY","https_proxy","http_proxy"): os.environ.pop(k, None)
sys.path.insert(0, "/workspace/projects/eaddfdd1-95d5-4717-aeac-26c5e0655a1d/tricloud")
from unittest import mock
import boto3
from moto import mock_aws
from app import core, services, tasks, telegram
from app.providers.aws_provider import AWSProvider
R = []
def ok(n, c): R.append(bool(c)); print(("PASS " if c else "FAIL ") + n)
core.init_db(); core.fernet(); core.ensure_password()
sent = []
async def fake_send(text, markup=None, **kw): sent.append((text, markup)); return True
telegram.send = fake_send; tasks.telegram.send = fake_send

def add(prov, cred, region=None):
    return core.ex("INSERT INTO accounts(provider,name,region,cred_enc,created) VALUES(?,?,?,?,?)",
                   (prov, prov + "1", region, core.encrypt(cred), int(time.time())))
oci = add("oci", {"user": "u", "tenancy": "t", "fingerprint": "f", "key_content": "k", "region": "ap-tokyo-1"}, "ap-tokyo-1")
aws = add("aws", {"access_key": "testing", "secret_key": "testing", "region": "us-east-1"}, "us-east-1")

# --- OCI 抢机：容量不足 2 次后成功
class CapErr(Exception):
    status = 500; code = "InternalError"; message = "Out of host capacity."
class FakeOCI:
    n = 0
    def create_instance(self, c):
        FakeOCI.n += 1
        if FakeOCI.n < 3: raise CapErr("Out of host capacity.")
        return {"name": c["name"]}
async def snatch():
    with mock.patch.object(services, "provider", return_value=FakeOCI()):
        tid = tasks.create_task("snatch", oci, {"create": {"name": "arm", "shape": "VM.Standard.A1.Flex", "ocpus": 4, "memory_gb": 24}, "interval": 30})
        for _ in range(3):
            t = core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)
            await tasks._run_snatch(t)
        t = core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)
        ok("FR-01 OCI 抢机: capacity retry -> success on 3rd", t["status"] == "done" and t["attempts"] == 3)
        ok("FR-04 抢机成功 TG 推送", any("抢机成功" in s[0] for s in sent))
        p = json.loads(core.q("SELECT params FROM tasks WHERE id=?", (tid,), one=True)["params"])
asyncio.run(snatch())
ok("OCI capacity error detection", services.OCIProvider.is_capacity_error(CapErr("Out of host capacity.")))

# --- 任务停止推送
async def stopt():
    tid = tasks.create_task("snatch", oci, {"create": {}, "interval": 30})
    tasks.stop_task(tid); await asyncio.sleep(0.05)
    ok("FR-04 停止任务推送", any("已停止" in s[0] for s in sent))
asyncio.run(stopt())

# --- 监控：异常停止 -> 告警 + 自动启动；用户主动停止不告警
async def mon():
    core.ex("INSERT INTO monitors(account_id,instance_id,region,kind,name,auto_start,last_state) VALUES(?,?,?,?,?,?,?)",
            (aws, "i-1", None, "vm", "box", 1, "running"))
    acts = []
    with mock.patch.object(services, "get_state", return_value="stopped"), \
         mock.patch.object(services, "instance_action", side_effect=lambda *a: acts.append(a[2])), \
         mock.patch.object(core, "get_setting", side_effect=lambda k, d=None: 0.0001 if k == "monitor_interval" else d):
        sent.clear()
        try: await asyncio.wait_for(tasks.monitor_loop(), 0.5)
        except asyncio.TimeoutError: pass
    ok("FR-04 实例异常告警 + 自启", acts == ["start"] and any("实例异常" in s[0] and "自动" in s[0] for s in sent))
    core.ex("UPDATE monitors SET last_state='user:stop'"); sent.clear()
    with mock.patch.object(services, "get_state", return_value="stopped"), \
         mock.patch.object(core, "get_setting", side_effect=lambda k, d=None: 0.0001 if k == "monitor_interval" else d):
        try: await asyncio.wait_for(tasks.monitor_loop(), 0.5)
        except asyncio.TimeoutError: pass
    ok("面板主动停止不误报", not any("实例异常" in s[0] for s in sent))
asyncio.run(mon())

# --- 定时 AWS：CE 失败时每天最多 3 次且间隔 >=1h
async def sched():
    calls = {"n": 0}
    def boom(self, credit_since=None): calls["n"] += 1; raise RuntimeError("ce down")
    t15 = dt.datetime(2026, 10, 15, 9, 0, tzinfo=services.tz())
    real_sleep = asyncio.sleep
    async def fast_sleep(s): await real_sleep(0)
    with mock.patch.object(AWSProvider, "cost_explorer", boom), mock.patch.object(services, "now_local", return_value=t15), \
         mock.patch.object(tasks.asyncio, "sleep", fast_sleep):
        try: await asyncio.wait_for(tasks.schedule_loop(), 0.5)
        except asyncio.TimeoutError: pass
    ok(f"FR-03 定时刷新失败不会反复扣费（调用 {calls['n']} 次）", calls["n"] == 1)
asyncio.run(sched())

# --- TG：只响应配置 chat_id；/start -> 云 -> 账号 -> 实例 -> 二次确认 -> 执行（v1.5 按钮菜单）
core.set_setting("tg_chat_id", "42")
async def tg():
    posts = []
    class Bot:
        async def call(self, method, body): posts.append((method, body)); return {"ok": True}
    bot = Bot()
    msg = {"message_id": 1, "chat": {"id": 42}}
    def btn(text_part):
        mk = posts[-1][1]["reply_markup"]["inline_keyboard"]
        return [b for r in mk for b in r if text_part in b["text"]][0]["callback_data"]
    await telegram.handle_message(bot, "42", {"chat": {"id": 42}, "text": "/start"})
    await telegram.handle_callback(bot, "42", {"id": "0", "data": btn("Oracle"), "message": msg})
    await telegram.handle_callback(bot, "42", {"id": "1", "data": posts[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "message": msg})
    with mock.patch.object(services, "list_instances", return_value=[{"id": "i-1", "name": "box", "state": "running", "public_ip": "203.0.113.1"}]):
        await telegram.handle_callback(bot, "42", {"id": "2", "data": btn("实例"), "message": msg})
    await telegram.handle_callback(bot, "42", {"id": "3", "data": btn("box"), "message": msg})
    await telegram.handle_callback(bot, "42", {"id": "4", "data": btn("停止"), "message": msg})
    ok("FR-04 Bot 二次确认", "确认" in posts[-1][1]["text"])
    did = []
    with mock.patch.object(services, "instance_action", side_effect=lambda *a: did.append(a[1:3])):
        await telegram.handle_callback(bot, "42", {"id": "5", "data": btn("确认"), "message": msg})
    ok("FR-04 Bot 账号→实例→操作→确认 执行", did == [("i-1", "stop")])
asyncio.run(tg())
src = open(telegram.__file__).read()
ok("FR-04 chat_id 过滤（message & callback）", src.count("!= chat_id") >= 2)

# --- AWS EC2 换 IP（弹性 IP 重分配）+ 配额
with mock_aws():
    services._cache.clear()
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ami = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    i = ec2.run_instances(ImageId=ami, MinCount=1, MaxCount=1)["Instances"][0]["InstanceId"]
    a = ec2.allocate_address(Domain="vpc"); ec2.associate_address(InstanceId=i, AllocationId=a["AllocationId"])
    r = services.provider(aws).change_ip(i, "auto")
    left = ec2.describe_addresses()["Addresses"]
    ok("FR-01 AWS 弹性 IP 换 IP + 释放旧 EIP", r["new_ip"] != a["PublicIp"] and len(left) == 1 and left[0]["PublicIp"] == r["new_ip"])
ok("FR-05 None 单位过滤", AWSProvider._clean_unit("None") == "" and AWSProvider._clean_unit("Count") == "Count")
print(f"\n{sum(R)}/{len(R)} passed"); sys.exit(0 if all(R) else 1)
