"""OCI (Oracle Cloud Infrastructure) provider。

功能对标 SIJULY/Oracle 面板：实例列表/生命周期/换公网IP/分配IPv6/
改配置/简化创建/自动抢机/自动建网，全部走 OCI Python SDK。
"""
import base64
import json
import logging
import random
import time

import oci
from oci.core.models import (
    AddVcnIpv6CidrDetails,
    CreateIpv6Details,
    CreatePublicIpDetails,
    CreateSubnetDetails,
    CreateVcnDetails,
    CreateInternetGatewayDetails,
    EgressSecurityRule,
    GetPublicIpByPrivateIpIdDetails,
    LaunchInstanceDetails,
    CreateVnicDetails,
    InstanceSourceViaImageDetails,
    LaunchInstanceShapeConfigDetails,
    RouteRule,
    UpdateInstanceDetails,
    UpdateInstanceShapeConfigDetails,
    UpdateRouteTableDetails,
    UpdateSecurityListDetails,
    UpdateSubnetDetails,
    UpdateVcnDetails,
)
from oci.exceptions import ServiceError

from .. import cf
from .base import (AccountField, InstanceInfo, IP_CHANGE_MAX_ATTEMPTS,
                    Provider, ip_in_spec, parse_cidr_spec, proxy_settings,
                    spec_desc)

log = logging.getLogger(__name__)

_STATUS_MAP = {
    "RUNNING": "running",
    "STOPPED": "stopped",
    "STOPPING": "stopping",
    "STARTING": "pending",
    "PROVISIONING": "pending",
    "TERMINATED": "terminated",
    "TERMINATING": "terminating",
}


def _sdk_config(creds: dict) -> dict:
    key = creds["private_key"].replace("\\n", "\n")
    if "BEGIN" not in key:
        raise ValueError("私钥格式不正确，需要 PEM 格式")
    return {
        "user": creds["user_ocid"].strip(),
        "tenancy": creds["tenancy_ocid"].strip(),
        "fingerprint": creds["fingerprint"].strip(),
        "region": creds["region"].strip(),
        "key_content": key,
    }


def _apply_proxy(client, creds: dict):
    """为 OCI 客户端设置代理。

    OCI SDK 底层用 requests.Session，原生支持 session.proxies；
    未配置代理时不做任何改动（直连）。
    """
    proxies = proxy_settings(creds)
    if proxies:
        client.base_client.session.proxies = proxies
    return client


def _clients(creds: dict):
    cfg = _sdk_config(creds)
    return (
        _apply_proxy(oci.core.ComputeClient(cfg), creds),
        _apply_proxy(oci.core.VirtualNetworkClient(cfg), creds),
        _apply_proxy(oci.identity.IdentityClient(cfg), creds),
    )


def _primary_vnic(vnet, compute, tenancy: str, instance_id: str):
    atts = oci.pagination.list_call_get_all_results(
        compute.list_vnic_attachments, compartment_id=tenancy, instance_id=instance_id
    ).data
    if not atts:
        return None, None
    vnic = vnet.get_vnic(atts[0].vnic_id).data
    return vnic, atts[0]


def _user_data(login_user: str, password: str, startup_script: str = "") -> str:
    default_script = """
echo "Waiting for apt lock..."
while fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || fuser /var/lib/dpkg/lock >/dev/null 2>&1; do
  sleep 10
done
for i in 1 2 3; do
  apt-get update && apt-get install -y curl wget unzip git socat cron && break
  sleep 15
done
"""
    parts = [
        "#cloud-config",
        "chpasswd:",
        "  expire: False",
        "  list:",
        f"    - {login_user}:{password}",
        "runcmd:",
        "  - \"sed -i -e '/^#*PasswordAuthentication/s/^.*$/PasswordAuthentication yes/' /etc/ssh/sshd_config\"",
        "  - 'rm -f /etc/ssh/sshd_config.d/60-cloudimg-settings.conf'",
        "  - \"sed -i -e '/^#*PermitRootLogin/s/^.*$/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config\"",
        f"  - [ bash, -c, {json.dumps(default_script)} ]",
    ]
    if startup_script and startup_script.strip():
        parts.append(f"  - [ bash, -c, {json.dumps(startup_script.strip())} ]")
    parts.append("  - systemctl restart sshd || service sshd restart || service ssh restart")
    return base64.b64encode("\n".join(parts).encode()).decode()


