"""实例状态监控：后台守护线程定时巡检。
- 状态异常（运行中 → 停止/终止）时 Telegram 推送告警
- 可选：异常停止后自动提交启动任务
- 可选：IP 连通性检测（ping + TCP 端口），不通时告警；
  开启“自动换 IP”的账号自动提交换 IP 任务（每天最多 3 次）
- 每日定时推送账单汇总报告（可选）
配置：账号表 monitor_alert / monitor_restart / monitor_ip_check /
auto_change_ip；meta: monitor_interval_min / daily_report /
daily_report_hour / daily_report_date；表 ip_change_daily 记录
每个账号当日自动换 IP 次数（跨天清零）。
"""
import datetime
import logging
import threading
import time

from . import db, tg

log = logging.getLogger(__name__)

_state = {"thread": None, "stop": False}
_last_status: dict[tuple[int, str], str] = {}  # (account_id, instance_id) -> status
_last_ip: dict[tuple[int, str], bool] = {}  # (account_id, instance_id) -> IP 是否连通


def _check_once() -> None:
    from . import tasks
    from .providers import get_provider
    for acc in db.account_list_monitored():
        provider = get_provider(acc["provider"])
        try:
            instances = provider.list_instances(acc["creds"])
        except Exception as e:  # noqa: BLE001
            log.warning("monitor list %s failed: %s", acc["name"], e)
            continue
        seen = set()
        for inst in instances:
            key = (acc["id"], inst.id)
            seen.add(key)
            prev, cur = _last_status.get(key), inst.status
            _last_status[key] = cur
            if not prev or prev == cur:
                continue
            name = f"{acc['name']} / {inst.name}"
            if prev == "running" and cur in ("stopped", "terminated", "stopping"):
                if acc["monitor_alert"]:
                    tg.send_message(
                        f"⚠️ <b>实例状态告警</b>\n{name}\n{prev} → {cur}")
                if acc["monitor_restart"] and cur == "stopped":
                    title = f"start / {inst.name}（监控自启）"
                    tasks.submit_action(acc["provider"], acc["id"],
                                        inst.__dict__, "start", {}, title)
                    log.info("monitor auto-restart submitted: %s", name)
            elif prev in ("stopped", "pending") and cur == "running" and acc["monitor_alert"]:
                tg.send_message(f"✅ <b>实例已恢复运行</b>\n{name}")
        for key in [k for k in _last_status if k[0] == acc["id"] and k not in seen]:
            _last_status.pop(key, None)


def _check_ip_once() -> None:
    """IP 连通性定时检测（按账号开关 monitor_ip_check，默认关闭）。

    对每个运行中且有公网 IP 的实例做 ping + TCP 端口探测；
    由“连通”变为“不通”时告警。账号开启 auto_change_ip 时自动
    提交换 IP 任务（每天最多 AUTO_CHANGE_IP_DAILY_LIMIT 次，
    次数记 ip_change_daily 表，跨天清零）；换 IP 失败由任务
    机制发 TG 告警，这里不循环重试。
    """
    from . import tasks
    from .providers import get_provider
    from .ip_check import probe_ip
    today = datetime.date.today().isoformat()
    for acc in db.account_list_ip_checked():
        provider = get_provider(acc["provider"])
        try:
            instances = provider.list_instances(acc["creds"])
        except Exception as e:  # noqa: BLE001
            log.warning("ip monitor list %s failed: %s", acc["name"], e)
            continue
        seen = set()
        for inst in instances:
            key = (acc["id"], inst.id)
            seen.add(key)
            if inst.status != "running" or not inst.public_ip:
                _last_ip.pop(key, None)
                continue
            ok = probe_ip(inst.public_ip)["ok"]
            prev = _last_ip.get(key)
            _last_ip[key] = ok
            if ok:
                if prev is False:
                    tg.send_message(
                        f"✅ <b>实例 IP 已恢复连通</b>\n"
                        f"{acc['name']} / {inst.name}\n"
                        f"公网 IP: {inst.public_ip}")
                continue
            if prev is False:
                # 上次检测已判定不通：已告警/已提交换 IP，不重复处理
                continue
            name = f"{acc['name']} / {inst.name}"
            if acc["auto_change_ip"]:
                used = db.ip_change_daily_count(acc["id"], today)
                if used >= db.AUTO_CHANGE_IP_DAILY_LIMIT:
                    tg.send_message(
                        f"⚠️ <b>实例 IP 不通</b>\n{name}\n"
                        f"公网 IP: {inst.public_ip}\n"
                        f"今日自动换 IP 已达上限"
                        f"（{db.AUTO_CHANGE_IP_DAILY_LIMIT} 次/天），"
                        f"请手动处理")
                    continue
                db.ip_change_daily_inc(acc["id"], today)
                title = f"change_ip / {inst.name}（监控自动换 IP）"
                tasks.submit_action(acc["provider"], acc["id"],
                                    inst.__dict__, "change_ip", {}, title)
                log.info("monitor auto-change-ip submitted: %s", name)
                tg.send_message(
                    f"⚠️ <b>实例 IP 不通，已自动换 IP</b>\n{name}\n"
                    f"公网 IP: {inst.public_ip}\n"
                    f"今日第 {used + 1}/{db.AUTO_CHANGE_IP_DAILY_LIMIT} 次"
                    f"自动换 IP，完成后 Telegram 通知结果")
            else:
                tg.send_message(
                    f"⚠️ <b>实例 IP 不通</b>\n{name}\n"
                    f"公网 IP: {inst.public_ip}")
        for key in [k for k in _last_ip
                    if k[0] == acc["id"] and k not in seen]:
            _last_ip.pop(key, None)


