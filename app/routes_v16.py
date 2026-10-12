"""v1.6 接口：重装系统、块存储卷、区域订阅、附加 IP / 预留 IP / 辅助网卡、IP 质量、账号类型与停用、
Azure 磁盘、免费 AMD 下行 500Mbps、对象存储、Lightsail 静态 IP 与防火墙、免费额度体检。
在 main.py 末尾导入（复用 need_acc / run / guarded）。耗时或会停机的操作走后台任务。"""
import asyncio
import json
import os
import tempfile
import time

from fastapi import Body, HTTPException, Request

from . import core, extras, services, tasks
from .providers import greencloud_provider as gcp  # greencloud
from .main import _public_guard, app, guarded, need_acc, run

OBJ_MAX = 100 * 1024 * 1024   # 面板中转上传单个对象上限 100MB


async def call(fn, *a, **kw):
    try:
        return await run(fn, *a, **kw)
    except (RuntimeError, ValueError, KeyError) as e:
        raise HTTPException(400, str(e).strip("'\"")[:400])


def P(acc_id, region=None):
    return services.provider(acc_id, region)


def _req(body, *keys):
    for k in keys:
        if not str(body.get(k) or "").strip():
            raise HTTPException(400, f"缺少参数：{k}")


# ================= 3. 重装系统（三家云，后台任务） =================
@app.post("/api/accounts/{acc_id}/instances/reinstall")
async def reinstall(acc_id: int, body: dict = Body(...)):
    acc = need_acc(acc_id)
    gcp.check_op(acc, "reinstall")  # greencloud
    _req(body, "instance_id")
    if not body.get("confirm"):
        raise HTTPException(400, "重装会清空系统盘全部数据，需确认")
    if acc["provider"] == "aws" and body.get("kind", "vm") != "vm":
        raise HTTPException(400, "Lightsail 不支持重装系统，可删除后重建")
    if acc["provider"] == "oci":
        await guarded(acc_id, "bootvol", {"size_gb": body.get("disk_gb"), **body}, body.get("region"))
    keys = ("instance_id", "region", "name", "os", "os_version", "disk_gb", "password_login", "ssh_key", "kind")
    tid = tasks.create_task("reinstall", acc_id, {k: body.get(k) for k in keys})
    return {"ok": True, "task_id": tid}


# ================= OCI 流量（本区域所有实例本月出站 / 入站） =================
@app.get("/api/accounts/{acc_id}/oci/traffic-summary")
async def oci_traffic_summary(acc_id: int, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).traffic_summary)


# ================= 6. OCI 块存储卷 =================
@app.get("/api/accounts/{acc_id}/oci/volumes")
async def oci_volumes(acc_id: int, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).volumes)


@app.post("/api/accounts/{acc_id}/oci/volumes")
async def oci_volume_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    op, region = body.get("op"), body.get("region")
    p = P(acc_id, region)
    if op == "create":
        await guarded(acc_id, "volume", {"size_gb": body.get("size_gb"), **body}, region)
        return await call(p.create_volume, body.get("name"), body.get("size_gb") or 50, body.get("vpus_per_gb", 10),
                          body.get("instance_id") or None)
    if op == "attach":
        _req(body, "volume_id", "instance_id")
        return await call(p.attach_volume, body["volume_id"], body["instance_id"])
    if op == "detach":
        _req(body, "attachment_id")
        return await call(p.detach_volume, body["attachment_id"])
    if op == "update":
        _req(body, "volume_id")
        if body.get("size_gb"):
            await guarded(acc_id, "volume", body, region)
        r = await call(p.update_volume, body["volume_id"], body.get("size_gb"), body.get("vpus_per_gb"))
        if r.get("expanded") and body.get("grow") and body.get("instance_id"):
            r["grow"] = await call(p.grow_fs, body["instance_id"], False)
        return r
    if op == "delete":
        _req(body, "volume_id")
        if not body.get("confirm"):
            raise HTTPException(400, "删除块存储卷不可恢复，需确认")
        return await call(p.delete_volume, body["volume_id"])
    if op == "grow":   # 引导卷 / 数据卷扩容后扩展分区（Run Command 固定脚本）
        _req(body, "instance_id")
        return await call(p.grow_fs, body["instance_id"], body.get("root", True))
    raise HTTPException(400, "op 无效")


# ================= 7. OCI 区域订阅 =================
@app.get("/api/accounts/{acc_id}/oci/region-subscriptions")
async def oci_region_subs(acc_id: int):
    need_acc(acc_id, "oci")
    return await call(P(acc_id).region_subscriptions)


