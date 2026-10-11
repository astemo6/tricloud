"""TriCloud 三合一云服务器管理面板：FastAPI 后端。"""
import io
import logging
import os
import sqlite3
import time

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, backup as backup_mod, billing, cf, config, db, jobs, monitor, tasks, tg, traffic
from .providers import get_provider, list_providers, oci_provider

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
    try:
        traffic.start()
    except Exception as e:
        log.warning("traffic watcher start failed: %s", e)
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


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@app.post("/api/login")
def login(body: LoginBody, request: Request, response: Response):
    ip = _client_ip(request)
    if not auth.verify_password(body.password):
        db.audit_add(ip, "login_fail", "密码错误")
        raise HTTPException(status_code=403, detail="密码错误")
    if auth.totp_enabled():
        # 两步登录第一步：密码对但启用了 TOTP，先不种 Cookie
        db.audit_add(ip, "login_totp_stage", "密码正确，等待 TOTP 验证码")
        return {"totp_required": True}
    token = db.session_create(config.SESSION_TTL_SECONDS)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=config.SESSION_TTL_SECONDS, path="/")
    db.audit_add(ip, "login_ok", "登录成功")
    return {"ok": True}


class TotpVerifyBody(BaseModel):
    password: str
    code: str


@app.post("/api/totp/verify")
def totp_verify(body: TotpVerifyBody, request: Request, response: Response):
    """两步登录第二步：密码 + TOTP 码都对才种 Cookie。"""
    ip = _client_ip(request)
    if not auth.verify_password(body.password):
        db.audit_add(ip, "totp_verify_fail", "密码错误")
        raise HTTPException(status_code=403, detail="密码错误")
    if not auth.totp_verify(body.code):
        db.audit_add(ip, "totp_verify_fail", "TOTP 验证码错误")
        raise HTTPException(status_code=403, detail="验证码错误")
    token = db.session_create(config.SESSION_TTL_SECONDS)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=config.SESSION_TTL_SECONDS, path="/")
    db.audit_add(ip, "login_ok", "登录成功（TOTP 已验证）")
    return {"ok": True}


# ---------- TOTP 管理 ----------
@app.get("/api/totp/status")
def totp_status(request: Request):
    _require_login(request)
    return {"enabled": auth.totp_enabled()}


@app.post("/api/totp/setup")
def totp_setup(request: Request):
    _require_login(request)
    if auth.totp_enabled():
        raise HTTPException(status_code=400, detail="TOTP 已启用，请先解绑")
    db.audit_add(_client_ip(request), "totp_setup", "生成 TOTP 密钥（待确认）")
    return auth.totp_setup()


class TotpConfirmBody(BaseModel):
    code: str


@app.post("/api/totp/confirm")
def totp_confirm(request: Request, body: TotpConfirmBody):
    _require_login(request)
    ip = _client_ip(request)
    if not auth.totp_confirm_enable(body.code):
        db.audit_add(ip, "totp_confirm_fail", "确认启用失败：验证码错误")
        raise HTTPException(status_code=400, detail="验证码错误")
    db.audit_add(ip, "totp_enable", "TOTP 二次验证已启用")
    return {"ok": True}


class TotpDisableBody(BaseModel):
    password: str
    code: str


@app.post("/api/totp/disable")
def totp_disable(request: Request, body: TotpDisableBody):
    _require_login(request)
    ip = _client_ip(request)
    if not auth.verify_password(body.password):
        db.audit_add(ip, "totp_disable_fail", "解绑失败：密码错误")
        raise HTTPException(status_code=403, detail="密码错误")
    if not auth.totp_verify(body.code):
        db.audit_add(ip, "totp_disable_fail", "解绑失败：验证码错误")
        raise HTTPException(status_code=403, detail="验证码错误")
    auth.totp_disable()
    db.audit_add(ip, "totp_disable", "TOTP 二次验证已解绑")
    return {"ok": True}


# ---------- 审计日志 ----------
@app.get("/api/audit-log")
def audit_log(request: Request, limit: int = 200):
    _require_login(request)
    limit = max(1, min(limit, 1000))
    return db.audit_list(limit)


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
        db.audit_add(_client_ip(request), "change_password_fail", "原密码错误")
        raise HTTPException(status_code=403, detail="原密码错误")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    auth.set_password(body.new_password)
    db.audit_add(_client_ip(request), "change_password", "面板密码已修改")
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
    # 账号级代理出口（可选；proxy_pass 后端 Fernet 加密存储）
    proxy_url: str = ""
    proxy_user: str = ""
    proxy_pass: str = ""


class AccountUpdateBody(BaseModel):
    # 部分更新：未提交的字段保持原值
    name: str | None = None
    creds: dict | None = None
    # None = 未提交（保持原代理配置不变）；"" = 清除代理
    proxy_url: str | None = None
    proxy_user: str | None = None
    proxy_pass: str | None = None


# 凭证中的非敏感字段：detail 接口回显明文、更新时提交即改（空值拒绝）；
# 其余凭证字段一律视为敏感（不回显明文、留空不更新）
_NON_SENSITIVE_CREDS = ("region",)


