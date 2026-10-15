"""Telegram 通知 + Bot 交互（FR-04）。只响应配置的 chat_id。长轮询，无需公网 webhook。"""
import asyncio
import secrets
import time

import httpx

from . import core, net, services

_cb = {}   # 短 key -> payload（callback_data 限 64 字节）
STATE_ICON = {"running": "🟢", "stopped": "🔴", "deallocated": "🔴", "stopping": "🟡", "starting": "🟡",
              "pending": "🟡", "provisioning": "🟡"}
ACTION_NAME = {"start": "启动", "stop": "停止", "reboot": "重启", "changeip": "换 IP", "terminate": "终止", "ipv6": "加 IPv6"}


def cfg():
    return core.get_secret_setting("tg_token"), str(core.get_setting("tg_chat_id", "") or "")


def _api(token, method):
    return f"https://api.telegram.org/bot{token}/{method}"


async def send(text, markup=None, token=None, chat_id=None):
    t, c = cfg()
    token, chat_id = token or t, chat_id or c
    if not token or not chat_id:
        return False
    body = {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        body["reply_markup"] = markup
    try:
        async with httpx.AsyncClient(timeout=20) as cl:
            r = await cl.post(_api(token, "sendMessage"), json=body)
            return r.json().get("ok", False)
    except Exception:
        return False


def notify(text):
    """线程中可调用的同步通知。"""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(send(text))
    except RuntimeError:
        asyncio.run(send(text))


def _key(payload):
    k = secrets.token_hex(4)
    _cb[k] = (payload, time.time())
    if len(_cb) > 2000:
        for kk in sorted(_cb, key=lambda x: _cb[x][1])[:1000]:
            _cb.pop(kk, None)
    return k


def _kb(rows):
    return {"inline_keyboard": [[{"text": t, "callback_data": _key(p)} for t, p in row] for row in rows]}


def esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class HttpBot:
    """Bot API 的最小封装；测试里换成记录调用的假 Bot。"""
    def __init__(self, cl, token):
        self.cl, self.token = cl, token

    async def call(self, method, body):
        r = await self.cl.post(_api(self.token, method), json=body)
        try:
            return r.json()
        except Exception:
            return {}


async def _edit(bot, chat_id, msg_id, text, markup=None):
    """编辑按钮所在的消息；消息过旧等原因编辑失败时改为发新消息。"""
    body = {"chat_id": chat_id, "message_id": msg_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        body["reply_markup"] = markup
    r = await bot.call("editMessageText", body)
    if isinstance(r, dict) and r.get("ok") is False and "not modified" not in str(r.get("description", "")):
        body.pop("message_id")
        await bot.call("sendMessage", body)


async def _reply(bot, chat_id, text, markup=None):
    body = {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        body["reply_markup"] = markup
    await bot.call("sendMessage", body)


PROV_NAME = {"oci": "Oracle Cloud", "aws": "AWS", "azure": "Azure"}
# 危险操作：确认页加醒目警告（所有实例操作都要点「确认」按钮才执行）
DANGER = {"terminate": "⚠️ 终止后实例和引导卷/磁盘一并删除，不可恢复！",
          "stop": "⚠️ 停机后服务中断（Azure 为释放，动态公网 IP 会变）。",
          "changeip": "⚠️ 换 IP 期间网络中断，旧 IP 释放后无法找回。",
          "delipv6": "⚠️ 将删除该实例的全部 IPv6 地址。",
          "reboot": "重启期间服务短暂中断。"}
HOME = ("« 主菜单", {"t": "home"})


def _home_kb():
    accs = core.list_accounts()
    cnt = {p: sum(1 for a in accs if a["provider"] == p) for p in PROV_NAME}
    provs = [(f"☁️ {n}（{cnt[p]}）", {"t": "prov", "p": p}) for p, n in PROV_NAME.items()]
    return _kb([provs[i:i + 3] for i in range(0, len(provs), 3)] + [
                [("⚡ 一键测活", {"t": "testall"}), ("📋 最近任务", {"t": "tasks"})],
                [("💰 账单汇总", {"t": "bill"}), ("💳 Credit", {"t": "credits"})]])


def _accounts_kb():   # v1.4 兼容名：/start 主菜单
    return _home_kb()


HOME_TEXT = "☁️ <b>TriCloud</b>\n选择云厂商，或直接查看汇总："


def _acc_kb(acc):
    rows = [[("🖥 实例", {"t": "list", "a": acc["id"], "k": "vm"})]]
    if acc["provider"] == "aws":
        rows[0].append(("💡 Lightsail", {"t": "list", "a": acc["id"], "k": "lightsail"}))
    rows.append([("💰 账单", {"t": "abill", "a": acc["id"]}), ("⚡ 测活", {"t": "test", "a": acc["id"]})])
    rows.append([(f"« {PROV_NAME[acc['provider']]}", {"t": "prov", "p": acc["provider"]}), HOME])
    return _kb(rows)


def _acc_text(acc):
    st = "未测活" if acc.get("last_test_ok") is None else ("✅ 连通" if acc["last_test_ok"] else "❌ 上次测活失败")
    return f"<b>{esc(acc['name'])}</b>\n{PROV_NAME[acc['provider']]} · {esc(acc.get('region') or '-')} · {st}"


def _inst_ops(provider, kind):
    ops = ["start", "stop", "reboot", "changeip"]
    if kind == "vm":
        ops.append("openport")
    if provider == "oci" and kind == "vm":
        ops += ["ipv6", "delipv6"]
    return ops + ["terminate"]


ACTION_NAME.update({"delipv6": "删 IPv6", "openport": "开放端口"})
PUBLIC_WARN = "⚠️ 来源 0.0.0.0/0：这些端口将对整个互联网开放，请确认服务已设置密码 / 鉴权。"
_await_port = {}   # chat_id -> (实例按钮 payload, 时间)：等待用户回复端口号
PORT_WAIT_SEC = 300


def parse_port_reply(txt):
    """"8443" / "80, 443, 8000-8100" / "udp 51820" -> (protocol, port 文本, ranges)；不合法抛 ValueError。"""
    from .providers.oci_provider import OCIProvider
    parts = str(txt or "").strip().split(None, 1)
    proto = "tcp"
    if parts and parts[0].lower() in ("tcp", "udp"):
        proto = parts[0].lower()
        parts = parts[1:]
    port = (parts[0] if parts else "").strip()
    if not port:
        raise ValueError("请填写端口，如 8443 或 80, 443, 8000-8100")
    ranges = OCIProvider.parse_ports(port)
    if not ranges or any(a <= 1 and b >= 65535 for a, b in ranges):
        raise ValueError("不支持对 0.0.0.0/0 放行全部端口，请填写具体端口")
    return proto, port, ranges


def _inst_view(d):
    rows, ops = [], _inst_ops(d["p"], d["k"])
    for i in range(0, len(ops), 3):
        rows.append([(ACTION_NAME[o], dict(d, t="ask", op=o)) for o in ops[i:i + 3]])
    rows.append([("🔄 刷新状态", dict(d, t="inst", fresh=1)), ("« 实例列表", {"t": "list", "a": d["a"], "k": d["k"]})])
    text = (f"<b>{esc(d['n'])}</b>{' [Lightsail]' if d['k'] == 'lightsail' else ''}\n状态：{STATE_ICON.get(d['s'], '⚪')} {esc(d['s'])}\n"
            f"IP：<code>{esc(d.get('ip') or '-')}</code>")
    return text, _kb(rows)


async def handle_callback(bot, chat_id, cq):
    """内联按钮回调。调用方已校验 chat_id；这里再校验一次，避免误用。"""
    msg_id, chat_id = cq["message"]["message_id"], str(chat_id)
    if str(cq["message"]["chat"]["id"]) != chat_id:
        await bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "未授权", "show_alert": True})
        return
    await bot.call("answerCallbackQuery", {"callback_query_id": cq["id"]})
    data = _cb.get(cq.get("data"), (None,))[0]
    if not data:
        await _edit(bot, chat_id, msg_id, "按钮已过期，请发送 /start", None)
        return
    t = data["t"]
    back = _kb([[HOME]])
    if t == "home":
        await _edit(bot, chat_id, msg_id, HOME_TEXT, _home_kb())
    elif t == "prov":
        accs = [a for a in core.list_accounts() if a["provider"] == data["p"]]
        rows = [[(("✅ " if a.get("last_test_ok") else "❌ " if a.get("last_test_ok") == 0 else "") + a["name"],
                  {"t": "acc", "a": a["id"]})] for a in accs]
        rows.append([HOME])
        txt = f"<b>{PROV_NAME[data['p']]}</b> 账号（{len(accs)} 个）：" if accs else f"{PROV_NAME[data['p']]} 还没有账号，请先在面板添加。"
        await _edit(bot, chat_id, msg_id, txt, _kb(rows))
    elif t == "acc":
        acc = core.get_account(data["a"])
        if not acc:
            await _edit(bot, chat_id, msg_id, "账号不存在（可能已删除）", back)
            return
        await _edit(bot, chat_id, msg_id, _acc_text(acc), _acc_kb(acc))
    elif t == "list":
        acc = core.get_account(data["a"])
        if not acc:
            await _edit(bot, chat_id, msg_id, "账号不存在（可能已删除）", back)
            return
        kind = data.get("k", "vm")
        await _edit(bot, chat_id, msg_id, f"⏳ 正在读取 {esc(acc['name'])} 的实例…")
        try:
            items = await asyncio.to_thread(services.list_instances, acc["id"], None, kind)
        except Exception as e:
            await _edit(bot, chat_id, msg_id, f"查询失败：{esc(str(e)[:300])}", _kb([[("« 返回", {"t": "acc", "a": acc["id"]})]]))
            return
        rows = [[(f"{STATE_ICON.get(i['state'], '⚪')} {i['name']}" + (f" · {i['public_ip']}" if i.get("public_ip") else ""),
                  {"t": "inst", "a": acc["id"], "p": acc["provider"], "i": i["id"], "k": kind, "n": i["name"], "s": i["state"],
                   "ip": i.get("public_ip"), "r": i.get("region")})] for i in items]
        rows.append([("« 返回", {"t": "acc", "a": acc["id"]}), HOME])
        await _edit(bot, chat_id, msg_id, f"<b>{esc(acc['name'])}</b> 的{'Lightsail ' if kind == 'lightsail' else ''}实例（{len(items)} 台）：",
                    _kb(rows))
    elif t == "inst":
        _await_port.pop(chat_id, None)
        d = dict(data)
        if d.get("fresh"):
            try:
                d["s"] = await asyncio.to_thread(services.get_state, d["a"], d["i"], d.get("r"), d["k"])
            except Exception as e:
                d["s"] = f"查询失败 {str(e)[:60]}"
        d.pop("fresh", None)
        text, kb = _inst_view(d)
        await _edit(bot, chat_id, msg_id, text, kb)
    elif t == "ask" and data["op"] == "openport":   # 先让用户回复端口号，收到后再二次确认
        _await_port[chat_id] = (dict(data), time.time())
        await _edit(bot, chat_id, msg_id, f"🔓 在 <b>{esc(data['n'])}</b> 开放端口（来源 0.0.0.0/0）\n"
                    "请直接回复端口号，例如 <code>8443</code> 或 <code>80, 443, 8000-8100</code>；"
                    "UDP 在前面加 udp，例如 <code>udp 51820</code>。\n5 分钟内有效，发送 /cancel 取消。",
                    _kb([[("取消", dict(data, t="inst"))]]))
    elif t == "ask":   # 二次确认
        op = data["op"]
        warn = DANGER.get(op, "")
        rows = [[("✅ 确认" + ACTION_NAME[op], dict(data, t="do")), ("取消", dict(data, t="inst"))]]
        await _edit(bot, chat_id, msg_id, f"确认对 <b>{esc(data['n'])}</b> 执行「{ACTION_NAME[op]}」？\n{warn}".strip(), _kb(rows))
    elif t == "do":
        from . import tasks
        op = data["op"]
        await _edit(bot, chat_id, msg_id, f"⏳ 正在对 {esc(data['n'])} 执行 {ACTION_NAME[op]}…")
        try:
            if op == "changeip":
                tid = tasks.create_task("change_ip", data["a"], {"instance_id": data["i"], "kind": data["k"], "name": data["n"],
                                                                 "region": data.get("r")})
                tasks.record_ip_change(data["a"], data["i"], False, tid)
                text = f"已创建换 IP 任务 #{tid}，完成后通知（已绑定的域名会自动更新解析）。"
            elif op == "ipv6":
                tid = tasks.create_task("ipv6", data["a"], {"instance_id": data["i"], "name": data["n"], "region": data.get("r")})
                text = f"已创建 IPv6 任务 #{tid}，会自动开通 VCN/子网/路由，完成后通知。"
            elif op == "openport":
                _, _, ranges = parse_port_reply(f"{data['proto']} {data['port']}")
                r = await asyncio.to_thread(lambda: services.provider(data["a"], data.get("r")).open_ports(data["i"], data["proto"], ranges))
                text = (f"✅ {esc(data['n'])} 已开放 {data['proto'].upper()} {esc(data['port'])}（来源 0.0.0.0/0）\n" +
                        "\n".join(f"{esc(g['kind'])} {esc(g['name'])}：新增 {g['added']} 条，跳过 {g['skipped']} 条"
                                  for g in r.get("groups", [])))
            elif op == "delipv6":
                r = await asyncio.to_thread(lambda: services.provider(data["a"], data.get("r")).delete_ipv6(data["i"]))
                text = "✅ 已删除 IPv6：" + esc(", ".join(r["deleted"]))
            else:
                await asyncio.to_thread(services.instance_action, data["a"], data["i"], op, data.get("r"), data["k"])
                text = f"✅ {esc(data['n'])} {ACTION_NAME[op]} 指令已发送"
        except Exception as e:
            text = f"❌ 失败：{esc(str(e)[:300])}"
        await _edit(bot, chat_id, msg_id, text, _kb([[("« 实例", dict(data, t="inst", fresh=1)), ("« 实例列表", {"t": "list", "a": data["a"], "k": data["k"]})]]))
    elif t == "test":
        acc = core.get_account(data["a"])
        await _edit(bot, chat_id, msg_id, f"⏳ 正在测活 {esc(acc['name'] if acc else '')}…")
        r = await asyncio.to_thread(_test_one, data["a"])
        acc = core.get_account(data["a"]) or {"id": data["a"], "name": "?", "provider": "oci"}
        await _edit(bot, chat_id, msg_id, r, _acc_kb(acc) if acc.get("provider") in PROV_NAME else back)
    elif t == "testall":
        await _edit(bot, chat_id, msg_id, "⏳ 正在测活全部账号…")
        lines = [await asyncio.to_thread(_test_one, a["id"]) for a in core.list_accounts()]
        await _edit(bot, chat_id, msg_id, "⚡ <b>测活结果</b>\n" + ("\n".join(lines) or "还没有账号"), back)
    elif t == "tasks":
        await _edit(bot, chat_id, msg_id, tasks_report(), back)
    elif t == "bill":
        await _edit(bot, chat_id, msg_id, await asyncio.to_thread(billing_report), back)
    elif t == "abill":
        acc = core.get_account(data["a"])
        await _edit(bot, chat_id, msg_id, await asyncio.to_thread(billing_report, [acc] if acc else []),
                    _kb([[("« 返回", {"t": "acc", "a": data["a"]}), HOME]]))
    elif t == "credits":
        await _edit(bot, chat_id, msg_id, await asyncio.to_thread(credits_report), back)


def _test_one(acc_id):
    """测活单个账号（与面板「测活」同一逻辑：清缓存、记录结果）。"""
    import time as _t
    acc = core.get_account(acc_id)
    if not acc:
        return "账号不存在"
    t0 = _t.time()
    try:
        services.drop_provider_cache(acc_id)
        services.provider(acc_id).test()
        ms = int((_t.time() - t0) * 1000)
        core.ex("UPDATE accounts SET last_test_ok=1, last_test_ms=?, last_test_at=?, last_test_error=NULL WHERE id=?",
                (ms, int(_t.time()), acc_id))
        return f"✅ {esc(acc['name'])} · {ms} ms"
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:200]}"
        core.ex("UPDATE accounts SET last_test_ok=0, last_test_ms=?, last_test_at=?, last_test_error=? WHERE id=?",
                (int((_t.time() - t0) * 1000), int(_t.time()), err, acc_id))
        return f"❌ {esc(acc['name'])} · {esc(err)}"


