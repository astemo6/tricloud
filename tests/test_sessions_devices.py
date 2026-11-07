"""自测：已登录设备（会话补记设备信息、列表、踢下线、退出其他设备）。
覆盖 core 会话字段与节流回填、device_label 解析、/api/sessions 三个接口（含踢自己清 cookie）、
API Token 被禁止访问 /api/sessions 的静态断言、前端卡片与 i18n。"""
import json
import os
import sys
import tempfile
import time

os.environ.update(TRICLOUD_DATA=tempfile.mkdtemp())
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from starlette.requests import Request

from app import core
from app.routers.security import device_label, sessions_kick, sessions_kick_others, sessions_list

core.init_db()
R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def mkreq(token=None):
    headers = []
    if token:
        headers.append((b"cookie", f"tc_session={token}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/api/sessions", "headers": headers})


UA_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
UA_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

# ---- core：会话字段 ----
t1 = core.new_session("1.2.3.4", UA_IPHONE, "web")
t2 = core.new_session("5.6.7.8", "", "app")
rows = core.list_sessions()
by_ip = {r["ip"]: r for r in rows}
ok("new sessions recorded with ip/ua/kind/time",
   by_ip["1.2.3.4"]["ua"] == UA_IPHONE and by_ip["5.6.7.8"]["kind"] == "app"
   and by_ip["1.2.3.4"]["created"] > 0 and by_ip["1.2.3.4"]["last_seen"] >= by_ip["1.2.3.4"]["created"])

# touch 节流：刚登录的会话 last_seen 不被立刻改写（60 秒内）
before = by_ip["1.2.3.4"]["last_seen"]
core.touch_session(t1, "9.9.9.9", UA_WIN)
r1 = [r for r in core.list_sessions() if r["token_hash"] == core.session_key(t1)][0]
ok("touch throttled within 60s", r1["last_seen"] == before and r1["ip"] == "1.2.3.4")
# 人工把 last_seen 调老后 touch 生效：更新 ip/last_seen，UA 已有值不覆盖；空 UA 的会话被回填
core.ex("UPDATE sessions SET last_seen=? WHERE token_hash=?", (int(time.time()) - 3600, core.session_key(t1)))
core.ex("UPDATE sessions SET last_seen=? WHERE token_hash=?", (int(time.time()) - 3600, core.session_key(t2)))
core.touch_session(t1, "9.9.9.9", UA_WIN)
core.touch_session(t2, "5.6.7.8", UA_WIN)
rows = {r["token_hash"]: r for r in core.list_sessions()}
ok("touch updates ip/last_seen, keeps existing ua",
   rows[core.session_key(t1)]["ip"] == "9.9.9.9" and rows[core.session_key(t1)]["ua"] == UA_IPHONE)
ok("touch backfills empty ua", rows[core.session_key(t2)]["ua"] == UA_WIN)

# ---- device_label ----
ok("device labels",
   device_label(UA_IPHONE, "web") == "iPhone · Safari"
   and device_label(UA_WIN, "web") == "Windows · Chrome"
   and device_label("Mozilla/5.0 (Android 14; Pixel 8) Chrome/126.0 Mobile", "web") == "Android · Chrome"
   and device_label("", "app") == "TriCloud App"
   and device_label("", "web") == "")

# ---- 接口：列表 / 踢人 / 退出其他 ----
lst = sessions_list(mkreq(t1))
me = [d for d in lst if d["current"]]
ok("list marks current + parses device",
   len(lst) == 2 and len(me) == 1 and me[0]["device"] == "iPhone · Safari" and me[0]["ip"] == "9.9.9.9")
other_id = [d for d in lst if not d["current"]][0]["id"]
resp = sessions_kick(other_id, mkreq(t1))
ok("kick other device", json.loads(resp.body)["self"] is False and not core.check_session(t2))
resp = sessions_kick(core.session_key(t1), mkreq(t1))
body = json.loads(resp.body)
ok("kick self flags self + clears cookie", body["self"] is True and "tc_session=" in resp.headers.get("set-cookie", "")
   and not core.check_session(t1))
t3 = core.new_session("3.3.3.3", UA_WIN, "web")
t4 = core.new_session("4.4.4.4", UA_WIN, "web")
out = sessions_kick_others(mkreq(t3))
ok("kick others keeps current", out["kicked"] == 1 and core.check_session(t3) and not core.check_session(t4))

# ---- 静态：Token 禁访 + 前端 ----
main = open(os.path.join(ROOT, "app/main.py"), encoding="utf-8").read()
ok("api tokens forbidden from /api/sessions", '"/api/sessions"' in main)
ok("middleware touches session", "core.touch_session" in main)
settings = open(os.path.join(ROOT, "web/js/settings.js"), encoding="utf-8").read()
ok("web: devices card + kick handlers", 'api("/sessions")' in settings and "data-kick" in settings and "kick-others" in settings)
i18n = open(os.path.join(ROOT, "web/js/i18n.js"), encoding="utf-8").read()
keys = ("set.devTitle", "set.devDevice", "set.devLoginAt", "set.devLastSeen", "set.devCurrent",
        "set.devKick", "set.devKickOthers", "set.devUnknown", "set.devKicked", "set.devOthersDone")
ok("i18n pairs", all(i18n.count(f'"{k}"') == 2 for k in keys))

import app.main  # noqa: F401
ok("app.main imports cleanly", True)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
