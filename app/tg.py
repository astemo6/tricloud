"""Telegram 联动：任务完成推送 + Bot 内联按钮操作实例。

配置存在 meta 表：tg_bot_token / tg_chat_id。
推送走 Bot HTTP API（urllib，无额外依赖）；交互 Bot 用 python-telegram-bot，
跑在独立守护线程里，只响应配置的 chat_id。
"""
import asyncio
import json
import logging
import threading
import time
import urllib.parse
import urllib.request

from . import db

log = logging.getLogger(__name__)

_state = {"thread": None, "stop_event": None, "token": None}
_inst_cache: dict[str, dict] = {}  # 短 key -> {account_id, instance, name}


# ---------- 配置与推送 ----------
def get_tg_config() -> tuple[str, str]:
    return db.meta_get("tg_bot_token") or "", db.meta_get("tg_chat_id") or ""


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    token, chat_id = get_tg_config()
    if not token or not chat_id:
        return False
    try:
        data = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:  # noqa: BLE001 - 推送失败只记日志
        log.warning("tg send failed: %s", e)
        return False


def notify_job_finished(job: dict) -> None:
    """任务结束时推送（成功/失败/停止）。在 jobs._run_job 尾部调用。"""
    token, chat_id = get_tg_config()
    if not token or not chat_id:
        return
    status = job.get("status", "")
    icon = {"success": "✅", "failed": "❌", "stopped": "⏹"}.get(status, "ℹ️")
    text = f"{icon} <b>任务{ {'success': '完成', 'failed': '失败', 'stopped': '已停止'}.get(status, status)}</b>\n"
    text += f"{job.get('title', '')}\n"
    result = (job.get("result") or "").strip()
    if result:
        if len(result) > 800:
            result = result[:800] + "…"
        text += f"\n<pre>{result}</pre>"
    send_message(text)


# ---------- 交互 Bot ----------
def _allowed(chat_id: int) -> bool:
    _, want = get_tg_config()
    return str(chat_id) == str(want)


_ACTION_LABELS = {
    "start": "启动", "stop": "停止", "reboot": "重启", "restart": "重启",
    "terminate": "终止/删除", "change_ip": "更换公网 IP", "assign_ipv6": "分配 IPv6",
    "delete_ipv6": "删除 IPv6",
    "rename": "改名", "extend_disk": "磁盘扩容", "open_port": "开放端口",
    "reimage": "重置系统",
}
# 需要用户输入参数的操作：action -> (提示语, params key)
_PARAM_ACTIONS = {
    "rename": ("请直接回复新的实例名称：", "new_name"),
    "extend_disk": ("请直接回复目标磁盘大小（GB，只能调大，例如 100）：", "size_gb"),
    "open_port": ("请直接回复要放行的端口（1-65535，例如 8080）：", "port"),
    "invalidate": ("请直接回复要刷新的路径（每行一个，回复“全部”则刷新 /*）：", "paths"),
}
_DANGER_ACTIONS = {"terminate", "change_ip", "reimage", "extend_disk"}
_pending: dict[int, dict] = {}  # chat_id -> {"kind":..., ...} 等待用户文本输入


class _NullCtx:
    """TG 直调 provider 方法时的空上下文（provider 只用 ctx.log）。"""

    def log(self, message: str) -> None:
        pass
_ls_cache: dict[str, dict] = {}
_cf_cache: dict[str, dict] = {}
_ls_create_cache: dict[str, dict] = {}  # 创建中转：key -> {account_id, name, region, zone, blueprint, bundle}


def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _provider_name(pid: str) -> str:
    return {"oci": "OCI", "aws": "AWS", "azure": "Azure"}.get(pid, pid)


async def _cmd_start(update, context):
    if not _allowed(update.effective_chat.id):
        return
    from telegram import InlineKeyboardButton
    await update.message.reply_text(
        "🤖 TriCloud 控制面板",
        reply_markup=_kb([
            [InlineKeyboardButton("☁️ OCI", callback_data="c:oci"),
             InlineKeyboardButton("☁️ AWS", callback_data="c:aws"),
             InlineKeyboardButton("☁️ Azure", callback_data="c:azure")],
            [InlineKeyboardButton("🔍 一键测活", callback_data="menu:testall"),
             InlineKeyboardButton("📊 每日报告", callback_data="menu:daily")],
            [InlineKeyboardButton("📋 最近任务", callback_data="menu:jobs")],
        ]))


