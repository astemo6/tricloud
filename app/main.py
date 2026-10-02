"""TriCloud 三合一云服务器管理面板：FastAPI 后端。"""
import logging
import os

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, db, jobs, monitor, tasks, tg
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
    try:
        monitor.start()
    except Exception as e:
        log.warning("monitor start failed: %s", e)
    yield


app = FastAPI(title="TriCloud", docs_url=None, redoc_url=None, lifespan=lifespan)

SESSION_COOKIE = "tricloud_session"


@app.middleware("http")
async def no_cache_api(request: Request, call_next):
    """API 接口和前端静态文件不允许浏览器缓存，避免发版后拿到旧页面/旧 JS。"""
    resp = await call_next(request)
    path = request.url.path
    if (path.startswith("/api/") or path.startswith("/static/")
            or path in ("/", "/login.html", "/index.html")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


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
            "supports_billing": p.supports_billing,
            "supports_quotas": p.supports_quotas,
            "supports_subscription": p.supports_subscription,
            "supports_lightsail": getattr(p, "supports_lightsail", False),
            "supports_cloudfront": getattr(p, "supports_cloudfront", False),
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


# ---------- 账单 ----------
@app.get("/api/accounts/{account_id}/billing")
def get_billing(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    if not provider.supports_billing:
        raise HTTPException(status_code=400, detail="该云厂商不支持查看账单")
    try:
        data = provider.get_billing(acc["creds"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取账单失败: {e}") from e
    if acc["provider"] == "aws":
        data["credit_total"] = acc.get("credit_total")
    return data


class CreditTotalBody(BaseModel):
    total: float | None = None  # 传 null 清除


@app.put("/api/accounts/{account_id}/credit-total")
def set_credit_total(request: Request, account_id: int, body: CreditTotalBody):
    _require_login(request)
    acc = _get_account(account_id)
    if acc["provider"] != "aws":
        raise HTTPException(status_code=400, detail="只有 AWS 账号支持设置 Credit 总额")
    total = body.total
    if total is not None and total < 0:
        raise HTTPException(status_code=400, detail="Credit 总额不能为负数")
    db.account_set_credit_total(account_id, total)
    return {"ok": True}


# ---------- 配额 / 订阅 ----------
@app.get("/api/accounts/{account_id}/quotas")
def get_quotas(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    if not provider.supports_quotas:
        raise HTTPException(status_code=400, detail="该云厂商不支持配额查询")
    try:
        return provider.get_quotas(acc["creds"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取配额失败: {e}") from e


@app.get("/api/accounts/{account_id}/subscription")
def get_subscription(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    if not provider.supports_subscription:
        raise HTTPException(status_code=400, detail="该云厂商不支持订阅信息查询")
    try:
        return provider.get_subscription(acc["creds"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取订阅信息失败: {e}") from e


# ---------- 一键测活 ----------
@app.post("/api/accounts/test-all")
def test_all_accounts(request: Request, provider: str = ""):
    _require_login(request)
    result = []
    for acc in db.account_list(provider or None):
        p = get_provider(acc["provider"])
        try:
            full = db.account_get(acc["id"])
            p.test(full["creds"])
            result.append({"id": acc["id"], "provider": acc["provider"],
                           "name": acc["name"], "ok": True, "message": "连接正常"})
        except Exception as e:  # noqa: BLE001
            result.append({"id": acc["id"], "provider": acc["provider"],
                           "name": acc["name"], "ok": False, "message": str(e)[:200]})
    return result


# ---------- 监控设置 ----------
class MonitorBody(BaseModel):
    monitor_alert: bool = False
    monitor_restart: bool = False


@app.get("/api/accounts/{account_id}/monitor")
def get_monitor(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    return {"monitor_alert": bool(acc.get("monitor_alert")),
            "monitor_restart": bool(acc.get("monitor_restart"))}


@app.put("/api/accounts/{account_id}/monitor")
def set_monitor(request: Request, account_id: int, body: MonitorBody):
    _require_login(request)
    _get_account(account_id)
    db.account_set_monitor(account_id, body.monitor_alert, body.monitor_restart)
    return {"ok": True}


# ---------- AWS Lightsail ----------
def _require_aws(acc: dict):
    provider = get_provider(acc["provider"])
    if acc["provider"] != "aws":
        raise HTTPException(status_code=400, detail="仅 AWS 账号支持此功能")
    return provider


@app.get("/api/accounts/{account_id}/lightsail")
def list_lightsail(request: Request, account_id: int, region: str = ""):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    try:
        return provider.list_lightsail(acc["creds"], region)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取 Lightsail 实例失败: {e}") from e


class LightsailActionBody(BaseModel):
    name: str
    action: str   # start|stop|reboot
    region: str


@app.post("/api/accounts/{account_id}/lightsail/action")
def lightsail_action(request: Request, account_id: int, body: LightsailActionBody):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    if body.action not in ("start", "stop", "reboot"):
        raise HTTPException(status_code=400, detail="不支持的操作")
    try:
        msg = provider.lightsail_action(acc["creds"], body.name, body.action, body.region)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"操作失败: {e}") from e
    return {"ok": True, "message": msg}


@app.get("/api/accounts/{account_id}/lightsail/options")
def lightsail_options(request: Request, account_id: int, region: str = ""):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    try:
        return provider.get_lightsail_options(
            acc["creds"], region or acc["creds"]["region"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取创建选项失败: {e}") from e


class LightsailCreateBody(BaseModel):
    name: str = ""
    region: str = ""
    zone: str = ""
    blueprint: str = ""
    bundle: str = ""
    key_pair: str = ""


@app.post("/api/accounts/{account_id}/lightsail/create")
def lightsail_create(request: Request, account_id: int, body: LightsailCreateBody):
    _require_login(request)
    acc = _get_account(account_id)
    _require_aws(acc)
    params = body.dict()
    job_id = jobs.submit("lightsail_create", "aws", account_id,
                         f"创建 Lightsail / {params.get('name') or 'lightsail'}",
                         tasks.job_lightsail_create, "aws", account_id, params)
    return {"ok": True, "job_id": job_id}


@app.post("/api/accounts/{account_id}/lightsail/change-ip")
def lightsail_change_ip(request: Request, account_id: int, body: LightsailActionBody):
    _require_login(request)
    acc = _get_account(account_id)
    _require_aws(acc)
    if not body.name or not body.region:
        raise HTTPException(status_code=400, detail="缺少实例名或区域")
    job_id = jobs.submit("lightsail_change_ip", "aws", account_id,
                         f"更换 Lightsail IP / {body.name}",
                         tasks.job_lightsail_change_ip, "aws", account_id,
                         {"name": body.name, "region": body.region})
    return {"ok": True, "job_id": job_id}


# ---------- AWS CloudFront ----------
@app.get("/api/accounts/{account_id}/cloudfront")
def list_cloudfront(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    try:
        return provider.list_cloudfront(acc["creds"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取 CloudFront 分发失败: {e}") from e


class InvalidateBody(BaseModel):
    distribution_id: str
    paths: list[str] = []


@app.post("/api/accounts/{account_id}/cloudfront/invalidate")
def cloudfront_invalidate(request: Request, account_id: int, body: InvalidateBody):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    try:
        msg = provider.cloudfront_invalidate(acc["creds"], body.distribution_id, body.paths)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"刷新失败: {e}") from e
    return {"ok": True, "message": msg}


class CloudFrontToggleBody(BaseModel):
    distribution_id: str
    enabled: bool


@app.post("/api/accounts/{account_id}/cloudfront/toggle")
def cloudfront_toggle(request: Request, account_id: int, body: CloudFrontToggleBody):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    try:
        msg = provider.cloudfront_toggle(acc["creds"], body.distribution_id, body.enabled)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"操作失败: {e}") from e
    return {"ok": True, "message": msg}


class CloudFrontCreateBody(BaseModel):
    origin_domain: str
    comment: str = ""
    price_class: str = "100"


@app.post("/api/accounts/{account_id}/cloudfront/create")
def cloudfront_create(request: Request, account_id: int, body: CloudFrontCreateBody):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    try:
        msg = provider.create_distribution(
            acc["creds"], body.origin_domain, body.comment, body.price_class)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"创建失败: {e}") from e
    return {"ok": True, "message": msg}


# ---------- 设置（Telegram 联动） ----------
class SettingsBody(BaseModel):
    tg_bot_token: str = ""
    tg_chat_id: str = ""
    daily_report: bool | None = None
    daily_report_hour: int | None = None
    monitor_interval_min: int | None = None


@app.get("/api/settings")
def get_settings(request: Request):
    _require_login(request)
    token, chat_id = tg.get_tg_config()
    return {
        "tg_bot_token_set": bool(token),
        "tg_chat_id": chat_id,
        "tg_bot_running": bool(tg._state["thread"] and tg._state["thread"].is_alive()),
        "daily_report": db.meta_get("daily_report") == "1",
        "daily_report_hour": int(db.meta_get("daily_report_hour") or 9),
        "monitor_interval_min": int(db.meta_get("monitor_interval_min") or 5),
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
    if body.daily_report is not None:
        db.meta_set("daily_report", "1" if body.daily_report else "0")
    if body.daily_report_hour is not None:
        db.meta_set("daily_report_hour", str(max(0, min(23, body.daily_report_hour))))
    if body.monitor_interval_min is not None:
        db.meta_set("monitor_interval_min", str(max(1, min(120, body.monitor_interval_min))))
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
