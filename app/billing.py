"""AWS 账单查询节流：Cost Explorer API 按次收费（$0.01/次），
AWS 账单每月只在 15 号和月末主动查两次，其余时间被动展示缓存。
OCI/Azure 的账单 API 免费，不走缓存。"""
import calendar
import datetime

from . import db


def is_fetch_day() -> bool:
    """今天是否为 AWS 账单查询日（每月 15 号和月末）。"""
    today = datetime.date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.day == 15 or today.day == last_day


def get_cached(account_id: int, fetch_fn):
    """AWS 账单缓存包装。

    fetch_fn 为无参函数，返回最新账单 dict（内部可调 Cost Explorer API）。
    规则：无缓存 → 查一次；查询日且今天没查过 → 查一次；其余 → 直接返回缓存。
    返回的 dict 会带上 "_cache_date"（数据日期，ISO 格式）供前端展示。
    """
    data, fetched_at = db.billing_cache_get(account_id)
    today = datetime.date.today()
    need_fetch = data is None
    if not need_fetch and is_fetch_day():
        need_fetch = datetime.date.fromtimestamp(fetched_at) != today
    if need_fetch:
        data = fetch_fn()
        if isinstance(data, dict):
            data["_cache_date"] = today.isoformat()
        db.billing_cache_set(account_id, data)
    return data
