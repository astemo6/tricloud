"""build 22：按端口 / 服务的流量明细（实例上自装的 tricloud-guard agent 用 nftables / iptables 计数规则统计，只计数、不拦截）。

agent 每 5 分钟随心跳 POST 一次「上次成功上报以来的增量」，每行：`协议 端口 进程名 入站字节 出站字节`
（协议 tcp / udp；非监听端口的流量——比如本机主动访问外网——记为 `other 0 - 入 出`）。
面板按「守护 × 面板时区的日期 × 协议 × 端口」累加，保留 90 天；只能凭守护专属 token 写本守护的数据。
"""
import datetime as dt
import html
import re
import time

from . import core, services

RETAIN_DAYS = 90
MAX_LINES = 400                 # 单次上报最多行数（agent 最多 64 个端口 × 2 协议 + other）
MAX_BODY = 64 * 1024
MAX_BYTES_PER_LINE = 50 * 1024 ** 4    # 单行单方向 5 分钟增量的合理上限（50 TiB，防止脏数据把统计撑爆）
PROTOS = ("tcp", "udp", "other")
PROC_RE = re.compile(r"^[A-Za-z0-9._:@/+\-]{1,40}$")
OTHER_LABEL = "其他/出站连接"



def parse_report(text):
    """解析 agent 上报正文。返回 (rows, bad)：rows = [(proto, port, proc, in, out)]，同一 (proto, port) 合并；格式不对的行计入 bad 并丢弃。"""
    rows, bad = {}, 0
    for n, line in enumerate((text or "").splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if n >= MAX_LINES:
            bad += 1
            continue
        p = line.split()
        if len(p) != 5:
            bad += 1
            continue
        proto, port, proc, bi, bo = p
        proto = proto.lower()
        if proto not in PROTOS or not port.isdigit() or not bi.isdigit() or not bo.isdigit():
            bad += 1
            continue
        port, bi, bo = int(port), int(bi), int(bo)
        if proto == "other":
            port, proc = 0, "-"
        elif not 0 < port < 65536:
            bad += 1
            continue
        if bi > MAX_BYTES_PER_LINE or bo > MAX_BYTES_PER_LINE:
            bad += 1
            continue
        if not PROC_RE.match(proc):
            proc = "-"
        k = (proto, port)
        if k in rows:
            o = rows[k]
            rows[k] = (proto, port, proc if proc != "-" else o[2], o[3] + bi, o[4] + bo)
        else:
            rows[k] = (proto, port, proc, bi, bo)
    return list(rows.values()), bad


def today(now=None):
    return (dt.datetime.fromtimestamp(now, services.tz()) if now else services.now_local()).strftime("%Y-%m-%d")


def record(gid, rows, now=None):
    """把一次上报的增量累加到当天（面板时区）。只写这条守护（gid 由 token 反查得到，agent 无法指定）。"""
    day = today(now)
    ts = int(now or time.time())
    n = 0
    with core.db() as c:
        for proto, port, proc, bi, bo in rows:
            if not bi and not bo:
                continue
            c.execute("INSERT INTO guard_port_traffic(guard_id,day,proto,port,proc,bytes_in,bytes_out,updated) VALUES(?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(guard_id,day,proto,port) DO UPDATE SET bytes_in=bytes_in+excluded.bytes_in, "
                      "bytes_out=bytes_out+excluded.bytes_out, updated=excluded.updated, "
                      "proc=CASE WHEN excluded.proc!='-' THEN excluded.proc ELSE guard_port_traffic.proc END",
                      (gid, day, proto, port, proc, bi, bo, ts))
            n += 1
        c.execute("UPDATE traffic_guards SET acct_seen=? WHERE id=?", (ts, gid))
    return n


def prune(now=None, days=RETAIN_DAYS):
    cutoff = (dt.datetime.fromtimestamp(now or time.time(), services.tz()).date() - dt.timedelta(days=days - 1)).strftime("%Y-%m-%d")
    with core.db() as c:
        return c.execute("DELETE FROM guard_port_traffic WHERE day<?", (cutoff,)).rowcount


def delete_guard(gid):
    core.ex("DELETE FROM guard_port_traffic WHERE guard_id=?", (gid,))


def label(r):
    if r["proto"] == "other":
        return OTHER_LABEL
    proc = r.get("proc") or "-"
    return f"{r['port']}/{r['proto']}" + (f" · {proc}" if proc != "-" else "")


def _range(rng, now=None):
    d = dt.datetime.fromtimestamp(now or time.time(), services.tz()).date()
    if rng == "today":
        return d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"), "今日"
    if rng == "month":
        return d.replace(day=1).strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"), "本月"
    raise ValueError("range 只能是 today / month")


def top(gid, rng="today", limit=20, now=None):
    """今日 / 本月按端口和按服务（进程名）的 Top 列表（入站、出站、合计、占比）。"""
    start, end, title = _range(rng, now)
    limit = max(1, min(100, int(limit or 20)))
    raw = core.q("SELECT proto, port, MAX(proc) AS proc0, SUM(bytes_in) AS bin, SUM(bytes_out) AS bout, MAX(updated) AS upd "
                 "FROM guard_port_traffic WHERE guard_id=? AND day BETWEEN ? AND ? GROUP BY proto, port", (gid, start, end))
    # 进程名取最新一天记录的（端口换了服务时显示当前的）
    latest = {(r["proto"], r["port"]): r["proc"] for r in core.q(
        "SELECT proto, port, proc FROM guard_port_traffic WHERE guard_id=? AND day BETWEEN ? AND ? ORDER BY day", (gid, start, end))}
    rows = []
    for r in raw:
        proc = latest.get((r["proto"], r["port"])) or r["proc0"] or "-"
        x = {"proto": r["proto"], "port": r["port"], "proc": proc, "in": int(r["bin"] or 0), "out": int(r["bout"] or 0)}
        x["total"] = x["in"] + x["out"]
        x["label"] = label(x)
        rows.append(x)
    tin, tout = sum(r["in"] for r in rows), sum(r["out"] for r in rows)
    tot = tin + tout
    svc = {}
    for r in rows:
        name = OTHER_LABEL if r["proto"] == "other" else (r["proc"] if r["proc"] != "-" else f"端口 {r['port']}")
        s = svc.setdefault(name, {"service": name, "in": 0, "out": 0, "ports": []})
        s["in"] += r["in"]
        s["out"] += r["out"]
        if r["proto"] != "other":
            s["ports"].append(f"{r['port']}/{r['proto']}")
    services_ = []
    for s in svc.values():
        s["total"] = s["in"] + s["out"]
        s["ports"] = sorted(set(s["ports"]), key=lambda p: (int(p.split("/")[0]), p))
        services_.append(s)

    def finish(lst):
        lst.sort(key=lambda r: (-r["total"], r.get("label") or r.get("service")))
        for r in lst:
            r["pct"] = round(r["total"] * 100.0 / tot, 1) if tot else 0
            r["in_text"], r["out_text"], r["total_text"] = fmt_bytes(r["in"]), fmt_bytes(r["out"]), fmt_bytes(r["total"])
        return lst[:limit]
    upd = max([r["upd"] or 0 for r in raw] or [0])
    return {"range": rng, "title": title, "start": start, "end": end, "ports": finish(rows), "services": finish(services_),
            "total_in": tin, "total_out": tout, "total": tot, "total_text": fmt_bytes(tot), "in_text": fmt_bytes(tin),
            "out_text": fmt_bytes(tout), "updated_at": upd or None, "count": len(rows)}


def fmt_bytes(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.2f} {u}"
        n /= 1024
    return f"{n:.2f} TB"


def tg_report(arg=""):
    """TG /ports [实例]：本月按端口 / 服务 Top。实例按守护名或实例 ID（尾部）匹配；不带参数时列出开了流量明细的实例。"""
    gs = core.q("SELECT id, name, instance_id, acct_enabled, acct_seen FROM traffic_guards ORDER BY id")
    have = [g for g in gs if g.get("acct_enabled") or g.get("acct_seen")]
    arg = (arg or "").strip()
    if not arg:
        if not have:
            return "还没有实例开启「流量明细」。在面板「流量守护」里打开流量明细并在实例上安装 agent。"
        return "用法：/ports 实例名\n已开启流量明细的实例：\n" + "\n".join(
            f"· {html.escape(g['name'] or g['instance_id'][-12:])}" for g in have)
    al = arg.lower()
    hit = [g for g in gs if (g["name"] or "").lower() == al] or \
          [g for g in gs if al in (g["name"] or "").lower() or g["instance_id"].lower().endswith(al)]
    if not hit:
        return f"没有找到实例「{html.escape(arg)}」的流量守护"
    if len(hit) > 1:
        return "匹配到多个实例，请写得更具体：\n" + "\n".join(f"· {html.escape(g['name'] or g['instance_id'][-12:])}" for g in hit[:10])
    g = hit[0]
    t = top(g["id"], "month", 10)
    name = html.escape(g["name"] or g["instance_id"][-12:])
    if not t["ports"]:
        return f"📊 {name}：本月还没有流量明细" + ("" if g.get("acct_enabled") else "（流量明细未开启）")
    lines = [f"📊 <b>{name}</b> 本月端口流量（{t['start'][5:]}~{t['end'][5:]}）",
             f"合计 {t['total_text']}（入 {t['in_text']} / 出 {t['out_text']}）", "", "<b>按端口 Top</b>"]
    for i, r in enumerate(t["ports"], 1):
        lines.append(f"{i}. {html.escape(r['label'])}：{r['total_text']}（入 {r['in_text']} / 出 {r['out_text']}，{r['pct']:g}%）")
    lines += ["", "<b>按服务</b>"]
    for r in t["services"][:5]:
        lines.append(f"· {html.escape(r['service'])}：{r['total_text']}（{r['pct']:g}%）")
    return "\n".join(lines)
