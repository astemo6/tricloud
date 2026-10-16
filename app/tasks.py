"""后台任务：OCI 自动抢机、长耗时换 IP、实例监控、AWS 定时账单、每日报告。"""
import asyncio
import json
import time
import traceback

from . import cloudinit, core, credits, dns, health, net, services, telegram, traffic_guard

RUNNING = set()
LOG_KEEP = 500          # 每个任务最多保留的日志行数（抢机任务可能跑几千次）
TYPE_NAME = {"snatch": "抢机", "change_ip": "换 IP", "resize": "改配置", "ipv6": "IPv6", "azure_create": "创建 VM",
             "ensure_network": "自动建网", "snapshot": "快照（已移除）", "migrate": "迁移", "cf_delete": "删除 CDN 分发",
             "reinstall": "重装系统", "net500m": "下行 500Mbps", "foundry": "部署 AI 模型",
             "billing_keep": "保号账单", "aws_credit": "新号 Credit", "onedrive_backup": "OneDrive 备份"}
NO_ACCOUNT_TYPES = {"onedrive_backup"}   # 面板级任务：account_id=0，不取云账号 / provider
CF_POLL_SECONDS = 30          # 删除 CloudFront 分发：等待停用部署完成的轮询间隔
CF_WAIT_SECONDS = 45 * 60     # 最长等待


class TaskStopped(Exception):
    """任务被用户停止：长任务在下一步检查点退出。"""


# ---------------- v1.4 任务日志 ----------------
def log(tid, msg, level="info"):
    """追加一行任务日志。level: info / ok / warn / error。"""
    core.ex("INSERT INTO task_logs(task_id, ts, level, msg) VALUES(?,?,?,?)", (tid, int(time.time()), level, str(msg)[:1000]))
    n = core.q("SELECT COUNT(*) AS n FROM task_logs WHERE task_id=?", (tid,), one=True)["n"]
    if n > LOG_KEEP + 50:
        core.ex("DELETE FROM task_logs WHERE task_id=? AND id NOT IN "
                "(SELECT id FROM task_logs WHERE task_id=? ORDER BY id DESC LIMIT ?)", (tid, tid, LOG_KEEP))


def get_logs(tid, after=0, limit=LOG_KEEP):
    """after=0：最近 limit 行（按时间正序）；after>0：该 id 之后的新日志（轮询增量）。"""
    if not after:
        rows = core.q("SELECT id, ts, level, msg FROM task_logs WHERE task_id=? ORDER BY id DESC LIMIT ?", (tid, limit))
        return rows[::-1]
    return core.q("SELECT id, ts, level, msg FROM task_logs WHERE task_id=? AND id>? ORDER BY id LIMIT ?", (tid, int(after), limit))


def _summary(ttype, params):
    p = params or {}
    bits = [TYPE_NAME.get(ttype, ttype)]
    if p.get("name"):
        bits.append(str(p["name"]))
    if ttype == "change_ip" and p.get("cidrs"):
        bits.append("网段 " + ", ".join(p["cidrs"]))
    if ttype == "snatch":
        c = p.get("create") or {}
        bits.append(f"{c.get('shape', '')} {c.get('ocpus', '')}C/{c.get('memory_gb', '')}G，间隔 {p.get('interval', 60)}s")
    if p.get("reason"):
        bits.append(f"原因：{p['reason']}")
    return " · ".join(b for b in bits if b and b.strip())


def create_task(ttype, acc_id, params):
    now = int(time.time())
    params = dict(params)
    params.setdefault("next_run", now)
    tid = core.ex("INSERT INTO tasks(type, account_id, params, status, attempts, message, created, updated) "
                  "VALUES(?,?,?,?,?,?,?,?)", (ttype, acc_id, json.dumps(params), "running", 0, "排队中", now, now))
    log(tid, "任务已创建：" + _summary(ttype, params))
    return tid


def _update(tid, **kw):
    kw["updated"] = int(time.time())
    quiet = kw.pop("quiet", False)
    if "params" in kw:
        kw["params"] = json.dumps(kw["params"])
    if "result" in kw and not isinstance(kw["result"], str):
        kw["result"] = json.dumps(kw["result"], ensure_ascii=False, default=str)
    cols = ", ".join(f"{k}=?" for k in kw)
    core.ex(f"UPDATE tasks SET {cols} WHERE id=?", (*kw.values(), tid))
    if kw.get("message") and not quiet:
        st = kw.get("status")
        log(tid, kw["message"], {"done": "ok", "failed": "error", "stopped": "warn"}.get(st, "info"))


def is_stopped(tid):
    r = core.q("SELECT status FROM tasks WHERE id=?", (tid,), one=True)
    return not r or r["status"] == "stopped"


def stop_task(tid):
    t = core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)
    if t and t["status"] == "running":
        _update(tid, status="stopped", message="已手动停止")
        acc = core.get_account(t["account_id"]) or {}
        coro = telegram.send(f"⏹ 任务 #{tid}（{t['type']} · {telegram.esc(acc.get('name'))}）已停止，共尝试 {t['attempts']} 次")
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:     # v1.4 修复：同步路由在线程池里调用时没有事件循环
            asyncio.run(coro)


