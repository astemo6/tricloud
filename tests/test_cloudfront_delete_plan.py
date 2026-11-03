"""CloudFront 删除分发自动处理套餐订阅自测（moto cloudfront/sts + fake pricing-plan-manager + 任务层打桩）。

覆盖：
1) 任务流（真 provider）：分发订阅 FREE → _cf_delete 先 cancel 再 delete（断言 cancel 在首次
   delete 之前）；且按实测教训模拟「cancel 成功、cf_plans 已无套餐，但 delete_distribution
   头两次仍被 pricing plan 拒绝、第三次才成功」→ 任务应重试并最终完成、删除成功；
2) 任务流（打桩 provider）：付费档 PRO → 任务以中文说明失败（付费套餐 / 账期），
   cancel 与 delete 都未被调用；
3) provider.cf_delete：delete_distribution 抛套餐类 ClientError → 转成中文 ValueError；
4) 任务流（打桩 provider）：无套餐 → 不调 cancel、一次 delete 成功、流程与现行一致；
   cf_plans 返回 None（查询失败）时同样按无套餐走完；
5) 任务流（打桩 provider）：无套餐但 delete 头两次抛含 pricing plan 原文的 ValueError
   （cf_plans 视图滞后的兜底场景）→ 重试后成功。
"""
import asyncio
import os
import sys

os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from botocore.exceptions import ClientError  # noqa: E402
from moto import mock_aws  # noqa: E402

from app import tasks as cf_tasks  # noqa: E402
from app.providers.aws_provider import AWSProvider  # noqa: E402

R = []
PLAN_MSG = ("You can't delete this distribution while it's subscribed to a pricing plan. "
            "Cancel the pricing plan, then you can delete the distribution.")


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


class FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kw):
        return list(self._pages)


class FakePPM:
    """假 pricing-plan-manager（同 test_cloudfront_waf_plan 套路）：记录调用顺序与 cancel 入参。"""

    def __init__(self, order):
        self.subs = []
        self.cancelled = []
        self.order = order

    def get_paginator(self, name):
        assert name == "list_subscriptions"
        return FakePaginator([{"subscriptionSummaries": list(self.subs)}])

    def cancel_subscription(self, arn=None, ifMatch=None, **kw):
        self.order.append("cancel")
        self.cancelled.append({"arn": arn, "ifMatch": ifMatch})
        self.subs = [s for s in self.subs if s["arn"] != arn]
        return {}


class StubProv:
    """任务层打桩 provider：状态全在内存，cf_delete 可按次数先抛套餐错误后成功。"""

    def __init__(self, plans, plan_fail_times=0, plan_fail_mode="cn"):
        self._plans = plans
        self.plan_fail_times = plan_fail_times
        self.plan_fail_mode = plan_fail_mode   # cn=provider 已翻译的中文；raw=含 pricing plan 的英文原文
        self.set_plan_calls = []
        self.delete_calls = 0

    def cf_state(self, did):
        return {"enabled": False, "status": "Deployed"}

    def cf_plans(self):
        return self._plans

    def cf_set_plan(self, did, tier):
        self.set_plan_calls.append((did, tier))
        return {"ok": True, "plan": tier}

    def cf_delete(self, did):
        self.delete_calls += 1
        if self.plan_fail_times > 0:
            self.plan_fail_times -= 1
            if self.plan_fail_mode == "cn":
                raise ValueError("该分发仍订阅着套餐，请先切回按量付费（FREE 可立即取消）再删除")
            raise ValueError(f"AWS 返回错误：{PLAN_MSG}")
        return {"ok": True}


def run_delete_task(prov, did):
    """以打桩的 log/_update 跑 _cf_delete，返回 (updates, 异常或 None)。"""
    updates = []
    orig_log, orig_update, orig_poll = cf_tasks.log, cf_tasks._update, cf_tasks.CF_POLL_SECONDS
    cf_tasks.log = lambda tid, msg, level="info": None  # noqa: E731
    cf_tasks._update = lambda tid, **kw: updates.append(kw)  # noqa: E731
    cf_tasks.CF_POLL_SECONDS = 0
    err = None
    try:
        asyncio.run(cf_tasks._cf_delete({"id": 9100}, {"distribution_id": did}, prov, lambda msg: None))
    except Exception as e:  # 任务失败以异常上抛，测试里接住断言
        err = e
    finally:
        cf_tasks.log, cf_tasks._update, cf_tasks.CF_POLL_SECONDS = orig_log, orig_update, orig_poll
    return updates, err


