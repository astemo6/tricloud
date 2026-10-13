"""TriCloud 面板入口：OCI / AWS / Azure 三合一管理。"""
import asyncio
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import base64

from . import accounts_import, core, extras, guard, hostname, services, tasks, telegram, traffic_guard
from . import credits as creditsm
from . import health as healthm

WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
VERSION = "1.6.0"

REQUIRED = {
    "oci": ["user", "tenancy", "fingerprint", "key_content", "region"],
    "aws": ["access_key", "secret_key", "region"],
    "azure": ["tenant_id", "client_id", "client_secret", "subscription_id"],
}


@asynccontextmanager
async def lifespan(app):
    core.init_db()
    core.fernet()
    core.ensure_password()
    r = tasks.recover_on_startup()
    if r["resumed"] or r["interrupted"]:
        print(f"[tricloud] 重启恢复：抢机任务续抢 {r['resumed']} 个，其他任务标记中断 {r['interrupted']} 个", flush=True)
    bg = [asyncio.create_task(f()) for f in (tasks.task_loop, tasks.monitor_loop, tasks.schedule_loop, telegram.poll_loop)]
    yield
    for t in bg:
        t.cancel()


app = FastAPI(title="TriCloud", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
PUBLIC = {"/api/login", "/api/health"}


def _token(req: Request):
    auth = req.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return req.cookies.get("tc_session")


def client_ip(req: Request):
    if os.environ.get("TRUST_PROXY", "false").lower() == "true":
        for h in ("cf-connecting-ip", "x-real-ip"):
            if req.headers.get(h):
                return req.headers[h]
        xff = req.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return req.client.host if req.client else "unknown"


AUDIT_SKIP = {"/api/logout"}


@app.middleware("http")
async def auth_mw(req: Request, call_next):
    path = req.url.path
    actor = "session"
    if path.startswith("/api/") and path not in PUBLIC:
        tok = _token(req)
        if core.check_session(tok):
            pass
        elif tok and (tk := extras.check_api_token(tok, req.method)):
            # v1.5：从旧版迁移来的 Token（不以 tc_ 开头）在审计里只记 id，不记 Token 片段
            actor = "api_token:" + (tok[:10] if tok.startswith("tc_") else f"legacy#{tk['id']}")
            # API Token 不能管理安全设置
            if path.startswith(("/api/2fa", "/api/tokens", "/api/password", "/api/backup", "/api/restore", "/api/secrets")):
                return JSONResponse({"detail": "API Token 无权访问此接口"}, status_code=403)
        else:
            return JSONResponse({"detail": "未登录"}, status_code=401)
    resp = await call_next(req)
    if path.startswith("/api/") and req.method != "GET" and path not in AUDIT_SKIP:
        try:
            extras.audit(client_ip(req), actor if path != "/api/login" else "-", f"{req.method} {path}",
                         f"HTTP {resp.status_code}")
        except Exception:
            pass
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@app.exception_handler(Exception)
async def err(req, exc):
    msg = str(exc)
    m = re.search(r"\((UnauthorizedOperation|AccessDenied\w*|AuthorizationFailed|NotAuthorized\w*)\)", msg) or \
        re.search(r"'code': '(NotAuthorizedOrNotFound|NotAuthenticated)'", msg)
    if m:   # 云账号权限不足：不是面板故障，给出缺哪个权限
        act = re.search(r"perform:? ([\w:.\-/]+)", msg) or re.search(r"action '([\w:.\-/]+)'", msg)
        tip = f"缺少 {act.group(1)} 权限" if act else "请检查该账号的 IAM / 角色授权"
        return JSONResponse({"detail": f"云账号权限不足（{m.group(1)}）：{tip}"}, status_code=403)
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


def run(fn, *a, **kw):
    return asyncio.to_thread(fn, *a, **kw)


async def guarded(acc_id, op, body, region=None):
    """免费额度护栏：可能超额时返回 409 + 警告列表，前端二次确认后带 confirm_overage 重发。"""
    if body.get("confirm_overage") or core.get_setting("free_guard", True) is False:
        return
    w = await run(guard.check, acc_id, op, body, region)
    if w:
        raise HTTPException(409, {"msg": "可能超出免费额度", "guard": w})


def need_acc(acc_id, provider=None):
    acc = core.get_account(acc_id)
    if not acc:
        raise HTTPException(404, "账号不存在")
    if provider and acc["provider"] != provider:
        raise HTTPException(400, f"该接口仅支持 {provider}")
    return acc


# ---------------- 认证 ----------------
@app.get("/api/meta")
def meta():
    """App / Web 用：当前可添加的云厂商。"""
    return {"providers": list(services.PROVIDERS)}


@app.get("/api/health")
def health_check():
    return {"ok": True, "version": VERSION}


@app.post("/api/login")
async def login(req: Request, body: dict = Body(...)):
    ip = client_ip(req)
    wait = core.login_locked(ip)
    if wait:
        raise HTTPException(429, f"失败次数过多，请 {wait // 60 + 1} 分钟后再试")
    ok = await run(core.verify_password, body.get("password", ""), core.get_setting("password_hash", ""))
    if ok and extras.totp_enabled():
        if not body.get("otp"):
            raise HTTPException(401, "需要二次验证码")   # 前端据此显示验证码输入框
        ok = extras.totp_verify(core.get_secret_setting("totp_secret"), body.get("otp"))
    if not ok:
        core.login_failed(ip)
        await asyncio.sleep(1)
        raise HTTPException(401, "密码或验证码错误")
    core.login_ok(ip)
    token = core.new_session()
    # Android App 使用 Bearer token；浏览器只拿 HttpOnly Cookie，不把 token 暴露给 JS
    resp = JSONResponse({"ok": True, "token": token} if body.get("client") == "app" else {"ok": True})
    resp.set_cookie("tc_session", token, max_age=core.SESSION_TTL, httponly=True, samesite="lax",
                    secure=core.COOKIE_SECURE, path="/")
    return resp


@app.post("/api/logout")
def logout(req: Request):
    core.drop_session(_token(req))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("tc_session", path="/")
    return resp


@app.post("/api/password")
async def change_password(body: dict = Body(...)):
    if not await run(core.verify_password, body.get("old", ""), core.get_setting("password_hash", "")):
        raise HTTPException(400, "原密码错误")
    new = body.get("new", "")
    if len(new) < 10:
        raise HTTPException(400, "新密码至少 10 位")
    core.set_setting("password_hash", await run(core.hash_password, new))
    core.drop_all_sessions()
    return {"ok": True}


# ---------------- 账号 ----------------
@app.get("/api/accounts")
def accounts():
    rows = core.list_accounts()
    for r in rows:   # 只回显代理主机、用户名、是否设置了密码，不回显代理密码
        r.update(core.proxy_view(core.get_account(r["id"], with_cred=True)["cred"]))
    return rows


def _clean_cred(prov, cred):
    cred = {k: (v.strip() if isinstance(v, str) and k != "key_content" else v) for k, v in (cred or {}).items() if v}
    miss = [k for k in REQUIRED[prov] if not cred.get(k)]
    return cred, miss


def _detect_created(prov_obj):
    """云账号创建日期：目前只有 OCI 能免费读到（租户根区间创建时间），其他云需手动填写。"""
    fn = getattr(prov_obj, "created_at", None)
    if not fn:
        return None
    try:
        return fn()
    except Exception:
        return None


def _valid_date(v, field):
    if v in (None, ""):
        return None
    import datetime as _dt
    try:
        return _dt.date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise HTTPException(400, f"{field} 日期格式应为 YYYY-MM-DD")


def _create_account_sync(prov, name, cred, cloud_created_at=None):
    """校验凭证并入库（add_account 与批量导入共用）。失败抛 ValueError(原因)。"""
    p = services.PROVIDERS[prov](core.runtime_cred(cred), cred.get("region"))
    try:
        info = p.test()
    except Exception as e:
        raise ValueError(f"凭证校验失败：{e}")
    created = cloud_created_at or _detect_created(p)
    acc_id = core.ex("INSERT INTO accounts(provider,name,region,cred_enc,created,cloud_created_at) VALUES(?,?,?,?,?,?)",
                     (prov, name, cred.get("region"), core.encrypt(cred), int(time.time()), created))
    return acc_id, info


@app.post("/api/accounts")
async def add_account(body: dict = Body(...)):
    prov, name, cred = body.get("provider"), (body.get("name") or "").strip(), body.get("cred") or {}
    if prov not in REQUIRED:
        raise HTTPException(400, "provider 无效")
    cred, miss = _clean_cred(prov, cred)
    if miss or not name:
        raise HTTPException(400, f"缺少字段：{', '.join(miss) or 'name'}")
    created = _valid_date(body.get("cloud_created_at"), "cloud_created_at")
    try:
        acc_id, info = await run(_create_account_sync, prov, name, cred, created)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": acc_id, "test": info}


# ---------------- v1.6：粘贴内容自动识别（只解析，不校验、不保存） ----------------
@app.post("/api/accounts/parse")
async def parse_accounts_text(body: dict = Body(...)):
    """添加账号弹窗用：把粘贴的一堆内容识别成账号字段，返回给前端自动填表。"""
    text = body.get("text") or ""
    if len(text) > 200_000:
        raise HTTPException(400, "内容过长")
    items = [it for it in accounts_import.parse(text, body.get("provider")) if not it.get("error") or it.get("provider")]
    out = []
    for it in items[:50]:
        prov = it.get("provider")
        miss = [k for k in REQUIRED.get(prov, []) if not (it.get("cred") or {}).get(k)] if prov else []
        cred = it.get("cred") or {}
        out.append({"provider": prov, "name": it.get("name") or "", "cred": cred, "missing": miss, "error": it.get("error")})
    return {"items": out}


# ---------------- v1.4：批量添加 / 一键测活 ----------------
@app.post("/api/accounts/batch")
async def add_accounts_batch(body: dict = Body(...)):
    """粘贴多段 JSON 或 OCI config，逐条校验（并发测试凭证），返回每条的结果。dry_run=true 只解析不入库。"""
    text = body.get("text") or ""
    if len(text) > 200_000:
        raise HTTPException(400, "内容过长")
    items = accounts_import.parse(text, body.get("provider"))
    if not items:
        raise HTTPException(400, "没有解析到任何账号")
    if len(items) > 50:
        raise HTTPException(400, "一次最多 50 个账号")
    existing = {(a["provider"], a["name"]) for a in core.list_accounts()}
    seen = set()

    async def one(idx, it):
        base = {"index": idx + 1, "provider": it.get("provider"), "name": it.get("name") or ""}
        if it.get("error"):
            return dict(base, ok=False, error=it["error"])
        prov = it["provider"]
        if prov not in REQUIRED:
            return dict(base, ok=False, error="不支持的云厂商")
        cred, miss = _clean_cred(prov, it["cred"])
        name = it["name"] or f"{prov.upper()}-{(cred.get('region') or 'acc')}-{idx + 1}"
        base["name"] = name
        if miss:
            return dict(base, ok=False, error=f"缺少字段：{', '.join(miss)}")
        if (prov, name) in existing or (prov, name) in seen:
            return dict(base, ok=False, error="同名账号已存在")
        seen.add((prov, name))
        if body.get("dry_run"):
            return dict(base, ok=True, dry_run=True)
        t0 = time.time()
        try:
            created = _valid_date(it.get("cloud_created_at"), "cloud_created_at")
            acc_id, _ = await asyncio.wait_for(run(_create_account_sync, prov, name, cred, created), timeout=45)
        except asyncio.TimeoutError:
            return dict(base, ok=False, error="校验超时（45 秒）")
        except (ValueError, HTTPException) as e:
            return dict(base, ok=False, error=str(getattr(e, "detail", e))[:300])
        except Exception as e:
            return dict(base, ok=False, error=f"{type(e).__name__}: {str(e)[:250]}")
        return dict(base, ok=True, id=acc_id, ms=int((time.time() - t0) * 1000))

    sem = asyncio.Semaphore(8)

    async def limited(i, it):
        async with sem:
            return await one(i, it)
    results = await asyncio.gather(*[limited(i, it) for i, it in enumerate(items)])
    return {"total": len(results), "ok": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"]),
            "results": results}


def _test_account_sync(acc_id):
    acc = core.get_account(acc_id)
    t0 = time.time()
    try:
        services.drop_provider_cache(acc_id)    # 用最新凭证 / 代理重新建连接
        p = services.provider(acc_id)
        info = p.test()
        ms = int((time.time() - t0) * 1000)
        if not acc.get("cloud_created_at"):
            d = _detect_created(p)
            if d:
                core.ex("UPDATE accounts SET cloud_created_at=? WHERE id=?", (d, acc_id))
        core.ex("UPDATE accounts SET last_test_ok=1, last_test_ms=?, last_test_at=?, last_test_error=NULL WHERE id=?",
                (ms, int(time.time()), acc_id))
        return {"account_id": acc_id, "name": acc["name"], "provider": acc["provider"], "ok": True, "ms": ms,
                "info": {k: v for k, v in (info or {}).items() if k in ("name", "home_region", "subscription", "account", "arn")}}
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        err = f"{type(e).__name__}: {str(e)[:300]}"
        core.ex("UPDATE accounts SET last_test_ok=0, last_test_ms=?, last_test_at=?, last_test_error=? WHERE id=?",
                (ms, int(time.time()), err, acc_id))
        return {"account_id": acc_id, "name": acc["name"], "provider": acc["provider"], "ok": False, "ms": ms, "error": err}


async def _test_with_timeout(acc_id, timeout=30):
    try:
        return await asyncio.wait_for(run(_test_account_sync, acc_id), timeout=timeout)
    except asyncio.TimeoutError:
        acc = core.get_account(acc_id) or {}
        core.ex("UPDATE accounts SET last_test_ok=0, last_test_ms=?, last_test_at=?, last_test_error=? WHERE id=?",
                (timeout * 1000, int(time.time()), "超时", acc_id))
        return {"account_id": acc_id, "name": acc.get("name"), "provider": acc.get("provider"), "ok": False,
                "ms": timeout * 1000, "error": f"超时（{timeout} 秒）"}


@app.post("/api/accounts/test-all")
async def test_all_accounts(body: dict = Body(default={})):
    """并发测活：provider 为空 = 全部账号，否则只测该云。"""
    prov = body.get("provider") or None
    if prov and prov not in REQUIRED:
        raise HTTPException(400, "provider 无效")
    ids = [a["id"] for a in core.list_accounts() if (not prov or a["provider"] == prov) and not a.get("disabled")]   # v1.6：停用账号跳过
    sem = asyncio.Semaphore(10)

    async def one(i):
        async with sem:
            return await _test_with_timeout(i)
    t0 = time.time()
    results = await asyncio.gather(*[one(i) for i in ids])
    return {"total": len(results), "ok": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"]),
            "ms": int((time.time() - t0) * 1000), "results": results}


@app.post("/api/accounts/{acc_id}/test")
async def test_account(acc_id: int):
    need_acc(acc_id)
    return await _test_with_timeout(acc_id)


def _detect_created_sync(acc_id):
    acc = core.get_account(acc_id)
    if acc["provider"] != "oci":
        raise HTTPException(400, "只有 OCI 能自动读取账号创建日期")
    try:
        d = services.provider(acc_id).created_at()
    except Exception as e:
        raise HTTPException(502, f"读取失败：{e}")
    if not d:
        raise HTTPException(502, "OCI 未返回租户创建时间")
    core.ex("UPDATE accounts SET cloud_created_at=? WHERE id=?", (d, acc_id))
    return {"cloud_created_at": d}


@app.post("/api/accounts/{acc_id}/detect-created")
async def detect_created(acc_id: int):
    """OCI：读取租户根区间创建时间并写入（迁移来的账号没测活时为空）。"""
    return await run(_detect_created_sync, acc_id)


@app.patch("/api/accounts/{acc_id}")
def edit_account(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id)
    if body.get("name"):
        core.ex("UPDATE accounts SET name=? WHERE id=?", (body["name"], acc_id))
    if any(k in body for k in ("proxy", "proxy_user", "proxy_pass", "proxy_pass_clear")):
        acc = core.get_account(acc_id, with_cred=True)
        cred = _apply_proxy_patch(dict(acc["cred"]), body)
        core.ex("UPDATE accounts SET cred_enc=? WHERE id=?", (core.encrypt(cred), acc_id))
        services.drop_provider_cache(acc_id)
    if isinstance(body.get("cred"), dict) and body["cred"]:
        _apply_cred_patch(acc_id, body["cred"])
    if body.get("region"):
        acc = core.get_account(acc_id, with_cred=True)
        cred = dict(acc["cred"], region=body["region"])
        core.ex("UPDATE accounts SET region=?, cred_enc=? WHERE id=?", (body["region"], core.encrypt(cred), acc_id))
        services.drop_provider_cache(acc_id)
    # v1.4：云账号创建日期 / Credit 总额 / Azure 教育优惠到期日（空字符串 = 清除）
    if "cloud_created_at" in body:
        core.ex("UPDATE accounts SET cloud_created_at=? WHERE id=?", (_valid_date(body["cloud_created_at"], "cloud_created_at"), acc_id))
    if "credit_total" in body:
        core.ex("UPDATE accounts SET credit_total=? WHERE id=?", (_num_or_none(body["credit_total"], "credit_total"), acc_id))
    if "edu_expires_at" in body:
        core.ex("UPDATE accounts SET edu_expires_at=? WHERE id=?", (_valid_date(body["edu_expires_at"], "edu_expires_at"), acc_id))
    return {"ok": True}


def _apply_proxy_patch(cred, body):
    """v1.5 代理编辑：proxy（URL，空 = 清除代理及账密）、proxy_user（空 = 清除用户名）、
    proxy_pass（留空 = 不改）、proxy_pass_clear（true = 清除密码）。旧的「URL 内嵌 user:pass」写法照常可用。"""
    if "proxy" in body:
        px = (body.get("proxy") or "").strip()
        if px and not px.startswith(core.PROXY_SCHEMES):
            raise HTTPException(400, "代理需以 http:// https:// socks5:// 开头")
        if px:
            cred["proxy"] = px
        else:
            for k in ("proxy", "proxy_user", "proxy_pass"):
                cred.pop(k, None)
    if "proxy_user" in body:
        u = (body.get("proxy_user") or "").strip()
        if u:
            cred["proxy_user"] = u
        else:
            cred.pop("proxy_user", None)
    if body.get("proxy_pass"):
        cred["proxy_pass"] = str(body["proxy_pass"])
    if body.get("proxy_pass_clear"):
        cred.pop("proxy_pass", None)
    if (cred.get("proxy_user") or cred.get("proxy_pass")) and not cred.get("proxy"):
        raise HTTPException(400, "请先填写代理地址（proxy），再填用户名 / 密码")
    return cred


# 账号编辑回显：这些字段明文回显并可直接修改；其余凭证字段只显示「已设置」，留空不改
NON_SENSITIVE = {"oci": ("region", "compartment", "home_region"), "aws": ("region",), "azure": ("region",)}
# 可识别但不算密钥的 ID 类字段：只回显末 6 位，方便核对是哪个账号
MASKED = {"oci": ("user", "tenancy", "fingerprint"), "aws": ("access_key",), "azure": ("tenant_id", "client_id", "subscription_id")}
CRED_KEYS = {
    "oci": ("user", "tenancy", "fingerprint", "key_content", "pass_phrase", "region", "compartment", "home_region"),
    "aws": ("access_key", "secret_key", "region"),
    "azure": ("tenant_id", "client_id", "client_secret", "subscription_id", "region"),
}


def _apply_cred_patch(acc_id, patch):
    """部分更新凭证：非敏感字段提交即改（region 不能为空），敏感字段非空才改；有变化时先测活通过再保存。"""
    acc = core.get_account(acc_id, with_cred=True)
    prov, cred = acc["provider"], dict(acc["cred"])
    changed = False
    for k, v in patch.items():
        if k not in CRED_KEYS[prov]:
            continue
        v = v.strip() if isinstance(v, str) and k != "key_content" else v
        if k in NON_SENSITIVE[prov]:
            if k == "region" and not v:
                raise HTTPException(400, "区域不能为空")
            if (cred.get(k) or "") != (v or ""):
                if v:
                    cred[k] = v
                else:
                    cred.pop(k, None)
                changed = True
        elif v and cred.get(k) != v:
            cred[k] = v
            changed = True
    if not changed:
        return False
    try:
        services.PROVIDERS[prov](core.runtime_cred(cred), cred.get("region")).test()
    except Exception as e:
        raise HTTPException(400, f"凭证校验失败（未保存）：{e}")
    core.ex("UPDATE accounts SET cred_enc=?, region=? WHERE id=?", (core.encrypt(cred), cred.get("region"), acc_id))
    services.drop_provider_cache(acc_id)
    return True


@app.get("/api/accounts/{acc_id}/detail")
def account_detail(acc_id: int):
    """v1.5 账号编辑回显：非敏感字段明文、ID 类字段只显示末 6 位、密钥类只标记是否已设置。"""
    acc = need_acc(acc_id)
    cred = core.get_account(acc_id, with_cred=True)["cred"]
    prov = acc["provider"]
    fields = {}
    for k in CRED_KEYS[prov]:
        v = cred.get(k)
        if k in NON_SENSITIVE[prov]:
            fields[k] = v or ""
        elif k in MASKED[prov]:
            fields[k] = {"set": bool(v), "hint": ("…" + str(v)[-6:]) if v else ""}
        else:
            fields[k] = {"set": bool(v)}
    out = {k: acc.get(k) for k in ("id", "name", "provider", "region", "cloud_created_at", "credit_total", "edu_expires_at")}
    out.update(core.proxy_view(cred), fields=fields)
    return out


def _num_or_none(v, field, minimum=0.0):
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field} 需为数字")
    if x < minimum:
        raise HTTPException(400, f"{field} 不能小于 {minimum:g}")
    return x


