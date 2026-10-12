"""v1.6：AWS 扩展功能（混入 AWSProvider）。
- EC2 重装系统：Replace Root Volume（用新 AMI 替换根卷；实例 ID、私网 IP、弹性 IP 不变；根卷数据清空）
- Lightsail 静态 IP：列出 / 分配 / 绑定 / 解绑 / 释放（未绑定的静态 IP 按小时计费）
- Lightsail 防火墙：查看端口规则、开放 / 关闭端口（对 0.0.0.0/0 不允许放行全部端口）
"""
import re

LS_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")


def _ls_name(n):
    if not LS_NAME.match(str(n or "")):
        raise RuntimeError("名称只能包含字母、数字、- _ .")
    return n


class AWSMore:
    # ---------- 3. EC2 重装系统 ----------
    def reinstall(self, inst_id, os_key="debian-12", progress=None):
        say = progress or (lambda m: None)
        ec2 = self.c("ec2")
        i = ec2.describe_instances(InstanceIds=[inst_id])["Reservations"][0]["Instances"][0]
        ami = self._ami(os_key or "debian-12", self._arch(i["InstanceType"]))
        say(f"用 {os_key} 替换根卷（AMI {ami}），实例会自动重启…")
        t = ec2.create_replace_root_volume_task(InstanceId=inst_id, ImageId=ami, DeleteReplacedRootVolume=True)
        tid = t["ReplaceRootVolumeTask"]["ReplaceRootVolumeTaskId"]
        return {"ok": True, "task": tid, "image_id": ami,
                "hint": "AWS 会沿用实例原来的 user-data 与密钥对；原随机 root 密码仍以「开机密码」里保存的为准（若原 user-data 设了密码）"}

    def reinstall_state(self, inst_id, task_id):
        r = self.c("ec2").describe_replace_root_volume_tasks(ReplaceRootVolumeTaskIds=[task_id])["ReplaceRootVolumeTasks"]
        return r[0]["TaskState"] if r else "unknown"

    # ---------- 19. Lightsail 静态 IP ----------
    def ls_static_ips(self):
        ls = self.c("lightsail")
        return [{"name": s["name"], "ip": s["ipAddress"], "attached_to": s.get("attachedTo"), "attached": s.get("isAttached", False)}
                for s in ls.get_static_ips()["staticIps"]]

    def ls_allocate_ip(self, name, attach_to=None):
        ls = self.c("lightsail")
        ls.allocate_static_ip(staticIpName=_ls_name(name))
        if attach_to:
            ls.attach_static_ip(staticIpName=name, instanceName=_ls_name(attach_to))
        return {"ok": True, "ip": ls.get_static_ip(staticIpName=name)["staticIp"]["ipAddress"]}

    def ls_attach_ip(self, name, instance):
        self.c("lightsail").attach_static_ip(staticIpName=_ls_name(name), instanceName=_ls_name(instance))
        return {"ok": True}

    def ls_detach_ip(self, name):
        self.c("lightsail").detach_static_ip(staticIpName=_ls_name(name))
        return {"ok": True, "hint": "已解绑：未绑定的静态 IP 会按小时计费，不用请释放"}

    def ls_release_ip(self, name):
        ls = self.c("lightsail")
        s = ls.get_static_ip(staticIpName=_ls_name(name))["staticIp"]
        if s.get("isAttached"):
            raise RuntimeError("静态 IP 仍绑定在实例上，请先解绑")
        ls.release_static_ip(staticIpName=name)
        return {"ok": True}

    # ---------- 19. Lightsail 防火墙 ----------
    def ls_ports(self, instance):
        r = self.c("lightsail").get_instance_port_states(instanceName=_ls_name(instance))["portStates"]
        return [{"from": p["fromPort"], "to": p["toPort"], "protocol": p["protocol"], "state": p.get("state"),
                 "cidrs": p.get("cidrs", []), "ipv6_cidrs": p.get("ipv6Cidrs", [])} for p in r]

    def ls_open_port(self, instance, protocol, from_port, to_port, cidrs=None):
        if protocol not in ("tcp", "udp", "all", "icmp"):
            raise RuntimeError("协议只能是 tcp / udp / icmp")
        cidrs = [c.strip() for c in (cidrs or ["0.0.0.0/0"]) if c.strip()]
        pi = {"fromPort": int(from_port), "toPort": int(to_port), "protocol": protocol, "cidrs": cidrs}
        if "0.0.0.0/0" in cidrs:
            pi["ipv6Cidrs"] = ["::/0"]
        self.c("lightsail").open_instance_public_ports(instanceName=_ls_name(instance), portInfo=pi)
        return {"ok": True}

    def ls_close_port(self, instance, protocol, from_port, to_port):
        self.c("lightsail").close_instance_public_ports(instanceName=_ls_name(instance), portInfo={
            "fromPort": int(from_port), "toPort": int(to_port), "protocol": protocol})
        return {"ok": True}
