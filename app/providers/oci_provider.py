"""Oracle Cloud (OCI) 适配。
凭证: {user, tenancy, fingerprint, key_content, region, compartment(可选)}
"""
import base64
import datetime as dt
import ipaddress
import re
import threading
import time

import oci

from .. import hostname
from ..cloudinit import cloud_init, gen_password
from ..net import ip_matches, split_cidrs
from .oci_more import OCIMore


def _proxied(client, proxy):
    """每账号独立出口代理（http://user:pass@host:port 或 socks5://...）。"""
    if proxy:
        client.base_client.session.proxies = {"http": proxy, "https": proxy}
    return client

CAPACITY_HINTS = ("Out of host capacity", "out of capacity", "InternalError", "TooManyRequests", "LimitExceeded")


class OCIProvider(OCIMore):
    def __init__(self, cred, region=None):
        self.cred = cred
        self.cfg = {
            "user": cred["user"],
            "tenancy": cred["tenancy"],
            "fingerprint": cred["fingerprint"],
            "key_content": cred["key_content"],
            "region": region or cred.get("region"),
        }
        if cred.get("pass_phrase"):
            self.cfg["pass_phrase"] = cred["pass_phrase"]
        oci.config.validate_config(self.cfg)
        self.compartment = cred.get("compartment") or cred["tenancy"]
        self.proxy = cred.get("proxy")
        self.compute = self._c(oci.core.ComputeClient)
        self.vnet = self._c(oci.core.VirtualNetworkClient)
        self.identity = self._c(oci.identity.IdentityClient)
        self._bs = None

    _client_lock = threading.Lock()

    def _c(self, cls, cfg=None):
        """按 (客户端类型, 区域) 复用 OCI 客户端（同一账号同一区域只建一次，含签名器与 HTTP 会话）。"""
        cfg = cfg or self.cfg
        key = (cls, cfg.get("region"))
        cache = self.__dict__.setdefault("_clients", {})
        cl = cache.get(key)
        if cl is None:
            with self._client_lock:
                cl = cache.get(key)
                if cl is None:
                    cl = cache[key] = _proxied(cls(cfg), self.proxy)
        return cl

    @property
    def bs(self):
        if self._bs is None:
            self._bs = self._c(oci.core.BlockstorageClient)
        return self._bs

    # ---------- 基础 ----------
    def test(self):
        t = self.identity.get_tenancy(self.cfg["tenancy"]).data
        return {"ok": True, "name": t.name, "home_region": t.home_region_key}

    def regions(self):
        subs = self.identity.list_region_subscriptions(self.cfg["tenancy"]).data
        return [s.region_name for s in subs]

    def _primary_vnic(self, inst_id):
        atts = oci.pagination.list_call_get_all_results(
            self.compute.list_vnic_attachments, compartment_id=self.compartment, instance_id=inst_id).data
        for a in atts:
            if a.lifecycle_state != "ATTACHED":
                continue
            v = self.vnet.get_vnic(a.vnic_id).data
            if v.is_primary:
                return v
        return None

    def list_instances(self):
        items = oci.pagination.list_call_get_all_results(
            self.compute.list_instances, compartment_id=self.compartment).data
        out = []
        for i in items:
            if i.lifecycle_state == "TERMINATED":
                continue
            pub = priv = None
            ipv6 = []
            if i.lifecycle_state in ("RUNNING", "STOPPED", "STARTING", "STOPPING"):
                try:
                    v = self._primary_vnic(i.id)
                    if v:
                        pub, priv = v.public_ip, v.private_ip
                        ipv6 = list(v.ipv6_addresses or [])
                except Exception:
                    pass
            sc = i.shape_config
            out.append({
                "id": i.id, "name": i.display_name, "state": i.lifecycle_state.lower(),
                "public_ip": pub, "private_ip": priv, "ipv6": ipv6, "shape": i.shape,
                "ocpus": getattr(sc, "ocpus", None), "memory_gb": getattr(sc, "memory_in_gbs", None),
                "region": i.region, "zone": i.availability_domain, "created": str(i.time_created),
            })
        return out

    def action(self, inst_id, action, preserve_boot_volume=False):
        m = {"start": "START", "stop": "STOP", "reboot": "SOFTRESET", "hard_reboot": "RESET"}
        if action == "terminate":
            self.compute.terminate_instance(inst_id, preserve_boot_volume=bool(preserve_boot_volume))
            return {"ok": True}
        self.compute.instance_action(inst_id, m[action])
        return {"ok": True}

    def get_state(self, inst_id):
        return self.compute.get_instance(inst_id).data.lifecycle_state.lower()

    # ---------- 换 IP / IPv6 / 改配置 ----------
    def _rotate_ip_once(self, primary):
        old_ip = None
        try:
            old = self.vnet.get_public_ip_by_private_ip_id(
                oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=primary.id)).data
            old_ip = old.ip_address
            if old.lifetime == "RESERVED":
                raise RuntimeError("当前为保留 IP，请在控制台处理，面板只轮换临时 IP")
            self.vnet.delete_public_ip(old.id)
        except oci.exceptions.ServiceError as e:
            if e.status != 404:
                raise
        new = self.vnet.create_public_ip(oci.core.models.CreatePublicIpDetails(
            compartment_id=self.compartment, lifetime="EPHEMERAL", private_ip_id=primary.id)).data
        return old_ip, new.ip_address

    def change_ip(self, inst_id, cidrs=None, max_tries=20, progress=None, interval=8, accept=None):
        """换临时公网 IP。cidrs 非空时持续更换，直到新 IP 落入目标网段（如 ["129.146.0.0/16"]）。
        v1.4：以 ! 开头的网段表示排除（如 "!129.146.10.0/24"），可与普通网段混用。"""
        v = self._primary_vnic(inst_id)
        if not v:
            raise RuntimeError("找不到主 VNIC（实例需处于运行或停止状态）")
        pips = self.vnet.list_private_ips(vnic_id=v.id).data
        primary = next(p for p in pips if p.is_primary)
        want = [str(c).strip() for c in (cidrs or []) if c and str(c).strip()]
        split_cidrs(want)   # 校验格式
        first_old, tries = None, 0
        while True:
            tries += 1
            try:
                old_ip, new_ip = self._rotate_ip_once(primary)
            except oci.exceptions.ServiceError as e:
                if e.status == 429 and want and tries < max_tries:   # 频率限制：等待后继续
                    if progress:
                        progress(f"第 {tries} 次：触发频率限制（429），{interval * 3} 秒后继续")
                    time.sleep(interval * 3)
                    continue
                raise
            first_old = first_old or old_ip
            why = "不满足网段要求" if want and not ip_matches(new_ip, want) else ""
            if not why and accept:   # v1.6：IP 质量条件（风险分 / 归属国家）
                good, why = accept(new_ip)
                why = "" if good else (why or "质量不合格")
            if not why:
                return {"old_ip": first_old, "new_ip": new_ip, "tries": tries}
            if progress:
                progress(f"第 {tries} 次：{new_ip} {why}，继续…")
            if tries >= max_tries:
                return {"old_ip": first_old, "new_ip": new_ip, "tries": tries, "warning": f"已达最大次数，最后一个 IP {why}"}
            time.sleep(interval)

    def add_ipv6(self, inst_id, progress=None):
        """一键 IPv6：按需为 VCN 开 IPv6 → 子网分配 /64 → 路由表 ::/0 → 安全列表放行 IPv6 出站，再给 VNIC 分配地址。"""
        say = progress or (lambda m: None)
        v = self._primary_vnic(inst_id)
        if not v:
            raise RuntimeError("找不到主 VNIC")
        subnet = self.vnet.get_subnet(v.subnet_id).data
        vcn = self.vnet.get_vcn(subnet.vcn_id).data
        if not vcn.ipv6_cidr_blocks:
            say("(1/4) 为 VCN 开启 IPv6…")
            self.vnet.add_ipv6_vcn_cidr(vcn.id, oci.core.models.AddVcnIpv6CidrDetails(is_oracle_gua_allocation_enabled=True))
            vcn = self._wait(lambda: self.vnet.get_vcn(vcn.id).data, lambda x: x.ipv6_cidr_blocks)
        if not subnet.ipv6_cidr_block and not getattr(subnet, "ipv6_cidr_blocks", None):
            say("(2/4) 为子网分配 IPv6 /64…")
            net = ipaddress.ip_network(vcn.ipv6_cidr_blocks[0])
            sub64 = str(next(net.subnets(new_prefix=64)))
            self.vnet.update_subnet(subnet.id, oci.core.models.UpdateSubnetDetails(ipv6_cidr_block=sub64))
            self._wait(lambda: self.vnet.get_subnet(subnet.id).data, lambda x: x.ipv6_cidr_block)
        say("(3/4) 检查路由与安全列表…")
        rt = self.vnet.get_route_table(subnet.route_table_id or vcn.default_route_table_id).data
        if not any(r.destination == "::/0" for r in rt.route_rules):
            igw = next((g for g in self.vnet.list_internet_gateways(compartment_id=vcn.compartment_id, vcn_id=vcn.id).data), None)
            if not igw:
                raise RuntimeError("VCN 没有互联网网关，无法添加 IPv6 路由")
            rules = list(rt.route_rules) + [oci.core.models.RouteRule(destination="::/0", destination_type="CIDR_BLOCK",
                                                                          network_entity_id=igw.id)]
            self.vnet.update_route_table(rt.id, oci.core.models.UpdateRouteTableDetails(route_rules=rules))
        for sl_id in (subnet.security_list_ids or [vcn.default_security_list_id]):
            sl = self.vnet.get_security_list(sl_id).data
            if not any(e.destination == "::/0" for e in sl.egress_security_rules):
                eg = list(sl.egress_security_rules) + [oci.core.models.EgressSecurityRule(destination="::/0", protocol="all")]
                self.vnet.update_security_list(sl.id, oci.core.models.UpdateSecurityListDetails(egress_security_rules=eg))
            break
        if v.ipv6_addresses:
            return {"ipv6": v.ipv6_addresses[0], "existing": True}
        say("(4/4) 分配 IPv6 地址…")
        r = self.vnet.create_ipv6(oci.core.models.CreateIpv6Details(vnic_id=v.id)).data
        return {"ipv6": r.ip_address}

    @staticmethod
    def _wait(get, ok, timeout=180):
        end = time.time() + timeout
        while True:
            x = get()
            if ok(x) or time.time() > end:
                return x
            time.sleep(5)

    # ---------- 改名 / 引导卷 ----------
    def rename(self, inst_id, name):
        self.compute.update_instance(inst_id, oci.core.models.UpdateInstanceDetails(display_name=name))
        return {"ok": True}

    RUN_CMD_PLUGIN = "Compute Instance Run Command"

    @property
    def agent(self):
        if getattr(self, "_agent", None) is None:
            self._agent = self._c(oci.compute_instance_agent.ComputeInstanceAgentClient)
        return self._agent

    def _run_cmd_plugin_state(self, inst_id):
        """Run Command 插件状态：RUNNING / STOPPED / NOT_SUPPORTED / INVALID；查不到（权限等）返回 None。"""
        try:
            pc = self._c(oci.compute_instance_agent.PluginClient)
            return (pc.get_instance_agent_plugin(inst_id, self.compartment, self.RUN_CMD_PLUGIN).data.status or "").upper()
        except Exception:
            return None

    def boot_volume(self, inst_id):
        inst = self.compute.get_instance(inst_id).data
        atts = self.compute.list_boot_volume_attachments(inst.availability_domain, self.compartment, instance_id=inst_id).data
        if not atts:
            raise RuntimeError("找不到引导卷")
        bv = self.bs.get_boot_volume(atts[0].boot_volume_id).data
        return {"id": bv.id, "name": bv.display_name, "size_gb": bv.size_in_gbs, "vpus_per_gb": bv.vpus_per_gb,
                "state": bv.lifecycle_state}

    def update_boot_volume(self, inst_id, size_gb=None, vpus_per_gb=None):
        bv = self.boot_volume(inst_id)
        d = {}
        if size_gb:
            if int(size_gb) < bv["size_gb"]:
                raise RuntimeError("OCI 引导卷只能扩容不能缩小")
            d["size_in_gbs"] = int(size_gb)
        if vpus_per_gb is not None and vpus_per_gb != "":
            if int(vpus_per_gb) not in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120):
                raise RuntimeError("VPU 需为 10~120 的 10 的倍数")
            d["vpus_per_gb"] = int(vpus_per_gb)
        if not d:
            raise RuntimeError("没有要修改的项")
        self.bs.update_boot_volume(bv["id"], oci.core.models.UpdateBootVolumeDetails(**d))
        hint = "扩容后需在系统内扩展分区：growpart /dev/sda 1 && resize2fs /dev/sda1（或 xfs_growfs /）" if "size_in_gbs" in d else ""
        return {"ok": True, "hint": hint}

    # ---------- 安全列表 ----------
    def _subnet_of(self, inst_id):
        v = self._primary_vnic(inst_id)
        if not v:
            raise RuntimeError("找不到主 VNIC")
        return self.vnet.get_subnet(v.subnet_id).data

    @staticmethod
    def _rule_view(r, direction):
        proto = {"6": "TCP", "17": "UDP", "1": "ICMP", "58": "ICMPv6", "all": "全部"}.get(r.protocol, r.protocol)
        opts = r.tcp_options or r.udp_options
        port = "全部"
        a = b = None
        if opts and opts.destination_port_range:
            a, b = opts.destination_port_range.min, opts.destination_port_range.max
            port = str(a) if a == b else f"{a}-{b}"
        return {"direction": direction, "protocol": proto, "cidr": r.source if direction == "ingress" else r.destination,
                "port": port, "desc": r.description or "", "port_min": a, "port_max": b, "stateless": bool(r.is_stateless)}

    def _sec_subnet(self, inst_id=None, subnet_id=None):
        """安全列表跟着子网走：优先按子网 OCID，兼容旧的按实例（主 VNIC 所在子网）。"""
        if subnet_id:
            return self.vnet.get_subnet(subnet_id).data
        if not inst_id:
            raise ValueError("请选择子网或实例")
        return self._subnet_of(inst_id)

    def rename_subnet(self, subnet_id, name):
        """子网改名：只改 display_name（UpdateSubnet），不影响实例、IP、安全列表 / 规则。返回旧名与新名。"""
        old = self.vnet.get_subnet(subnet_id).data
        new = self.vnet.update_subnet(subnet_id, oci.core.models.UpdateSubnetDetails(display_name=name)).data
        return {"id": subnet_id, "old_name": getattr(old, "display_name", "") or "", "name": getattr(new, "display_name", None) or name}

    def rename_vcn(self, vcn_id, name):
        """VCN 改名：只改 display_name（UpdateVcn），不影响子网、实例、IP、安全规则。"""
        old = self.vnet.get_vcn(vcn_id).data
        new = self.vnet.update_vcn(vcn_id, oci.core.models.UpdateVcnDetails(display_name=name)).data
        return {"id": vcn_id, "old_name": getattr(old, "display_name", "") or "", "name": getattr(new, "display_name", None) or name}

    def security_subnets(self):
        """安全组页的子网下拉：区间内所有子网（含没有实例的）+ 各子网里的实例名 + 实例 VNIC 上挂的 NSG（只读提示）。
        请求数：ListInstances + ListVnicAttachments + ListSubnets + ListVcns 各 1 次（分页），每个 VNIC 1 次 GetVnic，
        每个不同 NSG 1 次 GetNetworkSecurityGroup；不在本区间的子网 / VCN 各补 1 次 Get。"""
        from concurrent.futures import ThreadPoolExecutor
        pg = oci.pagination.list_call_get_all_results
        insts = {i.id: i for i in pg(self.compute.list_instances, compartment_id=self.compartment).data
                 if i.lifecycle_state not in ("TERMINATED", "TERMINATING")}
        atts = [a for a in pg(self.compute.list_vnic_attachments, compartment_id=self.compartment).data
                if a.lifecycle_state == "ATTACHED" and a.instance_id in insts]
        errors = []

        def vnic(a):
            try:
                return a, self.vnet.get_vnic(a.vnic_id).data
            except Exception as e:   # noqa: BLE001 —— 单个 VNIC 读不到时仍按挂载记录归到子网，只是没有 NSG 信息
                errors.append(f"VNIC {a.vnic_id[-8:]}: {getattr(e, 'message', None) or e}")
                return a, None
        with ThreadPoolExecutor(8) as ex:
            vnics = list(ex.map(vnic, atts)) if atts else []
        subs = {s.id: s for s in pg(self.vnet.list_subnets, compartment_id=self.compartment).data
                if s.lifecycle_state not in ("TERMINATED", "TERMINATING")}
        for a, v in vnics:
            sid = (v.subnet_id if v is not None else None) or a.subnet_id
            if sid and sid not in subs:
                try:
                    subs[sid] = self.vnet.get_subnet(sid).data
                except Exception as e:   # noqa: BLE001
                    errors.append(f"子网 {sid[-8:]}: {getattr(e, 'message', None) or e}")
        vcns = {}
        try:
            vcns = {x.id: x.display_name for x in pg(self.vnet.list_vcns, compartment_id=self.compartment).data}
        except Exception as e:   # noqa: BLE001
            errors.append(f"VCN 列表: {getattr(e, 'message', None) or e}")
        nsg_names = {}

        def nsg_name(nid):
            if nid not in nsg_names:
                try:
                    nsg_names[nid] = self.vnet.get_network_security_group(nid).data.display_name
                except Exception:   # noqa: BLE001 —— 读不到名字时显示 OCID 尾部
                    nsg_names[nid] = "…" + nid[-8:]
            return nsg_names[nid]
        out = {}
        for sid, s in subs.items():
            if s.vcn_id and s.vcn_id not in vcns:
                try:
                    vcns[s.vcn_id] = self.vnet.get_vcn(s.vcn_id).data.display_name
                except Exception:   # noqa: BLE001
                    vcns[s.vcn_id] = ""
            out[sid] = {"id": sid, "name": s.display_name, "cidr": s.cidr_block, "ipv6_cidrs": list(getattr(s, "ipv6_cidr_blocks", None) or []),
                        "vcn_id": s.vcn_id, "vcn_name": vcns.get(s.vcn_id, ""), "security_list_count": len(s.security_list_ids or []),
                        "instances": []}
        for a, v in vnics:
            sid = (v.subnet_id if v is not None else None) or a.subnet_id
            if sid not in out:
                continue
            i = insts[a.instance_id]
            row = next((x for x in out[sid]["instances"] if x["id"] == i.id), None)
            if row is None:
                row = {"id": i.id, "name": i.display_name, "state": (i.lifecycle_state or "").lower(), "nsgs": []}
                out[sid]["instances"].append(row)
            for nid in (getattr(v, "nsg_ids", None) or []) if v is not None else []:
                if all(n["id"] != nid for n in row["nsgs"]):
                    row["nsgs"].append({"id": nid, "name": nsg_name(nid)})
        for x in out.values():
            x["instances"].sort(key=lambda r: r["name"] or "")
        rows = sorted(out.values(), key=lambda x: (not x["instances"], x["vcn_name"] or "", x["name"] or ""))
        return {"subnets": rows, "errors": errors}

    def security_rules(self, inst_id, subnet_id=None):
        sub = self._sec_subnet(inst_id, subnet_id)
        out = []
        for sl_id in sub.security_list_ids:
            sl = self.vnet.get_security_list(sl_id).data
            rules = [dict(self._rule_view(r, "ingress"), idx=i) for i, r in enumerate(sl.ingress_security_rules)]
            rules += [dict(self._rule_view(r, "egress"), idx=i) for i, r in enumerate(sl.egress_security_rules)]
            out.append({"id": sl.id, "name": sl.display_name, "rules": rules})
        return out

    @staticmethod
    def _make_rule(direction, protocol, cidr, port=None, desc=None):
        pmap = {"tcp": "6", "udp": "17", "icmp": "1", "icmpv6": "58", "all": "all"}
        proto = pmap[protocol.lower()]
        kw = {"protocol": proto, "description": desc or None, "is_stateless": False}
        if proto in ("6", "17") and port and str(port) not in ("", "全部", "all"):
            a, _, b = str(port).partition("-")
            pr = oci.core.models.PortRange(min=int(a), max=int(b or a))
            opt = (oci.core.models.TcpOptions if proto == "6" else oci.core.models.UdpOptions)(destination_port_range=pr)
            kw["tcp_options" if proto == "6" else "udp_options"] = opt
        if direction == "ingress":
            return oci.core.models.IngressSecurityRule(source=cidr, **kw)
        return oci.core.models.EgressSecurityRule(destination=cidr, **kw)

    def add_security_rule(self, sl_id, direction, protocol, cidr, port=None, desc=None):
        ipaddress.ip_network(cidr, strict=False)
        sl = self.vnet.get_security_list(sl_id).data
        r = self._make_rule(direction, protocol, cidr, port, desc)
        if direction == "ingress":
            d = oci.core.models.UpdateSecurityListDetails(ingress_security_rules=list(sl.ingress_security_rules) + [r])
        else:
            d = oci.core.models.UpdateSecurityListDetails(egress_security_rules=list(sl.egress_security_rules) + [r])
        self.vnet.update_security_list(sl_id, d)
        return {"ok": True}

    def remove_security_rule(self, sl_id, direction, idx):
        sl = self.vnet.get_security_list(sl_id).data
        key = "ingress_security_rules" if direction == "ingress" else "egress_security_rules"
        rules = list(getattr(sl, key))
        if not 0 <= int(idx) < len(rules):
            raise RuntimeError("规则已变化，请刷新后重试")
        rules.pop(int(idx))
        self.vnet.update_security_list(sl_id, oci.core.models.UpdateSecurityListDetails(**{key: rules}))
        return {"ok": True}

    # ---------- v1.5 安全组：按规则内容增删（不怕下标变化）、批量端口、去重 ----------
    PROTO_NUM = {"tcp": "6", "udp": "17", "icmp": "1", "icmpv6": "58", "all": "all"}

    @staticmethod
    def parse_ports(spec):
        """"80, 443\n8000-8100" -> [(80,80),(443,443),(8000,8100)]；去重，最多 50 段。"""
        out = []
        for part in re.split(r"[\s,，;；]+", str(spec or "").strip()):
            if not part:
                continue
            m = re.fullmatch(r"(\d{1,5})(?:-(\d{1,5}))?", part)
            if not m:
                raise ValueError(f"端口格式不正确：{part}（如 80、443、8000-8100）")
            a, b = int(m.group(1)), int(m.group(2) or m.group(1))
            if not (1 <= a <= b <= 65535):
                raise ValueError(f"端口范围无效：{part}（1-65535，起始 ≤ 结束）")
            if (a, b) not in out:
                out.append((a, b))
        if len(out) > 50:
            raise ValueError("一次最多 50 段端口")
        return out

    @classmethod
    def _rule_key(cls, r, direction):
        opts = r.tcp_options or r.udp_options
        pr = opts.destination_port_range if opts and opts.destination_port_range else None
        return (r.protocol, r.source if direction == "ingress" else r.destination,
                pr.min if pr else None, pr.max if pr else None)

    def _pick_list(self, inst_id, sl_id=None, subnet_id=None):
        ids = self._sec_subnet(inst_id, subnet_id).security_list_ids or []
        where = "所选子网" if subnet_id else "实例所在子网"
        if not ids:
            raise ValueError(f"{where}没有安全列表")
        if sl_id and sl_id not in ids:
            raise ValueError(f"该安全列表不属于{where}")
        return sl_id or ids[0]

    def security_rules_flat(self, inst_id=None, subnet_id=None):
        lists = self.security_rules(inst_id, subnet_id)
        rules = [dict(r, sl_id=sl["id"], sl_name=sl["name"]) for sl in lists for r in sl["rules"]]
        return {"lists": [{"id": sl["id"], "name": sl["name"]} for sl in lists], "rules": rules}

    def add_security_rules(self, inst_id, sl_id, direction, protocol, cidr, ranges, desc=None, subnet_id=None):
        ipaddress.ip_network(cidr, strict=False)
        sl_id = self._pick_list(inst_id, sl_id, subnet_id)
        sl = self.vnet.get_security_list(sl_id).data
        key = "ingress_security_rules" if direction == "ingress" else "egress_security_rules"
        rules = list(getattr(sl, key) or [])
        have = {self._rule_key(r, direction) for r in rules}
        added = skipped = 0
        for rg in (ranges or [None]):
            port = f"{rg[0]}-{rg[1]}" if rg else None
            k = (self.PROTO_NUM[protocol], cidr, rg[0] if rg else None, rg[1] if rg else None)
            if k in have:
                skipped += 1
                continue
            rules.append(self._make_rule(direction, protocol, cidr, port, desc))
            have.add(k)
            added += 1
        if added:
            self.vnet.update_security_list(sl_id, oci.core.models.UpdateSecurityListDetails(**{key: rules}))
        return {"sl_id": sl_id, "added": added, "skipped": skipped}

    def open_ports(self, inst_id, protocol, ranges):
        """实例操作「开放端口」：在实例子网的安全列表放行 0.0.0.0/0 入站（已存在的跳过）。"""
        res = self.add_security_rules(inst_id, None, "ingress", protocol, "0.0.0.0/0", ranges, "TriCloud open port")
        try:
            name = self.vnet.get_security_list(res["sl_id"]).data.display_name
        except Exception:
            name = res["sl_id"]
        return {"ok": True, "added": res["added"], "skipped": res["skipped"],
                "groups": [{"kind": "安全列表", "id": res["sl_id"], "name": name, "added": res["added"], "skipped": res["skipped"]}]}

    def delete_security_rule_match(self, inst_id, sl_id, direction, protocol, cidr, port_min=None, port_max=None, subnet_id=None):
        sl_id = self._pick_list(inst_id, sl_id, subnet_id)
        sl = self.vnet.get_security_list(sl_id).data
        key = "ingress_security_rules" if direction == "ingress" else "egress_security_rules"
        rules = list(getattr(sl, key) or [])
        want = (self.PROTO_NUM[protocol], cidr, int(port_min) if port_min not in (None, "") else None,
                int(port_max) if port_max not in (None, "") else None)
        idx = next((i for i, r in enumerate(rules) if self._rule_key(r, direction) == want), None)
        if idx is None:
            raise LookupError("未找到匹配的规则（可能已被删除，请刷新）")
        rules.pop(idx)
        self.vnet.update_security_list(sl_id, oci.core.models.UpdateSecurityListDetails(**{key: rules}))
        return {"ok": True, "sl_id": sl_id, "deleted": 1}

    def delete_ipv6(self, inst_id):
        """删除实例主 VNIC 上的全部 IPv6 地址（VCN / 子网的 IPv6 配置保留）。"""
        v = self._primary_vnic(inst_id)
        if not v:
            raise LookupError("找不到主 VNIC")
        ips = self.vnet.list_ipv6s(vnic_id=v.id).data
        if not ips:
            raise LookupError("该实例没有 IPv6 地址")
        for ip in ips:
            self.vnet.delete_ipv6(ip.id)
        return {"deleted": [ip.ip_address for ip in ips]}

    # ---------- 配额 / 流量 ----------
    LIMIT_NAMES = {
        "standard-a1-core-count": "A1 ARM OCPU", "standard-a1-memory-count": "A1 ARM 内存(GB)",
        "standard-e2-micro-core-count": "E2.1.Micro 数量", "standard-e4-core-count": "E4 OCPU",
        "standard-e5-core-count": "E5 OCPU", "vm-standard3-flex-core-count": "Standard3 OCPU",
    }

    # Always Free 额度（租户合计）：A1 默认按免费号 2/12（2026-06 起），付费号由调用方传入 4/24
    FREE_LIMITS = {"standard-a1-core-count": 2, "standard-a1-memory-count": 12, "standard-e2-micro-core-count": 2}

    def limits(self, a1_free=None):
        lc = self._c(oci.limits.LimitsClient)
        vals = oci.pagination.list_call_get_all_results(lc.list_limit_values, self.cfg["tenancy"], "compute").data
        out = {}
        for v in vals:
            if v.name in self.LIMIT_NAMES:
                o = out.setdefault(v.name, {"name": self.LIMIT_NAMES[v.name], "limit": 0, "used": None, "available": None})
                o["limit"] += int(v.value or 0)
        for name in ("standard-a1-core-count", "standard-a1-memory-count", "standard-e2-micro-core-count"):
            if name not in out:
                continue
            used = avail = 0
            try:
                for ad in self.availability_domains():
                    a = lc.get_resource_availability("compute", name, self.compartment, availability_domain=ad).data
                    used += int(a.used or 0)
                    avail += int(a.available or 0)
                out[name].update(used=used, available=avail)
            except Exception:
                pass
        free_map = dict(self.FREE_LIMITS)
        if a1_free:
            free_map.update({"standard-a1-core-count": a1_free[0], "standard-a1-memory-count": a1_free[1]})
        for name, free in free_map.items():
            if name in out:
                used = out[name]["used"]
                out[name].update(free=free, free_left=None if used is None else max(0, free - used))
        return {"region": self.cfg["region"], "items": list(out.values())}

    def traffic(self, inst_id, start=None, end=None):
        """本月该实例主 VNIC 的流量（GB），来自 OCI Monitoring（免费）。出站超 10TB/月 才计费。
        v1.4：传入 start/end（UTC datetime）时统计该时间窗（滚动窗口模式，按小时聚合）。"""
        v = self._primary_vnic(inst_id)
        if not v:
            raise RuntimeError("找不到主 VNIC")
        mc = self._c(oci.monitoring.MonitoringClient)
        now = end or dt.datetime.now(dt.timezone.utc)
        win = start is not None
        start = start or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        res = {}
        for metric, key in (("VnicToNetworkBytes", "out_gb"), ("VnicFromNetworkBytes", "in_gb")):
            d = oci.monitoring.models.SummarizeMetricsDataDetails(
                namespace="oci_vcn", query=f'{metric}[{"1h" if win else "1d"}]{{resourceId = "{v.id}"}}.sum()',
                start_time=start, end_time=now)
            data = mc.summarize_metrics_data(self.compartment, d).data
            total = sum(p.value for s in data for p in s.aggregated_datapoints)
            res[key] = round(total / 1024 ** 3, 3)
        res["period"] = f"{start:%Y-%m-%d %H:%M} ~ {now:%Y-%m-%d %H:%M} UTC" if win else f"{start:%Y-%m-%d} ~ {now:%Y-%m-%d}"
        return res

    FREE_OUT_GB = 10240   # Always Free：每月 10TB 出站（整个租户、所有区域合计）

    def traffic_summary(self):
        """当前区域所有实例本月流量（OCI Monitoring，免费只读）。单个实例失败只记错误，不影响其他。"""
        from concurrent.futures import ThreadPoolExecutor
        insts = [i for i in self.list_instances() if i.get("state") not in ("terminating", "provisioning")]

        def one(i):
            row = {k: i.get(k) for k in ("id", "name", "state", "public_ip", "shape", "region")}
            try:
                t = self.traffic(i["id"])
                row.update(out_gb=t["out_gb"], in_gb=t["in_gb"])
            except Exception as e:
                row.update(out_gb=None, in_gb=None, error=str(getattr(e, "message", e))[:160])
            return row

        with ThreadPoolExecutor(max_workers=4) as ex:
            items = list(ex.map(one, insts))
        now = dt.datetime.now(dt.timezone.utc)
        out = round(sum(r["out_gb"] or 0 for r in items), 3)
        inn = round(sum(r["in_gb"] or 0 for r in items), 3)
        return {"region": self.cfg["region"], "period": f"{now:%Y-%m}-01 ~ {now:%Y-%m-%d}",
                "items": items, "out_gb": out, "in_gb": inn, "free_out_gb": self.FREE_OUT_GB}

    def created_at(self):
        """云账号（租户根区间）创建日期，免费只读接口。"""
        c = self.identity.get_compartment(self.cfg["tenancy"]).data
        return c.time_created.date().isoformat() if getattr(c, "time_created", None) else None

    def resize(self, inst_id, ocpus=None, memory_gb=None, shape=None):
        sc = oci.core.models.UpdateInstanceShapeConfigDetails(
            ocpus=float(ocpus) if ocpus else None, memory_in_gbs=float(memory_gb) if memory_gb else None)
        d = oci.core.models.UpdateInstanceDetails(shape_config=sc)
        if shape:
            d.shape = shape
        self.compute.update_instance(inst_id, d)
        return {"ok": True}

    # ---------- 创建 ----------
    OS_CHOICES = ("Canonical Ubuntu", "Oracle Linux")   # 表单可选系统（CentOS 已无平台镜像，v1.5 移除）

    @staticmethod
    def _ver_key(v):
        """配合 reverse=True 得到降序：数字部分从大到小（9 > 8.10 > 8 > 7.9）；同版本时纯版本号在前（24.04 先于 24.04 Minimal）。"""
        m = re.match(r"^([\d.]+)(.*)$", v or "")
        nums = tuple(int(x) for x in m.group(1).split(".") if x.isdigit()) if m else ()
        suffix = m.group(2).strip() if m else (v or "")
        return (nums, 0 if suffix else 1, suffix)

    def os_versions(self, shape=None):
        """按规格列出平台镜像可用的系统版本：{os: [versions…]}，去重后降序。"""
        kw = dict(compartment_id=self.compartment, lifecycle_state="AVAILABLE")
        if shape:
            kw["shape"] = shape
        imgs = oci.pagination.list_call_get_all_results(self.compute.list_images, **kw).data
        out = {}
        for i in imgs:
            os_name, ver = getattr(i, "operating_system", None), (getattr(i, "operating_system_version", None) or "").strip()
            if os_name in self.OS_CHOICES and ver:
                out.setdefault(os_name, set()).add(ver)
        return {k: sorted(v, key=self._ver_key, reverse=True) for k, v in out.items()}

    def availability_domains(self):
        return [a.name for a in self.identity.list_availability_domains(self.cfg["tenancy"]).data]

    def _pick_subnet(self, subnet_id=None):
        if subnet_id:
            return subnet_id
        subs = self.vnet.list_subnets(compartment_id=self.compartment).data
        subs = [s for s in subs if not s.prohibit_public_ip_on_vnic and s.lifecycle_state == "AVAILABLE"]
        if subs:
            return subs[0].id
        return self.ensure_network()["subnet_id"]

    def ensure_network(self):
        """自动建网：VCN(开 IPv6) + 互联网网关 + 路由(0.0.0.0/0、::/0) + 安全列表(仅放行 22 与 ICMP) + 公有子网。"""
        M = oci.core.models
        vcn = self.vnet.create_vcn(M.CreateVcnDetails(compartment_id=self.compartment, cidr_blocks=["10.0.0.0/16"],
                                                      display_name="tricloud-vcn", dns_label="tricloud",
                                                      is_ipv6_enabled=True)).data
        vcn = self._wait(lambda: self.vnet.get_vcn(vcn.id).data, lambda x: x.lifecycle_state == "AVAILABLE")
        igw = self.vnet.create_internet_gateway(M.CreateInternetGatewayDetails(
            compartment_id=self.compartment, vcn_id=vcn.id, is_enabled=True, display_name="tricloud-igw")).data
        self._wait(lambda: self.vnet.get_internet_gateway(igw.id).data, lambda x: x.lifecycle_state == "AVAILABLE")
        rules = [M.RouteRule(destination="0.0.0.0/0", destination_type="CIDR_BLOCK", network_entity_id=igw.id)]
        if vcn.ipv6_cidr_blocks:
            rules.append(M.RouteRule(destination="::/0", destination_type="CIDR_BLOCK", network_entity_id=igw.id))
        self.vnet.update_route_table(vcn.default_route_table_id, M.UpdateRouteTableDetails(route_rules=rules))
        ing = [self._make_rule("ingress", "tcp", "0.0.0.0/0", 22, "SSH"),
               self._make_rule("ingress", "icmp", "0.0.0.0/0", desc="ICMP")]
        eg = [self._make_rule("egress", "all", "0.0.0.0/0")]
        if vcn.ipv6_cidr_blocks:
            ing.append(self._make_rule("ingress", "tcp", "::/0", 22, "SSH v6"))
            eg.append(self._make_rule("egress", "all", "::/0"))
        self.vnet.update_security_list(vcn.default_security_list_id, M.UpdateSecurityListDetails(
            ingress_security_rules=ing, egress_security_rules=eg))
        sd = M.CreateSubnetDetails(compartment_id=self.compartment, vcn_id=vcn.id, cidr_block="10.0.0.0/24",
                                   display_name="tricloud-public", dns_label="pub", prohibit_public_ip_on_vnic=False,
                                   route_table_id=vcn.default_route_table_id,
                                   security_list_ids=[vcn.default_security_list_id])
        if vcn.ipv6_cidr_blocks:
            sd.ipv6_cidr_block = str(next(ipaddress.ip_network(vcn.ipv6_cidr_blocks[0]).subnets(new_prefix=64)))
        sub = self.vnet.create_subnet(sd).data
        self._wait(lambda: self.vnet.get_subnet(sub.id).data, lambda x: x.lifecycle_state == "AVAILABLE")
        return {"vcn_id": vcn.id, "subnet_id": sub.id}

    def _subnet_dns(self, subnet_id):
        try:
            return bool(self.vnet.get_subnet(subnet_id).data.dns_label)
        except Exception:
            return False

    def _pick_image(self, shape, os_name="Canonical Ubuntu", os_version=None, image_id=None):
        if image_id:
            return image_id
        kw = dict(compartment_id=self.compartment, operating_system=os_name, shape=shape,
                  sort_by="TIMECREATED", sort_order="DESC", lifecycle_state="AVAILABLE")
        if os_version:
            kw["operating_system_version"] = os_version
        imgs = self.compute.list_images(**kw).data
        if not imgs:
            raise RuntimeError(f"未找到镜像 {os_name} {os_version or ''} for {shape}")
        return imgs[0].id

    def create_instance(self, p):
        """p: name, shape, ocpus, memory_gb, disk_gb, os, os_version, ad, subnet_id, image_id, ssh_key, ipv6"""
        shape = p.get("shape") or "VM.Standard.A1.Flex"
        ad = p.get("ad")
        if not ad or ad == "auto":   # 自适应 AD：抢机时每次轮换到下一个可用域
            ads = self.availability_domains()
            ad = ads[int(p.get("_ad_index") or 0) % len(ads)]
        det = oci.core.models.LaunchInstanceDetails(
            availability_domain=ad, compartment_id=self.compartment, shape=shape,
            display_name=p.get("name") or "tricloud",
            source_details=oci.core.models.InstanceSourceViaImageDetails(
                image_id=self._pick_image(shape, p.get("os") or "Canonical Ubuntu", p.get("os_version"), p.get("image_id")),
                boot_volume_size_in_gbs=int(p.get("disk_gb") or 50)),
            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=self._pick_subnet(p.get("subnet_id") or self.cred.get("default_subnet_ocid")), assign_public_ip=True,
                assign_ipv6_ip=bool(p.get("ipv6"))),
            metadata={},
        )
        # v1.5：主机名默认 = 实例名（规范化后）。hostname_label 只在子网开了 DNS 时可设
        hn = hostname.normalize(p.get("name") or "tricloud")
        if hn and self._subnet_dns(det.create_vnic_details.subnet_id):
            det.create_vnic_details.hostname_label = hn
        ssh_key = p.get("ssh_key") or self.cred.get("default_ssh_key")   # v1.5：账号级默认 SSH 公钥（从旧版迁移）
        if ssh_key:
            det.metadata["ssh_authorized_keys"] = ssh_key
        password = None
        if p.get("password_login", True) or p.get("script"):
            password = gen_password() if p.get("password_login", True) else None
            ud = cloud_init(password, "root", p.get("script"), allow_password_ssh=bool(password), hostname=hn or None)
            det.metadata["user_data"] = base64.b64encode(ud.encode()).decode()
        if shape.endswith(".Flex"):
            det.shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=float(p.get("ocpus") or 1), memory_in_gbs=float(p.get("memory_gb") or 6))
        try:
            r = self.compute.launch_instance(det).data
        except oci.exceptions.ServiceError as e:
            # 同子网 hostname_label 冲突等：去掉 label 重试一次（系统主机名仍由 cloud-init 设置）
            if not det.create_vnic_details.hostname_label or "hostname" not in str(e).lower():
                raise
            det.create_vnic_details.hostname_label = None
            r = self.compute.launch_instance(det).data
        return {"id": r.id, "name": r.display_name, "state": r.lifecycle_state, "password": password,
                "username": "root" if password else None, "ad": ad}

    @staticmethod
    def is_capacity_error(e):
        s = str(e)
        return any(h.lower() in s.lower() for h in CAPACITY_HINTS)

    # ---------- 账单 ----------
    def billing(self):
        home = self.cred.get("home_region") or self.cfg["region"]
        cfg = dict(self.cfg, region=home)
        ua = self._c(oci.usage_api.UsageapiClient, cfg)
        now = dt.datetime.now(dt.timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        r = ua.request_summarized_usages(oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=self.cfg["tenancy"], time_usage_started=start, time_usage_ended=end,
            granularity="MONTHLY", query_type="COST", group_by=["service"])).data
        by = {}
        currency = "USD"
        for it in r.items:
            amt = float(it.computed_amount or 0)
            currency = it.currency or currency
            by[it.service or "其他"] = by.get(it.service or "其他", 0) + amt
        services = sorted([{"service": k, "amount": round(v, 4)} for k, v in by.items() if abs(v) > 0.00001],
                          key=lambda x: -x["amount"])
        return {"period": f"{start:%Y-%m-%d} ~ {now:%Y-%m-%d}", "currency": currency,
                "total": round(sum(by.values()), 4), "services": services}

    # ---------- v1.2：存储用量 ----------
    def storage_usage(self):
        """块存储总用量（引导卷 + 块卷，GB），用于免费额度护栏（Always Free：200GB）。"""
        total = 0
        for ad in self.availability_domains():
            for b in oci.pagination.list_call_get_all_results(self.bs.list_boot_volumes, availability_domain=ad,
                                                             compartment_id=self.compartment).data:
                if b.lifecycle_state not in ("TERMINATED", "TERMINATING"):
                    total += int(b.size_in_gbs or 0)
            for v in oci.pagination.list_call_get_all_results(self.bs.list_volumes, availability_domain=ad,
                                                             compartment_id=self.compartment).data:
                if v.lifecycle_state not in ("TERMINATED", "TERMINATING"):
                    total += int(v.size_in_gbs or 0)
        return {"volume_gb": total}

    def wait_public_ip(self, inst_id, timeout=600):
        end = time.time() + timeout
        while time.time() < end:
            try:
                v = self._primary_vnic(inst_id)
                if v and v.public_ip:
                    return v.public_ip
            except Exception:
                pass
            time.sleep(15)
        return None
