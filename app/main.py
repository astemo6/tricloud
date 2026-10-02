"""TriCloud 三合一云服务器管理面板：FastAPI 后端。"""
import logging
import os

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, db, jobs, tasks, tg
from .providers import get_provider, list_providers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tricloud")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    auth.ensure_password_initialized()
    log.info("TriCloud started, data dir: %s", config.DATA_DIR)
    try:
        tg.refresh_bot()
    except Exception as e:
        log.warning("tg bot start failed: %s", e)
    yield


app = FastAPI(title="TriCloud", docs_url=None, redoc_url=None, lifespan=lifespan)

SESSION_COOKIE = "tricloud_session"


def _require_login(request: Request) -> None:
    if not db.session_valid(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="未登录")


# ---------- 登录 ----------
class LoginBody(BaseModel):
    password: str


@app.post("/api/login")
def login(body: LoginBody, response: Response):
    if not auth.verify_password(body.password):
        raise HTTPException(status_code=403, detail="密码错误")
    token = db.session_create(config.SESSION_TTL_SECONDS)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=config.SESSION_TTL_SECONDS, path="/")
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    db.session_delete(request.cookies.get(SESSION_COOKIE) or "")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    return {"logged_in": db.session_valid(request.cookies.get(SESSION_COOKIE))}


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/change-password")
def change_password(request: Request, body: ChangePasswordBody):
    _require_login(request)
    if not auth.verify_password(body.old_password):
        raise HTTPException(status_code=403, detail="原密码错误")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    auth.set_password(body.new_password)
    return {"ok": True}


# ---------- 云厂商元信息 ----------
@app.get("/api/providers")
def providers(request: Request):
    _require_login(request)
    return [
        {
            "id": p.id, "name": p.name,
            "supports_snatch": p.supports_snatch,
            "fields": [f.__dict__ for f in p.fields],
            "actions": p.actions,
        }
        for p in list_providers()
    ]


# ---------- 账号管理 ----------
class AccountBody(BaseModel):
    provider: str
    name: str
    creds: dict


class AccountUpdateBody(BaseModel):
    name: str
    creds: dict | None = None


@app.get("/api/accounts")
def list_accounts(request: Request, provider: str = ""):
    _require_login(request)
    return db.account_list(provider or None)


@app.post("/api/accounts")
def create_account(request: Request, body: AccountBody):
    _require_login(request)
    provider = get_provider(body.provider)
    try:
        provider.test(body.creds)
    except Exception as e:  # noqa: BLE001 - 凭证错误要原样返回给前端
        raise HTTPException(status_code=400, detail=f"凭证校验失败: {e}") from e
    account_id = db.account_create(body.provider, body.name.strip(), body.creds)
    return {"ok": True, "id": account_id}


@app.put("/api/accounts/{account_id}")
def update_account(request: Request, account_id: int, body: AccountUpdateBody):
    _require_login(request)
    acc = db.account_get(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    creds = body.creds if body.creds is not None else acc["creds"]
    # 只有提交了新凭证才做连通性测试
    if body.creds is not None:
        provider = get_provider(acc["provider"])
        try:
            provider.test(body.creds)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"凭证校验失败: {e}") from e
    db.account_update(account_id, body.name.strip(), body.creds)
    return {"ok": True}


@app.delete("/api/accounts/{account_id}")
def delete_account(request: Request, account_id: int):
    _require_login(request)
    if not db.account_delete(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"ok": True}


