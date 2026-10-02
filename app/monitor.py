"""实例状态监控：后台守护线程定时巡检。
- 状态异常（运行中 → 停止/终止）时 Telegram 推送告警
- 可选：异常停止后自动提交启动任务
- 每日定时推送账单汇总报告（可选）
配置：账号表 monitor_alert / monitor_restart；meta: monitor_interval_min /
daily_report / daily_report_hour / daily_report_date。
"""
import datetime
import logging
import threading
import time

from . import db, tg

log = logging.getLogger(__name__)

_state = {"thread": None, "stop": False}
_last_status: dict[tuple[int, str], str] = {}  # (account_id, instance_id) -> status


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
            b = p.get_billing(full["creds"])
            cur = b.get("currency") or ""
            lines.append(f"{acc['provider'].upper()} · {acc['name']}: "
                         f"{cur} {b.get('total', 0):.2f}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"{acc['provider'].upper()} · {acc['name']}: 查询失败")
            log.warning("daily report %s failed: %s", acc["name"], e)
    if len(lines) > 1 and tg.send_message("\n".join(lines)):
        db.meta_set("daily_report_date", today)


def _loop() -> None:
    log.info("monitor thread started")
    while not _state["stop"]:
        try:
            _check_once()
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
