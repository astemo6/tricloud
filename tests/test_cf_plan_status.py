"""CloudFront 套餐订阅状态口径自测（2026-11-08 orakr201 事故回归）。

事故：刚订阅 FREE 的分发，订阅还停在 SYNC_IN_PROGRESS 时，列表（cf_plans 只认
ACTIVE/PENDING_APPROVAL）显示「按量付费」，而 cf_set_plan 找现行订阅不看状态，
点订阅又拦「该分发已是 FREE 套餐」——同一分发两处说法相反。
修复：三处统一 CF_SUB_LIVE_STATUSES = ACTIVE / PENDING_APPROVAL / SYNC_IN_PROGRESS，
FAILED 是终态废单不算现行。

覆盖：
1) cf_plans：SYNC_IN_PROGRESS / ACTIVE / PENDING_APPROVAL 都进映射，FAILED 不进；
2) cf_set_plan 同档：SYNC_IN_PROGRESS 的 FREE 单在场 → 抛「已是 FREE 套餐」（与列表显示一致）；
3) cf_set_plan：只有 FAILED 的 FREE 废单在场 → 不算现行，照常新建订阅成功；
4) cf_set_plan PAYGO：只有 FAILED 废单在场 → 抛「已是按量付费」，不调 cancel。
"""
import os
import sys

os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

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
    def __init__(self):
        self.subs = []
        self.created = []
        self.cancelled = []

    def get_paginator(self, name):
        assert name == "list_subscriptions"
        return FakePaginator([{"subscriptionSummaries": list(self.subs)}])

    def create_subscription(self, **kw):
        self.created.append(kw)
        sub = {"arn": f"arn:aws:pricing-plan-manager::123456789012:subscription/fake-{len(self.subs) + 1}",
               "planFamily": kw["planFamily"], "planTier": kw["planTier"], "status": "SYNC_IN_PROGRESS",
               "eTag": f"etag-fake-{len(self.subs) + 1}",
               "resourceArns": list(kw["resourceArns"])}
        self.subs.append(sub)
        return {"subscription": {"arn": sub["arn"], "status": "SYNC_IN_PROGRESS"}}

    def cancel_subscription(self, arn=None, ifMatch=None, **kw):
        self.cancelled.append({"arn": arn, "ifMatch": ifMatch})
        self.subs = [s for s in self.subs if s["arn"] != arn]
        return {}


def sub(dist_arn, tier, status, n):
    return {"arn": f"arn:aws:pricing-plan-manager::123456789012:subscription/s{n}",
            "planFamily": "CloudFront", "planTier": tier, "status": status,
            "eTag": f"etag-{n}", "resourceArns": [dist_arn]}


with mock_aws():
    p = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
    fake = FakePPM()
    p.__dict__["_clients"] = {("pricing-plan-manager", "us-east-1"): fake}
    acct = p.c("sts").get_caller_identity()["Account"]

    def arn_of(dist_id):
        return f"arn:aws:cloudfront::{acct}:distribution/{dist_id}"

    # 1) cf_plans 的状态口径
    fake.subs = [sub(arn_of("DSYNC"), "FREE", "SYNC_IN_PROGRESS", 1),
                 sub(arn_of("DACT"), "PRO", "ACTIVE", 2),
                 sub(arn_of("DPEND"), "PREMIUM", "PENDING_APPROVAL", 3),
                 sub(arn_of("DFAIL"), "BUSINESS", "FAILED", 4)]
    plans = p.cf_plans()
    ok("1: SYNC_IN_PROGRESS counts as FREE", plans.get("DSYNC") == "FREE")
    ok("1: ACTIVE counts", plans.get("DACT") == "PRO")
    ok("1: PENDING_APPROVAL counts", plans.get("DPEND") == "PREMIUM")
    ok("1: FAILED excluded", "DFAIL" not in plans)

    # 2) 同步中的 FREE 单在场，再订 FREE → 与列表一致地拦「已是」
    d2 = p.cf_create("sync.example.com")["id"]
    fake.subs = [sub(arn_of(d2), "FREE", "SYNC_IN_PROGRESS", 5)]
    try:
        p.cf_set_plan(d2, "FREE")
        ok("2: duplicate subscribe during sync raises", False)
    except ValueError as e:
        ok("2: duplicate subscribe during sync raises", "已是 FREE 套餐" in str(e))
    ok("2: no extra subscription created", fake.created == [])

    # 3) 只有 FAILED 废单在场 → 不算现行，照常订阅成功
    d3 = p.cf_create("failed.example.com")["id"]
    fake.subs = [sub(arn_of(d3), "FREE", "FAILED", 6)]
    out = p.cf_set_plan(d3, "FREE")
    ok("3: FAILED sub ignored, subscribe proceeds", out.get("ok") is True and len(fake.created) == 1)

    # 4) PAYGO + 只有 FAILED 废单 → 「已是按量付费」，且不调 cancel
    fake.subs = [sub(arn_of(d3), "FREE", "FAILED", 7)]
    fake.cancelled = []
    try:
        p.cf_set_plan(d3, "PAYGO")
        ok("4: PAYGO with only FAILED sub raises", False)
    except ValueError as e:
        ok("4: PAYGO with only FAILED sub raises", "已是按量付费" in str(e))
    ok("4: cancel not called on dead sub", fake.cancelled == [])

print()
failed = [n for n, c in R if not c]
print(f"{len(R) - len(failed)}/{len(R)} passed")
sys.exit(1 if failed else 0)