class OciProvider(Provider):
    id = "oci"
    name = "Oracle Cloud (OCI)"
    supports_snatch = True
    supports_billing = True

    def get_billing(self, creds: dict) -> dict:
        """OCI 账单：Usage API 按服务汇总当月费用。
        需要 IAM policy：allow group <组> to manage usage-report in tenancy
        """
        import datetime
        cfg = _sdk_config(creds)
        tenancy = cfg["tenancy"]
        now = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)  # Usage API 要求精确到天
        start = now.replace(day=1)
        usage = _apply_proxy(oci.usage_api.UsageapiClient(cfg), creds)
        details = oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=tenancy,
            time_usage_started=start,
            time_usage_ended=now,
            granularity="MONTHLY",
        )
        items = oci.pagination.list_call_get_all_results(
            usage.request_summarized_usages,
            request_summarized_usages_details=details).data
        by_service: dict[str, float] = {}
        currency = ""
        for it in items:
            svc = it.service or "其他"
            by_service[svc] = by_service.get(svc, 0.0) + float(it.computed_amount or 0)
            currency = currency or (it.currency or "")
        services = [{"name": k, "cost": round(v, 4)}
                    for k, v in sorted(by_service.items(), key=lambda x: -x[1])]
        return {
            "currency": currency or "USD",
            "period": f"{start.date()} ~ {now.date()}",
            "total": round(sum(by_service.values()), 4),
            "services": services,
            "note": "数据来自 OCI Usage API，可能有数小时延迟；免费套餐费用通常为 0",
        }

    def get_quotas(self, creds: dict) -> dict:
        """配额查询：计算实例各规格按可用域的可用余量 + 块存储额度。"""
        cfg = _sdk_config(creds)
        tenancy = cfg["tenancy"]
        identity = _apply_proxy(oci.identity.IdentityClient(cfg), creds)
        limits = _apply_proxy(oci.limits.LimitsClient(cfg), creds)
        ads = [ad.name for ad in
               identity.list_availability_domains(compartment_id=tenancy).data]
        groups = []

        def _availability(service: str, name: str) -> dict:
            out = {}
            for ad in ads:
                try:
                    ra = limits.get_resource_availability(
                        service, name, tenancy, availability_domain=ad).data
                    out[ad.split(":")[-1]] = f"可用{ra.available}"
                except Exception as e:  # noqa: BLE001
                    log.debug("quota %s/%s/%s failed: %s", service, name, ad, e)
            return out

        # 计算：挑实例数量类配额
        try:
            defs = oci.pagination.list_call_get_all_results(
                limits.list_limit_definitions,
                compartment_id=tenancy, service_name="compute").data
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"查询配额定义失败（需要 limits 读取权限）: {e}") from e
        interesting = [d for d in defs
                       if "count" in d.name.lower()
                       and "gpu" not in d.name.lower()
                       and "dvh" not in d.name.lower()
                       and any(k in d.name.lower() for k in
                               ("micro", "small", "-a1-", "-a1.", "e2", "e3", "e4", "standard"))]
        interesting.sort(key=lambda d: (0 if "micro" in d.name.lower() else
                                        1 if "a1" in d.name.lower() else 2, d.name))
        items = []
        for d in interesting[:10]:
            avail = _availability("compute", d.name)
            detail = " · ".join(f"{ad}:{v}" for ad, v in avail.items()) or "查询失败"
            items.append({"name": d.name, "detail": detail})
        if items:
            groups.append({"title": "计算实例余量（按可用域）", "items": items})

        # 块存储
        try:
            bdefs = oci.pagination.list_call_get_all_results(
                limits.list_limit_definitions,
                compartment_id=tenancy, service_name="block-storage").data
        except Exception:  # noqa: BLE001
            bdefs = []
        bitems = []
        for d in bdefs:
            if any(k in d.name.lower() for k in ("volume", "storage")):
                try:
                    vals = limits.list_limit_values(
                        compartment_id=tenancy, service_name="block-storage").data
                except Exception:  # noqa: BLE001
                    vals = []
                v = next((x.value for x in vals if x.name == d.name), None)
                bitems.append({"name": d.name,
                               "detail": f"配额 {v}" if v is not None else d.description or ""})
                if len(bitems) >= 6:
                    break
        if bitems:
            groups.append({"title": "块存储配额", "items": bitems})
        return {
            "groups": groups,
            "note": "余量为当前可用域实时可用数；部分规格需在对应可用域查询",
        }

    def get_subscription(self, creds: dict) -> dict:
        """订阅信息：租户基本信息（OCI 无公开的付费订阅 API）。"""
        cfg = _sdk_config(creds)
        tenancy = _apply_proxy(
            oci.identity.IdentityClient(cfg), creds
        ).get_tenancy(cfg["tenancy"]).data
        return {
            "items": [
                {"name": "租户名", "detail": tenancy.name or "-"},
                {"name": "归属区域", "detail": tenancy.home_region_key or "-"},
                {"name": "租户 OCID", "detail": cfg["tenancy"]},
            ],
            "note": "付费订阅详情/免费试用剩余请在 OCI 控制台账单页查看，API 未开放",
        }
    fields = [
        AccountField("tenancy_ocid", "Tenancy OCID", placeholder="ocid1.tenancy.oc1..…"),
        AccountField("user_ocid", "User OCID", placeholder="ocid1.user.oc1..…"),
        AccountField("fingerprint", "API 密钥指纹", placeholder="如 aa:bb:cc:…"),
        AccountField("region", "区域", placeholder="如 ap-tokyo-1",
                     help="实例所在的区域，如 ap-tokyo-1 / ap-osaka-1"),
        AccountField("private_key", "API 私钥 (PEM)", field_type="textarea",
                     placeholder="-----BEGIN PRIVATE KEY-----…"),
        AccountField("default_subnet_ocid", "默认子网 OCID", required=False,
                     help="创建实例时使用；留空则自动查找或创建"),
        AccountField("default_ssh_key", "默认 SSH 公钥", field_type="textarea", required=False,
                     help="创建实例时注入；留空则只用密码登录"),
    ]
    actions = [
        {"key": "start", "label": "启动"},
        {"key": "stop", "label": "停止"},
        {"key": "restart", "label": "重启"},
        {"key": "terminate", "label": "终止", "danger": True},
        {"key": "change_ip", "label": "更换公网 IP"},
        {"key": "check_ip", "label": "检测 IP 连通性"},
        {"key": "assign_ipv6", "label": "分配 IPv6"},
        {"key": "delete_ipv6", "label": "删除 IPv6"},
        {"key": "update_shape", "label": "更改配置"},
        {"key": "rename", "label": "改名"},
        {"key": "extend_disk", "label": "磁盘扩容"},
        {"key": "open_port", "label": "开放端口"},
    ]
    supports_quotas = True
    supports_subscription = True

    # ---------- 基础 ----------
    def test(self, creds: dict) -> None:
        compute, _, _ = _clients(creds)
        compute.list_instances(compartment_id=creds["tenancy_ocid"].strip(), limit=1)

    def list_instances(self, creds: dict) -> list[InstanceInfo]:
        compute, vnet, _ = _clients(creds)
        tenancy = creds["tenancy_ocid"].strip()
        result = []
        instances = oci.pagination.list_call_get_all_results(
            compute.list_instances, compartment_id=tenancy
        ).data
        for inst in instances:
            if inst.lifecycle_state in ("TERMINATED", "TERMINATING"):
                continue
            info = InstanceInfo(
                id=inst.id,
                name=inst.display_name or "-",
                status=_STATUS_MAP.get(inst.lifecycle_state, "unknown"),
                status_text=inst.lifecycle_state,
                shape=inst.shape,
                cpu=str(getattr(inst.shape_config, "ocpus", "") or ""),
                memory=str(getattr(inst.shape_config, "memory_in_gbs", "") or ""),
                region=inst.region,
                zone=inst.availability_domain,
                created=inst.time_created.isoformat() if inst.time_created else "",
            )
            try:
                vnic, att = _primary_vnic(vnet, compute, tenancy, inst.id)
                if vnic:
                    info.public_ip = vnic.public_ip or ""
                    info.private_ip = vnic.private_ip or ""
                    info.extra["vnic_id"] = vnic.id
                    info.extra["subnet_id"] = vnic.subnet_id
                ipv6s = vnet.list_ipv6s(vnic_id=vnic.id).data if vnic else []
                if ipv6s:
                    info.ipv6 = ipv6s[0].ip_address
            except Exception as e:  # noqa: BLE001 - 单个实例的网络信息失败不影响列表
                log.warning("enrich instance %s failed: %s", inst.id, e)
            try:
                bvas = compute.list_boot_volume_attachments(
                    compartment_id=tenancy, availability_domain=info.zone,
                    instance_id=inst.id,
                ).data
                if bvas:
                    bv = compute.get_boot_volume(bvas[0].boot_volume_id).data
                    info.extra["boot_volume_gb"] = str(bv.size_in_gbs)
                    info.extra["boot_volume_id"] = bvas[0].boot_volume_id
            except Exception as e:  # noqa: BLE001
                log.warning("boot volume info %s failed: %s", inst.id, e)
            result.append(info)
        return result

    # ---------- 实例操作 ----------
    def instance_action(self, creds: dict, inst: InstanceInfo, action: str, ctx) -> str:
        compute, vnet, _ = _clients(creds)
        iid = inst.id
        if action == "start":
            compute.instance_action(iid, "START")
            oci.wait_until(compute, compute.get_instance(iid), "lifecycle_state", "RUNNING",
                           max_wait_seconds=300)
            return "实例已启动"
        if action == "stop":
            compute.instance_action(iid, "STOP")
            oci.wait_until(compute, compute.get_instance(iid), "lifecycle_state", "STOPPED",
                           max_wait_seconds=300)
            return "实例已停止"
        if action == "restart":
            compute.instance_action(iid, "RESET")
            oci.wait_until(compute, compute.get_instance(iid), "lifecycle_state", "RUNNING",
                           max_wait_seconds=300)
            return "实例已重启"
        if action == "terminate":
            compute.terminate_instance(iid, preserve_boot_volume=False)
            return "实例终止请求已提交"
        if action == "change_ip":
            return self._change_ip(compute, vnet, creds, inst, ctx,
                                   cidr=(getattr(ctx, "params", {}) or {}).get("cidr"))
        if action == "check_ip":
            return self._check_ip(inst, ctx)
        if action == "assign_ipv6":
            return self._assign_ipv6(vnet, inst)
        if action == "delete_ipv6":
            return self._delete_ipv6(vnet, inst)
        if action == "update_shape":
            raise ValueError("更改配置需要提供 shape/ocpus/memory 参数，请用专用接口")
        if action == "rename":
            new_name = (getattr(ctx, "params", {}) or {}).get("new_name", "").strip()
            if not new_name:
                raise ValueError("请提供新名称")
            compute.update_instance(iid, UpdateInstanceDetails(display_name=new_name))
            return f"实例已改名为 {new_name}"
        if action == "extend_disk":
            return self._extend_disk(compute, creds, inst, ctx)
        if action == "open_port":
            return self._open_port(vnet, inst, ctx)
        raise ValueError(f"未知操作: {action}")

    def _change_ip(self, compute, vnet, creds, inst: InstanceInfo,
                   ctx, cidr: str | None = None) -> str:
        vnic_id = inst.extra.get("vnic_id")
        if not vnic_id:
            raise ValueError("缺少 vnic_id，请刷新实例列表后重试")
        privates = oci.pagination.list_call_get_all_results(
            vnet.list_private_ips, vnic_id=vnic_id
        ).data
        primary = next((p for p in privates if p.is_primary), None)
        if not primary:
            raise ValueError("未找到主私有 IP")
        spec = parse_cidr_spec(cidr)
        # OCI 机制：释放旧临时公网 IP 再分配新的，循环换直到命中目标网段
        for attempt in range(1, IP_CHANGE_MAX_ATTEMPTS + 1):
            try:
                existing = vnet.get_public_ip_by_private_ip_id(
                    GetPublicIpByPrivateIpIdDetails(private_ip_id=primary.id)
                ).data
                if existing.lifetime == "EPHEMERAL":
                    vnet.delete_public_ip(existing.id)
                    time.sleep(5)
            except ServiceError as e:
                if e.status != 404:
                    raise
            new_ip = vnet.create_public_ip(
                CreatePublicIpDetails(
                    compartment_id=creds["tenancy_ocid"].strip(),
                    lifetime="EPHEMERAL",
                    private_ip_id=primary.id,
                )
            ).data
            if ip_in_spec(new_ip.ip_address, spec):
                # 换 IP 成功后联动更新 Cloudflare A 记录（失败只记日志）
                cf.sync_dns(ctx, inst.id, new_ip.ip_address)
                return f"更换 IP 成功，新公网 IP: {new_ip.ip_address}"
            ctx.log(f"第 {attempt}/{IP_CHANGE_MAX_ATTEMPTS} 次换得公网 IP "
                    f"{new_ip.ip_address}，不符合要求（{spec_desc(spec)}），重新更换…")
        raise ValueError(
            f"已尝试 {IP_CHANGE_MAX_ATTEMPTS} 次，未能换到符合要求的公网 IP"
            f"（要求：{spec_desc(spec)}）")

    def _check_ip(self, inst: InstanceInfo, ctx) -> str:
        """检测公网 IP 连通性：ping + TCP 端口探测（复用 ip_check.probe_ip）。"""
        from ..ip_check import probe_ip
        ip = inst.public_ip or ""
        if not ip:
            raise ValueError("该实例没有公网 IP")
        return "\n".join(probe_ip(ip)["lines"])

    def _assign_ipv6(self, vnet, inst: InstanceInfo) -> str:
        vnic_id = inst.extra.get("vnic_id")
        if not vnic_id:
            raise ValueError("缺少 vnic_id，请刷新实例列表后重试")
        vnic = vnet.get_vnic(vnic_id).data
        subnet = vnet.get_subnet(vnic.subnet_id).data
        vcn = vnet.get_vcn(subnet.vcn_id).data
        if not vcn.ipv6_cidr_blocks:
            vnet.add_ipv6_vcn_cidr(
                vcn_id=vcn.id,
                add_vcn_ipv6_cidr_details=AddVcnIpv6CidrDetails(is_oracle_gua_allocation_enabled=True),
            )
            oci.wait_until(vnet, vnet.get_vcn(vcn.id), "lifecycle_state", "AVAILABLE",
                           max_wait_seconds=300)
            vcn = vnet.get_vcn(vcn.id).data
        if not subnet.ipv6_cidr_block:
            subnet_v6 = vcn.ipv6_cidr_blocks[0].replace("/56", "/64")
            vnet.update_subnet(subnet.id, UpdateSubnetDetails(ipv6_cidr_block=subnet_v6))
            oci.wait_until(vnet, vnet.get_subnet(subnet.id), "lifecycle_state", "AVAILABLE",
                           max_wait_seconds=300)
        rt = vnet.get_route_table(vcn.default_route_table_id).data
        igws = vnet.list_internet_gateways(compartment_id=vcn.compartment_id, vcn_id=vcn.id).data
        if not igws:
            raise ValueError("未找到互联网网关，无法添加 IPv6 路由")
        if not any(r.destination == "::/0" for r in rt.route_rules):
            rules = list(rt.route_rules)
            rules.append(RouteRule(destination="::/0", network_entity_id=igws[0].id))
            vnet.update_route_table(rt.id, UpdateRouteTableDetails(route_rules=rules))
        seclist = vnet.get_security_list(vcn.default_security_list_id).data
        if not any(r.destination == "::/0" for r in seclist.egress_security_rules):
            egress = list(seclist.egress_security_rules)
            egress.append(EgressSecurityRule(destination="::/0", protocol="all"))
            vnet.update_security_list(seclist.id, UpdateSecurityListDetails(egress_security_rules=egress))
        new_v6 = vnet.create_ipv6(CreateIpv6Details(vnic_id=vnic_id)).data
        return f"IPv6 分配成功: {new_v6.ip_address}"

    def _delete_ipv6(self, vnet, inst: InstanceInfo) -> str:
        vnic_id = inst.extra.get("vnic_id")
        if not vnic_id:
            raise ValueError("缺少 vnic_id，请刷新实例列表后重试")
        ipv6s = vnet.list_ipv6s(vnic_id=vnic_id).data
        if not ipv6s:
            raise ValueError("该实例未分配 IPv6，无需删除")
        for ip in ipv6s:
            vnet.delete_ipv6(ip.id)
        addrs = ", ".join(ip.ip_address for ip in ipv6s)
        return f"已删除 {len(ipv6s)} 个 IPv6 地址: {addrs}"

    def _extend_disk(self, compute, creds: dict, inst: InstanceInfo, ctx) -> str:
        size = int((getattr(ctx, "params", {}) or {}).get("size_gb") or 0)
        if size <= 0:
            raise ValueError("请提供目标磁盘大小（GB）")
        tenancy = creds["tenancy_ocid"].strip()
        bvol_id = inst.extra.get("boot_volume_id")
        if not bvol_id:
            bvas = compute.list_boot_volume_attachments(
                compartment_id=tenancy, availability_domain=inst.zone,
                instance_id=inst.id).data
            if not bvas:
                raise ValueError("未找到该实例的启动卷")
            bvol_id = bvas[0].boot_volume_id
        bv = compute.get_boot_volume(bvol_id).data
        cur = int(bv.size_in_gbs)
        if size <= cur:
            raise ValueError(f"目标大小 {size}GB 必须大于当前 {cur}GB（只支持扩容）")
        ctx.log(f"启动卷 {cur}GB → {size}GB…")
        compute.update_boot_volume(
            bvol_id, oci.core.models.UpdateBootVolumeDetails(size_in_gbs=size))
        return f"磁盘扩容已提交: {cur}GB → {size}GB（系统内需手动扩展分区）"

    def _open_port(self, vnet, inst: InstanceInfo, ctx) -> str:
        port = int((getattr(ctx, "params", {}) or {}).get("port") or 0)
        if not (1 <= port <= 65535):
            raise ValueError("请提供有效端口 1-65535")
        vnic_id = inst.extra.get("vnic_id")
        subnet_id = inst.extra.get("subnet_id")
        if not vnic_id or not subnet_id:
            raise ValueError("缺少网卡/子网信息，请刷新实例列表后重试")
        vnic = vnet.get_vnic(vnic_id).data
        seclist = vnet.get_security_list(vnic.nsg_ids[0]).data if vnic.nsg_ids else \
            vnet.get_security_list(vnet.get_subnet(subnet_id).data.security_list_ids[0]).data
        for r in seclist.ingress_security_rules or []:
            if (r.protocol == "6" and r.source == "0.0.0.0/0" and r.tcp_options
                    and r.tcp_options.destination_port_range
                    and r.tcp_options.destination_port_range.min == port
                    and r.tcp_options.destination_port_range.max == port):
                return f"端口 {port} 已在安全列表中放行，无需重复操作"
        from oci.core.models import IngressSecurityRule, TcpOptions, PortRange
        rules = list(seclist.ingress_security_rules or [])
        rules.append(IngressSecurityRule(
            protocol="6", source="0.0.0.0/0",
            tcp_options=TcpOptions(destination_port_range=PortRange(min=port, max=port)),
            description=f"tricloud open {port}"))
        vnet.update_security_list(seclist.id, UpdateSecurityListDetails(ingress_security_rules=rules))
        return f"已在安全列表放行 TCP 端口 {port}（来源 0.0.0.0/0）"

    def update_shape(self, creds: dict, instance_id: str, shape: str,
                     ocpus: float | None, memory_gbs: float | None, ctx) -> str:
        compute, _, _ = _clients(creds)
        details = UpdateInstanceDetails(shape=shape)
        if ocpus or memory_gbs:
            details.shape_config = UpdateInstanceShapeConfigDetails(
                ocpus=ocpus, memory_in_gbs=memory_gbs)
        compute.update_instance(instance_id, details)
        ctx.log("配置更新请求已提交，等待实例恢复 RUNNING…")
        oci.wait_until(compute, compute.get_instance(instance_id), "lifecycle_state", "RUNNING",
                       max_wait_seconds=600)
        return f"实例配置已更新为 {shape}"

    # ---------- 创建实例 ----------
    def create_options(self, creds: dict) -> dict:
        compute, _, identity = _clients(creds)
        tenancy = creds["tenancy_ocid"].strip()
        ads = identity.list_availability_domains(compartment_id=tenancy).data
        ad_names = [ad.name for ad in ads]
        shapes = []
        if ad_names:
            try:
                for s in compute.list_shapes(compartment_id=tenancy,
                                             availability_domain=ad_names[0]).data:
                    shapes.append(s.shape)
            except ServiceError as e:
                log.warning("list_shapes failed: %s", e)
        return {
            "availability_domains": ad_names,
            "shapes": sorted(set(shapes)),
            "os_options": ["Canonical Ubuntu", "Oracle Linux"],
            "has_default_subnet": bool(creds.get("default_subnet_ocid")),
            "has_default_ssh_key": bool(creds.get("default_ssh_key")),
        }

    def _ensure_subnet(self, vnet, creds: dict, account_id: int | None, ctx) -> str:
        tenancy = creds["tenancy_ocid"].strip()
        subnet_id = (creds.get("default_subnet_ocid") or "").strip()
        if subnet_id:
            try:
                if vnet.get_subnet(subnet_id).data.lifecycle_state == "AVAILABLE":
                    return subnet_id
            except ServiceError as e:
                if e.status != 404:
                    raise
                ctx.log("保存的默认子网不可用，将自动查找/创建")
        try:
            vcns = vnet.list_vcns(compartment_id=tenancy).data
            if vcns:
                subnets = vnet.list_subnets(compartment_id=tenancy, vcn_id=vcns[0].id).data
                if subnets:
                    return subnets[0].id
        except Exception as e:  # noqa: BLE001
            ctx.log(f"自动查找子网失败: {e}，将创建新网络")
        ctx.log("正在自动创建网络资源 (VCN/网关/子网)，约需 2-3 分钟…")
        alias = f"auto{random.randint(100, 999)}"
        vcn = vnet.create_vcn(CreateVcnDetails(
            cidr_block="10.0.0.0/16", display_name=f"vcn-{alias}", compartment_id=tenancy)).data
        oci.wait_until(vnet, vnet.get_vcn(vcn.id), "lifecycle_state", "AVAILABLE")
        ig = vnet.create_internet_gateway(CreateInternetGatewayDetails(
            display_name=f"ig-{alias}", compartment_id=tenancy,
            is_enabled=True, vcn_id=vcn.id)).data
        oci.wait_until(vnet, vnet.get_internet_gateway(ig.id), "lifecycle_state", "AVAILABLE")
        rt_id = vcn.default_route_table_id
        rules = vnet.get_route_table(rt_id).data.route_rules
        rules.append(RouteRule(destination="0.0.0.0/0", network_entity_id=ig.id))
        vnet.update_route_table(rt_id, UpdateRouteTableDetails(route_rules=rules))
        subnet = vnet.create_subnet(CreateSubnetDetails(
            compartment_id=tenancy, vcn_id=vcn.id, cidr_block="10.0.1.0/24",
            display_name=f"subnet-{alias}")).data
        oci.wait_until(vnet, vnet.get_subnet(subnet.id), "lifecycle_state", "AVAILABLE")
        ctx.log(f"网络创建完成，子网: {subnet.id}")
        # 回写账号，下次直接复用
        if account_id:
            from .. import db as _db
            acc = _db.account_get(account_id)
            if acc:
                acc["creds"]["default_subnet_ocid"] = subnet.id
                _db.account_update(account_id, acc["name"], acc["creds"])
        return subnet.id

    def _launch(self, creds: dict, account_id: int | None, params: dict, ctx) -> tuple[str, str]:
        """执行一次创建，返回 (instance_id, 结果文本)。"""
        compute, vnet, identity = _clients(creds)
        tenancy = creds["tenancy_ocid"].strip()
        shape = params["shape"]
        # 免费 E2.1.Micro 配额保护
        if shape == "VM.Standard.E2.1.Micro":
            existing = [i for i in oci.pagination.list_call_get_all_results(
                compute.list_instances, compartment_id=tenancy).data
                if i.shape == shape and i.lifecycle_state not in ("TERMINATED", "TERMINATING")]
            if len(existing) >= 2:
                raise ValueError("免费 E2.1.Micro 已有 2 台在运行，无法再创建")
        ads = identity.list_availability_domains(compartment_id=tenancy).data
        ad = params.get("availability_domain") or ads[0].name
        os_name = params.get("os", "Canonical Ubuntu")
        images = compute.list_images(
            compartment_id=tenancy, operating_system=os_name, shape=shape,
            sort_by="TIMECREATED", sort_order="DESC", limit=5).data
        if not images:
            raise ValueError(f"未找到 {os_name} + {shape} 的可用镜像")
        image_id = images[0].id
        ctx.log(f"使用镜像: {images[0].display_name}")
        subnet_id = self._ensure_subnet(vnet, creds, account_id, ctx)
        login_user = params.get("login_user", "ubuntu") or "ubuntu"
        password = params.get("password") or "".join(
            random.choice("abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789")
            for _ in range(16))
        ssh_key = (params.get("ssh_key") or creds.get("default_ssh_key") or "").strip()
        metadata = {"user_data": _user_data(login_user, password, params.get("startup_script", ""))}
        if ssh_key:
            metadata["ssh_authorized_keys"] = ssh_key
        details = LaunchInstanceDetails(
            compartment_id=tenancy,
            availability_domain=ad,
            display_name=params.get("name") or f"instance-{random.randint(1000, 9999)}",
            shape=shape,
            source_details=InstanceSourceViaImageDetails(
                image_id=image_id,
                boot_volume_size_in_gbs=int(params.get("boot_volume_gb") or 50)),
            create_vnic_details=CreateVnicDetails(
                subnet_id=subnet_id,
                assign_public_ip=params.get("assign_public_ip", True)),
            metadata=metadata,
        )
        if shape.endswith(".Flex"):
            details.shape_config = LaunchInstanceShapeConfigDetails(
                ocpus=float(params.get("ocpus") or 1),
                memory_in_gbs=float(params.get("memory_gbs") or 6))
        ctx.log(f"正在创建实例 {details.display_name} ({shape})…")
        instance = compute.launch_instance(details).data
        ctx.log(f"实例 {instance.id} 已提交，等待 RUNNING…")
        oci.wait_until(compute, compute.get_instance(instance.id), "lifecycle_state", "RUNNING",
                       max_wait_seconds=900, max_interval_seconds=15)
        public_ip = ""
        try:
            vnic, _ = _primary_vnic(vnet, compute, tenancy, instance.id)
            public_ip = (vnic.public_ip or "") if vnic else ""
        except Exception as e:  # noqa: BLE001
            ctx.log(f"获取公网 IP 失败: {e}")
        text = (f"实例创建成功: {details.display_name}\n"
                f"ID: {instance.id}\n"
                f"公网 IP: {public_ip or '（未分配）'}\n"
                f"登录用户: {login_user}\n"
                f"密码: {password}（仅显示一次，请妥善保存）")
        return instance.id, text

    def create_instance(self, creds: dict, params: dict, ctx) -> str:
        _, text = self._launch(creds, params.get("_account_id"), params, ctx)
        return text

    def snatch_instance(self, creds: dict, params: dict, ctx) -> str:
        interval = int(params.get("retry_interval") or 30)
        attempt = 0
        ctx.log(f"开始抢机: {params.get('shape')}，重试间隔 {interval}s，手动停止前一直尝试")
        while True:
            if ctx.should_stop():
                return "抢机任务已手动停止"
            attempt += 1
            try:
                _, text = self._launch(creds, params.get("_account_id"), params, ctx)
                ctx.log(f"第 {attempt} 次尝试成功！")
                return f"抢机成功（第 {attempt} 次尝试）\n{text}"
            except ServiceError as e:
                msg = f"{e.code}: {e.message}"
                if (e.status == 429 or "TooManyRequests" in str(e.code)
                        or "Out of host capacity" in str(e.message)
                        or "OutOfCapacity" in str(e.code)):
                    ctx.log(f"第 {attempt} 次尝试: 资源不足 ({e.code})，{interval}s 后重试…")
                    for _ in range(interval):
                        if ctx.should_stop():
                            return "抢机任务已手动停止"
                        time.sleep(1)
                    continue
                raise ValueError(f"抢机失败（非容量原因）: {msg}") from e
