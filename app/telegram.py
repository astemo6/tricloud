"""Telegram 通知 + Bot 交互（FR-04）。只响应配置的 chat_id。长轮询，无需公网 webhook。"""
import asyncio
import secrets
import time

import httpx

from . import core, net, services
from .i18n import msg as _msg


def chat_lang(chat_id=None):
    """按 chat 存的语言偏好（settings: tg_lang:<chat_id>），默认中文。"""
    cid = str(chat_id if chat_id is not None else (cfg()[1] or ""))
    if cid:
        v = core.get_setting(f"tg_lang:{cid}")
        if v in ("zh", "en"):
            return v
    return "zh"


def L(key, **kw):
    """推送 / 通用文案：用配置 chat 的语言。"""
    return _msg(key, _lang=chat_lang(), **kw)


def Lc(key, chat_id, **kw):
    """交互文案：用当前 chat 的语言。"""
    return _msg(key, _lang=chat_lang(chat_id), **kw)

_cb = {}   # 短 key -> payload（callback_data 限 64 字节）
STATE_ICON = {"running": "🟢", "stopped": "🔴", "deallocated": "🔴", "stopping": "🟡", "starting": "🟡",
              "pending": "🟡", "provisioning": "🟡"}
ACTION_KEYS = ("start", "stop", "reboot", "changeip", "terminate", "ipv6", "delipv6", "openport")


def act_name(op, chat_id=None):
    return Lc(f"tg.act.{op}", chat_id) if chat_id else L(f"tg.act.{op}")


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
DANGER_KEYS = ("terminate", "stop", "changeip", "delipv6", "reboot")


def _home_btn(chat_id=None):
    return (Lc("tg.btn.home", chat_id) if chat_id else L("tg.btn.home"), {"t": "home"})


def _home_kb(chat_id=None):
    g = (lambda k: Lc(k, chat_id)) if chat_id else L
    accs = core.list_accounts()
    cnt = {p: sum(1 for a in accs if a["provider"] == p) for p in PROV_NAME}
    provs = [(f"☁️ {n}（{cnt[p]}）", {"t": "prov", "p": p}) for p, n in PROV_NAME.items()]
    return _kb([provs[i:i + 3] for i in range(0, len(provs), 3)] + [
                [(g("tg.btn.testAll"), {"t": "testall"}), (g("tg.btn.recentTasks"), {"t": "tasks"})],
                [(g("tg.btn.billing"), {"t": "bill"}), ("💳 Credit", {"t": "credits"})],
                [(g("tg.btn.lang"), {"t": "lang"})]])


def _accounts_kb(chat_id=None):   # v1.4 兼容名：/start 主菜单
    return _home_kb(chat_id)


HOME_TEXT_KEY = "tg.home"


def _acc_kb(acc, chat_id=None):
    g = (lambda k: Lc(k, chat_id)) if chat_id else L
    rows = [[(g("tg.btn.instances"), {"t": "list", "a": acc["id"], "k": "vm"})]]
    if acc["provider"] == "aws":
        rows[0].append(("💡 Lightsail", {"t": "list", "a": acc["id"], "k": "lightsail"}))
    rows.append([(g("tg.btn.bill"), {"t": "abill", "a": acc["id"]}), (g("tg.btn.test"), {"t": "test", "a": acc["id"]})])
    rows.append([(f"« {PROV_NAME[acc['provider']]}", {"t": "prov", "p": acc["provider"]}), _home_btn(chat_id)])
    return _kb(rows)


def _acc_text(acc, chat_id=None):
    g = (lambda k: Lc(k, chat_id)) if chat_id else L
    st = g("tg.acc.untested") if acc.get("last_test_ok") is None else (g("tg.acc.ok") if acc["last_test_ok"] else g("tg.acc.failed"))
    return f"<b>{esc(acc['name'])}</b>\n{PROV_NAME[acc['provider']]} · {esc(acc.get('region') or '-')} · {st}"