def _daily_report_maybe() -> None:
    if db.meta_get("daily_report") != "1":
        return
    hour = int(db.meta_get("daily_report_hour") or 9)
    today = datetime.date.today().isoformat()
    if db.meta_get("daily_report_date") == today:
        return
    if datetime.datetime.now().hour < hour:
        return
    from .providers import get_provider
    lines = [f"📊 <b>每日账单报告</b>（{today}）"]
    for acc in db.account_list():
        try:
            full = db.account_get(acc["id"])
            p = get_provider(acc["provider"])
            if not p.supports_billing:
                continue
            if acc["provider"] == "aws":
                # AWS 走账单缓存，避免 Cost Explorer 按次收费
                from . import billing as _billing
                b = _billing.get_cached(
                    acc["id"], lambda: p.get_billing(full["creds"]))
            else:
                b = p.get_billing(full["creds"])
            cur = b.get("currency") or ""
            lines.append(f"{acc['provider'].upper()} · {acc['name']}: "
                         f"{cur} {b.get('total', 0):.2f}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"{acc['provider'].upper()} · {acc['name']}: 查询失败")
            log.warning("daily report %s failed: %s", acc["name"], e)
    if len(lines) > 1 and tg.send_message("\n".join(lines)):
        db.meta_set("daily_report_date", today)
    _edu_expiry_maybe()


def _edu_expiry_maybe() -> None:
    """Azure 教育优惠到期提醒：30/7/1 天前各提醒一次（每天最多一次）。"""
    import time as _time
    today = datetime.date.today().isoformat()
    if db.meta_get("edu_remind_date") == today:
        return
    now = _time.time()
    sent = False
    for acc in db.account_list("azure"):
        ts = acc.get("edu_expires_at")
        estimated = False
        if not ts and acc.get("cloud_created_at"):
            ts = acc["cloud_created_at"] + 365 * 86400
            estimated = True
        if not ts:
            continue
        est_tag = "（预估）" if estimated else ""
        days = int((ts - now) / 86400)
        if days < 0:
            msg = (f"🎓 <b>Azure 教育优惠已过期</b>{est_tag}\n"
                   f"账号：{acc['name']}\n"
                   f"到期日：{_fmt_date(ts)}（已过期 {-days} 天）\n"
                   f"请及时续期或升级为即用即付，避免服务被禁用。")
        elif days <= 30:
            # 只在 30/7/1 天这几个节点提醒，避免每天骚扰
            if days not in (30, 29, 7, 6, 1, 0):
                continue
            msg = (f"🎓 <b>Azure 教育优惠即将到期</b>{est_tag}\n"
                   f"账号：{acc['name']}\n"
                   f"到期日：{_fmt_date(ts)}（剩余 {days} 天）\n"
                   f"如仍是学生身份，请及时续期。")
        else:
            continue
        if tg.send_message(msg):
            sent = True
    if sent:
        db.meta_set("edu_remind_date", today)


def _fmt_date(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _loop() -> None:
    log.info("monitor thread started")
    while not _state["stop"]:
        try:
            _check_once()
            _check_ip_once()
            _daily_report_maybe()
        except Exception as e:  # noqa: BLE001
            log.warning("monitor loop error: %s", e)
        interval = max(1, int(db.meta_get("monitor_interval_min") or 5)) * 60
        for _ in range(interval):
            if _state["stop"]:
                break
            time.sleep(1)


def start() -> None:
    if _state["thread"] and _state["thread"].is_alive():
        return
    _state["stop"] = False
    t = threading.Thread(target=_loop, daemon=True, name="monitor")
    _state["thread"] = t
    t.start()
