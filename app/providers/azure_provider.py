"""Azure provider：虚拟机管理（azure-mgmt-* SDK）。"""
import logging
import random
import string
import time

from azure.core.exceptions import HttpResponseError
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource.resources import ResourceManagementClient
from azure.mgmt.subscription import SubscriptionClient

from .base import AccountField, InstanceInfo, Provider

log = logging.getLogger(__name__)

VM_SIZES = [
    "Standard_B1s", "Standard_B1ms", "Standard_B2s", "Standard_B2ms",
    "Standard_D2s_v3", "Standard_D2as_v5", "Standard_E2s_v3",
]
IMAGES = {
    "Ubuntu 22.04 LTS": {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy",
                         "sku": "22_04-lts", "version": "latest", "os": "linux"},
    "Debian 12": {"publisher": "Debian", "offer": "debian-12",
                  "sku": "12", "version": "latest", "os": "linux"},
    "Windows Server 2022": {"publisher": "MicrosoftWindowsServer", "offer": "WindowsServer",
                            "sku": "2022-datacenter-azure-edition", "version": "latest",
                            "os": "windows"},
}

_POWER_MAP = {
    "PowerState/running": "running",
    "PowerState/stopped": "stopped",
    "PowerState/deallocated": "stopped",
    "PowerState/deallocating": "stopping",
    "PowerState/stopping": "stopping",
    "PowerState/starting": "pending",
}


def _parse_id(resource_id: str) -> dict:
    parts = resource_id.strip("/").split("/")
    d = {}
    for i in range(0, len(parts) - 1, 2):
        d[parts[i].lower()] = parts[i + 1]
    return d


def _credential(creds: dict) -> ClientSecretCredential:
    return ClientSecretCredential(
        tenant_id=creds["tenant_id"].strip(),
        client_id=creds["client_id"].strip(),
        client_secret=creds["client_secret"],
    )


def _clients(creds: dict):
    cred = _credential(creds)
    sub = creds["subscription_id"].strip()
    return (
        ComputeManagementClient(cred, sub),
        NetworkManagementClient(cred, sub),
        ResourceManagementClient(cred, sub),
    )


