"""云账号：增删改查、粘贴识别、批量添加、测活、创建日期、账号类型 / 停用、已删账号回收站。"""
import asyncio
import json
import time

from fastapi import APIRouter, Body, HTTPException

from .. import accounts_import, core, services, tasks
from .common import _num_or_none, _valid_date, call, need_acc, P, REQUIRED, run

router = APIRouter()


# ---------------- 账号 ----------------
@router.get("/api/accounts")
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


@router.post("/api/accounts")
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
@router.post("/api/accounts/parse")
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
@router.post("/api/accounts/batch")
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


@router.post("/api/accounts/test-all")
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


@router.post("/api/accounts/{acc_id}/test")
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


@router.post("/api/accounts/{acc_id}/detect-created")
async def detect_created(acc_id: int):
    """OCI：读取租户根区间创建时间并写入（迁移来的账号没测活时为空）。"""
    return await run(_detect_created_sync, acc_id)


@router.patch("/api/accounts/{acc_id}")
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


@router.get("/api/accounts/{acc_id}/detail")
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


@router.delete("/api/accounts/{acc_id}")
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


@router.get("/api/accounts/{acc_id}/regions")
async def regions(acc_id: int):
    need_acc(acc_id)
    return await run(services.provider(acc_id).regions)


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


@router.get("/api/recycle-bin")
def recycle_bin():
    """已删账号：删除时留档的名称、云、存活天数、预估费用。"""
    return {"items": core.q("SELECT * FROM deleted_accounts ORDER BY deleted_at DESC, id DESC"), "stats": _deleted_stats()}


@router.get("/api/recycle-bin/stats")
def recycle_bin_stats():
    return _deleted_stats()


@router.delete("/api/recycle-bin/{rid}")
def recycle_bin_del(rid: int):
    core.ex("DELETE FROM deleted_accounts WHERE id=?", (rid,))
    return {"ok": True}


@router.delete("/api/recycle-bin")
def recycle_bin_clear(confirm: bool = False):
    if not confirm:
        raise HTTPException(400, "需确认")
    core.ex("DELETE FROM deleted_accounts")
    return {"ok": True}


# ================= 11. 账号类型 / 开户天数 / 停用 =================
@router.get("/api/accounts/{acc_id}/account-type")
async def account_type(acc_id: int, refresh: bool = False):
    acc = need_acc(acc_id)
    row = core.q("SELECT acct_type, cloud_created_at FROM accounts WHERE id=?", (acc_id,), one=True)
    if row and row["acct_type"] and not refresh:
        return json.loads(row["acct_type"])
    if acc["provider"] == "oci":
        r = await call(P(acc_id).account_type)
    elif acc["provider"] == "azure":
        s = await call(P(acc_id).subscription_info)
        r = {"label": s.get("offer") or s.get("quota_id") or "未知", "plan_type": s.get("quota_id"), "state": s.get("state"),
             "spending_limit": s.get("spending_limit")}
    else:
        r = {"label": "AWS 账号", "plan_type": None,
             "hint": "AWS 没有公开的「试用 / 付费」类型接口；新账号的免费套餐期限请以控制台 Billing 为准"}
    if not r.get("age_days") and row and row["cloud_created_at"]:
        try:
            r["age_days"] = int((time.time() - time.mktime(time.strptime(row["cloud_created_at"], "%Y-%m-%d"))) // 86400)
        except ValueError:
            pass
    r["checked_at"] = int(time.time())
    core.ex("UPDATE accounts SET acct_type=? WHERE id=?", (json.dumps(r, ensure_ascii=False), acc_id))
    if acc["provider"] == "oci" and r.get("time_start") and not (row and row["cloud_created_at"]):
        core.ex("UPDATE accounts SET cloud_created_at=? WHERE id=?", (r["time_start"], acc_id))
    return r


@router.post("/api/accounts/{acc_id}/disable")
async def disable_account(acc_id: int, body: dict = Body(default={})):
    """被封号一键停用：不测活、不监控、不跑流量守护；运行中的任务全部停止。可随时启用。凭证保留。"""
    need_acc(acc_id)
    on = body.get("disabled", True) not in (False, "false", 0, "0")
    core.ex("UPDATE accounts SET disabled=?, disabled_reason=? WHERE id=?",
            (1 if on else 0, (str(body.get("reason") or "")[:200] or None) if on else None, acc_id))
    stopped = []
    if on:
        for t in core.q("SELECT id FROM tasks WHERE account_id=? AND status='running'", (acc_id,)):
            tasks.stop_task(t["id"])
            stopped.append(t["id"])
    return {"ok": True, "disabled": on, "stopped_tasks": stopped}
