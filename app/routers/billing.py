"""账单与 Credit：账单、AWS Credit、三家通用手动 Credit、教育优惠、到期提醒。"""
from fastapi import APIRouter, Body, HTTPException

from .. import core, services
from .. import credits as creditsm
from .common import _num_or_none, _valid_date, need_acc, run

router = APIRouter()


# ---------------- 账单 ----------------
@router.get("/api/accounts/{acc_id}/billing")
async def billing(acc_id: int, force: bool = False):
    need_acc(acc_id)
    return await run(services.billing, acc_id, force)


@router.get("/api/accounts/{acc_id}/credits")
def credits(acc_id: int):
    need_acc(acc_id, "aws")
    return core.q("SELECT * FROM aws_credits WHERE account_id=? ORDER BY start_date", (acc_id,))


@router.post("/api/accounts/{acc_id}/credits")
def add_credit(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    return {"id": core.ex("INSERT INTO aws_credits(account_id,name,amount,start_date,expire_date) VALUES(?,?,?,?,?)",
                          (acc_id, body.get("name", "Credit"), float(body["amount"]), body["start_date"],
                           body.get("expire_date")))}


@router.delete("/api/credits/{cid}")
def del_credit(cid: int):
    core.ex("DELETE FROM aws_credits WHERE id=?", (cid,))
    return {"ok": True}


# ---------------- v1.4：Credit（三家云通用）与教育优惠 ----------------
@router.get("/api/accounts/{acc_id}/credit-summary")
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


@router.get("/api/accounts/{acc_id}/credits-manual")
def credits_manual(acc_id: int):
    need_acc(acc_id)
    return core.q("SELECT * FROM aws_credits WHERE account_id=? ORDER BY COALESCE(expire_date, '9999-12-31'), id", (acc_id,))


@router.post("/api/accounts/{acc_id}/credits-manual")
def credits_manual_add(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id)
    f = _credit_fields(body)
    return {"id": core.ex("INSERT INTO aws_credits(account_id,name,amount,start_date,expire_date,used_manual) VALUES(?,?,?,?,?,?)",
                          (acc_id, f["name"], f["amount"], f["start_date"], f["expire_date"], f["used_manual"]))}


@router.put("/api/accounts/{acc_id}/credits-manual/{cid}")
def credits_manual_edit(acc_id: int, cid: int, body: dict = Body(...)):
    need_acc(acc_id)
    if not core.q("SELECT 1 FROM aws_credits WHERE id=? AND account_id=?", (cid, acc_id), one=True):
        raise HTTPException(404, "Credit 不存在")
    f = _credit_fields(body, partial=True)
    if f:
        core.ex(f"UPDATE aws_credits SET {', '.join(k + '=?' for k in f)} WHERE id=? AND account_id=?", (*f.values(), cid, acc_id))
    return {"ok": True}


@router.delete("/api/accounts/{acc_id}/credits-manual/{cid}")
def credits_manual_del(acc_id: int, cid: int):
    need_acc(acc_id)
    core.ex("DELETE FROM aws_credits WHERE id=? AND account_id=?", (cid, acc_id))
    return {"ok": True}


@router.put("/api/accounts/{acc_id}/credit-total")
def credit_total(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id)
    core.ex("UPDATE accounts SET credit_total=? WHERE id=?", (_num_or_none(body.get("credit_total"), "credit_total"), acc_id))
    return {"ok": True}


@router.put("/api/accounts/{acc_id}/edu-expires-at")
def edu_expires(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "azure")
    core.ex("UPDATE accounts SET edu_expires_at=? WHERE id=?", (_valid_date(body.get("edu_expires_at"), "edu_expires_at"), acc_id))
    return {"ok": True}


@router.get("/api/expiry-alerts")
def expiry_alerts(days: int = 30):
    return creditsm.expiry_alerts(max(1, min(365, days)))