def _inst_ops(provider, kind):
    ops = ["start", "stop", "reboot", "changeip"]
    if kind == "vm":
        ops.append("openport")
    if provider == "oci" and kind == "vm":
        ops += ["ipv6", "delipv6"]
    return ops + ["terminate"]


PUBLIC_WARN_KEY = "tg.port.warn"
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
        raise ValueError(L("err.ports_hint"))
    ranges = OCIProvider.parse_ports(port)
    if not ranges or any(a <= 1 and b >= 65535 for a, b in ranges):
        raise ValueError(L("err.all_ports_public"))
    return proto, port, ranges


def _inst_view(d, chat_id=None):
    g = (lambda k, **kw: Lc(k, chat_id, **kw)) if chat_id else L
    rows, ops = [], _inst_ops(d["p"], d["k"])
    for i in range(0, len(ops), 3):
        rows.append([(act_name(o, chat_id), dict(d, t="ask", op=o)) for o in ops[i:i + 3]])
    rows.append([(g("tg.btn.refreshStatus"), dict(d, t="inst", fresh=1)), (g("tg.btn.instList"), {"t": "list", "a": d["a"], "k": d["k"]})])
    text = (f"<b>{esc(d['n'])}</b>{' [Lightsail]' if d['k'] == 'lightsail' else ''}\n{g('tg.inst.status')}{STATE_ICON.get(d['s'], '⚪')} {esc(d['s'])}\n"
            f"{g('tg.inst.ipLabel')}<code>{esc(d.get('ip') or '-')}</code>")
    return text, _kb(rows)


