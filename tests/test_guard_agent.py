"""build 22 流量守护 agent：「推送并限速」+ 按端口 / 服务的流量明细。
后端：迁移、保存 / 校验、token（加密存储 + 哈希查找、不回传）、agent 接口（GET/POST state、install / uninstall 脚本）、限速状态机
（超限限速、在线 / 离线文案、回落解除、跨月解除、离线提醒、手动解除）、流量明细（上报解析、只写本守护、按日聚合、今日 / 本月 Top、
占比、其他/出站连接、90 天清理、删除守护连带删除）、API Token 规则（reset 403、GET 不给命令）、审计、TG /traffic /ports。
agent：bash -n + shellcheck、tc 命令生成、监听端口解析（含 Docker 映射）、nft / iptables 计数规则（只计数）、
用假 nft / iptables / ss / tc / ip / sshd / docker 跑 run：建表、增量上报、失败补报、端口变化重建、关闭 / 401 删除、卸载清理；
最后用真实 curl 对本进程起的 uvicorn 跑一次端到端。"""
import asyncio
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

from fastapi.testclient import TestClient

from app import core, main, port_traffic, tasks, telegram, traffic_guard
from app.providers.aws_provider import AWSProvider

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


async def noop():
    await asyncio.sleep(3600)


for f in ("task_loop", "monitor_loop", "schedule_loop"):
    setattr(tasks, f, noop)
telegram.poll_loop = noop
sent = []


async def fake_send(text, *a, **k):
    sent.append(text)
    return True
telegram.send = fake_send

AG = os.path.join(ROOT, "app", "guard_agent")
SC = shutil.which("shellcheck") or os.path.join(ROOT, "..", "work", ".venv", "bin", "shellcheck")
HAVE_SC = os.path.exists(SC)

c = TestClient(main.app)
c.__enter__()
c.post("/api/login", json={"password": "devpassword123"})
with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
    aid = c.post("/api/accounts", json={"provider": "aws", "name": "aws1",
                                        "cred": {"access_key": "AK", "secret_key": "s", "region": "us-east-1"}}).json()["id"]

# ================= 1. 迁移 =================
cols = {r["name"] for r in core.q("PRAGMA table_info(traffic_guards)")}
ok("migrate: throttle / agent / acct columns", {"throttle_mbps", "throttled", "throttled_at", "agent_token_enc", "agent_token_hash",
                                                "agent_seen", "agent_info", "agent_alerted", "acct_enabled", "acct_seen"} <= cols)
pcols = {r["name"] for r in core.q("PRAGMA table_info(guard_port_traffic)")}
ok("migrate: guard_port_traffic table", {"guard_id", "day", "proto", "port", "proc", "bytes_in", "bytes_out", "updated"} <= pcols)
core.migrate()
ok("migrate: idempotent", {"acct_enabled"} <= {r["name"] for r in core.q("PRAGMA table_info(traffic_guards)")})

# ================= 2. 保存 / 校验 =================
use = {"out_gb": 10.0, "in_gb": 1.0}
P_USAGE = mock.patch.object(traffic_guard, "usage", lambda g: dict(use))
P_USAGE.start()
r = c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-thr", "name": "tokyo", "action": "throttle", "limit_gb": 100})
ok("save throttle guard 200", r.status_code == 200)
g = c.get("/api/traffic-guards").json()[0]
GID = g["id"]
ok("view: action throttle + default 1 Mbps", g["action"] == "throttle" and g["throttle_mbps"] == 1.0 and g["throttled"] == 0)
ok("view: no token fields", not any(k in g for k in ("agent_token_enc", "agent_token_hash", "agent_info", "agent_alerted")))
ok("view: agent block (not installed, offline)", g["agent"] and g["agent"]["installed"] is False and g["agent"]["online"] is False)
row = core.q("SELECT * FROM traffic_guards WHERE id=?", (GID,), one=True)
ok("token generated on throttle save, encrypted + hashed", row["agent_token_enc"] and row["agent_token_hash"] and "tg_" not in row["agent_token_enc"])
TOKEN = core.decrypt(row["agent_token_enc"])
ok("token format tg_ + urlsafe", traffic_guard.TOKEN_RE.match(TOKEN) and row["agent_token_hash"] == traffic_guard.token_hash(TOKEN))
for bad, why in ((0, "0"), (0.05, "too small"), (20000, "too big"), ("abc", "not number")):
    ok(f"throttle_mbps {why} -> 400", c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-thr", "action": "throttle",
                                                                          "throttle_mbps": bad}).status_code == 400)
r = c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-thr", "name": "tokyo", "action": "throttle", "limit_gb": 100,
                                        "throttle_mbps": 2.5})
ok("throttle_mbps 2.5 saved", c.get("/api/traffic-guards").json()[0]["throttle_mbps"] == 2.5)
ok("token unchanged on re-save", traffic_guard.agent_token(GID) == TOKEN)
ok("unknown action -> notify", c.post("/api/traffic-guards", json={"account_id": aid, "instance_id": "i-n", "name": "n1", "action": "boom"}).status_code == 200
   and core.q("SELECT action FROM traffic_guards WHERE instance_id='i-n'", one=True)["action"] == "notify")
GN = core.q("SELECT id FROM traffic_guards WHERE instance_id='i-n'", one=True)["id"]
ok("notify guard without acct: no token yet", not core.q("SELECT agent_token_hash FROM traffic_guards WHERE id=?", (GN,), one=True)["agent_token_hash"])

# ================= 3. agent 信息接口 / 安装脚本 =================
BASE = "https://panel.example.com"
info = c.get(f"/api/traffic-guards/{GID}/agent?base={BASE}").json()
ok("agent info: install cmd with base + token", info["commands"]["install"] == f"curl -fsSL '{BASE}/api/guard-agent/install.sh?token={TOKEN}' | sudo bash")
ok("agent info: uninstall cmds", "uninstall.sh" in info["commands"]["uninstall"] and info["commands"]["uninstall_local"] == "sudo tricloud-guard uninstall")
ok("agent info: poll 300 / offline 900 / throttle_mbps", info["poll_secs"] == 300 and info["offline_secs"] == 900 and info["throttle_mbps"] == 2.5)
ok("agent info: bad base falls back to host header", c.get(f"/api/traffic-guards/{GID}/agent?base=javascript:alert(1)").json()["commands"]["install"]
   .startswith("curl -fsSL 'http://testserver/api/guard-agent/install.sh"))
ok("agent info: 404 unknown guard", c.get("/api/traffic-guards/9999/agent").status_code == 404)
r = c.get(f"/api/guard-agent/install.sh?token={TOKEN}&base={BASE}")
SH = r.text
ok("install.sh 200 shellscript no-store", r.status_code == 200 and "shellscript" in r.headers["content-type"] and r.headers.get("cache-control") == "no-store")
ok("install.sh embeds panel + token + agent", f"PANEL='{BASE}'" in SH and f"TOKEN='{TOKEN}'" in SH and "acct_sync()" in SH and "__AGENT__" not in SH)
ok("install.sh: timer every 5 min + oneshot service", "OnUnitActiveSec=5min" in SH and "Type=oneshot" in SH and "conf（0600）" in SH)
ok("install.sh audited (guard-agent-install)", any(a["action"] == "guard-agent-install" for a in c.get("/api/audit").json()))
r = c.get("/api/guard-agent/install.sh?token=tg_" + "a" * 43)
ok("install.sh bad token -> 404 + exit 1 script", r.status_code == 404 and "exit 1" in r.text)
ok("install.sh no token -> 404", c.get("/api/guard-agent/install.sh").status_code == 404)
ok("uninstall.sh public 200", c.get("/api/guard-agent/uninstall.sh").status_code == 200 and "tricloud_acct" in c.get("/api/guard-agent/uninstall.sh").text)
with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
    f.write(SH)
