"""安全设置：二次验证、API Token、审计日志、加密备份 / 恢复、开机密码。"""
import base64

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .. import core, security, services
from ..i18n import msg
from .common import _token, client_ip, run

router = APIRouter()


# ---------------- 二次验证（TOTP） ----------------
@router.post("/api/2fa/setup")
def tfa_setup():
    sec = security.totp_new_secret()
    core.set_secret_setting("totp_pending", sec)
    uri = security.totp_uri(sec)
    out = {"secret": sec, "uri": uri}
    try:   # 二维码只是便利：生成失败不挡开通，前端没 qr_svg 时回退纯手动输入
        import base64 as _b64
        import io

        import segno
        qr = segno.make(uri, error="m")
        buf = io.BytesIO()
        qr.save(buf, kind="svg", scale=5, border=2, xmldecl=False)
        out["qr_svg"] = buf.getvalue().decode()
        png = io.BytesIO()   # build 38：App 端原生显示用（SVG 在 App 里渲染麻烦，PNG 解码即用）
        qr.save(png, kind="png", scale=6, border=2)
        out["qr_png"] = _b64.b64encode(png.getvalue()).decode()
    except Exception:
        pass
    return out


@router.post("/api/2fa/enable")
def tfa_enable(body: dict = Body(...)):
    sec = core.get_secret_setting("totp_pending")
    if not sec or not security.totp_verify(sec, body.get("code")):
        raise HTTPException(400, msg("err.code_wrong"))
    core.set_secret_setting("totp_secret", sec)
    core.set_secret_setting("totp_pending", "")
    return {"ok": True}


@router.post("/api/2fa/disable")
async def tfa_disable(body: dict = Body(...)):
    if not await run(core.verify_password, body.get("password", ""), core.get_setting("password_hash", "")):
        raise HTTPException(400, msg("err.password_wrong"))
    if not security.totp_verify(core.get_secret_setting("totp_secret"), body.get("code")):
        raise HTTPException(400, msg("err.code_wrong"))
    core.set_secret_setting("totp_secret", "")
    return {"ok": True}


# ---------------- API Token ----------------
@router.get("/api/tokens")
def tokens():
    return core.q("SELECT id,name,prefix,scope,created,last_used FROM api_tokens ORDER BY id DESC")


@router.post("/api/tokens")
def new_token(body: dict = Body(...)):
    scope = body.get("scope") if body.get("scope") in ("read", "full") else "read"
    return {"token": security.new_api_token((body.get("name") or "token")[:40], scope)}


@router.delete("/api/tokens/{tid}")
def del_token(tid: int):
    core.ex("DELETE FROM api_tokens WHERE id=?", (tid,))
    return {"ok": True}


