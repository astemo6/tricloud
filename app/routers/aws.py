"""AWS：EC2 创建 / 区域、Lightsail（创建、静态 IP、防火墙）、CloudFront、配额、闲置资源估算。"""
import time

from fastapi import APIRouter, Body, HTTPException

from .. import cloudinit, overview, services, tasks
from ..i18n import msg
from .common import _created, _public_guard, _req, call, guarded, need_acc, P, run

router = APIRouter()


# ---------------- AWS: EC2 创建 / 区域 ----------------
@router.get("/api/accounts/{acc_id}/aws/ec2-options")
async def ec2_opts(acc_id: int):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id).ec2_options)


@router.post("/api/accounts/{acc_id}/aws/ec2-create")
async def ec2_create(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    await guarded(acc_id, "create", body, body.get("region"))
    c = dict(body, script=cloudinit.resolve_script(body))
    return _created(acc_id, await run(services.provider(acc_id, body.get("region")).ec2_create, c), body.get("region"))


@router.get("/api/accounts/{acc_id}/aws/regions-status")
async def aws_regions_status(acc_id: int):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id).region_status)


@router.post("/api/accounts/{acc_id}/aws/enable-region")
async def aws_enable_region(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id).enable_region, body["region"])


@router.get("/api/accounts/{acc_id}/aws/scan")
async def aws_scan(acc_id: int, refresh: bool = False):
    """全区域扫描：与总览共用 overview 的缓存（30 分钟；refresh 两次全量至少间隔 60 秒）。"""
    need_acc(acc_id, "aws")
    return await run(overview.aws_full, acc_id, refresh)


# ---------------- AWS: Lightsail / CloudFront / 配额 ----------------
@router.get("/api/accounts/{acc_id}/lightsail/options")
async def ls_opts(acc_id: int, region: str = None):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id, region).ls_options)


@router.post("/api/accounts/{acc_id}/lightsail/create")
async def ls_create(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    await guarded(acc_id, "ls_create", body, body.get("region"))
    c = dict(body, user_data=cloudinit.resolve_script(body))
    return _created(acc_id, await run(services.provider(acc_id, body.get("region")).ls_create, c), body.get("region"))


@router.get("/api/accounts/{acc_id}/cloudfront")
async def cf_list(acc_id: int):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id).cf_list)


@router.post("/api/accounts/{acc_id}/cloudfront")
async def cf_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    p, op = services.provider(acc_id), body.get("op")
    if op == "create":
        try:   # v1.5：可选 price_class / compress / cache_mode，不传时与 v1.4 行为一致
            return await run(p.cf_create, body.get("origin") or body.get("origin_domain") or "", body.get("comment", ""),
                             body.get("origin_protocol", "http-only"), body.get("price_class") or "all",
                             body.get("compress", True) not in (False, "false", "0", 0), body.get("cache_mode") or "disabled")
        except ValueError as e:
            raise HTTPException(400, str(e))
    if op in ("enable", "disable"):
        return await run(p.cf_set_enabled, body["id"], op == "enable")
    if op == "delete":
        return await run(p.cf_delete, body["id"])
    raise HTTPException(400, msg("err.invalid_op"))


_quota_cache = {}


@router.get("/api/accounts/{acc_id}/quotas")
async def quotas(acc_id: int, refresh: bool = False):
    need_acc(acc_id, "aws")
    c = _quota_cache.get(acc_id)
    if c and not refresh and time.time() - c["ts"] < 6 * 3600:   # 6 小时缓存，避免限流
        return c["data"]
    data = await run(services.provider(acc_id).quotas)
    data["updated_at"] = services.now_local().strftime("%Y-%m-%d %H:%M")
    _quota_cache[acc_id] = {"ts": time.time(), "data": data}
    return data


@router.get("/api/accounts/{acc_id}/recycle")
async def recycle(acc_id: int, region: str = None):
    need_acc(acc_id, "aws")
    return await run(services.recycle_estimate, acc_id, region)