def _proxy_of(body) -> dict | None:
    """从请求体提取代理配置；未配置 URL 时返回 None（直连）。"""
    url = (getattr(body, "proxy_url", None) or "").strip()
    if not url:
        return None
    return {
        "proxy_url": url,
        "proxy_user": (getattr(body, "proxy_user", None) or "").strip(),
        "proxy_pass": getattr(body, "proxy_pass", None) or "",
    }


def _proxy_update_of(body: AccountUpdateBody, acc: dict) -> dict | None:
    """编辑账号时的代理配置：都未提交返回 None（不变）；
    否则以现有配置为基础合并提交值（proxy_pass 留空保持原值）。"""
    if (body.proxy_url is None and body.proxy_user is None
            and body.proxy_pass is None):
        return None
    old_creds = acc.get("creds") or {}
    url = (acc.get("proxy_url") or "").strip()
    user = (acc.get("proxy_user") or "").strip()
    pwd = old_creds.get("proxy_pass") or ""
    if body.proxy_url is not None:
        url = (body.proxy_url or "").strip()
    if body.proxy_user is not None:
        user = (body.proxy_user or "").strip()
    if body.proxy_pass:  # 敏感字段：仅非空新值更新
        pwd = body.proxy_pass
    if not url:
        return {"proxy_url": "", "proxy_user": "", "proxy_pass": ""}
    return {"proxy_url": url, "proxy_user": user, "proxy_pass": pwd}


@app.get("/api/accounts")
def list_accounts(request: Request, provider: str = ""):
    _require_login(request)
    return db.account_list(provider or None)


@app.post("/api/accounts")
def create_account(request: Request, body: AccountBody):
    _require_login(request)
    provider = get_provider(body.provider)
    proxy = _proxy_of(body)
    # 连通性校验走代理（若有配置）
    test_creds = {**body.creds, **(proxy or {})}
    try:
        provider.test(test_creds)
    except Exception as e:  # noqa: BLE001 - 凭证错误要原样返回给前端
        raise HTTPException(status_code=400, detail=f"凭证校验失败: {e}") from e
    account_id = db.account_create(
        body.provider, body.name.strip(), body.creds, proxy=proxy)
    db.audit_add(_client_ip(request), "account_create",
                 f"{body.provider} / {body.name.strip()}")
    return {"ok": True, "id": account_id}


class BatchAccountBody(BaseModel):
    provider: str
    accounts: list[dict]  # [{name, creds}]

@app.post("/api/accounts/batch")
def create_accounts_batch(request: Request, body: BatchAccountBody):
    _require_login(request)
    provider = get_provider(body.provider)
    results = []
    for item in body.accounts:
        name = (item.get("name") or "").strip()
        creds = item.get("creds") or {}
        if not name:
            results.append({"name": name, "ok": False, "error": "别名不能为空"})
            continue
        try:
            provider.test(creds)
        except Exception as e:  # noqa: BLE001
            results.append({"name": name, "ok": False, "error": f"凭证校验失败: {e}"})
            continue
        try:
            aid = db.account_create(body.provider, name, creds)
            results.append({"name": name, "ok": True, "id": aid})
        except Exception as e:  # noqa: BLE001
            results.append({"name": name, "ok": False, "error": str(e)})
    ok_count = sum(1 for r in results if r["ok"])
    db.audit_add(_client_ip(request), "account_create_batch",
                 f"{body.provider} 成功 {ok_count}/{len(results)}")
    return {"ok": True, "results": results,
            "summary": f"成功 {ok_count}/{len(results)}"}


@app.get("/api/create-defaults/{provider}")
def get_create_defaults(request: Request, provider: str):
    _require_login(request)
    import json as _json
    raw = db.meta_get(f"create_defaults_{provider}") or "{}"
    try:
        return _json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}


class CreateDefaultsBody(BaseModel):
    provider: str
    defaults: dict

@app.put("/api/create-defaults")
def set_create_defaults(request: Request, body: CreateDefaultsBody):
    _require_login(request)
    import json as _json
    get_provider(body.provider)  # 校验 provider 有效
    db.meta_set(f"create_defaults_{body.provider}", _json.dumps(body.defaults))
    return {"ok": True}


# ---------- 流量控制规则 ----------

class TrafficRuleBody(BaseModel):
    account_id: int
    instance_key: str
    instance_name: str = ""
    name: str
    metric: str = "out"
    window_hours: int = 24
    limit_gb: float = 100
    duration_hours: int = 24
    enabled: bool = True
    notify_trigger: bool = True
    notify_recover: bool = True

@app.get("/api/traffic-rules")
def list_traffic_rules(request: Request, account_id: int | None = None):
    _require_login(request)
    return db.traffic_rule_list(account_id)

@app.post("/api/traffic-rules")
def add_traffic_rule(request: Request, body: TrafficRuleBody):
    _require_login(request)
    if body.metric not in ("in", "out", "both"):
        raise HTTPException(status_code=400, detail="metric 只能是 in/out/both")
    rid = db.traffic_rule_add(body.dict())
    return {"ok": True, "id": rid}

@app.put("/api/traffic-rules/{rule_id}")
def update_traffic_rule(request: Request, rule_id: int, body: dict):
    _require_login(request)
    if not db.traffic_rule_update(rule_id, body):
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"ok": True}