async def handle_callback(bot, chat_id, cq):
    """内联按钮回调。调用方已校验 chat_id；这里再校验一次，避免误用。"""
    msg_id, chat_id = cq["message"]["message_id"], str(chat_id)
    if str(cq["message"]["chat"]["id"]) != chat_id:
        await bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": Lc("tg.unauthorized", chat_id), "show_alert": True})
        return
    await bot.call("answerCallbackQuery", {"callback_query_id": cq["id"]})
    data = _cb.get(cq.get("data"), (None,))[0]
    if not data:
        await _edit(bot, chat_id, msg_id, Lc("tg.expired", chat_id), None)
        return
    t = data["t"]
    back = _kb([[_home_btn(chat_id)]])
    if t == "home":
        await _edit(bot, chat_id, msg_id, Lc(HOME_TEXT_KEY, chat_id), _home_kb(chat_id))
    elif t == "lang":
        await _edit(bot, chat_id, msg_id, Lc("tg.lang.title", chat_id),
                    _kb([[("中文", {"t": "setlang", "l": "zh"}), ("English", {"t": "setlang", "l": "en"})], [_home_btn(chat_id)]]))
    elif t == "setlang":
        core.set_setting(f"tg_lang:{chat_id}", data["l"])
        await _edit(bot, chat_id, msg_id, Lc("tg.lang.done", chat_id) + "\n\n" + Lc(HOME_TEXT_KEY, chat_id), _home_kb(chat_id))
    elif t == "prov":
        accs = [a for a in core.list_accounts() if a["provider"] == data["p"]]
        rows = [[(("✅ " if a.get("last_test_ok") else "❌ " if a.get("last_test_ok") == 0 else "") + a["name"],
                  {"t": "acc", "a": a["id"]})] for a in accs]
        rows.append([_home_btn(chat_id)])
        txt = Lc("tg.prov.accounts", chat_id, prov=PROV_NAME[data["p"]], n=len(accs)) if accs else Lc("tg.prov.none", chat_id, prov=PROV_NAME[data["p"]])
        await _edit(bot, chat_id, msg_id, txt, _kb(rows))
    elif t == "acc":
        acc = core.get_account(data["a"])
        if not acc:
            await _edit(bot, chat_id, msg_id, Lc("tg.acc.gone", chat_id), back)
            return
        await _edit(bot, chat_id, msg_id, _acc_text(acc, chat_id), _acc_kb(acc, chat_id))
    elif t == "list":
        acc = core.get_account(data["a"])
        if not acc:
            await _edit(bot, chat_id, msg_id, Lc("tg.acc.gone", chat_id), back)
            return
        kind = data.get("k", "vm")
        await _edit(bot, chat_id, msg_id, Lc("tg.list.loading", chat_id, name=esc(acc["name"])))
        try:
            items = await asyncio.to_thread(services.list_instances, acc["id"], None, kind)
        except Exception as e:
            await _edit(bot, chat_id, msg_id, Lc("tg.queryFailed", chat_id, e=esc(str(e)[:300])), _kb([[(Lc("tg.btn.back", chat_id), {"t": "acc", "a": acc["id"]})]]))
            return
        rows = [[(f"{STATE_ICON.get(i['state'], '⚪')} {i['name']}" + (f" · {i['public_ip']}" if i.get("public_ip") else ""),
                  {"t": "inst", "a": acc["id"], "p": acc["provider"], "i": i["id"], "k": kind, "n": i["name"], "s": i["state"],
                   "ip": i.get("public_ip"), "r": i.get("region")})] for i in items]
        rows.append([(Lc("tg.btn.back", chat_id), {"t": "acc", "a": acc["id"]}), _home_btn(chat_id)])
        await _edit(bot, chat_id, msg_id, Lc("tg.list.title", chat_id, name=esc(acc["name"]), kind="Lightsail " if kind == "lightsail" else "", n=len(items)),
                    _kb(rows))
    elif t == "inst":
        _await_port.pop(chat_id, None)
        d = dict(data)
        if d.get("fresh"):
            try:
                d["s"] = await asyncio.to_thread(services.get_state, d["a"], d["i"], d.get("r"), d["k"])
            except Exception as e:
                d["s"] = Lc("tg.queryFailedShort", chat_id, e=str(e)[:60])
        d.pop("fresh", None)
        text, kb = _inst_view(d, chat_id)
        await _edit(bot, chat_id, msg_id, text, kb)
    elif t == "ask" and data["op"] == "openport":   # 先让用户回复端口号，收到后再二次确认
        _await_port[chat_id] = (dict(data), time.time())
        await _edit(bot, chat_id, msg_id, Lc("tg.port.ask", chat_id, n=esc(data["n"])),
                    _kb([[(Lc("tg.btn.cancel", chat_id), dict(data, t="inst"))]]))
    elif t == "ask":   # 二次确认
        op = data["op"]
        warn = Lc(f"tg.danger.{op}", chat_id) if op in DANGER_KEYS else ""
        rows = [[(Lc("tg.btn.confirmOp", chat_id, op=act_name(op, chat_id)), dict(data, t="do")), (Lc("tg.btn.cancel", chat_id), dict(data, t="inst"))]]
        await _edit(bot, chat_id, msg_id, (Lc("tg.ask.confirm", chat_id, n=esc(data["n"]), op=act_name(op, chat_id)) + f"\n{warn}").strip(), _kb(rows))
    elif t == "do":
        from . import tasks
        op = data["op"]
        await _edit(bot, chat_id, msg_id, Lc("tg.doing", chat_id, n=esc(data["n"]), op=act_name(op, chat_id)))
        try:
            if op == "changeip":
                tid = tasks.create_task("change_ip", data["a"], {"instance_id": data["i"], "kind": data["k"], "name": data["n"],
                                                                 "region": data.get("r")})
                tasks.record_ip_change(data["a"], data["i"], False, tid)
                text = Lc("tg.do.changeipCreated", chat_id, tid=tid)
            elif op == "ipv6":
                tid = tasks.create_task("ipv6", data["a"], {"instance_id": data["i"], "name": data["n"], "region": data.get("r")})
                text = Lc("tg.do.ipv6Created", chat_id, tid=tid)
            elif op == "openport":
                _, _, ranges = parse_port_reply(f"{data['proto']} {data['port']}")
                r = await asyncio.to_thread(lambda: services.provider(data["a"], data.get("r")).open_ports(data["i"], data["proto"], ranges))
                text = (Lc("tg.do.portOpened", chat_id, n=esc(data["n"]), proto=data["proto"].upper(), port=esc(data["port"])) + "\n" +
                        "\n".join(Lc("tg.do.portGroup", chat_id, kind=esc(g["kind"]), name=esc(g["name"]), added=g["added"], skipped=g["skipped"])
                                  for g in r.get("groups", [])))
            elif op == "delipv6":
                r = await asyncio.to_thread(lambda: services.provider(data["a"], data.get("r")).delete_ipv6(data["i"]))
                text = Lc("tg.do.ipv6Deleted", chat_id, list=esc(", ".join(r["deleted"])))
            else:
                await asyncio.to_thread(services.instance_action, data["a"], data["i"], op, data.get("r"), data["k"])
                text = Lc("tg.do.sent", chat_id, n=esc(data["n"]), op=act_name(op, chat_id))
        except Exception as e:
            text = Lc("tg.failed", chat_id, e=esc(str(e)[:300]))
        await _edit(bot, chat_id, msg_id, text, _kb([[(Lc("tg.btn.inst", chat_id), dict(data, t="inst", fresh=1)), (Lc("tg.btn.instList", chat_id), {"t": "list", "a": data["a"], "k": data["k"]})]]))
    elif t == "test":
        acc = core.get_account(data["a"])
        await _edit(bot, chat_id, msg_id, Lc("tg.testing", chat_id, name=esc(acc["name"] if acc else "")))
        r = await asyncio.to_thread(_test_one, data["a"])
        acc = core.get_account(data["a"]) or {"id": data["a"], "name": "?", "provider": "oci"}
        await _edit(bot, chat_id, msg_id, r, _acc_kb(acc, chat_id) if acc.get("provider") in PROV_NAME else back)
    elif t == "testall":
        await _edit(bot, chat_id, msg_id, Lc("tg.testingAll", chat_id))
        lines = [await asyncio.to_thread(_test_one, a["id"]) for a in core.list_accounts()]
        await _edit(bot, chat_id, msg_id, Lc("tg.test.title", chat_id) + "\n" + ("\n".join(lines) or Lc("tg.noAccounts", chat_id)), back)
    elif t == "tasks":
        await _edit(bot, chat_id, msg_id, tasks_report(), back)
    elif t == "bill":
        await _edit(bot, chat_id, msg_id, await asyncio.to_thread(billing_report), back)
    elif t == "abill":
        acc = core.get_account(data["a"])
        await _edit(bot, chat_id, msg_id, await asyncio.to_thread(billing_report, [acc] if acc else []),
                    _kb([[(Lc("tg.btn.back", chat_id), {"t": "acc", "a": data["a"]}), _home_btn(chat_id)]]))
    elif t == "credits":
        await _edit(bot, chat_id, msg_id, await asyncio.to_thread(credits_report), back)


