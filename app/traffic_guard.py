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
import hashlib
import html
import json
import os
import re
import secrets
import time

from . import core, services

# 各家每月免费出站流量（GB），作为新建守护时的默认上限
DEFAULT_LIMIT = {"oci": 10240, "aws": 100, "azure": 100}
CHECK_EVERY = 30 * 60
ROLLING_CHECK_EVERY = 10 * 60      # 滚动窗口更看重及时性
DIRECTIONS = ("out", "in", "both")
DIR_TEXT = {"out": "出站", "in": "入站", "both": "双向"}
ACTIONS = ("notify", "stop", "throttle")
# build 22「推送并限速」：实例上自装的 tc agent 每 5 分钟拉一次状态；15 分钟没心跳算离线
THROTTLE_DEFAULT_MBPS = 1.0
THROTTLE_MIN_MBPS, THROTTLE_MAX_MBPS = 0.1, 10000
AGENT_POLL_SECS = 300
AGENT_OFFLINE_SECS = 15 * 60
AGENT_DIR = os.path.join(os.path.dirname(__file__), "guard_agent")


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
    rolling = g.get("mode") == "rolling"
    month = services.now_local().strftime("%Y-%m")
    notified = g["notified"] if (rolling or g.get("month") == month) else 0
    used = measure(g)
    limit = float(g["limit_gb"] or 1)
    pct = used / limit * 100
    lvl = 2 if pct >= 100 else (1 if pct >= int(g.get("warn_pct") or 80) else 0)
    text = None
    name = html.escape(g.get("name") or g["instance_id"][-12:])
    scope = scope_text(g)
    extra = {}
    if act and lvl > notified:
        if lvl == 1:
            text = (f"📈 <b>流量预警</b>：{name}\n{scope}已用 <b>{used:.1f} GB</b> / {limit:g} GB（{pct:.0f}%）"
                    + ("\n到达上限后将自动停机" if g.get("action") == "stop" else "")
                    + (f"\n到达上限后将限速到 {throttle_mbps(g):g} Mbps" if g.get("action") == "throttle" else ""))
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
                        text += ("\n已自动停机（不会自动开机，请手动启动）" if rolling
                                 else "\n已自动停机（下月 1 日不会自动开机，请手动启动）")
                except Exception as e:
                    text += f"\n自动停机失败：{html.escape(str(e)[:200])}"
            elif g.get("action") == "throttle":
                mbps = throttle_mbps(g)
                extra = {"throttled": 1, "throttled_at": int(time.time()), "state_msg": f"超限限速 {mbps:g} Mbps（出站）"}
                if agent_online(g):
                    text += f"\n已下发限速：出站 {mbps:g} Mbps，SSH 端口不限（agent 最长约 5 分钟内生效）"
                else:
                    text += ("\n⚠️ <b>无法限速</b>：这台实例的限速 agent " + ("离线（最后心跳 " + fmt_ts(g["agent_seen"]) + "）" if g.get("agent_seen")
                                                                          else "尚未安装") + "，agent 上线后才会生效")
                text += "\n" + ("滚动窗口回落到上限以下后自动解除" if rolling else "下月 1 日自动解除")
        notified = lvl
    elif lvl < notified:      # 改了上限 / 跨月后回落 / 滚动窗口回落
        notified = lvl
    if lvl < 2 and g.get("throttled") and not extra:
        extra = {"throttled": 0, "throttled_at": None, "state_msg": "用量已回落，已解除限速"}
        text = (f"✅ <b>已解除限速</b>：{name}\n{scope}已用 {used:.1f} GB / {limit:g} GB，回落到上限以下"
                + ("" if agent_online(g) else "\n（agent 当前离线，上线后才会清除限速）"))
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
        g.pop("_prov", None)
        if g.get("enabled") == 0 or (g.get("state") == "tripped" and g.get("resume_at")):
            continue   # 停用 / 等待自动开机期间不检查
        every = ROLLING_CHECK_EVERY if g.get("mode") == "rolling" else CHECK_EVERY
        if now - (g["checked_at"] or 0) >= every:
            out.append(g)
    return out


