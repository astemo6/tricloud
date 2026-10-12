"""流量守护：按实例设置出站流量上限，到达预警比例推送，到达上限推送并可自动停机。

v1.3：月度模式（本月累计）。
v1.4：
- 滚动窗口模式：统计最近 N 小时的流量，可选出向 / 入向 / 双向；
- 超限停机后可设置「关机 M 小时」，到时自动开机并推送 TG；自动开机失败只推送告警，不循环重试；
- 每条规则可启用 / 停用；显示规则状态（正常 / 已触发关机 + 预计开机时间 / 自动开机失败）。

数据来源都是免费的平台指标：OCI Monitoring、AWS CloudWatch 基础监控 / Lightsail 指标、Azure Monitor。
平台指标有 5~15 分钟延迟，所以上限建议留出余量（默认预警 80%）。
"""
import datetime as dt
import html
import time

from . import core, services
from .providers import greencloud_provider as gcp  # greencloud

# 各家每月免费出站流量（GB），作为新建守护时的默认上限
DEFAULT_LIMIT = {"oci": 10240, "aws": 100, "azure": 100}
CHECK_EVERY = 30 * 60
ROLLING_CHECK_EVERY = 10 * 60      # 滚动窗口更看重及时性
DIRECTIONS = ("out", "in", "both")
DIR_TEXT = {"out": "出站", "in": "入站", "both": "双向"}


def direction_of(g):
    d = g.get("direction")
    if d in DIRECTIONS:
        return d
    return "both" if g.get("count_in") else "out"   # v1.3 规则：count_in=1 等同双向


def usage(g):
    acc = core.get_account(g["account_id"])
    prov = services.provider(g["account_id"], g.get("region"))
    if acc["provider"] == "oci":
        return prov.traffic(g["instance_id"])
    return prov.traffic(g["instance_id"], g.get("kind") or "vm")


def usage_window(g, hours):
    """最近 N 小时流量。"""
    acc = core.get_account(g["account_id"])
    prov = services.provider(g["account_id"], g.get("region"))
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(hours=float(hours))
    if acc["provider"] == "oci":
        return prov.traffic(g["instance_id"], start=start, end=end)
    return prov.traffic(g["instance_id"], g.get("kind") or "vm", start=start, end=end)


def measure(g):
    """按规则的模式和方向算出已用 GB。"""
    if gcp.is_gc(core.get_account(g["account_id"]) or {}):  # greencloud：bw.used，额度同步为 bw.total
        return gcp.guard_measure(g)  # greencloud
    rolling = g.get("mode") == "rolling"
    u = usage_window(g, int(g.get("window_hours") or 24)) if rolling else usage(g)
    out, inn = float(u.get("out_gb") or 0), float(u.get("in_gb") or 0)
    d = direction_of(g)
    return out if d == "out" else inn if d == "in" else out + inn


def scope_text(g):
    if g.get("mode") == "rolling":
        return f"最近 {int(g.get('window_hours') or 24)} 小时{DIR_TEXT[direction_of(g)]}"
    return f"本月{DIR_TEXT[direction_of(g)]}"


def fmt_ts(ts):
    return dt.datetime.fromtimestamp(ts, services.tz()).strftime("%m-%d %H:%M") if ts else "-"