def billing_report(accounts=None):
    lines = [f"💰 <b>账单汇总</b>（{services.now_local():%Y-%m-%d}）"]
    for a in (core.list_accounts() if accounts is None else accounts):
        try:
            b = services.billing(a["id"])  # AWS 自动走缓存
            extra = ""
            if a["provider"] == "aws" and b.get("no_cache"):
                lines.append(f"AWS · {esc(a['name'])}：暂无缓存，{b['next_refresh']} 自动刷新")
                continue
            if a["provider"] == "aws":
                extra = f"（数据更新于 {b['updated_at']}）"
                if b["credits"]["total"]:
                    extra += f" Credit 余 ${b['credits']['remaining']}"
            lines.append(f"{a['provider'].upper()} · {esc(a['name'])}：{b['total']} {b['currency']}{extra}")
        except Exception as e:
            lines.append(f"{a['provider'].upper()} · {esc(a['name'])}：查询失败 {esc(str(e)[:80])}")
    return "\n".join(lines)


TASK_ICON = {"running": "⏳", "done": "✅", "failed": "❌", "stopped": "⏹", "interrupted": "⚠️"}


def tasks_report(limit=10):
    """v1.4 /tasks：最近任务（含运行中），每条带状态、次数与最新一条信息。"""
    from .tasks import TYPE_NAME
    rows = core.q("SELECT t.*, a.name AS account_name FROM tasks t LEFT JOIN accounts a ON a.id=t.account_id ORDER BY t.id DESC LIMIT ?",
                  (limit,))
    if not rows:
        return "📋 最近没有任务"
    run = sum(1 for t in rows if t["status"] == "running")
    lines = [f"📋 <b>最近 {len(rows)} 个任务</b>（运行中 {run}）"]
    for t in rows:
        when = services.dt.datetime.fromtimestamp(t["updated"] or t["created"] or 0, services.tz()).strftime("%m-%d %H:%M")
        tries = f" · {t['attempts']} 次" if t["type"] == "snatch" else ""
        lines.append(f"{TASK_ICON.get(t['status'], '•')} #{t['id']} {TYPE_NAME.get(t['type'], t['type'])} · "
                     f"{esc(t.get('account_name') or '-')}{tries} · {when}\n   {esc((t['message'] or '')[:80])}")
    return "\n".join(lines)