def _deleted_snapshot(acc):
    """删除前留档：存活天数（云上创建日期优先，否则面板添加时间）+ 预估费用（只读本地缓存，绝不调用云 API）。"""
    import datetime as _dt
    import json as _json
    now = time.time()
    days, basis = None, None
    if acc.get("cloud_created_at"):
        try:
            d0 = _dt.datetime.fromisoformat(str(acc["cloud_created_at"])[:10]).timestamp()
            days, basis = round((now - d0) / 86400, 1), "云上创建日期"
        except ValueError:
            pass
    if days is None and acc.get("created"):
        days, basis = round((now - acc["created"]) / 86400, 1), "面板添加时间"
    cost, cur, cbasis = None, None, "无账单记录"
    if acc["provider"] == "aws":
        row = core.q("SELECT data, fetched_at FROM billing_cache WHERE account_id=?", (acc["id"],), one=True)
        if row:
            try:
                d = _json.loads(row["data"])
                if d.get("total") is not None:
                    cost, cur, cbasis = float(d["total"]), d.get("currency") or "USD", f"账单缓存 {d.get('period') or ''}".strip()
            except (ValueError, TypeError):
                pass
    else:
        row = core.q("SELECT month, total, currency FROM billing_months WHERE account_id=? ORDER BY month DESC LIMIT 1",
                     (acc["id"],), one=True)
        if row and row["total"] is not None:
            cost, cur, cbasis = float(row["total"]), row["currency"] or "USD", f"{row['month']} 月账单记录"
    return {"lifecycle_days": days, "age_basis": basis, "est_cost": cost, "currency": cur, "cost_basis": cbasis}