def check(g, act=True):
    """检查一条守护规则。返回需要推送的文本（或 None）。act=False 时只刷新用量不触发停机。"""
    g = dict(g)
    gc = gcp.is_gc(core.get_account(g["account_id"]) or {})  # greencloud：按自己的计费周期清零，跨月不重置提醒等级
    rolling = g.get("mode") == "rolling"
    month = services.now_local().strftime("%Y-%m")
    notified = g["notified"] if (rolling or gc or g.get("month") == month) else 0  # greencloud
    used = measure(g)
    limit = float(g["limit_gb"] or 1)
    pct = used / limit * 100
    lvl = 2 if pct >= 100 else (1 if pct >= int(g.get("warn_pct") or 80) else 0)
    text = None
    name = html.escape(g.get("name") or g["instance_id"][-12:])
    scope = gcp.SCOPE_TEXT if gc else scope_text(g)  # greencloud
    extra = {}
    if act and lvl > notified:
        if lvl == 1:
            text = (f"📈 <b>流量预警</b>：{name}\n{scope}已用 <b>{used:.1f} GB</b> / {limit:g} GB（{pct:.0f}%）"
                    + ("\n到达上限后将自动停机" if g.get("action") == "stop" else ""))
        else:
            text = f"🛑 <b>流量已达上限</b>：{name}\n{scope}已用 <b>{used:.1f} GB</b> / {limit:g} GB"
            if g.get("action") == "stop":
                try:
                    services.instance_action(g["account_id"], g["instance_id"], "stop", g.get("region"), g.get("kind") or "vm")
                    hours = float(g.get("shutdown_hours") or 0)
                    now = int(time.time())
                    if hours > 0:
                        resume = now + int(hours * 3600)
                        extra = {"state": "tripped", "tripped_at": now, "resume_at": resume,
                                 "state_msg": f"超限停机，预计 {fmt_ts(resume)} 自动开机"}
                        text += f"\n已自动停机，将在 {hours:g} 小时后（{fmt_ts(resume)}）自动开机"
                    else:
                        extra = {"state": "tripped", "tripped_at": now, "resume_at": None,
                                 "state_msg": "超限停机（不自动开机）"}
                        text += ("\n已自动停机（不会自动开机，请手动启动）" if rolling or gc  # greencloud
                                 else "\n已自动停机（下月 1 日不会自动开机，请手动启动）")
                except Exception as e:
                    text += f"\n自动停机失败：{html.escape(str(e)[:200])}"
        notified = lvl
    elif lvl < notified:      # 改了上限 / 跨月后回落 / 滚动窗口回落
        notified = lvl
    if lvl < 2 and g.get("state") == "tripped" and not g.get("resume_at") and not extra:
        extra = {"state": "ok", "tripped_at": None, "state_msg": "用量已回落到上限以下"}   # 不自动开机的停机：回落后恢复正常状态
    cols = {"month": month, "notified": notified, "last_gb": round(used, 3), "last_pct": round(pct, 1), "checked_at": int(time.time())}
    cols.update(extra)
    core.ex(f"UPDATE traffic_guards SET {', '.join(k + '=?' for k in cols)} WHERE id=?", (*cols.values(), g["id"]))
    return text


def due():
    """到了检查时间、已启用、且没有在等待自动开机的规则。"""
    now = int(time.time())
    out = []
    for g in core.q("SELECT g.*, a.provider AS _prov FROM traffic_guards g JOIN accounts a ON a.id=g.account_id WHERE COALESCE(a.disabled,0)=0"):
        if gcp.hidden(g.pop("_prov")):  # greencloud
            continue
        if g.get("enabled") == 0 or (g.get("state") == "tripped" and g.get("resume_at")):
            continue   # 停用 / 等待自动开机期间不检查
        every = ROLLING_CHECK_EVERY if g.get("mode") == "rolling" else CHECK_EVERY
        if now - (g["checked_at"] or 0) >= every:
            out.append(g)
    return out


def resume_due():
    """关机 M 小时到期、需要自动开机的规则。"""
    now = int(time.time())
    return [g for g in core.q("SELECT * FROM traffic_guards WHERE state='tripped' AND resume_at IS NOT NULL AND resume_at<=?", (now,))
            if not gcp.hidden((core.get_account(g["account_id"]) or {}).get("provider"))]  # greencloud


def resume(g):
    """到时自动开机：成功 → 状态恢复正常并推送；失败 → 只推送告警，状态记为 resume_failed，不重试。"""
    name = html.escape(g.get("name") or g["instance_id"][-12:])
    try:
        services.instance_action(g["account_id"], g["instance_id"], "start", g.get("region"), g.get("kind") or "vm")
    except Exception as e:
        core.ex("UPDATE traffic_guards SET state='resume_failed', resume_at=NULL, state_msg=? WHERE id=?",
                (f"自动开机失败：{str(e)[:150]}", g["id"]))
        return (f"⚠️ <b>流量守护自动开机失败</b>：{name}\n{html.escape(str(e)[:200])}\n"
                "不会自动重试，请到面板手动启动")
    core.ex("UPDATE traffic_guards SET state='ok', resume_at=NULL, tripped_at=NULL, state_msg=?, checked_at=? WHERE id=?",
            (f"{fmt_ts(int(time.time()))} 已自动开机", int(time.time()), g["id"]))
    return f"✅ <b>流量守护已自动开机</b>：{name}\n关机时长已满 {float(g.get('shutdown_hours') or 0):g} 小时"


def status_of(g):
    """给前端 / App 的规则状态。"""
    if g.get("state") == "tripped":
        return "tripped"
    if g.get("state") == "resume_failed":
        return "resume_failed"
    if g.get("enabled") == 0:
        return "disabled"
    pct = g.get("last_pct") or 0
    return "over" if pct >= 100 else "warn" if pct >= int(g.get("warn_pct") or 80) else "ok"


STATUS_TEXT = {"ok": "正常", "warn": "已到预警", "over": "已超限", "tripped": "已触发关机", "resume_failed": "自动开机失败",
               "disabled": "已停用"}
