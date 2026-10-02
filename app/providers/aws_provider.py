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
    name = "AWS (EC2)"
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
    ]

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

    def create_options(self, creds: dict) -> dict:
        ec2 = _client(creds)
        regions = [r["RegionName"] for r in ec2.describe_regions()["Regions"]]
        keys = [k["KeyName"] for k in ec2.describe_key_pairs()["KeyPairs"]]
        return {
            "regions": sorted(regions),
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
        ec2 = _client(creds)
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
                f"ID: {iid}\n"
                f"公网 IP: {desc.get('PublicIpAddress', '（分配中）')}\n"
                f"登录用户: ubuntu\n"
                f"密钥对: {key_name}")
        if key_material:
            text += f"\n私钥（仅显示一次，请妥善保存）:\n{key_material}"
        return text