# ---------------- 审计日志 ----------------
@router.get("/api/audit")
def audit_log(limit: int = 200):
    return core.q("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (min(limit, 1000),))


@router.get("/api/audit/logins")
def audit_logins(limit: int = 50):
    """登录记录专用：审计里只筛 POST /api/login（detail 含 HTTP 状态，200 成功 / 401 失败）。"""
    return core.q("SELECT ts, ip, detail FROM audit WHERE action='POST /api/login' ORDER BY id DESC LIMIT ?",
                  (min(limit, 200),))


# ---------------- 已登录设备 ----------------
def device_label(ua, kind):
    """UA → 人话设备名（系统 · 浏览器，都是专有名词不分语言）；认不出返回空串，前端显示「未知设备」。"""
    if kind == "app":
        return "TriCloud App"
    ua = ua or ""
    if not ua:
        return ""
    if "iPhone" in ua:
        os_name = "iPhone"
    elif "iPad" in ua:
        os_name = "iPad"
    elif "Android" in ua:
        os_name = "Android"
    elif "Windows" in ua:
        os_name = "Windows"
    elif "Macintosh" in ua or "Mac OS" in ua:
        os_name = "macOS"
    elif "Linux" in ua:
        os_name = "Linux"
    else:
        os_name = ""
    if "Edg/" in ua or "EdgA" in ua or "EdgiOS" in ua:
        browser = "Edge"
    elif "CriOS" in ua or "Chrome/" in ua:
        browser = "Chrome"
    elif "FxiOS" in ua or "Firefox/" in ua:
        browser = "Firefox"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = ""
    return " · ".join(x for x in (os_name, browser) if x) or ua[:40]


@router.get("/api/sessions")
def sessions_list(req: Request):
    cur = core.session_key(_token(req))
    return [{"id": r["token_hash"], "device": device_label(r["ua"], r["kind"]), "ua": r["ua"] or "",
             "ip": r["ip"] or "", "created": r["created"] or 0, "last_seen": r["last_seen"] or 0,
             "kind": r["kind"] or "web", "current": r["token_hash"] == cur}
            for r in core.list_sessions()]


@router.delete("/api/sessions/{sid}")
def sessions_kick(sid: str, req: Request):
    is_self = sid == core.session_key(_token(req))
    core.drop_session_by_key(sid)
    resp = JSONResponse({"ok": True, "self": is_self})
    if is_self:
        resp.delete_cookie("tc_session", path="/")
    return resp


@router.post("/api/sessions/kick-others")
def sessions_kick_others(req: Request):
    return {"ok": True, "kicked": core.drop_other_sessions(_token(req))}


@router.delete("/api/audit")
def audit_clear(req: Request, confirm: bool = False):
    """一键清空审计日志（不可恢复）。清空后立刻写一条 audit-clear，保留谁、何时、哪个 IP 清的痕迹。API Token 不能调用。"""
    if not confirm:
        raise HTTPException(400, msg("err.clear_audit_confirm"))
    with core.db() as c:
        n = c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        c.execute("DELETE FROM audit")
    security.audit(client_ip(req), getattr(req.state, "actor", "session"), "audit-clear", f"清空了 {n} 条")
    return {"ok": True, "deleted": n}


# ---------------- 备份 / 恢复 ----------------
@router.post("/api/backup")
async def backup(body: dict = Body(...)):
    if not await run(core.verify_password, body.get("password", ""), core.get_setting("password_hash", "")):
        raise HTTPException(400, msg("err.panel_pw_wrong"))
    try:
        blob = await run(security.make_backup, body.get("passphrase", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    fn = f"tricloud-backup-{services.now_local():%Y%m%d-%H%M}.tcbk"
    return Response(blob, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@router.post("/api/restore")
async def restore(body: dict = Body(...)):
    if not await run(core.verify_password, body.get("password", ""), core.get_setting("password_hash", "")):
        raise HTTPException(400, msg("err.panel_pw_wrong"))
    try:
        blob = base64.b64decode(body.get("file_b64", ""))
        await run(security.restore_backup, blob, body.get("passphrase", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    services._cache.clear()
    core.drop_all_sessions()
    return {"ok": True}


# ---------------- 开机密码 ----------------
@router.get("/api/secrets")
def secrets_list():
    return core.q("SELECT s.id, s.account_id, s.instance_id, s.name, s.username, s.created, a.name AS account_name "
                  "FROM instance_secrets s LEFT JOIN accounts a ON a.id=s.account_id ORDER BY s.id DESC")


@router.post("/api/secrets/{sid}/reveal")
async def secret_reveal(sid: int, body: dict = Body(...)):
    if not await run(core.verify_password, body.get("password", ""), core.get_setting("password_hash", "")):
        raise HTTPException(400, msg("err.panel_pw_wrong"))
    r = core.q("SELECT * FROM instance_secrets WHERE id=?", (sid,), one=True)
    if not r:
        raise HTTPException(404, msg("err.not_found"))
    return {"username": r["username"], "password": core.decrypt(r["password_enc"])}


@router.delete("/api/secrets/{sid}")
def secret_del(sid: int):
    core.ex("DELETE FROM instance_secrets WHERE id=?", (sid,))
    return {"ok": True}
