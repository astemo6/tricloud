import os, sys, json, tempfile, datetime as dt, stat, asyncio
D = tempfile.mkdtemp(); os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123",
    AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY","HTTP_PROXY","https_proxy","http_proxy"): os.environ.pop(k, None)
sys.path.insert(0, "/workspace/projects/eaddfdd1-95d5-4717-aeac-26c5e0655a1d/tricloud")
from unittest import mock
import boto3
from moto import mock_aws
from fastapi.testclient import TestClient
from app import main, core, services, tasks, telegram
from app.providers.aws_provider import AWSProvider
R = []
def ok(name, cond): R.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name)

# lifespan without background loops
async def noop(): await asyncio.sleep(3600)
for f in ("task_loop","monitor_loop","schedule_loop"): setattr(tasks, f, noop)
telegram.poll_loop = noop
with TestClient(main.app) as c:
    ok("NFR-01 unauth 401", c.get("/api/accounts").status_code == 401)
    ok("health public", c.get("/api/health").json()["ok"])
    ok("NFR-01 fernet key 600", stat.S_IMODE(os.stat(os.path.join(D, "fernet.key")).st_mode) == 0o600)
    ok("NFR-01 PBKDF2 210000", "210000" in core.get_setting("password_hash", ""))
    r = c.post("/api/login", json={"password": "devpassword123"})
    ok("login 200 + HttpOnly cookie, no token to browser", r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower() and "token" not in r.json())
    ok("app login gets bearer", "token" in c.post("/api/login", json={"password": "devpassword123", "client": "app"}).json())
    # add aws account with stubbed test()
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        r = c.post("/api/accounts", json={"provider": "aws", "name": "aws1", "cred": {"access_key": "AKIDEMO", "secret_key": "s", "region": "us-east-1"}})
    aid = r.json()["id"]
    raw = core.q("SELECT cred_enc FROM accounts WHERE id=?", (aid,), one=True)["cred_enc"]
    ok("NFR-01 cred encrypted at rest", "AKIDEMO" not in str(raw))
    c.post(f"/api/accounts/{aid}/credits", json={"name": "c", "amount": 100, "start_date": "2026-08-01"})

    calls = {"n": 0}
    def fake_ce(self, credit_since=None):
        calls["n"] += 1
        return {"period": "x", "currency": "USD", "total": 0.16, "services": [], "credits_used": 18.4, "ce_calls": 2}
    with mock.patch.object(AWSProvider, "cost_explorer", fake_ce):
        import contextlib
        @contextlib.contextmanager
        def at(day):
            t = dt.datetime(2026, 10, day, 9, 0, tzinfo=services.tz())
            with mock.patch.object(services, "now_local", return_value=t), mock.patch.object(services.time, "time", return_value=t.timestamp()):
                yield
        with at(10):
            b = c.get(f"/api/accounts/{aid}/billing").json()
            ok("FR-03 no cache on non-refresh day -> no CE call", calls["n"] == 0 and b["no_cache"] and b["total"] is None)
            telegram.billing_report()
            ok("FR-03 TG/daily report no CE", calls["n"] == 0)
            services.aws_billing(aid, scheduled=True)
            ok("FR-03 scheduled on 10th -> no CE", calls["n"] == 0)
        with at(15):
            services.aws_billing(aid, scheduled=True); services.aws_billing(aid, scheduled=True)
            ok("FR-03 scheduled 15th -> exactly 1 refresh", calls["n"] == 1)
        with at(16):
            b = c.get(f"/api/accounts/{aid}/billing").json()
            ok("FR-03 Web reads cache + 'updated' shown", calls["n"] == 1 and b["cached"] and b["updated_at"] != "尚无数据")
            ok("FR-02 credit remaining = total - used", b["credits"]["remaining"] == 81.6)
            ok("FR-03 next refresh = month end", b["next_refresh"] == "2026-10-31")
            rep = telegram.billing_report()
            ok("FR-03 TG report from cache + 数据更新于", calls["n"] == 1 and "数据更新于" in rep)
        with at(31):
            services.aws_billing(aid, scheduled=True)
            ok("FR-03 month-end refresh", calls["n"] == 2)
        ok("FR-03 Feb 28 is month end (2027)", services.is_aws_refresh_day(dt.date(2027, 2, 28)) and not services.is_aws_refresh_day(dt.date(2027, 2, 27)))
        b = c.get(f"/api/accounts/{aid}/billing?force=true").json()
        ok("FR-03 manual force refresh works", calls["n"] == 3 and not b["cached"])

        # 回收站估算 with moto
        with mock_aws():
            services._cache.clear()
            ec2 = boto3.client("ec2", region_name="us-east-1")
            ami = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
            i = ec2.run_instances(ImageId=ami, MinCount=1, MaxCount=1, InstanceType="t3.micro")["Instances"][0]["InstanceId"]
            ec2.stop_instances(InstanceIds=[i])
            v = ec2.create_volume(AvailabilityZone="us-east-1a", Size=20, VolumeType="gp3")
            ec2.allocate_address(Domain="vpc")
            ec2.create_snapshot(VolumeId=v["VolumeId"])
            n0 = calls["n"]
            r = c.get(f"/api/accounts/{aid}/recycle?region=us-east-1")
            d = r.json()
            kinds = {x["kind"] for x in d.get("items", [])}
            print(json.dumps(d, ensure_ascii=False)[:600])
            ok("FR-03 回收站估算 endpoint 200", r.status_code == 200)
            ok("回收站: stopped inst / volume / eip / snapshot found", {"stopped_instance", "volume", "eip", "snapshot"} <= kinds)
            ok("回收站: gp3 20GB volume = $1.6", any(x["kind"] == "volume" and x["monthly"] == 1.6 for x in d["items"]))
            ok("FR-03 回收站估算 reads billing cache, no CE", calls["n"] == n0 and d["billing_updated_at"] and d["credit_remaining"] == 81.6)
    # settings / tg token encrypted
    c.post("/api/settings", json={"tg_token": "123456:SECRETTOKEN", "tg_chat_id": "42"})
    s = c.get("/api/settings").json()
    ok("FR-04 TG token encrypted & masked", s["tg_token_hint"] == "123456:***" and "SECRETTOKEN" not in json.dumps(core.q("SELECT * FROM settings")))
    # lockout
    c2 = TestClient(main.app)
    codes = [c2.post("/api/login", json={"password": "bad"}).status_code for _ in range(6)]
    ok("NFR-01 lockout after 5 fails", codes[-1] == 429)
    c.post("/api/logout")
    ok("logout invalidates", c.get("/api/accounts").status_code == 401)
print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