async def _run_snatch(t):
    p = json.loads(t["params"])
    acc = core.get_account(t["account_id"])
    attempts = t["attempts"] + 1
    try:
        prov = services.provider(t["account_id"], p.get("region"))
        create = dict(p["create"], _ad_index=attempts - 1, script=cloudinit.resolve_script(p["create"]))
        r = await asyncio.to_thread(prov.create_instance, create)
        if r.get("password"):
            cloudinit.save_instance_secret(t["account_id"], r["id"], r["name"], r["username"], r["password"])
        _update(t["id"], status="done", attempts=attempts, message=f"抢机成功：{r['name']}（{r.get('ad', '')}）",
                result={k: r.get(k) for k in ("id", "name", "ad", "public_ip", "username") if r.get(k)})
        await telegram.send(f"🎉 <b>抢机成功</b>\n账号：{telegram.esc(acc['name'])}\n实例：{telegram.esc(r['name'])}\n"
                            f"规格：{p['create'].get('shape')} {p['create'].get('ocpus')}C/{p['create'].get('memory_gb')}G\n尝试次数：{attempts}"
                            + ("\nroot 密码已加密保存，可在面板「开机密码」查看" if r.get("password") else ""))
    except Exception as e:
        cap = services.OCIProvider.is_capacity_error(e)
        p["errors"] = 0 if cap else p.get("errors", 0) + 1
        p["next_run"] = int(time.time()) + int(p.get("interval", 60))
        msg = f"第 {attempts} 次：{'容量不足' if cap else str(e)[:200]}"
        maxa = int(p.get("max_attempts") or 0)
        if is_stopped(t["id"]):
            return
        if p["errors"] >= 5 or (maxa and attempts >= maxa):
            _update(t["id"], status="failed", attempts=attempts, message=msg, params=p)
            await telegram.send(f"❌ <b>抢机任务 #{t['id']} 失败</b>\n{telegram.esc(acc['name'])}\n{telegram.esc(msg)}")
        else:
            _update(t["id"], attempts=attempts, message=msg, params=p)


class _TaskCtx:
    """一次性任务处理函数的上下文：任务行、参数、账号、provider、显示名，以及进度 / 安全点 / 日志回调。"""
    __slots__ = ("t", "p", "acc", "prov", "name", "progress", "checkpoint", "tlog")

    def __init__(self, t, p, acc, prov, name, progress, checkpoint, tlog):
        self.t, self.p, self.acc, self.prov, self.name = t, p, acc, prov, name
        self.progress, self.checkpoint, self.tlog = progress, checkpoint, tlog


async def _do_change_ip(c):
    """换 IP（OCI 由 provider 内部重试；AWS / Azure 走 _change_ip_retry），完成后同步 DNS 与监控里的 IP。"""
    t, p, acc, prov, name, progress, checkpoint, tlog = c.t, c.p, c.acc, c.prov, c.name, c.progress, c.checkpoint, c.tlog
    core.ex("UPDATE monitors SET last_state='user:changeip' WHERE account_id=? AND instance_id=?",
            (t["account_id"], p["instance_id"]))
    if p.get("cidrs"):
        inc, exc = net.split_cidrs(p["cidrs"])
        tlog("网段要求：" + "；".join(([f"命中 {', '.join(map(str, inc))}"] if inc else [])
                                  + ([f"排除 {', '.join(map(str, exc))}"] if exc else [])))
    acc_q = _quality_accept(p, tlog)
    if acc_q:
        tlog(f"质量要求：{'风险分 ≤ ' + str(p['quality_max_risk']) if p.get('quality_max_risk') not in (None, '') else ''}"
             f"{' 归属 ' + str(p['quality_country']) if p.get('quality_country') else ''}（{net.QUALITY_SOURCES}）")
    if acc["provider"] == "oci":
        r = await asyncio.to_thread(prov.change_ip, p["instance_id"], p.get("cidrs"),
                                    int(p.get("max_tries") or 20), checkpoint, **({"accept": acc_q} if acc_q else {}))
    else:
        r = await asyncio.to_thread(_change_ip_retry, prov, acc, p, progress, checkpoint, acc_q)
    msg = f"{r.get('old_ip') or '-'} → {r.get('new_ip')}" + (f"（{r['tries']} 次）" if r.get("tries", 1) > 1 else "")
    if r.get("warning"):
        msg += "，" + r["warning"]
        tlog(r["warning"], "warn")
    tlog("同步 DNS 绑定…")
    dns_out = await asyncio.to_thread(dns.dns_sync, t["account_id"], p["instance_id"], r.get("new_ip"))
    for d in dns_out:
        tlog(d)
    core.ex("UPDATE monitors SET public_ip=?, fail_count=0 WHERE account_id=? AND instance_id=?",
            (r.get("new_ip"), t["account_id"], p["instance_id"]))
    _update(t["id"], status="done", message=msg + ("；" + "；".join(dns_out) if dns_out else ""),
            result={"old_ip": r.get("old_ip"), "new_ip": r.get("new_ip"), "tries": r.get("tries", 1), "dns": dns_out})
    await telegram.send(f"✅ <b>换 IP 完成</b>{'（' + telegram.esc(p['reason']) + '）' if p.get('reason') else ''}\n"
                        f"{telegram.esc(acc['name'])} / {telegram.esc(name)}\n<code>{msg}</code>"
                        + ("\n" + telegram.esc("\n".join(dns_out)) if dns_out else ""))


async def _do_ipv6(c):
    """一键 IPv6 全链路。"""
    t, p, prov, name, progress = c.t, c.p, c.prov, c.name, c.progress
    r = await asyncio.to_thread(prov.add_ipv6, p["instance_id"], progress)
    dns_out = await asyncio.to_thread(dns.dns_sync, t["account_id"], p["instance_id"], None, r["ipv6"])
    _update(t["id"], status="done", message=f"IPv6：{r['ipv6']}" + ("；" + "；".join(dns_out) if dns_out else ""), result={"ipv6": r["ipv6"]})
    await telegram.send(f"✅ <b>IPv6 已就绪</b>\n{telegram.esc(name)}\n<code>{r['ipv6']}</code>")


async def _do_azure_create(c):
    """Azure 创建 VM（后台，含开机密码留存）。"""
    t, p, prov, progress = c.t, c.p, c.prov, c.progress
    create = dict(p["create"], script=cloudinit.resolve_script(p["create"]))
    r = await asyncio.to_thread(prov.create_vm, create, progress)
    if r.get("password"):
        cloudinit.save_instance_secret(t["account_id"], r["id"], r["name"], r["username"], r["password"])
    _update(t["id"], status="done", message=f"已创建 {r['name']}，IP {r.get('public_ip')}",
            result={k: r.get(k) for k in ("id", "name", "public_ip", "username") if r.get(k)})
    await telegram.send(f"✅ <b>Azure VM 创建完成</b>\n{telegram.esc(r['name'])}\n<code>{r.get('public_ip')}</code>")