def credits_report():
    """v1.4 /credits：各账号 Credit 余额（估算）与 30 天内到期项。只读缓存 / 数据库，不调用 AWS Cost Explorer。"""
    from . import credits
    lines = ["💳 <b>Credit 与到期</b>"]
    for a in core.list_accounts():
        try:
            sm = credits.summary(a["id"])
        except Exception as e:
            lines.append(f"{a['provider'].upper()} · {esc(a['name'])}：读取失败 {esc(str(e)[:60])}")
            continue
        parts = []
        if sm["items"] or sm["credit_total_manual"]:
            rem = f"余 ${sm['remaining']}" if sm["remaining"] is not None else "已用额度估不出"
            parts.append(f"总额 ${sm['credit_total']:g}，{rem}")
            soon = [c for c in sm["items"] if c["expire_date"] and not c["expired"]]
            if soon:
                c = min(soon, key=lambda x: x["days_left"])
                parts.append(f"最近到期 {esc(c['name'])} {c['expire_date']}（{c['days_left']} 天）")
        if sm.get("edu") and sm["edu"].get("expires_at"):
            parts.append(f"教育优惠 {sm['edu']['expires_at']}{'（估算）' if sm['edu']['estimated'] else ''}，"
                         f"剩 {sm['edu']['days_left']} 天")
        if sm.get("age_days") is not None:
            parts.append(f"已存活 {sm['age_days']} 天")
        if parts:
            lines.append(f"{a['provider'].upper()} · {esc(a['name'])}：" + "；".join(parts))
    alerts = credits.expiry_alerts()
    if alerts:
        lines.append("\n⏰ <b>30 天内到期</b>")
        lines += ["· " + esc(credits.alert_line(x)) for x in alerts]
    if len(lines) == 1:
        lines.append("还没有录入 Credit（在面板账单页添加）")
    return "\n".join(lines)


