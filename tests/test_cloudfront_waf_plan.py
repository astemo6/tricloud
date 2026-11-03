"""CloudFront 套餐自动 WAF + 报错透传自测（moto cloudfront/wafv2/sts + fake pricing-plan-manager）。

覆盖：
1) cf_ensure_waf：空 WebACLId 的分发 → 建零规则面板 ACL 并关联；二次调用不重复建；
2) cf_set_plan FREE：create_subscription 被调用时分发已关联 WAF；订阅成功且 message 标注自动关联；
3) cf_set_plan 时已有用户自己的 WAF → 不新建面板 ACL、照常订阅；
4) fake ppm 抛 ClientError(ValidationException) → cf_set_plan 抛 ValueError 且含 AWS 原始 message；
5) cf_delete：带面板 ACL 的分发删除后 ACL 同步消失；带用户 ACL 的分发删除后 ACL 仍在；
6) PAYGO 解绑：返回值带 waf_cleanup 且分发 WebACLId 已清空。
"""
import os
import sys

os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from botocore.exceptions import ClientError  # noqa: E402
from moto import mock_aws  # noqa: E402

from app.providers.aws_provider import AWSProvider  # noqa: E402

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


class FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kw):
        return list(self._pages)


class FakePPM:
    """假 pricing-plan-manager：记录调用，可按需在 create 时回调断言 / 抛 ClientError。"""

    def __init__(self):
        self.subs = []            # list_subscriptions 返回的订阅
        self.created = []         # create_subscription 入参
        self.disassociated = []   # disassociate 入参
        self.fail_create = None   # 置为 ClientError 时 create_subscription 抛它
        self.on_create = None     # create_subscription 被调用时的钩子

    def get_paginator(self, name):
        assert name == "list_subscriptions"
        return FakePaginator([{"subscriptionSummaries": list(self.subs)}])

    def create_subscription(self, **kw):
        self.created.append(kw)
        if self.on_create:
            self.on_create(kw)
        if self.fail_create:
            raise self.fail_create
        sub = {"arn": f"arn:aws:pricing-plan-manager::123456789012:subscription/fake-{len(self.subs) + 1}",
               "planFamily": kw["planFamily"], "planTier": kw["planTier"], "status": "ACTIVE",
               "resourceArns": list(kw["resourceArns"])}
        self.subs.append(sub)
        return {"subscription": {"arn": sub["arn"], "status": "ACTIVE"}}

    def disassociate_resources_from_subscription(self, arn=None, resourceArns=None, **kw):
        self.disassociated.append({"arn": arn, "resourceArns": resourceArns})
        for s in self.subs:
            if s["arn"] == arn:
                s["resourceArns"] = [a for a in s["resourceArns"] if a not in (resourceArns or [])]
        return {}


def waf_names(p):
    return [a["Name"] for a in p.c("wafv2", "us-east-1").list_web_acls(Scope="CLOUDFRONT", Limit=100).get("WebACLs", [])]


def dist_cfg(p, dist_id):
    return p._cf().get_distribution_config(Id=dist_id)["DistributionConfig"]


def attach_waf(p, dist_id, acl_arn):
    cf = p._cf()
    g = cf.get_distribution_config(Id=dist_id)
    cfg = g["DistributionConfig"]
    cfg["WebACLId"] = acl_arn
    cf.update_distribution(Id=dist_id, IfMatch=g["ETag"], DistributionConfig=cfg)


def make_user_acl(p, name):
    return p.c("wafv2", "us-east-1").create_web_acl(
        Name=name, Scope="CLOUDFRONT", DefaultAction={"Allow": {}}, Rules=[],
        VisibilityConfig={"SampledRequestsEnabled": False, "CloudWatchMetricsEnabled": False,
                          "MetricName": name})["Summary"]["ARN"]


