"""AWS 适配：EC2 / Lightsail / CloudFront / Service Quotas / Cost Explorer。
凭证: {access_key, secret_key, region}
注意：Cost Explorer 每次调用 $0.01，只能经 app.billing 的缓存层调用 cost_explorer()。
"""
import concurrent.futures as cf
import datetime as dt
import threading
import time
import uuid


import boto3
from botocore.config import Config

from .. import hostname
from ..core import LightsailRegionError
from .aws_credit import AWSCredit
from .aws_more import AWSMore
from ..cloudinit import cloud_init, gen_password

_cfg = Config(retries={"max_attempts": 4, "mode": "standard"}, connect_timeout=10, read_timeout=30)
_scan_cfg = Config(retries={"max_attempts": 2, "mode": "standard"}, connect_timeout=5, read_timeout=20)

# ---------------- Lightsail 区域 ----------------
# Lightsail 只在部分区域提供服务（如台北 ap-east-2 没有），不能复用 EC2 的区域列表：
# 静态表来自 botocore 端点数据（get_available_regions('lightsail')），再用 Lightsail GetRegions 校正并缓存。
AWS_CITY = {"us-east-1": "弗吉尼亚北部", "us-east-2": "俄亥俄", "us-west-1": "加州北部", "us-west-2": "俄勒冈", "af-south-1": "开普敦",
            "ap-east-1": "香港", "ap-east-2": "台北", "ap-south-1": "孟买", "ap-south-2": "海得拉巴", "ap-northeast-1": "东京",
            "ap-northeast-2": "首尔", "ap-northeast-3": "大阪", "ap-southeast-1": "新加坡", "ap-southeast-2": "悉尼",
            "ap-southeast-3": "雅加达", "ap-southeast-4": "墨尔本", "ap-southeast-5": "吉隆坡", "ap-southeast-6": "新西兰",
            "ap-southeast-7": "曼谷", "ca-central-1": "蒙特利尔", "ca-west-1": "卡尔加里", "eu-central-1": "法兰克福",
            "eu-central-2": "苏黎世", "eu-north-1": "斯德哥尔摩", "eu-south-1": "米兰", "eu-south-2": "西班牙", "eu-west-1": "爱尔兰",
            "eu-west-2": "伦敦", "eu-west-3": "巴黎", "il-central-1": "特拉维夫", "me-central-1": "阿联酋", "me-south-1": "巴林",
            "mx-central-1": "墨西哥", "sa-east-1": "圣保罗"}
LS_REGIONS_TTL = 86400          # GetRegions 结果缓存 1 天（区域列表很少变）
_LS_GETREGIONS = {}             # "names" -> (ts, set)；进程级，所有账号共用（Lightsail 区域与账号无关）
_ls_static = None


def ls_region_msg(region):
    from ..i18n import get_lang, msg
    city = AWS_CITY.get(region)
    city_part = (city + " ") if (city and get_lang() == "zh") else ""
    return msg("err.ls_region", city=city_part, region=region)


# AWS 默认启用（Opt-in status: Not required）的 17 个商用区域，以
# https://docs.aws.amazon.com/global-infrastructure/latest/regions/aws-regions.html 为准（2026-10 核对，共 34 个区域）。
# 2019-03-20 之后上线的区域都要手动开通（af-south-1、ap-east-1/2、ap-south-2、ap-southeast-3/4/5/6/7、ca-west-1、
# eu-south-1/2、eu-central-2、il-central-1、me-south-1、me-central-1、mx-central-1 …），以后的新区域也一样，所以这里用白名单。
AWS_DEFAULT_REGIONS = frozenset((
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ap-south-1", "ap-northeast-1", "ap-northeast-2", "ap-northeast-3", "ap-southeast-1", "ap-southeast-2",
    "ca-central-1", "eu-central-1", "eu-west-1", "eu-west-2", "eu-west-3", "eu-north-1", "sa-east-1",
))


def ls_static_regions():
    global _ls_static
    if _ls_static is None:
        try:
            _ls_static = frozenset(boto3.Session().get_available_regions("lightsail"))
        except Exception:
            _ls_static = frozenset()
    return _ls_static


def ls_supported(region):
    """不发请求的快速判断：botocore 端点表里有，或最近一次 GetRegions 返回过。"""
    hit = _LS_GETREGIONS.get("names")
    if hit and time.time() - hit[0] < LS_REGIONS_TTL:
        return region in hit[1]
    return region in ls_static_regions()

VCPU_QUOTA = "L-1216C47A"        # Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances
CF_DIST_QUOTA = "L-24B04930"     # Web distributions per AWS account
# CloudFront 包月套餐（价格取自线上旧版实现的标注，以 AWS 官网为准）；PAYGO = 按量付费
CF_PLANS = {
    "PAYGO": {"label": "按量付费", "price": "按用量", "paid": False},
    "FREE": {"label": "Free", "price": "$0/月", "paid": False},
    "PRO": {"label": "Pro", "price": "$15/月", "paid": True},
    "BUSINESS": {"label": "Business", "price": "$200/月", "paid": True},
    "PREMIUM": {"label": "Premium", "price": "$1000/月起", "paid": True},
}
CF_PRICE_CLASS = {"100": "PriceClass_100", "200": "PriceClass_200", "all": "PriceClass_All"}
CF_CACHE_POLICY = {   # AWS 托管缓存策略
    "disabled": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",    # CachingDisabled：反代动态内容
    "optimized": "658327ea-f89d-4fab-a63d-7e88639e58f6",   # CachingOptimized：静态资源
}


