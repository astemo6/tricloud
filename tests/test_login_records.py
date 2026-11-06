"""自测：登录记录专门接口 + 安全页展示。
GET /api/audit/logins 只返回 POST /api/login 的审计行（时间/IP/结果，倒序）；
安全页拉这个接口渲染「登录记录」卡片，审计总表里登录行动作标为「🔐 登录」。"""
import os
import sys
import tempfile
import time

os.environ.update(TRICLOUD_DATA=tempfile.mkdtemp())
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from app import core
from app.routers.security import audit_logins

core.init_db()
R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


now = int(time.time())
core.ex("INSERT INTO audit(ts, ip, actor, action, detail) VALUES(?,?,?,?,?)", (now - 300, "1.1.1.1", "-", "POST /api/login", "HTTP 401"))
core.ex("INSERT INTO audit(ts, ip, actor, action, detail) VALUES(?,?,?,?,?)", (now - 200, "2.2.2.2", "session", "POST /api/scripts", "HTTP 200"))
core.ex("INSERT INTO audit(ts, ip, actor, action, detail) VALUES(?,?,?,?,?)", (now - 100, "98.98.127.144", "-", "POST /api/login", "HTTP 200"))

rows = audit_logins()
ok("only login rows, newest first", len(rows) == 2 and rows[0]["ip"] == "98.98.127.144" and rows[1]["ip"] == "1.1.1.1")
ok("fields limited to ts/ip/detail", set(dict(rows[0]).keys()) == {"ts", "ip", "detail"})
ok("limit respected", len(audit_logins(1)) == 1)

settings = open(os.path.join(ROOT, "web/js/settings.js"), encoding="utf-8").read()
ok("web: fetches /audit/logins + renders card + labels audit rows",
   "/audit/logins" in settings and "set.loginTitle" in settings and '"POST /api/login" ? "🔐 "' in settings)
i18n = open(os.path.join(ROOT, "web/js/i18n.js"), encoding="utf-8").read()
ok("i18n pairs", all(i18n.count(f'"{k}"') == 2 for k in ("set.loginTitle", "set.loginWord", "set.loginOk", "set.loginFail")))

import app.main  # noqa: F401
ok("app.main imports cleanly", True)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