# ---------------- AWS CloudFront：缓存刷新 / 编辑配置 / 启停 / 套餐 / 删除 ----------------
@router.post("/api/accounts/{acc_id}/cloudfront/invalidate")
async def cf_invalidate(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    did = body.get("distribution_id") or body.get("id")
    if not did:
        raise HTTPException(400, msg("err.missing_distribution"))
    paths = body.get("paths") or []
    if isinstance(paths, str):
        paths = [x for x in paths.replace(",", "\n").split("\n")]
    try:
        return await run(services.provider(acc_id).cf_invalidate, did, paths)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/accounts/{acc_id}/cloudfront/toggle")
async def cf_toggle(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    r = await run(services.provider(acc_id).cf_set_enabled, body["distribution_id"], bool(body.get("enabled")))
    return dict(r, message=f"分发已{'启用' if body.get('enabled') else '停用'}，部署约需几分钟")


@router.get("/api/accounts/{acc_id}/cloudfront/{dist_id}/config")
async def cf_config(acc_id: int, dist_id: str):
    need_acc(acc_id, "aws")
    return await run(services.provider(acc_id).cf_get_config, dist_id)


@router.put("/api/accounts/{acc_id}/cloudfront/{dist_id}")
async def cf_update(acc_id: int, dist_id: str, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    try:
        return await run(services.provider(acc_id).cf_update, dist_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/accounts/{acc_id}/cloudfront/plan")
async def cf_plan(acc_id: int, body: dict = Body(...)):
    """切换 CloudFront 包月套餐（计费操作）：付费套餐需 confirm=true。"""
    need_acc(acc_id, "aws")
    tier = (body.get("plan_tier") or body.get("tier") or "").strip().upper()
    from ..providers.aws_provider import CF_PLANS
    if tier not in CF_PLANS:
        raise HTTPException(400, msg("err.cf_plan_only", plans=" / ".join(CF_PLANS)))
    if CF_PLANS[tier]["paid"] and not body.get("confirm"):
        raise HTTPException(400, msg("err.cf_plan_paid", tier=tier, price=CF_PLANS[tier]["price"]))
    try:
        return await run(services.provider(acc_id).cf_set_plan, body["distribution_id"], tier)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/accounts/{acc_id}/cloudfront/{dist_id}")
async def cf_delete_v15(acc_id: int, dist_id: str, confirm: bool = False):
    """删除分发（需 confirm=true）。已停用且 Deployed：直接删除；
    仍启用或部署中：创建后台任务，先停用并等待部署完成（Deployed）再删除，否则 AWS 会拒绝。"""
    need_acc(acc_id, "aws")
    if not confirm:
        raise HTTPException(400, msg("err.cf_delete_confirm"))
    st = await run(services.provider(acc_id).cf_state, dist_id)
    if not st["enabled"] and st["status"] == "Deployed":
        await run(services.provider(acc_id).cf_delete, dist_id)
        return {"ok": True, "deleted": True}
    tid = tasks.create_task("cf_delete", acc_id, {"instance_id": dist_id, "name": dist_id, "distribution_id": dist_id})
    return {"ok": True, "deleted": False, "task_id": tid,
            "message": "分发仍在启用或部署中：已创建后台任务，先停用并等待部署完成后自动删除（通常 5~20 分钟）"}


# ================= 19. Lightsail 静态 IP / 防火墙 =================
@router.get("/api/accounts/{acc_id}/lightsail/static-ips")
async def ls_ips(acc_id: int, region: str = None):
    need_acc(acc_id, "aws")
    return await call(P(acc_id, region).ls_static_ips)


@router.post("/api/accounts/{acc_id}/lightsail/static-ips")
async def ls_ip_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    op, p = body.get("op"), P(acc_id, body.get("region"))
    if op == "allocate":
        _req(body, "name")
        return await call(p.ls_allocate_ip, body["name"], body.get("instance") or None)
    if op == "attach":
        _req(body, "name", "instance")
        return await call(p.ls_attach_ip, body["name"], body["instance"])
    if op == "detach":
        _req(body, "name")
        return await call(p.ls_detach_ip, body["name"])
    if op == "release":
        _req(body, "name")
        return await call(p.ls_release_ip, body["name"])
    raise HTTPException(400, msg("err.op_invalid"))


@router.get("/api/accounts/{acc_id}/lightsail/ports")
async def ls_ports(acc_id: int, instance: str, region: str = None):
    need_acc(acc_id, "aws")
    return await call(P(acc_id, region).ls_ports, instance)


@router.post("/api/accounts/{acc_id}/lightsail/ports")
async def ls_port_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    _req(body, "instance")
    proto = str(body.get("protocol") or "tcp").lower()
    try:
        a, b = int(body.get("from_port")), int(body.get("to_port") or body.get("from_port"))
    except (TypeError, ValueError):
        raise HTTPException(400, msg("err.port_required"))
    if not (0 <= a <= b <= 65535):
        raise HTTPException(400, msg("err.port_range_invalid"))
    p = P(acc_id, body.get("region"))
    if body.get("op") == "close":
        return await call(p.ls_close_port, body["instance"], proto, a, b)
    cidrs = [c.strip() for c in str(body.get("cidrs") or "0.0.0.0/0").replace("，", ",").split(",") if c.strip()]
    for c in cidrs:
        _public_guard("ingress", proto, c, "1-65535" if proto == "all" else f"{a}-{b}", body.get("confirm_public"))
    return await call(p.ls_open_port, body["instance"], proto, a, b, cidrs)