class AWSProvider(AWSMore, AWSCredit):
    def __init__(self, cred, region=None):
        self.cred = cred
        self.region = region or cred.get("region") or "us-east-1"
        self.session = boto3.Session(aws_access_key_id=cred["access_key"],
                                     aws_secret_access_key=cred["secret_key"], region_name=self.region)
        # 每账号独立出口代理
        self.cfg = _cfg.merge(Config(proxies={"http": cred["proxy"], "https": cred["proxy"]})) if cred.get("proxy") else _cfg

    _client_lock = threading.Lock()   # boto3 Session 建客户端不是线程安全的；客户端本身线程安全，可复用

    def c(self, svc, region=None):
        """按 (服务, 区域) 复用 boto3 客户端：每次新建客户端要重新加载服务模型，既慢又占内存。"""
        key = (svc, region or self.region)
        if svc == "lightsail" and not ls_supported(key[1]):
            raise LightsailRegionError(ls_region_msg(key[1]))
        cache = self.__dict__.setdefault("_clients", {})
        cl = cache.get(key)
        if cl is None:
            with self._client_lock:
                cl = cache.get(key)
                if cl is None:
                    cl = cache[key] = self.session.client(svc, region_name=key[1], config=self.cfg)
        return cl

    def test(self):
        ident = self.c("sts").get_caller_identity()
        return {"ok": True, "account": ident["Account"]}

    def regions(self):
        return sorted(r["RegionName"] for r in self.c("ec2").describe_regions()["Regions"])

    def ls_get_regions(self):
        """Lightsail GetRegions（缓存 1 天）；失败返回 None。"""
        hit = _LS_GETREGIONS.get("names")
        if hit and time.time() - hit[0] < LS_REGIONS_TTL:
            return hit[1]
        try:
            names = frozenset(r["name"] for r in self.c("lightsail", "us-east-1").get_regions()["regions"])
        except Exception:
            return None
        if names:
            _LS_GETREGIONS["names"] = (time.time(), names)
        return names or None

    def ls_regions(self):
        """Lightsail 可用区域 = 账号已启用的区域 ∩ Lightsail 支持的区域（GetRegions 优先，失败用 botocore 端点表）。"""
        enabled = set(self.regions())
        sup = self.ls_get_regions() or ls_static_regions()
        return sorted(enabled & set(sup))

    # ---------------- EC2 ----------------
    def list_instances(self):
        out = []
        pg = self.c("ec2").get_paginator("describe_instances")
        for page in pg.paginate():
            for res in page["Reservations"]:
                for i in res["Instances"]:
                    st = i["State"]["Name"]
                    if st == "terminated":
                        continue
                    name = next((t["Value"] for t in i.get("Tags", []) if t["Key"] == "Name"), i["InstanceId"])
                    ipv6 = [a["Ipv6Address"] for n in i.get("NetworkInterfaces", []) for a in n.get("Ipv6Addresses", [])]
                    out.append({"id": i["InstanceId"], "name": name, "state": st,
                                "public_ip": i.get("PublicIpAddress"), "private_ip": i.get("PrivateIpAddress"),
                                "ipv6": ipv6, "shape": i["InstanceType"], "region": self.region,
                                "zone": i["Placement"]["AvailabilityZone"], "created": str(i.get("LaunchTime"))})
        return out

    def action(self, inst_id, action):
        ec2 = self.c("ec2")
        {"start": lambda: ec2.start_instances(InstanceIds=[inst_id]),
         "stop": lambda: ec2.stop_instances(InstanceIds=[inst_id]),
         "reboot": lambda: ec2.reboot_instances(InstanceIds=[inst_id]),
         "terminate": lambda: ec2.terminate_instances(InstanceIds=[inst_id])}[action]()
        return {"ok": True}

    # ---------- 改名 + 同步主机名（v1.5，仅 EC2；Lightsail 不支持改名） ----------
    def rename(self, inst_id, name):
        self.c("ec2").create_tags(Resources=[inst_id], Tags=[{"Key": "Name", "Value": name}])
        return {"ok": True}

    def get_state(self, inst_id):
        r = self.c("ec2").describe_instances(InstanceIds=[inst_id])
        return r["Reservations"][0]["Instances"][0]["State"]["Name"]

    def _public_ip(self, inst_id):
        r = self.c("ec2").describe_instances(InstanceIds=[inst_id])
        return r["Reservations"][0]["Instances"][0].get("PublicIpAddress")

    def change_ip(self, inst_id, mode="auto", progress=None):
        """mode: eip（重分配弹性 IP） / stopstart（停机换 IP） / auto（有 EIP 则重分配，否则停机）"""
        ec2 = self.c("ec2")
        addrs = ec2.describe_addresses(Filters=[{"Name": "instance-id", "Values": [inst_id]}])["Addresses"]
        if mode == "eip" or (mode == "auto" and addrs):
            old = addrs[0] if addrs else None
            new = ec2.allocate_address(Domain="vpc")
            ec2.associate_address(InstanceId=inst_id, AllocationId=new["AllocationId"], AllowReassociation=True)
            if old:
                # 先解绑再释放，避免闲置 EIP 计费
                try:
                    ec2.release_address(AllocationId=old["AllocationId"])
                except Exception:
                    time.sleep(3)
                    ec2.release_address(AllocationId=old["AllocationId"])
            return {"old_ip": old["PublicIp"] if old else None, "new_ip": new["PublicIp"], "mode": "eip"}
        # 停机换 IP
        old_ip = self._public_ip(inst_id)
        if progress:
            progress("正在停止实例…")
        ec2.stop_instances(InstanceIds=[inst_id])
        ec2.get_waiter("instance_stopped").wait(InstanceIds=[inst_id], WaiterConfig={"Delay": 10, "MaxAttempts": 60})
        if progress:
            progress("正在启动实例…")
        ec2.start_instances(InstanceIds=[inst_id])
        ec2.get_waiter("instance_running").wait(InstanceIds=[inst_id], WaiterConfig={"Delay": 5, "MaxAttempts": 60})
        return {"old_ip": old_ip, "new_ip": self._public_ip(inst_id), "mode": "stopstart"}

    # ---------------- EC2 创建 / 区域激活 / 全区域扫描 ----------------
    AMI_PARAMS = {
        "ubuntu-24.04": "/aws/service/canonical/ubuntu/server/24.04/stable/current/{arch}/hvm/ebs-gp3/ami-id",
        "ubuntu-22.04": "/aws/service/canonical/ubuntu/server/22.04/stable/current/{arch}/hvm/ebs-gp2/ami-id",
        "debian-12": "/aws/service/debian/release/12/latest/{arch}",
        "al2023": "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-{arch2}",
    }
    EC2_TYPES = ["t2.micro", "t3.micro", "t3.small", "t3.medium", "t4g.micro", "t4g.small", "t4g.medium",
                 "c5.large", "c6g.large", "c7g.large", "m5.large", "m6g.large", "r6g.large"]

    def _arch(self, itype):
        r = self.c("ec2").describe_instance_types(InstanceTypes=[itype])["InstanceTypes"][0]
        return "arm64" if "arm64" in r["ProcessorInfo"]["SupportedArchitectures"] else "amd64"

    def _ami(self, os_key, arch):
        tpl = self.AMI_PARAMS.get(os_key) or self.AMI_PARAMS["debian-12"]
        name = tpl.format(arch=arch, arch2="arm64" if arch == "arm64" else "x86_64")
        return self.c("ssm").get_parameter(Name=name)["Parameter"]["Value"]

    def _sg(self, ports):
        """面板专用安全组：默认只放行 22；用户填的端口额外放行。不默认全端口放行。"""
        ec2 = self.c("ec2")
        vpc = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
        if not vpc:
            raise RuntimeError("该区域没有默认 VPC，请先在控制台创建默认 VPC")
        vpc_id = vpc[0]["VpcId"]
        name = "tricloud-" + ("-".join(str(p) for p in ports) if ports else "ssh")
        found = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [name[:255]]},
                                                      {"Name": "vpc-id", "Values": [vpc_id]}])["SecurityGroups"]
        if found:
            return found[0]["GroupId"]
        gid = ec2.create_security_group(GroupName=name[:255], Description="TriCloud", VpcId=vpc_id)["GroupId"]
        perms = []
        for p in sorted({22, *ports}):
            perms.append({"IpProtocol": "tcp", "FromPort": p, "ToPort": p, "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                          "Ipv6Ranges": [{"CidrIpv6": "::/0"}]})
        ec2.authorize_security_group_ingress(GroupId=gid, IpPermissions=perms)
        return gid

    def ec2_options(self):
        return {"types": self.EC2_TYPES, "os": list(self.AMI_PARAMS.keys())}

    def ec2_create(self, p):
        """p: name, type, os, disk_gb, ports(逗号分隔), password_login, script, key_name"""
        ec2 = self.c("ec2")
        itype = p.get("type") or "t3.micro"
        ami = self._ami(p.get("os") or "debian-12", self._arch(itype))
        ports = [int(x) for x in str(p.get("ports") or "").replace("，", ",").split(",") if x.strip().isdigit()]
        password = gen_password() if p.get("password_login", True) else None
        hn = hostname.normalize(p.get("name") or "tricloud")   # v1.5：主机名默认 = 实例名（规范化后）
        ud = cloud_init(password, "root", p.get("script"), allow_password_ssh=bool(password), hostname=hn or None)
        kw = dict(ImageId=ami, InstanceType=itype, MinCount=1, MaxCount=1, UserData=ud,
                  SecurityGroupIds=[self._sg(ports)],
                  BlockDeviceMappings=[{"DeviceName": ec2.describe_images(ImageIds=[ami])["Images"][0]["RootDeviceName"],
                                        "Ebs": {"VolumeSize": int(p.get("disk_gb") or 10), "VolumeType": "gp3",
                                                "DeleteOnTermination": True}}],
                  TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": p.get("name") or "tricloud"}]}],
                  MetadataOptions={"HttpTokens": "required"})
        if p.get("key_name"):
            kw["KeyName"] = p["key_name"]
        i = ec2.run_instances(**kw)["Instances"][0]
        return {"id": i["InstanceId"], "name": p.get("name") or "tricloud", "state": i["State"]["Name"],
                "password": password, "username": "root" if password else None}

    def open_ports(self, inst_id, protocol, ranges):
        """实例操作「开放端口」：写入实例关联的全部安全组，来源 0.0.0.0/0；已有相同规则的跳过。"""
        ec2 = self.c("ec2")
        inst = ec2.describe_instances(InstanceIds=[inst_id])["Reservations"][0]["Instances"][0]
        sg_ids = list(dict.fromkeys(g["GroupId"] for g in inst.get("SecurityGroups", [])))
        if not sg_ids:
            raise ValueError("实例未关联安全组")
        groups, added_all, skipped_all = [], 0, 0
        for sg in ec2.describe_security_groups(GroupIds=sg_ids)["SecurityGroups"]:
            have = set()
            for perm in sg.get("IpPermissions", []):
                if any(r.get("CidrIp") == "0.0.0.0/0" for r in perm.get("IpRanges", [])):
                    proto = perm.get("IpProtocol")
                    if proto == "-1":
                        have.add("all")
                    elif proto == protocol:
                        have.add((perm.get("FromPort"), perm.get("ToPort")))
            new, skipped = [], 0
            for a, b in ranges:
                if "all" in have or (a, b) in have:
                    skipped += 1
                    continue
                new.append({"IpProtocol": protocol, "FromPort": a, "ToPort": b,
                            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "TriCloud open port"}]})
            added = 0
            for perm in new:   # 逐条提交：个别规则并发重复时不影响其它
                try:
                    ec2.authorize_security_group_ingress(GroupId=sg["GroupId"], IpPermissions=[perm])
                    added += 1
                except Exception as e:
                    if "InvalidPermission.Duplicate" not in str(e):
                        raise
                    skipped += 1
            groups.append({"kind": "安全组", "id": sg["GroupId"], "name": sg.get("GroupName") or sg["GroupId"],
                           "added": added, "skipped": skipped})
            added_all += added
            skipped_all += skipped
        return {"ok": True, "added": added_all, "skipped": skipped_all, "groups": groups}

    def region_status(self):
        acct = self.c("account", "us-east-1")
        out, token = [], None
        while True:
            r = acct.list_regions(**({"NextToken": token} if token else {}), MaxResults=50)
            out += [{"region": x["RegionName"], "status": x["RegionOptStatus"]} for x in r["Regions"]]
            token = r.get("NextToken")
            if not token:
                return sorted(out, key=lambda x: x["region"])

    def enable_region(self, region):
        self.c("account", "us-east-1").enable_region(RegionName=region)
        return {"ok": True, "hint": "激活通常需要几分钟到数小时，状态会从 ENABLING 变为 ENABLED"}

    # ---------------- 全区域扫描（总览 / 区域扫描页共用，免费 API） ----------------
    SCAN_WORKERS = 4    # 每账号并发区域数上限（总览刷新不会对一个账号同时打 30+ 个请求）
    # 区域未启用（opt-in 区域没开）时 EC2 返回这些错误：静态区域表兜底时把它当作「未启用」跳过，不算查询失败
    OPTIN_ERRORS = ("AuthFailure", "OptInRequired", "UnrecognizedClientException", "InvalidClientTokenId")

    def cs(self, svc, region):
        """扫描专用客户端：连接超时 5 秒、最多 2 次尝试（某个区域网络不通时不拖住整个总览）。"""
        if svc == "lightsail" and not ls_supported(region):
            raise LightsailRegionError(ls_region_msg(region))
        key = (svc + "#scan", region)
        cache = self.__dict__.setdefault("_clients", {})
        cl = cache.get(key)
        if cl is None:
            with self._client_lock:
                cl = cache.get(key)
                if cl is None:
                    cl = cache[key] = self.session.client(svc, region_name=region, config=self.cfg.merge(_scan_cfg))
        return cl

    def scan_region_list(self, keep=()):
        """账号已启用的区域 → (regions, source)。
        DescribeRegions 优先（只取 opt-in-not-required / opted-in）；IAM 不给 ec2:DescribeRegions 时用 account:ListRegions；
        再不行用 botocore 静态区域表 ∩ 默认启用区域（AWS_DEFAULT_REGIONS）——需手动开通的 opt-in 区域（如巴林 me-south-1）
        没开通时可能连接超时，被误报为「区域查询失败」，所以不扫；keep 里的区域（已知有机器 / 默认区域 / 新建过实例）照样扫描。"""
        try:
            rs = sorted(r["RegionName"] for r in self.c("ec2").describe_regions()["Regions"]
                        if r.get("OptInStatus") in (None, "opt-in-not-required", "opted-in"))
            return rs, "describe_regions"
        except Exception:
            pass
        try:
            rs = sorted(x["region"] for x in self.region_status() if x["status"] in ("ENABLED", "ENABLED_BY_DEFAULT"))
            if rs:
                return rs, "list_regions"
        except Exception:
            pass
        static = set(boto3.session.Session().get_available_regions("ec2"))
        return sorted((static & AWS_DEFAULT_REGIONS) | {r for r in keep if r}), "static"

    @staticmethod
    def _err_code(e):
        return ((getattr(e, "response", None) or {}).get("Error") or {}).get("Code") or type(e).__name__

    def scan_region(self, rg, ls_ok=True):
        """单个区域：EC2（非 terminated）与 Lightsail 台数 / 运行数。Lightsail 不支持的区域 lightsail=None。"""
        row = {"region": rg, "ec2": 0, "ec2_running": 0, "lightsail": None, "lightsail_running": 0}
        try:
            for page in self.cs("ec2", rg).get_paginator("describe_instances").paginate():
                for res in page["Reservations"]:
                    for i in res["Instances"]:
                        st = i["State"]["Name"]
                        if st != "terminated":
                            row["ec2"] += 1
                            row["ec2_running"] += st == "running"
        except Exception as e:
            code = self._err_code(e)
            if code in self.OPTIN_ERRORS:
                row["not_enabled"] = True
                return row
            row["error"] = row["ec2_error"] = code
        if ls_ok:
            try:
                ls, token, n, run = self.cs("lightsail", rg), None, 0, 0
                while True:
                    r = ls.get_instances(**({"pageToken": token} if token else {}))
                    for i in r["instances"]:
                        n += 1
                        run += (i.get("state") or {}).get("name") == "running"
                    token = r.get("nextPageToken")
                    if not token:
                        break
                row["lightsail"], row["lightsail_running"] = n, run
            except Exception as e:
                row["lightsail_error"] = self._err_code(e)
                row.setdefault("error", row["lightsail_error"])
        return row

    def scan_all_regions(self, regions=None, keep=()):
        """逐区域统计 EC2 / Lightsail 数量（并发 SCAN_WORKERS 个区域，免费 API）。
        regions=None 时扫描账号全部已启用区域；静态区域表兜底时只扫默认启用区域 + keep，未启用的区域不出现在结果里。"""
        src = "given"
        if regions is None:
            regions, src = self.scan_region_list(keep)
        ls_regions = set(self.ls_get_regions() or ls_static_regions())   # 不支持 Lightsail 的区域（如台北）跳过，显示 -
        regions = list(dict.fromkeys(regions))
        if not regions:
            return []
        with cf.ThreadPoolExecutor(max_workers=min(self.SCAN_WORKERS, len(regions))) as ex:
            rows = list(ex.map(lambda rg: self.scan_region(rg, rg in ls_regions), regions))
        if src == "static":
            rows = [r for r in rows if not r.get("not_enabled")]
        return rows

    # ---------------- Lightsail ----------------
    def ls_list(self):
        ls = self.c("lightsail")
        out, token = [], None
        while True:
            r = ls.get_instances(**({"pageToken": token} if token else {}))
            for i in r["instances"]:
                out.append({"id": i["name"], "name": i["name"], "state": i["state"]["name"],
                            "public_ip": i.get("publicIpAddress"), "private_ip": i.get("privateIpAddress"),
                            "ipv6": i.get("ipv6Addresses", []), "shape": i["bundleId"], "blueprint": i["blueprintId"],
                            "static_ip": i.get("isStaticIp", False), "region": self.region,
                            "zone": i["location"]["availabilityZone"], "created": str(i.get("createdAt"))})
            token = r.get("nextPageToken")
            if not token:
                return out

    def ls_action(self, name, action):
        ls = self.c("lightsail")
        {"start": lambda: ls.start_instance(instanceName=name),
         "stop": lambda: ls.stop_instance(instanceName=name),
         "reboot": lambda: ls.reboot_instance(instanceName=name),
         "terminate": lambda: ls.delete_instance(instanceName=name, forceDeleteAddOns=True)}[action]()
        return {"ok": True}

    def ls_change_ip(self, name):
        """通过静态 IP 轮换：分配新静态 IP → 绑定 → 释放旧静态 IP。"""
        ls = self.c("lightsail")
        inst = ls.get_instance(instanceName=name)["instance"]
        old_ip = inst.get("publicIpAddress")
        old_static = None
        if inst.get("isStaticIp"):
            for s in ls.get_static_ips()["staticIps"]:
                if s.get("attachedTo") == name:
                    old_static = s["name"]
        new_name = f"tc-{name[:30]}-{uuid.uuid4().hex[:6]}"
        ls.allocate_static_ip(staticIpName=new_name)
        if old_static:
            ls.detach_static_ip(staticIpName=old_static)
        ls.attach_static_ip(staticIpName=new_name, instanceName=name)
        if old_static:
            ls.release_static_ip(staticIpName=old_static)
        new_ip = ls.get_static_ip(staticIpName=new_name)["staticIp"]["ipAddress"]
        return {"old_ip": old_ip, "new_ip": new_ip}

    def ls_options(self):
        ls = self.c("lightsail")
        bps = [{"id": b["blueprintId"], "name": f'{b["name"]} {b.get("version", "")}'.strip()}
               for b in ls.get_blueprints(includeInactive=False)["blueprints"]
               if b["type"] == "os" and b.get("platform") == "LINUX_UNIX"]
        bundles = [{"id": b["bundleId"], "name": f'{b["name"]} · {b["cpuCount"]}C/{b["ramSizeInGb"]}G/{b["diskSizeInGb"]}G · ${b["price"]}/月'}
                   for b in ls.get_bundles(includeInactive=False)["bundles"]
                   if "LINUX_UNIX" in b.get("supportedPlatforms", [])]
        zones = [z["zoneName"] for r in ls.get_regions(includeAvailabilityZones=True)["regions"]
                 if r["name"] == self.region for z in r.get("availabilityZones", [])]
        return {"blueprints": bps, "bundles": bundles, "zones": zones}

    def ls_create(self, p):
        ls = self.c("lightsail")
        kw = dict(instanceNames=[p["name"]], availabilityZone=p.get("zone") or f"{self.region}a",
                  blueprintId=p["blueprint"], bundleId=p["bundle"])
        ud = p.get("user_data") or ""
        password = None
        if p.get("password_login"):
            # Lightsail 的 userData 是 shell 启动脚本：设随机 root 密码并开启密码登录
            password = gen_password()
            ud = ("#!/bin/bash\n"
                  f"echo 'root:{password}' | chpasswd\n"
                  "sed -i 's/^#\\?PasswordAuthentication.*/PasswordAuthentication yes/; s/^#\\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config\n"
                  "rm -f /etc/ssh/sshd_config.d/*cloud*.conf; systemctl restart ssh || systemctl restart sshd\n"
                  + (ud.split("\n", 1)[1] if ud.startswith("#!") else ud))
        if ud:
            kw["userData"] = ud
        if p.get("ip_type"):
            kw["ipAddressType"] = p["ip_type"]
        ls.create_instances(**kw)
        return {"ok": True, "id": p["name"], "name": p["name"], "password": password, "username": "root" if password else None}

    # ---------------- CloudFront ----------------
    def cf_list(self):
        cf = self.c("cloudfront", "us-east-1")
        out = []
        for page in cf.get_paginator("list_distributions").paginate():
            for d in page["DistributionList"].get("Items", []):
                out.append({"id": d["Id"], "domain": d["DomainName"], "status": d["Status"], "enabled": d["Enabled"],
                            "origins": [o["DomainName"] for o in d["Origins"]["Items"]],
                            "aliases": d.get("Aliases", {}).get("Items", []), "comment": d.get("Comment", ""),
                            "price_class": (d.get("PriceClass") or "").replace("PriceClass_", "")})
        plans = self.cf_plans() if out else {}
        for d in out:   # v1.5：plans 为 None = 无权限 / 查询失败，套餐显示「未知」
            d["plan"] = None if plans is None else plans.get(d["id"], "PAYGO")
        return out

    # ---------- v1.5 CloudFront：状态 / 缓存刷新 / 编辑 / 套餐 ----------
    def _cf(self):
        return self.c("cloudfront", "us-east-1")    # CloudFront 是全局服务

    def cf_state(self, dist_id):
        d = self._cf().get_distribution(Id=dist_id)["Distribution"]
        return {"id": dist_id, "status": d["Status"], "enabled": bool(d["DistributionConfig"]["Enabled"])}

    def cf_invalidate(self, dist_id, paths):
        """缓存刷新。每月前 1000 条路径免费（通配符 /* 算 1 条），之后按路径计费，所以一次最多 100 条。"""
        clean = []
        for p in paths or []:
            p = str(p).strip()
            if p and p not in clean:
                clean.append(p if p.startswith("/") else "/" + p)
        clean = clean or ["/*"]
        if len(clean) > 100:
            raise ValueError("一次最多刷新 100 条路径（可用 /* 通配）")
        inv = self._cf().create_invalidation(DistributionId=dist_id, InvalidationBatch={
            "Paths": {"Quantity": len(clean), "Items": clean}, "CallerReference": f"tricloud-{uuid.uuid4().hex[:12]}"})["Invalidation"]
        return {"ok": True, "invalidation_id": inv["Id"], "status": inv["Status"], "paths": clean}

    def cf_get_config(self, dist_id):
        r = self._cf().get_distribution_config(Id=dist_id)
        cfg = r["DistributionConfig"]
        origins = (cfg.get("Origins") or {}).get("Items", [])
        o = origins[0] if origins else {}
        return {"id": dist_id, "comment": cfg.get("Comment", ""), "origin_domain": o.get("DomainName", ""),
                "origin_protocol": (o.get("CustomOriginConfig") or {}).get("OriginProtocolPolicy", ""),
                "price_class": (cfg.get("PriceClass") or "").replace("PriceClass_", ""),
                "default_root_object": cfg.get("DefaultRootObject", ""), "enabled": bool(cfg.get("Enabled")),
                "aliases": (cfg.get("Aliases") or {}).get("Items", [])}

    def cf_update(self, dist_id, params):
        """修改备注 / 源站域名 / 回源协议 / 价格等级 / 默认根对象 / 启用状态，带 ETag 防并发覆盖。"""
        cf = self._cf()
        r = cf.get_distribution_config(Id=dist_id)
        cfg, changed = r["DistributionConfig"], []
        if params.get("comment") is not None:
            cfg["Comment"] = str(params["comment"])[:128]
            changed.append("备注")
        origins = (cfg.get("Origins") or {}).get("Items", [])
        if params.get("origin_domain"):
            if not origins:
                raise ValueError("该分发没有源站")
            new = str(params["origin_domain"]).strip().removeprefix("https://").removeprefix("http://").strip("/")
            if not new or "/" in new or " " in new:
                raise ValueError("源站域名格式不正确（不要带路径）")
            if origins[0]["DomainName"] != new:
                origins[0]["DomainName"] = new
                changed.append("源站")
        if params.get("origin_protocol"):
            if params["origin_protocol"] not in ("http-only", "https-only", "match-viewer"):
                raise ValueError("回源协议只能是 http-only / https-only / match-viewer")
            if not origins or "CustomOriginConfig" not in origins[0]:
                raise ValueError("该源站不是自定义源站，不能修改回源协议")
            origins[0]["CustomOriginConfig"]["OriginProtocolPolicy"] = params["origin_protocol"]
            changed.append("回源协议")
        if params.get("price_class"):
            pc = CF_PRICE_CLASS.get(str(params["price_class"]).lower())
            if not pc:
                raise ValueError("价格等级只能是 100 / 200 / All")
            cfg["PriceClass"] = pc
            changed.append("价格等级")
        if params.get("default_root_object") is not None:
            cfg["DefaultRootObject"] = str(params["default_root_object"]).strip().lstrip("/")
            changed.append("默认根对象")
        if params.get("enabled") is not None:
            cfg["Enabled"] = bool(params["enabled"])
            changed.append("启用状态")
        if not changed:
            raise ValueError("没有要修改的字段")
        try:
            cf.update_distribution(Id=dist_id, IfMatch=r["ETag"], DistributionConfig=cfg)
        except cf.exceptions.PreconditionFailed:
            raise ValueError("配置已被其他人修改，请刷新后重试")
        return {"ok": True, "changed": changed, "message": f"已更新：{'、'.join(changed)}（部署约需几分钟）"}

    def _ppm(self):
        return self.c("pricing-plan-manager", "us-east-1")

    def cf_plans(self):
        """{dist_id: 套餐}；按量付费的分发不在其中。无权限 / 不支持时返回 None。"""
        try:
            out = {}
            for page in self._ppm().get_paginator("list_subscriptions").paginate():
                for sub in page.get("subscriptionSummaries", []):
                    if sub.get("planFamily") != "CloudFront" or (sub.get("status") or "").upper() not in ("ACTIVE", "PENDING_APPROVAL"):
                        continue
                    for arn in sub.get("resourceArns", []):
                        if ":distribution/" in arn:   # arn:aws:cloudfront::<账号>:distribution/<ID>
                            out[arn.split(":distribution/")[-1]] = (sub.get("planTier") or "").upper()
            return out
        except Exception:
            return None

    def cf_set_plan(self, dist_id, tier):
        """切换套餐：FREE / PRO / BUSINESS / PREMIUM（订阅），PAYGO（从订阅解绑，回到按量付费）。计费操作。"""
        tier = tier.upper()
        account = self.c("sts").get_caller_identity()["Account"]
        arn = f"arn:aws:cloudfront::{account}:distribution/{dist_id}"
        ppm = self._ppm()
        current = None
        for page in ppm.get_paginator("list_subscriptions").paginate():
            for sub in page.get("subscriptionSummaries", []):
                if sub.get("planFamily") == "CloudFront" and arn in sub.get("resourceArns", []):
                    current = sub
        if tier == "PAYGO":
            if not current:
                raise ValueError("该分发已是按量付费")
            ppm.disassociate_resources_from_subscription(arn=current["arn"], resourceArns=[arn])
            return {"ok": True, "plan": "PAYGO", "message": "已切回按量付费"}
        if current and (current.get("planTier") or "").upper() == tier:
            raise ValueError(f"该分发已是 {tier} 套餐")
        sub = ppm.create_subscription(planFamily="CloudFront", planTier=tier, resourceArns=[arn], approvalMode="IMMEDIATE",
                                      clientToken=f"tricloud-{dist_id}-{uuid.uuid4().hex[:8]}").get("subscription", {})
        return {"ok": True, "plan": tier, "status": sub.get("status"),
                "message": f"已订阅 {tier} 套餐（{CF_PLANS[tier]['price']}），状态 {sub.get('status') or '未知'}"}

    def cf_set_enabled(self, dist_id, enabled: bool):
        cf = self.c("cloudfront", "us-east-1")
        r = cf.get_distribution_config(Id=dist_id)
        cfg = r["DistributionConfig"]
        cfg["Enabled"] = enabled
        cf.update_distribution(Id=dist_id, IfMatch=r["ETag"], DistributionConfig=cfg)
        return {"ok": True}

    def cf_delete(self, dist_id):
        cf = self.c("cloudfront", "us-east-1")
        r = cf.get_distribution(Id=dist_id)
        d = r["Distribution"]
        if d["DistributionConfig"]["Enabled"] or d["Status"] != "Deployed":
            raise RuntimeError("需先禁用分发并等待状态变为 Deployed 后才能删除")
        cf.delete_distribution(Id=dist_id, IfMatch=r["ETag"])
        return {"ok": True}

    def cf_create(self, origin_domain, comment="", origin_protocol="http-only", price_class="all", compress=True,
                  cache_mode="disabled"):
        """新建分发。默认（v1.1 起）：CachingDisabled + AllViewer、全部边缘节点，适合反代动态内容。
        v1.5 可选：price_class 100/200/all、compress、cache_mode=optimized（CachingOptimized，适合静态资源）。"""
        origin_domain = (origin_domain or "").strip().removeprefix("https://").removeprefix("http://").strip("/")
        if not origin_domain or "/" in origin_domain or " " in origin_domain:
            raise ValueError("请填写源站域名（如 origin.example.com，不带路径）")
        if origin_protocol not in ("http-only", "https-only", "match-viewer"):
            raise ValueError("回源协议只能是 http-only / https-only / match-viewer")
        if str(price_class).lower() not in CF_PRICE_CLASS or cache_mode not in CF_CACHE_POLICY:
            raise ValueError("价格等级或缓存模式无效")
        cf = self.c("cloudfront", "us-east-1")
        oid = "origin-1"
        cfg = {
            "CallerReference": uuid.uuid4().hex, "Comment": comment or "TriCloud", "Enabled": True,
            "Origins": {"Quantity": 1, "Items": [{
                "Id": oid, "DomainName": origin_domain,
                "CustomOriginConfig": {"HTTPPort": 80, "HTTPSPort": 443, "OriginProtocolPolicy": origin_protocol,
                                       "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]}}}]},
            "DefaultCacheBehavior": {
                "TargetOriginId": oid, "ViewerProtocolPolicy": "allow-all",
                # AWS 托管策略：CachingDisabled + AllViewer，适合反代/动态内容
                "CachePolicyId": CF_CACHE_POLICY[cache_mode],
                "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3",
                "AllowedMethods": {"Quantity": 7, "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                                   "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}},
                "Compress": bool(compress)},
            "PriceClass": CF_PRICE_CLASS[str(price_class).lower()], "HttpVersion": "http2and3",
        }
        d = cf.create_distribution(DistributionConfig=cfg)["Distribution"]
        return {"id": d["Id"], "domain": d["DomainName"]}

    # ---------------- 配额（只查两项） ----------------
    @staticmethod
    def _clean_unit(u):
        return "" if not u or u == "None" else u

    def quotas(self):
        """Standard vCPU：逐区域查询取最大值（串行+间隔，避免限流）；CloudFront 分发配额。"""
        per_region, best = [], None
        for rg in self.regions():
            try:
                q = self.c("service-quotas", rg).get_service_quota(ServiceCode="ec2", QuotaCode=VCPU_QUOTA)["Quota"]
                v = q["Value"]
                per_region.append({"region": rg, "value": v})
                if best is None or v > best["value"]:
                    best = {"region": rg, "value": v, "unit": self._clean_unit(q.get("Unit"))}
            except Exception as e:  # 未启用区域等
                per_region.append({"region": rg, "value": None, "error": type(e).__name__})
            time.sleep(0.3)
        cf = None
        try:
            qd = self.c("service-quotas", "us-east-1").get_service_quota(ServiceCode="cloudfront", QuotaCode=CF_DIST_QUOTA)["Quota"]
            cf = {"value": qd["Value"], "unit": self._clean_unit(qd.get("Unit"))}
        except Exception as e:
            try:
                qd = self.c("service-quotas", "us-east-1").get_aws_default_service_quota(
                    ServiceCode="cloudfront", QuotaCode=CF_DIST_QUOTA)["Quota"]
                cf = {"value": qd["Value"], "unit": self._clean_unit(qd.get("Unit")), "default": True}
            except Exception:
                cf = {"error": str(e)}
        return {"standard_vcpu": best, "per_region": per_region, "cloudfront_distributions": cf}

    # ---------------- 回收站（闲置但仍计费的资源，全部免费 API） ----------------
    # 参考单价（us-east-1 公示价，USD/月），仅用于估算，实际以账单为准
    PRICE = {"gp3": 0.08, "gp2": 0.10, "io1": 0.125, "io2": 0.125, "st1": 0.045, "sc1": 0.015,
             "standard": 0.05, "snapshot": 0.05, "rbin_snapshot": 0.05, "ipv4": 3.6}
    LS_BUNDLE_FALLBACK = 5.0

    def recycle_bin(self):
        """列出当前区域"停了/没挂载但还在扣钱"的资源，并估算月费。"""
        ec2 = self.c("ec2")
        items = []

        def add(kind, rid, name, detail, monthly, tip):
            items.append({"kind": kind, "id": rid, "name": name, "detail": detail,
                          "monthly": round(monthly, 2), "tip": tip})

        # 1) 已停止的 EC2：EBS 照常计费
        vols = {v["VolumeId"]: v for page in ec2.get_paginator("describe_volumes").paginate()
                for v in page["Volumes"]}
        for page in ec2.get_paginator("describe_instances").paginate(
                Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]):
            for res in page["Reservations"]:
                for i in res["Instances"]:
                    name = next((t["Value"] for t in i.get("Tags", []) if t["Key"] == "Name"), i["InstanceId"])
                    gb, cost = 0, 0.0
                    for m in i.get("BlockDeviceMappings", []):
                        v = vols.get(m.get("Ebs", {}).get("VolumeId"))
                        if v:
                            gb += v["Size"]
                            cost += v["Size"] * self.PRICE.get(v["VolumeType"], 0.10)
                    add("stopped_instance", i["InstanceId"], name, f"已停止 · 系统盘 {gb} GB", cost,
                        "实例停止后硬盘仍计费，不用请终止")
        # 2) 未挂载的 EBS 卷
        for v in vols.values():
            if v["State"] == "available":
                name = next((t["Value"] for t in v.get("Tags", []) if t["Key"] == "Name"), v["VolumeId"])
                add("volume", v["VolumeId"], name, f"未挂载 · {v['VolumeType']} {v['Size']} GB",
                    v["Size"] * self.PRICE.get(v["VolumeType"], 0.10), "未挂载的卷可删除")
        # 3) 闲置弹性 IP
        for a in ec2.describe_addresses()["Addresses"]:
            if not a.get("AssociationId"):
                add("eip", a.get("AllocationId"), a.get("PublicIp"), "弹性 IP 未绑定", self.PRICE["ipv4"],
                    "闲置弹性 IP 按小时收费，不用请释放")
        # 4) 自有快照
        for page in ec2.get_paginator("describe_snapshots").paginate(OwnerIds=["self"]):
            for sn in page["Snapshots"]:
                add("snapshot", sn["SnapshotId"], sn.get("Description") or sn["SnapshotId"],
                    f"快照 · {sn['VolumeSize']} GB（按卷大小估算上限）",
                    sn["VolumeSize"] * self.PRICE["snapshot"], "快照为增量存储，实际费用通常更低")
        # 5) AWS 回收站（Recycle Bin）里保留的快照
        try:
            tok = None
            while True:
                r = ec2.list_snapshots_in_recycle_bin(**({"NextToken": tok} if tok else {}))
                for sn in r.get("Snapshots", []):
                    add("rbin_snapshot", sn["SnapshotId"], sn.get("Description") or sn["SnapshotId"],
                        f"Recycle Bin 保留 · {sn.get('VolumeSize', 0)} GB · 到期 {str(sn.get('RecycleBinExitTime', ''))[:10]}",
                        sn.get("VolumeSize", 0) * self.PRICE["rbin_snapshot"], "回收站内快照照常按快照计费")
                tok = r.get("NextToken")
                if not tok:
                    break
        except Exception:
            pass
        # 6) Lightsail：停止的实例照常按套餐计费；未绑定静态 IP 收费
        try:
            ls = self.c("lightsail")
            prices = {b["bundleId"]: b["price"] for b in ls.get_bundles(includeInactive=True)["bundles"]}
            for i in self.ls_list():
                if i["state"] == "stopped":
                    add("ls_stopped", i["id"], i["name"], f"Lightsail 已停止 · {i['shape']}",
                        prices.get(i["shape"], self.LS_BUNDLE_FALLBACK), "Lightsail 停机仍按套餐全额计费")
            for s in ls.get_static_ips()["staticIps"]:
                if not s.get("isAttached"):
                    add("ls_static_ip", s["name"], s.get("ipAddress"), "Lightsail 静态 IP 未绑定",
                        self.PRICE["ipv4"], "未绑定的静态 IP 收费，不用请释放")
        except Exception:
            pass
        items.sort(key=lambda x: -x["monthly"])
        return {"region": self.region, "items": items, "monthly_total": round(sum(i["monthly"] for i in items), 2)}

    # ---------------- Cost Explorer（收费！仅由缓存层调用） ----------------
    def cost_explorer(self, credit_since=None):
        """一次刷新最多 2 次 CE 调用：本月按服务、自 credit 起始日累计抵扣。"""
        ce = self.c("ce", "us-east-1")
        today = dt.date.today()
        start = today.replace(day=1)
        end = today + dt.timedelta(days=1)
        r = ce.get_cost_and_usage(TimePeriod={"Start": str(start), "End": str(end)}, Granularity="MONTHLY",
                                  Metrics=["UnblendedCost"], GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}])
        services, total, unit = [], 0.0, "USD"
        for res in r["ResultsByTime"]:
            for g in res["Groups"]:
                m = g["Metrics"]["UnblendedCost"]
                amt = float(m["Amount"])
                unit = m["Unit"]
                total += amt
                if abs(amt) > 0.00001:
                    services.append({"service": g["Keys"][0], "amount": round(amt, 4)})
        services.sort(key=lambda x: -x["amount"])
        credits_used = None
        if credit_since:
            r2 = ce.get_cost_and_usage(TimePeriod={"Start": credit_since, "End": str(end)}, Granularity="MONTHLY",
                                       Metrics=["UnblendedCost"],
                                       Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit"]}})
            credits_used = -sum(float(x["Total"]["UnblendedCost"]["Amount"]) for x in r2["ResultsByTime"])
        return {"period": f"{start} ~ {today}", "currency": unit, "total": round(total, 4),
                "services": services, "credits_used": None if credits_used is None else round(credits_used, 4),
                "ce_calls": 2 if credit_since else 1}

    # ---------- v1.2：存储用量 ----------
    def storage_usage(self):
        vols = self.c("ec2").describe_volumes()["Volumes"]
        return {"volume_gb": sum(v["Size"] for v in vols)}

    def wait_public_ip(self, inst_id, timeout=600):
        end = time.time() + timeout
        while time.time() < end:
            try:
                ip = self._public_ip(inst_id)
                if ip:
                    return ip
            except Exception:
                pass
            time.sleep(10)
        return None

    # ---------- v1.3：流量 ----------
    def traffic(self, inst_id, kind="vm", start=None, end=None):
        """本月流量（GB），CloudWatch 基础监控（5 分钟粒度，免费）。AWS 每月 100GB 出站免费（全服务合计）。
        v1.4：传入 start/end（UTC datetime）时统计该时间窗（滚动窗口模式，按小时聚合）。"""
        now = end or dt.datetime.now(dt.timezone.utc)
        win = start is not None
        start = start or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period = 3600 if win else 86400
        res = {}
        for metric, key in (("NetworkOut", "out_gb"), ("NetworkIn", "in_gb")):
            if kind == "lightsail":
                r = self.c("lightsail").get_instance_metric_data(instanceName=inst_id, metricName=metric, period=period,
                                                                startTime=start, endTime=now, unit="Bytes", statistics=["Sum"])
                pts = [p["sum"] for p in r["metricData"]]
            else:
                r = self.c("cloudwatch").get_metric_statistics(Namespace="AWS/EC2", MetricName=metric, StartTime=start, EndTime=now,
                                                               Dimensions=[{"Name": "InstanceId", "Value": inst_id}],
                                                               Period=period, Statistics=["Sum"])
                pts = [p["Sum"] for p in r["Datapoints"]]
            res[key] = round(sum(pts) / 1024 ** 3, 3)
        res["period"] = f"{start:%Y-%m-%d %H:%M} ~ {now:%Y-%m-%d %H:%M} UTC" if win else f"{start:%Y-%m-%d} ~ {now:%Y-%m-%d}"
        return res