@app.delete("/api/accounts/{acc_id}")
def del_account(acc_id: int):
    acc = core.get_account(acc_id)
    if acc:   # v1.5：记入「已删账号」
        snap = _deleted_snapshot(acc)
        core.ex("INSERT INTO deleted_accounts(provider,name,region,lifecycle_days,age_basis,est_cost,currency,cost_basis,created,"
                "deleted_at,source) VALUES(?,?,?,?,?,?,?,?,?,?,'panel')",
                (acc["provider"], acc["name"], acc.get("region"), snap["lifecycle_days"], snap["age_basis"], snap["est_cost"],
                 snap["currency"], snap["cost_basis"], acc.get("created"), int(time.time())))
    for t in ("monitors", "billing_cache", "aws_credits", "billing_months", "ip_changes"):
        core.ex(f"DELETE FROM {t} WHERE account_id=?", (acc_id,))
    core.ex("UPDATE tasks SET status='stopped' WHERE account_id=? AND status='running'", (acc_id,))
    core.ex("DELETE FROM accounts WHERE id=?", (acc_id,))
    services.drop_provider_cache(acc_id)
    return {"ok": True}


@app.get("/api/accounts/{acc_id}/regions")
async def regions(acc_id: int):
    need_acc(acc_id)
    return await run(services.provider(acc_id).regions)


# ---------------- 实例（通用） ----------------
@app.get("/api/accounts/{acc_id}/instances")
async def instances(acc_id: int, region: str = None, kind: str = "vm"):
    need_acc(acc_id)
    return await run(services.list_instances, acc_id, region, kind)


@app.post("/api/accounts/{acc_id}/instances/action")
async def inst_action(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id)
    act = body.get("action")
    if act not in ("start", "stop", "reboot", "terminate", "hard_reboot"):
        raise HTTPException(400, "无效操作")
    if act == "terminate" and not body.get("confirm"):
        raise HTTPException(400, "终止需确认")
    return await run(services.instance_action, acc_id, body["instance_id"], act, body.get("region"), body.get("kind", "vm"),
                     bool(body.get("preserve_boot_volume")))


@app.post("/api/accounts/{acc_id}/instances/change-ip")
async def change_ip(acc_id: int, body: dict = Body(...)):
    acc = need_acc(acc_id)
    p = {"instance_id": body["instance_id"], "region": body.get("region"), "kind": body.get("kind", "vm"),
         "mode": body.get("mode", "auto"), "name": body.get("name")}
    raw = body.get("cidrs") or ""
    raw = ",".join(map(str, raw)) if isinstance(raw, list) else str(raw)
    cidrs = [c.strip() for c in raw.replace("，", ",").replace("\n", ",").split(",") if c.strip()]
    mr, qc = body.get("quality_max_risk"), str(body.get("quality_country") or "").strip()
    if mr not in (None, ""):   # v1.6：IP 质量条件（风险分上限 / 归属国家），走任务重复更换
        try:
            mr = int(mr)
            assert 0 <= mr <= 100
        except Exception:
            raise HTTPException(400, "风险分上限需为 0~100 的整数")
        p["quality_max_risk"] = mr
    if qc:
        if not re.fullmatch(r"[A-Za-z]{2}(\s*[,，]\s*[A-Za-z]{2})*", qc):
            raise HTTPException(400, "国家代码格式如 US 或 US,JP")
        p["quality_country"] = qc.upper().replace("，", ",")
    quality = "quality_max_risk" in p or "quality_country" in p
    if acc["provider"] == "oci" and not cidrs and not quality:   # OCI 换临时 IP 很快，同步返回
        r = await run(services.provider(acc_id, p["region"]).change_ip, p["instance_id"])
        r["dns"] = await run(extras.dns_sync, acc_id, p["instance_id"], r.get("new_ip"))
        core.ex("UPDATE monitors SET public_ip=?, fail_count=0 WHERE account_id=? AND instance_id=?",
                (r.get("new_ip"), acc_id, p["instance_id"]))
        tasks.record_ip_change(acc_id, p["instance_id"])
        return {"ok": True, **r}
    if cidrs:   # v1.4：以 ! 开头表示排除网段，可与普通网段混用
        try:
            extras.split_cidrs(cidrs)
        except ValueError as e:
            raise HTTPException(400, f"网段格式错误：{e}")
        cap = 100 if acc["provider"] == "oci" else 20   # AWS/Azure 每次换 IP 更慢、可能停机，次数上限更低
        p.update(cidrs=cidrs)
    if cidrs or quality:
        cap = 100 if acc["provider"] == "oci" else 20
        p.update(max_tries=max(1, min(cap, int(body.get("max_tries") or (20 if acc["provider"] == "oci" else 5)))))
    tid = tasks.create_task("change_ip", acc_id, p)
    tasks.record_ip_change(acc_id, p["instance_id"], False, tid)
    return {"ok": True, "task_id": tid}


@app.get("/api/accounts/{acc_id}/ip-change-usage")
def ip_change_usage(acc_id: int):
    need_acc(acc_id)
    return tasks.ip_change_usage(acc_id)


@app.get("/api/ip-change-usage")
def ip_change_usage_all():
    return [dict(tasks.ip_change_usage(a["id"]), name=a["name"], provider=a["provider"]) for a in core.list_accounts()]


@app.post("/api/accounts/{acc_id}/instances/resize")
async def resize(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id)
    await guarded(acc_id, "resize", body, body.get("region"))
    tid = tasks.create_task("resize", acc_id, {k: body.get(k) for k in
                            ("instance_id", "region", "name", "ocpus", "memory_gb", "shape", "size")})
    return {"ok": True, "task_id": tid}


@app.post("/api/accounts/{acc_id}/instances/{iid:path}/open-port")
async def inst_open_port(acc_id: int, iid: str, body: dict = Body(...)):
    """实例操作「开放端口」（三家云）：来源固定 0.0.0.0/0。port 可填 "8443" 或 "80, 443, 8000-8100"。
    OCI 写子网安全列表；AWS 写实例全部安全组；Azure 写网卡 / 子网 NSG。已存在的规则跳过。
    不带 confirm_public 返回 409（detail.public_warning）；空端口或 1-65535 返回 400。"""
    acc = need_acc(acc_id)
    iid = (body.get("instance_id") or "").strip() if iid.strip("/") in ("", "-", "_") else iid
    if not iid:
        raise HTTPException(400, "缺少实例 ID")
    if acc["provider"] == "aws" and body.get("kind", "vm") != "vm":
        raise HTTPException(400, "Lightsail 请在 AWS 控制台的“网络”页设置防火墙；此处仅支持 EC2")
    proto = str(body.get("protocol") or "tcp").strip().lower()
    if proto not in ("tcp", "udp"):
        raise HTTPException(400, "协议只能是 tcp 或 udp")
    port = str(body.get("port") if body.get("port") is not None else "").strip()
    if not port:
        raise HTTPException(400, "请填写端口，如 8443 或 80, 443, 8000-8100")
    from .providers.oci_provider import OCIProvider
    try:
        ranges = OCIProvider.parse_ports(port)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _public_guard("ingress", proto, "0.0.0.0/0", port, body.get("confirm_public"))
    try:
        res = await run(services.provider(acc_id, body.get("region")).open_ports, iid, proto, ranges)
    except (ValueError, LookupError) as e:
        raise HTTPException(400, str(e))
    parts = [f"{g['kind']} {g['name']}：新增 {g['added']} 条，跳过 {g['skipped']} 条（已存在）" for g in res.get("groups", [])]
    res["msg"] = f"{proto.upper()} {port}（来源 0.0.0.0/0）\n" + "\n".join(parts)
    return res