# ---------- 1) 任务流（真 provider）：FREE 先 cancel 再 delete，delete 头两次被套餐拒绝后重试成功 ----------
with mock_aws():
    p = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
    order = []
    fake = FakePPM(order)
    p.__dict__["_clients"] = {("pricing-plan-manager", "us-east-1"): fake}
    acct = p.c("sts").get_caller_identity()["Account"]
    d1 = p.cf_create("del1.example.com")["id"]
    fake.subs.append({"arn": "arn:aws:pricing-plan-manager::123456789012:subscription/del-1",
                      "planFamily": "CloudFront", "planTier": "FREE", "status": "ACTIVE", "eTag": "etag-del-1",
                      "resourceArns": [f"arn:aws:cloudfront::{acct}:distribution/{d1}"]})

    delete_attempts = {"n": 0}

    def stubborn_delete(**kw):
        delete_attempts["n"] += 1
        order.append("delete")
        if delete_attempts["n"] <= 2:   # 取消已同步到列表视图、删除前置校验还没跟上：头两次仍被拒
            raise ClientError({"Error": {"Code": "PreconditionFailed", "Message": PLAN_MSG}},
                              "DeleteDistribution")

    p._cf().meta.events.register("before-call.cloudfront.DeleteDistribution", stubborn_delete)
    updates, err = run_delete_task(p, d1)
    ok("1: FREE task completes despite stubborn deletes", err is None
       and any(u.get("status") == "done" for u in updates))
    ok("1: cancel happened before first delete attempt", order[:1] == ["cancel"] and "delete" in order)
    ok("1: cancel_subscription called once with arn + ifMatch",
       fake.cancelled == [{"arn": "arn:aws:pricing-plan-manager::123456789012:subscription/del-1",
                           "ifMatch": "etag-del-1"}])
    ok("1: delete retried until third attempt succeeded", delete_attempts["n"] == 3)
    try:
        p._cf().get_distribution(Id=d1)
        ok("1: distribution actually deleted", False)
    except ClientError as e:
        ok("1: distribution actually deleted", e.response["Error"]["Code"] == "NoSuchDistribution")

# ---------- 3) provider.cf_delete：套餐类 ClientError → 中文 ValueError ----------
with mock_aws():
    p = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
    d3 = p.cf_create("del3.example.com")["id"]
    p.cf_set_enabled(d3, False)
    calls = {"n": 0}

    def always_plan_err(**kw):
        calls["n"] += 1
        raise ClientError({"Error": {"Code": "PreconditionFailed", "Message": PLAN_MSG}},
                          "DeleteDistribution")

    p._cf().meta.events.register("before-call.cloudfront.DeleteDistribution", always_plan_err)
    try:
        p.cf_delete(d3)
        ok("3: plan ClientError becomes Chinese ValueError", False)
    except ValueError as e:
        ok("3: plan ClientError becomes Chinese ValueError",
           "仍订阅着套餐" in str(e) and "请先切回按量付费" in str(e) and "You can't delete" not in str(e))
    ok("3: provider itself does not retry", calls["n"] == 1)

# ---------- 2) 任务流（打桩）：付费档不擅自取消、中文说明失败 ----------
prov = StubProv({"E-PAID": "PRO"})
updates, err = run_delete_task(prov, "E-PAID")
ok("2: paid-tier task fails", isinstance(err, RuntimeError) and not any(u.get("status") == "done" for u in updates))
ok("2: failure message explains paid plan + billing cycle",
   err is not None and "PRO" in str(err) and "付费套餐" in str(err) and "账期" in str(err))
ok("2: neither cancel nor delete called for paid tier", prov.set_plan_calls == [] and prov.delete_calls == 0)

# ---------- 4) 任务流（打桩）：无套餐 / cf_plans 查询失败 → 不调 cancel、一次删完 ----------
prov = StubProv({})
updates, err = run_delete_task(prov, "E-PLAIN")
ok("4: no-plan task completes in one delete", err is None and prov.delete_calls == 1
   and any(u.get("status") == "done" for u in updates))
ok("4: no-plan task never touches plan", prov.set_plan_calls == [])

prov = StubProv(None)
updates, err = run_delete_task(prov, "E-UNKNOWN")
ok("4: cf_plans None still completes", err is None and prov.delete_calls == 1 and prov.set_plan_calls == [])

# ---------- 5) 任务流（打桩）：无套餐但 delete 抛套餐原文错误 → 重试后成功 ----------
prov = StubProv({}, plan_fail_times=2, plan_fail_mode="raw")
updates, err = run_delete_task(prov, "E-LAGGING")
ok("5: raw pricing-plan ValueError is retried to success", err is None and prov.delete_calls == 3
   and any(u.get("status") == "done" for u in updates))

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
