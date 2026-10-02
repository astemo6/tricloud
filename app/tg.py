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


async def _cmd_start(update, context):
    if not _allowed(update.effective_chat.id):
        return
    from telegram import InlineKeyboardButton
    await update.message.reply_text(
        "TriCloud 控制面板",
        reply_markup=_kb([
            [InlineKeyboardButton("🖥 实例管理", callback_data="menu:accounts")],
            [InlineKeyboardButton("📋 最近任务", callback_data="menu:jobs")],
        ]))


async def _on_button(update, context):
    from telegram import InlineKeyboardButton
    query = update.callback_query
    if not _allowed(query.message.chat_id):
        await query.answer("未授权", show_alert=True)
        return
    await query.answer()
    data = query.data
    from . import tasks as _tasks
    from .providers import get_provider

    if data == "menu:accounts":
        accs = db.account_list()
        if not accs:
            await query.edit_message_text("还没有添加任何账号，请先在网页面板添加。")
            return
        await query.edit_message_text(
            "选择账号：",
            reply_markup=_kb([[InlineKeyboardButton(
                f"{a['provider'].upper()} · {a['name']}", callback_data=f"acc:{a['id']}")]
                for a in accs]))
        return

    if data == "menu:jobs":
        jobs_ = db.job_list(8)
        lines = ["📋 最近任务："]
        for j in jobs_:
            lines.append(f"{j['status']} · {j['title']}")
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=_kb([[InlineKeyboardButton("🔙 返回", callback_data="menu:start")]]))
        return

    if data == "menu:start":
        await query.edit_message_text(
            "TriCloud 控制面板",
            reply_markup=_kb([
                [InlineKeyboardButton("🖥 实例管理", callback_data="menu:accounts")],
                [InlineKeyboardButton("📋 最近任务", callback_data="menu:jobs")],
            ]))
        return

    if data.startswith("acc:"):
        account_id = int(data[4:])
        acc = db.account_get(account_id)
        if not acc:
            await query.edit_message_text("账号不存在")
            return
        provider = get_provider(acc["provider"])
        await query.edit_message_text("正在获取实例列表…")
        try:
            instances = provider.list_instances(acc["creds"])
        except Exception as e:  # noqa: BLE001
            await query.edit_message_text(f"获取失败: {e}")
            return
        if not instances:
            await query.edit_message_text("该账号下没有实例")
            return
        buttons = []
        for inst in instances:
            d = inst.__dict__
            key = _cache_instance(account_id, d)
            icon = {"running": "🟢", "stopped": "⚪", "pending": "🟡"}.get(d["status"], "❔")
            buttons.append([InlineKeyboardButton(
                f"{icon} {d['name']} ({d['public_ip'] or '无公网IP'})", callback_data=f"i:{key}")])
        buttons.append([InlineKeyboardButton("🔙 账号列表", callback_data="menu:accounts")])
        await query.edit_message_text(f"{acc['name']} 的实例（{len(instances)} 台）：",
                                      reply_markup=_kb(buttons))
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
        text = (f"<b>{inst['name']}</b>\n"
                f"状态: {inst['status']} ({inst.get('status_text', '')})\n"
                f"规格: {inst.get('shape', '')}\n"
                f"公网 IP: {inst.get('public_ip') or '-'}\n"
                f"内网 IP: {inst.get('private_ip') or '-'}\n"
                f"地域: {inst.get('region', '')}")
        buttons = [[InlineKeyboardButton(a["label"], callback_data=f"a:{key}:{a['key']}")]
                   for a in provider.actions if a["key"] != "update_shape"]
        buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"acc:{account_id}")])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=_kb(buttons))
        return

    if data.startswith("a:"):
        _, key, action = data.split(":", 2)
        item = _inst_cache.get(key)
        if not item:
            await query.edit_message_text("实例信息已过期，请重新进入")
            return
        label = {"start": "启动", "stop": "停止", "reboot": "重启",
                 "restart": "重启", "terminate": "终止/删除",
                 "change_ip": "更换公网 IP", "assign_ipv6": "分配 IPv6"}.get(action, action)
        danger = action in ("terminate", "change_ip")
        await query.edit_message_text(
            f"确认为 <b>{item['name']}</b> 执行「{label}」吗？"
            + ("（⚠️ 不可逆）" if danger else ""),
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
        acc = db.account_get(item["account_id"])
        provider = get_provider(acc["provider"])
        label = next((a["label"] for a in provider.actions if a["key"] == action), action)
        title = f"{label} / {item['name']} (TG)"
        _tasks.submit_action(acc["provider"], item["account_id"],
                             item["instance"], action, {}, title)
        await query.edit_message_text(f"任务已提交：{title}\n完成后会推送通知。")
        return


async def _amain(stop_event: asyncio.Event, token: str):
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CallbackQueryHandler(_on_button))
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