ok("rendered install.sh: bash -n", subprocess.run(["bash", "-n", f.name]).returncode == 0)
if HAVE_SC:
    for nm, path in (("rendered install.sh", f.name), ("tricloud-guard.sh", os.path.join(AG, "tricloud-guard.sh")),
                     ("install.sh template", os.path.join(AG, "install.sh")), ("uninstall.sh", os.path.join(AG, "uninstall.sh"))):
        p = subprocess.run([SC, "-s", "bash", path], capture_output=True, text=True)
        ok(f"shellcheck clean: {nm}", p.returncode == 0 or print(p.stdout[:2000]))
else:
    ok("shellcheck available", False)
for nm in ("tricloud-guard.sh", "uninstall.sh"):
    ok(f"bash -n {nm}", subprocess.run(["bash", "-n", os.path.join(AG, nm)]).returncode == 0)
try:
    traffic_guard.render_install("https://x.com/'; rm -rf /", TOKEN)
    ok("render_install rejects quote in base", False)
except ValueError:
    ok("render_install rejects quote in base", True)
try:
    traffic_guard.render_install(BASE, "tg_bad'token")
    ok("render_install rejects bad token", False)
except ValueError:
    ok("render_install rejects bad token", True)
AGENT_SRC = open(os.path.join(AG, "tricloud-guard.sh"), encoding="utf-8").read()
ok("agent: no remote exec / no firewall verdicts in acct rules",
   not any(x in AGENT_SRC for x in ("-j DROP", "-j ACCEPT", "-j REJECT", " drop\"", "counter drop", "counter accept", "Run Command")))