async def _do_ensure_network(c):
    """OCI 自动建网（VCN / 网关 / 路由 / 公有子网）。"""
    t, prov, progress = c.t, c.prov, c.progress
    progress("创建 VCN、互联网网关、路由表与公有子网…")
    r = await asyncio.to_thread(prov.ensure_network)
    _update(t["id"], status="done", message=f"已创建 VCN 与公有子网 {r['subnet_id'][-16:]}")


async def _do_migrate(c):
    """跨云迁移。"""
    t, p, progress = c.t, c.p, c.progress
    await _migrate(t, p, progress)


async def _do_cf_delete(c):
    """CloudFront 分发：先停用、等部署完成再删除。"""
    t, p, acc, prov, checkpoint = c.t, c.p, c.acc, c.prov, c.checkpoint
    await _cf_delete(t, p, prov, checkpoint)
    await telegram.send(f"🗑 <b>CloudFront 分发已删除</b>\n{telegram.esc(acc['name'])} / <code>{telegram.esc(p['distribution_id'])}</code>")


async def _do_resize(c):
    """改配置（Azure 改 VM 大小；OCI 改 OCPU / 内存 / 规格）。"""
    t, p, acc, prov, name, progress = c.t, c.p, c.acc, c.prov, c.name, c.progress
    if acc["provider"] == "azure":
        progress(f"调整 VM 大小为 {p['size']}（VM 会重启）…")
        await asyncio.to_thread(prov.resize, p["instance_id"], p["size"])
    else:
        progress(f"提交改配置：{p.get('shape') or '原规格'} {p.get('ocpus') or '-'} OCPU / {p.get('memory_gb') or '-'} GB…")
        await asyncio.to_thread(prov.resize, p["instance_id"], p.get("ocpus"), p.get("memory_gb"), p.get("shape"))
    _update(t["id"], status="done", message="改配置完成")
    await telegram.send(f"✅ <b>改配置完成</b>\n{telegram.esc(acc['name'])} / {telegram.esc(name)}")


async def _do_reinstall(c):
    """v1.6 重装系统。"""
    t, p, acc, prov, name, progress = c.t, c.p, c.acc, c.prov, c.name, c.progress
    await _reinstall(t, p, acc, prov, progress, name)


async def _do_net500m(c):
    """v1.6 OCI 免费 AMD 下行 500Mbps 开 / 关。"""
    t, p, prov, name, progress = c.t, c.p, c.prov, c.name, c.progress
    if p.get("enable", True):
        r = await asyncio.to_thread(prov.enable_500m, p["instance_id"], p.get("ssh_port") or 22, progress)
        dns_out = await asyncio.to_thread(dns.dns_sync, t["account_id"], p["instance_id"], r.get("public_ip"))
        _update(t["id"], status="done", message=f"已开启，新入口 IP {r.get('public_ip')}" + ("；" + "；".join(dns_out) if dns_out else ""),
                result={"public_ip": r.get("public_ip"), "hint": r.get("hint")})
        await telegram.send(f"✅ <b>下行 500Mbps 已开启</b>\n{telegram.esc(name)}\n新入口 IP <code>{r.get('public_ip')}</code>")
    else:
        r = await asyncio.to_thread(prov.disable_500m, p["instance_id"], progress)
        _update(t["id"], status="done", message="已关闭并还原原公网 IP 入站")


async def _do_foundry(c):
    """v1.6 Azure Foundry 部署模型。"""
    t, p, acc, prov, progress = c.t, c.p, c.acc, c.prov, c.progress
    r = await asyncio.to_thread(prov.foundry_deploy, p, progress)
    _update(t["id"], status="done", message=f"已部署 {r['model']} → {r['deployment']}，Endpoint {r['endpoint']}", result=r)
    await telegram.send(f"✅ <b>AI 模型已部署</b>\n{telegram.esc(acc['name'])} / {telegram.esc(r['model'])}\nEndpoint <code>{telegram.esc(r['endpoint'] or '-')}</code>")


async def _do_billing_keep(c):
    """OCI PAYG 保号账单：主区域标准层私有 bucket 里 multipart 流式上传全零对象（串行 64 MiB 分片，不落盘）。
    进度写在 result（uploaded / total / upload_id）；失败或停止时保留已传分片，再次发起会续传；删除接口会中止它。"""
    t, p, prov, progress, checkpoint, tlog = c.t, c.p, c.prov, c.progress, c.checkpoint, c.tlog
    total = int(p["size_bytes"])
    gib = 1024 ** 3
    state = {"upload_id": None, "logged": -1}

    def report(uploaded, tot, upload_id):
        state["upload_id"] = upload_id
        pct = int(uploaded * 100 / tot) if tot else 100
        _update(t["id"], quiet=True, message=f"已上传 {uploaded / gib:.2f} / {tot / gib:.2f} GiB（{pct}%）",
                result={"uploaded": uploaded, "total": tot, "upload_id": upload_id})
        if pct // 10 != state["logged"]:
            state["logged"] = pct // 10
            tlog(f"进度 {uploaded / gib:.2f} / {tot / gib:.2f} GiB（{pct}%）")
    _update(t["id"], quiet=True, result={"uploaded": 0, "total": total, "upload_id": (p.get("resume") or {}).get("upload_id")})
    r = await asyncio.to_thread(prov.billing_keep_upload, total, p.get("resume"), progress, checkpoint, report)
    if r.get("existed"):
        msg = f"对象已存在（{r['size'] / gib:.2f} GiB），未重复上传"
    else:
        msg = f"保号对象已就绪：{r['size'] / gib:.2f} GiB（{r.get('region')}，标准层）"
    _update(t["id"], status="done", message=msg, result={"uploaded": r["size"], "total": r["size"], "size": r["size"],
                                                        "region": r.get("region"), "done": True})