with mock_aws():
    p = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
    fake = FakePPM()
    p.__dict__["_clients"] = {("pricing-plan-manager", "us-east-1"): fake}   # 打桩点：client 工厂按服务名分发
    acct = p.c("sts").get_caller_identity()["Account"]

    # 1) ensure_waf：建零规则 ACL 并关联；二次调用幂等
    d1 = p.cf_create("waf1.example.com")["id"]
    info = p.cf_ensure_waf(d1)
    ok("1: ensure_waf created+attached", info["created"] is True and info["attached"] is True)
    ok("1: config WebACLId == new ACL ARN", dist_cfg(p, d1).get("WebACLId") == info["web_acl_arn"])
    ok("1: ACL named tricloud-cf-<id>", waf_names(p) == [f"tricloud-cf-{d1.lower()}"])
    acl = p.c("wafv2", "us-east-1").get_web_acl(Name=f"tricloud-cf-{d1.lower()}", Scope="CLOUDFRONT",
                                                Id=info["web_acl_arn"].split("/")[-1])["WebACL"]
    ok("1: ACL has zero rules", acl["Rules"] == [])
    info2 = p.cf_ensure_waf(d1)
    ok("1: second ensure_waf is a no-op", info2["created"] is False and info2["attached"] is False
       and waf_names(p) == [f"tricloud-cf-{d1.lower()}"])

    # 2) set_plan FREE：订阅时 WAF 已关联
    d2 = p.cf_create("waf2.example.com")["id"]
    seen = {}
    fake.on_create = lambda kw: seen.setdefault("web_acl", dist_cfg(p, d2).get("WebACLId"))
    r = p.cf_set_plan(d2, "FREE")
    fake.on_create = None
    ok("2: create_subscription called after WAF attached", bool(seen.get("web_acl")))
    ok("2: subscribe FREE ok + message notes auto WAF",
       r["ok"] is True and r["plan"] == "FREE" and "已自动关联 WAF" in r["message"])
    ok("2: fake ppm got planTier FREE", fake.created[-1]["planTier"] == "FREE")

    # 3) 已有用户 WAF：不新建面板 ACL
    d3 = p.cf_create("waf3.example.com")["id"]
    attach_waf(p, d3, make_user_acl(p, "user-own-acl"))
    before = set(waf_names(p))
    r = p.cf_set_plan(d3, "FREE")
    ok("3: subscribe with user WAF ok", r["ok"] is True and "已自动关联 WAF" not in r["message"])
    ok("3: no panel ACL created for user-WAF dist", set(waf_names(p)) == before
       and f"tricloud-cf-{d3.lower()}" not in waf_names(p))

    # 4) AWS 报错透传
    d4 = p.cf_create("waf4.example.com")["id"]
    fake.fail_create = ClientError({"Error": {"Code": "ValidationException",
                                              "Message": "Resources are incompatible with plan tier 'FREE': modify resources"}},
                                   "CreateSubscription")
    try:
        p.cf_set_plan(d4, "FREE")
        ok("4: ClientError becomes ValueError with AWS message", False)
    except ValueError as e:
        ok("4: ClientError becomes ValueError with AWS message",
           "Resources are incompatible with plan tier 'FREE'" in str(e))
    fake.fail_create = None

    # 5) cf_delete 同步删面板 WAF、不动用户 WAF
    d5 = p.cf_create("waf5.example.com")["id"]
    p.cf_ensure_waf(d5)
    p.cf_set_enabled(d5, False)
    r = p.cf_delete(d5)
    ok("5: delete dist with panel WAF reports waf_deleted", r["ok"] is True and r.get("waf_deleted") is True)
    ok("5: panel WAF gone after delete", f"tricloud-cf-{d5.lower()}" not in waf_names(p))

    d6 = p.cf_create("waf6.example.com")["id"]
    attach_waf(p, d6, make_user_acl(p, "keep-acl"))
    p.cf_set_enabled(d6, False)
    r = p.cf_delete(d6)
    ok("5: delete dist with user WAF leaves it alone", r["ok"] is True and "keep-acl" in waf_names(p))

    # 6) PAYGO 解绑带面板 ACL：返回 waf_cleanup 且 WebACLId 已清空
    d7 = p.cf_create("waf7.example.com")["id"]
    p.cf_ensure_waf(d7)
    fake.subs.append({"arn": "arn:aws:pricing-plan-manager::123456789012:subscription/manual-1",
                      "planFamily": "CloudFront", "planTier": "FREE", "status": "ACTIVE",
                      "resourceArns": [f"arn:aws:cloudfront::{acct}:distribution/{d7}"]})
    r = p.cf_set_plan(d7, "PAYGO")
    ok("6: PAYGO returns waf_cleanup for panel WAF",
       r["ok"] is True and (r.get("waf_cleanup") or {}).get("name") == f"tricloud-cf-{d7.lower()}")
    ok("6: WebACLId cleared after PAYGO detach", dist_cfg(p, d7).get("WebACLId") == "")
    ok("6: disassociate called on the subscription", len(fake.disassociated) == 1)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
