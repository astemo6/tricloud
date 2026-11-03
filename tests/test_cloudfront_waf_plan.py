"""CloudFront 套餐自动 WAF + 报错透传自测（moto cloudfront/wafv2/sts + fake pricing-plan-manager）。

覆盖：
1) cf_ensure_waf：空 WebACLId 的分发 → 建零规则面板 ACL 并关联；二次调用不重复建；
2) cf_set_plan FREE：create_subscription 被调用时分发已关联 WAF，且 resourceArns 恰为 {分发 ARN, WAF ARN}；
3) cf_set_plan 时已有用户自己的 WAF → 不新建面板 ACL、照常订阅，resourceArns 带用户 WAF ARN；
4) fake ppm 抛 ClientError(ValidationException) → cf_set_plan 抛 ValueError 且含 AWS 原始 message；
5) cf_delete：带面板 ACL 的分发删除后 ACL 同步消失；带用户 ACL 的分发删除后 ACL 仍在；
6) PAYGO（当前 FREE）：走 cancel_subscription（arn + ifMatch=eTag），返回值带 waf_cleanup 但不同步解绑
   （WebACLId 仍保持关联——取消同步传播期 CloudFront 不许拆 WAF，解绑归 cf_waf_cleanup 任务）；
7) PAYGO（当前付费档 PRO）：走 cancel、不拆 WAF、不带 waf_cleanup、message 含账期字样；
8) cf_waf_cleanup 任务：解绑第一次被 AWS 拒绝、重试后成功 → 最终删掉 WAF；关联的不是面板 ACL
   时 warn 结束，不解绑不删除。
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
        self.disassociated = []   # disassociate 入参（现行代码已不用，保留防误调用时可观测）
        self.cancelled = []       # cancel_subscription 入参
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
               "eTag": f"etag-fake-{len(self.subs) + 1}",
               "resourceArns": list(kw["resourceArns"])}
        self.subs.append(sub)
        return {"subscription": {"arn": sub["arn"], "status": "ACTIVE"}}

    def disassociate_resources_from_subscription(self, arn=None, resourceArns=None, **kw):
        self.disassociated.append({"arn": arn, "resourceArns": resourceArns})
        for s in self.subs:
            if s["arn"] == arn:
                s["resourceArns"] = [a for a in s["resourceArns"] if a not in (resourceArns or [])]
        return {}

    def cancel_subscription(self, arn=None, ifMatch=None, **kw):
        self.cancelled.append({"arn": arn, "ifMatch": ifMatch})
        self.subs = [s for s in self.subs if s["arn"] != arn]
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
    ok("2: resourceArns == {dist ARN, WAF ARN}",
       set(fake.created[-1]["resourceArns"]) == {f"arn:aws:cloudfront::{acct}:distribution/{d2}", seen["web_acl"]})

    # 3) 已有用户 WAF：不新建面板 ACL
    d3 = p.cf_create("waf3.example.com")["id"]
    user_arn = make_user_acl(p, "user-own-acl")
    attach_waf(p, d3, user_arn)
    before = set(waf_names(p))
    r = p.cf_set_plan(d3, "FREE")
    ok("3: subscribe with user WAF ok", r["ok"] is True and "已自动关联 WAF" not in r["message"])
    ok("3: no panel ACL created for user-WAF dist", set(waf_names(p)) == before
       and f"tricloud-cf-{d3.lower()}" not in waf_names(p))
    ok("3: resourceArns == {dist ARN, user WAF ARN}",
       set(fake.created[-1]["resourceArns"]) == {f"arn:aws:cloudfront::{acct}:distribution/{d3}", user_arn})

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

    # 6) PAYGO（当前 FREE）走 cancel：返回 waf_cleanup，但不同步解绑（解绑归清理任务带重试地做）
    d7 = p.cf_create("waf7.example.com")["id"]
    panel7 = p.cf_ensure_waf(d7)
    fake.subs.append({"arn": "arn:aws:pricing-plan-manager::123456789012:subscription/manual-1",
                      "planFamily": "CloudFront", "planTier": "FREE", "status": "ACTIVE", "eTag": "etag-manual-1",
                      "resourceArns": [f"arn:aws:cloudfront::{acct}:distribution/{d7}"]})
    r = p.cf_set_plan(d7, "PAYGO")
    ok("6: PAYGO returns waf_cleanup for panel WAF",
       r["ok"] is True and (r.get("waf_cleanup") or {}).get("name") == f"tricloud-cf-{d7.lower()}")
    ok("6: WebACLId still attached after PAYGO (no sync detach)",
       dist_cfg(p, d7).get("WebACLId") == panel7["web_acl_arn"])
    ok("6: PAYGO message promises auto WAF deletion after cancel takes effect",
       "自动删除" in r["message"] and "取消生效后" in r["message"])
    ok("6: cancel_subscription called with arn + ifMatch == eTag",
       fake.cancelled == [{"arn": "arn:aws:pricing-plan-manager::123456789012:subscription/manual-1",
                           "ifMatch": "etag-manual-1"}])
    ok("6: disassociate no longer used", fake.disassociated == [])

    # 7) PAYGO（当前付费档 PRO）：只 cancel 排账期结束，不拆 WAF、不带 waf_cleanup
    d8 = p.cf_create("waf8.example.com")["id"]
    panel_info = p.cf_ensure_waf(d8)
    fake.subs.append({"arn": "arn:aws:pricing-plan-manager::123456789012:subscription/manual-2",
                      "planFamily": "CloudFront", "planTier": "PRO", "status": "ACTIVE", "eTag": "etag-manual-2",
                      "resourceArns": [f"arn:aws:cloudfront::{acct}:distribution/{d8}"]})
    r = p.cf_set_plan(d8, "PAYGO")
    ok("7: paid PAYGO cancels with arn + ifMatch == eTag",
       fake.cancelled[-1] == {"arn": "arn:aws:pricing-plan-manager::123456789012:subscription/manual-2",
                              "ifMatch": "etag-manual-2"})
    ok("7: paid PAYGO keeps WAF attached, no waf_cleanup",
       "waf_cleanup" not in r and dist_cfg(p, d8).get("WebACLId") == panel_info["web_acl_arn"])
    ok("7: paid PAYGO message defers to billing cycle end",
       r["ok"] is True and r["plan"] == "PAYGO" and "账期" in r["message"] and "PRO" in r["message"])

    # 8) cf_waf_cleanup 任务：解绑带重试；关联的不是面板 ACL 时 warn 结束、不动任何东西
    import asyncio as _aio

    from app import tasks as cf_tasks

    class FakeCF:
        def __init__(self, prov):
            self._prov = prov

        def get_distribution_config(self, Id=None):
            if self._prov.gone:
                raise ClientError({"Error": {"Code": "NoSuchDistribution", "Message": "gone"}},
                                  "GetDistributionConfig")
            return {"DistributionConfig": {"WebACLId": self._prov.web_acl_id}, "ETag": "etag"}

    class FakeProv:
        """任务测试用假 provider：状态全在内存，detach 可按次数先失败后成功。"""

        def __init__(self, web_acl_id):
            self.web_acl_id = web_acl_id
            self.gone = False
            self.detach_calls = 0
            self.fail_detach_times = 0
            self.deleted = []

        def _cf(self):
            return FakeCF(self)

        def cf_state(self, did):
            return {"status": "Deployed"}

        def _panel_waf_from_arn(self, arn):
            return AWSProvider._panel_waf_from_arn(arn)

        def _cf_detach_panel_waf(self, did):
            self.detach_calls += 1
            if self.fail_detach_times > 0:
                self.fail_detach_times -= 1
                raise ValueError("AWS 返回错误：You can't remove or replace the web ACL for your distribution. "
                                 "Distributions with a pricing plan subscription must have a web ACL resource.")
            info = AWSProvider._panel_waf_from_arn(self.web_acl_id)
            self.web_acl_id = ""
            return info

        def cf_delete_waf(self, name, acl_id):
            self.deleted.append((name, acl_id))
            return {"ok": True}

    task_logs = []
    orig_log, orig_update = cf_tasks.log, cf_tasks._update
    orig_poll = cf_tasks.WAF_CLEANUP_POLL_SECONDS
    cf_tasks.log = lambda tid, msg, level="info": task_logs.append((level, msg))  # noqa: E731
    cf_tasks._update = lambda tid, **kw: None  # noqa: E731
    cf_tasks.WAF_CLEANUP_POLL_SECONDS = 0   # 测试里不真等轮询间隔
    try:
        panel_arn = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/tricloud-cf-e8/acl-id-8"
        prov8 = FakeProv(panel_arn)
        prov8.fail_detach_times = 1   # 第一次解绑被 AWS 拒绝（取消还在同步传播），第二次放行
        _aio.run(cf_tasks._cf_waf_cleanup(
            {"id": 9001}, {"distribution_id": "E8", "acl_name": "tricloud-cf-e8", "acl_id": "acl-id-8"},
            prov8, lambda msg: None))
        ok("8: cleanup retried detach after AWS refusal", prov8.detach_calls == 2)
        ok("8: cleanup deleted WAF after detach succeeded",
           prov8.deleted == [("tricloud-cf-e8", "acl-id-8")] and prov8.web_acl_id == "")

        user_arn = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/user-own-acl/acl-id-9"
        prov9 = FakeProv(user_arn)
        _aio.run(cf_tasks._cf_waf_cleanup(
            {"id": 9002}, {"distribution_id": "E9", "acl_name": "tricloud-cf-e9", "acl_id": "acl-id-9"},
            prov9, lambda msg: None))
        ok("8: cleanup leaves non-panel WAF alone (no detach, no delete)",
           prov9.detach_calls == 0 and prov9.deleted == [] and prov9.web_acl_id == user_arn)
        ok("8: cleanup warned about non-panel WAF", any(lv == "warn" for lv, _ in task_logs))
    finally:
        cf_tasks.log, cf_tasks._update = orig_log, orig_update
        cf_tasks.WAF_CLEANUP_POLL_SECONDS = orig_poll

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
