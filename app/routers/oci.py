"""OCI：IPv6、引导卷、安全列表 / 安全组规则、配额、流量、网络、系统版本、创建 / 抢机、块存储、区域订阅、附加 IP、免费 AMD 500Mbps、对象存储、免费额度体检。"""
import asyncio
import os
import tempfile
import time

from fastapi import APIRouter, Body, HTTPException, Request

from .. import cloudinit, core, dns, security, services, tasks
from .common import _created, _public_guard, _req, call, client_ip, guarded, need_acc, P, PUBLIC_CIDRS, run

router = APIRouter()


# ---------------- OCI ----------------
@router.post("/api/accounts/{acc_id}/oci/ipv6")
def oci_ipv6(acc_id: int, body: dict = Body(...)):
    """一键 IPv6 全链路，可能需要几分钟，走后台任务。"""
    need_acc(acc_id, "oci")
    return {"ok": True, "task_id": tasks.create_task("ipv6", acc_id, {k: body.get(k) for k in ("instance_id", "region", "name")})}


@router.get("/api/accounts/{acc_id}/oci/boot-volume")
async def oci_bv(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await run(services.provider(acc_id, region).boot_volume, instance_id)


@router.post("/api/accounts/{acc_id}/oci/boot-volume")
async def oci_bv_update(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    await guarded(acc_id, "bootvol", body, body.get("region"))
    prov = services.provider(acc_id, body.get("region"))
    try:
        r = await run(prov.update_boot_volume, body["instance_id"], body.get("size_gb") or None, body.get("vpus_per_gb"))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    if body.get("size_gb") and body.get("grow") not in (None, False, "false", 0, "0"):   # v1.6：扩容后自动扩根分区
        await asyncio.sleep(0)
        r["grow"] = await run(prov.grow_fs, body["instance_id"], True)
    return r


@router.get("/api/accounts/{acc_id}/oci/security")
async def oci_sec(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await run(services.provider(acc_id, region).security_rules, instance_id)


@router.post("/api/accounts/{acc_id}/oci/security")
async def oci_sec_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    p, op = services.provider(acc_id, body.get("region")), body.get("op")
    if op == "add":
        if body.get("direction") not in ("ingress", "egress") or body.get("protocol", "").lower() not in ("tcp", "udp", "icmp", "icmpv6", "all"):
            raise HTTPException(400, "参数无效")
        _public_guard(body["direction"], body["protocol"].lower(), body.get("cidr", ""), body.get("port"), body.get("confirm_public"))
        try:
            return await run(p.add_security_rule, body["sl_id"], body["direction"], body["protocol"], body["cidr"],
                             body.get("port"), body.get("desc"))
        except ValueError as e:
            raise HTTPException(400, f"CIDR 无效：{e}")
    if op == "remove":
        return await run(p.remove_security_rule, body["sl_id"], body["direction"], int(body["idx"]))
    if op == "add_ports":
        # 放行指定端口（入站）：必须填写端口；来源默认 0.0.0.0/0，需 confirm_public
        protos = [x for x in (body.get("protocols") or ["tcp"]) if x in ("tcp", "udp")]
        cidr = (body.get("cidr") or "0.0.0.0/0").strip()
        if not protos or not body.get("instance_id"):
            raise HTTPException(400, "参数无效")
        if str(body.get("ports") or "").strip() == "":
            raise HTTPException(400, "请填写端口，如 80, 443, 8000-8100")
        from ..providers.oci_provider import OCIProvider
        try:
            ranges = OCIProvider.parse_ports(body["ports"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        _public_guard("ingress", protos[0], cidr, body["ports"], body.get("confirm_public"))
        added = skipped = 0
        for pr in protos:
            try:
                res = await run(p.add_security_rules, body["instance_id"], body.get("sl_id"), "ingress", pr, cidr, ranges,
                                (body.get("desc") or "").strip() or None)
            except ValueError as e:
                raise HTTPException(400, str(e))
            added += res.get("added", 0); skipped += res.get("skipped", 0)
        return {"ok": True, "added": added, "skipped": skipped}
    raise HTTPException(400, "无效操作")


@router.get("/api/accounts/{acc_id}/oci/limits")
async def oci_limits(acc_id: int, region: str = None):
    need_acc(acc_id, "oci")
    fc, fm, basis = core.oci_a1_free(acc_id)
    r = await run(services.provider(acc_id, region).limits, (fc, fm))
    return dict(r, a1_basis=basis)


@router.get("/api/accounts/{acc_id}/oci/traffic")
async def oci_traffic(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await run(services.provider(acc_id, region).traffic, instance_id)


@router.post("/api/accounts/{acc_id}/oci/network")
def oci_network(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    return {"ok": True, "task_id": tasks.create_task("ensure_network", acc_id, {"region": body.get("region"), "instance_id": "-"})}


_OSV_CACHE = {}


OSV_TTL = 6 * 3600


@router.get("/api/accounts/{acc_id}/oci/os-versions")
async def oci_os_versions(acc_id: int, shape: str = None, region: str = None):
    """v1.5：创建/抢机表单「系统版本」下拉，按规格列平台镜像版本（A1=aarch64，E2=x86），缓存 6 小时。"""
    acc = need_acc(acc_id, "oci")
    key = (acc_id, region or acc.get("region"), shape or "")
    hit = _OSV_CACHE.get(key)
    if hit and time.time() - hit[0] < OSV_TTL:
        return hit[1]
    data = await run(services.provider(acc_id, region).os_versions, shape)
    _OSV_CACHE[key] = (time.time(), data)
    return data


@router.get("/api/accounts/{acc_id}/oci/ads")
async def oci_ads(acc_id: int, region: str = None):
    need_acc(acc_id, "oci")
    return await run(services.provider(acc_id, region).availability_domains)


@router.post("/api/accounts/{acc_id}/oci/create")
async def oci_create(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    await guarded(acc_id, "create", body, body.get("region"))
    c = dict(body["create"], script=cloudinit.resolve_script(body["create"]))
    return _created(acc_id, await run(services.provider(acc_id, body.get("region")).create_instance, c), body.get("region"))


@router.post("/api/accounts/{acc_id}/oci/snatch")
async def oci_snatch(acc_id: int, body: dict = Body(...)):
    """批量抢机：account_ids 可同时给多个租户各起一个任务（各自用自己账号的默认区域或指定区域）。"""
    need_acc(acc_id, "oci")
    await guarded(acc_id, "create", body, body.get("region"))
    interval = max(30, int(body.get("interval") or 60))   # 下限 30s，防止被风控
    ids = [int(x) for x in (body.get("account_ids") or [acc_id])]
    out = []
    for aid in ids:
        need_acc(aid, "oci")
        region = body.get("region") if aid == acc_id else None
        out.append(tasks.create_task("snatch", aid, {"region": region, "create": body["create"], "interval": interval,
                                                     "max_attempts": int(body.get("max_attempts") or 0)}))
    return {"ok": True, "task_id": out[0], "task_ids": out}


def _sec_rule_args(r):
    direction = (r.get("direction") or "ingress").strip().lower()
    protocol = (r.get("protocol") or "").strip().lower()
    cidr = (r.get("cidr") or r.get("source") or r.get("destination") or "").strip()
    if direction not in ("ingress", "egress"):
        raise HTTPException(400, "direction 只能是 ingress / egress")
    if protocol not in ("tcp", "udp", "icmp", "icmpv6", "all"):
        raise HTTPException(400, "protocol 只能是 tcp / udp / icmp / icmpv6 / all")
    if not cidr:
        raise HTTPException(400, "请填写来源 / 目标 CIDR")
    return direction, protocol, cidr


def _sec_target(instance_id, subnet_id):
    """安全组规则的目标：subnet_id（新，Web 安全组页按子网）优先；instance_id（旧，App 仍在用）兼容。"""
    subnet_id, instance_id = (subnet_id or "").strip() or None, (instance_id or "").strip() or None
    if subnet_id and not subnet_id.startswith("ocid1.subnet."):
        raise HTTPException(400, "subnet_id 不是子网 OCID")
    if not subnet_id and not instance_id:
        raise HTTPException(400, "请选择子网（subnet_id）或实例（instance_id）")
    return instance_id, subnet_id


@router.get("/api/accounts/{acc_id}/oci/security-subnets")
async def oci_sec_subnets(acc_id: int, region: str = None):
    """安全组页子网下拉：子网（VCN / 名称 / CIDR）+ 子网里的实例名 + 实例 VNIC 上挂的 NSG（只读）。"""
    need_acc(acc_id, "oci")
    return await run(services.provider(acc_id, region).security_subnets)


def _rename_name(body):
    name = str((body or {}).get("display_name") or "").strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    if len(name) > 255:
        raise HTTPException(400, "名称最多 255 个字符")
    return name


async def _oci_rename(req, acc_id, kind, ocid, body):
    """子网 / VCN 改名（只改 display_name，不影响实例、IP、安全规则）。写一条带新旧名的审计记录。"""
    need_acc(acc_id, "oci")
    prefix, label = {"subnet": ("ocid1.subnet.", "子网"), "vcn": ("ocid1.vcn.", "VCN")}[kind]
    ocid = (ocid or "").strip()
    if not ocid.startswith(prefix):
        raise HTTPException(400, f"{kind}_id 不是{label} OCID")
    name = _rename_name(body)
    p = services.provider(acc_id, (body or {}).get("region"))
    try:
        r = await run(p.rename_subnet if kind == "subnet" else p.rename_vcn, ocid, name)
    except HTTPException:
        raise
    except Exception as e:      # ServiceError（404 / 无权限等）给出明确原因
        raise HTTPException(400, str(getattr(e, "message", None) or e)[:300])
    try:
        security.audit(client_ip(req), getattr(req.state, "actor", "session"), f"oci-{kind}-rename",
                       f"账号 {acc_id} {label} …{ocid[-8:]}：{r.get('old_name') or '-'} → {r.get('name')}")
    except Exception:
        pass
    return {"ok": True, **r}


@router.patch("/api/accounts/{acc_id}/oci/subnets/{subnet_id}")
async def oci_subnet_rename(req: Request, acc_id: int, subnet_id: str, body: dict = Body(default={})):
    return await _oci_rename(req, acc_id, "subnet", subnet_id, body)


@router.patch("/api/accounts/{acc_id}/oci/vcns/{vcn_id}")
async def oci_vcn_rename(req: Request, acc_id: int, vcn_id: str, body: dict = Body(default={})):
    return await _oci_rename(req, acc_id, "vcn", vcn_id, body)


@router.get("/api/accounts/{acc_id}/security-rules")
async def sec_rules(acc_id: int, instance_id: str = None, region: str = None, subnet_id: str = None):
    need_acc(acc_id, "oci")
    iid, sid = _sec_target(instance_id, subnet_id)
    try:
        return await run(services.provider(acc_id, region).security_rules_flat, iid, sid)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/accounts/{acc_id}/security-rules")
async def sec_rule_add(acc_id: int, body: dict = Body(...)):
    """新增规则。ports 支持 "80, 443, 8000-8100"（批量，每段一条规则，已存在的跳过）。
    来源为 0.0.0.0/0 或 ::/0 时需 confirm_public=true（前端显示警告并二次确认）；
    对公网放行全部端口（协议 all，或 TCP/UDP 不限端口 / 1-65535）不支持。"""
    from ..providers.oci_provider import OCIProvider
    need_acc(acc_id, "oci")
    r = body.get("rule") if isinstance(body.get("rule"), dict) else body
    direction, protocol, cidr = _sec_rule_args(r)
    ports = r.get("ports")
    if ports in (None, "") and (r.get("port_min") or r.get("port_max")):
        ports = f"{r.get('port_min') or r.get('port_max')}-{r.get('port_max') or r.get('port_min')}"
    try:
        ranges = OCIProvider.parse_ports(ports) if protocol in ("tcp", "udp") and ports not in (None, "") else []
    except ValueError as e:
        raise HTTPException(400, str(e))
    public = cidr.replace(" ", "") in PUBLIC_CIDRS
    if public and direction == "ingress":
        if protocol == "all" or (protocol in ("tcp", "udp") and (not ranges or any(a <= 1 and b >= 65535 for a, b in ranges))):
            raise HTTPException(400, "不支持对 0.0.0.0/0（或 ::/0）放行全部端口，请填写具体端口")
        if not body.get("confirm_public"):
            raise HTTPException(409, {"msg": "来源为 0.0.0.0/0：将对整个互联网开放", "public_warning": True})
    iid, sid = _sec_target(body.get("instance_id"), body.get("subnet_id"))
    try:
        res = await run(services.provider(acc_id, body.get("region")).add_security_rules, iid, body.get("sl_id"),
                        direction, protocol, cidr, ranges, (r.get("description") or r.get("desc") or "").strip() or None, sid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **res}


@router.delete("/api/accounts/{acc_id}/security-rules")
async def sec_rule_del(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    r = body.get("rule") if isinstance(body.get("rule"), dict) else body
    direction, protocol, cidr = _sec_rule_args(r)
    iid, sid = _sec_target(body.get("instance_id"), body.get("subnet_id"))
    try:
        return await run(services.provider(acc_id, body.get("region")).delete_security_rule_match, iid,
                         body.get("sl_id"), direction, protocol, cidr, r.get("port_min"), r.get("port_max"), sid)
    except (LookupError, ValueError) as e:
        raise HTTPException(404 if isinstance(e, LookupError) else 400, str(e))


# ---------------- OCI：删除 IPv6（二次确认） ----------------
@router.post("/api/accounts/{acc_id}/oci/ipv6/delete")
async def oci_ipv6_delete(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    if not body.get("confirm"):
        raise HTTPException(400, "删除 IPv6 需确认")
    try:
        r = await run(services.provider(acc_id, body.get("region")).delete_ipv6, body["instance_id"])
    except LookupError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, **r}


OBJ_MAX = 100 * 1024 * 1024   # 面板中转上传单个对象上限 100MB


# ================= OCI 流量（本区域所有实例本月出站 / 入站） =================
@router.get("/api/accounts/{acc_id}/oci/traffic-summary")
async def oci_traffic_summary(acc_id: int, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).traffic_summary)


# ================= 6. OCI 块存储卷 =================
@router.get("/api/accounts/{acc_id}/oci/volumes")
async def oci_volumes(acc_id: int, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).volumes)


@router.post("/api/accounts/{acc_id}/oci/volumes")
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
@router.get("/api/accounts/{acc_id}/oci/region-subscriptions")
async def oci_region_subs(acc_id: int):
    need_acc(acc_id, "oci")
    return await call(P(acc_id).region_subscriptions)


@router.post("/api/accounts/{acc_id}/oci/region-subscriptions")
async def oci_region_subscribe(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    if not body.get("confirm"):
        raise HTTPException(400, "订阅区域不可撤销，需确认")
    r = await call(P(acc_id).subscribe_region, body.get("region_key"))
    services.drop_provider_cache(acc_id)
    return r


# ================= 8. OCI 附加 IP / 辅助网卡 / 预留 IP =================
@router.get("/api/accounts/{acc_id}/oci/ips")
async def oci_ips(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).ip_overview, instance_id)


@router.post("/api/accounts/{acc_id}/oci/ips")
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
            r["dns"] = await run(dns.dns_sync, acc_id, body["instance_id"], body["ip"])
        return r
    if op == "unassign_reserved":
        _req(body, "public_ip_id")
        return await call(p.unassign_reserved_ip, body["public_ip_id"], body.get("restore_ephemeral", True))
    if op == "delete_reserved":
        _req(body, "public_ip_id")
        return await call(p.delete_reserved_ip, body["public_ip_id"])
    raise HTTPException(400, "op 无效")


# ================= 15. 免费 AMD 下行 500Mbps =================
@router.get("/api/accounts/{acc_id}/oci/500m")
async def oci_500m_status(acc_id: int, instance_id: str, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).nlb_status, instance_id)


@router.post("/api/accounts/{acc_id}/oci/500m")
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
@router.get("/api/accounts/{acc_id}/oci/buckets")
async def oci_buckets(acc_id: int, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).buckets)


@router.post("/api/accounts/{acc_id}/oci/buckets")
async def oci_bucket_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    p = P(acc_id, body.get("region"))
    bk_scan_invalidate(acc_id)          # Bucket 增删后保号检测结果作废
    if body.get("op") == "create":
        return await call(p.create_bucket, body.get("name"), bool(body.get("public")))
    if body.get("op") == "delete":
        if not body.get("confirm"):
            raise HTTPException(400, "删除 Bucket 需确认")
        return await call(p.delete_bucket, body.get("name"))
    raise HTTPException(400, "op 无效")


@router.get("/api/accounts/{acc_id}/oci/objects")
async def oci_objects(acc_id: int, bucket: str, prefix: str = None, start: str = None, region: str = None):
    need_acc(acc_id, "oci")
    return await call(P(acc_id, region).objects, bucket, prefix, start)


@router.put("/api/accounts/{acc_id}/oci/objects")
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


@router.post("/api/accounts/{acc_id}/oci/objects")
async def oci_object_op(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id, "oci")
    _req(body, "bucket", "name")
    p = P(acc_id, body.get("region"))
    if body.get("op") == "url":
        return await call(p.object_url, body["bucket"], body["name"], body.get("minutes") or 60)
    if body.get("op") == "delete":
        return await call(p.delete_object, body["bucket"], body["name"])
    raise HTTPException(400, "op 无效")


# ================= 20. 免费额度体检（全部 OCI 账号） =================
@router.get("/api/oci/free-check")
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


# ================= 18b. 保号账单（仅 PAYG） =================
# PAYG 账号对象存储标准层免费 10 GB：在主区域的私有标准层 bucket 里放一个约 11 GiB 的全零对象，
# 超出部分每月约 $0.02–0.03，让账号每月有一笔小额账单。上传是入网流量，不计费。
BK_GIB = 1024 ** 3
BK_MIN_GB, BK_MAX_GB, BK_DEFAULT_GB = 0.5, 20, 11      # 先检测已有存储后按「补足到约 11 GB」给默认值，所以下限放宽到 0.5
BK_FREE_HINT = "免费号 20GB 内不收费，无需操作"
BK_NOTE = ("会在主区域标准层私有 Bucket tricloud-billing-keep 里存放全零对象，让标准层总量（含已有 Bucket）补足到约 11 GB、超出 10 GB 免费额度，"
           "每月约 $0.02–0.03 账单；上传走入网流量，不计费，也不会产生出网流量。")


async def _bk_plan(acc_id):
    """复用账号类型缓存（core.oci_a1_free）：paid / free / unknown；未缓存时查一次并缓存。"""
    basis = core.oci_a1_free(acc_id)[2]
    if basis == "unknown":
        from . import accounts as _accounts
        try:
            await _accounts.account_type(acc_id, refresh=True)
        except Exception:
            pass
        basis = core.oci_a1_free(acc_id)[2]
    return basis


def _bk_last_task(acc_id):
    return core.q("SELECT * FROM tasks WHERE account_id=? AND type='billing_keep' ORDER BY id DESC LIMIT 1", (acc_id,), one=True)


def _bk_task_view(t):
    if not t:
        return None
    import json as _json
    try:
        res = _json.loads(t["result"]) if t.get("result") else {}
    except ValueError:
        res = {}
    return {"id": t["id"], "status": t["status"], "message": t["message"], "updated": t["updated"],
            "uploaded": int(res.get("uploaded") or 0), "total": int(res.get("total") or 0), "size": res.get("size")}


async def _bk_oci(fn, *a):
    try:
        return await call(fn, *a)
    except HTTPException:
        raise
    except Exception as e:      # oci.exceptions.ServiceError 等：给出明确原因而不是 500
        raise HTTPException(400, str(getattr(e, "message", None) or e)[:300])


BK_SCAN_TTL = 300           # 检测结果缓存 5 分钟（每次扫描 = 区域数×区间数 次 ListBuckets + Bucket 数 次 GetBucket）
_BK_SCAN = {}               # acc_id -> (ts, result)


def bk_scan_invalidate(acc_id):
    _BK_SCAN.pop(acc_id, None)


@router.get("/api/accounts/{acc_id}/oci/billing-keep/scan")
async def oci_billing_keep_scan(acc_id: int, refresh: bool = False):
    """先检测已有存储：所有已订阅区域的 Bucket 近似大小，按存储层汇总，并给出「已满足 / 还差 X GB」与补足大小。只读，缓存 5 分钟。"""
    need_acc(acc_id, "oci")
    hit = _BK_SCAN.get(acc_id)
    if hit and not refresh and time.time() - hit[0] < BK_SCAN_TTL:
        return dict(hit[1], cached=True, age=int(time.time() - hit[0]))
    r = await _bk_oci(P(acc_id).storage_scan)
    r["scanned_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    _BK_SCAN[acc_id] = (time.time(), r)
    return dict(r, cached=False, age=0)


@router.get("/api/accounts/{acc_id}/oci/billing-keep")
async def oci_billing_keep_status(acc_id: int):
    need_acc(acc_id, "oci")
    plan = await _bk_plan(acc_id)
    out = {"plan": plan, "eligible": plan == "paid", "note": BK_NOTE, "default_gb": BK_DEFAULT_GB,
           "min_gb": BK_MIN_GB, "max_gb": BK_MAX_GB, "task": _bk_task_view(_bk_last_task(acc_id))}
    if plan == "free":
        return dict(out, hint=BK_FREE_HINT)
    if plan != "paid":
        return dict(out, hint="未能识别账号类型（需 osp-gateway 读权限），无法确认是 PAYG 升级号，暂不开放")
    return dict(out, **(await _bk_oci(P(acc_id).billing_keep_status)))


@router.post("/api/accounts/{acc_id}/oci/billing-keep")
async def oci_billing_keep_start(acc_id: int, body: dict = Body(default={})):
    need_acc(acc_id, "oci")
    try:
        size_gb = float(body.get("size_gb") if body.get("size_gb") not in (None, "") else BK_DEFAULT_GB)
    except (TypeError, ValueError):
        raise HTTPException(400, "size_gb 需为数字")
    if not BK_MIN_GB <= size_gb <= BK_MAX_GB:
        raise HTTPException(400, f"size_gb 范围 {BK_MIN_GB:g}–{BK_MAX_GB:g}")
    plan = await _bk_plan(acc_id)
    if plan == "free":
        raise HTTPException(400, f"该账号是免费号：{BK_FREE_HINT}")
    if plan != "paid":
        raise HTTPException(400, "未能识别账号类型（需 osp-gateway 读权限），无法确认是 PAYG 升级号")
    if not body.get("confirm"):
        raise HTTPException(400, "会产生每月约 $0.02–0.03 的账单，需确认")
    t = _bk_last_task(acc_id)
    if t and t["status"] == "running":
        return {"ok": True, "task_id": t["id"], "running": True}
    st = await _bk_oci(P(acc_id).billing_keep_status)
    if st.get("exists"):
        return {"ok": True, "existed": True, "size": st["size"], "region": st["region"]}
    resume = None
    tv = _bk_task_view(t)
    if t and t["status"] in ("failed", "stopped", "interrupted"):
        import json as _json
        try:
            res = _json.loads(t["result"] or "{}")
        except ValueError:
            res = {}
        if res.get("upload_id") and res["upload_id"] in {u["upload_id"] for u in st.get("pending_uploads") or []}:
            resume = {"upload_id": res["upload_id"], "total": int(res.get("total") or 0)}
    total = int((resume or {}).get("total") or round(size_gb * BK_GIB))
    tid = tasks.create_task("billing_keep", acc_id, {"name": "保号账单", "size_bytes": total, "resume": resume})
    bk_scan_invalidate(acc_id)
    return {"ok": True, "task_id": tid, "total": total, "resumed": bool(resume),
            "resumed_from": tv["uploaded"] if resume and tv else 0}


@router.delete("/api/accounts/{acc_id}/oci/billing-keep")
async def oci_billing_keep_delete(acc_id: int, confirm: bool = False):
    need_acc(acc_id, "oci")
    if not confirm:
        raise HTTPException(400, "删除保号对象需确认")
    t = _bk_last_task(acc_id)
    if t and t["status"] == "running":
        raise HTTPException(409, "上传任务仍在运行，请先在任务里停止")
    bk_scan_invalidate(acc_id)
    return await _bk_oci(P(acc_id).billing_keep_delete)
