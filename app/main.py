"""TriCloud 三合一云服务器管理面板：FastAPI 后端。"""
import logging
import os

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, db, jobs, monitor, tasks, tg, traffic
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


# ---------- 回收站 ----------

@app.get("/api/recycle-bin")
def list_recycle_bin(request: Request):
    _require_login(request)
    return {"items": db.recycle_list(), "stats": db.recycle_stats()}


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
    acc = db.account_get(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    # 记入回收站：估算费用（本月账单）+ 存活天数
    try:
        provider = get_provider(acc["provider"])
        billing = provider.get_billing(acc["creds"]) if getattr(provider, "supports_billing", False) else {}
        cost = float(billing.get("total") or 0)
    except Exception:  # noqa: BLE001
        cost = 0
    days = 0
    if acc.get("cloud_created_at"):
        days = round((time.time() - acc["cloud_created_at"]) / 86400, 2)
    db.recycle_add(acc["provider"], acc["name"], cost, days)
    db.account_delete(account_id)
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
    if acc["provider"] == "azure":
        # Azure 教育优惠到期日（手动设置，Sponsorships 门户无公开 API）
        import time as _time
        edu_ts = acc.get("edu_expires_at")
        if edu_ts:
            days_left = int((edu_ts - _time.time()) / 86400)
            data["edu_expires_at"] = edu_ts
            data["edu_expires"] = _fmt_ts(edu_ts)
            data["edu_days_left"] = days_left
            data["edu_expired"] = days_left < 0
            data["edu_expiring_soon"] = 0 <= days_left <= 30
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
    try:
        sts = _boto3.client(
            "sts",
            aws_access_key_id=acc["creds"]["access_key"].strip(),
            aws_secret_access_key=acc["creds"]["secret_key"].strip(),
            region_name="us-east-1",
        )
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
