"""v1.2 免费额度护栏：创建 / 改配置 / 扩容之前，估算是否会超出三家的免费额度。

只做「提示 + 二次确认」，不替用户做决定。查询失败时不拦截（返回空列表），避免护栏本身挡住正常操作。
免费额度以各家官方公示为准，账号类型不同（试用、升级、学生、新版额度制）时可能有差异。
"""
from . import core, services

# ---- 各家免费额度（2026 年公示口径） ----
OCI_MICRO_MAX = 2                         # VM.Standard.E2.1.Micro 最多 2 台
OCI_STORAGE_GB = 200                      # 块存储总量
OCI_FREE_SHAPES = {"VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"}

AWS_FREE_TYPES = {"t2.micro", "t3.micro", "t3.small", "t4g.micro", "t4g.small", "c7i-flex.large", "m7i-flex.large"}
AWS_EBS_GB = 30

AZ_FREE_SIZES = {"Standard_B1s", "Standard_B2pts_v2", "Standard_B2ats_v2"}
AZ_DISK_GB = 64                           # 2 块 P6（64GB Premium SSD）

ACTIVE = {"running", "starting", "pending", "provisioning", "stopping", "stopped"}   # OCI 停机仍占配额


def _instances(acc_id, region):
    try:
        return services.list_instances(acc_id, region, "vm")
    except Exception:
        return None


def _storage(prov):
    try:
        return prov.storage_usage()
    except Exception:
        return None


def check(acc_id, op, body, region=None):
    """op: create | resize | bootvol | ls_create。返回警告文本列表，空列表表示在免费额度内。"""
    acc = core.get_account(acc_id, with_cred=True)
    if not acc:
        return []
    region = region or body.get("region") or acc.get("region")
    try:
        prov = services.provider(acc_id, region)
    except Exception:
        return []
    fn = {"oci": _oci, "aws": _aws, "azure": _azure}.get(acc["provider"])
    if fn is None:
        return []
    try:
        return fn(acc, prov, op, body, region)
    except Exception as e:      # 护栏不能挡路
        print("guard check failed", acc_id, op, e, flush=True)
        return []


# ---------------- OCI ----------------
def _oci(acc, prov, op, body, region):
    w = []
    home = acc["cred"].get("home_region")
    if op in ("create", "resize") and home and region and region != home:
        w.append(f"Always Free 资源只在主区域（{home}）有效，在 {region} 创建将按量计费")
    if op in ("create", "resize"):
        c = body.get("create") or body
        shape = c.get("shape") or "VM.Standard.A1.Flex"
        insts = _instances(acc["id"], region)
        if op == "create" and shape not in OCI_FREE_SHAPES:
            w.append(f"{shape} 不是 Always Free 规格，开机即按量计费")
        if insts is not None:
            others = [i for i in insts if i.get("state") in ACTIVE and i.get("id") != body.get("instance_id")]
            if shape == "VM.Standard.A1.Flex" or op == "resize":
                a1 = [i for i in others if i.get("shape") == "VM.Standard.A1.Flex"]
                cpu = sum(float(i.get("ocpus") or 0) for i in a1) + float(c.get("ocpus") or (1 if op == "create" else 0))
                mem = sum(float(i.get("memory_gb") or 0) for i in a1) + float(c.get("memory_gb") or (6 if op == "create" else 0))
                fc, fm, basis = core.oci_a1_free(acc["id"])
                if cpu > fc or mem > fm:
                    who = "付费号" if basis == "paid" else "免费号"
                    w.append(f"A1 合计将达到 {cpu:g} OCPU / {mem:g} GB，超出{who}免费的 {fc} OCPU / {fm} GB，超出部分按小时计费")
            if op == "create" and shape == "VM.Standard.E2.1.Micro":
                n = sum(1 for i in others if i.get("shape") == shape) + 1
                if n > OCI_MICRO_MAX:
                    w.append(f"E2.1.Micro 将有 {n} 台，免费只含 {OCI_MICRO_MAX} 台")
        if op == "create":
            st = _storage(prov)
            disk = int(c.get("disk_gb") or 50)
            if st and st["volume_gb"] + disk > OCI_STORAGE_GB:
                w.append(f"块存储将达到 {st['volume_gb'] + disk} GB，超出免费的 {OCI_STORAGE_GB} GB")
    elif op == "bootvol":
        if body.get("vpus_per_gb") not in (None, "", 10, "10"):
            w.append(f"性能 {body['vpus_per_gb']} VPU/GB 高于免费的 10（均衡），会按量计费")
        if body.get("size_gb"):
            st = _storage(prov)
            try:
                cur = prov.boot_volume(body["instance_id"])["size_gb"]
            except Exception:
                cur = None
            if st and cur is not None and st["volume_gb"] - cur + int(body["size_gb"]) > OCI_STORAGE_GB:
                w.append(f"扩容后块存储合计 {st['volume_gb'] - cur + int(body['size_gb'])} GB，超出免费的 {OCI_STORAGE_GB} GB")
    elif op == "volume":   # v1.6：新建 / 扩容块存储卷
        if body.get("vpus_per_gb") not in (None, "", 0, "0", 10, "10"):
            w.append(f"性能 {body['vpus_per_gb']} VPU/GB 高于免费的 10（均衡），会按量计费")
        if body.get("size_gb"):
            st = _storage(prov)
            add = int(body["size_gb"])
            if body.get("volume_id"):
                try:
                    add -= int(prov.bs.get_volume(body["volume_id"]).data.size_in_gbs)
                except Exception:
                    pass
            if st and st["volume_gb"] + add > OCI_STORAGE_GB:
                w.append(f"块存储合计将达到 {st['volume_gb'] + add} GB，超出免费的 {OCI_STORAGE_GB} GB")
    elif op == "reserved_ip":
        try:
            n = len(prov.reserved_ips())
        except Exception:
            n = 0
        if n >= 1:
            w.append(f"已有 {n} 个预留公网 IP；Always Free 一般只含 1 个，超出或闲置（未绑定）可能计费")
    return w