@app.post("/api/accounts/{account_id}/test")
def test_account(request: Request, account_id: int):
    _require_login(request)
    acc = db.account_get(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    provider = get_provider(acc["provider"])
    try:
        provider.test(acc["creds"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"连接失败: {e}") from e
    return {"ok": True, "message": "连接正常"}


# ---------- 实例 ----------
def _get_account(account_id: int) -> dict:
    acc = db.account_get(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    return acc


@app.get("/api/accounts/{account_id}/instances")
def list_instances(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    try:
        instances = provider.list_instances(acc["creds"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取实例列表失败: {e}") from e
    return [i.__dict__ for i in instances]


class ActionBody(BaseModel):
    instance: dict
    action: str
    params: dict = {}


@app.post("/api/accounts/{account_id}/action")
def instance_action(request: Request, account_id: int, body: ActionBody):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    if body.action not in [a["key"] for a in provider.actions]:
        raise HTTPException(status_code=400, detail="不支持的操作")
    title = f"{body.action} / {body.instance.get('name', body.instance.get('id', ''))}"
    job_id = tasks.submit_action(acc["provider"], account_id,
                                 body.instance, body.action, body.params, title)
    return {"ok": True, "job_id": job_id}


@app.get("/api/accounts/{account_id}/create-options")
def create_options(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    try:
        return provider.create_options(acc["creds"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取创建选项失败: {e}") from e


@app.post("/api/accounts/{account_id}/create")
def create_instance(request: Request, account_id: int, params: dict):
    _require_login(request)
    acc = _get_account(account_id)
    job_id = jobs.submit("create", acc["provider"], account_id,
                         f"创建实例 / {params.get('name', '')}",
                         tasks.job_create, acc["provider"], account_id, params)
    return {"ok": True, "job_id": job_id}


@app.post("/api/accounts/{account_id}/snatch")
def snatch_instance(request: Request, account_id: int, params: dict):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    if not provider.supports_snatch:
        raise HTTPException(status_code=400, detail="该云厂商不支持抢机")
    job_id = jobs.submit("snatch", acc["provider"], account_id,
                         f"抢机 / {params.get('shape', '')}",
                         tasks.job_snatch, acc["provider"], account_id, params)
    return {"ok": True, "job_id": job_id}


# ---------- 设置（Telegram 联动） ----------
class SettingsBody(BaseModel):
    tg_bot_token: str = ""
    tg_chat_id: str = ""


@app.get("/api/settings")
def get_settings(request: Request):
    _require_login(request)
    token, chat_id = tg.get_tg_config()
    return {
        "tg_bot_token_set": bool(token),
        "tg_chat_id": chat_id,
        "tg_bot_running": bool(tg._state["thread"] and tg._state["thread"].is_alive()),
    }


@app.put("/api/settings")
def update_settings(request: Request, body: SettingsBody):
    _require_login(request)
    token = body.tg_bot_token.strip()
    chat_id = body.tg_chat_id.strip()
    if token:
        db.meta_set("tg_bot_token", token)
    if chat_id:
        db.meta_set("tg_chat_id", chat_id)
    state = tg.refresh_bot()
    return {"ok": True, **state}


@app.post("/api/settings/tg-test")
def tg_test(request: Request):
    _require_login(request)
    if tg.send_message("✅ TriCloud Telegram 联动测试成功"):
        return {"ok": True}
    raise HTTPException(status_code=400, detail="发送失败，请检查 Bot Token 和 Chat ID")


# ---------- 任务 ----------
@app.get("/api/jobs")
def list_jobs(request: Request, limit: int = 100):
    _require_login(request)
    return db.job_list(limit)


@app.get("/api/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    _require_login(request)
    job = db.job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.post("/api/jobs/{job_id}/stop")
def stop_job(request: Request, job_id: str):
    _require_login(request)
    if not jobs.request_stop(job_id):
        raise HTTPException(status_code=400, detail="任务已结束或不存在")
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(request: Request, job_id: str):
    _require_login(request)
    if not db.job_delete(job_id):
        raise HTTPException(status_code=400, detail="只能删除已结束的任务")
    return {"ok": True}


# ---------- 前端 ----------
@app.get("/login.html")
def login_page():
    return FileResponse(os.path.join(config.FRONTEND_DIR, "login.html"))


@app.get("/")
def index():
    return FileResponse(os.path.join(config.FRONTEND_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")