# ---------------- OCI ----------------
@app.post("/api/accounts/{acc_id}/oci/ipv6")
def oci_ipv6(acc_id: int, body: dict = Body(...)):
    """一键 IPv6 全链路，可能需要几分钟，走后台任务。"""
    need_acc(acc_id, "oci")
    return {"ok": True, "task_id": tasks.create_task("ipv6", acc_id, {k: body.get(k) for k in ("instance_id", "region", "name")})}


def _truthy(v, default=True):
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(v)


def rename_sync(acc, prov, inst_id, name, kind="vm"):
    """改名后同步系统主机名（尽力而为，绝不让改名失败），并写一条审计。"""
    r = hostname.sync(acc, prov, inst_id, name, kind)
    try:
        extras.audit("-", "hostname-sync", f"hostname-sync {acc['provider']}",
                     f"{inst_id} -> {r.get('hostname') or '-'}: {r['status']} {r.get('message', '')}")
    except Exception:
        pass
    return r


async def do_rename(acc_id, body, provider=None):
    acc = need_acc(acc_id, provider)
    name = (body.get("new_name") or "").strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    if len(name) > 255:
        raise HTTPException(400, "名称过长")
    if not body.get("instance_id"):
        raise HTTPException(400, "缺少 instance_id")
    kind = body.get("kind") or "vm"
    if acc["provider"] == "aws" and kind == "lightsail":
        raise HTTPException(400, "Lightsail 实例不支持改名")
    prov = services.provider(acc_id, body.get("region"))
    if not hasattr(prov, "rename"):
        raise HTTPException(400, "该云不支持改名")
    res = dict(await run(prov.rename, body["instance_id"], name) or {}, ok=True)
    # v1.5：sync_hostname 默认 true —— 通过云厂商 Run Command 执行固定命令改系统主机名
    res["hostname"] = await run(rename_sync, acc, prov, body["instance_id"], name, kind) \
        if _truthy(body.get("sync_hostname"), True) else None
    return res


@app.post("/api/accounts/{acc_id}/instances/rename")
async def inst_rename(acc_id: int, body: dict = Body(...)):
    """三家云通用改名：OCI 显示名 / AWS EC2 Name 标签 / Azure tricloud-name 标签（VM 资源名不可改）。"""
    return await do_rename(acc_id, body)


@app.post("/api/accounts/{acc_id}/oci/rename")
async def oci_rename(acc_id: int, body: dict = Body(...)):
    return await do_rename(acc_id, body, "oci")


@app.get("/api/accounts/{acc_id}/oci/boot-volume")
async def oci_bv(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await run(services.provider(acc_id, region).boot_volume, instance_id)


@app.post("/api/accounts/{acc_id}/oci/boot-volume")
async def oci_bv_update(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    await guarded(acc_id, "bootvol", body, body.get("region"))
    prov = services.provider(acc_id, body.get("region"))
    try:
        r = await run(prov.update_boot_volume, body["instance_id"], body.get("size_gb") or None, body.get("vpus_per_gb"))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    if body.get("size_gb") and body.get("grow") not in (None, False, "false", 0, "0"):   # v1.6：扩容后自动扩根分区
        await asyncio.sleep(0)
        r["grow"] = await run(prov.grow_fs, body["instance_id"], True)
    return r


def _public_guard(direction, protocol, cidr, port, confirmed):
    """入站来源为 0.0.0.0/0 或 ::/0：不允许放行全部端口；单条规则需二次确认（409）。"""
    if direction != "ingress" or str(cidr or "").replace(" ", "") not in PUBLIC_CIDRS:
        return
    from .providers.oci_provider import OCIProvider
    try:
        ranges = OCIProvider.parse_ports(port) if protocol in ("tcp", "udp") and str(port or "").strip() else []
    except ValueError as e:
        raise HTTPException(400, str(e))
    if protocol == "all" or (protocol in ("tcp", "udp") and (not ranges or any(a <= 1 and b >= 65535 for a, b in ranges))):
        raise HTTPException(400, "不支持对 0.0.0.0/0（或 ::/0）放行全部端口，请填写具体端口")
    if not confirmed:
        raise HTTPException(409, {"msg": "来源为 0.0.0.0/0：将对整个互联网开放", "public_warning": True})


@app.get("/api/accounts/{acc_id}/oci/security")
async def oci_sec(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await run(services.provider(acc_id, region).security_rules, instance_id)


@app.post("/api/accounts/{acc_id}/oci/security")
async def oci_sec_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    p, op = services.provider(acc_id, body.get("region")), body.get("op")
    if op == "add":
        if body.get("direction") not in ("ingress", "egress") or body.get("protocol", "").lower() not in ("tcp", "udp", "icmp", "icmpv6", "all"):
            raise HTTPException(400, "参数无效")
        _public_guard(body["direction"], body["protocol"].lower(), body.get("cidr", ""), body.get("port"), body.get("confirm_public"))
        try:
            return await run(p.add_security_rule, body["sl_id"], body["direction"], body["protocol"], body["cidr"],
                             body.get("port"), body.get("desc"))
        except ValueError as e:
            raise HTTPException(400, f"CIDR 无效：{e}")
    if op == "remove":
        return await run(p.remove_security_rule, body["sl_id"], body["direction"], int(body["idx"]))
    if op == "add_ports":
        # 放行指定端口（入站）：必须填写端口；来源默认 0.0.0.0/0，需 confirm_public
        protos = [x for x in (body.get("protocols") or ["tcp"]) if x in ("tcp", "udp")]
        cidr = (body.get("cidr") or "0.0.0.0/0").strip()
        if not protos or not body.get("instance_id"):
            raise HTTPException(400, "参数无效")
        if str(body.get("ports") or "").strip() == "":
            raise HTTPException(400, "请填写端口，如 80, 443, 8000-8100")
        from .providers.oci_provider import OCIProvider
        try:
            ranges = OCIProvider.parse_ports(body["ports"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        _public_guard("ingress", protos[0], cidr, body["ports"], body.get("confirm_public"))
        added = skipped = 0
        for pr in protos:
            try:
                res = await run(p.add_security_rules, body["instance_id"], body.get("sl_id"), "ingress", pr, cidr, ranges,
                                (body.get("desc") or "").strip() or None)
            except ValueError as e:
                raise HTTPException(400, str(e))
            added += res.get("added", 0); skipped += res.get("skipped", 0)
        return {"ok": True, "added": added, "skipped": skipped}
    raise HTTPException(400, "无效操作")


@app.get("/api/accounts/{acc_id}/oci/limits")
async def oci_limits(acc_id: int, region: str = None):
    need_acc(acc_id, "oci")
    fc, fm, basis = core.oci_a1_free(acc_id)
    r = await run(services.provider(acc_id, region).limits, (fc, fm))
    return dict(r, a1_basis=basis)


@app.get("/api/accounts/{acc_id}/oci/traffic")
async def oci_traffic(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await run(services.provider(acc_id, region).traffic, instance_id)


@app.get("/api/accounts/{acc_id}/traffic")
async def traffic(acc_id: int, instance_id: str, region: str = None, kind: str = "vm"):
    acc = need_acc(acc_id)
    p = services.provider(acc_id, region)
    return await run(p.traffic, instance_id) if acc["provider"] == "oci" else await run(p.traffic, instance_id, kind)


@app.post("/api/accounts/{acc_id}/oci/network")
def oci_network(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    return {"ok": True, "task_id": tasks.create_task("ensure_network", acc_id, {"region": body.get("region"), "instance_id": "-"})}


_OSV_CACHE = {}
OSV_TTL = 6 * 3600


@app.get("/api/accounts/{acc_id}/oci/os-versions")
async def oci_os_versions(acc_id: int, shape: str = None, region: str = None):
    """v1.5：创建/抢机表单「系统版本」下拉，按规格列平台镜像版本（A1=aarch64，E2=x86），缓存 6 小时。"""
    acc = need_acc(acc_id, "oci")
    key = (acc_id, region or acc.get("region"), shape or "")
    hit = _OSV_CACHE.get(key)
    if hit and time.time() - hit[0] < OSV_TTL:
        return hit[1]
    data = await run(services.provider(acc_id, region).os_versions, shape)
    _OSV_CACHE[key] = (time.time(), data)
    return data


@app.get("/api/accounts/{acc_id}/oci/ads")
async def oci_ads(acc_id: int, region: str = None):
    need_acc(acc_id, "oci")
    return await run(services.provider(acc_id, region).availability_domains)


def _created(acc_id, r):
    """创建成功后：随机 root 密码加密留存，前端只显示一次。"""
    if r.get("password"):
        extras.save_instance_secret(acc_id, r["id"], r["name"], r["username"], r["password"])
    return r


@app.post("/api/accounts/{acc_id}/oci/create")
async def oci_create(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    await guarded(acc_id, "create", body, body.get("region"))
    c = dict(body["create"], script=extras.resolve_script(body["create"]))
    return _created(acc_id, await run(services.provider(acc_id, body.get("region")).create_instance, c))


@app.post("/api/accounts/{acc_id}/oci/snatch")
async def oci_snatch(acc_id: int, body: dict = Body(...)):
    """批量抢机：account_ids 可同时给多个租户各起一个任务（各自用自己账号的默认区域或指定区域）。"""
    need_acc(acc_id, "oci")
    await guarded(acc_id, "create", body, body.get("region"))
    interval = max(30, int(body.get("interval") or 60))   # 下限 30s，防止被风控
    ids = [int(x) for x in (body.get("account_ids") or [acc_id])]
    out = []
    for aid in ids:
        need_acc(aid, "oci")
        region = body.get("region") if aid == acc_id else None
        out.append(tasks.create_task("snatch", aid, {"region": region, "create": body["create"], "interval": interval,
                                                     "max_attempts": int(body.get("max_attempts") or 0)}))
    return {"ok": True, "task_id": out[0], "task_ids": out}


# ---------------- AWS: EC2 创建 / 区域 ----------------
@app.get("/api/accounts/{acc_id}/aws/ec2-options")
async def ec2_opts(acc_id: int):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id).ec2_options)


@app.post("/api/accounts/{acc_id}/aws/ec2-create")
async def ec2_create(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    await guarded(acc_id, "create", body, body.get("region"))
    c = dict(body, script=extras.resolve_script(body))
    return _created(acc_id, await run(services.provider(acc_id, body.get("region")).ec2_create, c))


@app.get("/api/accounts/{acc_id}/aws/regions-status")
async def aws_regions_status(acc_id: int):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id).region_status)


@app.post("/api/accounts/{acc_id}/aws/enable-region")
async def aws_enable_region(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id).enable_region, body["region"])


_scan_cache = {}


@app.get("/api/accounts/{acc_id}/aws/scan")
async def aws_scan(acc_id: int, refresh: bool = False):
    need_acc(acc_id, "aws")
    c = _scan_cache.get(acc_id)
    if c and not refresh and time.time() - c["ts"] < 1800:
        return c["data"]
    data = {"regions": await run(services.provider(acc_id).scan_all_regions),
            "updated_at": services.now_local().strftime("%Y-%m-%d %H:%M")}
    _scan_cache[acc_id] = {"ts": time.time(), "data": data}
    return data


# ---------------- Azure ----------------
@app.get("/api/accounts/{acc_id}/azure/rgs")
async def az_rgs(acc_id: int):
    need_acc(acc_id, "azure")
    return await run(services.provider(acc_id).resource_groups)


@app.post("/api/accounts/{acc_id}/azure/rgs")
async def az_rg_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "azure")
    p = services.provider(acc_id)
    if body.get("op") == "delete":
        if body.get("confirm") != body.get("name"):
            raise HTTPException(400, "请输入资源组名称确认删除")
        return await run(p.delete_rg, body["name"])
    return await run(p.create_rg, body["name"], body["location"])


@app.get("/api/accounts/{acc_id}/azure/locations")
async def az_locations(acc_id: int):
    need_acc(acc_id, "azure")
    return await run(services.provider(acc_id).locations)


@app.get("/api/accounts/{acc_id}/azure/quotas")
async def az_quotas(acc_id: int, location: str):
    need_acc(acc_id, "azure")
    return await run(services.provider(acc_id).quotas, location)


@app.post("/api/accounts/{acc_id}/azure/create")
async def az_create(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "azure")
    await guarded(acc_id, "create", body)
    if not body.get("location"):
        raise HTTPException(400, "请选择区域")
    return {"ok": True, "task_id": tasks.create_task("azure_create", acc_id, {"create": body, "instance_id": "-",
                                                                               "name": body.get("name")})}


@app.get("/api/accounts/{acc_id}/azure/sizes")
async def az_sizes(acc_id: int, instance_id: str):
    need_acc(acc_id, "azure")
    return await run(services.provider(acc_id).sizes, instance_id)


# ---------------- AWS: Lightsail / CloudFront / 配额 ----------------
@app.get("/api/accounts/{acc_id}/lightsail/options")
async def ls_opts(acc_id: int, region: str = None):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id, region).ls_options)


@app.post("/api/accounts/{acc_id}/lightsail/create")
async def ls_create(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    await guarded(acc_id, "ls_create", body, body.get("region"))
    c = dict(body, user_data=extras.resolve_script(body))
    return _created(acc_id, await run(services.provider(acc_id, body.get("region")).ls_create, c))


@app.get("/api/accounts/{acc_id}/cloudfront")
async def cf_list(acc_id: int):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id).cf_list)


