"""实例（三家云通用）：列表、开关机、换 IP、改配置、开放端口、改名、流量、重装系统、IP 质量。"""
import re

from fastapi import APIRouter, Body, HTTPException

from .. import core, dns, hostname, net, overview, services, tasks
from ..i18n import msg
from .common import _public_guard, _req, call, guarded, need_acc, run

router = APIRouter()


# ---------------- 实例（通用） ----------------
@router.get("/api/accounts/{acc_id}/instances")
async def instances(acc_id: int, region: str = None, kind: str = "vm"):
    need_acc(acc_id)
    return await run(services.list_instances, acc_id, region, kind)


@router.get("/api/accounts/{acc_id}/overview")
async def account_overview(acc_id: int, refresh: bool = False):
    """总览卡片：账号在所有有机器的区域里的实例数（AWS EC2+Lightsail 全区域 / OCI 订阅区域 / Azure 订阅级），带缓存。"""
    need_acc(acc_id)
    return await call(overview.summary, acc_id, refresh)


@router.post("/api/accounts/{acc_id}/instances/action")
async def inst_action(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id)
    act = body.get("action")
    if act not in ("start", "stop", "reboot", "terminate", "hard_reboot"):
        raise HTTPException(400, msg("err.invalid_op"))
    if act == "terminate" and not body.get("confirm"):
        raise HTTPException(400, msg("err.terminate_confirm"))
    return await run(services.instance_action, acc_id, body["instance_id"], act, body.get("region"), body.get("kind", "vm"),
                     bool(body.get("preserve_boot_volume")))


@router.post("/api/accounts/{acc_id}/instances/change-ip")
async def change_ip(acc_id: int, body: dict = Body(...)):
    acc = need_acc(acc_id)
    p = {"instance_id": body["instance_id"], "region": body.get("region"), "kind": body.get("kind", "vm"),
         "mode": body.get("mode", "auto"), "name": body.get("name")}
    raw = body.get("cidrs") or ""
    raw = ",".join(map(str, raw)) if isinstance(raw, list) else str(raw)
    cidrs = [c.strip() for c in raw.replace("，", ",").replace("\n", ",").split(",") if c.strip()]
    mr, qc = body.get("quality_max_risk"), str(body.get("quality_country") or "").strip()
    if mr not in (None, ""):   # v1.6：IP 质量条件（风险分上限 / 归属国家），走任务重复更换
        try:
            mr = int(mr)
            assert 0 <= mr <= 100
        except Exception:
            raise HTTPException(400, msg("err.risk_range"))
        p["quality_max_risk"] = mr
    if qc:
        if not re.fullmatch(r"[A-Za-z]{2}(\s*[,，]\s*[A-Za-z]{2})*", qc):
            raise HTTPException(400, msg("err.country_format"))
        p["quality_country"] = qc.upper().replace("，", ",")
    quality = "quality_max_risk" in p or "quality_country" in p
    if acc["provider"] == "oci" and not cidrs and not quality:   # OCI 换临时 IP 很快，同步返回
        r = await run(services.provider(acc_id, p["region"]).change_ip, p["instance_id"])
        r["dns"] = await run(dns.dns_sync, acc_id, p["instance_id"], r.get("new_ip"))
        core.ex("UPDATE monitors SET public_ip=?, fail_count=0 WHERE account_id=? AND instance_id=?",
                (r.get("new_ip"), acc_id, p["instance_id"]))
        tasks.record_ip_change(acc_id, p["instance_id"])
        return {"ok": True, **r}
    if cidrs:   # v1.4：以 ! 开头表示排除网段，可与普通网段混用
        try:
            net.split_cidrs(cidrs)
        except ValueError as e:
            raise HTTPException(400, msg("err.cidr_bad", e=e))
        cap = 100 if acc["provider"] == "oci" else 20   # AWS/Azure 每次换 IP 更慢、可能停机，次数上限更低
        p.update(cidrs=cidrs)
    if cidrs or quality:
        cap = 100 if acc["provider"] == "oci" else 20
        p.update(max_tries=max(1, min(cap, int(body.get("max_tries") or (20 if acc["provider"] == "oci" else 5)))))
    tid = tasks.create_task("change_ip", acc_id, p)
    tasks.record_ip_change(acc_id, p["instance_id"], False, tid)
    return {"ok": True, "task_id": tid}


@router.get("/api/accounts/{acc_id}/ip-change-usage")
def ip_change_usage(acc_id: int):
    need_acc(acc_id)
    return tasks.ip_change_usage(acc_id)


@router.get("/api/ip-change-usage")
def ip_change_usage_all():
    return [dict(tasks.ip_change_usage(a["id"]), name=a["name"], provider=a["provider"]) for a in core.list_accounts()]


@router.post("/api/accounts/{acc_id}/instances/resize")
async def resize(acc_id: int, body: dict = Body(...)):
    need_acc(acc_id)
    await guarded(acc_id, "resize", body, body.get("region"))
    tid = tasks.create_task("resize", acc_id, {k: body.get(k) for k in
                            ("instance_id", "region", "name", "ocpus", "memory_gb", "shape", "size")})
    return {"ok": True, "task_id": tid}


