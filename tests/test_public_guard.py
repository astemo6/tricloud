"""自测：_public_guard 公网放行护栏（app/routers/common.py）。
2026-11-06 变更：原先「全部端口 + 公网来源」是硬拦截 400（err.all_ports_public，用户称不记得有此规则），
改为与普通公网放行一致的二次确认——未确认 409、确认后放行；非公网来源与出站不受影响。
不连接任何真实云。"""
import os
import sys
import tempfile

os.environ.update(TRICLOUD_DATA=tempfile.mkdtemp())
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from fastapi import HTTPException

from app.routers.common import _public_guard

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def outcome(*a):
    try:
        _public_guard(*a)
        return None
    except HTTPException as e:
        return e.status_code


ok("all + 0.0.0.0/0 unconfirmed -> 409 (was 400 hard block)", outcome("ingress", "all", "0.0.0.0/0", "1-65535", None) == 409)
ok("all + 0.0.0.0/0 confirmed -> allowed", outcome("ingress", "all", "0.0.0.0/0", "1-65535", True) is None)
ok("all + ::/0 confirmed -> allowed", outcome("ingress", "all", "::/0", "1-65535", True) is None)
ok("tcp full range + public unconfirmed -> 409", outcome("ingress", "tcp", "0.0.0.0/0", "1-65535", None) == 409)
ok("tcp full range + public confirmed -> allowed", outcome("ingress", "tcp", "0.0.0.0/0", "1-65535", True) is None)
ok("tcp single port + public unconfirmed -> 409", outcome("ingress", "tcp", "0.0.0.0/0", "443-443", None) == 409)
ok("tcp single port + public confirmed -> allowed", outcome("ingress", "tcp", "0.0.0.0/0", "443-443", True) is None)
ok("icmp + public unconfirmed -> 409", outcome("ingress", "icmp", "0.0.0.0/0", "0-0", None) == 409)
ok("private cidr -> always allowed", outcome("ingress", "all", "1.2.3.4/32", "1-65535", None) is None)
ok("egress -> always allowed", outcome("egress", "all", "0.0.0.0/0", "1-65535", None) is None)
ok("bad port spec -> 400", outcome("ingress", "tcp", "0.0.0.0/0", "abc", True) == 400)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
