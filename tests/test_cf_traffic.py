"""CloudFront 分发已用流量监控测试（CloudWatch get_metric_statistics / 周期计算 / 额度 / 缓存 / 容错）。"""
import calendar
import datetime as dt
import os
import sys
import tempfile

D = tempfile.mkdtemp()
os.environ.update(
    TRICLOUD_DATA=D,
    PANEL_PASSWORD="test",
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    AWS_DEFAULT_REGION="us-east-1",
)
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from app import core  # noqa: E402

core.init_db()

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402
from app.providers.aws_provider import AWSProvider, CF_TRAFFIC_QUOTA_BYTES  # noqa: E402

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


with mock_aws():
    cw = boto3.client("cloudwatch", region_name="us-east-1")
    now = dt.datetime.now(dt.timezone.utc)
    one_day_ago = now - dt.timedelta(days=1)

    # 写入 CloudWatch 指标数据
    cw.put_metric_data(
        Namespace="AWS/CloudFront",
        MetricData=[
            {
                "MetricName": "BytesDownloaded",
                "Dimensions": [
                    {"Name": "DistributionId", "Value": "E123"},
                    {"Name": "Region", "Value": "Global"},
                ],
                "Timestamp": one_day_ago,
                "Value": 3000000000.0,
                "Unit": "Bytes",
            },
            {
                "MetricName": "BytesUploaded",
                "Dimensions": [
                    {"Name": "DistributionId", "Value": "E123"},
                    {"Name": "Region", "Value": "Global"},
                ],
                "Timestamp": one_day_ago,
                "Value": 1000000000.0,
                "Unit": "Bytes",
            },
            {
                "MetricName": "BytesDownloaded",
                "Dimensions": [
                    {"Name": "DistributionId", "Value": "E456"},
                    {"Name": "Region", "Value": "Global"},
                ],
                "Timestamp": one_day_ago,
                "Value": 500000000.0,
                "Unit": "Bytes",
            },
            {
                "MetricName": "BytesUploaded",
                "Dimensions": [
                    {"Name": "DistributionId", "Value": "E456"},
                    {"Name": "Region", "Value": "Global"},
                ],
                "Timestamp": one_day_ago,
                "Value": 200000000.0,
                "Unit": "Bytes",
            },
        ],
    )

    # 场景1 聚合+额度+自然月
    p1 = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
    p1.cf_list = lambda: [{"id": "E123", "plan": "FREE"}, {"id": "E456", "plan": "PAYGO"}]
    p1._cf_sub_starts = lambda: {}

    res1 = p1.cf_traffic(901)
    e123_1 = res1.get("items", {}).get("E123", {})
    e456_1 = res1.get("items", {}).get("E456", {})

    ok("scenario 1: E123 down == 3000000000", e123_1.get("down") == 3000000000)
    ok("scenario 1: E123 up == 1000000000", e123_1.get("up") == 1000000000)
    ok("scenario 1: E123 total == 4000000000", e123_1.get("total") == 4000000000)
    ok("scenario 1: E123 quota_bytes == 100*1024**3", e123_1.get("quota_bytes") == 100 * 1024**3)
    ok("scenario 1: E123 total30d == 4000000000", e123_1.get("total30d") == 4000000000)
    ok("scenario 1: E123 period_basis == 'month'", e123_1.get("period_basis") == "month")
    ok("scenario 1: E456 quota_bytes is None", e456_1.get("quota_bytes") is None)
    ok("scenario 1: E456 total30d == 700000000", e456_1.get("total30d") == 700000000)

    # 场景2 缓存命中
    def boom(*args, **kwargs):
        raise RuntimeError("AWS should not be called when cache hits")

    p1.c = boom
    res2 = p1.cf_traffic(901)
    ok("scenario 2: cache hit returns same items", res2.get("items") == res1.get("items"))
    ok("scenario 2: cache hit has no error key", "error" not in res2)

    # 场景3 套餐周期
    p3 = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
    p3.cf_list = lambda: [{"id": "E123", "plan": "FREE"}]
    sub_start_dt = now - dt.timedelta(days=40)
    p3._cf_sub_starts = lambda: {"E123": sub_start_dt}

    res3 = p3.cf_traffic(902)
    e123_3 = res3.get("items", {}).get("E123", {})
    ok("scenario 3: period_basis == 'plan'", e123_3.get("period_basis") == "plan")

    p_start_str = e123_3.get("period_start")
    p_start = dt.datetime.fromisoformat(p_start_str) if p_start_str else None
    ok("scenario 3: period_start <= now", p_start is not None and p_start <= now)
    ok("scenario 3: now - period_start < 32 days", p_start is not None and (now - p_start).total_seconds() < 32 * 86400)
    if p_start:
        last_day_cur = calendar.monthrange(p_start.year, p_start.month)[1]
        ok("scenario 3: period_start.day matches clamped sub_start.day", p_start.day == min(sub_start_dt.day, last_day_cur))
    else:
        ok("scenario 3: period_start.day matches clamped sub_start.day", False)
    ok("scenario 3: total remains 4000000000", e123_3.get("total") == 4000000000)
    ok("scenario 3: E123 total30d == 4000000000", e123_3.get("total30d") == 4000000000)

    # 场景4 无权限不抛
    p4 = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
    p4.cf_list = lambda: [{"id": "E123", "plan": "FREE"}]

    def throw_access_denied(*args, **kwargs):
        raise RuntimeError("AccessDenied")

    p4.c = throw_access_denied
    try:
        res4 = p4.cf_traffic(903)
        no_exc = True
    except Exception:
        no_exc = False
        res4 = {}

    ok("scenario 4: does not raise exception", no_exc)
    ok("scenario 4: items == {}", res4.get("items") == {})
    ok("scenario 4: error field in result", "error" in res4 and "AccessDenied" in str(res4.get("error")))

    # 场景5 纯函数
    s5_1 = dt.datetime(2026, 8, 15, tzinfo=dt.timezone.utc)
    n5 = dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc)
    res5_1 = AWSProvider._cf_period_start("FREE", s5_1, n5)
    ok(
        "scenario 5.1: 2026-08-15 -> (2026-10-15, 'plan')",
        res5_1 == (dt.datetime(2026, 10, 15, 0, 0, 0, tzinfo=dt.timezone.utc), "plan"),
    )

    s5_2 = dt.datetime(2026, 8, 31, tzinfo=dt.timezone.utc)
    res5_2 = AWSProvider._cf_period_start("FREE", s5_2, n5)
    ok(
        "scenario 5.2: 2026-08-31 -> (2026-10-31, 'plan')",
        res5_2 == (dt.datetime(2026, 10, 31, 0, 0, 0, tzinfo=dt.timezone.utc), "plan"),
    )

    res5_3 = AWSProvider._cf_period_start("PAYGO", s5_1, n5)
    ok(
        "scenario 5.3: PAYGO -> (2026-11-01, 'month')",
        res5_3 == (dt.datetime(2026, 11, 1, 0, 0, 0, tzinfo=dt.timezone.utc), "month"),
    )

    # 场景6 套餐，假 CW 精确时间戳
    p6 = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
    p6.cf_list = lambda: [{"id": "E789", "plan": "FREE"}]
    d5 = now - dt.timedelta(days=5)
    target_d = d5.day
    sub_start_6 = None
    for k in (1, 2, 3):
        m_cand = now.month - k
        y_cand = now.year
        while m_cand <= 0:
            m_cand += 12
            y_cand -= 1
        if target_d <= calendar.monthrange(y_cand, m_cand)[1]:
            sub_start_6 = dt.datetime(y_cand, m_cand, target_d, 0, 0, 0, tzinfo=dt.timezone.utc)
            break
    p6._cf_sub_starts = lambda: {"E789": sub_start_6}
    period_start_6, _ = AWSProvider._cf_period_start("FREE", sub_start_6, now)

    dps_down_6 = [
        {"Timestamp": period_start_6 + dt.timedelta(days=1), "Sum": 1000},
        {"Timestamp": period_start_6 - dt.timedelta(days=2), "Sum": 2000},
        {"Timestamp": now - dt.timedelta(days=31), "Sum": 4000},
    ]
    dps_up_6 = [
        {"Timestamp": period_start_6 + dt.timedelta(days=2), "Sum": 100},
        {"Timestamp": period_start_6 - dt.timedelta(days=1), "Sum": 200},
    ]

    class FakeCW6:
        def get_metric_statistics(self, **kw):
            m = kw.get("MetricName")
            if m == "BytesDownloaded":
                return {"Datapoints": dps_down_6}
            elif m == "BytesUploaded":
                return {"Datapoints": dps_up_6}
            return {"Datapoints": []}

    p6.c = lambda *args, **kwargs: FakeCW6()

    res6 = p6.cf_traffic(904)
    e789 = res6.get("items", {}).get("E789", {})

    ok("scenario 6: down == 1000", e789.get("down") == 1000)
    ok("scenario 6: up == 100", e789.get("up") == 100)
    ok("scenario 6: total == 1100", e789.get("total") == 1100)
    ok("scenario 6: total30d == 3300", e789.get("total30d") == 3300)
    ok("scenario 6: pre-period datapoints (2000+200) in total30d not in total", (e789.get("total30d") - e789.get("total")) == 2200)
    ok("scenario 6: 31d-old datapoint (4000) excluded from both total and total30d", e789.get("total30d") == 3300 and e789.get("total") == 1100)

    # 场景7 按量 PAYGO，假 CW 同上法
    p7 = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
    p7.cf_list = lambda: [{"id": "E321", "plan": "PAYGO"}]
    p7._cf_sub_starts = lambda: {}

    period_start_7 = dt.datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    since30_7 = now - dt.timedelta(days=30)

    raw_down_7 = [
        (now - dt.timedelta(days=1), 500),
        (now - dt.timedelta(days=15), 700),
        (now - dt.timedelta(days=32), 900),
    ]
    raw_up_7 = [
        (now - dt.timedelta(days=2), 50),
        (now - dt.timedelta(days=15), 70),
    ]

    exp_down_7 = sum(v for ts, v in raw_down_7 if ts >= period_start_7)
    exp_up_7 = sum(v for ts, v in raw_up_7 if ts >= period_start_7)
    exp_total_7 = exp_down_7 + exp_up_7
    exp_30d_7 = sum(v for ts, v in raw_down_7 if ts >= since30_7) + sum(v for ts, v in raw_up_7 if ts >= since30_7)

    dps_down_7 = [{"Timestamp": ts, "Sum": v} for ts, v in raw_down_7]
    dps_up_7 = [{"Timestamp": ts, "Sum": v} for ts, v in raw_up_7]

    class FakeCW7:
        def get_metric_statistics(self, **kw):
            m = kw.get("MetricName")
            if m == "BytesDownloaded":
                return {"Datapoints": dps_down_7}
            elif m == "BytesUploaded":
                return {"Datapoints": dps_up_7}
            return {"Datapoints": []}

    p7.c = lambda *args, **kwargs: FakeCW7()

    res7 = p7.cf_traffic(905)
    e321 = res7.get("items", {}).get("E321", {})

    ok("scenario 7: down == exp_down", e321.get("down") == exp_down_7)
    ok("scenario 7: up == exp_up", e321.get("up") == exp_up_7)
    ok("scenario 7: total == exp_total", e321.get("total") == exp_total_7)
    ok("scenario 7: total30d == exp_30d", e321.get("total30d") == exp_30d_7)
    ok("scenario 7: period_basis == 'month'", e321.get("period_basis") == "month")
    ok("scenario 7: quota_bytes is None", e321.get("quota_bytes") is None)

passed = sum(1 for _, ok_ in R if ok_)
total = len(R)
print(f"\n{passed}/{total} passed")
sys.exit(0 if passed == total and total > 0 else 1)