def _test_one(acc_id):
    """测活单个账号（与面板「测活」同一逻辑：清缓存、记录结果）。"""
    import time as _t
    acc = core.get_account(acc_id)
    if not acc:
        return L("tg.acc.goneShort")
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
    lines = [L("tg.bill.title", date=f"{services.now_local():%Y-%m-%d}")]
    for a in (core.list_accounts() if accounts is None else accounts):
        try:
            b = services.billing(a["id"])  # AWS 自动走缓存
            extra = ""
            if a["provider"] == "aws" and b.get("no_cache"):
                lines.append(L("tg.bill.noCache", name=esc(a["name"]), next=b["next_refresh"]))
                continue
            if a["provider"] == "aws":
                extra = L("tg.bill.updated", at=b["updated_at"])
                if b["credits"]["total"]:
                    extra += L("tg.bill.creditLeft", amt=b["credits"]["remaining"])
            lines.append(L("tg.bill.line", prov=a["provider"].upper(), name=esc(a["name"]), total=b["total"], cur=b["currency"], extra=extra))
        except Exception as e:
            lines.append(L("tg.bill.fail", prov=a["provider"].upper(), name=esc(a["name"]), e=esc(str(e)[:80])))
    return "\n".join(lines)


TASK_ICON = {"running": "⏳", "done": "✅", "failed": "❌", "stopped": "⏹", "interrupted": "⚠️"}
TG_TYPES = {"snatch", "change_ip", "resize", "ipv6", "azure_create", "ensure_network", "snapshot", "migrate",
            "cf_delete", "reinstall", "net500m", "foundry", "billing_keep", "aws_credit", "onedrive_backup"}


