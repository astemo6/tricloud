"""AWS 账单手动刷新 CE 月度上限自测。

覆盖：
1) 无 Credit 账号：force 前两次放行，第三次拦截且不调用 provider.cost_explorer；
2) 有 Credit 账号：一次 force 消耗 2 次，第一次放行、第二次拦截；失败不扣次数；
3) allowance 接口加次数后可再次 force；
4) scheduled 定时刷新不受手动预算耗尽影响；
5) allowance 接口参数校验（0、负数、>20、小数、字符串均 400）。
"""
import asyncio
import datetime as dt
import os
import sys
import tempfile
from unittest import mock

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123",
                  AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from app import core, main, services, tasks, telegram  # noqa: E402
from app.providers.aws_provider import AWSProvider  # noqa: E402

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


async def noop():
    await asyncio.sleep(3600)


for f in ("task_loop", "monitor_loop", "schedule_loop"):
    setattr(tasks, f, noop)
telegram.poll_loop = noop

CALLS = {"attempts": 0, "fail": False}


def fake_ce(self, credit_since=None):
    CALLS["attempts"] += 1
    if CALLS["fail"]:
        raise RuntimeError("simulated CE failure")
    return {"period": "x", "currency": "USD", "total": 1.0, "services": [],
            "credits_used": 12.0 if credit_since else None,
            "ce_calls": 2 if credit_since else 1}


def force_error(acc_id):
    try:
        services.aws_billing(acc_id, force=True)
    except ValueError as e:
        return str(e)
    return ""


with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        plain_id = c.post("/api/accounts", json={
            "provider": "aws", "name": "plain", "cred": {"access_key": "AKPLAIN", "secret_key": "s", "region": "us-east-1"}
        }).json()["id"]
        credit_id = c.post("/api/accounts", json={
            "provider": "aws", "name": "with-credit", "cred": {"access_key": "AKCREDIT", "secret_key": "s", "region": "us-east-1"}
        }).json()["id"]
    c.post(f"/api/accounts/{credit_id}/credits", json={"name": "c", "amount": 100, "start_date": "2026-01-01"})

    with mock.patch.object(AWSProvider, "cost_explorer", fake_ce):
        # ① 无 Credit：默认预算 2 次调用 = 两次 force；第三次拦截且不调 CE
        b1 = services.aws_billing(plain_id, force=True)
        b2 = services.aws_billing(plain_id, force=True)
        before = CALLS["attempts"]
        err = force_error(plain_id)
        ok("no-credit: first two force refreshes pass and deduct 1 call each",
           CALLS["attempts"] == 2 and b1["manual_ce"] == {"used": 1, "budget": 2}
           and b2["manual_ce"] == {"used": 2, "budget": 2})
        ok("no-credit: third force is blocked with used/budget in message and no CE call",
           CALLS["attempts"] == before and "已用 2 / 上限 2" in err and "增加次数" in err)
        cached = services.aws_billing(plain_id)
        ok("non-force billing read also returns manual_ce", cached["manual_ce"] == {"used": 2, "budget": 2})

        # ③ allowance：+1 后预算变 3，可再 force 一次
        added = c.post(f"/api/accounts/{plain_id}/billing/allowance", json={"add": 1})
        ok("allowance endpoint adds 1 and returns used/budget",
           added.status_code == 200 and added.json() == {"used": 2, "budget": 3})
        b3 = services.aws_billing(plain_id, force=True)
        ok("after allowance, force passes again and deducts actual calls",
           CALLS["attempts"] == before + 1 and b3["manual_ce"] == {"used": 3, "budget": 3})

        # ④ scheduled：手动预算已耗尽（3/3）时，刷新日仍可拉取且不扣手动次数
        core.ex("DELETE FROM billing_cache WHERE account_id=?", (plain_id,))
        real_now = services.now_local()
        refresh_now = real_now.replace(day=15, hour=9, minute=0, second=0, microsecond=0)
        before = CALLS["attempts"]
        with mock.patch.object(services, "now_local", return_value=refresh_now), \
             mock.patch.object(services.time, "time", return_value=refresh_now.timestamp()):
            scheduled = services.aws_billing(plain_id, scheduled=True)
        ok("scheduled refresh ignores exhausted manual budget and does not deduct it",
           CALLS["attempts"] == before + 1 and not scheduled["cached"]
           and scheduled["manual_ce"] == {"used": 3, "budget": 3})

        # ② 有 Credit：一次 force 耗 2；先验证失败不扣，再验证成功后第二次被拦
        CALLS["fail"] = True
        before = CALLS["attempts"]
        try:
            services.aws_billing(credit_id, force=True)
            failed = False
        except RuntimeError:
            failed = True
        CALLS["fail"] = False
        ok("credit account: failed force does not deduct manual calls",
           failed and CALLS["attempts"] == before + 1
           and services.aws_billing(credit_id)["manual_ce"] == {"used": 0, "budget": 2})
        bc = services.aws_billing(credit_id, force=True)
        before = CALLS["attempts"]
        err = force_error(credit_id)
        ok("credit account: one force consumes both calls; second force blocked without CE",
           bc["manual_ce"] == {"used": 2, "budget": 2} and CALLS["attempts"] == before
           and "已用 2 / 上限 2" in err)

        # ⑤ allowance 参数校验：0、负数、>20、小数、字符串都应 400，且预算不变
        budget_before = services.aws_billing(credit_id)["manual_ce"]
        codes = [c.post(f"/api/accounts/{credit_id}/billing/allowance", json={"add": v}).status_code
                 for v in (0, -1, 21, 1.5, "2")]
        ok("allowance validation rejects 0/negative/>20/float/string with 400 and no budget change",
           codes == [400, 400, 400, 400, 400] and services.aws_billing(credit_id)["manual_ce"] == budget_before)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
