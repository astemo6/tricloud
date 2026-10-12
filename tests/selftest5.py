"""v1.3 自测：流量守护（预警/上限/停机/跨月重置/不重复推送）、AWS CloudWatch 流量（moto）。
v1.5：串口控制台已整体移除，原 12 项控制台用例删除，改为 4 项「控制台路由已不存在」的检查。"""
import asyncio
import datetime as dt
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

from app import core, main, services, tasks, telegram, traffic_guard
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
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        aid = c.post("/api/accounts", json={"provider": "aws", "name": "aws1",
                                            "cred": {"access_key": "AK", "secret_key": "s", "region": "us-east-1"}}).json()["id"]
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}), \
         mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: None):
        oid = c.post("/api/accounts", json={"provider": "oci", "name": "oci1", "cred": {
            "user": "u", "tenancy": "t", "fingerprint": "f", "key_content": "k", "region": "ap-tokyo-1"}}).json()["id"]

    # ---------------- 流量守护 ----------------
    use = {"out_gb": 50.0, "in_gb": 5.0}
    stops = []
    with mock.patch.object(traffic_guard, "usage", lambda g: dict(use)), \
         mock.patch.object(services, "instance_action", lambda *a, **k: stops.append(a) or {"ok": True}):
        r = c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-1", "name": "tokyo", "action": "stop"})
        g = c.get("/api/traffic-guards").json()[0]
        ok("guard default limit = AWS 100GB free, initial read no stop", r.json()["last_gb"] == 50.0 and g["limit_gb"] == 100 and not stops)
        ok("bad warn pct rejected", c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-1", "warn_pct": 5}).status_code == 400)
        use["out_gb"] = 85
        c.post(f"/api/traffic-guards/{g['id']}/check")
        ok("80% warn pushed once", sum("流量预警" in s for s in sent) == 1 and not stops)
        c.post(f"/api/traffic-guards/{g['id']}/check")
        ok("warn not repeated", sum("流量预警" in s for s in sent) == 1)
        use["out_gb"] = 101
        c.post(f"/api/traffic-guards/{g['id']}/check")
        ok("limit reached -> stop + push", len(stops) == 1 and stops[0][2] == "stop" and any("已自动停机" in s for s in sent))
        c.post(f"/api/traffic-guards/{g['id']}/check")
        ok("stop not repeated", len(stops) == 1)
        core.ex("UPDATE traffic_guards SET month='2000-01' WHERE id=?", (g["id"],))
        use["out_gb"] = 1
        c.post(f"/api/traffic-guards/{g['id']}/check")
        ok("new month resets level", core.q("SELECT notified FROM traffic_guards WHERE id=?", (g["id"],), one=True)["notified"] == 0)
        c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-2", "name": "n2", "limit_gb": 50, "count_in": True})
        use.update(out_gb=30, in_gb=20)
        g2 = [x for x in c.get("/api/traffic-guards").json() if x["instance_id"] == "i-2"][0]
        c.post(f"/api/traffic-guards/{g2['id']}/check")
        ok("count_in sums both directions; notify-only never stops",
           core.q("SELECT last_gb FROM traffic_guards WHERE id=?", (g2["id"],), one=True)["last_gb"] == 50 and len(stops) == 1)
        core.ex("UPDATE traffic_guards SET checked_at=?", (int(time.time()),))
        ok("due() respects 30min interval", traffic_guard.due() == [])
        c.delete(f"/api/traffic-guards/{g2['id']}")
        ok("guard deleted", len(c.get("/api/traffic-guards").json()) == 1)

    with mock_aws():
        import boto3
        cw = boto3.client("cloudwatch", "us-east-1")
        now = dt.datetime.now(dt.timezone.utc)
        for v in (2 * 1024 ** 3, 3 * 1024 ** 3):
            cw.put_metric_data(Namespace="AWS/EC2", MetricData=[{"MetricName": "NetworkOut", "Value": v, "Unit": "Bytes",
                                                                 "Timestamp": now - dt.timedelta(minutes=5),
                                                                 "Dimensions": [{"Name": "InstanceId", "Value": "i-abc"}]}])
        services.drop_provider_cache(aid)
        t = c.get(f"/api/accounts/{aid}/traffic?instance_id=i-abc").json()
        ok("AWS CloudWatch monthly out traffic", abs(t["out_gb"] - 5.0) < 0.01 and t["in_gb"] == 0)

    # ---------------- v1.5：串口控制台已移除 ----------------
    ok("console: /aws/serial GET/POST gone", c.get(f"/api/accounts/{aid}/aws/serial").status_code == 404
       and c.post(f"/api/accounts/{aid}/aws/serial").status_code in (404, 405))
    ok("console: /azure/serial-log gone", c.get(f"/api/accounts/{aid}/azure/serial-log?instance_id=x").status_code == 404)
    try:
        with c.websocket_connect(f"/api/ws/console/{aid}?instance_id=i-1"):
            pass
        ok("console: websocket route gone", False)
    except Exception:
        ok("console: websocket route gone", True)
    ok("console: module & provider methods gone", not os.path.exists(os.path.join(os.path.dirname(main.__file__), "console.py"))
       and not hasattr(AWSProvider, "console_open") and not hasattr(OCIProvider, "console_open"))
    ok("version 1.3+", c.get("/api/health").json()["version"] >= "1.3.0")

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
