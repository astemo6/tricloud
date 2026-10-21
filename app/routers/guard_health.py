"""v1.2：免费额度护栏预检、账号健康度、跨云迁移。"""
from fastapi import APIRouter, Body, HTTPException

from .. import core, guard, tasks, telegram
from ..i18n import msg
from .. import health as healthm
from .common import guarded, need_acc, run

router = APIRouter()


# ================= v1.2：免费额度护栏 / 账号健康度 / 跨云迁移 =================
@router.post("/api/accounts/{acc_id}/guard-check")
async def guard_check(acc_id: int, body: dict = Body(...)):
    """前端预检（不执行任何操作）。"""
    need_acc(acc_id)
    return {"warnings": await run(guard.check, acc_id, body.get("op", "create"), body, body.get("region"))}


@router.get("/api/account-health")
def account_health():
    return healthm.list_cached()


@router.post("/api/account-health/refresh")
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


@router.post("/api/migrate")
async def migrate(body: dict = Body(...)):
    """跨云迁移：在目标账号用同一开机脚本重建，可切 DNS、复制监控、停掉源实例。不复制磁盘数据。"""
    src, dst = need_acc(int(body["from_account_id"])), need_acc(int(body["to_account_id"]))
    if src["id"] == dst["id"]:
        raise HTTPException(400, msg("err.same_account"))
    c = dict(body.get("create") or {})
    if dst["provider"] == "azure" and not c.get("location"):
        raise HTTPException(400, msg("err.pick_azure_region"))
    await guarded(dst["id"], "create", c if dst["provider"] != "oci" else {"create": c, **c}, body.get("region"))
    tid = tasks.create_task("migrate", dst["id"], {
        "from_account_id": src["id"], "instance_id": body["instance_id"], "from_region": body.get("from_region"),
        "name": body.get("name"), "region": body.get("region"), "create": c,
        "switch_dns": bool(body.get("switch_dns")), "stop_source": bool(body.get("stop_source")),
        "copy_monitor": bool(body.get("copy_monitor", True))})
    return {"ok": True, "task_id": tid}