@app.post("/api/accounts/{acc_id}/oci/region-subscriptions")
async def oci_region_subscribe(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    if not body.get("confirm"):
        raise HTTPException(400, "订阅区域不可撤销，需确认")
    r = await call(P(acc_id).subscribe_region, body.get("region_key"))
    services.drop_provider_cache(acc_id)
    return r


# ================= 8. OCI 附加 IP / 辅助网卡 / 预留 IP =================
@app.get("/api/accounts/{acc_id}/oci/ips")
async def oci_ips(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).ip_overview, instance_id)


@app.post("/api/accounts/{acc_id}/oci/ips")
async def oci_ip_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    op, p = body.get("op"), P(acc_id, body.get("region"))
    yes = body.get("with_public", True) not in (False, "false", 0, "0")
    if op == "add_secondary":
        _req(body, "instance_id")
        return await call(p.add_secondary_ip, body["instance_id"], body.get("vnic_id"), yes)
    if op == "delete_private":
        _req(body, "private_ip_id")
        return await call(p.delete_private_ip, body["private_ip_id"])
    if op == "attach_vnic":
        _req(body, "instance_id")
        return await call(p.attach_vnic, body["instance_id"], body.get("subnet_id"), yes)
    if op == "detach_vnic":
        _req(body, "attachment_id")
        return await call(p.detach_vnic, body["attachment_id"])
    if op == "create_reserved":
        await guarded(acc_id, "reserved_ip", body, body.get("region"))
        return await call(p.create_reserved_ip, body.get("name"))
    if op == "assign_reserved":
        _req(body, "public_ip_id")
        if not body.get("instance_id") and not body.get("private_ip_id"):
            raise HTTPException(400, "缺少 instance_id")
        r = await call(p.assign_reserved_ip, body["public_ip_id"], body.get("instance_id"), body.get("private_ip_id"))
        if body.get("instance_id") and body.get("ip"):
            r["dns"] = await run(extras.dns_sync, acc_id, body["instance_id"], body["ip"])
        return r
    if op == "unassign_reserved":
        _req(body, "public_ip_id")
        return await call(p.unassign_reserved_ip, body["public_ip_id"], body.get("restore_ephemeral", True))
    if op == "delete_reserved":
        _req(body, "public_ip_id")
        return await call(p.delete_reserved_ip, body["public_ip_id"])
    raise HTTPException(400, "op 无效")


# ================= 9. IP 质量 =================
@app.get("/api/ip-quality")
async def ip_quality(ip: str):
    try:
        return await run(extras.ip_quality, ip.strip())
    except ValueError:
        raise HTTPException(400, "IP 格式错误")


# ================= 11. 账号类型 / 开户天数 / 停用 =================
@app.get("/api/accounts/{acc_id}/account-type")
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
    elif gcp.is_gc(acc):  # greencloud
        r = dict(gcp.ACCOUNT_TYPE)  # greencloud
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


@app.post("/api/accounts/{acc_id}/disable")
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


# ================= 14. Azure 磁盘 =================
@app.get("/api/accounts/{acc_id}/azure/disks")
async def az_disks(acc_id: int, instance_id: str):
    need_acc(acc_id, "azure")
    return await call(P(acc_id).disks, instance_id)


@app.post("/api/accounts/{acc_id}/azure/disks")
async def az_disk_update(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "azure")
    _req(body, "instance_id", "disk_id")
    return await call(P(acc_id).update_disk, body["instance_id"], body["disk_id"], body.get("size_gb") or None,
                      body.get("sku") or None, body.get("tier") or None)


# ================= Azure Foundry（AI Services） =================
@app.get("/api/accounts/{acc_id}/azure/foundry")
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


@app.post("/api/accounts/{acc_id}/azure/foundry")
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
            raise HTTPException(400, "查看密钥需确认")
        return await call(prov.foundry_keys, body.get("resource_id"))
    if op == "delete_deployment":
        if not body.get("confirm"):
            raise HTTPException(400, "需确认")
        return await call(prov.foundry_delete_deployment, body.get("resource_id"), body.get("deployment"))
    if op == "delete_resource":
        if not body.get("confirm"):
            raise HTTPException(400, "需确认")
        return await call(prov.foundry_delete_resource, body.get("resource_id"))
    raise HTTPException(400, "未知操作")


# ================= 15. 免费 AMD 下行 500Mbps =================
@app.get("/api/accounts/{acc_id}/oci/500m")
async def oci_500m_status(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).nlb_status, instance_id)


@app.post("/api/accounts/{acc_id}/oci/500m")
async def oci_500m(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    _req(body, "instance_id")
    on = body.get("enable", True) not in (False, "false", 0, "0")
    if on and not body.get("confirm"):
        raise HTTPException(400, "开启后入口 IP 会变成负载均衡器的公网 IP，需确认")
    tid = tasks.create_task("net500m", acc_id, {"instance_id": body["instance_id"], "region": body.get("region"),
                                                "name": body.get("name"), "enable": on, "ssh_port": int(body.get("ssh_port") or 22)})
    return {"ok": True, "task_id": tid}


# ================= 18. OCI 对象存储 =================
@app.get("/api/accounts/{acc_id}/oci/buckets")
async def oci_buckets(acc_id: int, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).buckets)