import re as _re
ok("agent: no credentials / domains / IPs in repo script (only 1.1.1.1 / 0.0.0.0 / 127.0.0.1 placeholders)", "panel." not in AGENT_SRC and "tg_" not in AGENT_SRC
   and set(_re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", AGENT_SRC)) <= {"1.1.1.1", "0.0.0.0", "127.0.0.1"})

# ================= 4. state（GET / POST）与心跳 =================
H = {"X-TriCloud-Guard-Token": TOKEN}
ok("state: no token -> 401", c.get("/api/guard-agent/state").status_code == 401)
ok("state: bad token -> 401", c.get("/api/guard-agent/state", headers={"X-TriCloud-Guard-Token": "tg_" + "z" * 43}).status_code == 401)
ok("state: malformed token -> 401 (regex)", c.get("/api/guard-agent/state?token=../../etc").status_code == 401)
r = c.get("/api/guard-agent/state?format=env&v=2&applied=0&iface=eth0&ssh=22,2222&acct=nft&nports=5&evil=1", headers=H)
ok("state env: not throttled, acct=0", r.status_code == 200 and "throttle=0" in r.text and "rate_kbit=0" in r.text and "acct=0" in r.text
   and "interval=300" in r.text)
ag = c.get("/api/traffic-guards").json()[0]["agent"]
ok("heartbeat: online + iface + ssh + backend", ag["online"] and ag["installed"] and ag["iface"] == "eth0" and ag["ssh_ports"] == "22,2222"
   and ag["acct_backend"] == "nft" and ag["acct_ports"] == 5 and ag["version"] == "2")
ok("heartbeat: whitelist only (no evil)", "evil" not in core.q("SELECT agent_info FROM traffic_guards WHERE id=?", (GID,), one=True)["agent_info"])
c.get("/api/guard-agent/state?iface=eth0;rm&ssh=22", headers=H)
ok("heartbeat: bad iface dropped", "iface" not in json.loads(core.q("SELECT agent_info FROM traffic_guards WHERE id=?", (GID,), one=True)["agent_info"]))
ok("state via ?token= also works", c.get(f"/api/guard-agent/state?token={TOKEN}").json()["throttle"] is False)
n_audit = len(c.get("/api/audit?limit=1000").json())
c.post("/api/guard-agent/state", headers=H, content=b"")
ok("POST state not audited (every 5 min)", len(c.get("/api/audit?limit=1000").json()) == n_audit)

# ================= 5. 限速状态机 =================
use["out_gb"] = 85
c.post(f"/api/traffic-guards/{GID}/check")
ok("warn text mentions throttle", any("将限速到 2.5 Mbps" in s for s in sent))
use["out_gb"] = 120
sent.clear()
c.post(f"/api/traffic-guards/{GID}/check")
g = c.get("/api/traffic-guards").json()[0]
ok("over limit -> throttled + status", g["throttled"] == 1 and g["status"] == "throttled" and g["status_text"] == "已限速")
ok("TG: online -> 已下发限速 + 下月解除", any("已下发限速" in s and "下月 1 日自动解除" in s for s in sent))
r = c.get("/api/guard-agent/state?format=env", headers=H)
ok("state env: throttle=1 rate_kbit=2500", "throttle=1" in r.text and "rate_kbit=2500" in r.text)
ok("state json: rate_mbps", c.get("/api/guard-agent/state", headers=H).json()["rate_mbps"] == 2.5)
c.patch(f"/api/traffic-guards/{GID}", json={"release_throttle": True})
g = c.get("/api/traffic-guards").json()[0]
ok("manual release_throttle", g["throttled"] == 0 and g["state_msg"] == "已手动解除限速")
c.post(f"/api/traffic-guards/{GID}/check")
ok("no re-throttle in same period after manual release", c.get("/api/traffic-guards").json()[0]["throttled"] == 0)
# 离线时超限
core.ex("UPDATE traffic_guards SET notified=0, throttled=0, agent_seen=? WHERE id=?", (int(time.time()) - 3600, GID))
sent.clear()
c.post(f"/api/traffic-guards/{GID}/check")
ok("offline agent -> TG 无法限速 + 最后心跳", any("无法限速" in s and "离线" in s for s in sent))
core.ex("UPDATE traffic_guards SET notified=0, throttled=0, agent_seen=NULL WHERE id=?", (GID,))
sent.clear()
c.post(f"/api/traffic-guards/{GID}/check")
ok("never installed -> TG 尚未安装", any("尚未安装" in s for s in sent))
# 回落解除（滚动窗口）
core.ex("UPDATE traffic_guards SET agent_seen=? WHERE id=?", (int(time.time()), GID))
use["out_gb"] = 5
sent.clear()
c.post(f"/api/traffic-guards/{GID}/check")
g = c.get("/api/traffic-guards").json()[0]
ok("usage drops -> released + TG 已解除限速", g["throttled"] == 0 and any("已解除限速" in s for s in sent))
# 跨月解除
core.ex("UPDATE traffic_guards SET throttled=1, month='2000-01' WHERE id=?", (GID,))
txt = traffic_guard.release_due()
ok("release_due: new month releases + text", txt and "新的月份" in txt[0] and not core.q("SELECT throttled FROM traffic_guards WHERE id=?", (GID,), one=True)["throttled"])
ok("release_due: idempotent", traffic_guard.release_due() == [])
core.ex("UPDATE traffic_guards SET throttled=1 WHERE id=?", (GN,))
traffic_guard.release_due()
ok("release_due: non-throttle action flag cleared", not core.q("SELECT throttled FROM traffic_guards WHERE id=?", (GN,), one=True)["throttled"])
# 离线提醒
core.ex("UPDATE traffic_guards SET agent_seen=?, agent_alerted=0 WHERE id=?", (int(time.time()) - 20 * 60, GID))
a1 = traffic_guard.agent_alerts()
ok("agent_alerts: once when offline > 15 min", len(a1) == 1 and "限速 agent 离线" in a1[0] and traffic_guard.agent_alerts() == [])
c.get("/api/guard-agent/state", headers=H)
ok("heartbeat resets alerted", core.q("SELECT agent_alerted FROM traffic_guards WHERE id=?", (GID,), one=True)["agent_alerted"] == 0)
ok("agent_alerts: fresh heartbeat -> none", traffic_guard.agent_alerts() == [])
# 停用 / 改成别的动作
core.ex("UPDATE traffic_guards SET throttled=1 WHERE id=?", (GID,))
c.patch(f"/api/traffic-guards/{GID}", json={"enabled": False})
ok("disabled guard -> agent told not to throttle", c.get("/api/guard-agent/state", headers=H).json()["throttle"] is False)
c.patch(f"/api/traffic-guards/{GID}", json={"enabled": True})
c.patch(f"/api/traffic-guards/{GID}", json={"reset_state": True})
ok("reset_state clears throttled", c.get("/api/traffic-guards").json()[0]["throttled"] == 0)

# TG /traffic
core.ex("UPDATE traffic_guards SET throttled=1 WHERE id=?", (GID,))
replies = []


async def fake_reply(bot, chat_id, text, markup=None):
    replies.append(text)
telegram._reply = fake_reply
core.set_setting("tg_chat_id", "42")


def tg(text):
    replies.clear()
    asyncio.run(telegram.handle_message(None, "42", {"text": text, "chat": {"id": 42}}))
    return "\n".join(replies)


out = tg("/traffic")
ok("TG /traffic shows 🐢已限速", "🐢已限速" in out)
core.ex("UPDATE traffic_guards SET throttled=0 WHERE id=?", (GID,))

# ================= 6. 流量明细：上报 / 聚合 / Top =================
rows, bad = port_traffic.parse_report("tcp 22 sshd 100 200\nudp 443 xray 5 6\nother 0 - 7 8\nfoo 1 x 1 1\ntcp 70000 a 1 1\ntcp 80 nginx -1 2\n"
                                      "tcp 22 - 1 1\ntcp 8080 bad;name 3 3\n# comment\n\ntcp 9 a 1\n")
d = {(r[0], r[1]): r for r in rows}
ok("parse: valid rows, merged dup port keeps proc", d[("tcp", 22)] == ("tcp", 22, "sshd", 101, 201) and d[("other", 0)][2] == "-")
ok("parse: bad lines counted (proto / port / neg / field count)", bad == 4)
ok("parse: unsafe proc -> '-'", d[("tcp", 8080)][2] == "-")
ok("parse: huge value rejected", port_traffic.parse_report(f"tcp 1 a {60 * 1024 ** 4} 0")[1] == 1)
ok("parse: line cap", len(port_traffic.parse_report("\n".join(f"tcp {i + 1} a 1 1" for i in range(500)))[0]) == port_traffic.MAX_LINES)

BODY = "tcp 22 sshd 1000 50000\ntcp 443 xray 900000 800000\nudp 443 xray 100 200\nother 0 - 3000 70000\n"
r = c.post("/api/guard-agent/state?format=env&acct=nft&nports=3", headers=H, content=BODY.encode())
ok("acct disabled -> not recorded (acct_ok=0, acct=0)", "acct_ok=0" in r.text and "acct=0" in r.text
   and not core.q("SELECT 1 FROM guard_port_traffic WHERE guard_id=?", (GID,), one=True))
r = c.patch(f"/api/traffic-guards/{GID}", json={"acct_enabled": True})
ok("PATCH acct_enabled -> view acct_enabled 1", r.json()["acct_enabled"] == 1 and r.json()["agent"]["acct_enabled"] is True)
r = c.post("/api/guard-agent/state?format=env&acct=nft&nports=3", headers=H, content=BODY.encode())
ok("acct enabled -> state acct=1 + acct_ok=4", "acct=1" in r.text and "acct_ok=4" in r.text)
c.post("/api/guard-agent/state?format=env", headers=H, content=b"tcp 22 sshd 10 20\nother 0 - 1 1\ntcp 9999 x 0 0\n")
t = c.get(f"/api/traffic-guards/{GID}/ports?range=today").json()
p = {(x["proto"], x["port"]): x for x in t["ports"]}
ok("today: accumulated per port", p[("tcp", 22)]["in"] == 1010 and p[("tcp", 22)]["out"] == 50020 and ("tcp", 9999) not in p)
ok("today: sorted by total desc", [x["total"] for x in t["ports"]] == sorted([x["total"] for x in t["ports"]], reverse=True)
   and t["ports"][0]["port"] == 443 and t["ports"][0]["proto"] == "tcp")
ok("today: other label", p[("other", 0)]["label"] == "其他/出站连接" and p[("tcp", 443)]["label"] == "443/tcp · xray")
ok("today: totals + pct sum ~100", t["total"] == t["total_in"] + t["total_out"] and abs(sum(x["pct"] for x in t["ports"]) - 100) < 1)
sv = {s["service"]: s for s in t["services"]}
ok("services: xray aggregates tcp+udp 443", sv["xray"]["total"] == 900000 + 800000 + 300 and sv["xray"]["ports"] == ["443/tcp", "443/udp"])
ok("services: sshd + other", "sshd" in sv and "其他/出站连接" in sv)
ok("text fields", p[("tcp", 443)]["total_text"].endswith("MB") and t["title"] == "今日")
ok("acct_seen updated", c.get("/api/traffic-guards").json()[0]["agent"]["acct_seen"])
# 历史数据：本月早些天 + 上个月
td = port_traffic.today()
first = td[:8] + "01"
core.ex("INSERT INTO guard_port_traffic VALUES(?,?,?,?,?,?,?,?)", (GID, first, "tcp", 8080, "nginx", 5_000_000, 5_000_000, 1))
core.ex("INSERT INTO guard_port_traffic VALUES(?,?,?,?,?,?,?,?)", (GID, "2000-01-01", "tcp", 9000, "old", 9 ** 12, 1, 1))
tm = c.get(f"/api/traffic-guards/{GID}/ports?range=month").json()
pm = {(x["proto"], x["port"]) for x in tm["ports"]}
ok("month: includes earlier day this month, excludes old", ("tcp", 8080) in pm and ("tcp", 9000) not in pm and tm["title"] == "本月")
ok("today excludes earlier days" if first != td else "today==first (skip)",
   first == td or ("tcp", 8080) not in {(x["proto"], x["port"]) for x in c.get(f"/api/traffic-guards/{GID}/ports").json()["ports"]})
ok("ports limit", len(c.get(f"/api/traffic-guards/{GID}/ports?range=month&limit=2").json()["ports"]) == 2)
ok("ports bad range -> 400", c.get(f"/api/traffic-guards/{GID}/ports?range=year").status_code == 400)
ok("ports 404 unknown guard", c.get("/api/traffic-guards/9999/ports").status_code == 404)
ok("ports response has agent + retain_days 90", tm["retain_days"] == 90 and tm["agent"]["acct_enabled"] is True)
# 进程名换了：显示最新的
c.post("/api/guard-agent/state", headers=H, content=b"tcp 22 dropbear 1 1\n")
ok("proc updated to latest", {(x["proto"], x["port"]): x for x in c.get(f"/api/traffic-guards/{GID}/ports").json()["ports"]}[("tcp", 22)]["proc"] == "dropbear")
c.post("/api/guard-agent/state", headers=H, content=b"tcp 22 - 1 1\n")
ok("proc '-' does not overwrite", {(x["proto"], x["port"]): x for x in c.get(f"/api/traffic-guards/{GID}/ports").json()["ports"]}[("tcp", 22)]["proc"] == "dropbear")
r = c.post("/api/guard-agent/state", headers=H, content=b"x" * (port_traffic.MAX_BODY + 1))
ok("body too large -> 413", r.status_code == 413)
ok("POST state bad token -> 401", c.post("/api/guard-agent/state", headers={"X-TriCloud-Guard-Token": "tg_" + "q" * 43}, content=BODY.encode()).status_code == 401)
# 另一条守护的 token 只能写自己的数据
c.patch(f"/api/traffic-guards/{GN}", json={"acct_enabled": True})
TOK2 = traffic_guard.agent_token(GN)
ok("acct toggle on notify guard creates token", TOK2 and TOK2 != TOKEN)
before = core.q("SELECT SUM(bytes_in) s FROM guard_port_traffic WHERE guard_id=?", (GID,), one=True)["s"]
c.post("/api/guard-agent/state?guard_id=%d" % GID, headers={"X-TriCloud-Guard-Token": TOK2}, content=b"tcp 22 sshd 777 777\n")
ok("token of guard B writes only B (guard_id param ignored)",
   core.q("SELECT SUM(bytes_in) s FROM guard_port_traffic WHERE guard_id=?", (GID,), one=True)["s"] == before
   and core.q("SELECT bytes_in FROM guard_port_traffic WHERE guard_id=?", (GN,), one=True)["bytes_in"] == 777)
ok("notify guard: state throttle false + acct true", c.get("/api/guard-agent/state", headers={"X-TriCloud-Guard-Token": TOK2}).json() ==
   {"throttle": False, "rate_mbps": 0, "rate_kbit": 0, "interval": 300, "acct": True})
ok("notify guard view has agent block when acct on", c.get("/api/traffic-guards").json()[1]["agent"] is not None)
# 天切换：时间戳在不同日期落到不同 day
port_traffic.record(GID, [("tcp", 22, "sshd", 1, 1)], now=time.time() - 86400 * 2)
ok("record(now=2 days ago) -> separate day row", core.q("SELECT COUNT(DISTINCT day) n FROM guard_port_traffic WHERE guard_id=? AND port=22", (GID,), one=True)["n"] >= 2)
# 90 天清理
core.ex("INSERT INTO guard_port_traffic VALUES(?,?,?,?,?,?,?,?)", (GID, "2001-01-01", "tcp", 1, "x", 1, 1, 1))
old_ok = (time.strftime("%Y-%m-%d", time.localtime(time.time() - 89 * 86400)))
core.ex("INSERT OR REPLACE INTO guard_port_traffic VALUES(?,?,?,?,?,?,?,?)", (GID, old_ok, "tcp", 2, "x", 1, 1, 1))
n = port_traffic.prune()
ok("prune removes > 90 days, keeps recent", n >= 2 and not core.q("SELECT 1 FROM guard_port_traffic WHERE day='2001-01-01'", one=True)
   and not core.q("SELECT 1 FROM guard_port_traffic WHERE day='2000-01-01'", one=True))
ok("fmt_bytes", port_traffic.fmt_bytes(0) == "0 B" and port_traffic.fmt_bytes(1536) == "1.50 KB" and port_traffic.fmt_bytes(5 * 1024 ** 4) == "5.00 TB")

# TG /ports
out = tg("/ports")
ok("TG /ports: list instances with acct", "用法：/ports" in out and "tokyo" in out and "n1" in out)
out = tg("/ports tokyo")
ok("TG /ports tokyo: month top + services", "本月端口流量" in out and "按端口 Top" in out and "443/tcp · xray" in out and "按服务" in out)
ok("TG /ports@bot tokyo", "本月端口流量" in tg("/ports@MyBot tokyo"))
ok("TG /ports unknown", "没有找到" in tg("/ports nope"))
ok("TG /ports by instance id tail", "本月端口流量" in tg("/ports i-thr"))
ok("TG help lists /ports", "/ports" in telegram.HELP)
core.ex("UPDATE traffic_guards SET name='tokyo2' WHERE id=?", (GN,))
ok("TG /ports ambiguous", "匹配到多个" in tg("/ports toky"))
core.ex("UPDATE traffic_guards SET name='n1' WHERE id=?", (GN,))
# 关闭流量明细
c.patch(f"/api/traffic-guards/{GN}", json={"acct_enabled": False})
r = c.post("/api/guard-agent/state?format=env", headers={"X-TriCloud-Guard-Token": TOK2}, content=b"tcp 22 sshd 5 5\n")
ok("acct off -> acct=0 and not recorded", "acct=0" in r.text and core.q("SELECT bytes_in FROM guard_port_traffic WHERE guard_id=?", (GN,), one=True)["bytes_in"] == 777)

# ================= 7. API Token / 未登录 =================
tok = c.post("/api/tokens", json={"name": "t", "scope": "full"}).json()["token"]
c2 = TestClient(main.app)
TH = {"Authorization": "Bearer " + tok}
r = c2.get(f"/api/traffic-guards/{GID}/agent", headers=TH)
ok("API Token GET /agent: status only, commands hidden", r.status_code == 200 and r.json()["commands"] is None and r.json()["commands_hidden"]
   and TOKEN not in r.text)
ok("API Token POST /agent/reset -> 403", c2.post(f"/api/traffic-guards/{GID}/agent/reset", headers=TH).status_code == 403)
ok("API Token GET /ports ok", c2.get(f"/api/traffic-guards/{GID}/ports", headers=TH).status_code == 200)
ok("API Token can toggle acct (non-sensitive)", c2.patch(f"/api/traffic-guards/{GID}", headers=TH, json={"acct_enabled": True}).status_code == 200)
ok("no session: /agent 401", c2.get(f"/api/traffic-guards/{GID}/agent").status_code == 401)
ok("no session: /ports 401", c2.get(f"/api/traffic-guards/{GID}/ports").status_code == 401)
ok("no session: reset 401", c2.post(f"/api/traffic-guards/{GID}/agent/reset").status_code == 401)
ok("no session: install.sh public but token-gated", c2.get("/api/guard-agent/install.sh").status_code == 404)

# reset token
r = c.post(f"/api/traffic-guards/{GID}/agent/reset?base={BASE}")
NEW = core.decrypt(core.q("SELECT agent_token_enc FROM traffic_guards WHERE id=?", (GID,), one=True)["agent_token_enc"])
ok("reset: new token in commands, old token 401", NEW != TOKEN and NEW in r.json()["commands"]["install"]
   and c.get("/api/guard-agent/state", headers=H).status_code == 401)
ok("reset: agent status cleared", r.json()["agent"]["installed"] is False)
ok("reset audited", any(a["action"] == "guard-agent-reset" for a in c.get("/api/audit").json()))
TOKEN, H = NEW, {"X-TriCloud-Guard-Token": NEW}

# ================= 8. agent 脚本（假命令） =================
FB = tempfile.mkdtemp()
BIN = os.path.join(FB, "bin")
os.makedirs(BIN)
ST = os.path.join(FB, "state")
CONF = os.path.join(FB, "conf")


def w(name, body):
    p = os.path.join(BIN, name)
    with open(p, "w") as f:
        f.write(body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)


PY = sys.executable
w("nft", f"""#!{PY}
import sys, os, re, json
F = os.environ['FAKE']; rules = os.path.join(F, 'nft.rules'); cnt = os.path.join(F, 'counters.json')
a = sys.argv[1:]
open(os.path.join(F, 'nft.log'), 'a').write(' '.join(a) + '\\n')
if a[:2] == ['list', 'tables']: sys.exit(0)
if a[:1] == ['-f']:
    txt = sys.stdin.read()
    if os.path.exists(os.path.join(F, 'nft.fail')) and open(os.path.join(F, 'nft.fail')).read().strip() in txt: sys.exit(1)
    open(rules, 'a').write(txt); sys.exit(0)
if a[:4] == ['list', 'table', 'inet', 'tricloud_acct']:
    if not os.path.exists(rules): sys.exit(1)
    c = json.load(open(cnt)) if os.path.exists(cnt) else {{}}
    seen = set()
    for l in open(rules):
        m = re.search(r'counter comment "([^"]+)"', l)
        if m:
            k = m.group(1); v = c.get(k, 0) if k not in seen else 0; seen.add(k)
            l = l.replace('counter comment', 'counter packets 1 bytes %d comment' % v)
        sys.stdout.write(l)
    sys.exit(0)
if a[:4] == ['delete', 'table', 'inet', 'tricloud_acct']:
    if os.path.exists(rules): os.remove(rules); sys.exit(0)
    sys.exit(1)
sys.exit(0)
""")
w("iptables", f"""#!{PY}
import sys, os, json
F = os.environ['FAKE']; me = os.path.basename(sys.argv[0]); db = os.path.join(F, me + '.json'); cnt = os.path.join(F, 'counters.json')
s = json.load(open(db)) if os.path.exists(db) else {{'chains': {{}}, 'jumps': []}}
a = sys.argv[1:]
open(os.path.join(F, 'ipt.log'), 'a').write(me + ' ' + ' '.join(a) + '\\n')
if a[:2] == ['-t', 'mangle']: a = a[2:]
def save(): json.dump(s, open(db, 'w'))
if a == ['-S']: sys.exit(0)
op = a[0]
if op == '-S': sys.exit(0 if a[1] in s['chains'] else 1)
if op == '-N':
    if a[1] in s['chains']: sys.exit(1)
    s['chains'][a[1]] = []; save(); sys.exit(0)
if op == '-I': s['jumps'].append([a[1], a[-1]]); save(); sys.exit(0)
if op == '-D':
    j = [a[1], a[-1]]
    if j in s['jumps']: s['jumps'].remove(j); save(); sys.exit(0)
    sys.exit(1)
if op == '-F':
    if a[1] in s['chains']: s['chains'][a[1]] = []; save(); sys.exit(0)
    sys.exit(1)
if op == '-X':
    if a[1] in s['chains']: del s['chains'][a[1]]; save(); sys.exit(0)
    sys.exit(1)
if op == '-A':
    if a[1] not in s['chains']: sys.exit(1)
    s['chains'][a[1]].append(a[2:]); save(); sys.exit(0)
if op == '-nvxL':
    if a[1] not in s['chains']: sys.exit(1)
    c = json.load(open(cnt)) if os.path.exists(cnt) else {{}}
    print('Chain %s (1 references)' % a[1]); print('    pkts      bytes target     prot opt in     out     source               destination')
    for r in s['chains'][a[1]]:
        if '--comment' in r:
            k = r[r.index('--comment') + 1]
            print('       1 %8d            all  --  *      *       0.0.0.0/0            0.0.0.0/0            /* %s */' % (c.get(k.replace('_', ' '), 0) if a[1] != 'TRICLOUD_ACCT_FWD' else 0, k))
        else:
            print('       0        0 RETURN     all  --  lo     *       0.0.0.0/0            0.0.0.0/0')
    sys.exit(0)
sys.exit(0)
""")
shutil.copy(os.path.join(BIN, "iptables"), os.path.join(BIN, "ip6tables"))
w("ss", "#!/bin/bash\ncat \"$FAKE/ss.txt\"\n")
w("docker", "#!/bin/bash\n[ \"$1\" = ps ] && cat \"$FAKE/docker.txt\"\n")
w("ip", "#!/bin/bash\necho '1.1.1.1 via 10.0.0.1 dev eth0 src 10.0.0.5 uid 0'\n")
w("sshd", "#!/bin/bash\nprintf 'port 2222\\nport 22\\n'\n")
w("systemctl", "#!/bin/bash\nexit 0\n")
w("tc", "#!/bin/bash\necho \"$*\" >> \"$FAKE/tc.log\"\nif [ \"$1 $2\" = 'qdisc show' ]; then [ -f \"$FAKE/tc.on\" ] && echo 'qdisc htb 1: root refcnt 2 r2q 10 default 0x20'; exit 0; fi\n"
         "if [ \"$1 $2\" = 'qdisc replace' ]; then touch \"$FAKE/tc.on\"; fi\nif [ \"$1 $2\" = 'qdisc del' ]; then rm -f \"$FAKE/tc.on\"; fi\nexit 0\n")
# 假 curl：记录参数和正文，按 curl.resp / curl.code 返回
w("curl", """#!/bin/bash
: > "$FAKE/curl.body"; args=""
while [ $# -gt 0 ]; do
  case "$1" in
    --data-binary) f="${2#@}"; cat "$f" > "$FAKE/curl.body" 2>/dev/null; shift 2 ;;
    *) args="$args $1"; shift ;;
  esac
done
echo "$args" > "$FAKE/curl.args"
[ -f "$FAKE/curl.code" ] && code=$(cat "$FAKE/curl.code") || code=200
cat "$FAKE/curl.resp" 2>/dev/null; printf '\\n%s' "$code"
""")
SS = """tcp   LISTEN 0      4096         0.0.0.0:22        0.0.0.0:*    users:(("sshd",pid=1,fd=3))
tcp   LISTEN 0      4096            [::]:22           [::]:*    users:(("sshd",pid=1,fd=4))
tcp   LISTEN 0      4096               *:443             *:*    users:(("xray",pid=9,fd=7))
udp   UNCONN 0      0                  *:443             *:*    users:(("xray",pid=9,fd=8))
tcp   LISTEN 0      4096       127.0.0.1:18711     0.0.0.0:*    users:(("docker-proxy",pid=5,fd=4))
tcp   LISTEN 0      4096   127.0.0.53%lo:53        0.0.0.0:*    users:(("systemd-resolve",pid=3,fd=14))
udp   UNCONN 0      0              [::1]:323          [::]:*    users:(("chronyd",pid=4,fd=5))
tcp   LISTEN 0      4096         0.0.0.0:8080      0.0.0.0:*    users:(("docker-proxy",pid=6,fd=4))
tcp   LISTEN 0      511          0.0.0.0:54321     0.0.0.0:*    users:(("x-ui",pid=7,fd=9))
"""
DOCKER = "web|0.0.0.0:8080->80/tcp, :::8080->80/tcp\npanel|127.0.0.1:18711->8000/tcp\n"


def env(**kw):
    e = dict(os.environ, PATH=BIN + ":" + os.environ["PATH"], FAKE=FB, TRICLOUD_GUARD_TEST="1", TRICLOUD_GUARD_CONF=CONF,
             TRICLOUD_GUARD_STATE=ST)
    e.update(kw)
    return e


def put(name, txt):
    with open(os.path.join(FB, name), "w") as f:
        f.write(txt)


def rd(name, d=FB):
    try:
        return open(os.path.join(d, name)).read()
    except OSError:
        return ""


def agent(*args, **kw):
    return subprocess.run(["bash", os.path.join(AG, "tricloud-guard.sh"), *args], capture_output=True, text=True, env=env(**kw), timeout=60)


put("ss.txt", SS)
put("docker.txt", DOCKER)
with open(CONF, "w") as f:
    f.write(f"PANEL=https://panel.example.com\nTOKEN={TOKEN}\n")

lp = agent("ports").stdout.split("\n")
lp = [x for x in lp if x]
ok("listen_ports: loopback excluded, sorted, docker mapped", lp == ["tcp 22 sshd", "tcp 443 xray", "udp 443 xray", "tcp 8080 docker:web", "tcp 54321 x-ui"])
ok("ssh ports from sshd -T", agent("commands", "eth0", "8000", "22", "2222").stdout.count("flowid 1:10") == 4)
cm = agent("commands", "eth0", "1000", "22").stdout
ok("tc commands: htb root + 1:20 rate/ceil + ssh sport filter", "root handle 1: htb default 20" in cm and "rate 1000kbit ceil 1000kbit" in cm
   and "match ip sport 22 0xffff flowid 1:10" in cm and "match ip6 sport 22" in cm)
nr = agent("acct-rules", "nft", "eth0").stdout
ok("nft rules: own table + input/output/forward + counters only", "table inet tricloud_acct" in nr and "hook input priority -160" in nr
   and "hook output" in nr and "hook forward" in nr and 'meta l4proto tcp th dport 22 counter comment "tcp 22 in"' in nr
   and 'meta l4proto udp th sport 443 counter comment "udp 443 out"' in nr and "ct original proto-dst 8080" in nr)
ok("nft rules: no drop/accept/reject verdicts", not any(v in nr for v in (" drop", " accept\n", "reject", "queue")) and "policy accept" in nr)
ir = agent("acct-rules", "iptables", "eth0").stdout
ok("iptables rules: mangle chains, no -j except lo RETURN", "-t mangle -A TRICLOUD_ACCT_IN -p tcp --dport 22 -m comment --comment tcp_22_in" in ir
   and all(("-j" not in ln) or ln.endswith("-j RETURN") for ln in ir.splitlines()) and "--ctorigdstport 8080" in ir)

# --- run #1：面板说 acct=1，还没有计数规则 → 空上报，然后建表 ---
put("curl.resp", "throttle=0\nrate_kbit=0\nacct=1\ninterval=300\n")
r1 = agent("run", TRICLOUD_GUARD_ACCT="nft")
args = rd("curl.args")
ok("run1: POST with token header + params", "-X POST" in args and f"X-TriCloud-Guard-Token: {TOKEN}" in args and "acct=off" in args
   and "iface=eth0" in args and "ssh=22,2222" in args and "v=2" in args)
ok("run1: empty body", rd("curl.body") == "")
ok("run1: nft table created", 'comment "tcp 54321 in"' in rd("nft.rules") and r1.returncode == 0)
ok("run1: acct_ports saved with proc", "tcp 443 xray" in rd("acct_ports", ST) and rd("acct_sig", ST).startswith("nft eth0 "))
ok("run1: no tc throttle", not os.path.exists(os.path.join(FB, "tc.on")))
# --- run #2：有计数 → 上报增量（其他 = 总量 − 各端口） ---
put("counters.json", json.dumps({"all 0 in": 10000, "all 0 out": 50000, "tcp 22 in": 1000, "tcp 22 out": 2000, "tcp 443 in": 5000,
                                 "tcp 443 out": 30000, "udp 443 in": 100, "udp 443 out": 200, "tcp 8080 in": 400, "tcp 8080 out": 800}))
r2 = agent("run", TRICLOUD_GUARD_ACCT="nft")
body = {tuple(x.split()[:3]): tuple(int(v) for v in x.split()[3:]) for x in rd("curl.body").splitlines()}
ok("run2: per-port deltas with proc", body.get(("tcp", "22", "sshd")) == (1000, 2000) and body.get(("tcp", "443", "xray")) == (5000, 30000)
   and body.get(("tcp", "8080", "docker:web")) == (400, 800))
ok("run2: other = all - ports", body.get(("other", "0", "-")) == (10000 - 6500, 50000 - 33000))
ok("run2: acct=nft nports=5 reported", "acct=nft" in rd("curl.args") and "nports=5" in rd("curl.args"))
ok("run2: pending cleared after 200, no rebuild", not os.path.exists(os.path.join(ST, "acct_pending")) and rd("nft.log").count("-f") == 2)
# --- run #3：面板 500 → 保留增量 ---
put("counters.json", json.dumps({"all 0 in": 10100, "all 0 out": 50100, "tcp 22 in": 1100, "tcp 22 out": 2000, "tcp 443 in": 5000,
                                 "tcp 443 out": 30000, "udp 443 in": 100, "udp 443 out": 200, "tcp 8080 in": 400, "tcp 8080 out": 800}))
put("curl.code", "500")
r3 = agent("run", TRICLOUD_GUARD_ACCT="nft")
ok("run3: panel 500 -> pending kept", "tcp 22 100 0" in rd("acct_pending", ST) and "下次补报" in r3.stdout)
# --- run #4：恢复 → 补报两次的增量之和 ---
put("counters.json", json.dumps({"all 0 in": 10300, "all 0 out": 50100, "tcp 22 in": 1300, "tcp 22 out": 2000, "tcp 443 in": 5000,
                                 "tcp 443 out": 30000, "udp 443 in": 100, "udp 443 out": 200, "tcp 8080 in": 400, "tcp 8080 out": 800}))
os.remove(os.path.join(FB, "curl.code"))
agent("run", TRICLOUD_GUARD_ACCT="nft")
body = {tuple(x.split()[:3]): tuple(int(v) for v in x.split()[3:]) for x in rd("curl.body").splitlines()}
ok("run4: deltas accumulated across failed report", body.get(("tcp", "22", "sshd")) == (300, 0) and body.get(("other", "0", "-")) == (0, 100))
# --- run #5：端口变化 → 重建（计数清零前收集进待上报） ---
put("ss.txt", SS + 'tcp   LISTEN 0      4096         0.0.0.0:9443      0.0.0.0:*    users:(("caddy",pid=11,fd=3))\n')
put("counters.json", json.dumps({"all 0 in": 10500, "all 0 out": 50100, "tcp 22 in": 1500, "tcp 22 out": 2000}))
agent("run", TRICLOUD_GUARD_ACCT="nft")
ok("run5: port change -> table rebuilt with new port", 'comment "tcp 9443 in"' in rd("nft.rules") and "delete table inet tricloud_acct" in rd("nft.log"))
ok("run5: snapshot reset after rebuild", not os.path.exists(os.path.join(ST, "acct_snap")))
# 计数器重建后从 0 开始
put("counters.json", json.dumps({"all 0 in": 50, "all 0 out": 60, "tcp 9443 in": 50, "tcp 9443 out": 60}))
agent("run", TRICLOUD_GUARD_ACCT="nft")
body = {tuple(x.split()[:3]): tuple(int(v) for v in x.split()[3:]) for x in rd("curl.body").splitlines()}
ok("run6: new port reported from 0", body.get(("tcp", "9443", "caddy")) == (50, 60) and ("other", "0", "-") not in body)
# --- forward 链失败不影响主表 ---
shutil.rmtree(ST)
os.remove(os.path.join(FB, "nft.rules"))
put("nft.fail", "chain forward")
r = agent("run", TRICLOUD_GUARD_ACCT="nft")
ok("forward chain failure tolerated (main table still created)", 'comment "tcp 22 in"' in rd("nft.rules") and "forward 计数链创建失败" in r.stdout)
os.remove(os.path.join(FB, "nft.fail"))
# --- 主表失败：记录错误，不留半成品 ---
shutil.rmtree(ST)
os.remove(os.path.join(FB, "nft.rules"))
put("nft.fail", "hook input")
r = agent("run", TRICLOUD_GUARD_ACCT="nft")
ok("main table failure -> logged, no sig", "计数规则创建失败" in r.stdout and not os.path.exists(os.path.join(ST, "acct_sig")))
os.remove(os.path.join(FB, "nft.fail"))
agent("run", TRICLOUD_GUARD_ACCT="nft")
# --- 面板关闭流量明细 → 删表 ---
put("curl.resp", "throttle=0\nrate_kbit=0\nacct=0\ninterval=300\n")
r = agent("run", TRICLOUD_GUARD_ACCT="nft")
ok("acct=0 -> nft table deleted + state cleared", not os.path.exists(os.path.join(FB, "nft.rules")) and "已关闭流量明细" in r.stdout
   and not os.path.exists(os.path.join(ST, "acct_sig")))
# --- 限速 + 流量明细同时 ---
put("curl.resp", "throttle=1\nrate_kbit=1000\nacct=1\ninterval=300\n")
agent("run", TRICLOUD_GUARD_ACCT="nft")
ok("throttle=1 -> tc htb applied with ssh ports", os.path.exists(os.path.join(FB, "tc.on")) and "rate 1000kbit ceil 1000kbit" in rd("tc.log")
   and "sport 2222" in rd("tc.log") and "tricloud_acct" in rd("nft.rules"))
ok("applied state file", rd("applied", ST).strip() == "eth0 1000 22 2222")
agent("run", TRICLOUD_GUARD_ACCT="nft")
ok("throttle unchanged -> no re-apply", rd("tc.log").count("qdisc replace") == 1)
ok("applied=1 reported", "applied=1" in rd("curl.args"))
# --- 401 → 解除限速 + 删计数 ---
put("curl.code", "401")
r = agent("run", TRICLOUD_GUARD_ACCT="nft")
ok("401 -> clear tc + delete acct table", not os.path.exists(os.path.join(FB, "tc.on")) and not os.path.exists(os.path.join(FB, "nft.rules"))
   and "token 无效" in r.stdout)
os.remove(os.path.join(FB, "curl.code"))
# --- 24 小时连不上 → 解除限速 ---
put("curl.resp", "throttle=1\nrate_kbit=1000\nacct=0\ninterval=300\n")
agent("run", TRICLOUD_GUARD_ACCT="nft")
put("curl.code", "000")
with open(os.path.join(ST, "last_ok"), "w") as f:
    f.write(str(int(time.time()) - 25 * 3600))
r = agent("run", TRICLOUD_GUARD_ACCT="nft")
ok("24h unreachable -> fail open", not os.path.exists(os.path.join(FB, "tc.on")) and "连续 24 小时" in r.stdout)
os.remove(os.path.join(FB, "curl.code"))
# --- iptables 后端（IPv4 + IPv6 求和） ---
shutil.rmtree(ST)
put("ss.txt", SS)
put("curl.resp", "throttle=0\nrate_kbit=0\nacct=1\ninterval=300\n")
agent("run", TRICLOUD_GUARD_ACCT="iptables")
ipt = json.loads(rd("iptables.json"))
ok("iptables: chains + jumps in mangle INPUT/OUTPUT/FORWARD", set(ipt["chains"]) == {"TRICLOUD_ACCT_IN", "TRICLOUD_ACCT_OUT", "TRICLOUD_ACCT_FWD"}
   and ["INPUT", "TRICLOUD_ACCT_IN"] in ipt["jumps"] and ["OUTPUT", "TRICLOUD_ACCT_OUT"] in ipt["jumps"])
ok("iptables: ip6tables too", os.path.exists(os.path.join(FB, "ip6tables.json")))
put("counters.json", json.dumps({"all 0 in": 1000, "all 0 out": 2000, "tcp 22 in": 100, "tcp 22 out": 200}))
agent("run", TRICLOUD_GUARD_ACCT="iptables")
body = {tuple(x.split()[:3]): tuple(int(v) for v in x.split()[3:]) for x in rd("curl.body").splitlines()}
ok("iptables: v4+v6 summed, other computed", body.get(("tcp", "22", "sshd")) == (200, 400) and body.get(("other", "0", "-")) == (1800, 3600)
   and "acct=iptables" in rd("curl.args"))
r = agent("uninstall")
ipt = json.loads(rd("iptables.json"))
ok("uninstall: iptables chains + jumps removed", ipt["chains"] == {} and ipt["jumps"] == [] and json.loads(rd("ip6tables.json"))["chains"] == {})
ok("uninstall: state dir removed + message", not os.path.exists(ST) and "流量计数规则已清除" in r.stdout)
# --- 没有计数后端 ---
put("curl.resp", "throttle=0\nrate_kbit=0\nacct=1\ninterval=300\n")
agent("run", TRICLOUD_GUARD_ACCT="none")
ok("backend none -> acct=none reported, no rules", "acct=none" in rd("curl.args"))
# --- nft 卸载 ---
agent("run", TRICLOUD_GUARD_ACCT="nft")
ok("nft table present before uninstall", os.path.exists(os.path.join(FB, "nft.rules")))
agent("uninstall")
ok("uninstall: nft table deleted", not os.path.exists(os.path.join(FB, "nft.rules")))
UN = open(os.path.join(AG, "uninstall.sh"), encoding="utf-8").read()
ok("uninstall.sh fallback cleans nft table + iptables chains", "delete table inet tricloud_acct" in UN and "TRICLOUD_ACCT_IN" in UN)
ok("status subcommand runs", "流量明细" in agent("status", TRICLOUD_GUARD_ACCT="nft").stdout)
ok("bad conf -> run exits 1", agent("run", TRICLOUD_GUARD_CONF=os.path.join(FB, "nope")).returncode == 1)

# ================= 9. 端到端：真实 curl → 本进程 uvicorn =================
import uvicorn

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
PORT = sock.getsockname()[1]
sock.close()
srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="off"))
th = threading.Thread(target=srv.run, daemon=True)
th.start()
for _ in range(100):
    if srv.started:
        break
    time.sleep(0.1)