@router.post("/api/accounts/{acc_id}/instances/{iid:path}/open-port")
async def inst_open_port(acc_id: int, iid: str, body: dict = Body(...)):
    """实例操作「开放端口」（三家云）：来源固定 0.0.0.0/0。port 可填 "8443" 或 "80, 443, 8000-8100"。
    OCI 写子网安全列表；AWS 写实例全部安全组；Azure 写网卡 / 子网 NSG。已存在的规则跳过。
    不带 confirm_public 返回 409（detail.public_warning）；空端口或 1-65535 返回 400。"""
    acc = need_acc(acc_id)
    iid = (body.get("instance_id") or "").strip() if iid.strip("/") in ("", "-", "_") else iid
    if not iid:
        raise HTTPException(400, msg("err.missing_instance_id"))
    if acc["provider"] == "aws" and body.get("kind", "vm") != "vm":
        raise HTTPException(400, msg("err.ls_fw_console"))
    proto = str(body.get("protocol") or "tcp").strip().lower()
    if proto not in ("tcp", "udp"):
        raise HTTPException(400, msg("err.proto_tcp_udp"))
    port = str(body.get("port") if body.get("port") is not None else "").strip()
    if not port:
        raise HTTPException(400, msg("err.ports_hint"))
    from ..providers.oci_provider import OCIProvider
    try:
        ranges = OCIProvider.parse_ports(port)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _public_guard("ingress", proto, "0.0.0.0/0", port, body.get("confirm_public"))
    try:
        res = await run(services.provider(acc_id, body.get("region")).open_ports, iid, proto, ranges)
    except (ValueError, LookupError) as e:
        raise HTTPException(400, str(e))
    parts = [f"{g['kind']} {g['name']}：新增 {g['added']} 条，跳过 {g['skipped']} 条（已存在）" for g in res.get("groups", [])]
    res["msg"] = f"{proto.upper()} {port}（来源 0.0.0.0/0）\n" + "\n".join(parts)
    return res


async def do_rename(acc_id, body, provider=None):
    acc = need_acc(acc_id, provider)
    name = (body.get("new_name") or "").strip()
    if not name:
        raise HTTPException(400, msg("err.name_required"))
    if len(name) > 255:
        raise HTTPException(400, msg("err.name_too_long"))
    if not body.get("instance_id"):
        raise HTTPException(400, msg("err.missing_instance_id2"))
    kind = body.get("kind") or "vm"
    if acc["provider"] == "aws" and kind == "lightsail":
        raise HTTPException(400, msg("err.ls_no_rename"))
    prov = services.provider(acc_id, body.get("region"))
    if not hasattr(prov, "rename"):
        raise HTTPException(400, msg("err.no_rename"))
    res = dict(await run(prov.rename, body["instance_id"], name) or {}, ok=True)
    # v1.6 关停自动同步主机名（Run Command / SSM 通道风险过高）：只改云端显示名，
    # 系统主机名返回手动命令给用户 SSH 自行执行；body 里的 sync_hostname 参数不再理会
    res["hostname"] = hostname.manual_result(name)
    return res


@router.post("/api/accounts/{acc_id}/instances/rename")
async def inst_rename(acc_id: int, body: dict = Body(...)):
    """三家云通用改名：OCI 显示名 / AWS EC2 Name 标签 / Azure tricloud-name 标签（VM 资源名不可改）。"""
    return await do_rename(acc_id, body)


@router.post("/api/accounts/{acc_id}/oci/rename")
async def oci_rename(acc_id: int, body: dict = Body(...)):
    return await do_rename(acc_id, body, "oci")


@router.get("/api/accounts/{acc_id}/traffic")
async def traffic(acc_id: int, instance_id: str, region: str = None, kind: str = "vm"):
    acc = need_acc(acc_id)
    p = services.provider(acc_id, region)
    return await run(p.traffic, instance_id) if acc["provider"] == "oci" else await run(p.traffic, instance_id, kind)


# ================= 3. 重装系统（三家云，后台任务） =================
@router.post("/api/accounts/{acc_id}/instances/reinstall")
async def reinstall(acc_id: int, body: dict = Body(...)):
    acc = need_acc(acc_id)
    _req(body, "instance_id")
    if not body.get("confirm"):
        raise HTTPException(400, msg("err.reinstall_confirm"))
    if acc["provider"] == "aws" and body.get("kind", "vm") != "vm":
        raise HTTPException(400, msg("err.ls_no_reinstall"))
    if acc["provider"] == "oci":
        await guarded(acc_id, "bootvol", {"size_gb": body.get("disk_gb"), **body}, body.get("region"))
    keys = ("instance_id", "region", "name", "os", "os_version", "disk_gb", "password_login", "ssh_key", "kind")
    tid = tasks.create_task("reinstall", acc_id, {k: body.get(k) for k in keys})
    return {"ok": True, "task_id": tid}


# ================= 9. IP 质量 =================
@router.get("/api/ip-quality")
async def ip_quality(ip: str):
    try:
        return await run(net.ip_quality, ip.strip())
    except ValueError:
        raise HTTPException(400, msg("err.ip_format"))
