"""v1.4 Credit 与教育优惠。

- 手动 Credit：三家云通用（沿用 aws_credits 表），每条含名称、初始额度、起始 / 到期日；
  已用额度按账单估算（先到期的先抵扣），估不出时允许手填（used_manual）。
- Credit 总额：accounts.credit_total，不填则 = 各条额度之和。
- Azure 教育优惠到期日：accounts.edu_expires_at；没填时按云账号创建日期 + 12 个月估算（标明是估算）。
- 30 天内到期：面板提醒 + 推送 TG（30 / 7 / 1 天各推一次）。

账单来源：
- AWS：只读 services.aws_billing 的缓存（Cost Explorer 累计抵扣），不新增任何 CE 调用点；
- OCI / Azure：每次查询账单（免费接口）时把本月累计写入 billing_months，按月累加估算。
"""
import calendar
import datetime as dt
import time

from . import core, services

ALERT_DAYS = 30
NOTIFY_STEPS = (30, 7, 1)


def today():
    return services.now_local().date()


def _date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def age_days(acc):
    d = _date(acc.get("cloud_created_at"))
    return (today() - d).days if d else None


def record_month(acc_id, data):
    """OCI / Azure 账单（免费）查询后记录本月累计，供 Credit 已用额度估算。"""
    try:
        total = float(data.get("total"))
    except (TypeError, ValueError):
        return
    core.ex("INSERT INTO billing_months(account_id, month, total, currency, updated) VALUES(?,?,?,?,?) "
            "ON CONFLICT(account_id, month) DO UPDATE SET total=excluded.total, currency=excluded.currency, updated=excluded.updated",
            (acc_id, services.now_local().strftime("%Y-%m"), total, data.get("currency") or "USD", int(time.time())))


def _billing_used(acc, items):
    """账单估算的累计抵扣（None = 估不出）。返回 (金额, 说明, 更新时间)。"""
    if acc["provider"] == "aws":
        b = services.aws_billing(acc["id"])   # 无 force/scheduled → 只读缓存，绝不调用 CE
        if b.get("no_cache") or b.get("credits_used") is None:
            return None, "暂无 AWS 账单缓存", None
        return float(b.get("credits_used") or 0), "Cost Explorer 累计抵扣（缓存）", b.get("updated_at")
    rows = core.q("SELECT * FROM billing_months WHERE account_id=? ORDER BY month", (acc["id"],))
    if not rows:
        return None, "还没有账单记录（打开一次账单页后开始记录）", None
    starts = [d for d in (_date(c.get("start_date")) for c in items) if d]
    since = min(starts).strftime("%Y-%m") if starts else None
    rows = [r for r in rows if not since or r["month"] >= since]
    if not rows:
        return None, "Credit 起始月之后还没有账单记录", None
    upd = max(r["updated"] for r in rows)
    return (round(sum(r["total"] or 0 for r in rows), 2), f"按月账单累加（{rows[0]['month']} 起，{len(rows)} 个月）",
            dt.datetime.fromtimestamp(upd, services.tz()).strftime("%Y-%m-%d %H:%M"))


def edu_info(acc):
    if acc["provider"] != "azure":
        return None
    d = _date(acc.get("edu_expires_at"))
    estimated, basis = False, "手动填写"
    if not d:
        c = _date(acc.get("cloud_created_at"))
        if not c:
            return {"expires_at": None, "estimated": False, "days_left": None, "basis": "未填写到期日，也没有云账号创建日期，无法估算"}
        d, estimated, basis = add_months(c, 12), True, f"估算：创建日期 {c} + 12 个月"
    return {"expires_at": d.isoformat(), "estimated": estimated, "days_left": (d - today()).days, "basis": basis}