async def _do_aws_credit(c):
    """build 20 AWS 新号 Credit：按顺序执行活动（EC2 / Budgets / Lambda / RDS / Bedrock），每个活动用完自动清理；
    一个失败不影响后面的；全部结束后刷新一次 freetier 状态。结果写在 result.steps[key]（status=executed / failed / stopped）。
    AWS 未公开 API 操作是否计入活动，所以成功也只写「已执行，等待 AWS 识别」。"""
    from .providers.aws_credit import ACT_INFO, _Ctx, friendly
    from .routers import aws_credit as rc
    t, p, prov, progress, checkpoint, tlog = c.t, c.p, c.prov, c.progress, c.checkpoint, c.tlog
    keys = [k for k in (p.get("activities") or []) if k in ACT_INFO]
    steps, state = {}, {"current": None}

    def save(msg=None):
        kw = {"result": {"steps": steps, "current": state["current"]}, "quiet": True}
        if msg:
            kw["message"] = msg
        _update(t["id"], **kw)
    ctx = _Ctx(log=tlog, step=checkpoint, note=progress)
    for i, k in enumerate(keys, 1):
        label = ACT_INFO[k]["label"]
        state["current"] = k
        steps[k] = {"status": "running", "started": int(time.time())}
        save(f"（{i}/{len(keys)}）{label}…")
        tlog(f"===== （{i}/{len(keys)}）{label} =====")
        try:
            r = await asyncio.to_thread(prov.credit_run, k, p, ctx)
            steps[k] = {"status": "executed", "message": "已执行，等待 AWS 识别", "finished": int(time.time()),
                        "result": {x: v for x, v in (r or {}).items() if x != "reply"}}
            tlog(f"{label}：已执行，等待 AWS 识别（活动状态可能需要几分钟到几小时才更新）", "ok")
        except TaskStopped:
            steps[k] = {"status": "stopped", "message": "已停止（已创建的资源已清理）", "finished": int(time.time())}
            for k2 in keys[i:]:
                steps[k2] = {"status": "skipped", "message": "任务已停止，未执行"}
            state["current"] = None
            save()
            raise
        except Exception as e:
            msg = friendly(e, k)
            steps[k] = {"status": "failed", "message": msg, "finished": int(time.time())}
            tlog(f"{label} 失败：{msg}", "error")
        save()
    state["current"] = None
    ok = [k for k in keys if steps.get(k, {}).get("status") == "executed"]
    tlog("刷新 AWS Free Tier 活动状态…")
    st = await asyncio.to_thread(rc.fetch_state, prov)
    if st.get("state") != "error":
        st["updated_at"] = services.now_local().strftime("%Y-%m-%d %H:%M:%S")
        rc.credits_store(t["account_id"], st)
    if st.get("state") == "ok":
        cur = {a.get("key"): a.get("status") for a in st.get("activities") or [] if a.get("key")}
        tlog("AWS 当前状态：" + "；".join(f"{ACT_INFO[k]['label']} {rc.STATUS_TEXT.get(cur.get(k) or '', cur.get(k) or '未返回')}" for k in keys))
    else:
        tlog("读取活动状态失败：" + str(st.get("message") or ""), "warn")
    summary = "、".join(ACT_INFO[k]["label"] for k in ok)
    if len(ok) == len(keys):
        _update(t["id"], status="done", result={"steps": steps, "current": None},
                message=f"已执行 {summary}，等待 AWS 识别（以 AWS 返回的活动状态为准）")
    else:
        bad = [k for k in keys if k not in ok]
        _update(t["id"], status="failed", result={"steps": steps, "current": None},
                message=f"{len(ok)}/{len(keys)} 已执行；失败：" + "；".join(f"{ACT_INFO[k]['label']}：{steps[k].get('message')}" for k in bad)[:400])
    acc = c.acc or {}
    await telegram.send(f"🎁 <b>新号 Credit 任务 #{t['id']}</b>\n{telegram.esc(acc.get('name'))}\n已执行 {len(ok)}/{len(keys)}：{telegram.esc(summary or '-')}"
                        "\n（等待 AWS 识别，以活动状态为准）")


async def _do_onedrive_backup(c):
    """build 21 OneDrive 备份：快照 → 加密 → 上传 approot → 保留最近 N 份。成功写审计，失败 TG 通知（不抛给通用失败处理，避免重复推送）。"""
    from . import onedrive, security
    t, p, tlog = c.t, c.p, c.tlog
    trigger = p.get("trigger") or "manual"
    if p.get("slot"):
        onedrive.mark_try(p["slot"])
    try:
        r = await asyncio.to_thread(onedrive.run_backup, trigger, tlog)
    except Exception as e:   # noqa: BLE001
        msg = str(e)[:400]
        s = onedrive.state()
        onedrive.set_state(last_result="failed", last_error=msg, last_try=int(time.time()), last_trigger=trigger,
                           failed_slot=s.get("slot") if trigger == "schedule" else s.get("failed_slot"))
        _update(t["id"], status="failed", message=msg)
        s = onedrive.state()
        retry = ""
        if trigger == "schedule":
            left = onedrive.RETRY_MAX - int(s.get("slot_tries") or 0)
            retry = f"\n1 小时后自动重试（本期还剩 {left} 次）" if left > 0 else "\n本期已重试 3 次，等下一次计划时间"
        await telegram.send(f"❌ <b>OneDrive 备份失败</b>（{ {'schedule': '定时', 'tg': 'Telegram', 'manual': '手动'}.get(trigger, trigger) }）\n"
                            f"{telegram.esc(msg)}{retry}")
        return
    kb = r["size"] / 1024
    msg = f"已备份到 OneDrive：{r['name']}（{kb:.1f} KB）" + (f"，清理旧备份 {len(r['pruned'])} 个" if r["pruned"] else "")
    _update(t["id"], status="done", message=msg, result={"name": r["name"], "size": r["size"], "pruned": len(r["pruned"])})
    security.audit("-", {"schedule": "schedule", "tg": "telegram"}.get(trigger, "session"), "onedrive-backup", msg)
    if trigger == "tg":
        await telegram.send(f"✅ <b>OneDrive 备份完成</b>\n{telegram.esc(r['name'])}（{kb:.1f} KB）")


