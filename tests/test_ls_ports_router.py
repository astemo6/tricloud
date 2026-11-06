"""自测：Lightsail 防火墙路由（POST /api/accounts/{id}/lightsail/ports）。
覆盖：icmp/icmpv6 的 -1（云端存值）在路由层归一、不再误报「端口范围无效」（关闭 icmp 规则的原 bug）；
tcp 的 -1 仍被拦；open all + 公网经二次确认（confirm_public）后放行、未确认 409（_public_guard 新行为）。
provider 用假对象记录入参，不连接任何真实云。"""
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

from fastapi.testclient import TestClient

from app import main, services
from app.providers.aws_provider import AWSProvider

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


class FakeProv:
    def __init__(self):
        self.calls = []

    def ls_open_port(self, instance, protocol, a, b, cidrs=None):
        self.calls.append(("open", instance, protocol, a, b, cidrs))
        return {"ok": True}

    def ls_close_port(self, instance, protocol, a, b):
        self.calls.append(("close", instance, protocol, a, b))
        return {"ok": True}


mock.patch.object(AWSProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()

with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        aid = c.post("/api/accounts", json={"provider": "aws", "name": "aws-1", "cred": {
            "access_key": "AKIAFAKEFAKE1234", "secret_key": "s3cr3t-fake", "region": "eu-central-1"}}).json()["id"]
    fp = FakeProv()
    with mock.patch.object(services, "provider", lambda acc_id, region=None: fp):
        url = f"/api/accounts/{aid}/lightsail/ports"
        r = c.post(url, json={"op": "close", "instance": "tm", "protocol": "icmp", "from_port": -1, "to_port": -1})
        ok("close icmp -1/-1 -> 200, normalized to 0/0 for provider", r.status_code == 200 and fp.calls[-1] == ("close", "tm", "icmp", 0, 0))
        r = c.post(url, json={"op": "close", "instance": "tm", "protocol": "tcp", "from_port": 22, "to_port": 22})
        ok("close tcp 22 -> 200 passthrough", r.status_code == 200 and fp.calls[-1] == ("close", "tm", "tcp", 22, 22))
        r = c.post(url, json={"op": "close", "instance": "tm", "protocol": "tcp", "from_port": -1, "to_port": -1})
        ok("close tcp -1 -> still 400 port range", r.status_code == 400)
        r = c.post(url, json={"op": "open", "instance": "tm", "protocol": "icmp", "from_port": -1, "to_port": -1, "cidrs": "0.0.0.0/0", "confirm_public": True})
        ok("open icmp -1/-1 confirmed -> 200", r.status_code == 200 and fp.calls[-1][:5] == ("open", "tm", "icmp", 0, 0))
        r = c.post(url, json={"op": "open", "instance": "tm", "protocol": "all", "from_port": 0, "to_port": 65535, "cidrs": "0.0.0.0/0"})
        ok("open all + public unconfirmed -> 409", r.status_code == 409)
        r = c.post(url, json={"op": "open", "instance": "tm", "protocol": "all", "from_port": 0, "to_port": 65535, "cidrs": "0.0.0.0/0", "confirm_public": True})
        ok("open all + public confirmed -> 200 (no more hard block)", r.status_code == 200 and fp.calls[-1][:5] == ("open", "tm", "all", 0, 65535))

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
