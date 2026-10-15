"""v1.4 自测：任务实时日志与 GET /api/tasks/{id}、批量添加账号、一键测活、云账号创建日期 / 存活天数、
手动 Credit 与已用额度估算（AWS 只读缓存、不调 CE）、Azure 教育优惠估算与到期提醒、流量守护滚动窗口 / 方向 /
关机 M 小时后自动开机（失败只告警不重试）/ 启停、换 IP 排除网段（!CIDR）、自动换 IP 每日限次、Azure 订阅页、
TG /tasks /credits、数据库迁移。全部用 mock / moto 模拟，不连接真实云。"""
import asyncio
import datetime as dt
import json
import os
import sqlite3
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

from app import accounts_import, core, credits, dns, main, net, services, tasks, telegram, traffic_guard
from app.providers.aws_provider import AWSProvider
from app.providers.azure_provider import AzureProvider
from app.providers.oci_provider import OCIProvider

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


async def noop():
    await asyncio.sleep(3600)


REAL_SCHEDULE = tasks.schedule_loop
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


# OCI / Azure 用假凭证：构造函数不连云
mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()
mock.patch.object(AzureProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()

from zoneinfo import ZoneInfo
TODAY = dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()   # 面板默认时区


def d(days):
    return (TODAY + dt.timedelta(days=days)).isoformat()


# ---------------- 0. 迁移：v1.3 旧库升级只加列/表 ----------------
old = os.path.join(D, "old.db")
oc = sqlite3.connect(old)
oc.executescript(core.SCHEMA)
oc.execute("INSERT INTO accounts(provider,name,region,cred_enc,created) VALUES('aws','legacy','us-east-1','x',1)")
oc.commit()
for m in core.MIGRATIONS:
    try:
        oc.execute(m)
    except sqlite3.OperationalError:
        pass
for m in core.MIGRATIONS:          # 再跑一遍：幂等
    try:
        oc.execute(m)
    except sqlite3.OperationalError:
        pass
cols = lambda t: {r[1] for r in oc.execute(f"PRAGMA table_info({t})")}   # noqa: E731
ok("migration: new columns/tables added, old rows kept, idempotent",
   {"cloud_created_at", "credit_total", "edu_expires_at", "last_test_ok"} <= cols("accounts")
   and {"mode", "window_hours", "direction", "enabled", "shutdown_hours", "resume_at", "state"} <= cols("traffic_guards")
   and "result" in cols("tasks") and "used_manual" in cols("aws_credits") and cols("task_logs") and cols("ip_changes")
   and oc.execute("SELECT name FROM accounts").fetchone()[0] == "legacy")
oc.close()

with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    ok("version 1.4.0+", c.get("/api/health").json()["version"] >= "1.4.0")

    # ---------------- 1. 账号：单个添加 + 创建日期 ----------------
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        aid = c.post("/api/accounts", json={"provider": "aws", "name": "aws1", "cloud_created_at": d(-100),
                                            "cred": {"access_key": "AK1", "secret_key": "s", "region": "us-east-1"}}).json()["id"]
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}), \
         mock.patch.object(OCIProvider, "created_at", return_value=d(-400), create=True):
        oid = c.post("/api/accounts", json={"provider": "oci", "name": "oci1", "cred": {
            "user": "u", "tenancy": "t", "fingerprint": "f", "key_content": "k", "region": "ap-tokyo-1"}}).json()["id"]
    with mock.patch.object(AzureProvider, "test", return_value={"ok": True}):
        zid = c.post("/api/accounts", json={"provider": "azure", "name": "az1", "cred": {
            "tenant_id": "t", "client_id": "c", "client_secret": "s", "subscription_id": "sub-1"}}).json()["id"]
    accs = {a["id"]: a for a in c.get("/api/accounts").json()}
    ok("cloud_created_at: manual on add (AWS) + auto-detected for OCI", accs[aid]["cloud_created_at"] == d(-100)
       and accs[oid]["cloud_created_at"] == d(-400))
    ok("PATCH cloud_created_at validates date", c.patch(f"/api/accounts/{zid}", json={"cloud_created_at": "2025/1/1"}).status_code == 400
       and c.patch(f"/api/accounts/{zid}", json={"cloud_created_at": d(-350)}).status_code == 200)
    ok("age_days from cloud_created_at", c.get(f"/api/accounts/{aid}/credit-summary").json()["age_days"] == 100)

    # ---------------- 2. 批量添加 ----------------
    PEM = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----"
    text = f"""{{"provider": "aws", "name": "b-aws-ok", "cred": {{"access_key": "GOOD1", "secret_key": "x", "region": "us-west-2"}}}}
{{"name": "b-aws-bad", "aws_access_key_id": "BAD1", "aws_secret_access_key": "x", "region": "us-east-1"}}
[{{"provider": "azure", "name": "b-az", "appId": "app", "password": "pw", "tenant": "ten", "subscription_id": "s2"}},
 {{"provider": "aws", "name": "b-miss", "access_key": "GOOD2"}}]
{{"provider": "aws", "name": "broken",
[tokyo-oci]
user=ocid1.user.oc1..aaa
fingerprint=aa:bb
tenancy=ocid1.tenancy.oc1..bbb
region=ap-tokyo-1
{PEM}

[seoul-oci]
user=ocid1.user.oc1..ccc
fingerprint=cc:dd
tenancy=ocid1.tenancy.oc1..ddd
region=ap-seoul-1
key_file=~/.oci/key.pem
"""
    parsed = accounts_import.parse(text)
    ok("batch parse: JSON objects + array + aliases + OCI config with inline PEM, order kept",
       [p.get("name") for p in parsed][:4] == ["b-aws-ok", "b-aws-bad", "b-az", "b-miss"]
       and parsed[1]["provider"] == "aws" and parsed[1]["cred"]["access_key"] == "BAD1"
       and parsed[2]["cred"]["client_id"] == "app" and parsed[2]["cred"]["client_secret"] == "pw"
       and any(p.get("name") == "tokyo-oci" and p["cred"]["key_content"].startswith("-----BEGIN") for p in parsed)
       and any(p.get("name") == "seoul-oci" and "key_file" in p.get("error", "") for p in parsed)
       and any("JSON 解析失败" in p.get("error", "") for p in parsed))
    sn = accounts_import.sniff("AZURE_CLIENT_ID=\nAZURE_TENANT_ID=t1")
    ok("sniff: empty env value is skipped, not taken as account name",
       len(sn) == 1 and sn[0]["name"] == "" and sn[0]["cred"] == {"tenant_id": "t1"})

    def aws_test(self):
        if self.cred["access_key"].startswith("BAD"):
            raise RuntimeError("InvalidClientTokenId")
        return {"ok": True}
    with mock.patch.object(AWSProvider, "test", aws_test), \
         mock.patch.object(AzureProvider, "test", return_value={"ok": True}), \
         mock.patch.object(OCIProvider, "test", return_value={"ok": True}), \
         mock.patch.object(OCIProvider, "created_at", return_value=None, create=True):
        dry = c.post("/api/accounts/batch", json={"text": text, "dry_run": True}).json()
        n_before = len(c.get("/api/accounts").json())
        ok("batch dry_run validates without inserting", len(c.get("/api/accounts").json()) == n_before and dry["total"] == len(parsed))
        r = c.post("/api/accounts/batch", json={"text": text}).json()
        by = {x["name"]: x for x in r["results"]}
        ok("batch: per-item results (ok / bad cred / missing field / parse error / key_file)",
           by["b-aws-ok"]["ok"] and by["b-az"]["ok"] and by["tokyo-oci"]["ok"]
           and not by["b-aws-bad"]["ok"] and "InvalidClientTokenId" in by["b-aws-bad"]["error"]
           and not by["b-miss"]["ok"] and "secret_key" in by["b-miss"]["error"]
           and not by["seoul-oci"]["ok"] and r["ok"] == 3 and r["failed"] == r["total"] - 3)
        ok("batch: secrets never echoed in results", "GOOD1" not in json.dumps(r) and "MIIEvQ" not in json.dumps(r))
        r2 = c.post("/api/accounts/batch", json={"text": '{"provider":"aws","name":"b-aws-ok","access_key":"GOOD9","secret_key":"x","region":"us-east-1"}'}).json()
        ok("batch: duplicate name rejected", not r2["results"][0]["ok"] and "同名" in r2["results"][0]["error"])
        ok("batch: empty text -> 400", c.post("/api/accounts/batch", json={"text": "  "}).status_code == 400)
        new_aws = by["b-aws-ok"]["id"]
        cred = core.get_account(new_aws, with_cred=True)["cred"]
        ok("batch: stored encrypted with region", cred["region"] == "us-west-2"
           and "GOOD1" not in core.q("SELECT cred_enc FROM accounts WHERE id=?", (new_aws,), one=True)["cred_enc"])

    # ---------------- 3. 一键测活（并发） ----------------
    def slow_aws(self):
        time.sleep(0.6)
        if self.cred["access_key"].startswith("BAD") or self.cred["access_key"] == "GOOD1":
            raise RuntimeError("AuthFailure")
        return {"ok": True, "account": "123"}

    def slow_ok(self):
        time.sleep(0.6)
        return {"ok": True}
    with mock.patch.object(AWSProvider, "test", slow_aws), mock.patch.object(OCIProvider, "test", slow_ok), \
         mock.patch.object(AzureProvider, "test", slow_ok), mock.patch.object(OCIProvider, "created_at", return_value=None, create=True):
        t0 = time.time()
        r = c.post("/api/accounts/test-all", json={}).json()
        el = time.time() - t0
        ok(f"test-all: concurrent ({r['total']} accounts in {el:.1f}s), each has ok + ms",
           r["total"] >= 6 and el < 0.6 * r["total"] * 0.6 and all("ms" in x and x["ms"] >= 500 for x in r["results"]))
        ok("test-all: failure reported with error", any(not x["ok"] and "AuthFailure" in x["error"] for x in r["results"]))
        ra = c.post("/api/accounts/test-all", json={"provider": "aws"}).json()
        ok("test-all: provider filter", ra["total"] == 2 and all(x["provider"] == "aws" for x in ra["results"]))
        one = c.post(f"/api/accounts/{aid}/test").json()
        accs = {a["id"]: a for a in c.get("/api/accounts").json()}
        ok("single test + last_test_* stored on account", one["ok"] and accs[aid]["last_test_ok"] == 1 and accs[aid]["last_test_ms"] >= 500
           and accs[new_aws]["last_test_ok"] == 0 and "AuthFailure" in accs[new_aws]["last_test_error"])
    ok("test-all: invalid provider 400", c.post("/api/accounts/test-all", json={"provider": "gcp"}).status_code == 400)

    # ---------------- 4. 任务日志 + GET /api/tasks/{id} ----------------
    with mock.patch.object(OCIProvider, "change_ip", lambda self, iid, cidrs=None, max_tries=20, progress=None, interval=8:
                           (progress and progress("第 1 次：10.9.9.9 不满足网段要求，继续…")) or
                           {"old_ip": "10.0.0.1", "new_ip": "129.146.20.7", "tries": 2}), \
         mock.patch.object(dns, "dns_sync", return_value=["A n1.example.com → 129.146.20.7"]):
        r = c.post(f"/api/accounts/{oid}/instances/change-ip", json={"instance_id": "ocid1.instance.x", "name": "arm",
                                                                       "cidrs": "129.146.0.0/16, !129.146.10.0/24"})
        tid = r.json()["task_id"]
        t = c.get(f"/api/tasks/{tid}").json()
        ok("task detail: running, creation logged, params sanitized", t["status"] == "running" and t["type_name"] == "换 IP"
           and "任务已创建" in t["logs"][0]["msg"] and t["params"]["cidrs"] == ["129.146.0.0/16", "!129.146.10.0/24"])
        first_last = t["last_log_id"]
        run_task(tid)
        t = c.get(f"/api/tasks/{tid}").json()
        msgs = [x["msg"] for x in t["logs"]]
        ok("change_ip task writes step logs + result", t["status"] == "done" and t["result"]["new_ip"] == "129.146.20.7"
           and any("开始执行" in m for m in msgs) and any("排除 129.146.10.0/24" in m for m in msgs)
           and any("不满足网段" in m for m in msgs) and any("A n1.example.com" in m for m in msgs) and t["logs"][-1]["level"] == "ok")
        inc = c.get(f"/api/tasks/{tid}?after={first_last}").json()
        ok("incremental logs via ?after=", inc["logs"] and inc["logs"][0]["id"] > first_last and len(inc["logs"]) == len(t["logs"]) - 1)
    ok("task detail 404", c.get("/api/tasks/99999").status_code == 404)

    # 改配置 / 迁移 等任务按步骤写日志
    with mock.patch.object(OCIProvider, "resize", lambda self, *a, **k: {"ok": True}), \
         mock.patch("app.guard.check", return_value=[]):
        tid2 = c.post(f"/api/accounts/{oid}/instances/resize", json={"instance_id": "ocid1.instance.x", "ocpus": 2, "memory_gb": 12}).json()["task_id"]
        run_task(tid2)
    msgs = [x["msg"] for x in c.get(f"/api/tasks/{tid2}").json()["logs"]]
    ok("resize task: step logs", any("提交改配置" in m and "2 OCPU" in m for m in msgs) and msgs[-1] == "改配置完成")

    # 抢机：每次尝试一行日志；停止后记录；删除连同日志
    with mock.patch.object(OCIProvider, "create_instance", side_effect=RuntimeError("Out of host capacity")), \
         mock.patch("app.guard.check", return_value=[]):
        sid = c.post(f"/api/accounts/{oid}/oci/snatch", json={"create": {"shape": "VM.Standard.A1.Flex", "ocpus": 4, "memory_gb": 24},
                                                             "interval": 30}).json()["task_id"]
        run_task(sid)
        run_task(sid)
    lg = c.get(f"/api/tasks/{sid}").json()["logs"]
    ok("snatch: one log line per attempt", sum("容量不足" in x["msg"] for x in lg) == 2)
    c.post(f"/api/tasks/{sid}/stop")
    t = c.get(f"/api/tasks/{sid}").json()
    ok("stop: status stopped + warn log", t["status"] == "stopped" and t["logs"][-1]["msg"] == "已手动停止" and t["logs"][-1]["level"] == "warn")
    c.delete(f"/api/tasks/{sid}")
    ok("delete task removes its logs", c.get(f"/api/tasks/{sid}").status_code == 404
       and not core.q("SELECT 1 FROM task_logs WHERE task_id=?", (sid,)))
    big = tasks.create_task("snatch", oid, {"create": {}})
    for i in range(tasks.LOG_KEEP + 80):
        tasks.log(big, f"line {i}")
    n = core.q("SELECT COUNT(*) AS n FROM task_logs WHERE task_id=?", (big,), one=True)["n"]
    ok("log trimmed to last LOG_KEEP lines", n <= tasks.LOG_KEEP + 50 and tasks.get_logs(big)[-1]["msg"] == f"line {tasks.LOG_KEEP + 79}")
    tasks.stop_task(big)

    # 长任务停止：两次尝试之间的安全点退出，不再继续
    calls = []

    def aws_change(self, iid, mode="auto", progress=None):
        calls.append(1)
        if len(calls) == 1:
            core.ex("UPDATE tasks SET status='stopped' WHERE id=?", (tid3,))
        return {"old_ip": "1.1.1.1", "new_ip": "10.0.0.%d" % len(calls)}
    with mock.patch.object(AWSProvider, "change_ip", aws_change):
        tid3 = c.post(f"/api/accounts/{aid}/instances/change-ip", json={"instance_id": "i-1", "cidrs": "!10.0.0.0/8", "mode": "eip"}).json()["task_id"]
        run_task(tid3)
    t = c.get(f"/api/tasks/{tid3}").json()
    ok("stopped long task exits at safe checkpoint", len(calls) == 1 and t["status"] == "stopped" and "后续步骤未执行" in t["logs"][-1]["msg"])

    # ---------------- 5. 换 IP 排除网段 ----------------
    ok("ip_matches: include + exclude mixed", net.ip_matches("129.146.20.7", ["129.146.0.0/16", "!129.146.10.0/24"])
       and not net.ip_matches("129.146.10.9", ["129.146.0.0/16", "!129.146.10.0/24"])
       and not net.ip_matches("10.1.1.1", ["129.146.0.0/16"]))
    ok("ip_matches: exclude-only accepts anything outside", net.ip_matches("8.8.8.8", ["!10.0.0.0/8"])
       and not net.ip_matches("10.2.3.4", "!10.0.0.0/8"))
    ok("bad excluded CIDR -> 400", c.post(f"/api/accounts/{oid}/instances/change-ip", json={"instance_id": "x", "cidrs": "!999.1.1.0/24"}).status_code == 400
       and c.post(f"/api/accounts/{oid}/instances/change-ip", json={"instance_id": "x", "cidrs": "!"}).status_code == 400)
    seq = iter(["129.146.10.5", "130.0.0.1", "129.146.20.7"])
    with mock.patch.object(OCIProvider, "_primary_vnic", lambda self, i: type("V", (), {"id": "vnic"})()), \
         mock.patch.object(OCIProvider, "_rotate_ip_once", lambda self, p: ("1.1.1.1", next(seq))), \
         mock.patch("app.providers.oci_provider.time.sleep", lambda s: None):
        p = OCIProvider({}, None)
        p.vnet = mock.Mock()
        p.vnet.list_private_ips.return_value.data = [type("P", (), {"is_primary": True, "id": "pip"})()]
        r = OCIProvider.change_ip(p, "i", ["129.146.0.0/16", "!129.146.10.0/24"], 10)
    ok("OCI change_ip skips excluded + out-of-range IPs", r["new_ip"] == "129.146.20.7" and r["tries"] == 3)
    seq2 = iter(["10.0.0.5", "10.0.0.6", "54.1.2.3"])
    with mock.patch.object(AzureProvider, "change_ip", lambda self, iid, progress=None: {"old_ip": "1.1.1.1", "new_ip": next(seq2)}), \
         mock.patch.object(dns, "dns_sync", return_value=[]):
        tz = c.post(f"/api/accounts/{zid}/instances/change-ip", json={"instance_id": "/sub/vm", "cidrs": "!10.0.0.0/8"}).json()["task_id"]
        run_task(tz)
    t = c.get(f"/api/tasks/{tz}").json()
    ok("Azure change_ip honours ! exclusion by retrying (max 5 default)", t["status"] == "done" and t["result"]["new_ip"] == "54.1.2.3"
       and t["result"]["tries"] == 3 and t["params"]["max_tries"] == 5)

    # ---------------- 6. 自动换 IP 每日限次 ----------------
    s = c.get("/api/settings").json()
    ok("auto_ip_daily_limit default 3", s["auto_ip_daily_limit"] == 3)
    ok("auto_ip_daily_limit validated", c.post("/api/settings", json={"auto_ip_daily_limit": 99}).status_code == 400)
    c.post("/api/monitors", json={"account_id": aid, "instance_id": "i-mon", "name": "mon1", "check_port": 22, "auto_change_ip": True,
                                  "public_ip": "198.51.100.7", "state": "running"})
    m = core.q("SELECT * FROM monitors WHERE instance_id='i-mon'", one=True)
    created = []
    sent.clear()
    with mock.patch.object(net, "tcp_alive", return_value=False):
        for i in range(4):
            core.ex("UPDATE tasks SET status='failed' WHERE type='change_ip' AND status='running'")
            core.ex("UPDATE monitors SET fail_count=? WHERE id=?", (tasks.PING_FAIL_THRESHOLD - 1, m["id"]))
            asyncio.run(tasks._reachability(core.q("SELECT * FROM monitors WHERE id=?", (m["id"],), one=True), "running"))
            created.append(len(core.q("SELECT id FROM tasks WHERE type='change_ip' AND params LIKE '%i-mon%'")))
    u = c.get(f"/api/accounts/{aid}/ip-change-usage").json()
    ok("auto change IP capped at 3/day/account", created == [1, 2, 3, 3] and u["auto_used"] == 3 and u["auto_left"] == 0 and u["limit"] == 3)
    ok("limit reached -> TG says so, no task", "已达上限" in sent[-1] and "第 3/3 次" in sent[-2])
    ok("manual change counted separately", u["manual_used"] >= 1)
    c.post("/api/settings", json={"auto_ip_daily_limit": 5})
    ok("limit configurable", c.get(f"/api/accounts/{aid}/ip-change-usage").json()["auto_left"] == 2
       and any(x["account_id"] == aid for x in c.get("/api/ip-change-usage").json()))
    # 自动换 IP 失败：只推送 TG，不重试
    auto_tid = core.q("SELECT id FROM tasks WHERE type='change_ip' AND params LIKE '%i-mon%' ORDER BY id DESC LIMIT 1", one=True)["id"]
    core.ex("UPDATE tasks SET status='running' WHERE id=?", (auto_tid,))
    sent.clear()
    with mock.patch.object(AWSProvider, "change_ip", side_effect=RuntimeError("AddressLimitExceeded")):
        run_task(auto_tid)
    ok("auto change IP failure -> TG alert only, task failed, no retry task",
       core.q("SELECT status FROM tasks WHERE id=?", (auto_tid,), one=True)["status"] == "failed"
       and any("不会自动重试" in x for x in sent)
       and not core.q("SELECT id FROM tasks WHERE type='change_ip' AND status='running' AND params LIKE '%i-mon%'"))

    # ---------------- 7. Credit 估算 ----------------
    # OCI：账单（免费接口）按月记录 → FIFO 分摊
    with mock.patch.object(OCIProvider, "billing", return_value={"period": "x", "currency": "USD", "total": 42.5, "services": []}):
        c.get(f"/api/accounts/{oid}/billing")
    core.ex("INSERT OR REPLACE INTO billing_months(account_id, month, total, currency, updated) VALUES(?,?,?,?,?)",
            (oid, "2000-01", 999, "USD", 1))   # 早于 Credit 起始月，不计入
    first_month = TODAY.replace(day=1)
    prev_month = (first_month - dt.timedelta(days=1)).strftime("%Y-%m")
    core.ex("INSERT OR REPLACE INTO billing_months(account_id, month, total, currency, updated) VALUES(?,?,?,?,?)", (oid, prev_month, 100, "USD", 1))
    start = (first_month - dt.timedelta(days=1)).replace(day=1).isoformat()
    c1 = c.post(f"/api/accounts/{oid}/credits-manual", json={"name": "Trial", "amount": 300, "start_date": start, "expire_date": d(20)}).json()["id"]
    c2 = c.post(f"/api/accounts/{oid}/credits-manual", json={"name": "Later", "amount": 100, "start_date": start, "expire_date": d(200)}).json()["id"]
    sm = c.get(f"/api/accounts/{oid}/credit-summary").json()
    it = {x["name"]: x for x in sm["items"]}
    ok("OCI credit used estimated from monthly bills since start (FIFO by expiry)",
       sm["billing_used"] == 142.5 and it["Trial"]["used"] == 142.5 and it["Later"]["used"] == 0
       and it["Trial"]["used_source"] == "billing" and sm["remaining"] == 257.5 and sm["credit_total"] == 400)
    c.put(f"/api/accounts/{oid}/credits-manual/{c2}", json={"used_manual": 10})
    sm = c.get(f"/api/accounts/{oid}/credit-summary").json()
    it = {x["name"]: x for x in sm["items"]}
    ok("manual used overrides; rest re-allocated", it["Later"]["used"] == 10 and it["Later"]["used_source"] == "manual"
       and it["Trial"]["used"] == 132.5 and sm["used"] == 142.5)
    c.put(f"/api/accounts/{oid}/credit-total", json={"credit_total": 500})
    sm = c.get(f"/api/accounts/{oid}/credit-summary").json()
    ok("credit total override", sm["credit_total"] == 500 and sm["credit_total_manual"] and sm["remaining"] == 357.5)
    c.put(f"/api/accounts/{oid}/credit-total", json={"credit_total": ""})
    ok("credit total cleared -> sum of items", c.get(f"/api/accounts/{oid}/credit-summary").json()["credit_total"] == 400)
    ok("credit validation", c.post(f"/api/accounts/{oid}/credits-manual", json={"name": "x"}).status_code == 400
       and c.post(f"/api/accounts/{oid}/credits-manual", json={"amount": 5, "expire_date": "nope"}).status_code == 400)
    c.put(f"/api/accounts/{oid}/credits-manual/{c1}", json={"name": "Trial 300", "amount": 300})
    ok("credit edit", any(x["name"] == "Trial 300" for x in c.get(f"/api/accounts/{oid}/credits-manual").json()))
    # Azure：没有账单记录 → 估不出，允许手填
    cz = c.post(f"/api/accounts/{zid}/credits-manual", json={"name": "Students", "amount": 100, "expire_date": d(5)}).json()["id"]
    sm = c.get(f"/api/accounts/{zid}/credit-summary").json()
    ok("no billing data -> used unknown (None) with note", sm["items"][0]["used"] is None and sm["used"] is None and "账单" in sm["estimate_note"])
    c.put(f"/api/accounts/{zid}/credits-manual/{cz}", json={"used_manual": 30})
    sm = c.get(f"/api/accounts/{zid}/credit-summary").json()
    ok("manual used when estimate unavailable", sm["used"] == 30 and sm["remaining"] == 70 and sm["used_source"] == "manual")
    # AWS：只读 aws_billing 缓存，绝不调用 CE
    ce = {"n": 0}

    def fake_ce(self, credit_since=None):
        ce["n"] += 1
        return {"period": "x", "currency": "USD", "total": 1, "services": [], "credits_used": 25.0, "ce_calls": 2}
    with mock.patch.object(AWSProvider, "cost_explorer", fake_ce):
        c.post(f"/api/accounts/{aid}/credits-manual", json={"name": "Promo", "amount": 100, "start_date": d(-60), "expire_date": d(3)})
        sm = c.get(f"/api/accounts/{aid}/credit-summary").json()
        ok("AWS credit: no cache -> estimate unavailable, 0 CE calls", sm["used"] is None and ce["n"] == 0)
        services.aws_billing(aid, force=True)     # 用户确认付费的手动刷新（唯一的 CE 调用点）
        n_after_force = ce["n"]
        sm = c.get(f"/api/accounts/{aid}/credit-summary").json()
        c.get("/api/expiry-alerts")
        telegram.credits_report()
        ok("AWS credit used = CE cumulative from aws_billing cache; summary/alerts/TG make 0 CE calls",
           sm["used"] == 25.0 and sm["remaining"] == 75.0 and ce["n"] == n_after_force == 1)
    ok("legacy AWS credits endpoint still AWS-only", c.get(f"/api/accounts/{oid}/credits").status_code == 400)

    # ---------------- 8. Azure 教育优惠 ----------------
    c.patch(f"/api/accounts/{zid}", json={"cloud_created_at": (TODAY - dt.timedelta(days=350)).isoformat()})
    sm = c.get(f"/api/accounts/{zid}/credit-summary").json()
    exp = credits.add_months(TODAY - dt.timedelta(days=350), 12)
    ok("edu expiry estimated = created + 12 months, marked estimated", sm["edu"]["expires_at"] == exp.isoformat()
       and sm["edu"]["estimated"] and "估算" in sm["edu"]["basis"])
    ok("add_months handles month ends", credits.add_months(dt.date(2024, 1, 31), 1) == dt.date(2024, 2, 29)
       and credits.add_months(dt.date(2024, 2, 29), 12) == dt.date(2025, 2, 28))
    c.put(f"/api/accounts/{zid}/edu-expires-at", json={"edu_expires_at": d(25)})
    sm = c.get(f"/api/accounts/{zid}/credit-summary").json()
    ok("edu expiry manual -> not estimated", sm["edu"]["expires_at"] == d(25) and not sm["edu"]["estimated"] and sm["edu"]["days_left"] == 25)
    ok("edu endpoint azure-only", c.put(f"/api/accounts/{aid}/edu-expires-at", json={"edu_expires_at": d(1)}).status_code == 400)
    al = c.get("/api/expiry-alerts").json()
    kinds = {(a["account_id"], a["kind"]) for a in al}
    ok("expiry alerts within 30 days (credits + edu), sorted", (zid, "edu") in kinds and (zid, "credit") in kinds and (aid, "credit") in kinds
       and (oid, "credit") in kinds and [a["days_left"] for a in al] == sorted(a["days_left"] for a in al)
       and not any(a["name"] == "Later" for a in al))
    first = credits.pending_notifications()
    again = credits.pending_notifications()
    ok("expiry TG: each item once per threshold (30/7/1)", len(first) == len(al) and again == [])
    core.ex("UPDATE aws_credits SET expire_date=? WHERE id=?", (d(6), c1))
    core.set_setting("expiry_notified", {k: v for k, v in (core.get_setting("expiry_notified") or {}).items()})
    ok("expiry date moved into new window -> notified again", any(a["name"] == "Trial 300" for a in credits.pending_notifications()))

    # ---------------- 9. Azure 订阅页 ----------------
    with mock.patch.object(AzureProvider, "subscription_info", create=True, return_value={
            "subscription_id": "sub-1", "display_name": "Azure for Students", "state": "Enabled", "quota_id": "AzureForStudents_2018-01-01",
            "offer": "Azure for Students（学生）", "spending_limit": "On"}):
        sub = c.get(f"/api/accounts/{zid}/azure/subscription").json()
    ok("azure subscription: state / offer / spending limit + edu", sub["state"] == "Enabled" and sub["spending_limit"] == "On"
       and "Students" in sub["offer"] and sub["edu"]["expires_at"] == d(25))
    with mock.patch.object(AzureProvider, "subscription_info", create=True, side_effect=RuntimeError("AuthorizationFailed")):
        sub = c.get(f"/api/accounts/{zid}/azure/subscription").json()
    ok("azure subscription error reported, edu still shown", "AuthorizationFailed" in sub["error"] and sub["edu"])
    ok("subscription endpoint azure-only", c.get(f"/api/accounts/{aid}/azure/subscription").status_code == 400)
    fake_sub = type("S", (), {"display_name": "Stu", "state": type("E", (), {"value": "Enabled"})(), "authorization_source": "RoleBased",
                              "tenant_id": "t", "subscription_policies": type("P", (), {"quota_id": "AzureForStudents_2018-01-01",
                                                                                        "spending_limit": "On", "location_placement_id": "Public_2014-09-01"})()})()
    with mock.patch("azure.mgmt.resource.SubscriptionClient") as SC:
        SC.return_value.subscriptions.get.return_value = fake_sub
        p = AzureProvider({}, None)
        p.credential, p.kw, p.sub = None, {}, "sub-1"
        info = AzureProvider.subscription_info(p)
    ok("subscription_info maps quotaId -> offer", info["offer"].startswith("Azure for Students") and info["state"] == "Enabled"
       and info["spending_limit"] == "On")

    # ---------------- 10. 流量守护：滚动窗口 / 方向 / 关机 M 小时 / 启停 ----------------
    seen_kw = []
    use = {"out_gb": 3.0, "in_gb": 7.0}

    def aws_traffic(self, iid, kind="vm", start=None, end=None):
        seen_kw.append((start, end))
        return dict(use)
    stops, starts = [], []

    def fake_action(acc_id, iid, action, region=None, kind="vm", *a):
        (stops if action == "stop" else starts).append(iid)
        return {"ok": True}
    with mock.patch.object(AWSProvider, "traffic", aws_traffic), mock.patch.object(services, "instance_action", fake_action):
        r = c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-roll", "name": "roll", "mode": "rolling",
                                                "window_hours": 6, "direction": "in", "limit_gb": 10, "action": "stop", "shutdown_hours": 2})
        g = [x for x in c.get("/api/traffic-guards").json() if x["instance_id"] == "i-roll"][0]
        st, en = seen_kw[-1]
        ok("rolling: window start/end passed (6h), direction=in counted, save does not stop",
           st is not None and abs((en - st).total_seconds() - 6 * 3600) < 5 and r.json()["last_gb"] == 7.0 and not stops
           and g["mode"] == "rolling" and g["scope"] == "最近 6 小时入站" and g["status"] == "ok")
        ok("validation: window/shutdown/direction/mode", c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-roll", "window_hours": 0, "mode": "rolling"}).status_code == 400
           and c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-roll", "direction": "up"}).status_code == 400
           and c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-roll", "mode": "weekly"}).status_code == 400
           and c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-roll", "action": "stop", "shutdown_hours": 9999}).status_code == 400)
        use["in_gb"] = 10.5
        sent.clear()
        g = c.post(f"/api/traffic-guards/{g['id']}/check").json()
        ok("rolling over limit -> stop + TG with resume time", stops == ["i-roll"] and g["status"] == "tripped" and g["resume_at"]
           and 7100 < g["resume_at"] - time.time() <= 7200 and any("2 小时后" in x and "自动开机" in x for x in sent))
        ok("tripped rule waiting for resume is not re-checked", all(x["id"] != g["id"] for x in traffic_guard.due()))
        core.ex("UPDATE traffic_guards SET resume_at=? WHERE id=?", (int(time.time()) - 1, g["id"]))
        due_r = traffic_guard.resume_due()
        txt = traffic_guard.resume(due_r[0])
        g2 = [x for x in c.get("/api/traffic-guards").json() if x["id"] == g["id"]][0]
        ok("auto start after M hours: start sent, status back to ok, TG text", starts == ["i-roll"] and "已自动开机" in txt
           and g2["status"] in ("ok", "over") and g2["state"] == "ok" and not g2["resume_at"] and traffic_guard.resume_due() == [])
        # 再次超限 → 自动开机失败 → 只告警一次，不重试
        use["in_gb"] = 1
        c.post(f"/api/traffic-guards/{g['id']}/check")
        use["in_gb"] = 20
        c.post(f"/api/traffic-guards/{g['id']}/check")
        core.ex("UPDATE traffic_guards SET resume_at=? WHERE id=?", (int(time.time()) - 1, g["id"]))
    with mock.patch.object(services, "instance_action", side_effect=RuntimeError("IncorrectInstanceState")):
        txt = traffic_guard.resume(traffic_guard.resume_due()[0])
    g3 = [x for x in c.get("/api/traffic-guards").json() if x["id"] == g["id"]][0]
    ok("auto start failure -> alert text, status resume_failed, never retried", "自动开机失败" in txt and "不会自动重试" in txt
       and g3["status"] == "resume_failed" and traffic_guard.resume_due() == [] and len(stops) == 2)

    # schedule_loop 中的自动开机路径（一次循环）
    with mock.patch.object(AWSProvider, "traffic", aws_traffic), mock.patch.object(services, "instance_action", fake_action):
        c.patch(f"/api/traffic-guards/{g['id']}", json={"reset_state": True})
        use["in_gb"] = 1
        c.post(f"/api/traffic-guards/{g['id']}/check")
        use["in_gb"] = 30
        c.post(f"/api/traffic-guards/{g['id']}/check")
        core.ex("UPDATE traffic_guards SET resume_at=? WHERE id=?", (int(time.time()) - 1, g["id"]))
        sent.clear()
        n_starts = len(starts)

        async def one_loop():
            async def stop_sleep(_):
                raise asyncio.CancelledError()
            with mock.patch.object(tasks.asyncio, "sleep", stop_sleep):
                try:
                    await REAL_SCHEDULE()
                except asyncio.CancelledError:
                    pass
        asyncio.run(one_loop())
    ok("schedule_loop runs auto-start + pushes TG", len(starts) == n_starts + 1 and any("已自动开机" in x for x in sent))

    # 启用 / 停用 / 取消自动开机
    gid = g["id"]
    c.patch(f"/api/traffic-guards/{gid}", json={"enabled": False})
    core.ex("UPDATE traffic_guards SET checked_at=0, state='ok' WHERE id=?", (gid,))
    gv = [x for x in c.get("/api/traffic-guards").json() if x["id"] == gid][0]
    ok("disabled rule skipped by scheduler, status 'disabled'", gv["enabled"] == 0 and gv["status"] == "disabled"
       and all(x["id"] != gid for x in traffic_guard.due()))
    c.patch(f"/api/traffic-guards/{gid}", json={"enabled": True})
    ok("re-enabled rule due again", any(x["id"] == gid for x in traffic_guard.due()))
    core.ex("UPDATE traffic_guards SET state='tripped', resume_at=? WHERE id=?", (int(time.time()) + 3600, gid))
    gv = c.patch(f"/api/traffic-guards/{gid}", json={"cancel_resume": True}).json()
    ok("cancel pending auto start", gv["resume_at"] is None and gv["status"] == "tripped" and "取消" in gv["state_msg"])

    # 三家云：OCI / Azure 也走滚动窗口（provider.traffic 收到 start/end）
    got = {}

    def oci_tr(self, iid, start=None, end=None):
        got["oci"] = start
        return {"out_gb": 50, "in_gb": 1}

    def az_tr(self, iid, kind="vm", start=None, end=None):
        got["az"] = start
        return {"out_gb": 2, "in_gb": 2}
    with mock.patch.object(OCIProvider, "traffic", oci_tr), mock.patch.object(AzureProvider, "traffic", az_tr):
        r1 = c.post("/api/traffic-guards", json={"account_id": oid, "instance_id": "ocid1.i", "mode": "rolling", "window_hours": 12, "limit_gb": 100}).json()
        r2 = c.post("/api/traffic-guards", json={"account_id": zid, "instance_id": "/sub/vm", "mode": "rolling", "window_hours": 1,
                                                 "direction": "both", "limit_gb": 10}).json()
    ok("rolling window supported on OCI + Azure", got.get("oci") is not None and got.get("az") is not None
       and r1["last_gb"] == 50 and r2["last_gb"] == 4)
    # v1.3 兼容：不传新字段 = 月度 + count_in 映射为双向
    with mock.patch.object(traffic_guard, "usage", lambda g: {"out_gb": 30, "in_gb": 20}):
        r = c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-legacy", "limit_gb": 100, "count_in": True}).json()
    gl = [x for x in c.get("/api/traffic-guards").json() if x["instance_id"] == "i-legacy"][0]
    ok("legacy body -> monthly, count_in == both", r["last_gb"] == 50 and gl["mode"] == "monthly" and gl["direction"] == "both"
       and gl["count_in"] == 1 and gl["shutdown_hours"] == 0)

    # moto：CloudWatch 滚动窗口只统计最近 N 小时
    with mock_aws():
        import boto3
        cw = boto3.client("cloudwatch", "us-east-1")
        now = dt.datetime.now(dt.timezone.utc)
        for mins, gb in ((30, 2), (60 * 30, 5)):
            cw.put_metric_data(Namespace="AWS/EC2", MetricData=[{"MetricName": "NetworkOut", "Value": gb * 1024 ** 3, "Unit": "Bytes",
                                                                 "Timestamp": now - dt.timedelta(minutes=mins),
                                                                 "Dimensions": [{"Name": "InstanceId", "Value": "i-cw"}]}])
        p = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
        w = p.traffic("i-cw", start=now - dt.timedelta(hours=6), end=now)
        w48 = p.traffic("i-cw", start=now - dt.timedelta(hours=48), end=now)
    ok("AWS CloudWatch rolling window (moto): 6h counts only recent point", abs(w["out_gb"] - 2) < 0.01 and abs(w48["out_gb"] - 7) < 0.01)

    # ---------------- 11. TG /tasks /credits ----------------
    tr = telegram.tasks_report()
    ok("TG /tasks lists recent tasks with status", "最近" in tr and f"#{tid}" in tr and "✅" in tr)
    cr = telegram.credits_report()
    ok("TG /credits shows remaining, edu and expiring items", "Credit 与到期" in cr and "教育优惠" in cr and "30 天内到期" in cr and "余 $" in cr)

    # ---------------- 12. 删除账号清理新表 ----------------
    c.delete(f"/api/accounts/{oid}")
    ok("account delete cleans credits / billing_months / ip_changes",
       not core.q("SELECT 1 FROM aws_credits WHERE account_id=?", (oid,)) and not core.q("SELECT 1 FROM billing_months WHERE account_id=?", (oid,)))

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
