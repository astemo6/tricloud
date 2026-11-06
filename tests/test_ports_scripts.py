"""自测：开放端口「全部协议」+ 开机脚本多选拼接 + Fail2ban 预设。
① open-port 路由接受 protocol=all（全部协议+全部端口，仍走公网二次确认）；
   AWS 写 IpProtocol=-1 不带端口、Azure 写 protocol=*/port=*、OCI 复用 PROTO_NUM 的 all。
② resolve_script 支持 script_ids 多选（按序拼接、后段去 #! 加分隔、自填追加），
   旧 script_id 语义不变（模板优先于自填）。
③ SCRIPT_PRESETS 新增「安装 Fail2ban」，标签与 i18n 齐全。
云调用全部用假客户端。"""
import os
import sys
import tempfile

os.environ.update(TRICLOUD_DATA=tempfile.mkdtemp())
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from fastapi import HTTPException

from app import cloudinit, core
from app.providers.aws_provider import AWSProvider
from app.providers.azure_provider import AzureProvider
from app.routers.common import _public_guard

core.init_db()
R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


# ---------- ① AWS open_ports: all ----------
class FakeEC2:
    def __init__(self, perms=None):
        self.perms, self.authorized = perms or [], []

    def describe_instances(self, InstanceIds):
        return {"Reservations": [{"Instances": [{"SecurityGroups": [{"GroupId": "sg-1"}]}]}]}

    def describe_security_groups(self, GroupIds):
        return {"SecurityGroups": [{"GroupId": "sg-1", "GroupName": "g", "IpPermissions": self.perms}]}

    def authorize_security_group_ingress(self, GroupId, IpPermissions):
        self.authorized.extend(IpPermissions)
        return {}


def aws_with(fake):
    p = AWSProvider.__new__(AWSProvider)
    p.region = "eu-central-1"
    p.c = lambda svc, region=None: fake
    return p


f = FakeEC2()
r = aws_with(f).open_ports("i-1", "all", [(0, 65535)])
ok("aws all: one -1 perm without ports", r["added"] == 1 and f.authorized[0]["IpProtocol"] == "-1" and "FromPort" not in f.authorized[0])

f2 = FakeEC2(perms=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
r2 = aws_with(f2).open_ports("i-1", "all", [(0, 65535)])
ok("aws all: existing -1 rule skipped", r2["skipped"] == 1 and not f2.authorized)

f3 = FakeEC2()
aws_with(f3).open_ports("i-1", "tcp", [(443, 443)])
ok("aws tcp: unchanged FromPort/ToPort perm", f3.authorized[0]["IpProtocol"] == "tcp" and f3.authorized[0]["FromPort"] == 443)

# ---------- ① Azure open_ports: all ----------
class FakeRules:
    def __init__(self):
        self.created = []

    def list(self, rg, name):
        return []

    def begin_create_or_update(self, rg, nsg, name, rule):
        self.created.append((name, rule))

        class Op:
            def result(self):
                return rule
        return Op()


az = AzureProvider.__new__(AzureProvider)
az._vm_nsgs = lambda iid: [("rg1", "nsg1")]
az.network = type("N", (), {"security_rules": FakeRules()})()
r = az.open_ports("vm1", "all", [(0, 65535)])
rule = az.network.security_rules.created[0][1]
ok("azure all: protocol * + port *", r["added"] == 1 and rule.protocol == "*" and rule.destination_port_range == "*")

# ---------- ① guard: all 仍需二次确认 ----------
try:
    _public_guard("ingress", "all", "0.0.0.0/0", "", None)
    ok("guard: all unconfirmed -> 409", False)
except HTTPException as e:
    ok("guard: all unconfirmed -> 409", e.status_code == 409)
_public_guard("ingress", "all", "0.0.0.0/0", "", True)
ok("guard: all confirmed -> passes", True)

router = open(os.path.join(ROOT, "app/routers/instances.py"), encoding="utf-8").read()
ok("router: accepts all + full range", '"tcp", "udp", "all"' in router and '[(0, 65535)] if proto == "all"' in router)

# ---------- ② resolve_script 多选 ----------
core.ex("INSERT INTO scripts(name, content, created) VALUES(?,?,0)", ("模板甲", "#!/bin/bash\necho A"))
core.ex("INSERT INTO scripts(name, content, created) VALUES(?,?,0)", ("模板乙", "#!/bin/bash\necho B"))
rows = core.q("SELECT id, name FROM scripts ORDER BY id")
ida, idb = rows[0]["id"], rows[1]["id"]

out = cloudinit.resolve_script({"script_ids": f"{idb},{ida}"})
ok("multi: order kept + separator + shebang stripped on 2nd",
   out.startswith("#!/bin/bash\necho B") and "# ===== 模板甲 =====" in out and out.count("#!/bin/bash") == 1 and out.rstrip().endswith("echo A"))
out2 = cloudinit.resolve_script({"script_ids": [ida], "script": "echo CUSTOM"})
ok("multi: raw script appended last", out2.startswith("#!/bin/bash\necho A") and "# ===== 自填脚本 =====" in out2 and out2.rstrip().endswith("echo CUSTOM"))
ok("legacy: script_id exact content", cloudinit.resolve_script({"script_id": ida}) == "#!/bin/bash\necho A")
ok("legacy: script_id wins over raw (App semantics)", cloudinit.resolve_script({"script_id": ida, "script": "echo X"}) == "#!/bin/bash\necho A")
ok("raw only + user_data fallback", cloudinit.resolve_script({"script": "echo R"}) == "echo R" and cloudinit.resolve_script({"user_data": "echo U"}) == "echo U")
ok("multi: unknown id ignored", cloudinit.resolve_script({"script_ids": "999"}) is None)

# ---------- 前端静态断言 ----------
inst = open(os.path.join(ROOT, "web/js/instances.js"), encoding="utf-8").read()
ok("web: open-port dialog has all option + port disable wiring", 'value="all"' in inst and "inst.protoAll" in inst and "pIn.disabled" in inst)
ok("web: loginFields multi-pick + hidden script_ids sync", "data-script-pick" in inst and 'name="script_ids"' in inst and "script_ids" in inst)
settings = open(os.path.join(ROOT, "web/js/settings.js"), encoding="utf-8").read()
ok("web: fail2ban preset + label", "安装 Fail2ban" in settings and "set.presetF2b" in settings and "jail.local" in settings)
i18n = open(os.path.join(ROOT, "web/js/i18n.js"), encoding="utf-8").read()
ok("i18n pairs", i18n.count('"inst.protoAll"') == 2 and i18n.count('"inst.allProtoPorts"') == 2 and i18n.count('"set.presetF2b"') == 2)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