# 一次性长任务：任务类型 → 处理函数（c 为 _TaskCtx）。新增任务类型在这里登记即可。
ONCE_HANDLERS = {
    "change_ip": _do_change_ip,
    "ipv6": _do_ipv6,
    "azure_create": _do_azure_create,
    "ensure_network": _do_ensure_network,
    "migrate": _do_migrate,
    "cf_delete": _do_cf_delete,
    "resize": _do_resize,
    "reinstall": _do_reinstall,
    "net500m": _do_net500m,
    "foundry": _do_foundry,
    "billing_keep": _do_billing_keep,
    "aws_credit": _do_aws_credit,
    "onedrive_backup": _do_onedrive_backup,
}


async def _run_once(t):
    """一次性长任务：change_ip / resize / ipv6 / azure_create / ensure_network。"""
    p = json.loads(t["params"])
    panel_task = t["type"] in NO_ACCOUNT_TYPES
    acc = {"provider": "panel", "name": "面板"} if panel_task else core.get_account(t["account_id"])
    _update(t["id"], message="执行中…", attempts=1, params=dict(p, next_run=2 ** 40))
    name = p.get("name") or p.get("name_display") or str(p.get("instance_id") or "")[-12:]

    def progress(m):
        """云厂商操作中途的进度：只记录，不打断（中途打断可能留下停机/无 IP 的半成品）。"""
        _update(t["id"], message=m)

    def checkpoint(m):
        """两次尝试之间的安全点：任务被停止则退出。"""
        if is_stopped(t["id"]):
            raise TaskStopped()
        _update(t["id"], message=m)
    tlog = lambda m, lv="info": log(t["id"], m, lv)   # noqa: E731
    try:
        tlog(f"开始执行：{_summary(t['type'], p)}（{acc['provider'].upper()} · {acc['name']}）")
        prov = None if panel_task else services.provider(t["account_id"], p.get("region"))
        h = ONCE_HANDLERS.get(t["type"])
        if h:
            await h(_TaskCtx(t, p, acc, prov, name, progress, checkpoint, tlog))
        else:
            _update(t["id"], status="failed", message=f"任务类型 {t['type']} 已不再支持")
    except TaskStopped:
        log(t["id"], "任务已停止，后续步骤未执行", "warn")
    except Exception as e:
        _update(t["id"], status="failed", message=str(e)[:500])
        await telegram.send(f"❌ <b>任务 #{t['id']} {t['type']} 失败</b>\n{telegram.esc(name)}\n{telegram.esc(str(e)[:300])}"
                            + ("\n（自动换 IP，不会自动重试）" if p.get("auto") else ""))


async def _reinstall(t, p, acc, prov, progress, name):
    """v1.6 重装系统：OCI 替换引导卷 / AWS EC2 替换根卷 / Azure 保留网卡和数据盘重建。完成后新密码存入「开机密码」。"""
    core.ex("UPDATE monitors SET last_state='user:reinstall' WHERE account_id=? AND instance_id=?", (t["account_id"], p["instance_id"]))
    pw = p.get("password_login", True) not in (False, "false", 0, "0")
    if acc["provider"] == "oci":
        r = await asyncio.to_thread(prov.reinstall, p["instance_id"], p.get("os") or "Canonical Ubuntu", p.get("os_version") or None,
                                    None, p.get("disk_gb") or None, pw, p.get("ssh_key") or None, progress)
        progress("等待实例重新运行…")
        await asyncio.to_thread(prov._wait, lambda: prov.get_state(p["instance_id"]), lambda s: s == "running", 900)
    elif acc["provider"] == "aws":
        r = await asyncio.to_thread(prov.reinstall, p["instance_id"], p.get("os") or "debian-12", progress)
        for _ in range(120):
            st = await asyncio.to_thread(prov.reinstall_state, p["instance_id"], r["task"])
            if st in ("succeeded", "failed", "failed-detached"):
                break
            progress(f"替换根卷：{st}…")
            await asyncio.sleep(10)
        if st != "succeeded":
            raise RuntimeError(f"替换根卷任务 {st}")
    else:
        r = await asyncio.to_thread(prov.reinstall, p["instance_id"], p.get("os") or "debian-12", pw, p.get("ssh_key") or None, progress)
    if r.get("password"):
        cloudinit.save_instance_secret(t["account_id"], r.get("id") or p["instance_id"], r.get("name") or name, r.get("username"), r["password"])
    msg = "重装完成" + ("，新密码已存入「开机密码」" if r.get("password") else "") + (f"；{r['warning']}" if r.get("warning") else "")
    _update(t["id"], status="done", message=msg, result={k: r.get(k) for k in ("image_id", "username", "hint") if r.get(k)})
    await telegram.send(f"✅ <b>重装系统完成</b>\n{telegram.esc(acc['name'])} / {telegram.esc(name)}")


async def _cf_delete(t, p, prov, checkpoint):
    """删除 CloudFront 分发：启用中先停用 → 等部署完成（Deployed）→ 用最新 ETag 删除。AWS 不允许直接删启用中的分发。"""
    did = p["distribution_id"]
    st = await asyncio.to_thread(prov.cf_state, did)
    if st["enabled"]:
        log(t["id"], "分发仍在启用中，先停用…")
        await asyncio.to_thread(prov.cf_set_enabled, did, False)
    deadline = time.time() + CF_WAIT_SECONDS
    while True:
        st = await asyncio.to_thread(prov.cf_state, did)
        if not st["enabled"] and st["status"] == "Deployed":
            break
        if time.time() > deadline:
            raise RuntimeError(f"等待停用部署完成超时（{CF_WAIT_SECONDS // 60} 分钟），分发已停用，可稍后再删除")
        checkpoint(f"等待停用部署完成（当前 {st['status']}）…")
        await asyncio.sleep(CF_POLL_SECONDS)
    await asyncio.to_thread(prov.cf_delete, did)
    _update(t["id"], status="done", message=f"分发 {did} 已删除", result={"distribution_id": did, "deleted": True})