@app.post("/api/accounts/{acc_id}/oci/buckets")
async def oci_bucket_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    p = P(acc_id, body.get("region"))
    if body.get("op") == "create":
        return await call(p.create_bucket, body.get("name"), bool(body.get("public")))
    if body.get("op") == "delete":
        if not body.get("confirm"):
            raise HTTPException(400, "删除 Bucket 需确认")
        return await call(p.delete_bucket, body.get("name"))
    raise HTTPException(400, "op 无效")


@app.get("/api/accounts/{acc_id}/oci/objects")
async def oci_objects(acc_id: int, bucket: str, prefix: str = None, start: str = None, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).objects, bucket, prefix, start)


@app.put("/api/accounts/{acc_id}/oci/objects")
async def oci_object_put(acc_id: int, bucket: str, name: str, request: Request, region: str = None):
    """原始请求体即文件内容（不依赖 multipart）。先落到临时文件，超过 100MB 拒绝。"""
    need_acc(acc_id, "oci")
    size = int(request.headers.get("content-length") or 0)
    if size > OBJ_MAX:
        raise HTTPException(413, "单个文件最大 100MB，更大的文件请用 OCI 控制台或 CLI 分片上传")
    fd, path = tempfile.mkstemp(prefix="tc-up-")
    total = 0
    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                total += len(chunk)
                if total > OBJ_MAX:
                    raise HTTPException(413, "单个文件最大 100MB")
                f.write(chunk)

        def put():
            with open(path, "rb") as f:
                return P(acc_id, region).put_object(bucket, name, f)
        r = await call(put)
        return dict(r, size=total)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@app.post("/api/accounts/{acc_id}/oci/objects")
async def oci_object_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    _req(body, "bucket", "name")
    p = P(acc_id, body.get("region"))
    if body.get("op") == "url":
        return await call(p.object_url, body["bucket"], body["name"], body.get("minutes") or 60)
    if body.get("op") == "delete":
        return await call(p.delete_object, body["bucket"], body["name"])
    raise HTTPException(400, "op 无效")


# ================= 19. Lightsail 静态 IP / 防火墙 =================
@app.get("/api/accounts/{acc_id}/lightsail/static-ips")
async def ls_ips(acc_id: int, region: str = None):
    need_acc(acc_id, "aws")
    return await call(P(acc_id, region).ls_static_ips)


@app.post("/api/accounts/{acc_id}/lightsail/static-ips")
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
    raise HTTPException(400, "op 无效")


@app.get("/api/accounts/{acc_id}/lightsail/ports")
async def ls_ports(acc_id: int, instance: str, region: str = None):
    need_acc(acc_id, "aws")
    return await call(P(acc_id, region).ls_ports, instance)


@app.post("/api/accounts/{acc_id}/lightsail/ports")
async def ls_port_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "aws")
    _req(body, "instance")
    proto = str(body.get("protocol") or "tcp").lower()
    try:
        a, b = int(body.get("from_port")), int(body.get("to_port") or body.get("from_port"))
    except (TypeError, ValueError):
        raise HTTPException(400, "请填写端口")
    if not (0 <= a <= b <= 65535):
        raise HTTPException(400, "端口范围无效")
    p = P(acc_id, body.get("region"))
    if body.get("op") == "close":
        return await call(p.ls_close_port, body["instance"], proto, a, b)
    cidrs = [c.strip() for c in str(body.get("cidrs") or "0.0.0.0/0").replace("，", ",").split(",") if c.strip()]
    for c in cidrs:
        _public_guard("ingress", proto, c, "1-65535" if proto == "all" else f"{a}-{b}", body.get("confirm_public"))
    return await call(p.ls_open_port, body["instance"], proto, a, b, cidrs)


# ================= 20. 免费额度体检（全部 OCI 账号） =================
@app.get("/api/oci/free-check")
async def oci_free_check():
    accs = [a for a in core.list_accounts() if a["provider"] == "oci" and not a.get("disabled")]
    sem = asyncio.Semaphore(5)

    async def one(a):
        async with sem:
            try:
                fc, fm, basis = core.oci_a1_free(a["id"])
                r = await asyncio.wait_for(run(P(a["id"]).free_check, (fc, fm)), 60)
                return dict(r, account_id=a["id"], name=a["name"], a1_basis=basis)
            except Exception as e:
                return {"account_id": a["id"], "name": a["name"], "error": str(e)[:200]}
    return await asyncio.gather(*[one(a) for a in accs])