os.remove(os.path.join(BIN, "curl"))
with open(CONF, "w") as f:
    f.write(f"PANEL=http://127.0.0.1:{PORT}\nTOKEN={TOKEN}\n")
for k in ("counters.json", "nft.rules"):
    if os.path.exists(os.path.join(FB, k)):
        os.remove(os.path.join(FB, k))
core.ex("DELETE FROM guard_port_traffic WHERE guard_id=?", (GID,))
core.ex("UPDATE traffic_guards SET acct_enabled=1, throttled=0 WHERE id=?", (GID,))
e2e = dict(no_proxy="*", NO_PROXY="*", TRICLOUD_GUARD_ACCT="nft")
r = agent("run", **e2e)
ok("e2e run1: heartbeat recorded, table created", 'comment "tcp 22 in"' in rd("nft.rules")
   and c.get("/api/traffic-guards").json()[0]["agent"]["acct_backend"] == "off")
put("counters.json", json.dumps({"all 0 in": 9000, "all 0 out": 9000, "tcp 22 in": 1000, "tcp 22 out": 2000, "tcp 443 in": 3000, "tcp 443 out": 4000}))
r = agent("run", **e2e)
t = c.get(f"/api/traffic-guards/{GID}/ports").json()
pp = {(x["proto"], x["port"]): x for x in t["ports"]}
ok("e2e run2: panel shows per-port + other", pp.get(("tcp", 22), {}).get("in") == 1000 and pp.get(("tcp", 443), {}).get("out") == 4000
   and pp.get(("other", 0), {}).get("in") == 5000 and pp.get(("other", 0), {}).get("out") == 3000)
