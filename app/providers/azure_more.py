"""v1.6：Azure 扩展功能（混入 AzureProvider）。
- 磁盘：列出 VM 的系统盘 / 数据盘，调整大小（只能扩大）、类型（Standard_LRS / StandardSSD_LRS / Premium_LRS）、
  Premium 性能层（P1~P80，只对 Premium SSD 有效）
- 重装系统：删除 VM 后用同名、同大小、原网卡（含公网 IP）和原数据盘重新创建，系统盘全新部署（旧系统盘删除）
"""
import base64

from .. import hostname
from ..extras import cloud_init, gen_password

SKUS = ("Standard_LRS", "StandardSSD_LRS", "Premium_LRS", "StandardSSD_ZRS", "Premium_ZRS")
TIERS = ("P1", "P2", "P3", "P4", "P6", "P10", "P15", "P20", "P30", "P40", "P50", "P60", "P70", "P80")


class AzureMore:
    def _disk_ref(self, disk_id):
        from .azure_provider import _name, _rg
        return _rg(disk_id), _name(disk_id)

    def disks(self, inst_id):
        rg, n = self._vm_id(inst_id)
        vm = self.compute.virtual_machines.get(rg, n)
        sp = vm.storage_profile
        refs = [("os", sp.os_disk)] + [("data", d) for d in (sp.data_disks or [])]
        out = []
        for role, d in refs:
            if not d.managed_disk or not d.managed_disk.id:
                continue
            drg, dn = self._disk_ref(d.managed_disk.id)
            disk = self.compute.disks.get(drg, dn)
            out.append({"id": disk.id, "name": disk.name, "role": role, "lun": getattr(d, "lun", None),
                        "size_gb": disk.disk_size_gb, "sku": disk.sku.name if disk.sku else None,
                        "tier": getattr(disk, "tier", None), "state": str(getattr(disk, "disk_state", "") or "")})
        return {"disks": out, "skus": list(SKUS), "tiers": list(TIERS),
                "hint": "扩大系统盘或改类型一般需要先停止（释放）VM；Azure for Students 免费额度含 2 块 64GB P6 SSD"}

    def update_disk(self, inst_id, disk_id, size_gb=None, sku=None, tier=None):
        rg, n = self._vm_id(inst_id)
        drg, dn = self._disk_ref(disk_id)
        disk = self.compute.disks.get(drg, dn)
        if disk.managed_by and disk.managed_by.lower() != self.compute.virtual_machines.get(rg, n).id.lower():
            raise RuntimeError("磁盘不属于该 VM")
        upd = {}
        if size_gb:
            if int(size_gb) < int(disk.disk_size_gb or 0):
                raise RuntimeError("Azure 磁盘只能扩大不能缩小")
            if int(size_gb) != disk.disk_size_gb:
                upd["disk_size_gb"] = int(size_gb)
        if sku:
            if sku not in SKUS:
                raise RuntimeError("磁盘类型无效")
            if not disk.sku or sku != disk.sku.name:
                upd["sku"] = {"name": sku}
        if tier:
            if tier not in TIERS:
                raise RuntimeError("性能层无效（P1~P80）")
            if (sku or (disk.sku.name if disk.sku else "")).startswith("Premium") is False:
                raise RuntimeError("性能层只对 Premium SSD 有效")
            upd["tier"] = tier
        if not upd:
            raise RuntimeError("没有要修改的项")
        self.compute.disks.begin_update(drg, dn, upd).result()
        return {"ok": True, "hint": "扩容后需在系统内扩展分区（Ubuntu 通常开机自动扩展；否则 growpart + resize2fs）" if "disk_size_gb" in upd else ""}

    def reinstall(self, inst_id, os_key="debian-12", password_login=True, ssh_key=None, progress=None):
        """重建 VM：保留网卡（含公网 IP）、数据盘、名称、大小、标签；系统盘用新镜像全新部署（走完整开机初始化，可设新密码）。"""
        from .azure_provider import IMAGES
        say = progress or (lambda m: None)
        rg, n = self._vm_id(inst_id)
        vms = self.compute.virtual_machines
        vm = vms.get(rg, n)
        pub, offer, sku, ver = IMAGES.get(os_key or "debian-12", IMAGES["debian-12"])
        od = vm.storage_profile.os_disk
        odrg, odn = self._disk_ref(od.managed_disk.id)
        old_disk = self.compute.disks.get(odrg, odn)
        nics = [x.id for x in vm.network_profile.network_interfaces]
        datas = list(vm.storage_profile.data_disks or [])
        say("把网卡和数据盘设为删除 VM 时保留…")
        for x in vm.network_profile.network_interfaces:
            x.delete_option = "Detach"
        for d in datas:
            d.delete_option = "Detach"
        vm.storage_profile.os_disk.delete_option = "Delete"
        vms.begin_create_or_update(rg, n, vm).result()
        say("删除旧 VM 与旧系统盘（网卡 / 公网 IP / 数据盘保留）…")
        vms.begin_delete(rg, n).result()
        try:
            self.compute.disks.begin_delete(odrg, odn).result()
        except Exception:
            pass
        password = gen_password() if password_login or not ssh_key else None
        name = (vm.tags or {}).get("tricloud-name") or n
        hn = hostname.normalize(name)
        os_profile = {"computer_name": hn or n[:15], "admin_username": "azureuser",
                      "custom_data": base64.b64encode(cloud_init(password, "azureuser", None, allow_password_ssh=bool(password),
                                                                 hostname=hn or None).encode()).decode()}
        if password:
            os_profile["admin_password"] = password
        if ssh_key:
            os_profile["linux_configuration"] = {"disable_password_authentication": not password, "ssh": {"public_keys": [
                {"path": "/home/azureuser/.ssh/authorized_keys", "key_data": ssh_key.strip()}]}}
        say(f"用 {offer}/{sku} 重新创建 VM…")
        new = vms.begin_create_or_update(rg, n, {
            "location": vm.location, "zones": vm.zones, "tags": vm.tags, "hardware_profile": {"vm_size": vm.hardware_profile.vm_size},
            "storage_profile": {"image_reference": {"publisher": pub, "offer": offer, "sku": sku, "version": ver},
                                "os_disk": {"create_option": "FromImage", "disk_size_gb": max(int(old_disk.disk_size_gb or 30), 30),
                                            "managed_disk": {"storage_account_type": old_disk.sku.name if old_disk.sku else "StandardSSD_LRS"},
                                            "delete_option": "Delete"},
                                "data_disks": [{"lun": d.lun, "create_option": "Attach", "managed_disk": {"id": d.managed_disk.id},
                                                "delete_option": "Detach"} for d in datas]},
            "os_profile": os_profile,
            "network_profile": {"network_interfaces": [{"id": nid, "primary": i == 0, "delete_option": "Delete"} for i, nid in enumerate(nics)]},
        }).result()
        return {"ok": True, "id": new.id, "password": password, "username": "azureuser（root 同密码）" if password else "azureuser",
                "name": name}