def summary(acc_id):
    acc = core.q("SELECT * FROM accounts WHERE id=?", (acc_id,), one=True)
    if not acc:
        raise KeyError("账号不存在")
    acc.pop("cred_enc", None)
    items = core.q("SELECT * FROM aws_credits WHERE account_id=? ORDER BY COALESCE(expire_date, '9999-12-31'), id", (acc_id,))
    used_bill, note, updated = _billing_used(acc, items)
    # 分摊：手填的优先，其余按到期日先后（先到期的先抵扣）分摊账单估算的累计抵扣
    pool = None if used_bill is None else max(0.0, used_bill - sum(c["used_manual"] or 0 for c in items if c.get("used_manual") is not None))
    out, t = [], today()
    for c in items:
        amt = float(c["amount"] or 0)
        if c.get("used_manual") is not None:
            used, src = float(c["used_manual"]), "manual"
        elif pool is not None:
            used, src = round(min(amt, pool), 2), "billing"
            pool = max(0.0, pool - used)
        else:
            used, src = None, None
        exp = _date(c.get("expire_date"))
        out.append({"id": c["id"], "name": c["name"], "amount": amt, "start_date": c.get("start_date"), "expire_date": c.get("expire_date"),
                    "used": used, "used_manual": c.get("used_manual"), "used_source": src,
                    "remaining": round(amt - used, 2) if used is not None else None,
                    "days_left": (exp - t).days if exp else None, "expired": bool(exp and exp < t)})
    total_manual = acc.get("credit_total") is not None
    total = float(acc["credit_total"]) if total_manual else round(sum(x["amount"] for x in out), 2)
    known = [x["used"] for x in out if x["used"] is not None]
    if out and len(known) == len(out):
        used_total, used_src = round(sum(known), 2), ("manual" if all(x["used_source"] == "manual" for x in out) else "billing")
    elif not out and used_bill is not None and total_manual:
        used_total, used_src = round(used_bill, 2), "billing"
    else:
        used_total, used_src = None, None
    edu = edu_info(acc)
    alerts = [a for a in account_alerts(acc, out, edu)]
    return {"account_id": acc_id, "provider": acc["provider"], "name": acc["name"], "currency": "USD", "items": out,
            "credit_total": total, "credit_total_manual": total_manual, "used": used_total, "used_source": used_src,
            "remaining": round(total - used_total, 2) if used_total is not None else None,
            "billing_used": used_bill, "estimate_note": note, "billing_updated_at": updated,
            "edu": edu, "cloud_created_at": acc.get("cloud_created_at"), "age_days": age_days(acc), "alerts": alerts}


def account_alerts(acc, items, edu, within=ALERT_DAYS):
    out = []
    for c in items:
        d = c.get("days_left")
        if d is not None and 0 <= d <= within:
            out.append({"account_id": acc["id"], "account_name": acc["name"], "provider": acc["provider"], "kind": "credit",
                        "key": f"credit:{c['id']}:{c['expire_date']}", "name": c["name"], "date": c["expire_date"],
                        "days_left": d, "estimated": False})
    if edu and edu.get("days_left") is not None and 0 <= edu["days_left"] <= within:
        out.append({"account_id": acc["id"], "account_name": acc["name"], "provider": acc["provider"], "kind": "edu",
                    "key": f"edu:{acc['id']}:{edu['expires_at']}", "name": "Azure 教育优惠", "date": edu["expires_at"],
                    "days_left": edu["days_left"], "estimated": edu["estimated"]})
    return out


def expiry_alerts(within=ALERT_DAYS):
    """所有账号 30 天内到期的 Credit / 教育优惠（只读数据库，不调云 API）。"""
    out = []
    t = today()
    for acc in core.q("SELECT * FROM accounts ORDER BY provider, id"):
        acc.pop("cred_enc", None)
        items = []
        for c in core.q("SELECT * FROM aws_credits WHERE account_id=? AND expire_date IS NOT NULL", (acc["id"],)):
            exp = _date(c["expire_date"])
            if exp:
                items.append(dict(c, days_left=(exp - t).days))
        out += account_alerts(acc, items, edu_info(acc), within)
    return sorted(out, key=lambda a: a["days_left"])


def alert_line(a):
    when = "今天到期" if a["days_left"] == 0 else f"还剩 {a['days_left']} 天"
    return f"{a['account_name']} · {a['name']}：{a['date']}{'（估算）' if a['estimated'] else ''}，{when}"


def pending_notifications():
    """返回需要推送的提醒（每条在 30 / 7 / 1 天各推一次），并记下已推送的档位。"""
    sent = core.get_setting("expiry_notified", {}) or {}
    texts = []
    live = {}
    for a in expiry_alerts():
        step = min(s for s in NOTIFY_STEPS if a["days_left"] <= s)
        prev = sent.get(a["key"])
        live[a["key"]] = prev if prev is not None else 999
        if prev is None or step < prev:
            texts.append(a)
            live[a["key"]] = step
    core.set_setting("expiry_notified", live)
    return texts
