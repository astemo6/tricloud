"""build 30：OCI「一键切换受限 API」。
GET  /api/accounts/{id}/oci/restrict        状态（是否已受限、TG 是否绑定、最近一次任务、将要创建的策略语句）
POST /api/accounts/{id}/oci/restrict/code   通过已绑定的 Telegram Bot 发 6 位验证码（5 分钟有效、一次性）
POST /api/accounts/{id}/oci/restrict        {code, confirm:true} 校验验证码后创建后台任务 oci_restrict
API Token 调这三个接口一律 403（main.py RESTRICT_RE）。"""
import json

from fastapi import APIRouter, Body, HTTPException, Request

from .. import core, security, tasks, telegram, tg_verify
from ..i18n import msg
from ..providers.oci_restrict import POLICY_RULES, WAIT_SECONDS, names, policy_statements
from .common import client_ip, need_acc

router = APIRouter()
TASK_TYPE = "oci_restrict"


def restricted_info(acc_id):
    r = core.q("SELECT restricted_api FROM accounts WHERE id=?", (acc_id,), one=True)
    if not r or not r.get("restricted_api"):
        return None
    try:
        return json.loads(r["restricted_api"])
    except ValueError:
        return None


def last_task(acc_id):
    return core.q("SELECT id, status, message, created, updated, result FROM tasks WHERE type=? AND account_id=? ORDER BY id DESC LIMIT 1",
                  (TASK_TYPE, acc_id), one=True)


def _task_view(t):
    if not t:
        return None
    try:
        res = json.loads(t.get("result") or "{}")
    except ValueError:
        res = {}
    return {"id": t["id"], "status": t["status"], "message": t["message"], "created": t["created"], "updated": t["updated"],
            "stage": res.get("stage"), "step": res.get("step"), "steps": res.get("steps")}


def _code_key(acc_id):
    return f"restrict:{acc_id}"


def _code_err(e):
    if e.kind == "not_bound":
        raise HTTPException(400, msg("err.rapi_tg_not_bound"))
    if e.kind == "too_soon":
        raise HTTPException(429, msg("err.rapi_code_too_soon", n=e.wait))
    if e.kind == "send_failed":
        raise HTTPException(502, msg("err.rapi_code_send_failed"))
    raise HTTPException(400, msg(f"err.rapi_code_{e.kind}"))


@router.get("/api/accounts/{acc_id}/oci/restrict")
def restrict_status(acc_id: int):
    need_acc(acc_id, "oci")
    return {"restricted": restricted_info(acc_id), "tg_bound": tg_verify.bound(), "task": _task_view(last_task(acc_id)),
            "statements": policy_statements(names("xxxxxx")["group"]), "rules": [{"verb": v, "resource": r, "why": w} for v, r, w in POLICY_RULES],
            "wait_minutes": WAIT_SECONDS // 60, "code_ttl": tg_verify.TTL}


@router.post("/api/accounts/{acc_id}/oci/restrict/code")
async def restrict_code(acc_id: int):
    acc = need_acc(acc_id, "oci")
    if restricted_info(acc_id):
        raise HTTPException(400, msg("err.rapi_already"))
    try:
        return await tg_verify.send(_code_key(acc_id), lambda code: telegram.L(
            "tg.rapi.code", code=code, acc=telegram.esc(acc["name"]), m=tg_verify.TTL // 60))
    except tg_verify.CodeError as e:
        _code_err(e)


@router.post("/api/accounts/{acc_id}/oci/restrict")
def restrict_start(acc_id: int, req: Request, body: dict = Body(default={})):
    acc = need_acc(acc_id, "oci")
    if restricted_info(acc_id):
        raise HTTPException(400, msg("err.rapi_already"))
    t = last_task(acc_id)
    if t and t["status"] == "running":
        raise HTTPException(409, msg("err.rapi_running", id=t["id"]))
    if not tg_verify.bound():
        raise HTTPException(400, msg("err.rapi_tg_not_bound"))
    if not body.get("confirm"):
        raise HTTPException(400, msg("err.rapi_confirm"))
    try:
        tg_verify.verify(_code_key(acc_id), body.get("code"))
    except tg_verify.CodeError as e:
        _code_err(e)
    tid = tasks.create_task(TASK_TYPE, acc_id, {"name": acc["name"]})
    security.audit(client_ip(req), getattr(req.state, "actor", "session"), "oci-restrict-start", f"账号 {acc_id} {acc['name']} 任务 #{tid}")
    return {"ok": True, "task_id": tid}
