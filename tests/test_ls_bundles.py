"""自测：Lightsail 套餐网络标记与创建兼容校验（aws_provider.ls_options / ls_create）。
背景：套餐列表混排双栈与「仅 IPv6」两系（同名同配置只差价钱），用户选了仅 IPv6 的 Nano($3.5)
又搭 IPv4+IPv6 网络，AWS 拒绝且原先报 500。现：options 给仅 IPv6 套餐加标记、create 前置校验、
AWS 错误转可读 ValueError、前端选仅 IPv6 套餐时网络锁定。
全部用假客户端，不连接任何真实云。"""
import os
import sys
import tempfile

os.environ.update(TRICLOUD_DATA=tempfile.mkdtemp())
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from botocore.exceptions import ClientError

from app.providers.aws_provider import AWSProvider

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def bundle(bid, name, price):
    return {"bundleId": bid, "name": name, "cpuCount": 2, "ramSizeInGb": 0.5, "diskSizeInGb": 20,
            "price": price, "supportedPlatforms": ["LINUX_UNIX"]}


class FakeLS:
    def __init__(self):
        self.created, self.err = [], None

    def get_blueprints(self, includeInactive=False):
        return {"blueprints": []}

    def get_bundles(self, includeInactive=False):
        return {"bundles": [bundle("nano_3_0", "Nano", 5.0), bundle("nano_ipv6_3_0", "Nano", 3.5),
                            bundle("micro_ipv6_3_0", "Micro", 5.0), bundle("m_large_1_0", "Large", 74.0),
                            bundle("c_large_ipv6_1_0", "Large", 38.0)]}

    def get_regions(self, includeAvailabilityZones=True):
        return {"regions": [{"name": "eu-central-1", "availabilityZones": [{"zoneName": "eu-central-1a"}]}]}

    def create_instances(self, **kw):
        if self.err:
            raise self.err
        self.created.append(kw)
        return {}


fake = FakeLS()
p = AWSProvider.__new__(AWSProvider)
p.region = "eu-central-1"
p.c = lambda name, region=None: fake

opts = p.ls_options()
by_id = {b["id"]: b for b in opts["bundles"]}
ok("options: dualstack bundle unmarked", by_id["nano_3_0"]["ipv6_only"] is False and "仅IPv6" not in by_id["nano_3_0"]["name"])
ok("options: ipv6 bundle marked + price kept", by_id["nano_ipv6_3_0"]["ipv6_only"] is True
   and by_id["nano_ipv6_3_0"]["name"].endswith("· 仅IPv6") and "$3.5/月" in by_id["nano_ipv6_3_0"]["name"])
ok("options: family by bundle prefix", by_id["nano_3_0"]["family"] == "general" and by_id["m_large_1_0"]["family"] == "memory"
   and by_id["c_large_ipv6_1_0"]["family"] == "compute" and by_id["c_large_ipv6_1_0"]["ipv6_only"] is True)

base = {"name": "tm2", "zone": "eu-central-1a", "blueprint": "ubuntu_22_04", "bundle": "nano_ipv6_3_0"}
try:
    p.ls_create({**base, "ip_type": "dualstack"})
    ok("create: ipv6 bundle + dualstack -> clear ValueError, no AWS call", False)
except ValueError as e:
    ok("create: ipv6 bundle + dualstack -> clear ValueError, no AWS call", "仅 IPv6" in str(e) and not fake.created)

r = p.ls_create({**base, "ip_type": "ipv6"})
ok("create: ipv6 bundle + ipv6 -> ok", r["ok"] and fake.created[-1]["ipAddressType"] == "ipv6" and fake.created[-1]["bundleId"] == "nano_ipv6_3_0")

r = p.ls_create({**base, "bundle": "nano_3_0", "ip_type": "dualstack"})
ok("create: dualstack bundle + dualstack -> ok", r["ok"] and fake.created[-1]["ipAddressType"] == "dualstack")

fake.err = ClientError({"Error": {"Code": "InvalidInputException", "Message": "The ipAddressType isn't compatible with the selected bundle"}}, "CreateInstances")
try:
    p.ls_create({**base, "bundle": "nano_3_0", "ip_type": "ipv6"})
    ok("create: AWS error -> ValueError with original message", False)
except ValueError as e:
    ok("create: AWS error -> ValueError with original message", "ipAddressType isn't compatible" in str(e))
fake.err = None

web = open(os.path.join(ROOT, "web/js/aws.js"), encoding="utf-8").read()
ok("web: family+network selects filter bundle list (console flow)", 'name="family"' in web and "o.bundles.filter" in web
   and "b.family === famSel.value && b.ipv6_only === v6" in web and "aws.planFamily" in web)
i18n = open(os.path.join(ROOT, "web/js/i18n.js"), encoding="utf-8").read()
ok("i18n: family keys in zh+en", i18n.count('"aws.planFamily"') == 2 and i18n.count('"aws.famCompute"') == 2)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
