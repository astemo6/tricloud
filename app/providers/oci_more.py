"""v1.6：OCI 扩展功能（混入 OCIProvider）。
- 重装系统：替换引导卷（实例 OCID、私网 IP、公网 IP 不变）
- 块存储卷：列出 / 创建 / 挂载 / 卸载 / 调整容量与 VPU / 删除；扩容后可用 Run Command 执行固定的扩分区命令
- 区域订阅：列出全部区域与已订阅区域，订阅新区域（不可撤销，需确认）
- 附加 IP：辅助私网 IP + 临时公网 IP、预留公网 IP（创建 / 绑定 / 解绑 / 删除）、辅助网卡（挂载 / 卸载）
- 账号类型：Subscription（osp_gateway）里的 plan_type / account_type / upgrade_state
- 免费 AMD 下行 500Mbps：网络负载均衡器（NLB）入站 + NAT 网关出站（参考 oci-helper 的公开实现），可关闭还原
- 对象存储：Bucket 列表 / 创建 / 删除，对象列表 / 上传 / 下载（预认证链接）/ 删除
- 免费额度体检：A1 OCPU / 内存、E2.1.Micro 台数、块存储总量与 Always Free 额度对比
所有改动都只调用 OCI 官方 SDK；不在实例里执行任意命令（Run Command 只下发本文件里的固定脚本）。
"""
import base64
import datetime as dt
import hashlib
import re
import time

import oci

from ..cloudinit import cloud_init, gen_password

FREE = {"a1_ocpus": 2, "a1_mem": 12, "micro": 2, "storage_gb": 200, "object_gb": 20, "nlb": 1}
A1 = "VM.Standard.A1.Flex"
MICRO = "VM.Standard.E2.1.Micro"
NLB_PREFIX = "tricloud-500m"
VPUS = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120)

# 扩容后扩展分区：只扩根分区（引导卷）或对数据盘做在线 rescan；固定脚本，不拼接任何用户输入
GROW_ROOT = ("ROOT=$(findmnt -n -o SOURCE /); DEV=/dev/$(lsblk -no PKNAME \"$ROOT\" | head -n1); "
             "PART=$(echo \"$ROOT\" | grep -o '[0-9]*$'); "
             "for f in /sys/class/block/*/device/rescan; do echo 1 > \"$f\" 2>/dev/null; done; "
             "command -v growpart >/dev/null || (apt-get install -y cloud-guest-utils >/dev/null 2>&1 || "
             "yum install -y cloud-utils-growpart >/dev/null 2>&1 || dnf install -y cloud-utils-growpart >/dev/null 2>&1); "
             "growpart \"$DEV\" \"$PART\" || true; "
             "FS=$(findmnt -n -o FSTYPE /); if [ \"$FS\" = xfs ]; then xfs_growfs /; else resize2fs \"$ROOT\"; fi; df -h /")
RESCAN = "for f in /sys/class/block/*/device/rescan; do echo 1 > \"$f\" 2>/dev/null; done; lsblk"


def as_root(c):
    """c 是本文件里的固定脚本（只含双引号）。非 root（OCI 的 ocarun）用 sudo -n 提权。"""
    c = c.replace("'", "'\\''")
    return f"if [ \"$(id -u)\" = 0 ]; then sh -c '{c}'; else sudo -n sh -c '{c}'; fi"


def _v(x):
    return str(getattr(x, "value", x)) if x is not None else None