# ================= Foundry（Azure AI Services）：配额 / 模型 / 资源 / 部署 =================
import re as _re
import time as _time

ARM = "https://management.azure.com"
CS_API = "2024-10-01"
FOUNDRY_REGIONS = ("swedencentral", "eastus", "eastus2", "westus", "westus3", "northcentralus", "southcentralus",
                   "francecentral", "germanywestcentral", "uksouth", "westeurope", "norwayeast", "switzerlandnorth",
                   "japaneast", "koreacentral", "australiaeast", "southeastasia", "southindia", "canadaeast", "brazilsouth")
_NAME_RE = _re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{1,62}$")


class AzureFoundry:
    def _arm(self, method, path, body=None, timeout=60):
        import httpx
        tok = self.credential.get_token("https://management.azure.com/.default").token
        px = self.cred.get("proxy")
        kw = {"proxy": px} if px else {}
        url = path if path.startswith("http") else ARM + path
        r = httpx.request(method, url, headers={"Authorization": f"Bearer {tok}"}, json=body, timeout=timeout, **kw)
        if r.status_code >= 400:
            try:
                err = r.json().get("error") or {}
                msg = f"{err.get('code', r.status_code)}: {err.get('message', '')}"
            except Exception:
                msg = f"HTTP {r.status_code}: {r.text[:200]}"
            raise RuntimeError(msg[:400])
        return r.json() if r.content else {}

    def foundry_quotas(self, region):
        region = (region or "swedencentral").strip().lower()
        d = self._arm("GET", f"/subscriptions/{self.sub}/providers/Microsoft.CognitiveServices/locations/{region}/usages?api-version={CS_API}")
        out = []
        for u in d.get("value") or []:
            lim = u.get("limit") or 0
            if not lim:
                continue
            n = u.get("name") or {}
            out.append({"name": n.get("localizedValue") or n.get("value") or "", "key": n.get("value") or "",
                        "used": u.get("currentValue") or 0, "limit": lim, "unit": u.get("unit") or ""})
        out.sort(key=lambda x: (-x["used"], x["name"].lower()))
        return {"region": region, "regions": list(FOUNDRY_REGIONS), "quotas": out[:80]}

    def foundry_models(self, region):
        region = (region or "swedencentral").strip().lower()
        d = self._arm("GET", f"/subscriptions/{self.sub}/providers/Microsoft.CognitiveServices/locations/{region}/models?api-version={CS_API}")
        seen, out = set(), []
        for it in d.get("value") or []:
            m = it.get("model") or {}
            if m.get("format") not in ("OpenAI",) or (m.get("lifecycleStatus") or "").lower() == "deprecated":
                continue
            if "chatCompletion" not in (m.get("capabilities") or {}) and "embeddings" not in (m.get("capabilities") or {}):
                continue
            skus = sorted({s.get("name") for s in (m.get("skus") or []) if s.get("name")})
            k = (m.get("name"), m.get("version"))
            if k in seen or not skus:
                continue
            seen.add(k)
            out.append({"name": m.get("name"), "version": m.get("version"), "format": m.get("format"), "skus": skus,
                        "default": bool(m.get("isDefaultVersion"))})
        out.sort(key=lambda x: (x["name"], x["version"]))
        return {"region": region, "models": out}

    def foundry_resources(self):
        d = self._arm("GET", f"/subscriptions/{self.sub}/providers/Microsoft.CognitiveServices/accounts?api-version={CS_API}")
        out = []
        for a in d.get("value") or []:
            if a.get("kind") not in ("AIServices", "OpenAI"):
                continue
            rid = a["id"]
            deps = []
            try:
                for x in self._arm("GET", f"{rid}/deployments?api-version={CS_API}").get("value") or []:
                    pm = (x.get("properties") or {}).get("model") or {}
                    sku = x.get("sku") or {}
                    deps.append({"name": x.get("name"), "model": pm.get("name"), "version": pm.get("version"),
                                 "sku": sku.get("name"), "capacity": sku.get("capacity"),
                                 "state": (x.get("properties") or {}).get("provisioningState")})
            except RuntimeError:
                pass
            pr = a.get("properties") or {}
            out.append({"id": rid, "name": a.get("name"), "kind": a.get("kind"), "region": a.get("location"),
                        "resource_group": rid.split("/")[4], "sku": (a.get("sku") or {}).get("name"),
                        "endpoint": pr.get("endpoint"), "state": pr.get("provisioningState"), "deployments": deps})
        return out

    def _foundry_id(self, rid):
        rid = (rid or "").strip()
        if not _re.match(rf"^/subscriptions/{_re.escape(self.sub)}/resourceGroups/[^/]+/providers/Microsoft\.CognitiveServices/accounts/[^/]+$", rid, _re.I):
            raise RuntimeError("资源 ID 无效")
        return rid

    def foundry_keys(self, rid):
        rid = self._foundry_id(rid)
        k = self._arm("POST", f"{rid}/listKeys?api-version={CS_API}")
        a = self._arm("GET", f"{rid}?api-version={CS_API}")
        pr = a.get("properties") or {}
        sub = pr.get("customSubDomainName") or a.get("name")
        return {"endpoint": pr.get("endpoint"), "openai_base_url": f"https://{sub}.openai.azure.com/openai/v1/",
                "key1": k.get("key1"), "key2": k.get("key2")}

    def foundry_delete_deployment(self, rid, name):
        rid = self._foundry_id(rid)
        if not _NAME_RE.match(name or ""):
            raise RuntimeError("部署名称无效")
        self._arm("DELETE", f"{rid}/deployments/{name}?api-version={CS_API}")
        return {"ok": True}

    def foundry_delete_resource(self, rid):
        rid = self._foundry_id(rid)
        self._arm("DELETE", f"{rid}?api-version={CS_API}")
        return {"ok": True, "hint": "资源进入软删除状态 48 小时，期间同名资源无法重建"}

    def foundry_deploy(self, p, progress=None):
        """新建或复用 AI Services 资源并部署模型。p: resource_id | (name, region, resource_group)、model、version、sku、capacity、deployment。"""
        log = progress or (lambda m: None)
        model = (p.get("model") or "").strip()
        if not model:
            raise RuntimeError("请选择模型")
        sku = (p.get("sku") or "GlobalStandard").strip()
        if sku not in ("Standard", "GlobalStandard", "DataZoneStandard"):
            raise RuntimeError("部署类型无效")
        cap = int(p.get("capacity") or 10)
        if not 1 <= cap <= 1000:
            raise RuntimeError("容量范围 1~1000（单位：千 TPM）")
        dep = (p.get("deployment") or _re.sub(r"[^a-z0-9-]+", "-", model.lower())).strip("-")[:60]
        if not _NAME_RE.match(dep):
            raise RuntimeError("部署名称只能含字母、数字和 -")
        if p.get("resource_id"):
            rid = self._foundry_id(p["resource_id"])
            log(f"使用已有资源 {rid.split('/')[-1]}")
        else:
            name = (p.get("name") or "").strip()
            region = (p.get("region") or "swedencentral").strip().lower()
            rg = (p.get("resource_group") or f"{name}-rg").strip()
            if not _NAME_RE.match(name):
                raise RuntimeError("资源名称 2~63 位，只能含字母、数字和 -")
            if region not in FOUNDRY_REGIONS:
                raise RuntimeError("区域无效")
            log(f"创建/复用资源组 {rg}（{region}）")
            self._arm("PUT", f"/subscriptions/{self.sub}/resourcegroups/{rg}?api-version=2021-04-01", {"location": region})
            rid = f"/subscriptions/{self.sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{name}"
            log(f"创建 AI Services 资源 {name}（S0）")
            self._arm("PUT", f"{rid}?api-version={CS_API}", {"location": region, "kind": "AIServices", "sku": {"name": "S0"},
                                                               "properties": {"customSubDomainName": name.lower(), "publicNetworkAccess": "Enabled"}})
            for _ in range(60):
                st = (self._arm("GET", f"{rid}?api-version={CS_API}").get("properties") or {}).get("provisioningState")
                if st == "Succeeded":
                    break
                if st in ("Failed", "Canceled"):
                    raise RuntimeError(f"资源创建失败（{st}）")
                _time.sleep(5)
            else:
                raise RuntimeError("资源创建超时")
        body = {"sku": {"name": sku, "capacity": cap},
                "properties": {"model": {"format": "OpenAI", "name": model, **({"version": p["version"]} if p.get("version") else {})},
                               "versionUpgradeOption": "OnceNewDefaultVersionAvailable"}}
        log(f"部署模型 {model}{' ' + p['version'] if p.get('version') else ''}（{sku}，{cap}K TPM）→ {dep}")
        self._arm("PUT", f"{rid}/deployments/{dep}?api-version={CS_API}", body)
        for _ in range(60):
            st = (self._arm("GET", f"{rid}/deployments/{dep}?api-version={CS_API}").get("properties") or {}).get("provisioningState")
            if st == "Succeeded":
                break
            if st in ("Failed", "Canceled"):
                raise RuntimeError(f"模型部署失败（{st}）")
            _time.sleep(5)
        a = self._arm("GET", f"{rid}?api-version={CS_API}")
        ep = (a.get("properties") or {}).get("endpoint")
        log(f"完成：Endpoint {ep}，部署名 {dep}")
        return {"resource_id": rid, "endpoint": ep, "deployment": dep, "model": model, "sku": sku, "capacity": cap}
