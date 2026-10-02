"""流量控制：后台巡检流量规则，超限自动关机（deallocate），到期自动开机。

规则见 db.traffic_rules。巡检间隔复用 monitor_interval_min。
"""
import logging
import threading
import time

from . import db, tg

log = logging.getLogger(__name__)

_state = {"thread": None, "stop": False}


def _check_once() -> None:
    from . import tasks
    from .providers import get_provider
    for rule in db.traffic_rule_enabled():
        if rule.get("provider") != "azure":
            continue  # 目前只支持 Azure
        try:
            provider = get_provider("azure")
            gb = provider.get_traffic_gb(
                rule["creds"], rule["instance_key"],
                rule["window_hours"], rule["metric"])
        except Exception as e:  # noqa: BLE001
            log.warning("traffic check rule %s failed: %s", rule["id"], e)
            continue
        name = f"{rule['account_name']} / {rule['instance_name'] or rule['instance_key']}"
        log.info("traffic rule %s: %.2fGB / %.2fGB", rule["id"], gb, rule["limit_gb"])
        if rule["state"] == "normal" and gb >= rule["limit_gb"]:
            # 超限 → 关机
            log.warning("traffic rule %s triggered: %.2fGB", rule["id"], gb)
            db.traffic_rule_update(rule["id"], {
                "state": "triggered", "triggered_at": time.time()})
            try:
                tasks.submit_action(
                    "azure", rule["account_id"],
                    {"id": rule["instance_key"], "name": rule["instance_name"],
                     "extra": {}}, "stop", {},
                    f"stop / {rule['instance_name']}（流量超限自动关机）")
            except Exception as e:  # noqa: BLE001
                log.warning("traffic auto-stop failed: %s", e)
            if rule["notify_trigger"]:
                tg.send_message(
                    f"🚨 <b>流量超限自动关机</b>\n{name}\n"
                    f"规则：{rule['name']}\n"
                    f"过去 {rule['window_hours']} 小时流量 {gb:.2f}GB"
                    f"（阈值 {rule['limit_gb']}GB）\n"
                    f"{rule['duration_hours']} 小时后自动开机")
        elif rule["state"] == "triggered":
            # 检查是否到期恢复
            triggered_at = rule.get("triggered_at") or 0
            if time.time() - triggered_at >= rule["duration_hours"] * 3600:
                log.info("traffic rule %s recovering", rule["id"])
                db.traffic_rule_update(rule["id"], {"state": "normal", "triggered_at": None})
                try:
                    tasks.submit_action(
                        "azure", rule["account_id"],
                        {"id": rule["instance_key"], "name": rule["instance_name"],
                         "extra": {}}, "start", {},
                        f"start / {rule['instance_name']}（流量限制到期自动开机）")
                except Exception as e:  # noqa: BLE001
                    log.warning("traffic auto-start failed: %s", e)
                if rule["notify_recover"]:
                    tg.send_message(
                        f"✅ <b>流量限制到期，已自动开机</b>\n{name}\n"
                        f"规则：{rule['name']}")


def _loop() -> None:
    while not _state["stop"]:
        try:
            _check_once()
        except Exception as e:  # noqa: BLE001
            log.warning("traffic check loop error: %s", e)
        interval = int(db.meta_get("monitor_interval_min") or 5)
        for _ in range(max(1, interval) * 60):
            if _state["stop"]:
                break
            time.sleep(1)


def start() -> None:
    if _state["thread"] and _state["thread"].is_alive():
        return
    _state["stop"] = False
    t = threading.Thread(target=_loop, daemon=True, name="traffic-watch")
    t.start()
    _state["thread"] = t
    log.info("traffic watcher started")