HELP = ("/start 按钮菜单（选云 → 账号 → 实例 → 操作）\n/bill 账单汇总\n/tasks 最近任务\n/credits Credit 与到期\n"
        "/health 账号健康度\n/traffic 流量守护\n/ipq IP 查询 IP 质量（风险分 / 归属）\n/free OCI 免费额度体检")


def free_report():
    """v1.6：OCI 免费额度体检（只读）。"""
    out = []
    for a in core.list_accounts():
        if a["provider"] != "oci" or a.get("disabled"):
            continue
        try:
            fc, fm, _b = core.oci_a1_free(a["id"])
            r = services.provider(a["id"]).free_check((fc, fm))
            out.append(f"{'✅' if r['ok'] else '⚠️'} <b>{esc(a['name'])}</b> A1 {r['a1']['ocpus']:g}/{fc}C {r['a1']['memory_gb']:g}/{fm}G · "
                       f"Micro {r['micro']['count']}/2 · 存储 {r['storage']['used_gb'] if r['storage']['used_gb'] is not None else '?'}/200G"
                       + ("".join(f"\n  · {esc(x)}" for x in r["issues"])))
        except Exception as e:
            out.append(f"❌ <b>{esc(a['name'])}</b> {esc(str(e)[:100])}")
    return "🆓 OCI 免费额度体检：\n" + ("\n".join(out) or "没有启用中的 OCI 账号")