ok("e2e: agent status nft + 5 ports + online", (lambda a: a["acct_backend"] == "nft" and a["acct_ports"] == 5 and a["online"])(
    c.get("/api/traffic-guards").json()[0]["agent"]))
core.ex("UPDATE traffic_guards SET throttled=1 WHERE id=?", (GID,))
agent("run", **e2e)
ok("e2e: throttled guard -> tc applied at 2500kbit", os.path.exists(os.path.join(FB, "tc.on")) and "rate 2500kbit" in rd("tc.log"))
ok("e2e: agent applied=1 visible on panel", (lambda: (agent("run", **e2e), c.get("/api/traffic-guards").json()[0]["agent"]["applied"])[1])())
c.delete(f"/api/traffic-guards/{GID}")
r = agent("run", **e2e)
ok("e2e: guard deleted -> 401 -> agent clears tc + acct", not os.path.exists(os.path.join(FB, "tc.on")) and not os.path.exists(os.path.join(FB, "nft.rules")))
ok("delete guard removes port rows", not core.q("SELECT 1 FROM guard_port_traffic WHERE guard_id=?", (GID,), one=True))
srv.should_exit = True
th.join(5)

# ================= 10. schedule_loop / 路由注册 =================
TS = open(os.path.join(ROOT, "app", "tasks.py"), encoding="utf-8").read()
ok("schedule_loop: release_due + agent_alerts + daily prune", "traffic_guard.release_due() + traffic_guard.agent_alerts()" in TS
   and "port_traffic.prune()" in TS)