@app.delete("/api/traffic-rules/{rule_id}")
def delete_traffic_rule(request: Request, rule_id: int):
    _require_login(request)
    db.traffic_rule_delete(rule_id)
    return {"ok": True}


# ---------- Cloudflare DNS 映射 ----------
class DnsMappingBody(BaseModel):
    account_id: int
    instance_id: str
    zone_name: str
    record_name: str


class DnsMappingUpdateBody(BaseModel):
    instance_id: str | None = None
    zone_name: str | None = None
    record_name: str | None = None


@app.get("/api/dns-mappings")
def list_dns_mappings(request: Request, account_id: int | None = None):
    _require_login(request)
    if account_id:
        _get_account(account_id)
    return db.dns_mapping_list(account_id)


@app.post("/api/dns-mappings")
def add_dns_mapping(request: Request, body: DnsMappingBody):
    _require_login(request)
    _get_account(body.account_id)
    instance_id = body.instance_id.strip()
    zone_name = body.zone_name.strip()
    record_name = body.record_name.strip()
    if not instance_id or not zone_name or not record_name:
        raise HTTPException(status_code=400, detail="实例、Zone 域名、记录名均不能为空")
    mid = db.dns_mapping_add(body.account_id, instance_id, zone_name, record_name)
    return {"ok": True, "id": mid}


@app.put("/api/dns-mappings/{mapping_id}")
def update_dns_mapping(request: Request, mapping_id: int,
                       body: DnsMappingUpdateBody):
    _require_login(request)
    fields = {k: v.strip() for k, v in body.dict().items()
              if v is not None and v.strip()}
    if not fields:
        raise HTTPException(status_code=400, detail="没有要更新的字段")
    if not db.dns_mapping_update(mapping_id, None, fields):
        raise HTTPException(status_code=404, detail="映射不存在")
    return {"ok": True}


@app.delete("/api/dns-mappings/{mapping_id}")
def delete_dns_mapping(request: Request, mapping_id: int):
    _require_login(request)
    if not db.dns_mapping_delete(mapping_id):
        raise HTTPException(status_code=404, detail="映射不存在")
    return {"ok": True}


# ---------- 回收站 ----------

@app.get("/api/recycle-bin")
def list_recycle_bin(request: Request):
    _require_login(request)
    return {"items": db.recycle_list(), "stats": db.recycle_stats()}


