"""认证：登录 / 退出 / 改密码、健康检查、/api/meta。"""
import asyncio

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import core, security, services
from ..i18n import msg
from .common import _token, client_ip, run, VERSION

router = APIRouter()


# ---------------- 认证 ----------------
@router.get("/api/meta")
def meta():
    """App / Web 用：当前可添加的云厂商。"""
    return {"providers": list(services.PROVIDERS)}


@router.get("/api/health")
def health_check():
    return {"ok": True, "version": VERSION}


@router.post("/api/login")
async def login(req: Request, body: dict = Body(...)):
    ip = client_ip(req)
    wait = core.login_locked(ip)
    if wait:
        raise HTTPException(429, msg("err.login_locked", n=wait // 60 + 1))
    ok = await run(core.verify_password, body.get("password", ""), core.get_setting("password_hash", ""))
    if ok and security.totp_enabled():
        if not body.get("otp"):
            raise HTTPException(401, msg("err.need_otp"))   # 前端据此显示验证码输入框
        ok = security.totp_verify(core.get_secret_setting("totp_secret"), body.get("otp"))
    if not ok:
        core.login_failed(ip)
        await asyncio.sleep(1)
        raise HTTPException(401, msg("err.bad_credentials"))
    core.login_ok(ip)
    token = core.new_session()
    # Android App 使用 Bearer token；浏览器只拿 HttpOnly Cookie，不把 token 暴露给 JS
    resp = JSONResponse({"ok": True, "token": token} if body.get("client") == "app" else {"ok": True})
    resp.set_cookie("tc_session", token, max_age=core.SESSION_TTL, httponly=True, samesite="lax",
                    secure=core.COOKIE_SECURE, path="/")
    return resp


@router.post("/api/logout")
def logout(req: Request):
    core.drop_session(_token(req))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("tc_session", path="/")
    return resp


@router.post("/api/password")
async def change_password(body: dict = Body(...)):
    if not await run(core.verify_password, body.get("old", ""), core.get_setting("password_hash", "")):
        raise HTTPException(400, msg("err.old_pw_wrong"))
    new = body.get("new", "")
    if len(new) < 10:
        raise HTTPException(400, msg("err.new_pw_short"))
    core.set_setting("password_hash", await run(core.hash_password, new))
    core.drop_all_sessions()
    return {"ok": True}
