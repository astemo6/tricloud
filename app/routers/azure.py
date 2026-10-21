"""Azure：资源组、位置、配额、创建、规格、订阅信息、磁盘、Foundry（AI Services）。"""
from fastapi import APIRouter, Body, HTTPException

from .. import core, services, tasks
from ..i18n import msg
from .. import credits as creditsm
from .common import _req, call, guarded, need_acc, P, run

router = APIRouter()


# ---------------- Azure ----------------
@router.get("/api/accounts/{acc_id}/azure/rgs")
async def az_rgs(acc_id: int):
    need_acc(acc_id, "azure")
    return await run(services.provider(acc_id).resource_groups)


@router.post("/api/accounts/{acc_id}/azure/rgs")
async def az_rg_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "azure")
    p = services.provider(acc_id)
    if body.get("op") == "delete":
        if body.get("confirm") != body.get("name"):
            raise HTTPException(400, msg("err.rg_name_confirm"))
        return await run(p.delete_rg, body["name"])
    return await run(p.create_rg, body["name"], body["location"])


@router.get("/api/accounts/{acc_id}/azure/locations")
async def az_locations(acc_id: int):
    need_acc(acc_id, "azure")
    return await run(services.provider(acc_id).locations)


@router.get("/api/accounts/{acc_id}/azure/quotas")
async def az_quotas(acc_id: int, location: str):
    need_acc(acc_id, "azure")
    return await run(services.provider(acc_id).quotas, location)


@router.post("/api/accounts/{acc_id}/azure/create")
async def az_create(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "azure")
    await guarded(acc_id, "create", body)
    if not body.get("location"):
        raise HTTPException(400, msg("err.pick_region"))
    return {"ok": True, "task_id": tasks.create_task("azure_create", acc_id, {"create": body, "instance_id": "-",
                                                                               "name": body.get("name")})}


@router.get("/api/accounts/{acc_id}/azure/sizes")
async def az_sizes(acc_id: int, instance_id: str):
    need_acc(acc_id, "azure")
    return await run(services.provider(acc_id).sizes, instance_id)


@router.get("/api/accounts/{acc_id}/azure/subscription")
async def az_subscription(acc_id: int):
    """v1.4 Azure 订阅页（只读）：状态、类型 / offer、spending limit 等 + 教育优惠到期。"""
    acc = need_acc(acc_id, "azure")
    full = core.q("SELECT * FROM accounts WHERE id=?", (acc_id,), one=True)
    full.pop("cred_enc", None)
    out = {"edu": creditsm.edu_info(full), "cloud_created_at": full.get("cloud_created_at"), "age_days": creditsm.age_days(full),
           "name": acc["name"]}
    try:
        out.update(await run(services.provider(acc_id).subscription_info))
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return out


# ================= 14. Azure 磁盘 =================
@router.get("/api/accounts/{acc_id}/azure/disks")
async def az_disks(acc_id: int, instance_id: str):
    need_acc(acc_id, "azure")
    return await call(P(acc_id).disks, instance_id)


@router.post("/api/accounts/{acc_id}/azure/disks")
async def az_disk_update(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "azure")
    _req(body, "instance_id", "disk_id")
    return await call(P(acc_id).update_disk, body["instance_id"], body["disk_id"], body.get("size_gb") or None,
                      body.get("sku") or None, body.get("tier") or None)


# ================= Azure Foundry（AI Services） =================
@router.get("/api/accounts/{acc_id}/azure/foundry")
async def az_foundry(acc_id: int, region: str = "swedencentral", part: str = "all"):
    need_acc(acc_id, "azure")
    prov = P(acc_id)
    out = {"region": region}
    if part in ("all", "quotas"):
        out.update(await call(prov.foundry_quotas, region))
    if part in ("all", "resources"):
        out["resources"] = await call(prov.foundry_resources)
    if part in ("all", "models"):
        try:
            out["models"] = (await call(prov.foundry_models, region))["models"]
        except HTTPException as e:
            out["models"], out["models_error"] = [], e.detail
    return out


@router.post("/api/accounts/{acc_id}/azure/foundry")
async def az_foundry_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "azure")
    op = body.get("op")
    prov = P(acc_id)
    if op == "deploy":
        _req(body, "model")
        if not body.get("resource_id"):
            _req(body, "name", "region")
        keys = ("resource_id", "name", "region", "resource_group", "model", "version", "sku", "capacity", "deployment")
        tid = tasks.create_task("foundry", acc_id, {**{k: body.get(k) for k in keys}, "name_display": body.get("model")})
        return {"ok": True, "task_id": tid}
    if op == "keys":
        if not body.get("confirm"):
            raise HTTPException(400, msg("err.view_key_confirm"))
        return await call(prov.foundry_keys, body.get("resource_id"))
    if op == "delete_deployment":
        if not body.get("confirm"):
            raise HTTPException(400, msg("err.need_confirm"))
        return await call(prov.foundry_delete_deployment, body.get("resource_id"), body.get("deployment"))
    if op == "delete_resource":
        if not body.get("confirm"):
            raise HTTPException(400, msg("err.need_confirm"))
        return await call(prov.foundry_delete_resource, body.get("resource_id"))
    raise HTTPException(400, msg("err.unknown_op"))