@app.get("/api/accounts/{account_id}/detail")
def account_detail(request: Request, account_id: int):
    """账号编辑回显：非敏感字段明文返回，敏感凭证只标记是否已设置。"""
    _require_login(request)
    acc = db.account_get(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    creds = acc.get("creds") or {}
    creds_out = {}
    for f in get_provider(acc["provider"]).fields:
        if f.key in _NON_SENSITIVE_CREDS:
            creds_out[f.key] = creds.get(f.key) or ""
        else:
            creds_out[f.key] = {"set": bool(creds.get(f.key))}
    return {
        "id": acc["id"],
        "name": acc["name"],
        "provider": acc["provider"],
        "region": creds.get("region") or "",
        "proxy_url": acc.get("proxy_url") or "",
        "proxy_user": acc.get("proxy_user") or "",
        "proxy_pass": {"set": bool(acc.get("proxy_pass_enc"))},
        "creds": creds_out,
    }


@app.put("/api/accounts/{account_id}")
def update_account(request: Request, account_id: int, body: AccountUpdateBody):
    _require_login(request)
    acc = db.account_get(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    # 别名：未提交保持原值；提交空字符串拒绝
    name = (body.name if body.name is not None else acc["name"]).strip()
    if not name:
        raise HTTPException(status_code=400, detail="别名不能为空")
    proxy = _proxy_update_of(body, acc)
    # 凭证部分更新：以现有凭证为基础，只应用提交的字段
    new_creds = None
    if body.creds:
        merged = {k: v for k, v in (acc.get("creds") or {}).items()
                  if k not in db._PROXY_CREDS_KEYS}
        changed = False
        for k, v in body.creds.items():
            if k in db._PROXY_CREDS_KEYS:
                continue
            if isinstance(v, str):
                v = v.strip()
            if k in _NON_SENSITIVE_CREDS:  # 非敏感：提交即更新，空值拒绝
                if not v:
                    raise HTTPException(
                        status_code=400,
                        detail="区域不能为空" if k == "region" else f"{k} 不能为空")
                if merged.get(k) != v:
                    merged[k] = v
                    changed = True
            elif v:  # 敏感字段：仅非空新值更新，留空保持原值
                if merged.get(k) != v:
                    merged[k] = v
                    changed = True
        if changed:
            new_creds = merged
    # 只有凭证实际变更才做连通性测试（走新代理配置，若有）
    if new_creds is not None:
        provider = get_provider(acc["provider"])
        try:
            provider.test({**new_creds, **(proxy or {})})
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"凭证校验失败: {e}") from e
    db.account_update(account_id, name, new_creds, proxy=proxy)
    db.audit_add(_client_ip(request), "account_update",
                 f"{acc['provider']} / {name}")
    return {"ok": True}


@app.delete("/api/accounts/{account_id}")
def delete_account(request: Request, account_id: int):
    _require_login(request)
    acc = db.account_get(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    # 记入回收站：估算费用（本月账单）+ 存活天数
    try:
        provider = get_provider(acc["provider"])
        if not getattr(provider, "supports_billing", False):
            billing = {}
        elif acc["provider"] == "aws":
            # AWS 走账单缓存，避免 Cost Explorer 按次收费
            billing = billing.get_cached(
                acc["id"], lambda: provider.get_billing(acc["creds"]))
        else:
            billing = provider.get_billing(acc["creds"])
        cost = float(billing.get("total") or 0)
    except Exception:  # noqa: BLE001
        cost = 0
    days = 0
    if acc.get("cloud_created_at"):
        days = round((time.time() - acc["cloud_created_at"]) / 86400, 2)
    db.recycle_add(acc["provider"], acc["name"], cost, days)
    db.account_delete(account_id)
    # 级联删除该账号的 DNS 映射
    db.dns_mapping_delete_by_account(account_id)
    db.audit_add(_client_ip(request), "account_delete",
                 f"{acc['provider']} / {acc['name']}")
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
def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return ""
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


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


# 操作参数定义：key -> [(param_name, label, type)]
_ACTION_PARAMS: dict[str, list[tuple[str, str, str]]] = {
    "rename": [("new_name", "新名称", "text")],
    "extend_disk": [("size_gb", "新磁盘大小 (GB)", "number")],
    "open_port": [("port", "端口号", "number")],
    "resize": [("size", "新规格 (如 Standard_B2s)", "text")],
    "change_ip": [("cidr", "目标网段 (如 192.0.2.0/24，! 前缀为排除，可空)", "text")],
    "update_shape": [("shape", "新形状", "text"),
                     ("ocpus", "OCPU 数 (Flex 可填)", "number"),
                     ("memory_gbs", "内存 GB (Flex 可填)", "number")],
}


@app.get("/api/accounts/{account_id}/actions")
def list_actions(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    out = []
    for a in provider.actions:
        out.append({
            "key": a["key"],
            "label": a.get("label", a["key"]),
            "danger": bool(a.get("danger", False)),
            "params": [
                {"name": n, "label": lb, "type": t}
                for n, lb, t in _ACTION_PARAMS.get(a["key"], [])
            ],
        })
    return out


@app.post("/api/accounts/{account_id}/action")
def instance_action(request: Request, account_id: int, body: ActionBody):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    if body.action not in [a["key"] for a in provider.actions]:
        raise HTTPException(status_code=400, detail="不支持的操作")
    title = f"{body.action} / {body.instance.get('name', body.instance.get('id', ''))}"
    db.audit_add(_client_ip(request), "instance_action",
                 f"{acc['provider']} / {title}")
    job_id = tasks.submit_action(acc["provider"], account_id,
                                 body.instance, body.action, body.params, title)
    return {"ok": True, "job_id": job_id}


class BootVolumeVpusBody(BaseModel):
    instance_id: str
    vpus_per_gb: int


@app.post("/api/accounts/{account_id}/boot-volume-vpus")
def boot_volume_vpus(request: Request, account_id: int, body: BootVolumeVpusBody):
    """调整 OCI 实例引导卷 VPU（只能调大，同步执行非后台任务）。"""
    _require_login(request)
    acc = _get_account(account_id)
    if acc["provider"] != "oci":
        raise HTTPException(status_code=400, detail="仅支持 OCI 账号")
    instance_id = (body.instance_id or "").strip()
    if not instance_id:
        raise HTTPException(status_code=400, detail="缺少 instance_id")
    vpus = int(body.vpus_per_gb or 0)
    if vpus <= 0:
        raise HTTPException(status_code=400, detail="VPU 必须是正整数")
    provider = get_provider("oci")
    compute, _, _ = oci_provider._clients(acc["creds"])
    try:
        msg = provider.update_boot_volume_vpus(compute, acc["creds"], instance_id, vpus)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 - OCI SDK 报错原样返回
        raise HTTPException(status_code=502, detail=f"OCI 调用失败: {e}") from e
    db.audit_add(_client_ip(request), "boot_volume_vpus",
                 f"账号 {acc['name']} 实例 {instance_id} VPU → {vpus}")
    return {"ok": True, "message": msg}


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


# ---------- OCI 安全列表 ----------
class SecurityRuleBody(BaseModel):
    instance_id: str
    rule: dict


def _require_oci(acc: dict):
    if acc["provider"] != "oci":
        raise HTTPException(status_code=400, detail="仅 OCI 账号支持安全列表管理")


@app.get("/api/accounts/{account_id}/security-rules")
def list_security_rules(request: Request, account_id: int, instance_id: str):
    _require_login(request)
    acc = _get_account(account_id)
    _require_oci(acc)
    try:
        return get_provider(acc["provider"]).list_security_rules(
            acc["creds"], instance_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取安全规则失败: {e}") from e


@app.post("/api/accounts/{account_id}/security-rules")
def add_security_rule(request: Request, account_id: int, body: SecurityRuleBody):
    _require_login(request)
    acc = _get_account(account_id)
    _require_oci(acc)
    try:
        msg = get_provider(acc["provider"]).add_security_rule(
            acc["creds"], body.instance_id, body.rule)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"添加规则失败: {e}") from e
    return {"ok": True, "message": msg}


@app.delete("/api/accounts/{account_id}/security-rules")
def delete_security_rule(request: Request, account_id: int, body: SecurityRuleBody):
    _require_login(request)
    acc = _get_account(account_id)
    _require_oci(acc)
    try:
        msg = get_provider(acc["provider"]).delete_security_rule(
            acc["creds"], body.instance_id, body.rule)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"删除规则失败: {e}") from e
    return {"ok": True, "message": msg}


# ---------- 账单 ----------
@app.get("/api/accounts/{account_id}/billing")
def get_billing(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    if not provider.supports_billing:
        raise HTTPException(status_code=400, detail="该云厂商不支持查看账单")
    if acc["provider"] == "aws":
        # AWS Cost Explorer 按次收费：每月 15 号和月末查两次，其余时间被动展示缓存
        def _fetch_aws():
            try:
                data = provider.get_billing(acc["creds"])
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"获取账单失败: {e}") from e
            # 手动维护的 credit（API 查不到的类型，如 Explore AWS 教程奖励）
            # 剩余额度自动更新：总额 − CE 查到的累计抵扣（从最早生效日算起）
            import datetime as _dt
            manual = db.credit_list(account_id)
            man_total = sum(m["amount"] for m in manual)
            man_applied = 0.0
            if manual:
                end_d = _dt.date.today().isoformat()
                for m in manual:
                    start_ts = m.get("start_at")
                    start_d = _dt.datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d") if start_ts \
                        else (_dt.date.today() - _dt.timedelta(days=365)).isoformat()
                    try:
                        cur_applied = provider.get_credit_applied(acc["creds"], start_d, end_d)
                    except Exception:  # noqa: BLE001
                        cur_applied = 0.0
                    # 只算添加之后的新增抵扣
                    man_applied += max(0.0, cur_applied - (m.get("ce_baseline") or 0.0))
            man_remaining = max(0.0, round(man_total - man_applied, 2))
            for m in manual:
                m["source"] = "manual"
                m["initial"] = m.pop("amount")
                m["remaining"] = m["initial"]  # 单笔不精确分摊，只展示总额
                m["used"] = 0.0
                exp = m.pop("expires_at")
                m["expires_at_raw"] = exp
                m["expires"] = _fmt_ts(exp) if exp else ""
                m["status"] = "手动"
            data["manual_credits"] = manual
            data["manual_total"] = round(man_total, 2)
            data["manual_applied"] = man_applied
            data["manual_remaining"] = man_remaining
            return data
        try:
            data = billing.get_cached(account_id, _fetch_aws)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"获取账单失败: {e}") from e
        return data
    try:
        data = provider.get_billing(acc["creds"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取账单失败: {e}") from e
    if acc["provider"] == "azure":
        # Azure 教育优惠到期日：
        # 1) 手动设置的 edu_expires_at 最准（Sponsorships 门户无公开 API）
        # 2) 没手动设但有云账号创建时间 → 按学生优惠 12 个月规则预估
        import time as _time
        edu_ts = acc.get("edu_expires_at")
        edu_estimated = False
        if not edu_ts and acc.get("cloud_created_at"):
            edu_ts = acc["cloud_created_at"] + 365 * 86400
            edu_estimated = True
        if edu_ts:
            days_left = int((edu_ts - _time.time()) / 86400)
            data["edu_expires_at"] = edu_ts
            data["edu_expires"] = _fmt_ts(edu_ts)
            data["edu_days_left"] = days_left
            data["edu_expired"] = days_left < 0
            data["edu_expiring_soon"] = 0 <= days_left <= 30
            data["edu_estimated"] = edu_estimated
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


class CloudCreatedAtBody(BaseModel):
    timestamp: float | None = None  # unix 时间戳，传 null 清除


@app.put("/api/accounts/{account_id}/cloud-created-at")
def set_cloud_created_at(request: Request, account_id: int, body: CloudCreatedAtBody):
    _require_login(request)
    _get_account(account_id)
    ts = body.timestamp
    if ts is not None and ts <= 0:
        raise HTTPException(status_code=400, detail="时间戳无效")
    db.account_set_cloud_created_at(account_id, ts)
    return {"ok": True}


class EduExpiresAtBody(BaseModel):
    timestamp: float | None = None  # unix 时间戳，传 null 清除


@app.put("/api/accounts/{account_id}/edu-expires-at")
def set_edu_expires_at(request: Request, account_id: int, body: EduExpiresAtBody):
    """设置 Azure 教育优惠到期日。"""
    _require_login(request)
    _get_account(account_id)
    ts = body.timestamp
    if ts is not None and ts <= 0:
        raise HTTPException(status_code=400, detail="时间戳无效")
    db.account_set_edu_expires_at(account_id, ts)
    return {"ok": True}


class ManualCreditBody(BaseModel):
    name: str
    amount: float
    expires_at: float | None = None  # unix 时间戳，可空
    start_at: float | None = None  # 生效日期 unix 时间戳，可空（默认今天）


@app.get("/api/accounts/{account_id}/credits-manual")
def list_manual_credits(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    if acc["provider"] != "aws":
        raise HTTPException(status_code=400, detail="只有 AWS 账号支持维护 Credit")
    return db.credit_list(account_id)


@app.post("/api/accounts/{account_id}/credits-manual")
def add_manual_credit(request: Request, account_id: int, body: ManualCreditBody):
    _require_login(request)
    acc = _get_account(account_id)
    if acc["provider"] != "aws":
        raise HTTPException(status_code=400, detail="只有 AWS 账号支持维护 Credit")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写 Credit 名称")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    import time as _t
    import datetime as _dt2
    start_ts = body.start_at or _t.time()
    # 记录添加时的 CE 累计抵扣作为基线，之后只算新增抵扣（排除历史其他 credit）
    baseline = 0.0
    try:
        provider = get_provider(acc["provider"])
        start_d = _dt2.datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d")
        baseline = provider.get_credit_applied(acc["creds"], start_d, _dt2.date.today().isoformat())
    except Exception:  # noqa: BLE001
        pass
    cid = db.credit_add(account_id, name, body.amount, body.expires_at, start_ts, baseline)
    return {"ok": True, "id": cid}


@app.delete("/api/accounts/{account_id}/credits-manual/{credit_id}")
def del_manual_credit(request: Request, account_id: int, credit_id: int):
    _require_login(request)
    _get_account(account_id)
    if not db.credit_delete(credit_id, account_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True}


@app.put("/api/accounts/{account_id}/credits-manual/{credit_id}")
def edit_manual_credit(request: Request, account_id: int, credit_id: int,
                       body: ManualCreditBody):
    _require_login(request)
    acc = _get_account(account_id)
    if acc["provider"] != "aws":
        raise HTTPException(status_code=400, detail="只有 AWS 账号支持维护 Credit")
    old = db.credit_get(credit_id, account_id)
    if not old:
        raise HTTPException(status_code=404, detail="记录不存在")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写 Credit 名称")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    import time as _t
    import datetime as _dt2
    fields = {"name": name, "amount": body.amount, "expires_at": body.expires_at}
    # 生效日期变了 → 重算基线
    new_start = body.start_at or old.get("start_at") or _t.time()
    if abs(new_start - (old.get("start_at") or 0)) > 1:
        fields["start_at"] = new_start
        try:
            provider = get_provider(acc["provider"])
            start_d = _dt2.datetime.fromtimestamp(new_start).strftime("%Y-%m-%d")
            fields["ce_baseline"] = provider.get_credit_applied(
                acc["creds"], start_d, _dt2.date.today().isoformat())
        except Exception:  # noqa: BLE001
            fields["ce_baseline"] = old.get("ce_baseline") or 0.0
    db.credit_update(credit_id, account_id, fields)
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


# ---------- Azure Foundry ----------
@app.get("/api/accounts/{account_id}/foundry-quotas")
def get_foundry_quotas(request: Request, account_id: int, region: str = ""):
    _require_login(request)
    acc = _get_account(account_id)
    provider = get_provider(acc["provider"])
    if acc["provider"] != "azure":
        raise HTTPException(status_code=400, detail="仅 Azure 账号支持此功能")
    try:
        result = provider.get_foundry_quotas(acc["creds"], region)
        if "error" in result:
            raise ValueError(result["error"])
        return result
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取 Foundry 配额失败: {e}") from e


class FoundryDeployBody(BaseModel):
    account_name: str = ""
    region: str = ""
    model_name: str = ""


@app.post("/api/accounts/{account_id}/foundry-deploy")
def foundry_deploy(request: Request, account_id: int, body: FoundryDeployBody):
    _require_login(request)
    acc = _get_account(account_id)
    if acc["provider"] != "azure":
        raise HTTPException(status_code=400, detail="仅 Azure 账号支持此功能")
    try:
        # 直接同步执行（账号创建/模型部署通常 < 2 分钟），结果文本返回前端
        provider = get_provider(acc["provider"])
        ctx = _LogCtx()
        result = provider.foundry_deploy(
            acc["creds"],
            {"account_name": body.account_name,
             "region": body.region,
             "model_name": body.model_name},
            ctx)
        return {"ok": True, "result": result, "logs": ctx.lines}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Foundry 部署失败: {e}") from e


class _LogCtx:
    """最小 ctx：收集 provider 的 ctx.log 输出，随结果返回前端。"""

    def __init__(self):
        self.lines: list[str] = []

    def log(self, message: str) -> None:
        self.lines.append(message)
        log.info("foundry-deploy: %s", message)


# ---------- Azure 资源组 ----------
@app.get("/api/accounts/{account_id}/resource-groups")
def list_resource_groups(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    if acc["provider"] != "azure":
        raise HTTPException(status_code=400, detail="仅 Azure 账号支持此功能")
    provider = get_provider(acc["provider"])
    groups = provider.list_resource_groups(acc["creds"])
    return {"groups": groups}


@app.delete("/api/accounts/{account_id}/resource-groups/{rg_name}")
def delete_resource_group(request: Request, account_id: int, rg_name: str):
    _require_login(request)
    acc = _get_account(account_id)
    if acc["provider"] != "azure":
        raise HTTPException(status_code=400, detail="仅 Azure 账号支持此功能")
    provider = get_provider(acc["provider"])
    try:
        msg = provider.delete_resource_group(acc["creds"], rg_name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"删除资源组失败: {e}") from e
    return {"ok": True, "message": msg}


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
    monitor_ip_check: bool | None = None   # IP 连通性定时检测
    auto_change_ip: bool | None = None     # IP 不通时自动换 IP


@app.get("/api/accounts/{account_id}/monitor")
def get_monitor(request: Request, account_id: int):
    _require_login(request)
    acc = _get_account(account_id)
    import datetime as _dt
    today = _dt.date.today().isoformat()
    return {"monitor_alert": bool(acc.get("monitor_alert")),
            "monitor_restart": bool(acc.get("monitor_restart")),
            "monitor_ip_check": bool(acc.get("monitor_ip_check")),
            "auto_change_ip": bool(acc.get("auto_change_ip")),
            "auto_change_ip_used": db.ip_change_daily_count(
                account_id, today),
            "auto_change_ip_limit": db.AUTO_CHANGE_IP_DAILY_LIMIT}


@app.put("/api/accounts/{account_id}/monitor")
def set_monitor(request: Request, account_id: int, body: MonitorBody):
    _require_login(request)
    _get_account(account_id)
    db.account_set_monitor(account_id, body.monitor_alert, body.monitor_restart)
    if body.monitor_ip_check is not None or body.auto_change_ip is not None:
        db.account_set_ip_check(account_id,
                                 bool(body.monitor_ip_check),
                                 bool(body.auto_change_ip))
    return {"ok": True}


@app.get("/api/accounts/{account_id}/ip-change-usage")
def get_ip_change_usage(request: Request, account_id: int):
    """当日自动换 IP 次数（前端监控页展示用）。"""
    _require_login(request)
    _get_account(account_id)
    import datetime as _dt
    today = _dt.date.today().isoformat()
    return {"used": db.ip_change_daily_count(account_id, today),
            "limit": db.AUTO_CHANGE_IP_DAILY_LIMIT,
            "date": today}


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


@app.get("/api/accounts/{account_id}/cloudfront/{dist_id}/config")
def cloudfront_config(request: Request, account_id: int, dist_id: str):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    try:
        return provider.get_distribution_config(acc["creds"], dist_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取配置失败: {e}") from e


class CloudFrontUpdateBody(BaseModel):
    comment: str | None = None
    origin_domain: str | None = None
    price_class: str | None = None
    default_root_object: str | None = None


class CloudFrontPlanBody(BaseModel):
    distribution_id: str
    plan_tier: str  # paygo | FREE | PRO | BUSINESS | PREMIUM


@app.post("/api/accounts/{account_id}/cloudfront/plan")
def cloudfront_set_plan(request: Request, account_id: int, body: CloudFrontPlanBody):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    # 分发 ARN 需要账号 ID，用 STS 获取
    import boto3 as _boto3
    from botocore.config import Config as _BotocoreConfig
    from .providers.base import proxy_settings as _proxy_settings
    try:
        sts_kwargs = dict(
            aws_access_key_id=acc["creds"]["access_key"].strip(),
            aws_secret_access_key=acc["creds"]["secret_key"].strip(),
            region_name="us-east-1",
        )
        _proxies = _proxy_settings(acc["creds"])
        if _proxies:
            sts_kwargs["config"] = _BotocoreConfig(proxies=_proxies)
        sts = _boto3.client("sts", **sts_kwargs)
        aws_account_id = sts.get_caller_identity()["Account"]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取账号 ID 失败: {e}") from e
    try:
        msg = provider.set_cf_plan(acc["creds"], body.distribution_id, aws_account_id, body.plan_tier)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"切换套餐失败: {e}") from e
    return {"ok": True, "message": msg}


@app.put("/api/accounts/{account_id}/cloudfront/{dist_id}")
def cloudfront_update(request: Request, account_id: int, dist_id: str, body: CloudFrontUpdateBody):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    params = {k: v for k, v in body.dict().items() if v is not None}
    try:
        msg = provider.update_distribution(acc["creds"], dist_id, params)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"更新失败: {e}") from e
    return {"ok": True, "message": msg}


@app.delete("/api/accounts/{account_id}/cloudfront/{dist_id}")
def cloudfront_delete(request: Request, account_id: int, dist_id: str):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    try:
        msg = provider.delete_distribution(acc["creds"], dist_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"删除失败: {e}") from e
    return {"ok": True, "message": msg}


class CloudFrontCreateBody(BaseModel):
    origin_domain: str
    comment: str = ""
    price_class: str = "100"
    origin_protocol: str = "match-viewer"  # http-only|https-only|match-viewer
    compress: bool = False
    cache_mode: str = "legacy"  # legacy|optimized


@app.post("/api/accounts/{account_id}/cloudfront/create")
def cloudfront_create(request: Request, account_id: int, body: CloudFrontCreateBody):
    _require_login(request)
    acc = _get_account(account_id)
    provider = _require_aws(acc)
    try:
        msg = provider.create_distribution(
            acc["creds"], body.origin_domain, body.comment, body.price_class,
            body.origin_protocol, body.compress, body.cache_mode)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"创建失败: {e}") from e
    return {"ok": True, "message": msg}


# ---------- 设置（Telegram 联动） ----------
class SettingsBody(BaseModel):
    tg_bot_token: str = ""
    tg_chat_id: str = ""
    cf_api_token: str = ""
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
        "cf_token_set": cf.token_configured(),
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
    cf_token = body.cf_api_token.strip()
    if cf_token:
        cf.set_token(cf_token)
    if body.daily_report is not None:
        db.meta_set("daily_report", "1" if body.daily_report else "0")
    if body.daily_report_hour is not None:
        db.meta_set("daily_report_hour", str(max(0, min(23, body.daily_report_hour))))
    if body.monitor_interval_min is not None:
        db.meta_set("monitor_interval_min", str(max(1, min(120, body.monitor_interval_min))))
    state = tg.refresh_bot()
    db.audit_add(_client_ip(request), "settings_update", "Telegram/监控设置已保存")
    return {"ok": True, **state}


@app.post("/api/settings/tg-test")
def tg_test(request: Request):
    _require_login(request)
    if tg.send_message("✅ TriCloud Telegram 联动测试成功"):
        return {"ok": True}
    raise HTTPException(status_code=400, detail="发送失败，请检查 Bot Token 和 Chat ID")


# ---------- 加密备份 / 恢复 ----------
def _db_path() -> str:
    return os.path.join(config.DATA_DIR, "tricloud.db")


class BackupBody(BaseModel):
    password: str


@app.post("/api/backup")
def backup(request: Request, body: BackupBody):
    """导出整个 SQLite 库的加密备份。备份密码不存服务器、不记日志。"""
    _require_login(request)
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="备份密码至少 8 位")
    db_path = _db_path()
    if not os.path.exists(db_path):
        raise HTTPException(status_code=500, detail="数据库文件不存在")
    with open(db_path, "rb") as f:
        raw = f.read()
    blob = backup_mod.encrypt_db_file(raw, body.password)
    fname = "tricloud-backup-%s.bin" % time.strftime("%Y%m%d")
    db.audit_add(_client_ip(request), "backup", f"导出加密备份 {fname}")
    return StreamingResponse(
        io.BytesIO(blob), media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/api/restore")
async def restore(request: Request, file: UploadFile = File(...),
                  password: str = Form(...), confirm: str = Form("")):
    """恢复备份。第一步只校验并返回备份信息；带 confirm=true 才真正覆盖。

    覆盖前把当前库重命名为 .bak 保留；恢复后清空 sessions 要求重新登录。
    """
    _require_login(request)
    ip = _client_ip(request)
    blob = await file.read()
    try:
        raw = backup_mod.decrypt_db_file(blob, password)
        info = backup_mod.inspect_db(raw)
    except ValueError as e:
        db.audit_add(ip, "restore_fail", str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e
    if confirm != "true":
        return {"ok": True, "need_confirm": True,
                "file_name": file.filename or "",
                "accounts": info["accounts"],
                "latest_record_at": info["latest_record_at"]}
    db_path = _db_path()
    if os.path.exists(db_path):
        os.replace(db_path, db_path + ".bak")  # 保留当前库
    with open(db_path, "wb") as f:
        f.write(raw)
    # 清空会话：恢复后要求重新登录
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM sessions")
        conn.commit()
    finally:
        conn.close()
    db.audit_add(ip, "restore",
                 f"从备份恢复：账号 {info['accounts']} 个，原库已保留为 .bak")
    return {"ok": True, "restored": True}


# ---------- 开机脚本模板 ----------
class ScriptTemplateBody(BaseModel):
    name: str
    os_type: str
    content: str = ""


@app.get("/api/script-templates")
def script_template_list(request: Request, os_type: str | None = None):
    _require_login(request)
    return db.script_template_list(os_type)


@app.post("/api/script-templates")
def script_template_add(request: Request, body: ScriptTemplateBody):
    _require_login(request)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    try:
        tpl_id = db.script_template_add(body.name, body.os_type, body.content or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.audit_add(_client_ip(request), "script_template_add",
                 f"{body.os_type} / {body.name.strip()}")
    return {"ok": True, "id": tpl_id}


@app.put("/api/script-templates/{tpl_id}")
def script_template_update(request: Request, tpl_id: int, body: ScriptTemplateBody):
    _require_login(request)
    try:
        ok = db.script_template_update(tpl_id, {
            "name": body.name, "os_type": body.os_type,
            "content": body.content or ""})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.audit_add(_client_ip(request), "script_template_update",
                 f"#{tpl_id} {body.name.strip()}")
    return {"ok": True}


@app.delete("/api/script-templates/{tpl_id}")
def script_template_delete(request: Request, tpl_id: int):
    _require_login(request)
    if not db.script_template_delete(tpl_id):
        raise HTTPException(status_code=404, detail="模板不存在")
    db.audit_add(_client_ip(request), "script_template_delete", f"#{tpl_id}")
    return {"ok": True}


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