def _quality_accept(p, tlog=None):
    """v1.6：换 IP 的质量条件（quality_max_risk / quality_country），返回 accept(ip) -> (ok, why)；没设条件返回 None。"""
    if p.get("quality_max_risk") in (None, "") and not p.get("quality_country"):
        return None

    def accept(ip):
        q = net.ip_quality(ip)
        good, why = net.quality_ok(q, p.get("quality_max_risk"), p.get("quality_country"))
        if tlog:
            tlog(f"{ip} 质量：风险 {q.get('risk') if q.get('risk') is not None else '?'} · {q.get('country_code') or '?'} · {q.get('isp') or '?'}"
                 + ("" if good else f"（{why}）"), "info" if good else "warn")
        return good, why
    return accept


def _change_ip_retry(prov, acc, p, progress, checkpoint=None, accept=None):
    """AWS / Azure / Lightsail 换 IP；带网段要求（含 ! 排除）时重复更换直到满足或达到最大次数。"""
    def once():
        if acc["provider"] == "aws" and p.get("kind") == "lightsail":
            return prov.ls_change_ip(p["instance_id"])
        if acc["provider"] == "aws":
            return prov.change_ip(p["instance_id"], p.get("mode", "auto"), progress)
        return prov.change_ip(p["instance_id"], progress)
    cidrs = p.get("cidrs") or []
    maxt = int(p.get("max_tries") or 5) if cidrs or accept else 1
    first_old, why = None, ""
    for i in range(1, maxt + 1):
        r = once()
        first_old = first_old or r.get("old_ip")
        why = "不满足网段要求" if cidrs and not net.ip_matches(r.get("new_ip"), cidrs) else ""
        if not why and accept:
            good, why = accept(r.get("new_ip"))
            why = "" if good else (why or "质量不合格")
        if not why:
            return dict(r, old_ip=first_old, tries=i)
        if i < maxt:
            (checkpoint or progress)(f"第 {i} 次：{r.get('new_ip')} {why}，继续…")
    return dict(r, old_ip=first_old, tries=maxt, warning=f"已达最大次数，最后一个 IP {why}")


# ---------------- v1.4 换 IP 次数 / 自动换 IP 每日上限 ----------------
def today_str():
    return services.now_local().strftime("%Y-%m-%d")


def auto_ip_limit():
    try:
        return max(0, int(core.get_setting("auto_ip_daily_limit", 3)))
    except (TypeError, ValueError):
        return 3


def record_ip_change(acc_id, inst_id, auto=False, task_id=None):
    core.ex("INSERT INTO ip_changes(account_id, instance_id, ts, day, auto, task_id) VALUES(?,?,?,?,?,?)",
            (acc_id, inst_id, int(time.time()), today_str(), 1 if auto else 0, task_id))


def ip_change_usage(acc_id):
    day = today_str()
    rows = core.q("SELECT auto, COUNT(*) AS n FROM ip_changes WHERE account_id=? AND day=? GROUP BY auto", (acc_id, day))
    by = {r["auto"]: r["n"] for r in rows}
    lim = auto_ip_limit()
    return {"account_id": acc_id, "day": day, "auto_used": by.get(1, 0), "manual_used": by.get(0, 0),
            "limit": lim, "auto_left": max(0, lim - by.get(1, 0))}


async def _migrate(t, p, progress):
    """跨云迁移 = 用同一开机脚本在目标账号重建 + 切 DNS + （可选）停掉源实例。不复制磁盘数据。"""
    src_acc, dst_acc = core.get_account(p["from_account_id"]), core.get_account(t["account_id"])
    dst = services.provider(t["account_id"], p.get("region"))
    c = dict(p["create"], script=cloudinit.resolve_script(p["create"]))
    progress(f"在 {dst_acc['name']} 创建新实例…")
    if dst_acc["provider"] == "oci":
        r = await asyncio.to_thread(dst.create_instance, c)
    elif dst_acc["provider"] == "aws":
        r = await asyncio.to_thread(dst.ec2_create, c)
    else:
        r = await asyncio.to_thread(dst.create_vm, c, progress)
    if r.get("password"):
        cloudinit.save_instance_secret(t["account_id"], r["id"], r["name"], r["username"], r["password"])
    progress("等待公网 IP…")
    ip = r.get("public_ip") or await asyncio.to_thread(dst.wait_public_ip, r["id"])
    notes = [f"新实例 {r['name']}（{dst_acc['name']}）IP {ip or '未分配'}"]
    if p.get("switch_dns") and ip:
        progress("切换 DNS…")
        binds = core.q("SELECT * FROM dns_bindings WHERE account_id=? AND instance_id=?", (p["from_account_id"], p["instance_id"]))
        for b in binds:
            core.ex("INSERT OR IGNORE INTO dns_bindings(account_id,instance_id,name,zone_id,zone_name,record,proxied,v4,v6) "
                    "VALUES(?,?,?,?,?,?,?,?,?)", (t["account_id"], r["id"], r["name"], b["zone_id"], b["zone_name"],
                                                  b["record"], b["proxied"], b["v4"], 0))
            core.ex("DELETE FROM dns_bindings WHERE id=?", (b["id"],))
        notes += await asyncio.to_thread(dns.dns_sync, t["account_id"], r["id"], ip) if binds else ["源实例没有绑定域名，未切换 DNS"]
    if p.get("copy_monitor"):
        m = core.q("SELECT * FROM monitors WHERE account_id=? AND instance_id=?", (p["from_account_id"], p["instance_id"]), one=True)
        if m:
            core.ex("INSERT OR IGNORE INTO monitors(account_id,instance_id,region,kind,name,auto_start,last_state,check_port,"
                    "auto_change_ip,public_ip) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (t["account_id"], r["id"], p.get("region"), "vm", r["name"], m["auto_start"], "running",
                     m["check_port"], m["auto_change_ip"], ip))
            notes.append("已复制监控设置")
    if p.get("stop_source"):
        try:
            await asyncio.to_thread(services.instance_action, p["from_account_id"], p["instance_id"], "stop",
                                    p.get("from_region"), "vm")
            notes.append("源实例已停机（未删除）")
        except Exception as e:
            notes.append(f"源实例停机失败：{str(e)[:120]}")
    _update(t["id"], status="done", message="；".join(notes)[:500])
    await telegram.send(f"🚚 <b>迁移完成</b>\n{telegram.esc(src_acc['name'])} / {telegram.esc(p.get('name') or '')} → "
                        f"{telegram.esc(dst_acc['name'])}\n" + telegram.esc("\n".join(notes)))