def _main_menu_text():
    return "🤖 TriCloud 控制面板"


def _account_menu(acc):
    from telegram import InlineKeyboardButton
    from .providers import get_provider
    p = get_provider(acc["provider"])
    rows = [[InlineKeyboardButton("🖥️ 实例管理", callback_data=f"am:{acc['id']}:inst")]]
    if p.supports_quotas:
        rows.append([InlineKeyboardButton("📊 配额查询", callback_data=f"am:{acc['id']}:quota")])
    if p.supports_billing:
        rows.append([InlineKeyboardButton("💰 账单查询", callback_data=f"am:{acc['id']}:billing")])
    if p.supports_subscription:
        rows.append([InlineKeyboardButton("📋 订阅信息", callback_data=f"am:{acc['id']}:sub")])
    if getattr(p, "supports_lightsail", False):
        rows.append([InlineKeyboardButton("💡 Lightsail", callback_data=f"am:{acc['id']}:ls")])
    if getattr(p, "supports_cloudfront", False):
        rows.append([InlineKeyboardButton("☁️ CloudFront", callback_data=f"am:{acc['id']}:cf")])
    rows.append([InlineKeyboardButton("🔔 监控设置", callback_data=f"am:{acc['id']}:mon")])
    rows.append([InlineKeyboardButton("🔙 主菜单", callback_data="menu:start")])
    return (f"<b>{_esc(acc['name'])}</b>（{_provider_name(acc['provider'])}）\n请选择功能：",
            _kb(rows))


def _fmt_billing(b: dict) -> str:
    cur = b.get("currency") or ""
    lines = [f"💰 <b>账单</b>（{ _esc(b.get('period', '')) }）",
             f"总计：<b>{cur} {b.get('total', 0):.2f}</b>"]
    for s in (b.get("services") or [])[:10]:
        lines.append(f"· {_esc(s['name'])}: {cur} {s['cost']:.2f}")
    if b.get("note"):
        lines.append(f"<i>{_esc(b['note'])}</i>")
    return "\n".join(lines)


def _fmt_quotas(q: dict) -> str:
    lines = ["📊 <b>配额查询</b>"]
    for g in q.get("groups") or []:
        lines.append(f"\n<b>{_esc(g.get('title', ''))}</b>")
        for it in (g.get("items") or [])[:15]:
            lines.append(f"· {_esc(it['name'])}: {_esc(it['detail'])}")
    if q.get("note"):
        lines.append(f"\n<i>{_esc(q['note'])}</i>")
    text = "\n".join(lines)
    return text[:3800]


