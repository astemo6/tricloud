"""自测：Lightsail 防火墙开放/关闭端口的 portInfo 构造（aws_more.ls_open_port / ls_close_port）。
覆盖：icmp 只带 IPv4 CIDR（原 bug：误带 ::/0 被 AWS 拒绝并 500）、icmpv6 只带 IPv6、
tcp 旧行为不变（0.0.0.0/0 自动双栈）、只给 IPv6 时不擅自开放 IPv4、all 强制 0-65535、
AWS ClientError 转 ValueError（面板显示真实原因而非 500）、前端对话框含 icmpv6/all 选项。
全部用假客户端，不连接任何真实云。"""
import os
import sys
import tempfile

os.environ.update(TRICLOUD_DATA=tempfile.mkdtemp())
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from botocore.exceptions import ClientError

from app.providers.aws_provider import AWSProvider

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


class FakeLS:
    def __init__(self):
        self.opened, self.closed, self.err = [], [], None

    def open_instance_public_ports(self, instanceName, portInfo):
        if self.err:
            raise self.err
        self.opened.append(portInfo)
        return {}

    def close_instance_public_ports(self, instanceName, portInfo):
        if self.err:
            raise self.err
        self.closed.append(portInfo)
        return {}


fake = FakeLS()
p = AWSProvider.__new__(AWSProvider)
p.c = lambda name, region=None: fake

# icmp + 默认来源：只带 IPv4，端口 -1/-1，绝不能出现 ipv6Cidrs（原 500 根源）
fake.opened.clear()
p.ls_open_port("tm", "icmp", 0, 0, ["0.0.0.0/0"])
pi = fake.opened[-1]
ok("icmp: ipv4 only, no ipv6Cidrs, ports -1", pi == {"fromPort": -1, "toPort": -1, "protocol": "icmp", "cidrs": ["0.0.0.0/0"]})

# icmp 只给 IPv6 -> 明确报错提示改用 icmpv6
try:
    p.ls_open_port("tm", "icmp", 0, 0, ["::/0"])
    ok("icmp: v6-only source rejected", False)
except RuntimeError as e:
    ok("icmp: v6-only source rejected", "icmpv6" in str(e))

# icmpv6 + 默认 0.0.0.0/0 输入 -> 翻译为 ::/0，只带 ipv6Cidrs
fake.opened.clear()
p.ls_open_port("tm", "icmpv6", 0, 0, ["0.0.0.0/0"])
pi = fake.opened[-1]
ok("icmpv6: ::/0 only, no cidrs", pi == {"fromPort": -1, "toPort": -1, "protocol": "icmpv6", "ipv6Cidrs": ["::/0"]})

# tcp 旧行为：0.0.0.0/0 -> 双栈
fake.opened.clear()
p.ls_open_port("tm", "tcp", 8080, 8080, ["0.0.0.0/0"])
pi = fake.opened[-1]
ok("tcp: legacy dual-stack for 0.0.0.0/0", pi["cidrs"] == ["0.0.0.0/0"] and pi["ipv6Cidrs"] == ["::/0"] and pi["fromPort"] == 8080)

# tcp 只给 IPv6 -> 不擅自开放 IPv4
fake.opened.clear()
p.ls_open_port("tm", "tcp", 443, 443, ["2001:db8::/32"])
pi = fake.opened[-1]
ok("tcp: v6-only source stays v6-only", "cidrs" not in pi and pi["ipv6Cidrs"] == ["2001:db8::/32"])

# tcp 指定 IPv4 -> 不带 IPv6
fake.opened.clear()
p.ls_open_port("tm", "tcp", 22, 22, ["1.2.3.4/32"])
pi = fake.opened[-1]
ok("tcp: single v4 source, no ipv6", pi["cidrs"] == ["1.2.3.4/32"] and "ipv6Cidrs" not in pi)

# all：端口强制 0-65535
fake.opened.clear()
p.ls_open_port("tm", "all", 0, 0, ["1.2.3.4/32"])
pi = fake.opened[-1]
ok("all: ports forced 0-65535", pi["fromPort"] == 0 and pi["toPort"] == 65535 and pi["protocol"] == "all" and pi["cidrs"] == ["1.2.3.4/32"])

# 非法协议
try:
    p.ls_open_port("tm", "gre", 0, 0, [])
    ok("bad protocol rejected", False)
except RuntimeError:
    ok("bad protocol rejected", True)

# AWS 报错 -> ValueError 带原始消息（路由层转 400，不再 500）
fake.err = ClientError({"Error": {"Code": "InvalidInputException", "Message": "ICMP supports only IPv4 CIDRs."}}, "OpenInstancePublicPorts")
try:
    p.ls_open_port("tm", "tcp", 80, 80, ["0.0.0.0/0"])
    ok("aws error -> ValueError with message", False)
except ValueError as e:
    ok("aws error -> ValueError with message", "ICMP supports only IPv4 CIDRs." in str(e))
fake.err = None

# close：icmp 同样归一到 -1/-1（与 open 对称）
fake.closed.clear()
p.ls_close_port("tm", "icmp", 0, 0)
ok("close icmp: ports -1", fake.closed[-1] == {"fromPort": -1, "toPort": -1, "protocol": "icmp"})
fake.closed.clear()
p.ls_close_port("tm", "tcp", 22, 22)
ok("close tcp: passthrough", fake.closed[-1] == {"fromPort": 22, "toPort": 22, "protocol": "tcp"})

# 前端：Lightsail 对话框协议选项含 icmpv6 与 all
web = open(os.path.join(ROOT, "web/js/instances.js"), encoding="utf-8").read()
i = web.find("lsPortsDialog")
seg = web[i:i + 6000]
ok("web: ls dialog offers icmpv6 + all", "<option>icmpv6</option><option>all</option>" in seg)
ok("web: ls dialog all -> 0-65535", 'f.protocol === "all"' in seg and "65535" in seg)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