TASK_RUNNERS = {"snatch": "_run_snatch"}


async def _dispatch(t):
    try:
        # 抢机是循环任务（每次只尝试一轮），其余都是一次性长任务；按名字查找，便于测试替换
        runner = globals()[TASK_RUNNERS.get(t["type"], "_run_once")]
        await runner(t)
    except Exception:
        traceback.print_exc()
    finally:
        RUNNING.discard(t["id"])


def recover_on_startup():
    """v1.5 断点续抢：服务重启时，running / queued 的抢机任务重新入队（保留已尝试次数）；
    其他类型的任务（换 IP、改配置、建网等一次性操作）重启后不会自动重做，标为 interrupted，由用户检查后手动重发。"""
    now = int(time.time())
    resumed = interrupted = 0
    for t in core.q("SELECT * FROM tasks WHERE status IN ('running','queued')"):
        if t["type"] == "snatch":
            try:
                p = json.loads(t["params"] or "{}")
            except ValueError:
                p = {}
            p["next_run"] = now + 5
            _update(t["id"], status="running", params=p, message=f"服务重启，断点续抢（已尝试 {t['attempts']} 次）")
            resumed += 1
        else:
            _update(t["id"], status="interrupted", message="服务重启时任务中断，未自动重做；请检查实例状态后手动重新发起")
            interrupted += 1
    RUNNING.clear()
    return {"resumed": resumed, "interrupted": interrupted}


async def task_loop():
    while True:
        now = int(time.time())
        for t in core.q("SELECT * FROM tasks WHERE status='running'"):
            if t["id"] in RUNNING:
                continue
            p = json.loads(t["params"])
            if p.get("next_run", 0) <= now:
                RUNNING.add(t["id"])
                asyncio.create_task(_dispatch(t))
        await asyncio.sleep(3)


# ---------------- 监控 ----------------
DOWN = {"stopped", "deallocated", "terminated", "stopping", "deallocating"}
PING_FAIL_THRESHOLD = 3


async def _reachability(m, st):
    """IP 不通检测：面板所在服务器 TCP 连接实例端口，连续失败达阈值后告警，可选自动换 IP。
    注意：检测结果反映的是「面板服务器 → 实例」的连通性。"""
    if not m.get("check_port") or st != "running" or not m.get("public_ip"):
        return
    ok = await asyncio.to_thread(net.tcp_alive, m["public_ip"], m["check_port"])
    if ok:
        if m.get("fail_count"):
            core.ex("UPDATE monitors SET fail_count=0 WHERE id=?", (m["id"],))
        return
    n = (m.get("fail_count") or 0) + 1
    core.ex("UPDATE monitors SET fail_count=? WHERE id=?", (n, m["id"]))
    if n != PING_FAIL_THRESHOLD:
        return
    text = f"📵 <b>IP 不通</b>：{telegram.esc(m['name'])} <code>{m['public_ip']}:{m['check_port']}</code> 连续 {n} 次连接失败"
    running = core.q("SELECT id FROM tasks WHERE type='change_ip' AND status='running' AND account_id=? AND params LIKE ?",
                     (m["account_id"], f'%{m["instance_id"]}%'))
    if m.get("auto_change_ip") and not running:
        u = ip_change_usage(m["account_id"])
        if u["auto_used"] >= u["limit"]:
            text += f"\n今日自动换 IP 已达上限（{u['limit']} 次/账号/天），本次不再更换"
        else:
            tid = create_task("change_ip", m["account_id"], {"instance_id": m["instance_id"], "region": m["region"],
                                                             "kind": m["kind"], "name": m["name"], "reason": "IP 不通自动更换",
                                                             "auto": True})
            record_ip_change(m["account_id"], m["instance_id"], True, tid)
            text += f"\n已自动创建换 IP 任务 #{tid}（今日第 {u['auto_used'] + 1}/{u['limit']} 次）"
    await telegram.send(text)


async def monitor_loop():
    while True:
        interval = max(1, int(core.get_setting("monitor_interval", 5) or 5)) * 60
        for m in core.q("SELECT m.*, a.provider AS _prov FROM monitors m JOIN accounts a ON a.id=m.account_id WHERE COALESCE(a.disabled,0)=0"):
            m.pop("_prov", None)
            try:
                st = await asyncio.to_thread(services.get_state, m["account_id"], m["instance_id"], m["region"], m["kind"])
            except Exception as e:
                st = "unknown"
                if m["last_state"] != "unknown":
                    await telegram.send(f"⚠️ 监控查询失败：{telegram.esc(m['name'])}\n{telegram.esc(str(e)[:200])}")
            last = m["last_state"] or ""
            user_op = last.startswith("user:")
            if st in DOWN and not user_op and last not in DOWN:
                text = f"🚨 <b>实例异常</b>：{telegram.esc(m['name'])} 当前状态 {st}"
                if m["auto_start"] and st in ("stopped", "deallocated"):
                    try:
                        await asyncio.to_thread(services.instance_action, m["account_id"], m["instance_id"],
                                                "start", m["region"], m["kind"])
                        st = "user:start"
                        text += "\n已自动发送启动指令"
                    except Exception as e:
                        text += f"\n自动启动失败：{telegram.esc(str(e)[:200])}"
                await telegram.send(text)
            try:
                await _reachability(m, st)
            except Exception as e:
                print("reachability check failed", m["id"], e, flush=True)
            # user:stop 后等稳定状态出现再恢复正常跟踪
            transitional = st in ("stopping", "starting", "pending", "deallocating", "unknown")
            st_to_save = last if (user_op and transitional) else st
            core.ex("UPDATE monitors SET last_state=? WHERE id=?", (st_to_save, m["id"]))
        await asyncio.sleep(interval)


