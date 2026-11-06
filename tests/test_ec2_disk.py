"""自测：EC2 系统盘默认按最小（aws_provider.ec2_create + 创建/迁移表单默认值）。
用户定：默认 8G（四个预置系统镜像快照底线实测均为 8G）；后端缺省 8 且低于镜像快照
底线时自动抬到底线（防个别区域/架构镜像底线更高时被 AWS 拒），用户填更大值照用。
全部用假客户端，不连接任何真实云。"""
import os
import sys
import tempfile

os.environ.update(TRICLOUD_DATA=tempfile.mkdtemp())
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from app.providers.aws_provider import AWSProvider

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


class FakeEC2:
    def __init__(self, floor=8):
        self.floor, self.kw = floor, None

    def describe_images(self, ImageIds):
        return {"Images": [{"RootDeviceName": "/dev/sda1",
                            "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": self.floor, "SnapshotId": "snap-1"}}]}]}

    def describe_instance_types(self, InstanceTypes):
        return {"InstanceTypes": [{"ProcessorInfo": {"SupportedArchitectures": ["x86_64"]}}]}

    def run_instances(self, **kw):
        self.kw = kw
        return {"Instances": [{"InstanceId": "i-0123", "State": {"Name": "pending"}}]}


def make(floor=8):
    fake = FakeEC2(floor)
    p = AWSProvider.__new__(AWSProvider)
    p.region = "eu-central-1"
    p.c = lambda svc, region=None: fake
    p._ami = lambda os_key, arch: "ami-1"
    p._sg = lambda ports: "sg-1"
    return p, fake


def vol(p, fake, body):
    p.ec2_create(body)
    return fake.kw["BlockDeviceMappings"][0]["Ebs"]["VolumeSize"]


p, f = make(8)
ok("no disk_gb -> 8 (minimum default)", vol(p, f, {"name": "x", "type": "t3.micro", "os": "ubuntu-22.04"}) == 8)
ok("disk 8 with floor 8 -> 8", vol(p, f, {"name": "x", "disk_gb": 8}) == 8)
ok("explicit 20 kept", vol(p, f, {"name": "x", "disk_gb": 20}) == 20)
ok("string '10' from form -> 10", vol(p, f, {"name": "x", "disk_gb": "10"}) == 10)

p2, f2 = make(12)
ok("disk 8 below AMI floor 12 -> clamped to 12", vol(p2, f2, {"name": "x", "disk_gb": 8}) == 12)
ok("no disk_gb with floor 12 -> 12", vol(p2, f2, {"name": "x"}) == 12)

aws_js = open(os.path.join(ROOT, "web/js/aws.js"), encoding="utf-8").read()
ok("web: create dialog default disk 8", "d.disk_gb || 8" in aws_js)
inst_js = open(os.path.join(ROOT, "web/js/instances.js"), encoding="utf-8").read()
ok("web: migrate-to-AWS spec default disk 8", 'name="disk_gb" type="number" min="8" value="8"' in inst_js)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