paths = {(r.path, tuple(sorted(r.methods))) for r in main.app.routes if getattr(r, "path", "").startswith("/api/")}
for pth, m in (("/api/guard-agent/state", "GET"), ("/api/guard-agent/state", "POST"), ("/api/guard-agent/install.sh", "GET"),
               ("/api/guard-agent/uninstall.sh", "GET"), ("/api/traffic-guards/{gid}/agent", "GET"), ("/api/traffic-guards/{gid}/agent/reset", "POST"),
               ("/api/traffic-guards/{gid}/ports", "GET")):
    ok(f"route {m} {pth}", (pth, (m,)) in paths)
ok("PUBLIC only guard-agent state/install/uninstall", main.PUBLIC == {"/api/login", "/api/health", "/api/guard-agent/state",
                                                                      "/api/guard-agent/install.sh", "/api/guard-agent/uninstall.sh"})

P_USAGE.stop()
c.__exit__(None, None, None)

# ================= 11. 静态检查：Web / mock / 文档 / App =================
if os.path.exists(os.path.join(ROOT, "web", "js", "guard.js")):
    WJ = open(os.path.join(ROOT, "web", "js", "guard.js"), encoding="utf-8").read()
    INS = open(os.path.join(ROOT, "web", "js", "instances.js"), encoding="utf-8").read()
    MJ = open(os.path.join(ROOT, "demo", "mock.js"), encoding="utf-8").read()
    ok("web: throttle option + mbps input default 1", 'value="throttle"' in INS and 'name="throttle_mbps"' in INS)
    ok("web: agent panel (install/uninstall copy, reset, status, acct toggle)", all(x in WJ for x in (
        "/agent/reset", "commands.install", "commands.uninstall", "copyText", "acct_enabled", "last_seen_text", "重置 token")))
    ok("web: ports top today/month + bars + other", all(x in WJ for x in ('data-r="today"', 'data-r="month"', "pbar", "/ports?range=", "services")))
    ok("demo mock: agent + ports routes", "/agent/reset" in MJ and "/ports" in MJ and "guard-agent" in MJ)
for nm, path in (("android", os.path.join(ROOT, "android", "app", "src", "main", "java", "com", "tricloud", "app", "GuardAgentActivity.java")),
                 ("ios", os.path.join(ROOT, "ios", "TriCloud", "GuardAgentPage.swift"))):
    if os.path.exists(path):
        S = open(path, encoding="utf-8").read()
        ok(f"{nm}: agent endpoints + ports + reset + acct toggle + copy", all(x in S for x in ("/agent", "/agent/reset", "/ports?range=", "acct_enabled", "commands")))
DOC = open(os.path.join(ROOT, "docs", "FEATURES.md"), encoding="utf-8").read()
ok("docs: FEATURES build 22 section", "推送并限速" in DOC and "流量明细" in DOC and "tricloud_acct" in DOC)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
