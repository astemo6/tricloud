"""Provider 工厂 + 账单（含 AWS 节流缓存，FR-03）。"""
import calendar
import datetime as dt
import importlib
import json
import time
from collections.abc import Mapping
from zoneinfo import ZoneInfo

from . import core

# 三家云 SDK（oci / boto3 / azure-mgmt-*）都很大：用到哪家才导入哪家，没有该云账号就不占内存、不拖慢启动。
_PROVIDER_CLASSES = {"oci": ("oci_provider", "OCIProvider"), "aws": ("aws_provider", "AWSProvider"),
                     "azure": ("azure_provider", "AzureProvider")}


class _LazyProviders(Mapping):
    """provider 名 → Provider 类（首次取值时才 import）。键顺序即 /api/meta 返回的顺序。"""

    def __getitem__(self, name):
        mod, cls = _PROVIDER_CLASSES[name]
        return getattr(importlib.import_module(f".providers.{mod}", __package__), cls)

    def __iter__(self):
        return iter(_PROVIDER_CLASSES)

    def __len__(self):
        return len(_PROVIDER_CLASSES)


PROVIDERS = _LazyProviders()
_cache = {}


def __getattr__(name):
    """兼容旧写法 services.OCIProvider / AWSProvider / AzureProvider（按需导入）。"""
    for prov, (_, cls) in _PROVIDER_CLASSES.items():
        if name == cls:
            return PROVIDERS[prov]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def provider(acc_id, region=None):
    acc = core.get_account(acc_id, with_cred=True)
    if not acc:
        raise KeyError("账号不存在")
    region = region or acc.get("region")
    key = (acc_id, region)
    if key not in _cache:
        _cache[key] = PROVIDERS[acc["provider"]](core.runtime_cred(acc["cred"]), region)
    return _cache[key]


def drop_provider_cache(acc_id):
    for k in [k for k in _cache if k[0] == acc_id]:
        _cache.pop(k, None)
    from . import overview   # 凭证 / 区域变了，总览缓存一起作废
    overview.clear(acc_id)


def tz():
    return ZoneInfo(core.get_setting("timezone", "Asia/Shanghai"))


def now_local():
    return dt.datetime.now(tz())


# ---------------- AWS 节流 ----------------
def is_aws_refresh_day(d: dt.date) -> bool:
    """每月 15 号和月末最后一天。"""
    return d.day == 15 or d.day == calendar.monthrange(d.year, d.month)[1]


def _credits(acc_id):
    return core.q("SELECT * FROM aws_credits WHERE account_id=? ORDER BY start_date", (acc_id,))


def _credit_since(creds):
    return min((c["start_date"] for c in creds if c["start_date"]), default=None)


def _manual_ce_keys(acc_id):
    ym = now_local().strftime("%Y%m")
    return f"ce_manual_used_{acc_id}_{ym}", f"ce_manual_extra_{acc_id}_{ym}"


def _manual_ce_state(acc_id):
    used_key, extra_key = _manual_ce_keys(acc_id)
    used = int(core.get_setting(used_key, 0) or 0)
    extra = int(core.get_setting(extra_key, 0) or 0)
    return {"used": used, "budget": 2 + extra}


def _manual_ce_cost(acc_id):
    """一次手动刷新预计消耗的 CE 调用次数，与 _aws_fetch 的 credit_since 判定同源。"""
    return 2 if _credit_since(_credits(acc_id)) else 1


def billing_add_allowance(acc_id, n):
    """给指定 AWS 账号增加当月手动刷新 CE 调用预算，返回最新已用/上限。"""
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 20:
        raise ValueError("增加次数必须是 1–20 的整数")
    _, extra_key = _manual_ce_keys(acc_id)
    extra = int(core.get_setting(extra_key, 0) or 0)
    core.set_setting(extra_key, extra + n)
    return _manual_ce_state(acc_id)


def _aws_fetch(acc_id):
    creds = _credits(acc_id)
    since = _credit_since(creds)
    data = provider(acc_id).cost_explorer(credit_since=since)
    now = int(time.time())
    core.ex("INSERT OR REPLACE INTO billing_cache(account_id, data, fetched_at) VALUES(?,?,?)",
            (acc_id, json.dumps(data), now))
    # 记录本月 CE 调用次数，便于用户核对费用
    key = f"ce_calls_{now_local():%Y%m}"
    core.set_setting(key, (core.get_setting(key, 0) or 0) + data.get("ce_calls", 1))
    return data, now