def resume_due():
    """关机 M 小时到期、需要自动开机的规则。"""
    now = int(time.time())
    return core.q("SELECT * FROM traffic_guards WHERE state='tripped' AND resume_at IS NOT NULL AND resume_at<=?", (now,))


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
    if g.get("throttled"):
        return "throttled"
    if g.get("state") == "tripped":
        return "tripped"
    if g.get("state") == "resume_failed":
        return "resume_failed"
    if g.get("enabled") == 0:
        return "disabled"
    pct = g.get("last_pct") or 0
    return "over" if pct >= 100 else "warn" if pct >= int(g.get("warn_pct") or 80) else "ok"


STATUS_TEXT = {"ok": "正常", "warn": "已到预警", "over": "已超限", "tripped": "已触发关机", "resume_failed": "自动开机失败",
               "disabled": "已停用", "throttled": "已限速"}


# ================= build 22：限速 + 流量明细 agent =================
TOKEN_RE = re.compile(r"^tg_[A-Za-z0-9_-]{20,80}$")


def throttle_mbps(g):
    try:
        v = float(g.get("throttle_mbps") or THROTTLE_DEFAULT_MBPS)
    except (TypeError, ValueError):
        v = THROTTLE_DEFAULT_MBPS
    return min(THROTTLE_MAX_MBPS, max(THROTTLE_MIN_MBPS, v))


def agent_online(g, now=None):
    seen = g.get("agent_seen") or 0
    return bool(seen) and (now or time.time()) - seen < AGENT_OFFLINE_SECS


def token_hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


def agent_token(gid, reset=False):
    """返回这条守护的 agent token（没有就生成）。Fernet 加密存库（面板要能再次显示安装命令），另存 sha256 用于查找。"""
    g = core.q("SELECT id, agent_token_enc FROM traffic_guards WHERE id=?", (gid,), one=True)
    if not g:
        return None
    if g.get("agent_token_enc") and not reset:
        try:
            return core.decrypt(g["agent_token_enc"])
        except Exception:   # noqa: BLE001  key 变了（恢复了别的备份）→ 重新生成
            pass
    t = "tg_" + secrets.token_urlsafe(32)
    core.ex("UPDATE traffic_guards SET agent_token_enc=?, agent_token_hash=?, agent_seen=NULL, agent_info=NULL, agent_alerted=0 WHERE id=?",
            (core.encrypt(t), token_hash(t), gid))
    return t


def guard_by_token(t):
    if not t or not TOKEN_RE.match(t):
        return None
    return core.q("SELECT * FROM traffic_guards WHERE agent_token_hash=?", (token_hash(t),), one=True)


def wants_throttle(g):
    return g.get("action") == "throttle" and g.get("enabled") != 0 and bool(g.get("throttled"))


_INFO_RE = {"iface": re.compile(r"^[\w.@:-]{1,32}$"), "ssh": re.compile(r"^[0-9,]{1,64}$"), "applied": re.compile(r"^[01]$"),
            "v": re.compile(r"^[0-9]{1,4}$"), "acct": re.compile(r"^(nft|iptables|none|off)$"), "nports": re.compile(r"^[0-9]{1,4}$")}
ACCT_BACKEND_TEXT = {"nft": "nftables", "iptables": "iptables", "none": "无可用计数后端（需要 nft 或 iptables）", "off": "未启用"}


def agent_heartbeat(g, params):
    """agent 拉状态时顺带上报（只收白名单字段，格式不对丢弃）；返回给 agent 的状态。"""
    info = {k: str(params.get(k)) for k, rx in _INFO_RE.items() if params.get(k) is not None and rx.match(str(params.get(k)))}
    now = int(time.time())
    core.ex("UPDATE traffic_guards SET agent_seen=?, agent_info=?, agent_alerted=0 WHERE id=?", (now, json.dumps(info), g["id"]))
    on = wants_throttle(g)
    mbps = throttle_mbps(g)
    return {"throttle": on, "rate_mbps": mbps if on else 0, "rate_kbit": int(round(mbps * 1000)) if on else 0, "interval": AGENT_POLL_SECS,
            "acct": bool(g.get("acct_enabled"))}