@app.post("/api/accounts/{acc_id}/cloudfront")
async def cf_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    p, op = services.provider(acc_id), body.get("op")
    if op == "create":
        try:   # v1.5：可选 price_class / compress / cache_mode，不传时与 v1.4 行为一致
            return await run(p.cf_create, body.get("origin") or body.get("origin_domain") or "", body.get("comment", ""),
                             body.get("origin_protocol", "http-only"), body.get("price_class") or "all",
                             body.get("compress", True) not in (False, "false", "0", 0), body.get("cache_mode") or "disabled")
        except ValueError as e:
            raise HTTPException(400, str(e))
    if op in ("enable", "disable"):
        return await run(p.cf_set_enabled, body["id"], op == "enable")
    if op == "delete":
        return await run(p.cf_delete, body["id"])
    raise HTTPException(400, "无效操作")


_quota_cache = {}


@app.get("/api/accounts/{acc_id}/quotas")
async def quotas(acc_id: int, refresh: bool = False):
    need_acc(acc_id, "aws")
    c = _quota_cache.get(acc_id)
    if c and not refresh and time.time() - c["ts"] < 6 * 3600:   # 6 小时缓存，避免限流
        return c["data"]
    data = await run(services.provider(acc_id).quotas)
    data["updated_at"] = services.now_local().strftime("%Y-%m-%d %H:%M")
    _quota_cache[acc_id] = {"ts": time.time(), "data": data}
    return data


@app.get("/api/accounts/{acc_id}/recycle")
async def recycle(acc_id: int, region: str = None):
    need_acc(acc_id, "aws")
    return await run(services.recycle_estimate, acc_id, region)


# ---------------- 账单 ----------------
@app.get("/api/accounts/{acc_id}/billing")
async def billing(acc_id: int, force: bool = False):
    need_acc(acc_id)
    return await run(services.billing, acc_id, force)


@app.get("/api/accounts/{acc_id}/credits")
def credits(acc_id: int):
    need_acc(acc_id, "aws")
    return core.q("SELECT * FROM aws_credits WHERE account_id=? ORDER BY start_date", (acc_id,))