async def _on_text(update, context):
    chat_id = update.effective_chat.id
    if not _allowed(chat_id):
        return
    pend = _pending.pop(chat_id, None)
    if not pend:
        return
    from telegram import InlineKeyboardButton
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("输入为空，已取消。")
        return
    kind = pend["kind"]
    if kind == "param":
        action, pkey = pend["action"], pend["pkey"]
        if pkey in ("size_gb", "port") and not text.isdigit():
            await update.message.reply_text("请输入数字，已取消。")
            return
        if pkey == "port" and not (1 <= int(text) <= 65535):
            await update.message.reply_text("端口范围 1-65535，已取消。")
            return
        _pending[chat_id] = {"kind": "confirm", "key": pend["key"],
                             "action": action, "param": {pkey: text}}
        label = _ACTION_LABELS.get(action, action)
        await update.message.reply_text(
            f"确认为 <b>{_esc(pend['name'])}</b> 执行「{label}」（参数：{_esc(text)}）吗？"
            + ("（⚠️ 不可逆）" if action in _DANGER_ACTIONS else ""),
            parse_mode="HTML",
            reply_markup=_kb([
                [InlineKeyboardButton("✅ 确认执行",
                                     callback_data=f"g:{pend['key']}:{action}")],
                [InlineKeyboardButton("取消", callback_data=f"i:{pend['key']}")],
            ]))
        return
    if kind == "invalidate":
        paths = ["/*"] if text in ("全部", "all", "*") else \
            [l if l.startswith("/") else "/" + l for l in text.splitlines() if l.strip()]
        item = _cf_cache.get(pend["key"])
        if not item:
            await update.message.reply_text("信息已过期，请重新进入。")
            return
        from .providers import get_provider
        acc = db.account_get(item["account_id"])
        try:
            msg = get_provider("aws").cloudfront_invalidate(
                acc["creds"], item["dist_id"], paths)
            await update.message.reply_text(f"✅ {msg}")
        except Exception as e:  # noqa: BLE001
            await update.message.reply_text(f"❌ 刷新失败: {e}")
        return
    if kind == "cf_create":
        acc = db.account_get(pend["account_id"])
        try:
            msg = get_provider("aws").create_distribution(
                acc["creds"], text, "", "100")
            await update.message.reply_text(f"✅ {msg}")
        except Exception as e:  # noqa: BLE001
            await update.message.reply_text(f"❌ 创建失败: {e}")
        return
    if kind == "ls_create_name":
        name = text.strip()
        if not name or len(name) > 30:
            await update.message.reply_text("名称无效（1-30 个字符），已取消。")
            return
        key = f"n{len(_ls_create_cache) % 9000 + 1}"
        _ls_create_cache[key] = {"account_id": pend["account_id"], "name": name}
        regions = get_provider("aws").LIGHTSAIL_REGIONS
        buttons = [[InlineKeyboardButton(r, callback_data=f"lsr:{key}:{r}")]
                   for r in regions]
        await update.message.reply_text(
            f"实例名：<b>{_esc(name)}</b>\n请选择区域：",
            parse_mode="HTML", reply_markup=_kb(buttons))
        return
    if kind == "daily_hour":
        if not text.isdigit() or not (0 <= int(text) <= 23):
            await update.message.reply_text("请输入 0-23 的小时数，已取消。")
            return
        db.meta_set("daily_report_hour", text)
        await update.message.reply_text(f"每日报告时间已设为 {text}:00。")
        return


def _cache_instance(account_id: int, inst: dict) -> str:
    key = f"k{len(_inst_cache) % 9000 + 1}"
    _inst_cache[key] = {"account_id": account_id, "instance": inst,
                        "name": inst.get("name", "?"), "ts": time.time()}
    # 简单淘汰
    if len(_inst_cache) > 200:
        old = sorted(_inst_cache, key=lambda k: _inst_cache[k]["ts"])[:50]
        for k in old:
            _inst_cache.pop(k, None)
    return key


def _kb(buttons):
    from telegram import InlineKeyboardMarkup
    return InlineKeyboardMarkup(buttons)


