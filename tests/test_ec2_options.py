"""自测：EC2 创建选项（aws_provider.ec2_options / _ec2_prices）。
背景：创建 EC2 对话框的机型原先是裸文本框（预填 t3.micro，看着像「只有一个机型」）且没有价格。
现：types 保持字符串数组（Android/iOS 都按此解析，不动），新增 specs（vCPU/内存 + 官方
Pricing API 查的按需月价），价格在 settings 里按区域缓存（有价 7 天 / 空 1 天），
查价失败静默无价、绝不让创建页打不开。全部用假客户端，不连接任何真实云。"""
import json
import os
import sys
import tempfile

os.environ.update(TRICLOUD_DATA=tempfile.mkdtemp())
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from app import core
from app.providers.aws_provider import AWSProvider

core.init_db()
R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def price_doc(usd):
    return json.dumps({"terms": {"OnDemand": {"T1": {"priceDimensions": {"D1": {"pricePerUnit": {"USD": str(usd)}}}}}}})


class FakePricing:
    def __init__(self):
        self.calls = 0

    def get_products(self, **kw):
        self.calls += 1
        itype = next(f["Value"] for f in kw["Filters"] if f["Field"] == "instanceType")
        if itype == "t3.micro":
            return {"PriceList": [price_doc(0.0104)]}   # 0.0104*730 = 7.59/月
        return {"PriceList": []}


fake = FakePricing()
p = AWSProvider.__new__(AWSProvider)
p.region = "eu-central-1"
p.c = lambda svc, region=None: fake

o = p.ec2_options()
ok("types stays a plain string list (App/iOS compat)", isinstance(o["types"], list) and len(o["types"]) == 13 and all(isinstance(x, str) for x in o["types"]))
ok("specs: t3.micro has vcpu/ram/monthly", o["specs"]["t3.micro"] == {"vcpu": 2, "ram": 1.0, "monthly": 7.59})
ok("specs: unpriced type has specs without monthly", o["specs"]["t3.small"] == {"vcpu": 2, "ram": 2.0})
ok("specs: r6g.large ram 16", o["specs"]["r6g.large"]["ram"] == 16.0)
n1 = fake.calls
o2 = p.ec2_options()
ok("second call served from cache (no new pricing calls)", fake.calls == n1 and o2["specs"]["t3.micro"]["monthly"] == 7.59)

core.set_setting("ec2_prices:eu-west-1", {"ts": 1, "prices": {}})   # 过期空缓存不挡路
p2 = AWSProvider.__new__(AWSProvider)
p2.region = "eu-west-1"


def boom(svc, region=None):
    raise RuntimeError("pricing denied")


p2.c = boom
o3 = p2.ec2_options()
ok("pricing failure -> options still fine, no monthly anywhere", o3["types"] == o["types"] and all("monthly" not in s for s in o3["specs"].values()))

web = open(os.path.join(ROOT, "web/js/aws.js"), encoding="utf-8").read()
ok("web: type is a spec-labeled select with custom escape hatch", '<select name="type">' in web and '"__custom__"' in web
   and 'name="type_custom"' in web and "s.vcpu" in web and "s.monthly" in web and "aws.ec2CustomType" in web)
i18n = open(os.path.join(ROOT, "web/js/i18n.js"), encoding="utf-8").read()
ok("i18n: ec2CustomType in zh+en", i18n.count('"aws.ec2CustomType"') == 2)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
