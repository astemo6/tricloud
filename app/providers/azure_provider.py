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
    ]

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
        raise ValueError(f"未知操作: {action}")

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