def type_name(tt):
    return L(f"tg.type.{tt}") if tt in TG_TYPES else tt


def tasks_report(limit=10):
    """v1.4 /tasks：最近任务（含运行中），每条带状态、次数与最新一条信息。"""
    rows = core.q("SELECT t.*, a.name AS account_name FROM tasks t LEFT JOIN accounts a ON a.id=t.account_id ORDER BY t.id DESC LIMIT ?",
                  (limit,))
    if not rows:
        return L("tg.tasks.empty")
    run = sum(1 for t in rows if t["status"] == "running")
    lines = [L("tg.tasks.title", n=len(rows), run=run)]
    for t in rows:
        when = services.dt.datetime.fromtimestamp(t["updated"] or t["created"] or 0, services.tz()).strftime("%m-%d %H:%M")
        tries = L("tg.tasks.tries", n=t["attempts"]) if t["type"] == "snatch" else ""
        lines.append(f"{TASK_ICON.get(t['status'], '•')} #{t['id']} {type_name(t['type'])} · "
                     f"{esc(t.get('account_name') or '-')}{tries} · {when}\n   {esc((t['message'] or '')[:80])}")
    return "\n".join(lines)


def credits_report():
    """v1.4 /credits：各账号 Credit 余额（估算）与 30 天内到期项。只读缓存 / 数据库，不调用 AWS Cost Explorer。"""
    from . import credits
    lines = [L("tg.credits.title")]
    for a in core.list_accounts():
        try:
            sm = credits.summary(a["id"])
        except Exception as e:
            lines.append(L("tg.credits.readFail", prov=a["provider"].upper(), name=esc(a["name"]), e=esc(str(e)[:60])))
            continue
        parts = []
        if sm["items"] or sm["credit_total_manual"]:
            rem = L("tg.credits.remLeft", amt=sm["remaining"]) if sm["remaining"] is not None else L("tg.credits.remUnknown")
            parts.append(L("tg.credits.total", total=f"{sm['credit_total']:g}", rem=rem))
            soon = [c for c in sm["items"] if c["expire_date"] and not c["expired"]]
            if soon:
                c = min(soon, key=lambda x: x["days_left"])
                parts.append(L("tg.credits.soonest", name=esc(c["name"]), date=c["expire_date"], days=c["days_left"]))
        if sm.get("edu") and sm["edu"].get("expires_at"):
            parts.append(L("tg.credits.edu", date=sm["edu"]["expires_at"], est=L("tg.credits.est") if sm["edu"]["estimated"] else "", days=sm["edu"]["days_left"]))
        if sm.get("age_days") is not None:
            parts.append(L("tg.credits.age", days=sm["age_days"]))
        if parts:
            lines.append(L("tg.credits.line", prov=a["provider"].upper(), name=esc(a["name"]), parts=L("tg.sep").join(parts)))
    lines += aws_free_plan_lines()
    alerts = credits.expiry_alerts()
    if alerts:
        lines.append(L("tg.credits.expSoon"))
        lines += ["· " + esc(credits.alert_line(x)) for x in alerts]
    if len(lines) == 1:
        lines.append(L("tg.credits.empty"))
    return "\n".join(lines)