def agent_view(g, now=None):
    """给面板 / App 的 agent 状态（不含 token）：在线 / 最后心跳 / 当前是否已限速 / 流量明细计数后端与端口数。"""
    try:
        info = json.loads(g.get("agent_info") or "{}")
    except ValueError:
        info = {}
    applied = info.get("applied") == "1"
    be = info.get("acct")
    return {"installed": bool(g.get("agent_seen")), "online": agent_online(g, now), "last_seen": g.get("agent_seen"),
            "last_seen_text": fmt_ts(g["agent_seen"]) if g.get("agent_seen") else None, "iface": info.get("iface"),
            "ssh_ports": info.get("ssh"), "applied": applied, "version": info.get("v"),
            "acct_enabled": bool(g.get("acct_enabled")), "acct_backend": be, "acct_backend_text": ACCT_BACKEND_TEXT.get(be) if be else None,
            "acct_ports": int(info["nports"]) if info.get("nports") else None, "acct_active": be in ("nft", "iptables"),
            "acct_seen": g.get("acct_seen"), "acct_seen_text": fmt_ts(g["acct_seen"]) if g.get("acct_seen") else None}


def install_commands(base, token):
    base = base.rstrip("/")
    return {"install": f"curl -fsSL '{base}/api/guard-agent/install.sh?token={token}' | sudo bash",
            "uninstall": f"curl -fsSL '{base}/api/guard-agent/uninstall.sh' | sudo bash",
            "uninstall_local": "sudo tricloud-guard uninstall", "status": "sudo tricloud-guard status"}


def agent_script():
    with open(os.path.join(AGENT_DIR, "tricloud-guard.sh"), encoding="utf-8") as f:
        return f.read()


def render_install(base, token):
    """生成安装脚本：只替换面板地址与 token（都已校验，不含引号 / 空白），agent 正文原样嵌入 quoted heredoc。"""
    if not re.match(r"^https?://[A-Za-z0-9.\-:\[\]]+(/[A-Za-z0-9._~/-]*)?$", base) or not TOKEN_RE.match(token):
        raise ValueError("面板地址或 token 无效")
    agent = agent_script().rstrip("\n")
    if "TRICLOUD_AGENT_EOF" in agent:
        raise ValueError("agent 脚本包含保留标记")
    with open(os.path.join(AGENT_DIR, "install.sh"), encoding="utf-8") as f:
        tpl = f.read()
    return tpl.replace("__PANEL__", base.rstrip("/")).replace("__TOKEN__", token).replace("__AGENT__", agent)


def uninstall_script():
    with open(os.path.join(AGENT_DIR, "uninstall.sh"), encoding="utf-8") as f:
        return f.read()


def release_due():
    """月度模式：跨月了还在限速 → 直接解除（不依赖查云指标）。返回要推送的文本列表。"""
    month = services.now_local().strftime("%Y-%m")
    out = []
    for g in core.q("SELECT * FROM traffic_guards WHERE throttled=1 AND COALESCE(mode,'monthly')='monthly' AND COALESCE(month,'')!=?", (month,)):
        core.ex("UPDATE traffic_guards SET throttled=0, throttled_at=NULL, notified=0, month=?, state_msg=?, checked_at=0 WHERE id=?",
                (month, "新的月份，已解除限速", g["id"]))
        out.append(f"✅ <b>已解除限速</b>：{html.escape(g.get('name') or g['instance_id'][-12:])}\n新的月份（{month}），流量重新计算")
    # 改成别的动作 / 停用的规则：限速标记清掉（agent 下次拉取时也会解除）
    core.ex("UPDATE traffic_guards SET throttled=0, throttled_at=NULL WHERE throttled=1 AND (action!='throttle' OR enabled=0)")
    return out


def agent_alerts(now=None):
    """「推送并限速」的规则：agent 装过但超过 15 分钟没心跳 → TG 提醒一次「无法限速」，恢复心跳后重置。"""
    now = now or time.time()
    out = []
    for g in core.q("SELECT * FROM traffic_guards WHERE action='throttle' AND COALESCE(enabled,1)=1 AND agent_seen IS NOT NULL "
                    "AND COALESCE(agent_alerted,0)=0 AND agent_seen<?", (int(now - AGENT_OFFLINE_SECS),)):
        core.ex("UPDATE traffic_guards SET agent_alerted=1 WHERE id=?", (g["id"],))
        out.append(f"⚠️ <b>限速 agent 离线</b>：{html.escape(g.get('name') or g['instance_id'][-12:])}\n最后心跳 {fmt_ts(g['agent_seen'])}，"
                   + ("当前应限速但<b>无法限速</b>" if g.get("throttled") else "超限时将<b>无法限速</b>")
                   + "\n请检查实例上的 tricloud-guard.timer（sudo tricloud-guard status）")
    return out
