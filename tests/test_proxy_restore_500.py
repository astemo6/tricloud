"""fix-160-sec 三个提交（19c16a6 / 1b4c557 / 8e9243e）的测试：
1) Dockerfile --forwarded-allow-ips 只信任 127.0.0.1（不再是 *）；线上拓扑（cloudflared→docker 网关）下靠 TRUST_PROXY=true 取真实 IP；
   经 uvicorn ProxyHeadersMiddleware 时真实 IP / https 识别、登录、会话 cookie、按 IP 限流都正常，伪造的 X-Forwarded-For 被忽略；
2) 备份恢复失败时回滚到原 DB 与 key；
3) 兜底 500 不返回异常原文，只返回 request_id 并记日志。
全部本地，不连接任何真实云。"""
import asyncio
import logging
import os
import re
import sys
import tempfile

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123", LOGIN_MAX_FAIL="2")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY", "TRUST_PROXY", "COOKIE_SECURE"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import core, main, security, tasks, telegram

R = []
core.init_db()


def ok(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  → {extra}" if extra and not cond else ""))


async def noop():
    await asyncio.sleep(3600)


for f in ("task_loop", "monitor_loop", "schedule_loop"):
    setattr(tasks, f, noop)
telegram.poll_loop = noop

# ================= 1. Dockerfile / entrypoint =================
DF = open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8").read()
cmd = re.search(r"^CMD (\[.*\])$", DF, re.M).group(1)
ok("Dockerfile: --proxy-headers --forwarded-allow-ips 127.0.0.1 (user commit 1b4c557)", '"--forwarded-allow-ips", "127.0.0.1"' in cmd and '"--proxy-headers"' in cmd)
ok("Dockerfile: no wildcard '*' trust anymore", '"*"' not in cmd)
ok("Dockerfile: entrypoint still wraps CMD", 'ENTRYPOINT ["/entrypoint.sh"]' in DF)

EPS = open(os.path.join(ROOT, "entrypoint.sh"), encoding="utf-8").read()
ok("entrypoint unchanged: passes CMD through (no extra trust added)", "forwarded" not in EPS and 'exec setpriv --reuid=10001 --regid=10001 --init-groups "$@"' in EPS)

# ================= 2. 经 ProxyHeadersMiddleware（与 Dockerfile 相同：只信任 127.0.0.1） =================
# 线上拓扑：cloudflared（host 网络）→ 宿主 127.0.0.1:端口 → docker 网关 172.x.0.1 → 容器。源地址是网关，不受 uvicorn 信任。
proxied = ProxyHeadersMiddleware(main.app, trusted_hosts="127.0.0.1")
seen = {}


@main.app.get("/api/_t/whoami")
def _whoami(req: main.Request):
    from app.routers.common import client_ip
    seen.update(ip=req.client.host if req.client else None, scheme=req.url.scheme, client_ip=client_ip(req))
    return {"ok": True}


main.app.router.routes.insert(0, main.app.router.routes.pop())   # 放在 /static 挂载之前
main.PUBLIC.add("/api/_t/whoami")   # 测试路由免登录
os.environ["COOKIE_SECURE"] = "false"
with TestClient(main.app):   # 跑一次生命周期（init_db 等）
    pass
lo = TestClient(proxied, base_url="http://panel.local", client=("127.0.0.1", 40000))        # 反代与容器同一网络命名空间
gw = TestClient(proxied, base_url="http://panel.local", client=("172.19.0.1", 40000))       # docker 网关（宿主上的 cloudflared）
ext = TestClient(proxied, base_url="http://panel.local", client=("198.51.100.200", 40000))  # 直接对外暴露时的外部访问者

h = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https", "CF-Connecting-IP": "203.0.113.9"}
lo.get("/api/_t/whoami", headers=h)
ok("trusted 127.0.0.1: real IP + https from proxy headers", seen.get("ip") == "203.0.113.9" and seen.get("scheme") == "https", seen)
ext.get("/api/_t/whoami", headers={"X-Forwarded-For": "10.0.0.1", "X-Forwarded-Proto": "https"})
ok("external peer: forged X-Forwarded-For / Proto ignored (was trusted with '*')", seen.get("ip") == "198.51.100.200" and seen.get("scheme") == "http", seen)
gw.get("/api/_t/whoami", headers=h)
ok("docker gateway peer: uvicorn no longer trusts its headers (peer IP kept)", seen.get("ip") == "172.19.0.1", seen)
ok("TRUST_PROXY unset: client_ip = peer (gateway)", seen.get("client_ip") == "172.19.0.1", seen)
with mock.patch.dict(os.environ, {"TRUST_PROXY": "true"}):
    gw.get("/api/_t/whoami", headers=h)
    ok("TRUST_PROXY=true (live .env): client_ip = CF-Connecting-IP despite gateway peer", seen.get("client_ip") == "203.0.113.9", seen)
    gw.get("/api/_t/whoami", headers={"X-Forwarded-For": "203.0.113.10, 172.19.0.1"})
    ok("TRUST_PROXY=true: falls back to first X-Forwarded-For", seen.get("client_ip") == "203.0.113.10", seen)

_real_sleep = asyncio.sleep
with mock.patch("app.routers.auth.asyncio.sleep", new=lambda s: _real_sleep(0)), mock.patch.dict(os.environ, {"TRUST_PROXY": "true"}):
    # 登录 + 会话 cookie（经 cloudflared → 网关）
    r = gw.post("/api/login", json={"password": "devpassword123"}, headers=h)
    ok("login via gateway (TRUST_PROXY=true): 200 + HttpOnly session cookie", r.status_code == 200 and "tc_session" in r.cookies
       and "httponly" in r.headers.get("set-cookie", "").lower(), r.text)
    ok("session cookie works for API", gw.get("/api/accounts", headers=h).status_code == 200)
    ok("COOKIE_SECURE=false -> cookie not Secure (env-controlled, not scheme-dependent)", "secure" not in r.headers.get("set-cookie", "").lower())
    with mock.patch.object(core, "COOKIE_SECURE", True):
        r = gw.post("/api/login", json={"password": "devpassword123"}, headers=h)
        ok("COOKIE_SECURE=true (live) -> Secure cookie even though uvicorn sees http", "secure" in r.headers.get("set-cookie", "").lower())
    gw.cookies.clear()
    # 按真实 IP 限流：A 被锁，B 不受影响，网关本身不被锁
    A = {"CF-Connecting-IP": "203.0.113.50"}
    B = {"CF-Connecting-IP": "203.0.113.51"}
    for _ in range(2):
        gw.post("/api/login", json={"password": "wrong-password"}, headers=A)
    ok("rate limit: client A locked after LOGIN_MAX_FAIL", gw.post("/api/login", json={"password": "devpassword123"}, headers=A).status_code == 429)
    ok("rate limit: client B (different real IP) not locked", gw.post("/api/login", json={"password": "devpassword123"}, headers=B).status_code == 200)
    ok("rate limit keyed by real IP, not by the gateway", core.login_locked("203.0.113.50") > 0 and core.login_locked("172.19.0.1") == 0)
    gw.cookies.clear()
with mock.patch("app.routers.auth.asyncio.sleep", new=lambda s: _real_sleep(0)):
    # TRUST_PROXY 未开（直接对外暴露）：伪造 XFF 不能绕过锁定
    for _ in range(2):
        ext.post("/api/login", json={"password": "wrong-password"}, headers={"X-Forwarded-For": "198.51.100.1"})
    r = ext.post("/api/login", json={"password": "devpassword123"}, headers={"X-Forwarded-For": "198.51.100.2"})
    ok("direct exposure: rotating forged XFF cannot dodge lockout", r.status_code == 429 and core.login_locked("198.51.100.200") > 0)

# guard-agent 安装命令里的面板地址仍按 X-Forwarded-Proto 生成 https（不依赖 uvicorn 的 scheme）
GA = open(os.path.join(ROOT, "app", "routers", "guard_agent.py"), encoding="utf-8").read()
ok("guard-agent install URL reads x-forwarded-proto header directly", 'req.headers.get("x-forwarded-proto")' in GA)

# ================= 3. 兜底 500 =================
logging.getLogger("tricloud").setLevel(logging.ERROR)


@main.app.get("/api/_t/boom")
def _boom():
    raise RuntimeError("secret-path /data/tricloud.db SELECT password_hash")


main.app.router.routes.insert(0, main.app.router.routes.pop())
with TestClient(main.app, raise_server_exceptions=False) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(main.log, "exception") as lx:
        r = c.get("/api/_t/boom")
    j = r.json()
    ok("500: status 500", r.status_code == 500)
    ok("500: no exception text / type in body (user commit 8e9243e)", "secret-path" not in r.text and "RuntimeError" not in r.text and j.get("detail") == "服务器内部错误", r.text)
    ok("500: request_id (8 hex) returned", re.fullmatch(r"[0-9a-f]{8}", j.get("request_id", "")))
    ok("500: logged with request_id, method and path", lx.called and j["request_id"] in lx.call_args[0] and "GET /api/_t/boom" in lx.call_args[0])
    r = c.get("/api/accounts/9999/instances")
    ok("non-500 errors unchanged (404 detail kept)", r.status_code == 404)

# ================= 4. 备份恢复回滚 =================
core.ex("INSERT INTO accounts(provider, name, region, cred_enc, created) VALUES('aws', 'keep-me', 'us-east-1', ?, 0)", (core.encrypt({"a": 1}),))
PW = "backup-pass-123"
blob = security.make_backup(PW)
key_before = open(core.KEY_PATH, "rb").read()
core.ex("INSERT INTO accounts(provider, name, region, cred_enc, created) VALUES('aws', 'added-after-backup', 'us-east-1', ?, 0)", (core.encrypt({"b": 2}),))
names = lambda: sorted(r["name"] for r in core.q("SELECT name FROM accounts"))   # noqa: E731
before = names()
real_migrate = core.migrate
with mock.patch.object(core, "migrate", side_effect=RuntimeError("migrate exploded")):
    try:
        security.restore_backup(blob, PW)
        ok("restore failure raises", False)
    except RuntimeError:
        ok("restore failure raises", True)
ok("rollback: DB back to pre-restore content", names() == before and "added-after-backup" in before)
ok("rollback: fernet.key unchanged", open(core.KEY_PATH, "rb").read() == key_before)
ok("rollback: data still decryptable", core.decrypt(core.q("SELECT cred_enc FROM accounts WHERE name='keep-me'", one=True)["cred_enc"]) == {"a": 1})
ok("rollback: temp files cleaned", not any(os.path.exists(os.path.join(core.DATA_DIR, f)) for f in (".restore.tmp.db", ".restore.bak.db", ".restore.bak.key")))
try:
    security.restore_backup(blob, "wrong-pass-xx")
    ok("wrong passphrase rejected", False)
except ValueError as e:
    ok("wrong passphrase rejected, data untouched", "口令错误" in str(e) and names() == before)
security.restore_backup(blob, PW)
ok("successful restore: backup content restored", "added-after-backup" not in names() and "keep-me" in names())
ok("successful restore: temp files cleaned", not any(os.path.exists(os.path.join(core.DATA_DIR, f)) for f in (".restore.tmp.db", ".restore.bak.db", ".restore.bak.key", "fernet.key.tmp")))

passed = sum(1 for _, x in R if x)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
