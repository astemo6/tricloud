"""AWS provider：EC2 实例管理（boto3）。"""
import logging
import time

import boto3
from botocore.exceptions import ClientError

from .base import AccountField, InstanceInfo, Provider

log = logging.getLogger(__name__)

_STATE_MAP = {
    "pending": "pending",
    "running": "running",
    "shutting-down": "stopping",
    "terminated": "terminated",
    "stopping": "stopping",
    "stopped": "stopped",
}

INSTANCE_TYPES = [
    "t2.micro", "t2.small", "t3.micro", "t3.small", "t3.medium",
    "t3a.micro", "t3a.small", "c5.large", "c6g.medium", "m5.large",
]


def _client(creds: dict, service="ec2"):
    return boto3.client(
        service,
        aws_access_key_id=creds["access_key"].strip(),
        aws_secret_access_key=creds["secret_key"].strip(),
        region_name=creds["region"].strip(),
    )


def _name_of(tags) -> str:
    for t in tags or []:
        if t.get("Key") == "Name":
            return t.get("Value", "")
    return ""


class AwsProvider(Provider):
    id = "aws"
    name = "AWS"
    supports_billing = True
    supports_lightsail = True
    supports_cloudfront = True
    fields = [
        AccountField("access_key", "Access Key ID"),
        AccountField("secret_key", "Secret Access Key", field_type="password"),
        AccountField("region", "默认区域", placeholder="如 ap-northeast-1",
                     help="如 ap-northeast-1（东京）/ us-east-1（弗吉尼亚）"),
    ]
    actions = [
        {"key": "start", "label": "启动"},
        {"key": "stop", "label": "停止"},
        {"key": "reboot", "label": "重启"},
        {"key": "terminate", "label": "终止", "danger": True},
        {"key": "change_ip", "label": "更换公网 IP"},
        {"key": "rename", "label": "改名"},
        {"key": "extend_disk", "label": "磁盘扩容"},
        {"key": "open_port", "label": "开放端口"},
    ]
    supports_quotas = True

    def test(self, creds: dict) -> None:
        _client(creds).describe_instances(MaxResults=5)

    def list_instances(self, creds: dict) -> list[InstanceInfo]:
        ec2 = _client(creds)
        region = creds["region"].strip()
        result = []
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate():
            for r in page["Reservations"]:
                for i in r["Instances"]:
                    state = i["State"]["Name"]
                    if state == "terminated":
                        continue
                    ipv6 = ""
                    for ni in i.get("NetworkInterfaces", []):
                        for v6 in ni.get("Ipv6Addresses", []):
                            ipv6 = v6.get("Ipv6Address", "")
                    result.append(InstanceInfo(
                        id=i["InstanceId"],
                        name=_name_of(i.get("Tags")) or i["InstanceId"],
                        status=_STATE_MAP.get(state, "unknown"),
                        status_text=state,
                        shape=i.get("InstanceType", ""),
                        public_ip=i.get("PublicIpAddress", "") or "",
                        private_ip=i.get("PrivateIpAddress", "") or "",
                        ipv6=ipv6,
                        region=region,
                        zone=i.get("Placement", {}).get("AvailabilityZone", ""),
                        created=i["LaunchTime"].isoformat() if i.get("LaunchTime") else "",
                    ))
        return result

    def instance_action(self, creds: dict, inst: InstanceInfo, action: str, ctx) -> str:
        ec2 = _client(creds)
        iid = inst.id
        if action == "start":
            ec2.start_instances(InstanceIds=[iid])
            ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
            return "实例已启动"
        if action == "stop":
            ec2.stop_instances(InstanceIds=[iid])
            ec2.get_waiter("instance_stopped").wait(InstanceIds=[iid])
            return "实例已停止"
        if action == "reboot":
            ec2.reboot_instances(InstanceIds=[iid])
            return "重启请求已提交"
        if action == "terminate":
            ec2.terminate_instances(InstanceIds=[iid])
            return "实例终止请求已提交"
        if action == "change_ip":
            return self._change_ip(ec2, iid, ctx)
        if action == "rename":
            new_name = (getattr(ctx, "params", {}) or {}).get("new_name", "").strip()
            if not new_name:
                raise ValueError("请提供新名称")
            ec2.create_tags(Resources=[iid], Tags=[{"Key": "Name", "Value": new_name}])
            return f"实例已改名为 {new_name}"
        if action == "extend_disk":
            return self._extend_disk(ec2, iid, ctx)
        if action == "open_port":
            return self._open_port(ec2, iid, ctx)
        raise ValueError(f"未知操作: {action}")

    def _change_ip(self, ec2, iid: str, ctx) -> str:
        desc = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
        private_ip = desc.get("PrivateIpAddress")
        addrs = ec2.describe_addresses(
            Filters=[{"Name": "private-ip-address", "Values": [private_ip]}]
        )["Addresses"] if private_ip else []
        eip = next((a for a in addrs if a.get("InstanceId") == iid), None)
        if eip:
            ctx.log(f"解绑并释放弹性 IP {eip['PublicIp']}…")
            ec2.disassociate_address(AssociationId=eip["AssociationId"])
            ec2.release_address(AllocationId=eip["AllocationId"])
            new = ec2.allocate_address(Domain="vpc")
            ec2.associate_address(InstanceId=iid, AllocationId=new["AllocationId"])
            return f"已更换弹性 IP，新 IP: {new['PublicIp']}"
        # 无弹性 IP：停机再开机换临时公网 IP
        ctx.log("实例使用临时公网 IP，将通过停止→启动来更换（约需 1-2 分钟）…")
        ec2.stop_instances(InstanceIds=[iid])
        ec2.get_waiter("instance_stopped").wait(InstanceIds=[iid])
        ec2.start_instances(InstanceIds=[iid])
        ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
        time.sleep(5)
        desc = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
        return f"已通过重启更换公网 IP，新 IP: {desc.get('PublicIpAddress', '未知')}"

    def get_billing(self, creds: dict) -> dict:
        """AWS 账单：Cost Explorer 按服务汇总当月费用。
        需要 IAM 权限 ce:GetCostAndUsage；数据约有 24 小时延迟。
        Cost Explorer 是全局服务，走 us-east-1 endpoint。
        """
        import datetime
        ce = boto3.client(
            "ce",
            aws_access_key_id=creds["access_key"].strip(),
            aws_secret_access_key=creds["secret_key"].strip(),
            region_name="us-east-1",
        )
        today = datetime.date.today()
        start = today.replace(day=1).isoformat()
        try:
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start, "End": today.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if "AccessDenied" in code or "Unauthorized" in code:
                raise ValueError(
                    "无 Cost Explorer 权限：请给 IAM 用户添加 ce:GetCostAndUsage 权限") from e
            raise
        groups = (resp.get("ResultsByTime") or [{}])[0].get("Groups", [])
        services = []
        total = 0.0
        for g in groups:
            amount = float(g["Metrics"]["UnblendedCost"]["Amount"])
            total += amount
            services.append({"name": g["Keys"][0], "cost": round(amount, 4)})
        services.sort(key=lambda x: -x["cost"])
        # 本月已用 credit（RECORD_TYPE=Credit，金额为负数，取绝对值）
        credit_used = 0.0
        try:
            cr = ce.get_cost_and_usage(
                TimePeriod={"Start": start, "End": today.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit"]}},
            )
            for r in cr.get("ResultsByTime", []):
                credit_used += float(r.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))
        except ClientError:  # noqa: BLE001
            pass
        credit_used = abs(round(credit_used, 4))
        # Credit 明细（billing:GetCredits，需要额外 IAM 权限；无权限时跳过不阻断账单）
        credits = []
        credit_remaining = 0.0
        credit_initial = 0.0
        try:
            ak = creds["access_key"].strip()
            sk = creds["secret_key"].strip()
            sts = boto3.client("sts", aws_access_key_id=ak,
                               aws_secret_access_key=sk, region_name="us-east-1")
            account_id = sts.get_caller_identity()["Account"]
            billing = boto3.client("billing", aws_access_key_id=ak,
                                   aws_secret_access_key=sk, region_name="us-east-1")
            start_dt = datetime.datetime.now() - datetime.timedelta(days=365)
            kwargs: dict = {"accountId": account_id, "startDate": start_dt}
            while True:
                cr_resp = billing.get_credits(**kwargs)
                for c in cr_resp.get("CreditDataList", []):
                    init = float(c["initialAmount"]["CurrencyAmount"])
                    rem = float(c["remainingAmount"]["CurrencyAmount"])
                    end = c.get("endDate")
                    credits.append({
                        "id": c.get("creditId", ""),
                        "name": c.get("description", "") or c.get("creditId", ""),
                        "initial": round(init, 2),
                        "remaining": round(rem, 2),
                        "used": round(init - rem, 2),
                        "expires": end.strftime("%Y-%m-%d") if hasattr(end, "strftime") else str(end or ""),
                        "status": c.get("creditStatus", ""),
                    })
                    credit_remaining += rem
                    credit_initial += init
                token = cr_resp.get("NextToken")
                if not token:
                    break
                kwargs["NextToken"] = token
        except ClientError:  # noqa: BLE001
            pass
        credits.sort(key=lambda x: x["expires"] or "9999")
        return {
            "currency": "",
            "period": f"{start} ~ {today.isoformat()}",
            "total": round(total, 4),
            "credit_used": credit_used,
            "credits": credits,
            "credit_remaining": round(credit_remaining, 2),
            "credit_initial": round(credit_initial, 2),
            "services": services,
            "note": "金额为账户结算币种；Cost Explorer 数据约有 24 小时延迟",
        }

    def get_credit_applied(self, creds: dict, start: str, end: str) -> float:
        """指定周期 [start, end) 内 credit 抵扣总额（正数）。start/end 为 YYYY-MM-DD。"""
        ce = boto3.client(
            "ce",
            aws_access_key_id=creds["access_key"].strip(),
            aws_secret_access_key=creds["secret_key"].strip(),
            region_name="us-east-1",
        )
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit"]}},
        )
        total = 0.0
        for r in resp.get("ResultsByTime", []):
            total += float(r.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))
        return abs(round(total, 4))

    # ---------- Lightsail ----------
    LIGHTSAIL_REGIONS = [
        "us-east-1", "us-east-2", "us-west-2",
        "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1",
        "ap-southeast-1", "ap-southeast-2", "ap-northeast-1", "ap-northeast-2",
        "ap-south-1", "ca-central-1",
    ]

    def _ls_client(self, creds: dict, region: str):
        return boto3.client(
            "lightsail",
            aws_access_key_id=creds["access_key"].strip(),
            aws_secret_access_key=creds["secret_key"].strip(),
            region_name=region,
        )

    def list_lightsail(self, creds: dict, region: str = "") -> list[dict]:
        """列出 Lightsail 实例。region 为空时并行扫所有 Lightsail 区域。"""
        from concurrent.futures import ThreadPoolExecutor
        regions = [region.strip()] if region and region.strip() else self.LIGHTSAIL_REGIONS

        def _one(rg: str) -> list[dict]:
            try:
                ls = self._ls_client(creds, rg)
                out = []
                for inst in ls.get_instances().get("instances", []):
                    st = (inst.get("state") or {}).get("name", "")
                    out.append({
                        "name": inst.get("name", ""),
                        "state": st,
                        "blueprint": (inst.get("blueprintName") or ""),
                        "bundle": (inst.get("bundleId") or ""),
                        "public_ip": inst.get("publicIpAddress") or "",
                        "private_ip": inst.get("privateIpAddress") or "",
                        "ipv6": ", ".join(inst.get("ipv6Addresses") or []),
                        "region": rg,
                        "zone": (inst.get("location") or {}).get("availabilityZone", ""),
                        "created": str(inst.get("createdAt") or ""),
                    })
                return out
            except ClientError as e:
                log.warning("lightsail %s failed: %s", rg, e)
                return []

        result: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(len(regions), 8)) as pool:
            for part in pool.map(_one, regions):
                result.extend(part)
        return result

    def lightsail_action(self, creds: dict, name: str, action: str, region: str) -> str:
        ls = self._ls_client(creds, region.strip())
        if action == "start":
            ls.start_instance(instanceName=name)
            return f"Lightsail 实例 {name} 已启动"
        if action == "stop":
            ls.stop_instance(instanceName=name)
            return f"Lightsail 实例 {name} 已停止"
        if action == "reboot":
            ls.reboot_instance(instanceName=name)
            return f"Lightsail 实例 {name} 重启请求已提交"
        raise ValueError(f"未知操作: {action}")

    def lightsail_change_ip(self, creds: dict, name: str, region: str, ctx) -> str:
        """更换 Lightsail 实例公网 IP（后台任务）。
        绑定了静态 IP：分配新静态 IP 并绑定，释放旧的；动态 IP：停止后启动。"""
        import time as _time
        ls = self._ls_client(creds, region.strip())

        def _pub_ip() -> str:
            inst = ls.get_instance(instanceName=name)["instance"]
            return inst.get("publicIpAddress") or ""

        old_ip = _pub_ip()
        # 查是否有绑定的静态 IP
        attached = ""
        try:
            for sip in ls.get_static_ips().get("staticIps", []):
                if sip.get("attachedTo") == name:
                    attached = sip.get("name", "")
                    break
        except Exception:  # noqa: BLE001
            attached = ""
        if attached:
            ctx.log(f"实例绑定了静态 IP {attached}（{old_ip}），分配新静态 IP…")
            new_sip = f"{name}-sip-{int(_time.time()) % 1000000}"[:60]
            ls.allocate_static_ip(staticIpName=new_sip)
            ls.attach_static_ip(staticIpName=new_sip, instanceName=name)
            new_ip = ls.get_static_ip(staticIpName=new_sip)["staticIp"]["ipAddress"]
            try:
                ls.release_static_ip(staticIpName=attached)
                ctx.log(f"已释放旧静态 IP {attached}")
            except Exception as e:  # noqa: BLE001
                ctx.log(f"释放旧静态 IP 失败（请手动释放 {attached}，否则会产生费用）：{e}")
            return f"Lightsail 实例 {name} 已更换静态 IP：{old_ip} → {new_ip}"
        # 动态 IP：停止→启动
        ctx.log(f"实例使用动态 IP（当前 {old_ip}），停止实例…")
        ls.stop_instance(instanceName=name)
        for _ in range(30):
            st = (ls.get_instance(instanceName=name)["instance"].get("state") or {}).get("name", "")
            if st == "stopped":
                break
            _time.sleep(10)
        else:
            raise TimeoutError("等待实例停止超时")
        ctx.log("实例已停止，重新启动…")
        ls.start_instance(instanceName=name)
        for _ in range(30):
            inst = ls.get_instance(instanceName=name)["instance"]
            st = (inst.get("state") or {}).get("name", "")
            if st == "running":
                break
            _time.sleep(10)
        else:
            raise TimeoutError("等待实例启动超时")
        new_ip = _pub_ip()
        return f"Lightsail 实例 {name} 已更换 IP：{old_ip} → {new_ip}"

    def get_lightsail_options(self, creds: dict, region: str) -> dict:
        """Lightsail 创建选项：指定区域的可用区、系统镜像、套餐。"""
        region = (region or "").strip()
        if not region:
            raise ValueError("请选择区域")
        ls = self._ls_client(creds, region)
        blueprints = []
        for b in ls.get_blueprints().get("blueprints", []):
            if not b.get("isActive"):
                continue
            blueprints.append({
                "id": b["blueprintId"],
                "name": f"{b.get('name', b['blueprintId'])}",
                "platform": b.get("platform", ""),
            })
        bundles = []
        for b in ls.get_bundles().get("bundles", []):
            if not b.get("isActive"):
                continue
            bundles.append({
                "id": b["bundleId"],
                "name": (f"{b.get('name', b['bundleId'])} · "
                         f"${b.get('price', '?')}/月 · "
                         f"{b.get('ramSizeInGb', '?')}G 内存"),
                "price": float(b.get("price", 9999)),
            })
        bundles.sort(key=lambda x: x["price"])
        zones = []
        for r in ls.get_regions().get("regions", []):
            if r.get("name") == region:
                zones = [z["zoneName"] for z in r.get("availabilityZones", [])]
        return {
            "regions": self.LIGHTSAIL_REGIONS,
            "default_region": region,
            "zones": zones,
            "blueprints": blueprints,
            "bundles": bundles,
        }

    def create_lightsail_instance(self, creds: dict, params: dict, ctx) -> str:
        region = (params.get("region") or "").strip() or creds["region"].strip()
        ls = self._ls_client(creds, region)
        name = (params.get("name") or "").strip() or f"tricloud-{int(time.time()) % 100000}"
        zone = (params.get("zone") or "").strip()
        blueprint = (params.get("blueprint") or "").strip()
        bundle = (params.get("bundle") or "").strip()
        if not zone:
            raise ValueError("请选择可用区")
        if not blueprint:
            raise ValueError("请选择系统镜像")
        if not bundle:
            raise ValueError("请选择套餐")
        kwargs: dict = {
            "instanceNames": [name],
            "availabilityZone": zone,
            "blueprintId": blueprint,
            "bundleId": bundle,
        }
        key_pair = (params.get("key_pair") or "").strip()
        if key_pair:
            kwargs["keyPairName"] = key_pair
        ctx.log(f"在 {region} / {zone} 创建 Lightsail 实例 {name}…")
        ls.create_instances(**kwargs)
        return (f"Lightsail 实例创建已提交: {name}\n"
                f"区域: {region} / {zone}\n"
                f"镜像: {blueprint}\n"
                f"套餐: {bundle}\n"
                f"（实例启动约需几分钟，之后在列表中查看 IP）")

    # ---------- CloudFront ----------
    def _cf_client(self, creds: dict):
        return boto3.client(
            "cloudfront",
            aws_access_key_id=creds["access_key"].strip(),
            aws_secret_access_key=creds["secret_key"].strip(),
            region_name="us-east-1",  # CloudFront 是全局服务
        )

    def list_cloudfront(self, creds: dict) -> list[dict]:
        cf = self._cf_client(creds)
        result = []
        paginator = cf.get_paginator("list_distributions")
        for page in paginator.paginate():
            for d in (page.get("DistributionList") or {}).get("Items", []):
                aliases = (d.get("Aliases") or {}).get("Items", [])
                origins = []
                for o in (d.get("Origins") or {}).get("Items", []):
                    origins.append(o.get("DomainName", ""))
                result.append({
                    "id": d.get("Id", ""),
                    "domain": d.get("DomainName", ""),
                    "status": d.get("Status", ""),
                    "enabled": bool(d.get("Enabled")),
                    "comment": d.get("Comment", ""),
                    "aliases": aliases,
                    "origins": origins,
                    "price_class": (d.get("PriceClass") or "").replace("PriceClass_", ""),
                })
        return result

    def cloudfront_invalidate(self, creds: dict, dist_id: str, paths: list[str]) -> str:
        cf = self._cf_client(creds)
        clean = [p if p.startswith("/") else "/" + p for p in paths if p.strip()]
        if not clean:
            clean = ["/*"]
        resp = cf.create_invalidation(
            DistributionId=dist_id,
            InvalidationBatch={
                "Paths": {"Quantity": len(clean), "Items": clean},
                "CallerReference": f"tricloud-{int(time.time())}",
            },
        )
        inv = resp.get("Invalidation", {})
        return (f"缓存刷新已提交: {dist_id}\n"
                f"ID: {inv.get('Id', '')}\n"
                f"路径: {', '.join(clean)}\n"
                f"状态: {inv.get('Status', '')}")

    def cloudfront_toggle(self, creds: dict, dist_id: str, enabled: bool) -> str:
        cf = self._cf_client(creds)
        cfg_resp = cf.get_distribution_config(Id=dist_id)
        etag = cfg_resp["ETag"]
        cfg = cfg_resp["DistributionConfig"]
        cfg["Enabled"] = enabled
        cf.update_distribution(DistributionConfig=cfg, Id=dist_id, IfMatch=etag)
        return f"分发 {dist_id} 已{'启用' if enabled else '停用'}（配置部署中，约需几分钟生效）"

    def get_distribution_config(self, creds: dict, dist_id: str) -> dict:
        """取分发的可编辑配置摘要。"""
        cf = self._cf_client(creds)
        cfg = cf.get_distribution_config(Id=dist_id)["DistributionConfig"]
        origins = (cfg.get("Origins") or {}).get("Items", [])
        return {
            "comment": cfg.get("Comment", ""),
            "origin_domain": origins[0].get("DomainName", "") if origins else "",
            "price_class": (cfg.get("PriceClass") or "").replace("PriceClass_", ""),
            "default_root_object": cfg.get("DefaultRootObject", ""),
            "enabled": bool(cfg.get("Enabled")),
        }

    def update_distribution(self, creds: dict, dist_id: str, params: dict) -> str:
        """更新分发配置：备注/源站域名/价格等级/默认根对象。"""
        cf = self._cf_client(creds)
        cfg_resp = cf.get_distribution_config(Id=dist_id)
        etag = cfg_resp["ETag"]
        cfg = cfg_resp["DistributionConfig"]
        changed = []
        if "comment" in params:
            cfg["Comment"] = params["comment"] or ""
            changed.append("备注")
        if "origin_domain" in params and params["origin_domain"]:
            origins = (cfg.get("Origins") or {}).get("Items", [])
            if not origins:
                raise ValueError("该分发没有源站，无法修改")
            old = origins[0].get("DomainName", "")
            origins[0]["DomainName"] = params["origin_domain"].strip()
            # 源站 ID 默认就是域名，同步更新避免不一致
            if origins[0].get("Id") == old:
                origins[0]["Id"] = params["origin_domain"].strip()
            changed.append(f"源站 {old} → {params['origin_domain'].strip()}")
        if "price_class" in params and params["price_class"]:
            pc = params["price_class"].strip()
            if pc not in ("100", "200", "All"):
                raise ValueError("价格等级只能是 100/200/All")
            cfg["PriceClass"] = f"PriceClass_{pc}"
            changed.append(f"价格等级 {pc}")
        if "default_root_object" in params:
            cfg["DefaultRootObject"] = (params["default_root_object"] or "").strip()
            changed.append("默认根对象")
        if not changed:
            raise ValueError("没有要修改的字段")
        try:
            cf.update_distribution(DistributionConfig=cfg, Id=dist_id, IfMatch=etag)
        except cf.exceptions.InvalidIfMatchVersion:
            raise ValueError("配置已被他人修改，请刷新后重试") from None
        return f"分发 {dist_id} 已更新（{ '、'.join(changed)}），配置部署中约需几分钟生效"

    # AWS 托管的缓存优化策略（CachingOptimized），免得手写 ForwardedValues
    _CF_CACHE_POLICY_OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    def create_distribution(self, creds: dict, origin_domain: str,
                            comment: str = "", price_class: str = "100") -> str:
        """简化创建 CloudFront 分发：给个源站域名，其他用默认配置。

        默认：回源 http-only、访客侧 http 跳 https、CachingOptimized 缓存策略、
        价格等级 100（仅北美+欧洲，最便宜）。
        """
        cf = self._cf_client(creds)
        origin_domain = (origin_domain or "").strip()
        if not origin_domain:
            raise ValueError("请提供源站域名（如 example.com）")
        price_map = {"100": "PriceClass_100", "200": "PriceClass_200",
                     "all": "PriceClass_All"}
        origin_id = f"tricloud-{origin_domain}"
        resp = cf.create_distribution(DistributionConfig={
            "CallerReference": f"tricloud-{int(time.time())}",
            "Comment": (comment or "").strip() or f"tricloud {origin_domain}",
            "Enabled": True,
            "Origins": {"Quantity": 1, "Items": [{
                "Id": origin_id,
                "DomainName": origin_domain,
                "CustomOriginConfig": {
                    "HTTPPort": 80, "HTTPSPort": 443,
                    "OriginProtocolPolicy": "http-only",
                },
            }]},
            "DefaultCacheBehavior": {
                "TargetOriginId": origin_id,
                "ViewerProtocolPolicy": "redirect-to-https",
                "AllowedMethods": {
                    "Quantity": 2, "Items": ["GET", "HEAD"],
                    "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
                },
                "CachePolicyId": self._CF_CACHE_POLICY_OPTIMIZED,
                "Compress": True,
            },
            "PriceClass": price_map.get(price_class, "PriceClass_100"),
        })
        d = resp["Distribution"]
        return (f"分发创建已提交: {d['Id']}\n"
                f"域名: {d['DomainName']}\n"
                f"状态: {d['Status']}（部署约需 15 分钟，之后生效）")

    def _extend_disk(self, ec2, iid: str, ctx) -> str:
        size = int((getattr(ctx, "params", {}) or {}).get("size_gb") or 0)
        if size <= 0:
            raise ValueError("请提供目标磁盘大小（GB）")
        desc = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
        bdm = (desc.get("BlockDeviceMappings") or [None])[0] or {}
        vol_id = (bdm.get("Ebs") or {}).get("VolumeId")
        if not vol_id:
            raise ValueError("未找到系统盘")
        vol = ec2.describe_volumes(VolumeIds=[vol_id])["Volumes"][0]
        cur = vol["Size"]
        if size <= cur:
            raise ValueError(f"目标大小 {size}GB 必须大于当前 {cur}GB（只支持扩容）")
        ctx.log(f"卷 {vol_id} {cur}GB → {size}GB…")
        ec2.modify_volume(VolumeId=vol_id, Size=size)
        return f"磁盘扩容已提交: {cur}GB → {size}GB（系统内需手动扩展分区）"

    def _open_port(self, ec2, iid: str, ctx) -> str:
        port = int((getattr(ctx, "params", {}) or {}).get("port") or 0)
        if not (1 <= port <= 65535):
            raise ValueError("请提供有效端口 1-65535")
        desc = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
        sg_ids = [g["GroupId"] for g in desc.get("SecurityGroups", [])]
        if not sg_ids:
            raise ValueError("实例未关联安全组")
        done = []
        for sg in sg_ids:
            try:
                ec2.authorize_security_group_ingress(
                    GroupId=sg, IpPermissions=[{
                        "IpProtocol": "tcp", "FromPort": port, "ToPort": port,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "tricloud open"}]}])
                done.append(sg)
            except ClientError as e:
                if "InvalidPermission.Duplicate" in str(e):
                    continue
                raise
        if not done:
            return f"端口 {port} 在安全组中已放行，无需重复操作"
        return f"已在安全组放行 TCP 端口 {port}（来源 0.0.0.0/0）: {', '.join(done)}"

    def get_quotas(self, creds: dict) -> dict:
        """配额查询：Service Quotas API 看 EC2 主要配额。"""
        sq = boto3.client(
            "service-quotas",
            aws_access_key_id=creds["access_key"].strip(),
            aws_secret_access_key=creds["secret_key"].strip(),
            region_name=creds["region"].strip(),
        )
        try:
            quotas = sq.list_service_quotas(ServiceCode="ec2")["Quotas"]
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if "AccessDenied" in code:
                raise ValueError(
                    "无 Service Quotas 权限：请给 IAM 用户添加 servicequotas:ListServiceQuotas") from e
            raise
        items = []
        for q in quotas:
            name = q.get("QuotaName", "")
            if "On-Demand" in name and "instances" in name.lower():
                items.append({
                    "name": name,
                    "detail": f"配额 {q.get('Value')} {q.get('Unit', '')}"
                              f"{'（可申请提高）' if q.get('Adjustable') else ''}",
                })
        items.sort(key=lambda x: x["name"])
        return {
            "groups": [{"title": "EC2 按需实例配额", "items": items[:12]}] if items else [],
            "note": "数据来自 Service Quotas；vCPU 配额等可在 AWS 控制台 Service Quotas 页查看",
        }

    def create_options(self, creds: dict) -> dict:
        ec2 = _client(creds)
        regions = [r["RegionName"] for r in ec2.describe_regions()["Regions"]]
        keys = [k["KeyName"] for k in ec2.describe_key_pairs()["KeyPairs"]]
        return {
            "regions": sorted(regions),
            "default_region": creds["region"].strip(),
            "instance_types": INSTANCE_TYPES,
            "key_pairs": keys,
            "ami_note": "留空则自动使用最新的 Ubuntu 22.04 LTS 镜像",
        }

    def _latest_ubuntu_ami(self, ec2) -> str:
        images = ec2.describe_images(
            Owners=["099720109477"],  # Canonical
            Filters=[
                {"Name": "name", "Values": ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]},
                {"Name": "state", "Values": ["available"]},
            ],
        )["Images"]
        if not images:
            raise ValueError("未找到 Ubuntu 22.04 镜像")
        images.sort(key=lambda x: x["CreationDate"], reverse=True)
        return images[0]["ImageId"]

    def _ensure_sg(self, ec2, ctx) -> str:
        vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
        if not vpcs:
            raise ValueError("该区域没有默认 VPC，无法自动创建安全组")
        vpc_id = vpcs[0]["VpcId"]
        sgs = ec2.describe_security_groups(
            Filters=[{"Name": "group-name", "Values": ["tricloud-sg"]},
                     {"Name": "vpc-id", "Values": [vpc_id]}])["SecurityGroups"]
        if sgs:
            return sgs[0]["GroupId"]
        ctx.log("创建安全组 tricloud-sg（放行 SSH 22 端口）…")
        sg = ec2.create_security_group(
            GroupName="tricloud-sg", Description="tricloud auto created",
            VpcId=vpc_id)
        try:
            ec2.authorize_security_group_ingress(
                GroupId=sg["GroupId"],
                IpPermissions=[{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                                "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
        except ClientError as e:
            if "InvalidPermission.Duplicate" not in str(e):
                raise
        return sg["GroupId"]

    def create_instance(self, creds: dict, params: dict, ctx) -> str:
        region = (params.get("region") or "").strip() or creds["region"].strip()
        ec2 = boto3.client(
            "ec2",
            aws_access_key_id=creds["access_key"].strip(),
            aws_secret_access_key=creds["secret_key"].strip(),
            region_name=region,
        )
        ctx.log(f"目标区域: {region}")
        ami = (params.get("ami") or "").strip() or self._latest_ubuntu_ami(ec2)
        ctx.log(f"使用镜像: {ami}")
        itype = params.get("instance_type", "t2.micro")
        name = params.get("name") or f"tricloud-{int(time.time()) % 100000}"
        key_name = (params.get("key_name") or "").strip()
        key_material = ""
        if not key_name:
            key_name = f"tricloud-{int(time.time())}"
            ctx.log(f"创建新密钥对 {key_name}…")
            kp = ec2.create_key_pair(KeyName=key_name)
            key_material = kp["KeyMaterial"]
        sg_id = self._ensure_sg(ec2, ctx)
        ctx.log(f"正在创建实例 {name} ({itype})…")
        resp = ec2.run_instances(
            ImageId=ami, InstanceType=itype, MinCount=1, MaxCount=1,
            KeyName=key_name, SecurityGroupIds=[sg_id],
            TagSpecifications=[{"ResourceType": "instance",
                                "Tags": [{"Key": "Name", "Value": name}]}],
        )
        iid = resp["Instances"][0]["InstanceId"]
        ctx.log(f"实例 {iid} 已提交，等待运行…")
        ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
        time.sleep(5)
        desc = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
        text = (f"实例创建成功: {name}\n"
                f"区域: {region}\n"
                f"ID: {iid}\n"
                f"公网 IP: {desc.get('PublicIpAddress', '（分配中）')}\n"
                f"登录用户: ubuntu\n"
                f"密钥对: {key_name}")
        if key_material:
            text += f"\n私钥（仅显示一次，请妥善保存）:\n{key_material}"
        return text