@app.post("/api/accounts/{acc_id}/credits")
def add_credit(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    return {"id": core.ex("INSERT INTO aws_credits(account_id,name,amount,start_date,expire_date) VALUES(?,?,?,?,?)",
                          (acc_id, body.get("name", "Credit"), float(body["amount"]), body["start_date"],
                           body.get("expire_date")))}


@app.delete("/api/credits/{cid}")
def del_credit(cid: int):
    core.ex("DELETE FROM aws_credits WHERE id=?", (cid,))
    return {"ok": True}


# ---------------- v1.4：Credit（三家云通用）与教育优惠 ----------------
@app.get("/api/accounts/{acc_id}/credit-summary")
async def credit_summary(acc_id: int):
    """Credit 列表 + 已用额度估算 + 总额 + 教育优惠 + 到期提醒。只读缓存 / 数据库，不调用 AWS Cost Explorer。"""
    need_acc(acc_id)
    return await run(creditsm.summary, acc_id)


def _credit_fields(body, partial=False):
    out = {}
    if not partial or "name" in body:
        out["name"] = (str(body.get("name") or "").strip() or "Credit")[:60]
    if not partial or "amount" in body:
        amt = _num_or_none(body.get("amount"), "amount")
        if amt is None:
            raise HTTPException(400, "初始额度必填")
        out["amount"] = amt
    for k in ("start_date", "expire_date"):
        if not partial or k in body:
            out[k] = _valid_date(body.get(k), k)
    if not partial or "used_manual" in body:
        out["used_manual"] = _num_or_none(body.get("used_manual"), "used_manual")
    return out


@app.get("/api/accounts/{acc_id}/credits-manual")
def credits_manual(acc_id: int):
    need_acc(acc_id)
    return core.q("SELECT * FROM aws_credits WHERE account_id=? ORDER BY COALESCE(expire_date, '9999-12-31'), id", (acc_id,))


@app.post("/api/accounts/{acc_id}/credits-manual")
def credits_manual_add(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id)
    f = _credit_fields(body)
    return {"id": core.ex("INSERT INTO aws_credits(account_id,name,amount,start_date,expire_date,used_manual) VALUES(?,?,?,?,?,?)",
                          (acc_id, f["name"], f["amount"], f["start_date"], f["expire_date"], f["used_manual"]))}


@app.put("/api/accounts/{acc_id}/credits-manual/{cid}")
def credits_manual_edit(acc_id: int, cid: int, body: dict = Body(...)):
    need_acc(acc_id)
    if not core.q("SELECT 1 FROM aws_credits WHERE id=? AND account_id=?", (cid, acc_id), one=True):
        raise HTTPException(404, "Credit 不存在")
    f = _credit_fields(body, partial=True)
    if f:
        core.ex(f"UPDATE aws_credits SET {', '.join(k + '=?' for k in f)} WHERE id=? AND account_id=?", (*f.values(), cid, acc_id))
    return {"ok": True}


@app.delete("/api/accounts/{acc_id}/credits-manual/{cid}")
def credits_manual_del(acc_id: int, cid: int):
    need_acc(acc_id)
    core.ex("DELETE FROM aws_credits WHERE id=? AND account_id=?", (cid, acc_id))
    return {"ok": True}


@app.put("/api/accounts/{acc_id}/credit-total")
def credit_total(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id)
    core.ex("UPDATE accounts SET credit_total=? WHERE id=?", (_num_or_none(body.get("credit_total"), "credit_total"), acc_id))
    return {"ok": True}


@app.put("/api/accounts/{acc_id}/edu-expires-at")
def edu_expires(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "azure")
    core.ex("UPDATE accounts SET edu_expires_at=? WHERE id=?", (_valid_date(body.get("edu_expires_at"), "edu_expires_at"), acc_id))
    return {"ok": True}


@app.get("/api/expiry-alerts")
def expiry_alerts(days: int = 30):
    return creditsm.expiry_alerts(max(1, min(365, days)))


@app.get("/api/accounts/{acc_id}/azure/subscription")
async def az_subscription(acc_id: int):
    """v1.4 Azure 订阅页（只读）：状态、类型 / offer、spending limit 等 + 教育优惠到期。"""
    acc = need_acc(acc_id, "azure")
    full = core.q("SELECT * FROM accounts WHERE id=?", (acc_id,), one=True)
    full.pop("cred_enc", None)
    out = {"edu": creditsm.edu_info(full), "cloud_created_at": full.get("cloud_created_at"), "age_days": creditsm.age_days(full),
           "name": acc["name"]}
    try:
        out.update(await run(services.provider(acc_id).subscription_info))
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return out


# ---------------- 任务 ----------------
@app.get("/api/tasks")
def list_tasks(limit: int = 50):
    rows = core.q("SELECT t.*, a.name AS account_name, a.provider FROM tasks t LEFT JOIN accounts a ON a.id=t.account_id "
                  "ORDER BY t.id DESC LIMIT ?", (limit,))
    return rows


@app.get("/api/tasks/{tid}")
def task_detail(tid: int, after: int = 0):
    """v1.4：任务状态 + 追加式日志 + 结果。after=上次拿到的最后一条日志 id，只返回新日志（轮询用）。"""
    import json as _json
    t = core.q("SELECT t.*, a.name AS account_name, a.provider FROM tasks t LEFT JOIN accounts a ON a.id=t.account_id WHERE t.id=?",
               (tid,), one=True)
    if not t:
        raise HTTPException(404, "任务不存在")
    try:
        params = _json.loads(t.pop("params") or "{}")
    except ValueError:
        params = {}
    safe = {k: params.get(k) for k in ("instance_id", "name", "region", "kind", "mode", "cidrs", "max_tries", "interval",
                                       "max_attempts", "reason", "auto", "size", "ocpus", "memory_gb", "shape") if params.get(k) not in (None, "")}
    if isinstance(params.get("create"), dict):
        safe["create"] = {k: v for k, v in params["create"].items() if k not in ("ssh_key", "script", "password")}
    try:
        t["result"] = _json.loads(t["result"]) if t.get("result") else None
    except ValueError:
        pass
    logs = tasks.get_logs(tid, after)
    t.update(params=safe, type_name=tasks.TYPE_NAME.get(t["type"], t["type"]), logs=logs,
             last_log_id=logs[-1]["id"] if logs else int(after or 0))
    return t


@app.post("/api/tasks/{tid}/stop")
def stop(tid: int):
    tasks.stop_task(tid)
    return {"ok": True}


@app.delete("/api/tasks/{tid}")
def del_task(tid: int):
    core.ex("DELETE FROM tasks WHERE id=? AND status!='running'", (tid,))
    if not core.q("SELECT 1 FROM tasks WHERE id=?", (tid,), one=True):
        core.ex("DELETE FROM task_logs WHERE task_id=?", (tid,))
    return {"ok": True}


# ---------------- 监控 ----------------
@app.get("/api/monitors")
def monitors():
    rows = core.q("SELECT m.*, a.name AS account_name, a.provider FROM monitors m LEFT JOIN accounts a ON a.id=m.account_id")
    return rows


@app.post("/api/monitors")
def add_monitor(body: dict = Body(...)):
    port = int(body.get("check_port") or 0)
    if port and not 0 < port < 65536:
        raise HTTPException(400, "端口无效")
    core.ex("INSERT INTO monitors(account_id,instance_id,region,kind,name,auto_start,last_state,check_port,auto_change_ip,public_ip) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,instance_id) DO UPDATE SET auto_start=excluded.auto_start, "
            "name=excluded.name, check_port=excluded.check_port, auto_change_ip=excluded.auto_change_ip, public_ip=excluded.public_ip",
            (body["account_id"], body["instance_id"], body.get("region"), body.get("kind", "vm"),
             body.get("name"), 1 if body.get("auto_start") else 0, body.get("state"), port,
             1 if body.get("auto_change_ip") and port else 0, body.get("public_ip")))
    return {"ok": True}


@app.delete("/api/monitors/{mid}")
def del_monitor(mid: int):
    core.ex("DELETE FROM monitors WHERE id=?", (mid,))
    return {"ok": True}


# ---------------- 设置 ----------------
SETTING_KEYS = ("tg_chat_id", "daily_report", "report_time", "monitor_interval", "timezone", "default_create", "free_guard",
                "auto_ip_daily_limit")


@app.get("/api/settings")
def get_settings():
    s = {k: core.get_setting(k) for k in SETTING_KEYS}
    s["auto_ip_daily_limit"] = tasks.auto_ip_limit()
    tok = core.get_secret_setting("tg_token")
    s["tg_token_set"] = bool(tok)
    s["tg_token_hint"] = (tok.split(":")[0] + ":***") if tok else ""
    s["cf_token_set"] = bool(core.get_secret_setting("cf_token"))
    s["proxycheck_key_set"] = bool(core.get_secret_setting("proxycheck_key"))
    s["totp_enabled"] = extras.totp_enabled()
    s["version"] = VERSION
    return s


@app.post("/api/settings")
def save_settings(body: dict = Body(...)):
    if "auto_ip_daily_limit" in body:
        try:
            body["auto_ip_daily_limit"] = int(body["auto_ip_daily_limit"])
        except (TypeError, ValueError):
            raise HTTPException(400, "自动换 IP 每日上限需为整数")
        if not 0 <= body["auto_ip_daily_limit"] <= 50:
            raise HTTPException(400, "自动换 IP 每日上限 0~50")
    for k in SETTING_KEYS:
        if k in body:
            core.set_setting(k, body[k])
    if body.get("tg_token"):
        core.set_secret_setting("tg_token", body["tg_token"].strip())
    if body.get("tg_token_clear"):
        core.set_secret_setting("tg_token", "")
    if body.get("cf_token"):
        core.set_secret_setting("cf_token", body["cf_token"].strip())
    if body.get("cf_token_clear"):
        core.set_secret_setting("cf_token", "")
    if body.get("proxycheck_key"):   # v1.6：IP 质量检测（proxycheck.io 免费 Key，可选）
        core.set_secret_setting("proxycheck_key", str(body["proxycheck_key"]).strip())
    if body.get("proxycheck_key_clear"):
        core.set_secret_setting("proxycheck_key", "")
    return {"ok": True}


@app.post("/api/settings/tg-test")
async def tg_test():
    ok = await telegram.send("✅ TriCloud 测试消息：Telegram 通知已连通")
    if not ok:
        raise HTTPException(400, "发送失败，请检查 Bot Token 与 Chat ID（需先给 Bot 发过一条消息）")
    return {"ok": True}


# ---------------- 二次验证（TOTP） ----------------
@app.post("/api/2fa/setup")
def tfa_setup():
    sec = extras.totp_new_secret()
    core.set_secret_setting("totp_pending", sec)
    return {"secret": sec, "uri": extras.totp_uri(sec)}


@app.post("/api/2fa/enable")
def tfa_enable(body: dict = Body(...)):
    sec = core.get_secret_setting("totp_pending")
    if not sec or not extras.totp_verify(sec, body.get("code")):
        raise HTTPException(400, "验证码错误")
    core.set_secret_setting("totp_secret", sec)
    core.set_secret_setting("totp_pending", "")
    return {"ok": True}


@app.post("/api/2fa/disable")
async def tfa_disable(body: dict = Body(...)):
    if not await run(core.verify_password, body.get("password", ""), core.get_setting("password_hash", "")):
        raise HTTPException(400, "密码错误")
    if not extras.totp_verify(core.get_secret_setting("totp_secret"), body.get("code")):
        raise HTTPException(400, "验证码错误")
    core.set_secret_setting("totp_secret", "")
    return {"ok": True}


# ---------------- API Token ----------------
@app.get("/api/tokens")
def tokens():
    return core.q("SELECT id,name,prefix,scope,created,last_used FROM api_tokens ORDER BY id DESC")


@app.post("/api/tokens")
def new_token(body: dict = Body(...)):
    scope = body.get("scope") if body.get("scope") in ("read", "full") else "read"
    return {"token": extras.new_api_token((body.get("name") or "token")[:40], scope)}


@app.delete("/api/tokens/{tid}")
def del_token(tid: int):
    core.ex("DELETE FROM api_tokens WHERE id=?", (tid,))
    return {"ok": True}


# ---------------- 审计日志 ----------------
@app.get("/api/audit")
def audit_log(limit: int = 200):
    return core.q("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (min(limit, 1000),))


# ---------------- 备份 / 恢复 ----------------
@app.post("/api/backup")
async def backup(body: dict = Body(...)):
    if not await run(core.verify_password, body.get("password", ""), core.get_setting("password_hash", "")):
        raise HTTPException(400, "面板密码错误")
    try:
        blob = await run(extras.make_backup, body.get("passphrase", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    fn = f"tricloud-backup-{services.now_local():%Y%m%d-%H%M}.tcbk"
    return Response(blob, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@app.post("/api/restore")
async def restore(body: dict = Body(...)):
    if not await run(core.verify_password, body.get("password", ""), core.get_setting("password_hash", "")):
        raise HTTPException(400, "面板密码错误")
    try:
        blob = base64.b64decode(body.get("file_b64", ""))
        await run(extras.restore_backup, blob, body.get("passphrase", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    services._cache.clear()
    core.drop_all_sessions()
    return {"ok": True}


# ---------------- 开机密码 ----------------
@app.get("/api/secrets")
def secrets_list():
    return core.q("SELECT s.id, s.account_id, s.instance_id, s.name, s.username, s.created, a.name AS account_name "
                  "FROM instance_secrets s LEFT JOIN accounts a ON a.id=s.account_id ORDER BY s.id DESC")


@app.post("/api/secrets/{sid}/reveal")
async def secret_reveal(sid: int, body: dict = Body(...)):
    if not await run(core.verify_password, body.get("password", ""), core.get_setting("password_hash", "")):
        raise HTTPException(400, "面板密码错误")
    r = core.q("SELECT * FROM instance_secrets WHERE id=?", (sid,), one=True)
    if not r:
        raise HTTPException(404, "不存在")
    return {"username": r["username"], "password": core.decrypt(r["password_enc"])}


@app.delete("/api/secrets/{sid}")
def secret_del(sid: int):
    core.ex("DELETE FROM instance_secrets WHERE id=?", (sid,))
    return {"ok": True}


# ---------------- 开机脚本模板 ----------------
@app.get("/api/scripts")
def scripts():
    return core.q("SELECT * FROM scripts ORDER BY id")


@app.post("/api/scripts")
def save_script(body: dict = Body(...)):
    name, content = (body.get("name") or "").strip(), body.get("content") or ""
    if not name or not content.strip():
        raise HTTPException(400, "名称和内容必填")
    if len(content) > 16000:
        raise HTTPException(400, "脚本过长（user-data 上限 16KB）")
    if body.get("id"):
        core.ex("UPDATE scripts SET name=?, content=? WHERE id=?", (name, content, int(body["id"])))
        return {"id": int(body["id"])}
    return {"id": core.ex("INSERT INTO scripts(name,content,created) VALUES(?,?,?)", (name, content, int(time.time())))}


@app.delete("/api/scripts/{sid}")
def del_script(sid: int):
    core.ex("DELETE FROM scripts WHERE id=?", (sid,))
    return {"ok": True}


# ---------------- Cloudflare DNS 联动 ----------------
@app.get("/api/cf/zones")
async def cf_zones():
    try:
        return await run(extras.cf_zones)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/dns-bindings")
def dns_bindings():
    return core.q("SELECT d.*, a.name AS account_name FROM dns_bindings d LEFT JOIN accounts a ON a.id=d.account_id ORDER BY d.id")


@app.post("/api/dns-bindings")
async def add_dns_binding(body: dict = Body(...)):
    need_acc(body["account_id"])
    rec = (body.get("record") or "").strip().lower().rstrip(".")
    zone_name = body.get("zone_name") or ""
    if not rec or not rec.endswith(zone_name):
        raise HTTPException(400, f"记录名需属于域名 {zone_name}")
    core.ex("INSERT INTO dns_bindings(account_id,instance_id,name,zone_id,zone_name,record,proxied,v4,v6) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(account_id,instance_id,record) DO UPDATE SET proxied=excluded.proxied, v4=excluded.v4, v6=excluded.v6",
            (body["account_id"], body["instance_id"], body.get("name"), body["zone_id"], zone_name, rec,
             1 if body.get("proxied") else 0, 1 if body.get("v4", True) else 0, 1 if body.get("v6") else 0))
    out = []
    if body.get("sync_now"):
        out = await run(extras.dns_sync, body["account_id"], body["instance_id"], body.get("ipv4"),
                        (body.get("ipv6") or [None])[0] if isinstance(body.get("ipv6"), list) else body.get("ipv6"))
    return {"ok": True, "dns": out}


@app.delete("/api/dns-bindings/{bid}")
def del_dns_binding(bid: int):
    core.ex("DELETE FROM dns_bindings WHERE id=?", (bid,))
    return {"ok": True}


# ---------------- 静态页 ----------------
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


# ================= v1.2：免费额度护栏 / 账号健康度 / 跨云迁移 =================
@app.post("/api/accounts/{acc_id}/guard-check")
async def guard_check(acc_id: int, body: dict = Body(...)):
    """前端预检（不执行任何操作）。"""
    need_acc(acc_id)
    return {"warnings": await run(guard.check, acc_id, body.get("op", "create"), body, body.get("region"))}


@app.get("/api/account-health")
def account_health():
    return healthm.list_cached()


@app.post("/api/account-health/refresh")
async def account_health_refresh(body: dict = Body(default={})):
    ids = [int(body["account_id"])] if body.get("account_id") else [a["id"] for a in core.list_accounts()]
    out = []
    for i in ids:
        need_acc(i)
        try:
            r = await run(healthm.compute, i)
            txt = healthm.alert_text(r)
            if txt:
                await telegram.send(txt)
            out.append(r)
        except Exception as e:
            out.append({"account_id": i, "error": str(e)[:200]})
    return out


@app.post("/api/migrate")
async def migrate(body: dict = Body(...)):
    """跨云迁移：在目标账号用同一开机脚本重建，可切 DNS、复制监控、停掉源实例。不复制磁盘数据。"""
    src, dst = need_acc(int(body["from_account_id"])), need_acc(int(body["to_account_id"]))
    if src["id"] == dst["id"]:
        raise HTTPException(400, "目标账号不能与源账号相同")
    c = dict(body.get("create") or {})
    if dst["provider"] == "azure" and not c.get("location"):
        raise HTTPException(400, "请选择 Azure 区域")
    await guarded(dst["id"], "create", c if dst["provider"] != "oci" else {"create": c, **c}, body.get("region"))
    tid = tasks.create_task("migrate", dst["id"], {
        "from_account_id": src["id"], "instance_id": body["instance_id"], "from_region": body.get("from_region"),
        "name": body.get("name"), "region": body.get("region"), "create": c,
        "switch_dns": bool(body.get("switch_dns")), "stop_source": bool(body.get("stop_source")),
        "copy_monitor": bool(body.get("copy_monitor", True))})
    return {"ok": True, "task_id": tid}


# ================= v1.3：流量守护 / 串口控制台 =================
def _guard_view(g, a=None):
    a = a or {}
    st = traffic_guard.status_of(g)
    return dict(g, account_name=a.get("name"), provider=a.get("provider"), mode=g.get("mode") or "monthly",
                direction=traffic_guard.direction_of(g), enabled=0 if g.get("enabled") == 0 else 1,
                status=st, status_text=traffic_guard.STATUS_TEXT[st],
                scope=traffic_guard.scope_text(g),
                resume_at_text=traffic_guard.fmt_ts(g["resume_at"]) if g.get("resume_at") else None)


@app.get("/api/traffic-guards")
def traffic_guards():
    names = {a["id"]: a for a in core.list_accounts()}
    return [_guard_view(g, names.get(g["account_id"])) for g in core.q("SELECT * FROM traffic_guards ORDER BY id")]


@app.post("/api/traffic-guards")
async def traffic_guard_save(body: dict = Body(...)):
    acc = need_acc(int(body["account_id"]))
    limit = float(body.get("limit_gb") or traffic_guard.DEFAULT_LIMIT[acc["provider"]])
    warn = int(body.get("warn_pct") or 80)
    if limit <= 0 or not 10 <= warn <= 99:
        raise HTTPException(400, "上限需大于 0，预警比例 10~99")
    action = "stop" if body.get("action") == "stop" else "notify"
    # v1.4：滚动窗口 / 方向 / 关机 M 小时 / 启停（都可省略，省略时与 v1.3 行为一致）
    mode = body.get("mode") or "monthly"
    if mode not in ("monthly", "rolling"):
        raise HTTPException(400, "mode 只能是 monthly 或 rolling")
    try:
        window = int(body["window_hours"]) if body.get("window_hours") not in (None, "") else 24
        shut = float(body["shutdown_hours"]) if body.get("shutdown_hours") not in (None, "") else 0.0
    except (TypeError, ValueError):
        raise HTTPException(400, "窗口小时数 / 关机小时数需为数字")
    if not 1 <= window <= 720:
        raise HTTPException(400, "滚动窗口 1~720 小时")
    if not 0 <= shut <= 720:
        raise HTTPException(400, "关机时长 0~720 小时")
    direction = body.get("direction") or ("both" if body.get("count_in") else "out")
    if direction not in traffic_guard.DIRECTIONS:
        raise HTTPException(400, "direction 只能是 out / in / both")
    enabled = 0 if body.get("enabled") in (False, 0, "0", "false") else 1
    core.ex("INSERT INTO traffic_guards(account_id,instance_id,region,kind,name,limit_gb,warn_pct,action,count_in,mode,window_hours,"
            "direction,shutdown_hours,enabled) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(account_id,instance_id) DO UPDATE SET limit_gb=excluded.limit_gb, warn_pct=excluded.warn_pct, "
            "action=excluded.action, count_in=excluded.count_in, name=excluded.name, region=excluded.region, checked_at=0, "
            "notified=CASE WHEN COALESCE(traffic_guards.mode,'monthly')=excluded.mode THEN traffic_guards.notified ELSE 0 END, "
            "mode=excluded.mode, window_hours=excluded.window_hours, direction=excluded.direction, "
            "shutdown_hours=excluded.shutdown_hours, enabled=excluded.enabled",
            (acc["id"], body["instance_id"], body.get("region"), body.get("kind") or "vm", body.get("name"), limit, warn, action,
             1 if direction == "both" else 0, mode, window, direction, shut if action == "stop" else 0, enabled))
    g = core.q("SELECT * FROM traffic_guards WHERE account_id=? AND instance_id=?", (acc["id"], body["instance_id"]), one=True)
    try:   # 立即读一次用量（不触发停机，避免刚设的上限立刻关机）
        await run(traffic_guard.check, g, False)
    except Exception as e:
        return {"ok": True, "id": g["id"], "warning": f"已保存，但读取流量失败：{str(e)[:150]}"}
    return {"ok": True, "id": g["id"], **core.q("SELECT last_gb, last_pct FROM traffic_guards WHERE id=?", (g["id"],), one=True)}


@app.patch("/api/traffic-guards/{gid}")
def traffic_guard_patch(gid: int, body: dict = Body(...)):
    """v1.4：启用 / 停用规则；cancel_resume 取消待执行的自动开机；reset_state 清除「已触发 / 开机失败」状态。"""
    g = core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True)
    if not g:
        raise HTTPException(404, "规则不存在")
    if "enabled" in body:
        core.ex("UPDATE traffic_guards SET enabled=?, checked_at=0 WHERE id=?", (1 if body["enabled"] else 0, gid))
    if body.get("cancel_resume") and g.get("state") == "tripped":
        core.ex("UPDATE traffic_guards SET resume_at=NULL, state_msg=? WHERE id=?", ("已取消自动开机", gid))
    if body.get("reset_state"):
        core.ex("UPDATE traffic_guards SET state='ok', resume_at=NULL, tripped_at=NULL, state_msg=NULL, checked_at=0 WHERE id=?", (gid,))
    a = core.get_account(g["account_id"]) or {}
    return _guard_view(core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True), a)


@app.post("/api/traffic-guards/{gid}/check")
async def traffic_guard_check(gid: int):
    g = core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True)
    if not g:
        raise HTTPException(404, "规则不存在")
    txt = await run(traffic_guard.check, g)
    if txt:
        await telegram.send(txt)
    g = core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True)
    return _guard_view(g, core.get_account(g["account_id"]))


@app.delete("/api/traffic-guards/{gid}")
def traffic_guard_del(gid: int):
    core.ex("DELETE FROM traffic_guards WHERE id=?", (gid,))
    return {"ok": True}


# ================= v1.5 =================
# ---------------- 已删账号（与 AWS「闲置资源」估算区分开） ----------------
def _deleted_stats():
    rows = core.q("SELECT provider, lifecycle_days, est_cost, currency FROM deleted_accounts")
    by = {}
    for r in rows:
        by[r["provider"]] = by.get(r["provider"], 0) + 1
    days = [r["lifecycle_days"] for r in rows if r["lifecycle_days"] is not None]
    usd = [r["est_cost"] for r in rows if r["est_cost"] is not None and (r["currency"] or "USD") == "USD"]
    return {"count": len(rows), "by_provider": by,
            "avg_lifecycle_days": round(sum(days) / len(days), 1) if days else None,
            "max_lifecycle_days": max(days) if days else None,
            "total_est_cost_usd": round(sum(usd), 2) if usd else 0.0,
            "max_est_cost_usd": round(max(usd), 2) if usd else 0.0}


@app.get("/api/recycle-bin")
def recycle_bin():
    """已删账号：删除时留档的名称、云、存活天数、预估费用。"""
    return {"items": core.q("SELECT * FROM deleted_accounts ORDER BY deleted_at DESC, id DESC"), "stats": _deleted_stats()}


@app.get("/api/recycle-bin/stats")
def recycle_bin_stats():
    return _deleted_stats()


@app.delete("/api/recycle-bin/{rid}")
def recycle_bin_del(rid: int):
    core.ex("DELETE FROM deleted_accounts WHERE id=?", (rid,))
    return {"ok": True}


@app.delete("/api/recycle-bin")
def recycle_bin_clear(confirm: bool = False):
    if not confirm:
        raise HTTPException(400, "需确认")
    core.ex("DELETE FROM deleted_accounts")
    return {"ok": True}


# ---------------- 默认创建参数（与「设置 → 默认创建参数」JSON 是同一份数据） ----------------
CREATE_DEFAULT_KINDS = ("oci", "aws", "lightsail", "azure")
CREATE_DEFAULT_DROP = ("password", "confirm", "confirm_overage", "region")


@app.get("/api/create-defaults/{provider}")
def create_defaults_get(provider: str):
    if provider not in CREATE_DEFAULT_KINDS:
        raise HTTPException(400, f"provider 只能是 {'/'.join(CREATE_DEFAULT_KINDS)}")
    d = core.get_setting("default_create") or {}
    return (d.get(provider) if isinstance(d, dict) else None) or {}


@app.put("/api/create-defaults")
def create_defaults_put(body: dict = Body(...)):
    import json as _json
    prov, vals = body.get("provider"), body.get("defaults")
    if prov not in CREATE_DEFAULT_KINDS:
        raise HTTPException(400, f"provider 只能是 {'/'.join(CREATE_DEFAULT_KINDS)}")
    if not isinstance(vals, dict):
        raise HTTPException(400, "defaults 需为对象")
    vals = {str(k): v for k, v in vals.items() if k not in CREATE_DEFAULT_DROP and not isinstance(v, (dict, list))}
    if len(_json.dumps(vals)) > 16000:
        raise HTTPException(400, "默认参数过大")
    d = core.get_setting("default_create") or {}
    d = dict(d) if isinstance(d, dict) else {}
    d[prov] = vals
    core.set_setting("default_create", d)
    return {"ok": True, "defaults": vals}


# ---------------- OCI 安全组：按规则内容增删、批量端口、对公网放行二次确认 ----------------
PUBLIC_CIDRS = ("0.0.0.0/0", "::/0")


def _sec_rule_args(r):
    direction = (r.get("direction") or "ingress").strip().lower()
    protocol = (r.get("protocol") or "").strip().lower()
    cidr = (r.get("cidr") or r.get("source") or r.get("destination") or "").strip()
    if direction not in ("ingress", "egress"):
        raise HTTPException(400, "direction 只能是 ingress / egress")
    if protocol not in ("tcp", "udp", "icmp", "icmpv6", "all"):
        raise HTTPException(400, "protocol 只能是 tcp / udp / icmp / icmpv6 / all")
    if not cidr:
        raise HTTPException(400, "请填写来源 / 目标 CIDR")
    return direction, protocol, cidr


@app.get("/api/accounts/{acc_id}/security-rules")
async def sec_rules(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await run(services.provider(acc_id, region).security_rules_flat, instance_id)


@app.post("/api/accounts/{acc_id}/security-rules")
async def sec_rule_add(acc_id: int, body: dict = Body(...)):
    """新增规则。ports 支持 "80, 443, 8000-8100"（批量，每段一条规则，已存在的跳过）。
    来源为 0.0.0.0/0 或 ::/0 时需 confirm_public=true（前端显示警告并二次确认）；
    对公网放行全部端口（协议 all，或 TCP/UDP 不限端口 / 1-65535）不支持。"""
    from .providers.oci_provider import OCIProvider
    need_acc(acc_id, "oci")
    r = body.get("rule") if isinstance(body.get("rule"), dict) else body
    direction, protocol, cidr = _sec_rule_args(r)
    ports = r.get("ports")
    if ports in (None, "") and (r.get("port_min") or r.get("port_max")):
        ports = f"{r.get('port_min') or r.get('port_max')}-{r.get('port_max') or r.get('port_min')}"
    try:
        ranges = OCIProvider.parse_ports(ports) if protocol in ("tcp", "udp") and ports not in (None, "") else []
    except ValueError as e:
        raise HTTPException(400, str(e))
    public = cidr.replace(" ", "") in PUBLIC_CIDRS
    if public and direction == "ingress":
        if protocol == "all" or (protocol in ("tcp", "udp") and (not ranges or any(a <= 1 and b >= 65535 for a, b in ranges))):
            raise HTTPException(400, "不支持对 0.0.0.0/0（或 ::/0）放行全部端口，请填写具体端口")
        if not body.get("confirm_public"):
            raise HTTPException(409, {"msg": "来源为 0.0.0.0/0：将对整个互联网开放", "public_warning": True})
    try:
        res = await run(services.provider(acc_id, body.get("region")).add_security_rules, body["instance_id"], body.get("sl_id"),
                        direction, protocol, cidr, ranges, (r.get("description") or r.get("desc") or "").strip() or None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **res}


@app.delete("/api/accounts/{acc_id}/security-rules")
async def sec_rule_del(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    r = body.get("rule") if isinstance(body.get("rule"), dict) else body
    direction, protocol, cidr = _sec_rule_args(r)
    try:
        return await run(services.provider(acc_id, body.get("region")).delete_security_rule_match, body["instance_id"],
                         body.get("sl_id"), direction, protocol, cidr, r.get("port_min"), r.get("port_max"))
    except (LookupError, ValueError) as e:
        raise HTTPException(404 if isinstance(e, LookupError) else 400, str(e))


# ---------------- OCI：删除 IPv6（二次确认） ----------------
@app.post("/api/accounts/{acc_id}/oci/ipv6/delete")
async def oci_ipv6_delete(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    if not body.get("confirm"):
        raise HTTPException(400, "删除 IPv6 需确认")
    try:
        r = await run(services.provider(acc_id, body.get("region")).delete_ipv6, body["instance_id"])
    except LookupError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, **r}


# ---------------- AWS CloudFront：缓存刷新 / 编辑配置 / 启停 / 套餐 / 删除 ----------------
@app.post("/api/accounts/{acc_id}/cloudfront/invalidate")
async def cf_invalidate(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    did = body.get("distribution_id") or body.get("id")
    if not did:
        raise HTTPException(400, "缺少 distribution_id")
    paths = body.get("paths") or []
    if isinstance(paths, str):
        paths = [x for x in paths.replace(",", "\n").split("\n")]
    try:
        return await run(services.provider(acc_id).cf_invalidate, did, paths)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/accounts/{acc_id}/cloudfront/toggle")
async def cf_toggle(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    r = await run(services.provider(acc_id).cf_set_enabled, body["distribution_id"], bool(body.get("enabled")))
    return dict(r, message=f"分发已{'启用' if body.get('enabled') else '停用'}，部署约需几分钟")


@app.get("/api/accounts/{acc_id}/cloudfront/{dist_id}/config")
async def cf_config(acc_id: int, dist_id: str):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id).cf_get_config, dist_id)


@app.put("/api/accounts/{acc_id}/cloudfront/{dist_id}")
async def cf_update(acc_id: int, dist_id: str, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    try:
        return await run(services.provider(acc_id).cf_update, dist_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/accounts/{acc_id}/cloudfront/plan")
async def cf_plan(acc_id: int, body: dict = Body(...)):
    """切换 CloudFront 包月套餐（计费操作）：付费套餐需 confirm=true。"""
    need_acc(acc_id, "aws")
    tier = (body.get("plan_tier") or body.get("tier") or "").strip().upper()
    from .providers.aws_provider import CF_PLANS
    if tier not in CF_PLANS:
        raise HTTPException(400, f"套餐只能是 {' / '.join(CF_PLANS)}")
    if CF_PLANS[tier]["paid"] and not body.get("confirm"):
        raise HTTPException(400, f"{tier} 套餐按月计费（{CF_PLANS[tier]['price']}），需确认")
    try:
        return await run(services.provider(acc_id).cf_set_plan, body["distribution_id"], tier)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/accounts/{acc_id}/cloudfront/{dist_id}")
async def cf_delete_v15(acc_id: int, dist_id: str, confirm: bool = False):
    """删除分发（需 confirm=true）。已停用且 Deployed：直接删除；
    仍启用或部署中：创建后台任务，先停用并等待部署完成（Deployed）再删除，否则 AWS 会拒绝。"""
    need_acc(acc_id, "aws")
    if not confirm:
        raise HTTPException(400, "删除分发需确认")
    st = await run(services.provider(acc_id).cf_state, dist_id)
    if not st["enabled"] and st["status"] == "Deployed":
        await run(services.provider(acc_id).cf_delete, dist_id)
        return {"ok": True, "deleted": True}
    tid = tasks.create_task("cf_delete", acc_id, {"instance_id": dist_id, "name": dist_id, "distribution_id": dist_id})
    return {"ok": True, "deleted": False, "task_id": tid,
            "message": "分发仍在启用或部署中：已创建后台任务，先停用并等待部署完成后自动删除（通常 5~20 分钟）"}



from . import routes_v16  # noqa: E402  v1.6 接口（重装 / 块存储 / 区域订阅 / 附加 IP / 对象存储 等）
V16_ROUTES = routes_v16.__name__


_PAGE_CACHE = {}


def _versioned_page(name):
    """给 /static/*.js|css 加内容哈希 ?v=，避免浏览器 / Cloudflare 缓存旧前端；页面本身不缓存。"""
    path = os.path.join(WEB_DIR, name)
    mt = os.path.getmtime(path)
    hit = _PAGE_CACHE.get(name)
    if not hit or hit[0] != mt:
        import hashlib
        html = open(path, encoding="utf-8").read()

        def _v(m):
            f = os.path.join(WEB_DIR, m.group(2))
            try:
                h = hashlib.sha1(open(f, "rb").read()).hexdigest()[:10]
            except OSError:
                return m.group(0)
            return f'{m.group(1)}/static/{m.group(2)}?v={h}"'
        html = re.sub(r'((?:src|href)=")/static/([\w.-]+\.(?:js|css))"', _v, html)
        hit = _PAGE_CACHE[name] = (mt, html)
    return Response(hit[1], media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return _versioned_page("index.html")


@app.get("/login")
def login_page():
    return _versioned_page("login.html")
