"""Azure 适配。凭证: {tenant_id, client_id, client_secret, subscription_id}
停止 = deallocate（释放计算资源，不再计费）；换 IP = 重建 Public IP。
"""
import base64
import uuid

from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient

from .. import hostname
from .azure_more import AzureFoundry, AzureMore
from ..extras import cloud_init, gen_password

IMAGES = {
    "ubuntu-24.04": ("Canonical", "ubuntu-24_04-lts", "server", "latest"),
    "ubuntu-22.04": ("Canonical", "0001-com-ubuntu-server-jammy", "22_04-lts-gen2", "latest"),
    "debian-12": ("Debian", "debian-12", "12-gen2", "latest"),
}


NAME_TAG = "tricloud-name"   # Azure VM 资源名不可修改，改名写入此标签作为显示名


def _rg(resource_id):
    parts = resource_id.split("/")
    return parts[parts.index("resourceGroups") + 1]


def _name(resource_id):
    return resource_id.rstrip("/").split("/")[-1]


class AzureProvider(AzureMore, AzureFoundry):
    def __init__(self, cred, region=None):
        self.cred = cred
        self.sub = cred["subscription_id"]
        # 每账号独立出口代理
        self.kw = {"proxies": {"http": cred["proxy"], "https": cred["proxy"]}} if cred.get("proxy") else {}
        self.credential = ClientSecretCredential(cred["tenant_id"], cred["client_id"], cred["client_secret"], **self.kw)
        self.compute = ComputeManagementClient(self.credential, self.sub, **self.kw)
        self.network = NetworkManagementClient(self.credential, self.sub, **self.kw)
        self._res = None

    @property
    def res(self):
        if self._res is None:
            from azure.mgmt.resource import ResourceManagementClient
            self._res = ResourceManagementClient(self.credential, self.sub, **self.kw)
        return self._res

    # ---------- 资源组 ----------
    def resource_groups(self):
        return [{"name": g.name, "location": g.location, "state": g.properties.provisioning_state if g.properties else ""}
                for g in self.res.resource_groups.list()]

    def create_rg(self, name, location):
        g = self.res.resource_groups.create_or_update(name, {"location": location})
        return {"name": g.name, "location": g.location}

    def delete_rg(self, name):
        self.res.resource_groups.begin_delete(name)   # 异步删除组内全部资源
        return {"ok": True}

    def locations(self):
        from azure.mgmt.resource import SubscriptionClient
        sc = SubscriptionClient(self.credential, **self.kw)
        return sorted(l.name for l in sc.subscriptions.list_locations(self.sub) if getattr(l.metadata, "region_type", "") == "Physical")

    def quotas(self, location):
        """Compute 配额：总 vCPU、各系列 vCPU、公网 IP。"""
        out = []
        for u in self.compute.usage.list(location):
            n = u.name.value
            if n in ("cores", "virtualMachines", "standardBSFamily", "standardDSv2Family", "standardDASv5Family",
                     "standardDSv5Family", "standardBpsv2Family", "standardDPLDSv6Family") or n.endswith("Family") and u.current_value:
                out.append({"name": u.name.localized_value, "used": u.current_value, "limit": u.limit})
        try:
            for u in self.network.usages.list(location):
                if u.name.value in ("PublicIPAddresses", "StandardSkuPublicIpAddresses"):
                    out.append({"name": u.name.localized_value, "used": u.current_value, "limit": u.limit})
        except Exception:
            pass
        return {"location": location, "items": out}

    # ---------- 创建 VM ----------
    def create_vm(self, p, progress=None):
        """p: name, location, resource_group, size, os, disk_gb, ports, password_login, ssh_key, script, ipv6"""
        say = progress or (lambda m: None)
        name, loc = p.get("name") or f"vm-{uuid.uuid4().hex[:6]}", p["location"]
        rg = p.get("resource_group") or f"{name}-rg"
        say("创建资源组…")
        self.res.resource_groups.create_or_update(rg, {"location": loc})
        ports = sorted({22, *[int(x) for x in str(p.get("ports") or "").replace("，", ",").split(",") if x.strip().isdigit()]})
        say("创建网络安全组（默认仅放行 22）…")
        rules = [{"name": f"allow-{pt}", "protocol": "Tcp", "direction": "Inbound", "access": "Allow",
                  "priority": 1000 + i, "source_address_prefix": "*", "source_port_range": "*",
                  "destination_address_prefix": "*", "destination_port_range": str(pt)} for i, pt in enumerate(ports)]
        nsg = self.network.network_security_groups.begin_create_or_update(
            rg, f"{name}-nsg", {"location": loc, "security_rules": rules}).result()
        say("创建虚拟网络…")
        ipv6 = bool(p.get("ipv6"))
        vnet = {"location": loc, "address_space": {"address_prefixes": ["10.1.0.0/16"] + (["fd00:db8:deca::/48"] if ipv6 else [])},
                "subnets": [{"name": "default", "address_prefixes": ["10.1.0.0/24"] + (["fd00:db8:deca::/64"] if ipv6 else [])}]}
        vn = self.network.virtual_networks.begin_create_or_update(rg, f"{name}-vnet", vnet).result()
        subnet_id = vn.subnets[0].id
        say("创建公网 IP…")
        pip = self.network.public_ip_addresses.begin_create_or_update(rg, f"{name}-pip", {
            "location": loc, "sku": {"name": "Standard"}, "public_ip_allocation_method": "Static",
            "public_ip_address_version": "IPv4"}).result()
        ipcs = [{"name": "ipv4", "primary": True, "subnet": {"id": subnet_id}, "public_ip_address": {"id": pip.id}}]
        if ipv6:
            pip6 = self.network.public_ip_addresses.begin_create_or_update(rg, f"{name}-pip6", {
                "location": loc, "sku": {"name": "Standard"}, "public_ip_allocation_method": "Static",
                "public_ip_address_version": "IPv6"}).result()
            ipcs.append({"name": "ipv6", "subnet": {"id": subnet_id}, "private_ip_address_version": "IPv6",
                         "public_ip_address": {"id": pip6.id}})
        nic = self.network.network_interfaces.begin_create_or_update(rg, f"{name}-nic", {
            "location": loc, "ip_configurations": ipcs, "network_security_group": {"id": nsg.id}}).result()
        password = gen_password() if p.get("password_login", True) or not p.get("ssh_key") else None
        pub, offer, sku, ver = IMAGES.get(p.get("os") or "debian-12", IMAGES["debian-12"])
        hn = hostname.normalize(name)   # v1.5：主机名默认 = 实例名（规范化后）
        os_profile = {"computer_name": hn or name[:15], "admin_username": "azureuser",
                      "custom_data": base64.b64encode(cloud_init(password, "azureuser", p.get("script"),
                                                                 allow_password_ssh=bool(password),
                                                                 hostname=hn or None).encode()).decode()}
        if password:
            os_profile["admin_password"] = password
        if p.get("ssh_key"):
            os_profile["linux_configuration"] = {"disable_password_authentication": not password, "ssh": {"public_keys": [
                {"path": "/home/azureuser/.ssh/authorized_keys", "key_data": p["ssh_key"].strip()}]}}
        say("创建虚拟机…")
        vm = self.compute.virtual_machines.begin_create_or_update(rg, name, {
            "location": loc, "hardware_profile": {"vm_size": p.get("size") or "Standard_B1s"},
            "storage_profile": {"image_reference": {"publisher": pub, "offer": offer, "sku": sku, "version": ver},
                                "os_disk": {"create_option": "FromImage", "disk_size_gb": int(p.get("disk_gb") or 30),
                                            "managed_disk": {"storage_account_type": p.get("disk_type") or "StandardSSD_LRS"},
                                            "delete_option": "Delete"}},
            "os_profile": os_profile,
            "network_profile": {"network_interfaces": [{"id": nic.id, "primary": True, "delete_option": "Delete"}]},
        }).result()
        pip = self.network.public_ip_addresses.get(rg, f"{name}-pip")
        return {"id": vm.id, "name": vm.name, "state": "running", "public_ip": pip.ip_address,
                "password": password, "username": "azureuser（root 同密码）" if password else "azureuser"}

    def test(self):
        list(self.compute.virtual_machines.list_all())
        return {"ok": True, "subscription": self.sub}

    def regions(self):
        return []

    def _vm_id(self, inst_id):
        # inst_id 为完整资源 ID
        return _rg(inst_id), _name(inst_id)

    def _nic_info(self, vm):
        pub = priv = None
        ipv6 = []
        nics = vm.network_profile.network_interfaces if vm.network_profile else []
        for ref in nics:
            nic = self.network.network_interfaces.get(_rg(ref.id), _name(ref.id))
            for ipc in nic.ip_configurations:
                if ipc.private_ip_address_version == "IPv6":
                    ipv6.append(ipc.private_ip_address)
                elif priv is None:
                    priv = ipc.private_ip_address
                if ipc.public_ip_address:
                    p = self.network.public_ip_addresses.get(_rg(ipc.public_ip_address.id), _name(ipc.public_ip_address.id))
                    if p.public_ip_address_version == "IPv6":
                        ipv6.append(p.ip_address)
                    elif pub is None:
                        pub = p.ip_address
            break
        return pub, priv, ipv6

    def list_instances(self):
        out = []
        status = {}
        for vm in self.compute.virtual_machines.list_all(status_only="true"):
            ps = [s.code for s in (vm.instance_view.statuses if vm.instance_view else []) if s.code.startswith("PowerState/")]
            status[vm.id.lower()] = ps[0].split("/")[1] if ps else "unknown"
        for vm in self.compute.virtual_machines.list_all():
            try:
                pub, priv, ipv6 = self._nic_info(vm)
            except Exception:
                pub, priv, ipv6 = None, None, []
            out.append({"id": vm.id, "name": (vm.tags or {}).get(NAME_TAG) or vm.name, "state": status.get(vm.id.lower(), "unknown"),
                        "public_ip": pub, "private_ip": priv, "ipv6": ipv6, "shape": vm.hardware_profile.vm_size,
                        "region": vm.location, "zone": ",".join(vm.zones or []) or "-", "resource_group": _rg(vm.id), "created": str(getattr(vm, "time_created", None) or "")})
        return out

    def get_state(self, inst_id):
        rg, n = self._vm_id(inst_id)
        iv = self.compute.virtual_machines.instance_view(rg, n)
        ps = [s.code for s in iv.statuses if s.code.startswith("PowerState/")]
        return ps[0].split("/")[1] if ps else "unknown"

    def action(self, inst_id, action, wait=False):
        rg, n = self._vm_id(inst_id)
        vms = self.compute.virtual_machines
        poller = {"start": lambda: vms.begin_start(rg, n),
                  "stop": lambda: vms.begin_deallocate(rg, n),   # 停止即 deallocate
                  "reboot": lambda: vms.begin_restart(rg, n),
                  "terminate": lambda: vms.begin_delete(rg, n)}[action]()
        if wait:
            poller.result()
        return {"ok": True}

    # ---------- 改名 + 同步主机名（v1.5） ----------
    def rename(self, inst_id, name):
        """Azure 不允许修改 VM 资源名：显示名写入 tricloud-name 标签（列表优先显示）。"""
        rg, n = self._vm_id(inst_id)
        vm = self.compute.virtual_machines.get(rg, n)
        tags = dict(vm.tags or {})
        tags[NAME_TAG] = name
        self.compute.virtual_machines.begin_update(rg, n, {"tags": tags}).result()
        return {"ok": True}

    def sync_hostname(self, inst_id, h, wait=10):
        rg, n = self._vm_id(inst_id)
        vm = self.compute.virtual_machines.get(rg, n)
        sp = getattr(vm, "storage_profile", None)
        os_type = str(getattr(getattr(sp, "os_disk", None), "os_type", "") or "")
        if "windows" in os_type.lower() or getattr(getattr(vm, "os_profile", None), "windows_configuration", None):
            return {"status": "unsupported", "message": "Windows 虚拟机不支持自动同步主机名（修改计算机名需要重启），已跳过", "_manual": False}
        try:
            poller = self.compute.virtual_machines.begin_run_command(
                rg, n, {"command_id": "RunShellScript", "script": [hostname.build_cmd(h)]})
        except Exception as e:
            return {"status": "failed", "message": f"Run Command 下发失败（虚拟机需处于运行状态）：{hostname.err_text(e)}"}
        if wait:
            try:
                poller.wait(wait)
            except Exception:
                pass
        if poller.done():
            try:
                poller.result()
                return {"status": "ok", "message": f"系统主机名已改为 {h}，重新登录 SSH 可见"}
            except Exception as e:
                return {"status": "failed", "message": f"Run Command 执行失败：{hostname.err_text(e)}"}
        return {"status": "pending", "message": f"已通过 Azure Run Command 下发，通常 1 分钟内生效（主机名 {h}），重新登录 SSH 可见"}

    # ---------- 实例操作「开放端口」 ----------
    @staticmethod
    def _parse_ref(rid):
        """/subscriptions/../resourceGroups/RG/providers/../TYPE/NAME[/SUB/NAME2] -> (rg, [names...])"""
        parts = rid.strip("/").split("/")
        low = [x.lower() for x in parts]
        rg = parts[low.index("resourcegroups") + 1]
        names = parts[low.index("providers") + 3::2] if "providers" in low else [parts[-1]]
        return rg, names

    def _vm_nsgs(self, inst_id):
        """实例主网卡上的 NSG，以及该网卡所在子网的 NSG（两处都有时两处都要放行，流量才会通）。"""
        rg, n = self._vm_id(inst_id)
        vm = self.compute.virtual_machines.get(rg, n)
        refs = vm.network_profile.network_interfaces if vm.network_profile else []
        if not refs:
            raise ValueError("未找到该虚拟机的网卡")
        ref = next((r for r in refs if getattr(r, "primary", False)), refs[0])
        nic = self.network.network_interfaces.get(_rg(ref.id), _name(ref.id))
        out = []
        if nic.network_security_group:
            out.append(nic.network_security_group.id)
        ipc = (nic.ip_configurations or [None])[0]
        if ipc is not None and ipc.subnet:
            srg, names = self._parse_ref(ipc.subnet.id)
            if len(names) >= 2:
                sub = self.network.subnets.get(srg, names[0], names[1])
                if sub.network_security_group:
                    out.append(sub.network_security_group.id)
        seen, nsgs = set(), []
        for rid in out:
            if rid.lower() not in seen:
                seen.add(rid.lower())
                nsgs.append((_rg(rid), _name(rid)))
        if not nsgs:
            raise ValueError("网卡和子网都没有关联网络安全组（NSG），无法放行端口")
        return nsgs

    @staticmethod
    def _nsg_covers(r, protocol, port):
        if (r.direction or "").lower() != "inbound" or (r.access or "").lower() != "allow":
            return False
        if (r.protocol or "").lower() not in (protocol, "*"):
            return False
        srcs = [r.source_address_prefix] if r.source_address_prefix else list(r.source_address_prefixes or [])
        if not any(str(x).lower() in ("*", "0.0.0.0/0", "internet", "any") for x in srcs):
            return False
        dports = [r.destination_port_range] if r.destination_port_range else list(r.destination_port_ranges or [])
        return "*" in dports or port in dports

    def open_ports(self, inst_id, protocol, ranges):
        """写入实例网卡 / 子网的 NSG：来源 0.0.0.0/0；规则名唯一、优先级自动找空位；已放行的跳过。"""
        from azure.mgmt.network.models import SecurityRule
        groups, added_all, skipped_all = [], 0, 0
        for nrg, nname in self._vm_nsgs(inst_id):
            rules = list(self.network.security_rules.list(nrg, nname))
            names = {(r.name or "").lower() for r in rules}
            used = {r.priority for r in rules if r.priority}
            added = skipped = 0
            for a, b in ranges:
                port = str(a) if a == b else f"{a}-{b}"
                if any(self._nsg_covers(r, protocol, port) for r in rules):
                    skipped += 1
                    continue
                prio = next((x for x in range(100, 4097, 10) if x not in used), None) or \
                    next((x for x in range(100, 4097) if x not in used), None)
                if prio is None:
                    raise ValueError(f"NSG {nname} 没有空闲的优先级（100-4096 已用完）")
                base = f"tricloud-{protocol}-{port}"
                name, i = base, 2
                while name.lower() in names:
                    name, i = f"{base}-{i}", i + 1
                rule = SecurityRule(protocol=protocol.capitalize(), source_port_range="*", destination_port_range=port,
                                    source_address_prefix="0.0.0.0/0", destination_address_prefix="*", access="Allow",
                                    priority=prio, direction="Inbound", description="TriCloud open port")
                created = self.network.security_rules.begin_create_or_update(nrg, nname, name, rule).result()
                rules.append(created if created is not None else rule)
                names.add(name.lower())
                used.add(prio)
                added += 1
            groups.append({"kind": "NSG", "id": nname, "name": nname, "added": added, "skipped": skipped})
            added_all += added
            skipped_all += skipped
        return {"ok": True, "added": added_all, "skipped": skipped_all, "groups": groups}

    def change_ip(self, inst_id, progress=None):
        """解绑旧 PIP → 删除 → 新建同 SKU PIP → 绑定。"""
        rg, n = self._vm_id(inst_id)
        vm = self.compute.virtual_machines.get(rg, n)
        nic_ref = vm.network_profile.network_interfaces[0]
        nic_rg, nic_name = _rg(nic_ref.id), _name(nic_ref.id)
        nic = self.network.network_interfaces.get(nic_rg, nic_name)
        ipc = next(c for c in nic.ip_configurations if (c.primary or len(nic.ip_configurations) == 1)
                   and c.private_ip_address_version != "IPv6")
        old_ip, sku, location, alloc = None, "Standard", vm.location, "Static"
        old_pip = None
        if ipc.public_ip_address:
            old_pip = self.network.public_ip_addresses.get(_rg(ipc.public_ip_address.id), _name(ipc.public_ip_address.id))
            old_ip = old_pip.ip_address
            sku = old_pip.sku.name if old_pip.sku else "Standard"
            alloc = old_pip.public_ip_allocation_method or ("Static" if sku == "Standard" else "Dynamic")
            if progress:
                progress("解绑旧公网 IP…")
            ipc.public_ip_address = None
            self.network.network_interfaces.begin_create_or_update(nic_rg, nic_name, nic).result()
            if progress:
                progress("删除旧公网 IP…")
            self.network.public_ip_addresses.begin_delete(_rg(old_pip.id), old_pip.name).result()
        new_name = f"{n}-pip-{uuid.uuid4().hex[:5]}"
        if progress:
            progress("创建新公网 IP…")
        params = {"location": location, "sku": {"name": sku}, "public_ip_allocation_method": alloc,
                  "public_ip_address_version": "IPv4"}
        if old_pip is not None and old_pip.zones:
            params["zones"] = old_pip.zones
        pip = self.network.public_ip_addresses.begin_create_or_update(rg, new_name, params).result()
        nic = self.network.network_interfaces.get(nic_rg, nic_name)
        for c in nic.ip_configurations:
            if c.name == ipc.name:
                c.public_ip_address = pip
        self.network.network_interfaces.begin_create_or_update(nic_rg, nic_name, nic).result()
        pip = self.network.public_ip_addresses.get(rg, new_name)
        return {"old_ip": old_ip, "new_ip": pip.ip_address}

    def sizes(self, inst_id):
        rg, n = self._vm_id(inst_id)
        return [{"name": s.name, "cores": s.number_of_cores, "memory_mb": s.memory_in_mb}
                for s in self.compute.virtual_machines.list_available_sizes(rg, n)]

    def resize(self, inst_id, size):
        rg, n = self._vm_id(inst_id)
        vm = self.compute.virtual_machines.get(rg, n)
        vm.hardware_profile.vm_size = size
        self.compute.virtual_machines.begin_create_or_update(rg, n, vm).result()
        return {"ok": True}

    def billing(self):
        from azure.mgmt.costmanagement import CostManagementClient
        from azure.mgmt.costmanagement.models import (QueryAggregation, QueryDataset, QueryDefinition,
                                                      QueryGrouping)
        cm = CostManagementClient(self.credential)
        qd = QueryDefinition(type="ActualCost", timeframe="MonthToDate", dataset=QueryDataset(
            granularity="None", aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
            grouping=[QueryGrouping(type="Dimension", name="ServiceName")]))
        r = cm.query.usage(scope=f"/subscriptions/{self.sub}", parameters=qd)
        cols = [c.name for c in r.columns]
        ic, isv = cols.index("Cost"), cols.index("ServiceName")
        icur = cols.index("Currency") if "Currency" in cols else None
        services, total, cur = [], 0.0, "USD"
        for row in r.rows:
            amt = float(row[ic])
            total += amt
            if icur is not None:
                cur = row[icur]
            if abs(amt) > 0.00001:
                services.append({"service": row[isv] or "其他", "amount": round(amt, 4)})
        services.sort(key=lambda x: -x["amount"])
        return {"period": "本月至今", "currency": cur, "total": round(total, 4), "services": services}

    def wait_public_ip(self, inst_id, timeout=600):
        import time
        rg, n = self._vm_id(inst_id)
        end = time.time() + timeout
        while time.time() < end:
            try:
                pub, _, _ = self._nic_info(self.compute.virtual_machines.get(rg, n))
                if pub:
                    return pub
            except Exception:
                pass
            time.sleep(10)
        return None

    # ---------- v1.3：流量 ----------
    def traffic(self, inst_id, kind="vm", start=None, end=None):
        """本月流量（GB），Azure Monitor 平台指标（免费）。Azure 每月 100GB 出站免费。
        v1.4：传入 start/end（UTC datetime）时统计该时间窗（滚动窗口模式，按小时聚合）。"""
        import datetime as dt

        import httpx
        now = end or dt.datetime.now(dt.timezone.utc)
        win = start is not None
        start = start or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        tok = self.credential.get_token("https://management.azure.com/.default").token
        url = (f"https://management.azure.com{inst_id}/providers/Microsoft.Insights/metrics?api-version=2018-01-01"
               f"&metricnames=Network%20Out%20Total,Network%20In%20Total&aggregation=Total&interval={'PT1H' if win else 'P1D'}"
               f"&timespan={start:%Y-%m-%dT%H:%M:%SZ}/{now:%Y-%m-%dT%H:%M:%SZ}")
        px = self.cred.get("proxy")
        kw = {"proxy": px} if px else {}
        r = httpx.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=30, **kw)
        r.raise_for_status()
        res = {}
        for m in r.json().get("value", []):
            key = "out_gb" if "Out" in m["name"]["value"] else "in_gb"
            tot = sum(d.get("total") or 0 for ts in m.get("timeseries", []) for d in ts.get("data", []))
            res[key] = round(tot / 1024 ** 3, 3)
        res["period"] = f"{start:%Y-%m-%d %H:%M} ~ {now:%Y-%m-%d %H:%M} UTC" if win else f"{start:%Y-%m-%d} ~ {now:%Y-%m-%d}"
        return res

    # ---------- v1.4：订阅信息（只读） ----------
    OFFERS = {
        "AzureForStudents": "Azure for Students（学生）", "FreeTrial": "免费试用（Free Trial）", "PayAsYouGo": "即用即付（Pay-As-You-Go）",
        "MSDN": "Visual Studio 订阅", "MSDNDevTest": "Visual Studio 开发测试", "Sponsored": "Azure Sponsorship（赞助）",
        "AzurePass": "Azure Pass", "EnterpriseAgreement": "企业协议（EA）", "CSP": "云解决方案提供商（CSP）",
        "DreamSpark": "Azure for Students Starter", "Internal": "Microsoft 内部",
    }

    def subscription_info(self):
        """订阅状态、类型（quotaId → offer）、spending limit 等，来自 Subscriptions API（免费只读）。"""
        from azure.mgmt.resource import SubscriptionClient
        s = SubscriptionClient(self.credential, **self.kw).subscriptions.get(self.sub)
        pol = getattr(s, "subscription_policies", None)
        quota = getattr(pol, "quota_id", None) or ""
        key = quota.split("_")[0]
        val = lambda x: str(getattr(x, "value", x)) if x is not None else None
        return {"subscription_id": self.sub, "display_name": s.display_name, "state": val(s.state),
                "quota_id": quota or None, "offer": self.OFFERS.get(key, key or None),
                "spending_limit": val(getattr(pol, "spending_limit", None)),
                "location_placement_id": getattr(pol, "location_placement_id", None),
                "authorization_source": getattr(s, "authorization_source", None),
                "tenant_id": getattr(s, "tenant_id", None) or self.cred.get("tenant_id")}