# ---------------- 定时：AWS 账单 + 每日报告 ----------------
_last = {}


async def schedule_loop():
    while True:
        now = services.now_local()
        # AWS：15 号 / 月末，08:00 后主动刷新一次
        if now.hour >= 8 and services.is_aws_refresh_day(now.date()):
            for a in core.list_accounts():
                if a["provider"] == "aws":
                    # 失败时最多每天重试 3 次（间隔 ≥1 小时），防止异常时每分钟反复调用收费的 CE
                    key = f"aws_sched_try_{a['id']}"
                    st = core.get_setting(key) or {}
                    day = now.strftime("%Y-%m-%d")
                    if st.get("day") != day:
                        st = {"day": day, "n": 0, "last": 0}
                    if st["n"] >= 3 or time.time() - st["last"] < 3600:
                        continue
                    try:
                        b = await asyncio.to_thread(services.aws_billing, a["id"], False, True)
                        if not b["cached"]:
                            st = {"day": day, "n": 99, "last": time.time()}   # 今日已成功
                    except Exception as e:
                        st.update(n=st["n"] + 1, last=time.time())
                        print("aws billing refresh failed", a["id"], e, flush=True)
                    core.set_setting(key, st)
        # 每日账号健康度（07:30 后跑一次）
        today = now.strftime("%Y-%m-%d")
        if now.strftime("%H:%M") >= "07:30" and core.get_setting("last_health_date") != today:
            core.set_setting("last_health_date", today)
            for a in core.list_accounts():
                try:
                    r = await asyncio.to_thread(health.compute, a["id"])
                    txt = health.alert_text(r)
                    if txt:
                        await telegram.send(txt)
                except Exception as e:
                    print("health check failed", a["id"], e, flush=True)
        # v1.4 流量守护：关机 M 小时到期 → 自动开机（失败只告警，不重试）
        for g in traffic_guard.resume_due():
            try:
                txt = await asyncio.to_thread(traffic_guard.resume, g)
                if txt:
                    await telegram.send(txt)
            except Exception as e:
                print("traffic guard resume failed", g["id"], e, flush=True)
        # v1.4 Credit / 教育优惠到期提醒（30/7/1 天各推一次；每小时检查一次）
        if time.time() - _last.get("expiry", 0) >= 3600:
            _last["expiry"] = time.time()
            try:
                for a in credits.pending_notifications():
                    await telegram.send("⏰ <b>即将到期</b>\n" + telegram.esc(credits.alert_line(a)))
            except Exception as e:
                print("expiry check failed", e, flush=True)
        # v1.4 有 Credit 的 OCI / Azure 账号每天记录一次账单（免费接口），用于估算 Credit 已用额度
        if now.hour >= 8 and core.get_setting("last_billing_record_date") != today:
            core.set_setting("last_billing_record_date", today)
            for a in core.q("SELECT DISTINCT a.id FROM accounts a JOIN aws_credits c ON c.account_id=a.id WHERE a.provider IN ('oci','azure')"):
                try:
                    await asyncio.to_thread(services.billing, a["id"])
                except Exception as e:
                    print("billing record failed", a["id"], e, flush=True)
        # 流量守护（月度每 30 分钟、滚动窗口每 10 分钟查一次平台指标）
        for g in traffic_guard.due():
            try:
                txt = await asyncio.to_thread(traffic_guard.check, g)
                if txt:
                    await telegram.send(txt)
            except Exception as e:
                core.ex("UPDATE traffic_guards SET checked_at=? WHERE id=?", (int(time.time()), g["id"]))
                print("traffic guard failed", g["id"], e, flush=True)
        # build 22 流量守护限速：月度跨月解除（不查云指标）+ agent 离线提醒
        try:
            for txt in traffic_guard.release_due() + traffic_guard.agent_alerts():
                await telegram.send(txt)
        except Exception as e:
            print("traffic guard agent check failed", e, flush=True)
        # build 22 流量明细：每天清理一次 90 天前的按日记录
        if core.get_setting("last_port_prune_date") != now.strftime("%Y-%m-%d"):
            core.set_setting("last_port_prune_date", now.strftime("%Y-%m-%d"))
            try:
                from . import port_traffic
                port_traffic.prune()
            except Exception as e:
                print("port traffic prune failed", e, flush=True)
        # build 21 OneDrive 定期备份（每天 / 每周 HH:MM，面板时区；失败 1 小时后重试，每期最多 3 次）
        try:
            from . import onedrive
            key = onedrive.due(now)
            if key and not core.q("SELECT 1 FROM tasks WHERE type='onedrive_backup' AND status='running'", one=True):
                onedrive.mark_try(key)
                create_task("onedrive_backup", 0, {"name": "OneDrive 备份", "trigger": "schedule"})
        except Exception as e:
            print("onedrive schedule failed", e, flush=True)
        # 每日账单报告
        if core.get_setting("daily_report", False):
            hhmm = core.get_setting("report_time", "09:00")
            today = now.strftime("%Y-%m-%d")
            if now.strftime("%H:%M") >= hhmm and core.get_setting("last_report_date") != today:
                core.set_setting("last_report_date", today)
                await telegram.send(await asyncio.to_thread(telegram.billing_report))
        await asyncio.sleep(60)