def aws_free_plan_lines():
    """build 20：AWS 新号 Free Tier Credit（只读面板里 5 分钟内查过的缓存，不额外调用 AWS）。"""
    from .routers import aws_credit as rc
    out = []
    for a in core.list_accounts():
        hit = rc._CREDITS.get(a["id"]) if a["provider"] == "aws" else None
        if not hit or hit[1].get("state") != "ok":
            continue
        d = hit[1]
        pl = d.get("plan") or {}
        acts = [x for x in d.get("activities") or [] if x.get("key")]
        done = sum(1 for x in acts if x.get("status") == "COMPLETED")
        rem = pl.get("remaining")
        out.append(L("tg.awsFree.line", name=esc(a["name"]), type=esc(pl.get("type") or "-"),
                     rem=(f"${rem:g}" if isinstance(rem, (int, float)) else "-"), exp=esc(str(pl.get("expires") or "-")[:10]),
                     acts=(L("tg.awsFree.acts", done=done, total=len(acts)) if acts else ""), at=esc(d.get("updated_at") or "")))
    return ([L("tg.awsFree.title")] + out) if out else []


HELP_KEY = "tg.help"


def __getattr__(name):   # 兼容旧引用（测试等）：HELP 按配置 chat 的当前语言动态生成
    if name == "HELP":
        return L(HELP_KEY)
    raise AttributeError(name)


def backup_command(arg=""):
    """build 21 /backup：立即备份（后台任务，完成后另发一条）+ 状态；/backup status 只看状态。"""
    from . import onedrive
    from .routers import onedrive as rod
    head = L("tg.backup.title")
    if arg.strip().lower() in ("status", "状态", "s"):
        return head + "\n" + esc(onedrive.status_text())
    if not onedrive.bound() or not onedrive.password():
        return head + "\n" + esc(onedrive.status_text()) + "\n" + L("tg.backup.needSetup")
    tid = rod.running_task()
    if tid:
        return head + "\n" + L("tg.backup.running", tid=tid) + "\n" + esc(onedrive.status_text())
    tid = rod.start_backup("tg")
    return head + "\n" + L("tg.backup.started", tid=tid) + "\n" + esc(onedrive.status_text())


def free_report():
    """v1.6：OCI 免费额度体检（只读）。"""
    out = []
    for a in core.list_accounts():
        if a["provider"] != "oci" or a.get("disabled"):
            continue
        try:
            fc, fm, _b = core.oci_a1_free(a["id"])
            r = services.provider(a["id"]).free_check((fc, fm))
            out.append(L("tg.free.line", icon="✅" if r["ok"] else "⚠️", name=esc(a["name"]), o=f"{r['a1']['ocpus']:g}", fc=fc,
                         m=f"{r['a1']['memory_gb']:g}", fm=fm, mc=r["micro"]["count"],
                         used=(r["storage"]["used_gb"] if r["storage"]["used_gb"] is not None else "?"))
                       + ("".join(f"\n  · {esc(x)}" for x in r["issues"])))
        except Exception as e:
            out.append(f"❌ <b>{esc(a['name'])}</b> {esc(str(e)[:100])}")
    return L("tg.free.title") + ("\n".join(out) or L("tg.free.none"))


def _cmd_arg(txt, cmd):
    """「/ports@MyBot 名字」或「/ports 名字」→「名字」。"""
    rest = txt[len(cmd):]
    if rest.startswith("@"):
        rest = rest.split(None, 1)[1] if len(rest.split(None, 1)) > 1 else ""
    return rest.strip()