def _gen_password(length=16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(random.choice(alphabet) for _ in range(length))
        cats = sum([any(c.islower() for c in pwd), any(c.isupper() for c in pwd),
                    any(c.isdigit() for c in pwd), any(c in "!@#$%^&*" for c in pwd)])
        if cats >= 3:
            return pwd


class AzureProvider(Provider):
    id = "azure"
    name = "Microsoft Azure"
    fields = [
        AccountField("tenant_id", "租户 ID (Tenant ID)"),
        AccountField("client_id", "客户端 ID (Client ID)", help="服务主体的应用 ID"),
        AccountField("client_secret", "客户端密码 (Client Secret)", field_type="password"),
        AccountField("subscription_id", "订阅 ID (Subscription ID)"),
    ]
    actions = [
        {"key": "start", "label": "启动"},
        {"key": "stop", "label": "停止（释放资源）"},
        {"key": "reboot", "label": "重启"},
        {"key": "terminate", "label": "删除", "danger": True},
        {"key": "change_ip", "label": "更换公网 IP"},
        {"key": "open_port", "label": "开放端口"},
        {"key": "extend_disk", "label": "磁盘扩容"},
        {"key": "reimage", "label": "重置系统", "danger": True},
    ]
    supports_quotas = True
    supports_billing = True

    def get_billing(self, creds: dict) -> dict:
        """Azure 账单：Cost Management 查询当月实际费用，按服务分组。
        需要服务主体在订阅上有 Cost Management Reader（或更高）角色。
        """
        import json
        import urllib.request
        import urllib.error
        cred = _credential(creds)
        sub = creds["subscription_id"].strip()
        try:
            token = cred.get_token("https://management.azure.com/.default").token
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"获取 Azure 令牌失败: {e}") from e
        url = (f"https://management.azure.com/subscriptions/{sub}"
               f"/providers/Microsoft.CostManagement/query?api-version=2023-11-01")
        body = json.dumps({
            "type": "ActualCost",
            "timeframe": "MonthToDate",
            "dataset": {
                "granularity": "None",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "ServiceName"}],
            },
        }).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (401, 403):
                raise ValueError(
                    "无 Cost Management 查询权限：请给服务主体分配订阅的 "
                    f"Cost Management Reader 角色 ({detail})") from e
            raise ValueError(f"Cost Management 查询失败 ({e.code}): {detail}") from e
        props = data.get("properties", {})
        cols = [c.get("name") for c in props.get("columns", [])]
        rows = props.get("rows", [])
        ci_cost, ci_svc, ci_cur = cols.index("Cost"), cols.index("ServiceName"), cols.index("Currency")
        services, total, currency = [], 0.0, ""
        for r in rows:
            cost = float(r[ci_cost] or 0)
            total += cost
            currency = currency or r[ci_cur] or ""
            services.append({"name": r[ci_svc] or "其他", "cost": round(cost, 4)})
        services.sort(key=lambda x: -x["cost"])
        return {
            "currency": currency or "USD",
            "period": "本月至今 (MonthToDate)",
            "total": round(total, 4),
            "services": services,
            "note": "实际费用（ActualCost）；数据可能有数小时延迟",
        }

    def test(self, creds: dict) -> None:
        _, _, resource = _clients(creds)
        next(resource.resource_groups.list(), None)

    def _power_state(self, compute, rg: str, name: str) -> tuple[str, str]:
        try:
            iv = compute.virtual_machines.instance_view(rg, name)
            for s in iv.statuses or []:
                if s.code and s.code.startswith("PowerState/"):
                    return _POWER_MAP.get(s.code, "unknown"), s.code
        except HttpResponseError as e:
            log.warning("instance_view %s failed: %s", name, e)
        return "unknown", ""

    def list_instances(self, creds: dict) -> list[InstanceInfo]:
        compute, network, _ = _clients(creds)
        result = []
        for vm in compute.virtual_machines.list_all():
            parsed = _parse_id(vm.id)
            rg = parsed.get("resourcegroups", "")
            name = vm.name
            power, power_text = self._power_state(compute, rg, name)
            public_ip, private_ip = "", ""
            try:
                nics = vm.network_profile.network_interfaces if vm.network_profile else []
                if nics:
                    nic_parsed = _parse_id(nics[0].id)
                    nic = network.network_interfaces.get(
                        nic_parsed.get("resourcegroups", rg), nic_parsed.get("networkinterfaces", ""))
                    for ipc in nic.ip_configurations or []:
                        private_ip = ipc.private_ip_address or private_ip
                        if ipc.public_ip_address:
                            pip_parsed = _parse_id(ipc.public_ip_address.id)
                            pip = network.public_ip_addresses.get(
                                pip_parsed.get("resourcegroups", rg),
                                pip_parsed.get("publicipaddresses", ""))
                            public_ip = pip.ip_address or ""
            except HttpResponseError as e:
                log.warning("nic info %s failed: %s", name, e)
            hw = vm.hardware_profile.vm_size if vm.hardware_profile else ""
            result.append(InstanceInfo(
                id=vm.id, name=name, status=power, status_text=power_text,
                shape=hw, public_ip=public_ip, private_ip=private_ip,
                region=vm.location, zone="",
                created="",
                extra={"resource_group": rg, "vm_name": name},
            ))
        return result

    def instance_action(self, creds: dict, inst: InstanceInfo, action: str, ctx) -> str:
        compute, network, _ = _clients(creds)
        rg = inst.extra.get("resource_group") or _parse_id(inst.id).get("resourcegroups", "")
        name = inst.extra.get("vm_name") or inst.name
        if action == "start":
            compute.virtual_machines.begin_start(rg, name).result()
            return "虚拟机已启动"
        if action == "stop":
            ctx.log("正在释放资源（deallocate），完成后停止计费…")
            compute.virtual_machines.begin_deallocate(rg, name).result()
            return "虚拟机已停止并释放资源"
        if action == "reboot":
            compute.virtual_machines.begin_restart(rg, name).result()
            return "重启请求已提交"
        if action == "terminate":
            compute.virtual_machines.begin_delete(rg, name).result()
            return "虚拟机删除请求已提交"
        if action == "change_ip":
            return self._change_ip(network, rg, name, ctx)
        if action == "open_port":
            return self._open_port(compute, network, rg, name, ctx)
        if action == "extend_disk":
            return self._extend_disk(compute, rg, name, ctx)
        if action == "reimage":
            ctx.log("正在重置系统（重装镜像），虚拟机数据盘保留、系统盘还原…")
            compute.virtual_machines.begin_reimage(rg, name).result()
            return "重置系统请求已提交，完成后需重新配置系统"
        raise ValueError(f"未知操作: {action}")

    def _find_nic(self, network, rg: str, vm_name: str):
        for nic in network.network_interfaces.list(rg):
            if nic.virtual_machine and vm_name in (nic.virtual_machine.id or ""):
                parsed = _parse_id(nic.id)
                return network.network_interfaces.get(
                    rg, parsed.get("networkinterfaces", ""))
        raise ValueError("未找到该虚拟机的网卡")

    def _open_port(self, compute, network, rg: str, vm_name: str, ctx) -> str:
        port = int((getattr(ctx, "params", {}) or {}).get("port") or 0)
        if not (1 <= port <= 65535):
            raise ValueError("请提供有效端口 1-65535")
        nic = self._find_nic(network, rg, vm_name)
        nsg_ref = nic.network_security_group
        nsg_rg, nsg_name = rg, ""
        if nsg_ref:
            p = _parse_id(nsg_ref.id)
            nsg_rg, nsg_name = p.get("resourcegroups", rg), p.get("networksecuritygroups", "")
        else:
            # 回退到子网上的 NSG
            subnet_ref = (nic.ip_configurations or [None])[0].subnet if nic.ip_configurations else None
            if subnet_ref:
                sp = _parse_id(subnet_ref.id)
                subnet = network.subnets.get(sp.get("resourcegroups", rg),
                                             sp.get("virtualnetworks", ""),
                                             sp.get("subnets", ""))
                if subnet.network_security_group:
                    p = _parse_id(subnet.network_security_group.id)
                    nsg_rg, nsg_name = p.get("resourcegroups", rg), p.get("networksecuritygroups", "")
        if not nsg_name:
            raise ValueError("网卡/子网均未关联网络安全组，无法放行端口")
        rules = list(network.security_rules.list(nsg_rg, nsg_name))
        for r in rules:
            if (r.destination_port_range == str(port) and r.access == "Allow"
                    and r.direction == "Inbound" and r.protocol in ("Tcp", "*")):
                return f"端口 {port} 已在 NSG 放行，无需重复操作"
        prio = 100
        used = {r.priority for r in rules if r.priority}
        while prio in used and prio < 4096:
            prio += 10
        from azure.mgmt.network.models import SecurityRule
        poller = network.security_rules.begin_create_or_update(
            nsg_rg, nsg_name, f"tricloud-open-{port}",
            SecurityRule(protocol="Tcp", source_port_range="*",
                         destination_port_range=str(port),
                         source_address_prefix="*", destination_address_prefix="*",
                         access="Allow", priority=prio, direction="Inbound"))
        poller.result()
        return f"已在 NSG {nsg_name} 放行 TCP 端口 {port}（来源 *）"

    def _extend_disk(self, compute, rg: str, vm_name: str, ctx) -> str:
        size = int((getattr(ctx, "params", {}) or {}).get("size_gb") or 0)
        if size <= 0:
            raise ValueError("请提供目标磁盘大小（GB）")
        vm = compute.virtual_machines.get(rg, vm_name)
        disk_ref = (vm.storage_profile.os_disk.managed_disk
                    if vm.storage_profile and vm.storage_profile.os_disk else None)
        if not disk_ref or not disk_ref.id:
            raise ValueError("未找到系统托管磁盘")
        p = _parse_id(disk_ref.id)
        d_rg, d_name = p.get("resourcegroups", rg), p.get("disks", "")
        disk = compute.disks.get(d_rg, d_name)
        cur = disk.disk_size_gb or 0
        if size <= cur:
            raise ValueError(f"目标大小 {size}GB 必须大于当前 {cur}GB（只支持扩容）")
        ctx.log(f"磁盘 {d_name} {cur}GB → {size}GB…")
        from azure.mgmt.compute.models import DiskUpdate
        compute.disks.begin_create_or_update(d_rg, d_name, DiskUpdate(disk_size_gb=size)).result()
        return f"磁盘扩容已提交: {cur}GB → {size}GB（系统内需手动扩展分区）"

    def get_quotas(self, creds: dict) -> dict:
        """配额查询：各区域计算资源用量/上限。"""
        compute, _, _ = _clients(creds)
        try:
            vms = list(compute.virtual_machines.list_all())
        except HttpResponseError as e:
            raise ValueError(f"查询实例失败: {e}") from e
        locations = sorted({vm.location for vm in vms if vm.location}) or ["japaneast"]
        groups = []
        for loc in locations[:4]:
            try:
                usages = list(compute.usage.list(loc))
            except HttpResponseError as e:
                log.warning("quota %s failed: %s", loc, e)
                continue
            items = []
            for u in usages:
                name = (u.name.localized_value or u.name.value or "")
                if u.limit and u.limit > 0 and ("virtual machines" in name.lower()
                                                or "cores" in name.lower()):
                    items.append({"name": name,
                                  "detail": f"已用 {u.current_value}/{u.limit}"})
            if items:
                groups.append({"title": f"计算配额 · {loc}", "items": items[:10]})
        return {
            "groups": groups,
            "note": "为各区域 vCPU/虚拟机数量配额；详情见 Azure 门户订阅-用量+配额页",
        }

    def _change_ip(self, network, rg: str, vm_name: str, ctx) -> str:
        # 通过 VM 找到主网卡
        nic_id = None
        # 简化：按命名约定查找该 VM 的网卡（创建时我们按固定规则命名）
        for nic in network.network_interfaces.list(rg):
            if nic.virtual_machine and vm_name in (nic.virtual_machine.id or ""):
                nic_id = nic.id
                break
        if not nic_id:
            raise ValueError("未找到该虚拟机的网卡")
        nic_parsed = _parse_id(nic_id)
        nic = network.network_interfaces.get(rg, nic_parsed["networkinterfaces"])
        ipc = nic.ip_configurations[0]
        if not ipc.public_ip_address:
            raise ValueError("该网卡未绑定公网 IP")
        pip_parsed = _parse_id(ipc.public_ip_address.id)
        pip_name = pip_parsed["publicipaddresses"]
        old_pip = network.public_ip_addresses.get(rg, pip_name)
        ctx.log(f"解绑并删除公网 IP {old_pip.ip_address}…")
        ipc.public_ip_address = None
        network.network_interfaces.begin_create_or_update(rg, nic.name, nic).result()
        network.public_ip_addresses.begin_delete(rg, pip_name).result()
        for _ in range(60):
            try:
                network.public_ip_addresses.get(rg, pip_name)
                time.sleep(5)
            except HttpResponseError:
                break
        new_pip_name = f"{pip_name}-new"
        ctx.log("创建新的公网 IP…")
        poller = network.public_ip_addresses.begin_create_or_update(
            rg, new_pip_name,
            {"location": old_pip.location,
             "sku": {"name": "Standard"},
             "public_ip_allocation_method": "Static"})
        new_pip = poller.result()
        ipc.public_ip_address = {"id": new_pip.id}
        network.network_interfaces.begin_create_or_update(rg, nic.name, nic).result()
        return f"公网 IP 更换成功，新 IP: {new_pip.ip_address}"

    def create_options(self, creds: dict) -> dict:
        cred = _credential(creds)
        sub_client = SubscriptionClient(cred)
        locations = [loc.name for loc in
                     sub_client.subscriptions.list_locations(creds["subscription_id"].strip())]
        return {
            "locations": sorted(locations),
            "vm_sizes": VM_SIZES,
            "images": list(IMAGES.keys()),
        }

    def create_instance(self, creds: dict, params: dict, ctx) -> str:
        compute, network, resource = _clients(creds)
        location = params.get("location") or "japaneast"
        vm_name = params.get("name") or f"vm-{random.randint(1000, 9999)}"
        rg_name = (params.get("resource_group") or f"{vm_name}-rg").strip()
        size = params.get("vm_size", "Standard_B1s")
        image_label = params.get("image", "Ubuntu 22.04 LTS")
        image = IMAGES.get(image_label, IMAGES["Ubuntu 22.04 LTS"])
        admin_user = params.get("admin_username") or "azureuser"
        password = (params.get("password") or "").strip() or _gen_password()
        ssh_key = (params.get("ssh_key") or "").strip()

        ctx.log(f"创建资源组 {rg_name}…")
        resource.resource_groups.create_or_update(rg_name, {"location": location})

        base = vm_name.replace("_", "-")
        vnet_name, subnet_name = f"{base}-vnet", f"{base}-subnet"
        nsg_name, pip_name, nic_name = f"{base}-nsg", f"{base}-pip", f"{base}-nic"

        ctx.log("创建虚拟网络/子网/安全组…")
        network.virtual_networks.begin_create_or_update(
            rg_name, vnet_name,
            {"location": location,
             "address_space": {"address_prefixes": ["10.0.0.0/16"]}}).result()
        nsg_poller = network.network_security_groups.begin_create_or_update(
            rg_name, nsg_name,
            {"location": location,
             "security_rules": [{
                 "name": "allow-ssh", "protocol": "Tcp",
                 "source_port_range": "*", "destination_port_range": "22",
                 "source_address_prefix": "*", "destination_address_prefix": "*",
                 "access": "Allow", "priority": 1000, "direction": "Inbound"}]})
        nsg = nsg_poller.result()
        subnet_poller = network.subnets.begin_create_or_update(
            rg_name, vnet_name, subnet_name,
            {"address_prefix": "10.0.0.0/24",
             "network_security_group": {"id": nsg.id}})
        subnet = subnet_poller.result()

        ctx.log("创建公网 IP 和网卡…")
        pip = network.public_ip_addresses.begin_create_or_update(
            rg_name, pip_name,
            {"location": location, "sku": {"name": "Standard"},
             "public_ip_allocation_method": "Static"}).result()
        nic = network.network_interfaces.begin_create_or_update(
            rg_name, nic_name,
            {"location": location,
             "ip_configurations": [{
                 "name": "ipconfig1",
                 "subnet": {"id": subnet.id},
                 "public_ip_address": {"id": pip.id}}]}).result()

        ctx.log(f"正在创建虚拟机 {vm_name} ({size})，约需 2-4 分钟…")
        os_profile = {"computer_name": vm_name, "admin_username": admin_user}
        if image["os"] == "linux" and ssh_key:
            os_profile["linux_configuration"] = {
                "disable_password_authentication": False,
                "ssh": {"public_keys": [{
                    "path": f"/home/{admin_user}/.ssh/authorized_keys",
                    "key_data": ssh_key}]}}
        else:
            os_profile["admin_password"] = password
        vm_params = {
            "location": location,
            "hardware_profile": {"vm_size": size},
            "storage_profile": {
                "image_reference": {
                    "publisher": image["publisher"], "offer": image["offer"],
                    "sku": image["sku"], "version": image["version"]},
                "os_disk": {
                    "create_option": "FromImage",
                    "managed_disk": {"storage_account_type": "Standard_LRS"},
                    "disk_size_gb": int(params.get("disk_gb") or 30)}},
            "os_profile": os_profile,
            "network_profile": {"network_interfaces": [{"id": nic.id, "primary": True}]},
        }
        poller = compute.virtual_machines.begin_create_or_update(rg_name, vm_name, vm_params)
        poller.result()
        pip = network.public_ip_addresses.get(rg_name, pip_name)
        text = (f"虚拟机创建成功: {vm_name}\n"
                f"资源组: {rg_name}\n"
                f"公网 IP: {pip.ip_address or '（分配中）'}\n"
                f"登录用户: {admin_user}\n"
                f"密码: {password}（仅显示一次，请妥善保存）")
        if ssh_key:
            text += "\n已注入 SSH 公钥"
        return text