async def _on_button(update, context):
    from telegram import InlineKeyboardButton
    query = update.callback_query
    if not _allowed(query.message.chat_id):
        await query.answer("未授权", show_alert=True)
        return
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    from . import tasks as _tasks
    from .providers import get_provider

    def _back_main():
        return [[InlineKeyboardButton("🔙 主菜单", callback_data="menu:start")]]

    if data == "menu:start":
        await query.edit_message_text(
            _main_menu_text(),
            reply_markup=_kb([
                [InlineKeyboardButton("☁️ OCI", callback_data="c:oci"),
                 InlineKeyboardButton("☁️ AWS", callback_data="c:aws"),
                 InlineKeyboardButton("☁️ Azure", callback_data="c:azure")],
                [InlineKeyboardButton("🔍 一键测活", callback_data="menu:testall"),
                 InlineKeyboardButton("📊 每日报告", callback_data="menu:daily")],
                [InlineKeyboardButton("📋 最近任务", callback_data="menu:jobs")],
            ]))
        return

    if data == "menu:jobs":
        jobs_ = db.job_list(8)
        lines = ["📋 最近任务："]
        for j in jobs_:
            lines.append(f"{j['status']} · {j['title']}")
        await query.edit_message_text("\n".join(lines), reply_markup=_kb(_back_main()))
        return

    if data == "menu:testall":
        await query.edit_message_text("🔍 测活中…")
        lines = ["🔍 <b>一键测活</b>"]
        for acc in db.account_list():
            try:
                full = db.account_get(acc["id"])
                get_provider(acc["provider"]).test(full["creds"])
                lines.append(f"✅ {_esc(acc['name'])}（{_provider_name(acc['provider'])}）")
            except Exception as e:  # noqa: BLE001
                lines.append(f"❌ {_esc(acc['name'])}: {_esc(str(e)[:80])}")
        await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                      reply_markup=_kb(_back_main()))
        return

    if data == "menu:daily":
        enabled = db.meta_get("daily_report") == "1"
        hour = db.meta_get("daily_report_hour") or "9"
        await query.edit_message_text(
            f"📊 <b>每日账单报告</b>\n状态：{'✅ 开启' if enabled else '⚪ 关闭'}\n"
            f"推送时间：{hour}:00",
            parse_mode="HTML",
            reply_markup=_kb([
                [InlineKeyboardButton("✅ 开启" if not enabled else "⚪ 关闭",
                                     callback_data="daily:toggle")],
                [InlineKeyboardButton("🕘 设置时间", callback_data="daily:hour")],
                [InlineKeyboardButton("🔙 主菜单", callback_data="menu:start")],
            ]))
        return

    if data == "daily:toggle":
        cur = db.meta_get("daily_report") == "1"
        db.meta_set("daily_report", "0" if cur else "1")
        await query.edit_message_text(
            f"每日报告已{'关闭' if cur else '开启'}。",
            reply_markup=_kb(_back_main()))
        return

    if data == "daily:hour":
        _pending[chat_id] = {"kind": "daily_hour"}
        await query.edit_message_text("请直接回复推送小时（0-23，例如 9）：")
        return

    if data.startswith("c:"):
        pid = data[2:]
        accs = db.account_list(pid)
        if not accs:
            await query.edit_message_text(
                f"{_provider_name(pid)} 还没有账号，请先在网页面板添加。",
                reply_markup=_kb(_back_main()))
            return
        await query.edit_message_text(
            f"选择{_provider_name(pid)}账号：",
            reply_markup=_kb(
                [[InlineKeyboardButton(a["name"], callback_data=f"acc:{a['id']}")]
                 for a in accs] + _back_main()))
        return

    if data.startswith("acc:"):
        acc = db.account_get(int(data[4:]))
        if not acc:
            await query.edit_message_text("账号不存在")
            return
        text, kb = _account_menu(acc)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data.startswith("am:"):
        _, aid, tab = data.split(":", 2)
        acc = db.account_get(int(aid))
        if not acc:
            await query.edit_message_text("账号不存在")
            return
        provider = get_provider(acc["provider"])
        back = [[InlineKeyboardButton("🔙 返回", callback_data=f"acc:{aid}")]]

        if tab == "inst":
            await query.edit_message_text("正在获取实例列表…")
            try:
                instances = provider.list_instances(acc["creds"])
            except Exception as e:  # noqa: BLE001
                await query.edit_message_text(f"获取失败: {e}", reply_markup=_kb(back))
                return
            if not instances:
                await query.edit_message_text("该账号下没有实例", reply_markup=_kb(back))
                return
            buttons = []
            for inst in instances:
                d = inst.__dict__
                key = _cache_instance(int(aid), d)
                icon = {"running": "🟢", "stopped": "⚪", "pending": "🟡"}.get(
                    d["status"], "❔")
                buttons.append([InlineKeyboardButton(
                    f"{icon} {d['name']} ({d['public_ip'] or '无公网IP'})",
                    callback_data=f"i:{key}")])
            buttons += back
            await query.edit_message_text(
                f"{acc['name']} 的实例（{len(instances)} 台）：", reply_markup=_kb(buttons))
            return

        if tab in ("quota", "billing", "sub"):
            await query.edit_message_text("查询中…")
            try:
                if tab == "quota":
                    text = _fmt_quotas(provider.get_quotas(acc["creds"]))
                elif tab == "billing":
                    text = _fmt_billing(provider.get_billing(acc["creds"]))
                else:
                    s = provider.get_subscription(acc["creds"])
                    text = "📋 <b>订阅信息</b>\n" + "\n".join(
                        f"· {_esc(i['name'])}: {_esc(i['detail'])}" for i in s["items"])
                    if s.get("note"):
                        text += f"\n<i>{_esc(s['note'])}</i>"
            except Exception as e:  # noqa: BLE001
                text = f"❌ 查询失败: {_esc(str(e)[:300])}"
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=_kb(back))
            return

        if tab == "mon":
            m = db.account_get(int(aid))
            await query.edit_message_text(
                f"🔔 <b>监控设置</b> · {_esc(acc['name'])}\n"
                f"状态告警：{'✅ 开' if m.get('monitor_alert') else '⚪ 关'}\n"
                f"异常自启：{'✅ 开' if m.get('monitor_restart') else '⚪ 关'}",
                parse_mode="HTML",
                reply_markup=_kb([
                    [InlineKeyboardButton("切换状态告警", callback_data=f"mon:{aid}:alert"),
                     InlineKeyboardButton("切换异常自启", callback_data=f"mon:{aid}:restart")],
                    [InlineKeyboardButton("🔙 返回", callback_data=f"acc:{aid}")],
                ]))
            return

        if tab == "ls":
            await query.edit_message_text("正在获取 Lightsail 实例…")
            try:
                items = provider.list_lightsail(acc["creds"], "")
            except Exception as e:  # noqa: BLE001
                await query.edit_message_text(f"获取失败: {e}", reply_markup=_kb(back))
                return
            if not items:
                await query.edit_message_text(
                    "没有 Lightsail 实例",
                    reply_markup=_kb(
                        [[InlineKeyboardButton("➕ 创建实例",
                                              callback_data=f"lsc:{aid}")]] + back))
                return
            buttons = []
            for it in items:
                key = f"l{len(_ls_cache) % 9000 + 1}"
                _ls_cache[key] = {"account_id": int(aid), "region": it["region"],
                                  "name": it["name"], "state": it.get("state", "")}
                icon = "🟢" if it["state"] == "running" else "⚪"
                buttons.append([InlineKeyboardButton(
                    f"{icon} {it['name']} ({it['region']})", callback_data=f"ls:{key}")])
            buttons.append([InlineKeyboardButton("➕ 创建实例",
                                                callback_data=f"lsc:{aid}")])
            buttons += back
            await query.edit_message_text(
                f"Lightsail 实例（{len(items)} 台）：", reply_markup=_kb(buttons))
            return

        if tab == "cf":
            await query.edit_message_text("正在获取 CloudFront 分发…")
            try:
                items = provider.list_cloudfront(acc["creds"])
            except Exception as e:  # noqa: BLE001
                await query.edit_message_text(f"获取失败: {e}", reply_markup=_kb(back))
                return
            if not items:
                await query.edit_message_text(
                    "没有 CloudFront 分发",
                    reply_markup=_kb(
                        [[InlineKeyboardButton("➕ 创建分发",
                                              callback_data=f"cfc:{aid}")]] + back))
                return
            buttons = []
            for d in items:
                key = f"c{len(_cf_cache) % 9000 + 1}"
                _cf_cache[key] = {"account_id": int(aid), "dist_id": d["id"],
                                  "enabled": bool(d.get("enabled"))}
                icon = "🟢" if d["enabled"] else "⚪"
                label = (d["aliases"][0] if d["aliases"] else d["domain"])[:28]
                buttons.append([InlineKeyboardButton(
                    f"{icon} {label}", callback_data=f"cf:{key}")])
            buttons.append([InlineKeyboardButton("➕ 创建分发",
                                                callback_data=f"cfc:{aid}")])
            buttons += back
            await query.edit_message_text(
                f"CloudFront 分发（{len(items)} 个）：", reply_markup=_kb(buttons))
            return
        return

    if data.startswith("mon:"):
        _, aid, which = data.split(":", 2)
        acc = db.account_get(int(aid))
        alert = bool(acc.get("monitor_alert"))
        restart = bool(acc.get("monitor_restart"))
        if which == "alert":
            alert = not alert
        else:
            restart = not restart
        db.account_set_monitor(int(aid), alert, restart)
        await query.edit_message_text(
            f"🔔 <b>监控设置</b> · {_esc(acc['name'])}\n"
            f"状态告警：{'✅ 开' if alert else '⚪ 关'}\n"
            f"异常自启：{'✅ 开' if restart else '⚪ 关'}",
            parse_mode="HTML",
            reply_markup=_kb([
                [InlineKeyboardButton("切换状态告警", callback_data=f"mon:{aid}:alert"),
                 InlineKeyboardButton("切换异常自启", callback_data=f"mon:{aid}:restart")],
                [InlineKeyboardButton("🔙 返回", callback_data=f"acc:{aid}")],
            ]))
        return

    if data.startswith("ls:"):
        key = data[3:]
        item = _ls_cache.get(key)
        if not item:
            await query.edit_message_text("信息已过期，请重新进入")
            return
        st = item.get("state", "")
        rows = []
        if st == "running":
            rows.append([InlineKeyboardButton("🔄 重启", callback_data=f"lg:{key}:reboot"),
                         InlineKeyboardButton("⏹ 停止", callback_data=f"lg:{key}:stop")])
        else:
            rows.append([InlineKeyboardButton("▶️ 启动", callback_data=f"lg:{key}:start")])
        rows.append([InlineKeyboardButton("🔙 返回",
                                         callback_data=f"am:{item['account_id']}:ls")])
        await query.edit_message_text(
            f"💡 <b>{_esc(item['name'])}</b>（{item['region']}）",
            parse_mode="HTML", reply_markup=_kb(rows))
        return

    if data.startswith("lg:"):
        _, key, action = data.split(":", 2)
        item = _ls_cache.get(key)
        if not item:
            await query.edit_message_text("信息已过期，请重新进入")
            return
        if action == "stop":
            await query.edit_message_text(
                f"确定停止 Lightsail 实例 <b>{_esc(item['name'])}</b> 吗？",
                parse_mode="HTML",
                reply_markup=_kb([
                    [InlineKeyboardButton("✅ 确认", callback_data=f"lx:{key}:stop")],
                    [InlineKeyboardButton("取消", callback_data=f"ls:{key}")],
                ]))
            return
        acc = db.account_get(item["account_id"])
        try:
            msg = get_provider("aws").lightsail_action(
                acc["creds"], item["name"], action, item["region"])
            await query.edit_message_text(f"✅ {msg}")
        except Exception as e:  # noqa: BLE001
            await query.edit_message_text(f"❌ 操作失败: {e}")
        return

    if data.startswith("lx:"):
        _, key, action = data.split(":", 2)
        item = _ls_cache.get(key)
        if not item:
            await query.edit_message_text("信息已过期，请重新进入")
            return
        acc = db.account_get(item["account_id"])
        try:
            msg = get_provider("aws").lightsail_action(
                acc["creds"], item["name"], action, item["region"])
            await query.edit_message_text(f"✅ {msg}")
        except Exception as e:  # noqa: BLE001
            await query.edit_message_text(f"❌ 操作失败: {e}")
        return

    if data.startswith("cf:"):
        key = data[3:]
        item = _cf_cache.get(key)
        if not item:
            await query.edit_message_text("信息已过期，请重新进入")
            return
        acc = db.account_get(item["account_id"])
        await query.edit_message_text(
            f"☁️ <b>{_esc(item['dist_id'])}</b>",
            parse_mode="HTML",
            reply_markup=_kb([
                [InlineKeyboardButton("🧹 刷新缓存", callback_data=f"cfi:{key}")],
                [InlineKeyboardButton("⏸️ 停用" if item.get("enabled", True) else "▶️ 启用",
                                     callback_data=f"cft:{key}")],
                [InlineKeyboardButton("🔙 返回",
                                     callback_data=f"am:{item['account_id']}:cf")],
            ]))
        return

    if data.startswith("cfi:"):
        key = data[4:]
        _pending[chat_id] = {"kind": "invalidate", "key": key}
        await query.edit_message_text(
            "请直接回复要刷新的路径（每行一个；回复“全部”则刷新 /*）：")
        return

    if data.startswith("cft:"):
        key = data[4:]
        item = _cf_cache.get(key)
        if not item:
            await query.edit_message_text("信息已过期，请重新进入")
            return
        acc = db.account_get(item["account_id"])
        to_enable = not item.get("enabled", True)
        await query.edit_message_text(
            f"确定{'启用' if to_enable else '停用'}分发 <b>{_esc(item['dist_id'])}</b> 吗？",
            parse_mode="HTML",
            reply_markup=_kb([
                [InlineKeyboardButton("✅ 确认",
                                     callback_data=f"cfx:{key}:{1 if to_enable else 0}")],
                [InlineKeyboardButton("取消", callback_data=f"cf:{key}")],
            ]))
        return

    if data.startswith("cfx:"):
        _, key, flag = data.split(":", 2)
        item = _cf_cache.get(key)
        if not item:
            await query.edit_message_text("信息已过期，请重新进入")
            return
        acc = db.account_get(item["account_id"])
        try:
            msg = get_provider("aws").cloudfront_toggle(
                acc["creds"], item["dist_id"], flag == "1")
            item["enabled"] = flag == "1"
            await query.edit_message_text(f"✅ {msg}")
        except Exception as e:  # noqa: BLE001
            await query.edit_message_text(f"❌ 操作失败: {e}")
        return

    if data.startswith("cfc:"):
        aid = data[4:]
        _pending[chat_id] = {"kind": "cf_create", "account_id": int(aid)}
        await query.edit_message_text(
            "请直接回复源站域名（例如 example.com，不带 https://）：\n"
            "将按默认配置创建：回源 HTTP、访客侧 HTTP 跳 HTTPS、价格等级 100（北美+欧洲）。")
        return

    if data.startswith("lsc:"):
        aid = data[4:]
        _pending[chat_id] = {"kind": "ls_create_name", "account_id": int(aid)}
        await query.edit_message_text(
            "请直接回复实例名称（字母、数字、横线，例如 web-1）：")
        return

    if data.startswith("lsr:"):
        _, key, region = data.split(":", 2)
        item = _ls_create_cache.get(key)
        if not item:
            await query.edit_message_text("信息已过期，请重新进入")
            return
        acc = db.account_get(item["account_id"])
        await query.edit_message_text("正在获取该区域的镜像和套餐…")
        try:
            opts = get_provider("aws").get_lightsail_options(acc["creds"], region)
        except Exception as e:  # noqa: BLE001
            await query.edit_message_text(f"❌ 获取失败: {e}")
            return
        if not opts["zones"] or not opts["blueprints"] or not opts["bundles"]:
            await query.edit_message_text("❌ 该区域无可用镜像/套餐，请换区域重试")
            return
        bp = next((b for b in opts["blueprints"] if "ubuntu" in b["id"].lower()),
                  opts["blueprints"][0])
        item.update({"region": region, "zone": opts["zones"][0],
                     "blueprint": bp["id"], "bundle": opts["bundles"][0]["id"],
                     "blueprint_name": bp["name"],
                     "bundle_name": opts["bundles"][0]["name"]})
        await query.edit_message_text(
            f"🆕 <b>确认创建 Lightsail 实例</b>\n"
            f"名称：{_esc(item['name'])}\n"
            f"区域：{_esc(region)} / {_esc(item['zone'])}\n"
            f"镜像：{_esc(item['blueprint_name'])}\n"
            f"套餐：{_esc(item['bundle_name'])}\n"
            f"（TG 端使用默认选项，更多组合请用 Web 端）",
            parse_mode="HTML",
            reply_markup=_kb([
                [InlineKeyboardButton("✅ 确认创建", callback_data=f"lsx:{key}")],
                [InlineKeyboardButton("取消",
                                     callback_data=f"am:{item['account_id']}:ls")],
            ]))
        return

    if data.startswith("lsx:"):
        key = data[4:]
        item = _ls_create_cache.get(key)
        if not item:
            await query.edit_message_text("信息已过期，请重新进入")
            return
        acc = db.account_get(item["account_id"])
        try:
            msg = get_provider("aws").create_lightsail_instance(
                acc["creds"], item, _NullCtx())
            _ls_create_cache.pop(key, None)
            await query.edit_message_text(f"✅ {msg}")
        except Exception as e:  # noqa: BLE001
            await query.edit_message_text(f"❌ 创建失败: {e}")
        return

    if data.startswith("i:"):
        key = data[2:]
        item = _inst_cache.get(key)
        if not item:
            await query.edit_message_text("实例信息已过期，请重新进入")
            return
        inst, account_id = item["instance"], item["account_id"]
        acc = db.account_get(account_id)
        provider = get_provider(acc["provider"])
        text = (f"<b>{_esc(inst['name'])}</b>\n"
                f"状态: {inst['status']} ({inst.get('status_text', '')})\n"
                f"规格: {_esc(inst.get('shape', ''))}\n"
                f"公网 IP: {_esc(inst.get('public_ip') or '-')}\n"
                f"内网 IP: {_esc(inst.get('private_ip') or '-')}\n"
                f"地域: {_esc(inst.get('region', ''))}")
        buttons = [[InlineKeyboardButton(a["label"], callback_data=f"a:{key}:{a['key']}")]
                   for a in provider.actions if a["key"] != "update_shape"]
        buttons.append([InlineKeyboardButton("🔙 返回",
                                             callback_data=f"am:{account_id}:inst")])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=_kb(buttons))
        return

    if data.startswith("a:"):
        _, key, action = data.split(":", 2)
        item = _inst_cache.get(key)
        if not item:
            await query.edit_message_text("实例信息已过期，请重新进入")
            return
        if action in _PARAM_ACTIONS:
            prompt, pkey = _PARAM_ACTIONS[action]
            _pending[chat_id] = {"kind": "param", "key": key, "action": action,
                                 "pkey": pkey, "name": item["name"]}
            await query.edit_message_text(prompt)
            return
        label = _ACTION_LABELS.get(action, action)
        await query.edit_message_text(
            f"确认为 <b>{_esc(item['name'])}</b> 执行「{label}」吗？"
            + ("（⚠️ 不可逆）" if action in _DANGER_ACTIONS else ""),
            parse_mode="HTML",
            reply_markup=_kb([
                [InlineKeyboardButton("✅ 确认执行", callback_data=f"g:{key}:{action}")],
                [InlineKeyboardButton("取消", callback_data=f"i:{key}")],
            ]))
        return

    if data.startswith("g:"):
        _, key, action = data.split(":", 2)
        item = _inst_cache.get(key)
        if not item:
            await query.edit_message_text("实例信息已过期，请重新进入")
            return
        pend = _pending.pop(chat_id, None)
        params = {}
        if pend and pend.get("kind") == "confirm" and pend.get("key") == key \
                and pend.get("action") == action:
            params = pend.get("param", {})
        acc = db.account_get(item["account_id"])
        provider = get_provider(acc["provider"])
        label = next((a["label"] for a in provider.actions if a["key"] == action),
                     _ACTION_LABELS.get(action, action))
        title = f"{label} / {item['name']} (TG)"
        _tasks.submit_action(acc["provider"], item["account_id"],
                             item["instance"], action, params, title)
        await query.edit_message_text(f"任务已提交：{title}\n完成后会推送通知。")
        return



async def _amain(stop_event: asyncio.Event, token: str):
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CallbackQueryHandler(_on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_text))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    log.info("tg bot started")
    try:
        await stop_event.wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        log.info("tg bot stopped")


def _thread_main(token: str, stop_event: asyncio.Event):
    try:
        asyncio.run(_amain(stop_event, token))
    except Exception as e:  # noqa: BLE001
        log.warning("tg bot thread exited: %s", e)


def refresh_bot() -> dict:
    """根据当前配置启动/重启/停止 Bot。返回状态。"""
    token, chat_id = get_tg_config()
    if _state["thread"] and _state["thread"].is_alive():
        if _state["token"] == token and token:
            return {"running": True, "chat_id": chat_id}
        _state["stop_event"].set()
        _state["thread"].join(timeout=10)
        _state["thread"] = None
    if not token:
        _state["token"] = None
        return {"running": False}
    stop_event = asyncio.Event()
    t = threading.Thread(target=_thread_main, args=(token, stop_event),
                         daemon=True, name="tg-bot")
    _state.update(thread=t, stop_event=stop_event, token=token)
    t.start()
    return {"running": True, "chat_id": chat_id}