async def handle_message(bot, chat_id, m):
    chat_id = str(chat_id)
    if str(m["chat"]["id"]) != chat_id:   # 只响应配置的 chat_id
        return
    txt = (m.get("text") or "").strip()
    pend = _await_port.pop(chat_id, None)
    if pend and time.time() - pend[1] > PORT_WAIT_SEC:
        pend = None
    if pend and txt.startswith("/cancel"):
        await _reply(bot, chat_id, Lc("tg.port.cancelled", chat_id))
        return
    if pend and txt and not txt.startswith("/"):
        d = pend[0]
        try:
            proto, port, _ = parse_port_reply(txt)
        except ValueError as e:
            _await_port[chat_id] = (d, time.time())   # 格式不对可以直接重新回复
            await _reply(bot, chat_id, Lc("tg.port.retry", chat_id, e=esc(str(e))))
            return
        await _reply(bot, chat_id, Lc("tg.port.confirm", chat_id, n=esc(d["n"]), proto=proto.upper(), port=esc(port)) + "\n" + Lc(PUBLIC_WARN_KEY, chat_id),
                     _kb([[(Lc("tg.btn.confirmOpenPort", chat_id), dict(d, t="do", op="openport", proto=proto, port=port)), (Lc("tg.btn.cancel", chat_id), dict(d, t="inst"))]]))
        return
    if txt.startswith("/start") or txt.startswith("/menu"):
        await _reply(bot, chat_id, Lc(HOME_TEXT_KEY, chat_id), _home_kb(chat_id))
    elif txt.startswith("/lang"):
        await _reply(bot, chat_id, Lc("tg.lang.title", chat_id),
                     _kb([[("中文", {"t": "setlang", "l": "zh"}), ("English", {"t": "setlang", "l": "en"})]]))
    elif txt.startswith("/bill"):
        await _reply(bot, chat_id, await asyncio.to_thread(billing_report))
    elif txt.startswith("/health"):
        rows = core.q("SELECT h.score, a.name FROM account_health h JOIN accounts a ON a.id=h.account_id ORDER BY h.score")
        await _reply(bot, chat_id, Lc("tg.health.title", chat_id) + ("\n".join(f"{r['score']:>3}  {esc(r['name'])}" for r in rows) or Lc("tg.health.none", chat_id)))
    elif txt.startswith("/traffic"):
        rows = core.q("SELECT * FROM traffic_guards ORDER BY last_pct DESC")
        await _reply(bot, chat_id, Lc("tg.traffic.title", chat_id) + ("\n".join(
            Lc("tg.traffic.line", chat_id, name=esc(g["name"]), gb=f"{g['last_gb'] or 0:.1f}", limit=f"{g['limit_gb']:g}", pct=f"{g['last_pct'] or 0:.0f}")
            + (Lc("tg.traffic.stopSuffix", chat_id) if g["action"] == "stop" else "")
            + ((Lc("tg.traffic.throttledSuffix", chat_id) if g.get("throttled") else Lc("tg.traffic.throttleSuffix", chat_id)) if g["action"] == "throttle" else "") for g in rows) or Lc("tg.traffic.none", chat_id)))
    elif txt.startswith("/ports"):   # build 22 流量明细
        from . import port_traffic
        await _reply(bot, chat_id, await asyncio.to_thread(port_traffic.tg_report, _cmd_arg(txt, "/ports")))
    elif txt.startswith("/tasks"):
        await _reply(bot, chat_id, tasks_report())
    elif txt.startswith("/ipq"):   # v1.6
        arg = txt[4:].strip()
        try:
            q = await asyncio.to_thread(net.ip_quality, arg)
        except ValueError:
            await _reply(bot, chat_id, Lc("tg.ipq.usage", chat_id))
            return
        await _reply(bot, chat_id, Lc("tg.ipq.result", chat_id, ip=esc(q["ip"]),
                                      risk=(q["risk"] if q["risk"] is not None else Lc("tg.ipq.failed", chat_id)),
                                      type=esc(q.get("type") or "-"), country=esc(q.get("country") or "-"),
                                      isp=esc(q.get("isp") or "-"), asn=esc(q.get("asn") or "")))
    elif txt.startswith("/free"):
        await _reply(bot, chat_id, await asyncio.to_thread(free_report))
    elif txt.startswith("/backup"):   # build 21
        await _reply(bot, chat_id, await asyncio.to_thread(backup_command, txt[7:]))
    elif txt.startswith("/credits"):
        await _reply(bot, chat_id, await asyncio.to_thread(credits_report))
    else:
        await _reply(bot, chat_id, Lc(HELP_KEY, chat_id))


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
                        await send(L("tg.botError", e=esc(e)))
        except Exception:
            await asyncio.sleep(5)