class OCIMore:
    # ================= 通用：Run Command 固定脚本 =================
    def run_fixed(self, inst_id, script, name="tricloud-cmd", wait=20):
        M = oci.compute_instance_agent.models
        st = self._run_cmd_plugin_state(inst_id)
        if st and st != "RUNNING":
            return {"status": "failed", "message": f"Oracle Cloud Agent 的「{self.RUN_CMD_PLUGIN}」插件未运行（{st}）"}
        det = M.CreateInstanceAgentCommandDetails(
            compartment_id=self.compartment, execution_time_out_in_seconds=300, display_name=name,
            target=M.InstanceAgentCommandTarget(instance_id=inst_id),
            content=M.InstanceAgentCommandContent(source=M.InstanceAgentCommandSourceViaTextDetails(
                source_type="TEXT", text=as_root(script))))
        try:
            cmd = self.agent.create_instance_agent_command(det).data
        except Exception as e:
            return {"status": "failed", "message": f"Run Command 下发失败：{str(getattr(e, 'message', e))[:200]}"}
        end = time.time() + max(0, wait or 0)
        while time.time() < end:
            time.sleep(3)
            try:
                ex = self.agent.get_instance_agent_command_execution(cmd.id, inst_id).data
            except Exception:
                continue
            ls = (ex.lifecycle_state or "").upper()
            if ls == "SUCCEEDED":
                code = getattr(getattr(ex, "content", None), "exit_code", 0)
                out = getattr(getattr(ex, "content", None), "text", "") or ""
                return {"status": "ok" if code in (0, None) else "failed", "message": out[-800:] or f"exit {code}"}
            if ls in ("FAILED", "TIMED_OUT", "CANCELED"):
                return {"status": "failed", "message": f"命令执行 {ls}（插件未开启或 ocarun 无 sudo 权限）"}
        return {"status": "pending", "message": "已下发，稍后在系统内确认", "command_id": cmd.id}

    # ================= 3. 重装系统 =================
    def reinstall(self, inst_id, os_name="Canonical Ubuntu", os_version=None, image_id=None, disk_gb=None,
                  password_login=True, ssh_key=None, progress=None):
        """替换引导卷：实例 OCID / 私网 IP / 公网 IP 不变，引导卷数据全部清空（旧卷不保留）。"""
        say = progress or (lambda m: None)
        inst = self.compute.get_instance(inst_id).data
        img = self._pick_image(inst.shape, os_name or "Canonical Ubuntu", os_version or None, image_id)
        cur = None
        try:
            cur = self.boot_volume(inst_id)["size_gb"]
        except Exception:
            pass
        size = int(disk_gb or cur or 50)
        if cur and size < cur:
            raise RuntimeError(f"新引导卷不能小于当前 {cur} GB")
        password = gen_password() if password_login else None
        md = dict(inst.metadata or {})
        key = ssh_key or md.get("ssh_authorized_keys") or self.cred.get("default_ssh_key")
        if key:
            md["ssh_authorized_keys"] = key
        from .. import hostname
        hn = hostname.normalize(inst.display_name) or None
        md["user_data"] = base64.b64encode(cloud_init(password, "root", None, allow_password_ssh=bool(password),
                                                      hostname=hn).encode()).decode()
        say(f"替换引导卷：{os_name} {os_version or '最新'}，{size} GB（实例会停机，约 3-10 分钟）…")
        self.compute.update_instance(inst_id, oci.core.models.UpdateInstanceDetails(
            metadata=md, source_details=oci.core.models.UpdateInstanceSourceViaImageDetails(
                image_id=img, boot_volume_size_in_gbs=size, is_preserve_boot_volume_enabled=False)))
        return {"ok": True, "image_id": img, "password": password, "username": "root" if password else None,
                "name": inst.display_name, "size_gb": size}

    # ================= 6. 块存储卷 =================
    def _vol_view(self, v, att=None):
        return {"id": v.id, "name": v.display_name, "size_gb": v.size_in_gbs, "vpus_per_gb": v.vpus_per_gb,
                "state": v.lifecycle_state, "ad": v.availability_domain,
                "attached_to": getattr(att, "instance_id", None), "attachment_id": getattr(att, "id", None),
                "device": getattr(att, "device", None), "attach_type": getattr(att, "attachment_type", None)}

    def volumes(self):
        atts = {}
        for a in oci.pagination.list_call_get_all_results(self.compute.list_volume_attachments,
                                                          compartment_id=self.compartment).data:
            if a.lifecycle_state in ("ATTACHED", "ATTACHING"):
                atts[a.volume_id] = a
        out = []
        for ad in self.availability_domains():
            for v in oci.pagination.list_call_get_all_results(self.bs.list_volumes, availability_domain=ad,
                                                             compartment_id=self.compartment).data:
                if v.lifecycle_state in ("TERMINATED", "TERMINATING"):
                    continue
                out.append(self._vol_view(v, atts.get(v.id)))
        boots = []
        for ad in self.availability_domains():
            for b in oci.pagination.list_call_get_all_results(self.bs.list_boot_volumes, availability_domain=ad,
                                                             compartment_id=self.compartment).data:
                if b.lifecycle_state not in ("TERMINATED", "TERMINATING"):
                    boots.append({"id": b.id, "name": b.display_name, "size_gb": b.size_in_gbs, "vpus_per_gb": b.vpus_per_gb,
                                  "state": b.lifecycle_state})
        used = sum(int(x["size_gb"] or 0) for x in out + boots)
        return {"volumes": out, "boot_volumes": boots, "used_gb": used, "free_gb": FREE["storage_gb"]}

    def create_volume(self, name, size_gb, vpus_per_gb=10, instance_id=None, ad=None):
        size = int(size_gb)
        if size < 50 or size > 32768:
            raise RuntimeError("块存储卷容量范围 50 ~ 32768 GB")
        if int(vpus_per_gb) not in VPUS:
            raise RuntimeError("VPU 需为 0~120 的 10 的倍数")
        if instance_id:
            ad = self.compute.get_instance(instance_id).data.availability_domain
        ad = ad or self.availability_domains()[0]
        v = self.bs.create_volume(oci.core.models.CreateVolumeDetails(
            compartment_id=self.compartment, availability_domain=ad, display_name=name or "tricloud-vol",
            size_in_gbs=size, vpus_per_gb=int(vpus_per_gb))).data
        res = {"ok": True, "id": v.id, "name": v.display_name}
        if instance_id:
            for _ in range(40):
                if self.bs.get_volume(v.id).data.lifecycle_state == "AVAILABLE":
                    break
                time.sleep(3)
            res["attach"] = self.attach_volume(v.id, instance_id)
        return res

    def attach_volume(self, vol_id, instance_id):
        a = self.compute.attach_volume(oci.core.models.AttachParavirtualizedVolumeDetails(
            type="paravirtualized", instance_id=instance_id, volume_id=vol_id, display_name="tricloud")).data
        return {"ok": True, "attachment_id": a.id,
                "hint": "半虚拟化挂载，系统内用 lsblk 查看新盘（通常是 /dev/sdb），首次使用需自行分区和格式化"}

    def detach_volume(self, attachment_id):
        self.compute.detach_volume(attachment_id)
        return {"ok": True, "hint": "建议先在系统内 umount 并移除 /etc/fstab 中的条目"}

    def update_volume(self, vol_id, size_gb=None, vpus_per_gb=None):
        v = self.bs.get_volume(vol_id).data
        d = {}
        if size_gb:
            if int(size_gb) < v.size_in_gbs:
                raise RuntimeError("块存储卷只能扩容不能缩小")
            if int(size_gb) != v.size_in_gbs:
                d["size_in_gbs"] = int(size_gb)
        if vpus_per_gb not in (None, ""):
            if int(vpus_per_gb) not in VPUS:
                raise RuntimeError("VPU 需为 0~120 的 10 的倍数")
            d["vpus_per_gb"] = int(vpus_per_gb)
        if not d:
            raise RuntimeError("没有要修改的项")
        self.bs.update_volume(vol_id, oci.core.models.UpdateVolumeDetails(**d))
        return {"ok": True, "expanded": "size_in_gbs" in d}

    def delete_volume(self, vol_id):
        v = self.bs.get_volume(vol_id).data
        for a in self.compute.list_volume_attachments(compartment_id=self.compartment, volume_id=vol_id).data:
            if a.lifecycle_state in ("ATTACHED", "ATTACHING"):
                raise RuntimeError("卷仍挂载在实例上，请先卸载")
        self.bs.delete_volume(vol_id)
        return {"ok": True, "name": v.display_name}

    def grow_fs(self, inst_id, root=True):
        return self.run_fixed(inst_id, GROW_ROOT if root else RESCAN, "tricloud-growfs", wait=30)

    # ================= 7. 区域订阅 =================
    def region_subscriptions(self):
        subs = self.identity.list_region_subscriptions(self.cfg["tenancy"]).data
        allr = self.identity.list_regions().data
        have = {s.region_name: s for s in subs}
        home = next((s.region_name for s in subs if s.is_home_region), None)
        return {"home": home, "limit_hint": "免费账号通常只能订阅 1 个额外区域；Always Free 资源只在主区域",
                "regions": [{"name": r.name, "key": r.key, "subscribed": r.name in have,
                             "status": _v(getattr(have.get(r.name), "status", None)), "home": r.name == home}
                            for r in sorted(allr, key=lambda r: r.name)]}

    def subscribe_region(self, region_key):
        if not re.fullmatch(r"[A-Z]{3}", str(region_key or "")):
            raise RuntimeError("区域 key 不合法（如 NRT、ICN）")
        subs = self.identity.list_region_subscriptions(self.cfg["tenancy"]).data
        home = next((s.region_name for s in subs if s.is_home_region), self.cfg["region"])
        idc = self._c(oci.identity.IdentityClient, dict(self.cfg, region=home))   # 只能在主区域调用
        r = idc.create_region_subscription(oci.identity.models.CreateRegionSubscriptionDetails(region_key=region_key),
                                           self.cfg["tenancy"]).data
        return {"ok": True, "region": r.region_name, "status": _v(r.status)}

    # ================= 8. 附加 IP / 辅助网卡 / 预留 IP =================
    def ip_overview(self, inst_id):
        atts = oci.pagination.list_call_get_all_results(
            self.compute.list_vnic_attachments, compartment_id=self.compartment, instance_id=inst_id).data
        vnics = []
        for a in atts:
            if a.lifecycle_state != "ATTACHED":
                continue
            v = self.vnet.get_vnic(a.vnic_id).data
            ips = []
            for p in self.vnet.list_private_ips(vnic_id=v.id).data:
                pub = None
                try:
                    pi = self.vnet.get_public_ip_by_private_ip_id(
                        oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=p.id)).data
                    pub = {"id": pi.id, "ip": pi.ip_address, "lifetime": pi.lifetime}
                except oci.exceptions.ServiceError:
                    pass
                ips.append({"id": p.id, "ip": p.ip_address, "primary": p.is_primary, "public": pub})
            vnics.append({"vnic_id": v.id, "attachment_id": a.id, "name": v.display_name, "primary": v.is_primary,
                          "subnet_id": v.subnet_id, "ips": ips})
        return {"vnics": vnics, "reserved": self.reserved_ips()}

    def add_secondary_ip(self, inst_id, vnic_id=None, with_public=True):
        v = self.vnet.get_vnic(vnic_id).data if vnic_id else self._primary_vnic(inst_id)
        if not v:
            raise RuntimeError("找不到网卡")
        p = self.vnet.create_private_ip(oci.core.models.CreatePrivateIpDetails(vnic_id=v.id, display_name="tricloud")).data
        pub = None
        if with_public:
            pub = self.vnet.create_public_ip(oci.core.models.CreatePublicIpDetails(
                compartment_id=self.compartment, lifetime="EPHEMERAL", private_ip_id=p.id)).data.ip_address
        return {"ok": True, "private_ip": p.ip_address, "public_ip": pub,
                "hint": f"系统内需手动添加地址：ip addr add {p.ip_address}/24 dev ens3（或写入 netplan 持久化）；Oracle Linux 可用 oci-network-config"}

    def delete_private_ip(self, private_ip_id):
        p = self.vnet.get_private_ip(private_ip_id).data
        if p.is_primary:
            raise RuntimeError("不能删除主私网 IP")
        self.vnet.delete_private_ip(private_ip_id)
        return {"ok": True}

    def attach_vnic(self, inst_id, subnet_id=None, with_public=True):
        subnet_id = subnet_id or self._primary_vnic(inst_id).subnet_id
        a = self.compute.attach_vnic(oci.core.models.AttachVnicDetails(
            instance_id=inst_id, display_name="tricloud-vnic",
            create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=bool(with_public)))).data
        return {"ok": True, "attachment_id": a.id,
                "hint": "辅助网卡需在系统内配置（Oracle Linux：oci-network-config；Ubuntu：按官方 secondary VNIC 脚本配置路由）。免费规格网卡数量有限：E2.1.Micro 1 块、A1 每 OCPU 1 块"}

    def detach_vnic(self, attachment_id):
        v = self.vnet.get_vnic(self.compute.get_vnic_attachment(attachment_id).data.vnic_id).data
        if v.is_primary:
            raise RuntimeError("不能卸载主网卡")
        self.compute.detach_vnic(attachment_id)
        return {"ok": True}

    def reserved_ips(self):
        out = []
        for p in oci.pagination.list_call_get_all_results(self.vnet.list_public_ips, scope="REGION",
                                                          compartment_id=self.compartment, lifetime="RESERVED").data:
            out.append({"id": p.id, "ip": p.ip_address, "name": p.display_name, "state": p.lifecycle_state,
                        "assigned": bool(p.assigned_entity_id or getattr(p, "private_ip_id", None))})
        return out

    def create_reserved_ip(self, name=None):
        p = self.vnet.create_public_ip(oci.core.models.CreatePublicIpDetails(
            compartment_id=self.compartment, lifetime="RESERVED", display_name=name or "tricloud-reserved")).data
        return {"ok": True, "id": p.id, "ip": p.ip_address}

    def assign_reserved_ip(self, public_ip_id, inst_id=None, private_ip_id=None):
        """把预留 IP 绑定到实例主私网 IP：先删掉该私网 IP 上的临时公网 IP（预留 IP 会替代它）。"""
        if not private_ip_id:
            v = self._primary_vnic(inst_id)
            private_ip_id = next(p.id for p in self.vnet.list_private_ips(vnic_id=v.id).data if p.is_primary)
        try:
            old = self.vnet.get_public_ip_by_private_ip_id(
                oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=private_ip_id)).data
            if old.id != public_ip_id:
                if old.lifetime == "EPHEMERAL":
                    self.vnet.delete_public_ip(old.id)
                else:
                    self.vnet.update_public_ip(old.id, oci.core.models.UpdatePublicIpDetails(private_ip_id=""))
                time.sleep(3)
        except oci.exceptions.ServiceError as e:
            if e.status != 404:
                raise
        self.vnet.update_public_ip(public_ip_id, oci.core.models.UpdatePublicIpDetails(private_ip_id=private_ip_id))
        return {"ok": True}

    def unassign_reserved_ip(self, public_ip_id, restore_ephemeral=True):
        p = self.vnet.get_public_ip(public_ip_id).data
        priv = getattr(p, "private_ip_id", None) or p.assigned_entity_id
        self.vnet.update_public_ip(public_ip_id, oci.core.models.UpdatePublicIpDetails(private_ip_id=""))
        new = None
        if restore_ephemeral and priv:
            time.sleep(3)
            new = self.vnet.create_public_ip(oci.core.models.CreatePublicIpDetails(
                compartment_id=self.compartment, lifetime="EPHEMERAL", private_ip_id=priv)).data.ip_address
        return {"ok": True, "ephemeral_ip": new}

    def delete_reserved_ip(self, public_ip_id):
        p = self.vnet.get_public_ip(public_ip_id).data
        if p.lifetime != "RESERVED":
            raise RuntimeError("只能删除预留 IP")
        if getattr(p, "private_ip_id", None) or p.assigned_entity_id:
            raise RuntimeError("预留 IP 仍绑定在实例上，请先解绑")
        self.vnet.delete_public_ip(public_ip_id)
        return {"ok": True}

    # ================= 11. 账号类型 =================
    def account_type(self):
        subs = self.identity.list_region_subscriptions(self.cfg["tenancy"]).data
        home = next((s.region_name for s in subs if s.is_home_region), self.cfg["region"])
        t = self.identity.get_tenancy(self.cfg["tenancy"]).data
        res = {"home_region": home, "tenancy_name": t.name}
        try:
            c = self._c(oci.osp_gateway.SubscriptionServiceClient, dict(self.cfg, region=home))
            items = c.list_subscriptions(osp_home_region=home, compartment_id=self.cfg["tenancy"]).data.items or []
            s = items[0] if items else None
        except Exception as e:
            res["error"] = f"查询订阅失败（需要 osp-gateway 读权限）：{str(getattr(e, 'message', e))[:160]}"
            s = None
        if s:
            plan = _v(s.plan_type)
            res.update(plan_type=plan, account_type=_v(s.account_type), upgrade_state=_v(s.upgrade_state),
                       time_start=str(s.time_start)[:10] if s.time_start else None,
                       time_upgrade=str(s.time_plan_upgrade)[:10] if getattr(s, "time_plan_upgrade", None) else None,
                       currency=s.currency_code)
            res["label"] = {"FREE_TIER": "免费试用 / 免费号", "PAYG": "升级号（按量付费）"}.get(plan, plan or "未知")
            if s.time_start:
                st = s.time_start if isinstance(s.time_start, dt.datetime) else dt.datetime.fromisoformat(str(s.time_start)[:19])
                res["age_days"] = (dt.datetime.now(dt.timezone.utc) - st.replace(tzinfo=st.tzinfo or dt.timezone.utc)).days
        return res

    # ================= 15. 免费 AMD 下行 500Mbps =================
    def _nlbc(self):
        return self._c(oci.network_load_balancer.NetworkLoadBalancerClient)

    def nlb_status(self, inst_id):
        v = self._primary_vnic(inst_id)
        for n in self._nlbc().list_network_load_balancers(compartment_id=self.compartment).data.items:
            if (n.display_name or "").startswith(NLB_PREFIX) and n.lifecycle_state not in ("DELETED", "DELETING", "FAILED"):
                full = self._nlbc().get_network_load_balancer(n.id).data
                for bs in (full.backend_sets or {}).values():
                    if any(b.target_id == inst_id for b in (bs.backends or [])):
                        pub = next((i.ip_address for i in full.ip_addresses or [] if i.is_public), None)
                        return {"enabled": True, "nlb_id": n.id, "public_ip": pub, "state": n.lifecycle_state,
                                "route_table_id": getattr(v, "route_table_id", None)}
        return {"enabled": False}

    def enable_500m(self, inst_id, ssh_port=22, progress=None):
        """NLB（Always Free 1 个）承接入站，实例网卡走 NAT 网关出站。新入口 IP = NLB 公网 IP。"""
        say = progress or (lambda m: None)
        inst = self.compute.get_instance(inst_id).data
        if inst.shape != MICRO:
            raise RuntimeError("仅支持免费 AMD 规格 VM.Standard.E2.1.Micro")
        if self.nlb_status(inst_id)["enabled"]:
            raise RuntimeError("该实例已开启")
        nlbc = self._nlbc()
        others = [n for n in nlbc.list_network_load_balancers(compartment_id=self.compartment).data.items
                  if n.lifecycle_state in ("ACTIVE", "CREATING", "UPDATING")]
        if others:
            raise RuntimeError(f"账号里已有网络负载均衡器「{others[0].display_name}」，Always Free 只含 1 个；请先在控制台删除后再开启")
        v = self._primary_vnic(inst_id)
        sub = self.vnet.get_subnet(v.subnet_id).data
        priv_ip = v.private_ip
        say("准备 NAT 网关…")
        nats = self.vnet.list_nat_gateways(compartment_id=self.compartment, vcn_id=sub.vcn_id, lifecycle_state="AVAILABLE").data
        nat = nats[0] if nats else self.vnet.create_nat_gateway(oci.core.models.CreateNatGatewayDetails(
            compartment_id=self.compartment, vcn_id=sub.vcn_id, display_name=f"{NLB_PREFIX}-nat")).data
        self._wait(lambda: self.vnet.get_nat_gateway(nat.id).data.lifecycle_state, lambda s: s == "AVAILABLE")
        say("创建网络负载均衡器（保留源地址，TCP+UDP 全端口转发）…")
        N = oci.network_load_balancer.models
        det = N.CreateNetworkLoadBalancerDetails(
            compartment_id=self.compartment, display_name=f"{NLB_PREFIX}-{inst.display_name}"[:255], is_private=False,
            subnet_id=sub.id, is_preserve_source_destination=False,
            listeners={"l1": N.ListenerDetails(name="l1", default_backend_set_name="b1", protocol="TCP_AND_UDP", port=0)},
            backend_sets={"b1": N.BackendSetDetails(
                policy="TWO_TUPLE", is_preserve_source=True, is_fail_open=True,
                health_checker=N.HealthChecker(protocol="TCP", port=int(ssh_port or 22)),
                backends=[N.BackendDetails(target_id=inst_id, ip_address=priv_ip, port=0, weight=1)])})
        nlb = nlbc.create_network_load_balancer(det).data
        self._wait(lambda: nlbc.get_network_load_balancer(nlb.id).data.lifecycle_state, lambda s: s in ("ACTIVE", "FAILED"), timeout=600)
        full = nlbc.get_network_load_balancer(nlb.id).data
        if full.lifecycle_state != "ACTIVE":
            raise RuntimeError("网络负载均衡器创建失败")
        pub = next((i.ip_address for i in full.ip_addresses or [] if i.is_public), None)
        say("创建 NAT 路由表并绑定到实例网卡…")
        rt = self.vnet.create_route_table(oci.core.models.CreateRouteTableDetails(
            compartment_id=self.compartment, vcn_id=sub.vcn_id, display_name=f"{NLB_PREFIX}-rt",
            route_rules=[oci.core.models.RouteRule(destination="0.0.0.0/0", destination_type="CIDR_BLOCK",
                                                   network_entity_id=nat.id)])).data
        self._wait(lambda: self.vnet.get_route_table(rt.id).data.lifecycle_state, lambda s: s == "AVAILABLE")
        self.vnet.update_vnic(v.id, oci.core.models.UpdateVnicDetails(route_table_id=rt.id, skip_source_dest_check=True))
        return {"ok": True, "public_ip": pub, "nlb_id": nlb.id,
                "hint": f"新的入口 IP 是 {pub}（NLB 公网 IP），原公网 IP 不再接收入站；安全列表仍按原规则放行端口"}

    def disable_500m(self, inst_id, progress=None):
        say = progress or (lambda m: None)
        st = self.nlb_status(inst_id)
        v = self._primary_vnic(inst_id)
        say("还原实例网卡路由…")
        sub_rt = self.vnet.get_subnet(v.subnet_id).data.route_table_id   # 回到子网默认路由表
        self.vnet.update_vnic(v.id, oci.core.models.UpdateVnicDetails(route_table_id=sub_rt, skip_source_dest_check=False))
        rt_id = st.get("route_table_id")
        if st.get("enabled"):
            say("删除网络负载均衡器…")
            self._nlbc().delete_network_load_balancer(st["nlb_id"])
        if rt_id:
            try:
                rt = self.vnet.get_route_table(rt_id).data
                if (rt.display_name or "").startswith(NLB_PREFIX):
                    time.sleep(5)
                    self.vnet.delete_route_table(rt_id)
            except Exception:
                pass
        return {"ok": True, "hint": "已还原：实例重新使用原公网 IP 入站（NAT 网关保留，不收费，可在控制台删除）"}

    # ================= 18. 对象存储 =================
    @property
    def os_client(self):
        if getattr(self, "_os", None) is None:
            self._os = self._c(oci.object_storage.ObjectStorageClient)
        return self._os

    @property
    def namespace(self):
        if getattr(self, "_ns", None) is None:
            self._ns = self.os_client.get_namespace(compartment_id=self.cfg["tenancy"]).data
        return self._ns

    @staticmethod
    def _bucket_ok(b):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", str(b or "")):
            raise RuntimeError("Bucket 名称只能包含字母、数字、- _ .")
        return b

    def buckets(self):
        out = []
        for b in oci.pagination.list_call_get_all_results(self.os_client.list_buckets, self.namespace, self.compartment).data:
            out.append({"name": b.name, "created": str(b.time_created)[:16]})
        return {"namespace": self.namespace, "buckets": out, "free_gb": FREE["object_gb"]}

    def create_bucket(self, name, public=False):
        self._bucket_ok(name)
        self.os_client.create_bucket(self.namespace, oci.object_storage.models.CreateBucketDetails(
            name=name, compartment_id=self.compartment, public_access_type="ObjectReadWithoutList" if public else "NoPublicAccess",
            storage_tier="Standard"))
        return {"ok": True}

    def delete_bucket(self, name):
        self._bucket_ok(name)
        if self.os_client.list_objects(self.namespace, name, limit=1).data.objects:
            raise RuntimeError("Bucket 不为空，请先删除其中的对象")
        self.os_client.delete_bucket(self.namespace, name)
        return {"ok": True}

    def objects(self, bucket, prefix=None, start=None):
        self._bucket_ok(bucket)
        r = self.os_client.list_objects(self.namespace, bucket, prefix=prefix or None, start=start or None, limit=200,
                                        delimiter="/", fields="name,size,timeCreated").data
        objs = [{"name": o.name, "size": o.size, "created": str(o.time_created)[:16]} for o in r.objects]
        return {"objects": objs, "prefixes": list(r.prefixes or []), "next": r.next_start_with,
                "total_bytes": sum(int(o["size"] or 0) for o in objs)}

    def put_object(self, bucket, name, data):
        self._bucket_ok(bucket)
        if not name or name.startswith("/") or ".." in name.split("/"):
            raise RuntimeError("对象名不合法")
        self.os_client.put_object(self.namespace, bucket, name, data)
        return {"ok": True}

    def object_url(self, bucket, name, minutes=60):
        """生成只读的预认证链接（PAR），默认 1 小时有效，浏览器直接从 OCI 下载。"""
        self._bucket_ok(bucket)
        exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=max(5, min(int(minutes or 60), 7 * 24 * 60)))
        par = self.os_client.create_preauthenticated_request(self.namespace, bucket,
                                                             oci.object_storage.models.CreatePreauthenticatedRequestDetails(
                                                                 name=f"tricloud-dl-{int(time.time())}", object_name=name,
                                                                 access_type="ObjectRead", time_expires=exp)).data
        host = f"https://objectstorage.{self.cfg['region']}.oraclecloud.com"
        return {"url": host + par.access_uri, "expires": exp.strftime("%Y-%m-%d %H:%M UTC")}

    def delete_object(self, bucket, name):
        self._bucket_ok(bucket)
        self.os_client.delete_object(self.namespace, bucket, name)
        return {"ok": True}

    # ================= 18b. 保号账单（PAYG：标准层存约 11 GiB 全零对象，超出 10 GB 免费额度，每月约 $0.02–0.03） =================
    BK_BUCKET = "tricloud-billing-keep"
    BK_OBJECT = "billing-keep.bin"
    BK_PART = 64 * 1024 * 1024          # 分片 64 MiB：一块全零缓冲区反复使用，串行上传，内存约 70 MB，不落盘

    def _bk_home(self):
        """主区域（Always Free / 对象存储免费额度都按租户算，固定放在主区域，便于查找）。"""
        try:
            subs = self.identity.list_region_subscriptions(self.cfg["tenancy"]).data
            return next((s.region_name for s in subs if s.is_home_region), self.cfg["region"])
        except Exception:
            return self.cfg["region"]

    def _bk_os(self, region=None):
        region = region or self._bk_home()
        c = self._c(oci.object_storage.ObjectStorageClient, dict(self.cfg, region=region))
        if getattr(self, "_bk_ns", None) is None:
            self._bk_ns = c.get_namespace(compartment_id=self.cfg["tenancy"]).data
        return c, self._bk_ns, region

    def _bk_uploads(self, c, ns):
        try:
            ups = oci.pagination.list_call_get_all_results(c.list_multipart_uploads, ns, self.BK_BUCKET).data
        except oci.exceptions.ServiceError as e:
            if e.status == 404:
                return []
            raise
        return [u for u in ups if u.object == self.BK_OBJECT]

    def billing_keep_status(self):
        """保号对象当前状态：bucket 是否存在、对象大小、是否有未完成的分片上传。只读。"""
        c, ns, region = self._bk_os()
        out = {"region": region, "namespace": ns, "bucket": self.BK_BUCKET, "object": self.BK_OBJECT,
               "bucket_exists": False, "exists": False, "size": 0, "storage_tier": None, "pending_uploads": []}
        try:
            b = c.get_bucket(ns, self.BK_BUCKET).data
        except oci.exceptions.ServiceError as e:
            if e.status == 404:
                return out
            raise
        out.update(bucket_exists=True, storage_tier=b.storage_tier, auto_tiering=getattr(b, "auto_tiering", None))
        try:
            h = c.head_object(ns, self.BK_BUCKET, self.BK_OBJECT)
            out.update(exists=True, size=int(h.headers.get("content-length") or 0),
                       modified=h.headers.get("last-modified"))
        except oci.exceptions.ServiceError as e:
            if e.status != 404:
                raise
        out["pending_uploads"] = [{"upload_id": u.upload_id, "created": str(u.time_created)[:16]} for u in self._bk_uploads(c, ns)]
        return out

    def _bk_bucket(self, c, ns):
        """建（或复用）标准层私有 bucket，并关闭自动分层（否则对象会被转到低频层，不再产生账单）。"""
        try:
            b = c.get_bucket(ns, self.BK_BUCKET).data
        except oci.exceptions.ServiceError as e:
            if e.status != 404:
                raise
            c.create_bucket(ns, oci.object_storage.models.CreateBucketDetails(
                name=self.BK_BUCKET, compartment_id=self.compartment, public_access_type="NoPublicAccess",
                storage_tier="Standard", auto_tiering="Disabled", freeform_tags={"tricloud": "billing-keep"}))
            return "created"
        if b.storage_tier != "Standard":
            raise RuntimeError(f"已有同名 Bucket {self.BK_BUCKET} 但不是标准层（{b.storage_tier}），请先在控制台删除")
        if getattr(b, "public_access_type", "NoPublicAccess") != "NoPublicAccess":
            raise RuntimeError(f"已有同名 Bucket {self.BK_BUCKET} 但不是私有的，请检查")
        if getattr(b, "auto_tiering", None) not in (None, "Disabled"):
            c.update_bucket(ns, self.BK_BUCKET, oci.object_storage.models.UpdateBucketDetails(auto_tiering="Disabled"))
        return "reused"

    def billing_keep_upload(self, total, resume=None, progress=None, checkpoint=None, report=None):
        """multipart 流式上传 total 字节全零数据。resume={"upload_id", "total"}：续传未完成的上传（跳过已传分片）。
        report(uploaded, total, upload_id) 每片回调一次；checkpoint(msg) 在分片之间检查是否被停止（停止时保留已传分片，可续传）。"""
        say = progress or (lambda m: None)
        c, ns, region = self._bk_os()
        say(f"主区域 {region}：准备 Bucket {self.BK_BUCKET}（标准层、私有、关闭自动分层）…")
        self._bk_bucket(c, ns)
        try:
            h = c.head_object(ns, self.BK_BUCKET, self.BK_OBJECT)
            size = int(h.headers.get("content-length") or 0)
            return {"ok": True, "existed": True, "size": size, "region": region}
        except oci.exceptions.ServiceError as e:
            if e.status != 404:
                raise
        pending = {u.upload_id for u in self._bk_uploads(c, ns)}
        upload_id, done = None, {}
        if resume and resume.get("upload_id") in pending:
            upload_id, total = resume["upload_id"], int(resume.get("total") or total)
            for pt in oci.pagination.list_call_get_all_results(c.list_multipart_upload_parts, ns, self.BK_BUCKET,
                                                                self.BK_OBJECT, upload_id).data:
                done[pt.part_number] = (pt.etag, int(pt.size or 0))
            say(f"续传上次未完成的上传：已有 {len(done)} 个分片")
        for u in pending - {upload_id}:      # 其他残留的分片上传（不知道大小，无法续）直接中止，避免未提交分片持续计费
            try:
                c.abort_multipart_upload(ns, self.BK_BUCKET, self.BK_OBJECT, u)
            except Exception:
                pass
        if not upload_id:
            upload_id = c.create_multipart_upload(ns, self.BK_BUCKET, oci.object_storage.models.CreateMultipartUploadDetails(
                object=self.BK_OBJECT, content_type="application/octet-stream", storage_tier="Standard")).data.upload_id
        nparts = (total + self.BK_PART - 1) // self.BK_PART
        if nparts > 10000:
            raise RuntimeError("对象过大")
        buf = bytes(self.BK_PART)
        md5 = base64.b64encode(hashlib.md5(buf).digest()).decode()
        uploaded = 0
        for n in range(1, nparts + 1):
            ln = min(self.BK_PART, total - (n - 1) * self.BK_PART)
            if n in done and done[n][1] == ln:
                uploaded += ln
                continue
            if checkpoint:
                checkpoint(f"上传分片 {n}/{nparts}…")
            if ln != self.BK_PART:      # 最后一片（只会出现一次）：先释放整片缓冲区再分配，峰值内存不翻倍
                buf = None
            body = buf if ln == self.BK_PART else bytes(ln)
            pmd5 = md5 if ln == self.BK_PART else base64.b64encode(hashlib.md5(body).digest()).decode()
            for i in range(3):
                try:
                    r = c.upload_part(ns, self.BK_BUCKET, self.BK_OBJECT, upload_id, n, body, content_length=ln, content_md5=pmd5)
                    done[n] = (r.headers.get("etag"), ln)
                    break
                except Exception:
                    if i == 2:
                        raise
                    time.sleep(3 * (i + 1))
            del body
            uploaded += ln
            if report:
                report(uploaded, total, upload_id)
        say("合并分片…")
        c.commit_multipart_upload(ns, self.BK_BUCKET, self.BK_OBJECT, upload_id,
                                  oci.object_storage.models.CommitMultipartUploadDetails(parts_to_commit=[
                                      oci.object_storage.models.CommitMultipartUploadPartDetails(part_num=k, etag=done[k][0])
                                      for k in sorted(done)]))
        h = c.head_object(ns, self.BK_BUCKET, self.BK_OBJECT)
        return {"ok": True, "existed": False, "size": int(h.headers.get("content-length") or total), "region": region, "parts": nparts}

    def billing_keep_delete(self):
        """删除保号对象、中止未完成的分片上传，bucket 空了就一并删除。只动 tricloud-billing-keep 这个 bucket。"""
        c, ns, region = self._bk_os()
        aborted = 0
        try:
            c.get_bucket(ns, self.BK_BUCKET)
        except oci.exceptions.ServiceError as e:
            if e.status == 404:
                return {"ok": True, "deleted": False, "aborted": 0, "bucket_deleted": False}
            raise
        for u in self._bk_uploads(c, ns):
            c.abort_multipart_upload(ns, self.BK_BUCKET, self.BK_OBJECT, u.upload_id)
            aborted += 1
        deleted = False
        try:
            c.delete_object(ns, self.BK_BUCKET, self.BK_OBJECT)
            deleted = True
        except oci.exceptions.ServiceError as e:
            if e.status != 404:
                raise
        bucket_deleted = False
        if not c.list_objects(ns, self.BK_BUCKET, limit=1).data.objects and not self._bk_uploads(c, ns):
            try:
                c.delete_bucket(ns, self.BK_BUCKET)
                bucket_deleted = True
            except oci.exceptions.ServiceError:
                pass
        return {"ok": True, "deleted": deleted, "aborted": aborted, "bucket_deleted": bucket_deleted, "region": region}

    # ================= 20. 免费额度体检 =================
    def free_check(self, a1_free=None):
        """a1_free=(ocpus, mem)：按账号类型传入（core.oci_a1_free），缺省按免费号 2/12。"""
        fc, fm = a1_free or (FREE["a1_ocpus"], FREE["a1_mem"])
        insts = [i for i in self.list_instances() if i["state"] not in ("terminated", "terminating")]
        a1 = [i for i in insts if i["shape"] == A1]
        micro = [i for i in insts if i["shape"] == MICRO]
        ocpu = sum(float(i.get("ocpus") or 0) for i in a1)
        mem = sum(float(i.get("memory_gb") or 0) for i in a1)
        try:
            st = self.storage_usage()["volume_gb"]
        except Exception:
            st = None
        issues = []
        if ocpu > fc:
            issues.append(f"A1 OCPU 合计 {ocpu:g}，超出免费 {fc:g}")
        if mem > fm:
            issues.append(f"A1 内存合计 {mem:g} GB，超出免费 {fm:g} GB")
        if len(micro) > FREE["micro"]:
            issues.append(f"E2.1.Micro {len(micro)} 台，超出免费 {FREE['micro']} 台")
        if st is not None and st > FREE["storage_gb"]:
            issues.append(f"块存储合计 {st} GB，超出免费 {FREE['storage_gb']} GB")
        paid = [{"id": i["id"], "name": i["name"], "shape": i["shape"]} for i in insts if i["shape"] not in (A1, MICRO)]
        if paid:
            issues.append(f"{len(paid)} 台非 Always Free 规格（按量计费）")
        # 降配建议：按创建顺序保留到额度内，超出的实例给出建议值（只建议、不自动执行；只降不升）
        left_c, left_m, sugg = fc, fm, []
        for i in sorted(a1, key=lambda x: x.get("created") or ""):
            c, m = float(i.get("ocpus") or 0), float(i.get("memory_gb") or 0)
            nc, nm = min(c, max(left_c, 0)), min(m, max(left_m, 0))
            if (nc, nm) != (c, m):
                sugg.append({"id": i["id"], "name": i["name"], "ocpus": c, "memory_gb": m,
                             "to_ocpus": nc, "to_memory_gb": nm, "delete": nc < 1 or nm < 1})
            left_c, left_m = left_c - nc, left_m - nm
        return {"a1": {"ocpus": ocpu, "memory_gb": mem, "count": len(a1), "limit_ocpus": fc, "limit_mem": fm},
                "micro": {"count": len(micro), "limit": FREE["micro"]},
                "storage": {"used_gb": st, "limit": FREE["storage_gb"]}, "paid": paid,
                "ok": not issues, "issues": issues, "suggestions": sugg}