async def handle_message(bot, chat_id, m):
    chat_id = str(chat_id)
    if str(m["chat"]["id"]) != chat_id:   # 只响应配置的 chat_id
        return
    txt = (m.get("text") or "").strip()
    pend = _await_port.pop(chat_id, None)
    if pend and time.time() - pend[1] > PORT_WAIT_SEC:
        pend = None
    if pend and txt.startswith("/cancel"):
        await _reply(bot, chat_id, "已取消开放端口。")
        return
    if pend and txt and not txt.startswith("/"):
        d = pend[0]
        try:
            proto, port, _ = parse_port_reply(txt)
        except ValueError as e:
            _await_port[chat_id] = (d, time.time())   # 格式不对可以直接重新回复
            await _reply(bot, chat_id, f"❌ {esc(str(e))}\n请重新回复端口号，或发送 /cancel 取消。")
            return
        await _reply(bot, chat_id, f"确认在 <b>{esc(d['n'])}</b> 开放 {proto.upper()} <code>{esc(port)}</code>？\n{PUBLIC_WARN}",
                     _kb([[("✅ 确认开放端口", dict(d, t="do", op="openport", proto=proto, port=port)), ("取消", dict(d, t="inst"))]]))
        return
    if txt.startswith("/start") or txt.startswith("/menu"):
        await _reply(bot, chat_id, HOME_TEXT, _home_kb())
    elif txt.startswith("/bill"):
        await _reply(bot, chat_id, await asyncio.to_thread(billing_report))
    elif txt.startswith("/health"):
        rows = core.q("SELECT h.score, a.name FROM account_health h JOIN accounts a ON a.id=h.account_id ORDER BY h.score")
        await _reply(bot, chat_id, "🩺 账号健康度：\n" + ("\n".join(f"{r['score']:>3}  {esc(r['name'])}" for r in rows) or "还没有检测记录"))
    elif txt.startswith("/traffic"):
        rows = core.q("SELECT * FROM traffic_guards ORDER BY last_pct DESC")
        await _reply(bot, chat_id, "📈 本月流量：\n" + ("\n".join(f"{esc(g['name'])}：{g['last_gb'] or 0:.1f}/{g['limit_gb']:g} GB（{g['last_pct'] or 0:.0f}%）"
                                                               + (" 超限停机" if g["action"] == "stop" else "") for g in rows) or "未设置流量守护"))
    elif txt.startswith("/tasks"):
        await _reply(bot, chat_id, tasks_report())
    elif txt.startswith("/ipq"):   # v1.6
        arg = txt[4:].strip()
        try:
            q = await asyncio.to_thread(net.ip_quality, arg)
        except ValueError:
            await _reply(bot, chat_id, "用法：/ipq 203.0.113.5")
            return
        await _reply(bot, chat_id, f"🔎 <code>{esc(q['ip'])}</code>\n风险分：{q['risk'] if q['risk'] is not None else '查询失败'}（越低越干净）\n"
                                   f"类型：{esc(q.get('type') or '-')}\n归属：{esc(q.get('country') or '-')}\nISP：{esc(q.get('isp') or '-')} {esc(q.get('asn') or '')}")
    elif txt.startswith("/free"):
        await _reply(bot, chat_id, await asyncio.to_thread(free_report))
    elif txt.startswith("/credits"):
        await _reply(bot, chat_id, await asyncio.to_thread(credits_report))
    else:
        await _reply(bot, chat_id, HELP)


async def poll_loop():
    offset = 0
    while True:
        token, chat_id = cfg()
        if not token or not chat_id:
            await asyncio.sleep(15)
            continue
        try:
            async with httpx.AsyncClient(timeout=40) as cl:
                bot = HttpBot(cl, token)
                r = await cl.get(_api(token, "getUpdates"), params={"offset": offset, "timeout": 30})
                for u in r.json().get("result", []):
                    offset = u["update_id"] + 1
                    try:
                        if "callback_query" in u:
                            if str(u["callback_query"]["message"]["chat"]["id"]) == chat_id:
                                await handle_callback(bot, chat_id, u["callback_query"])
                        elif "message" in u:
                            await handle_message(bot, chat_id, u["message"])
                    except Exception as e:
                        await send(f"Bot 处理出错：{esc(e)}")
        except Exception:
            await asyncio.sleep(5)