def aws_billing(acc_id, force=False, scheduled=False):
    """所有 AWS 账单调用点（Web 账单页 / 回收站估算 / TG Bot / 每日报告）统一走这里。
    - force=True：用户在 Web/App 明确确认付费后手动刷新
    - scheduled=True：仅 15 号/月末且当天尚未拉取时拉取（由定时任务调用）
    - 其他：只读缓存；没有缓存也绝不主动调用 Cost Explorer
    """
    row = core.q("SELECT * FROM billing_cache WHERE account_id=?", (acc_id,), one=True)
    manual_ce = _manual_ce_state(acc_id)
    if force:
        expected = _manual_ce_cost(acc_id)
        if manual_ce["used"] + expected > manual_ce["budget"]:
            raise ValueError(f"本月手动刷新次数已用完（已用 {manual_ce['used']} / 上限 {manual_ce['budget']} 次调用）。"
                             "可在账单页点『增加次数』后再刷新")
    need = bool(force)
    if scheduled and not need and is_aws_refresh_day(now_local().date()):
        need = row is None or dt.datetime.fromtimestamp(row["fetched_at"], tz()).date() != now_local().date()
    if need:
        data, ts = _aws_fetch(acc_id)
        if force:
            used_key, _ = _manual_ce_keys(acc_id)
            manual_ce["used"] += int(data.get("ce_calls", expected))
            core.set_setting(used_key, manual_ce["used"])
    elif row:
        data, ts = json.loads(row["data"]), row["fetched_at"]
    else:
        data, ts = {"period": "-", "currency": "USD", "total": None, "services": [], "credits_used": None}, None
    creds = _credits(acc_id)
    total_credit = sum(c["amount"] or 0 for c in creds)
    used = data.get("credits_used") or 0
    data["credits"] = {"items": creds, "total": round(total_credit, 2), "used": round(used, 2),
                       "remaining": round(total_credit - used, 2)}
    data["cached"] = not need
    data["no_cache"] = ts is None
    data["updated_at"] = dt.datetime.fromtimestamp(ts, tz()).strftime("%Y-%m-%d %H:%M") if ts else "尚无数据"
    data["next_refresh"] = next_aws_refresh_day().isoformat()
    data["ce_calls_this_month"] = core.get_setting(f"ce_calls_{now_local():%Y%m}", 0)
    data["manual_ce"] = manual_ce
    return data


def next_aws_refresh_day():
    d = now_local().date()
    for i in range(0, 40):
        x = d + dt.timedelta(days=i)
        if is_aws_refresh_day(x):
            return x
    return d


def billing(acc_id, force=False):
    acc = core.get_account(acc_id)
    if acc["provider"] == "aws":
        return aws_billing(acc_id, force=force)
    # OCI / Azure 免费，实时查询
    data = provider(acc_id).billing()
    try:   # v1.4：记录本月累计，供 Credit 已用额度估算
        from . import credits
        credits.record_month(acc_id, data)
    except Exception as e:
        print("record billing month failed", acc_id, e, flush=True)
    data["cached"] = False
    data["updated_at"] = now_local().strftime("%Y-%m-%d %H:%M")
    return data


def recycle_estimate(acc_id, region=None):
    """回收站估算（FR-03 调用点之一）：闲置资源走免费 EC2/Lightsail API 实时查；
    账单与 Credit 只读 aws_billing 缓存，绝不触发 Cost Explorer。"""
    data = provider(acc_id, region).recycle_bin()
    b = aws_billing(acc_id)   # 无 force/scheduled → 只读缓存，绝不调用 CE
    remaining = b["credits"]["remaining"] if (b["credits"]["total"] and not b["no_cache"]) else None
    data.update({"billing_updated_at": b["updated_at"], "month_to_date": b["total"], "currency": b.get("currency", "USD"),
                 "credit_remaining": remaining,
                 "credit_months_for_idle": (round(remaining / data["monthly_total"], 1)
                                            if remaining and data["monthly_total"] else None)})
    return data


# ---------------- 统一实例操作 ----------------
def list_instances(acc_id, region=None, kind="vm"):
    p = provider(acc_id, region)
    if kind == "lightsail":
        return p.ls_list()
    return p.list_instances()


def instance_action(acc_id, inst_id, action, region=None, kind="vm", preserve_boot_volume=False):
    p = provider(acc_id, region)
    # 面板主动操作时抑制监控告警
    core.ex("UPDATE monitors SET last_state=? WHERE account_id=? AND instance_id=?",
            (f"user:{action}", acc_id, inst_id))
    from . import overview   # 总览运行数 / 台数下次刷新重查
    overview.invalidate(acc_id, region)
    if kind == "lightsail":
        return p.ls_action(inst_id, action)
    if action == "terminate" and preserve_boot_volume and isinstance(p, PROVIDERS["oci"]):
        return p.action(inst_id, action, preserve_boot_volume=True)
    return p.action(inst_id, action)


def get_state(acc_id, inst_id, region=None, kind="vm"):
    p = provider(acc_id, region)
    if kind == "lightsail":
        return p.c("lightsail").get_instance(instanceName=inst_id)["instance"]["state"]["name"]
    return p.get_state(inst_id)