# ---------------- AWS ----------------
def _aws(acc, prov, op, body, region):
    w = []
    if op == "create":
        t = body.get("type") or "t3.micro"
        if t not in AWS_FREE_TYPES:
            w.append(f"{t} 不在免费套餐机型内，按小时计费")
        insts = _instances(acc["id"], region)
        if insts is not None and t in AWS_FREE_TYPES:
            run = [i for i in insts if i.get("state") in ("running", "pending") and i.get("shape") in AWS_FREE_TYPES]
            if run:
                w.append(f"已有 {len(run)} 台免费机型在运行；旧版免费套餐每月共 750 小时，多台同时运行会超出"
                         "（2025-07-15 后注册的新账号为额度制，按 Credit 扣减）")
        st = _storage(prov)
        disk = int(body.get("disk_gb") or 10)
        if st and st["volume_gb"] + disk > AWS_EBS_GB:
            w.append(f"EBS 合计将达到 {st['volume_gb'] + disk} GB，超出免费的 {AWS_EBS_GB} GB")
    elif op == "ls_create":
        w.append("Lightsail 按套餐月费计费，仅部分套餐对新账号前 3 个月免费，请确认所选套餐")
    return w


# ---------------- Azure ----------------
def _azure(acc, prov, op, body, region):
    w = []
    size = body.get("size")
    if op in ("create", "resize") and size and size not in AZ_FREE_SIZES:
        w.append(f"{size} 不在免费额度内（免费：B1s / B2pts_v2 / B2ats_v2 各 750 小时/月），按小时计费")
    if op == "create":
        insts = _instances(acc["id"], None)
        if insts is not None and size in AZ_FREE_SIZES:
            same = [i for i in insts if i.get("shape") == size and i.get("state") == "running"]
            if same:
                w.append(f"已有 {len(same)} 台 {size} 在运行，同规格免费额度每月共 750 小时，两台同时运行会超出")
        disk = int(body.get("disk_gb") or 30)
        dtype = body.get("disk_type") or "StandardSSD_LRS"
        if dtype != "Premium_LRS":
            w.append(f"免费磁盘是 Premium SSD（P6 64GB×2），{dtype} 不在免费范围内，会按量计费")
        elif disk > AZ_DISK_GB:
            w.append(f"系统盘 {disk} GB 超过免费 P6 的 {AZ_DISK_GB} GB，会按 P10 计费")
    return w
