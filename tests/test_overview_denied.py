"""AWS 权限被拒（UnauthorizedOperation / AccessDenied）全面失败时，记录 denied 标记，账号列表显示「权限被拒」。
全部用假客户端，不连接任何真实云。"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

from fastapi.testclient import TestClient

from app import core, main, overview, services, tasks, telegram
from app.providers.aws_provider import AWSProvider

R = []
core.init_db()


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


async def noop():
    await asyncio.sleep(3600)


for f in ("task_loop", "monitor_loop", "schedule_loop"):
    setattr(tasks, f, noop)
telegram.poll_loop = noop


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ================= 假 provider =================
# AWS：scan_all_regions 返回 rows；记录调用次数
AWS_ROWS = {}     # acc_id -> rows
AWS_CALLS = []


class FakeAws:
    def __init__(self, acc_id):
        self.acc_id = acc_id

    def scan_all_regions(self, regions=None, keep=()):
        AWS_CALLS.append((self.acc_id, tuple(regions) if regions else None))
        rows = AWS_ROWS.get(self.acc_id, [])
        if regions:
            rows = [r for r in rows if r["region"] in regions] or [{"region": rg, "ec2": 0, "ec2_running": 0, "lightsail": 0, "lightsail_running": 0}
                                                                  for rg in regions]
        return [dict(r) for r in rows]


def row(rg, ec2=0, ec2_run=0, ls=0, ls_run=0, **kw):
    return dict(region=rg, ec2=ec2, ec2_running=ec2_run, lightsail=ls, lightsail_running=ls_run, **kw)


def prov(acc_id, region=None):
    return FakeAws(acc_id)


with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        a1 = c.post("/api/accounts", json={"provider": "aws", "name": "aws-1", "cred": {"access_key": "AKIAFAKE00000001", "secret_key": "x", "region": "us-east-1"}}).json()["id"]
    ok("setup: 1 AWS account", isinstance(a1, int))

    def accs():
        return {a["id"]: a for a in c.get("/api/accounts").json()}

    with mock.patch.object(services, "provider", prov):
        # ---------- ① 3 个区域全带 ec2_error="UnauthorizedOperation" ----------
        overview.clear()
        AWS_ROWS[a1] = [
            row("us-east-1", ec2_error="UnauthorizedOperation"),
            row("us-west-2", ec2_error="UnauthorizedOperation"),
            row("ap-northeast-1", ec2_error="UnauthorizedOperation"),
        ]
        try:
            overview.summary(a1)
            ok("① summary raises RuntimeError", False)
        except RuntimeError as e:
            ok("① summary raises RuntimeError", "所有区域查询失败" in str(e))
        # HINT_KEY 里该账号记录 regions == [] 且 denied is True 且 partial is False
        hint = core.get_setting(overview.HINT_KEY).get(str(a1))
        ok("① hint regions == []", hint and hint.get("regions") == [])
        ok("① hint denied is True", hint and hint.get("denied") is True)
        ok("① hint partial is False", hint and hint.get("partial") is False)
        # hint_fields denied is True
        hf = overview.hint_fields(a1)
        ok("① hint_fields machine_regions_denied is True", hf["machine_regions_denied"] is True)
        # GET /api/accounts 该行 machine_regions_denied is True 且 machine_regions == []
        A = accs()
        ok("① /accounts machine_regions_denied is True", A[a1]["machine_regions_denied"] is True)
        ok("① /accounts machine_regions == []", A[a1]["machine_regions"] == [])
        # GET /api/accounts/{a1}/overview 返回 400
        r = c.get(f"/api/accounts/{a1}/overview")
        ok("① /overview returns 400", r.status_code == 400)

        # ---------- ② 全 ec2_error="AccessDeniedException" ----------
        overview.clear()
        core.set_setting(overview.HINT_KEY, {})  # 清 HINT
        AWS_ROWS[a1] = [
            row("us-east-1", ec2_error="AccessDeniedException"),
            row("us-west-2", ec2_error="AccessDeniedException"),
            row("ap-northeast-1", ec2_error="AccessDeniedException"),
        ]
        try:
            overview.summary(a1)
            ok("② summary raises RuntimeError", False)
        except RuntimeError:
            ok("② summary raises RuntimeError", True)
        hint = core.get_setting(overview.HINT_KEY).get(str(a1))
        ok("② hint denied is True (AccessDenied)", hint and hint.get("denied") is True)
        hf = overview.hint_fields(a1)
        ok("② hint_fields denied is True", hf["machine_regions_denied"] is True)

        # ----------③ 全 ec2_error="RequestTimeout"（非权限类） ----------
        overview.clear()
        core.set_setting(overview.HINT_KEY, {})
        AWS_ROWS[a1] = [
            row("us-east-1", ec2_error="RequestTimeout"),
            row("us-west-2", ec2_error="RequestTimeout"),
        ]
        try:
            overview.summary(a1)
            ok("③ summary raises RuntimeError", False)
        except RuntimeError:
            ok("③ summary raises RuntimeError", True)
        hint = core.get_setting(overview.HINT_KEY).get(str(a1))
        ok("③ HINT_KEY 里没有该账号 denied 记录", not hint or hint.get("denied") is not True)
        hf = overview.hint_fields(a1)
        ok("③ hint_fields denied is False", hf["machine_regions_denied"] is False)

        # ----------④ 一半 UnauthorizedOperation、一半 RequestLimitExceeded（混杂非权限类） ----------
        overview.clear()
        core.set_setting(overview.HINT_KEY, {})
        AWS_ROWS[a1] = [
            row("us-east-1", ec2_error="UnauthorizedOperation"),
            row("us-west-2", ec2_error="RequestLimitExceeded"),
        ]
        try:
            overview.summary(a1)
            ok("④ summary raises RuntimeError", False)
        except RuntimeError:
            ok("④ summary raises RuntimeError", True)
        hint = core.get_setting(overview.HINT_KEY).get(str(a1))
        ok("④ 不写 denied", not hint or hint.get("denied") is not True)
        hf = overview.hint_fields(a1)
        ok("④ hint_fields denied is False", hf["machine_regions_denied"] is False)

        # ----------⑤ 一个区域 UnauthorizedOperation + 一个区域正常零机器：不抛错、total==0，记录正常写入不带 denied ----------
        overview.clear()
        core.set_setting(overview.HINT_KEY, {})
        AWS_ROWS[a1] = [
            row("us-east-1", ec2_error="UnauthorizedOperation"),
            row("ap-northeast-1"),  # 正常零机器
        ]
        data = overview.summary(a1)
        ok("⑤ summary 不抛错", True)
        ok("⑤ total == 0", data.get("total") == 0)
        hint = core.get_setting(overview.HINT_KEY).get(str(a1))
        ok("⑤ 记录被 remember 正常写入且不带 denied", hint and hint.get("denied") is not True)
        hf = overview.hint_fields(a1)
        ok("⑤ hint_fields denied is False", hf["machine_regions_denied"] is False)

        # ----------⑥ 承接①的 denied 状态：先按①再写一次 denied，然后 clear，ROWS 改成 ap-northeast-1 有 1 台 ec2 ----------
        overview.clear()
        core.set_setting(overview.HINT_KEY, {})
        # 先按①写一次 denied
        AWS_ROWS[a1] = [
            row("us-east-1", ec2_error="UnauthorizedOperation"),
            row("us-west-2", ec2_error="UnauthorizedOperation"),
        ]
        try:
            overview.summary(a1)
        except RuntimeError:
            pass
        hint = core.get_setting(overview.HINT_KEY).get(str(a1))
        ok("⑥ 先写 denied 成功", hint and hint.get("denied") is True)
        # 然后概览成功
        overview.clear()
        AWS_ROWS[a1] = [
            row("ap-northeast-1", ec2=1, ec2_run=1),
            row("us-east-1"),
            row("us-west-2"),
        ]
        data = overview.summary(a1)
        ok("⑥ summary 成功 total == 1", data.get("total") == 1)
        hint = core.get_setting(overview.HINT_KEY).get(str(a1))
        ok("⑥ 记录 regions 含 ap-northeast-1", hint and any(r["region"] == "ap-northeast-1" for r in hint.get("regions", [])))
        ok("⑥ 记录里没有 denied（或为假）", hint and hint.get("denied") is not True)
        hf = overview.hint_fields(a1)
        ok("⑥ hint_fields denied is False", hf["machine_regions_denied"] is False)
        A = accs()
        ok("⑥ /accounts machine_regions_denied is False", A[a1]["machine_regions_denied"] is False)

# ================= JS 助手实际输出（含 denied） =================
P = {k: os.path.join(ROOT, v) for k, v in {"core": "web/js/core.js", "i18n": "web/js/i18n.js"}.items()}
S = {k: open(v, encoding="utf-8").read() for k, v in P.items()}

# core.js _t 回退表有 core.acc.denied
ok("core.js _t fallback has core.acc.denied", '"core.acc.denied": "权限被拒"' in S["core"])
# core.js accountRegionText 最前面有 denied 分支
ok("core.js accountRegionText denied branch", 'if (acc.machine_regions_denied) return _t("core.acc.denied");' in S["core"])
# core.js applyOverview 写 acc.machine_regions_denied = false
ok("core.js applyOverview clears denied", "acc.machine_regions_denied = false;" in S["core"])
# i18n.js zh 有 core.acc.denied
ok("i18n zh core.acc.denied", '"core.acc.denied": "权限被拒"' in S["i18n"])
# i18n.js en 有 core.acc.denied
ok("i18n en core.acc.denied", '"core.acc.denied": "Access denied"' in S["i18n"])

node = shutil.which("node")
ok("node available", node)
if node:
    core_js = S["core"]
    esc = re.search(r"^export const esc = [^\n]*\n", core_js, re.M).group(0)
    # 抽取：REGION_CITY..regionOpt（含 _t / regionCity）+ regionsBrief + build25 注释起（machineRegion / accountRegionText / regionOf / applyOverview）
    chunk1 = re.search(r"export const REGION_CITY = .*?export const regionOpt = [^\n]*\n", core_js, re.S).group(0)
    brief_fn = re.search(r"export const regionsBrief = .*?\n\};", core_js, re.S).group(0)
    chunk2 = re.search(r"// build 25：GET /accounts .*?acc\.machine_regions_stale = .*?\n\}", core_js, re.S).group(0)
    js = re.sub(r"^export ", "", "\n".join([esc, chunk1, brief_fn, chunk2]), flags=re.M)
    probe = "const _ls = {}; const localStorage = { getItem: (k) => _ls[k] ?? null, setItem: (k, v) => { _ls[k] = v; } };\n" + js + r"""
const A1 = { id: 1, provider: "aws", region: "us-east-1", machine_regions: [{ region: "ap-northeast-1", count: 1, running: 1 }], machine_regions_denied: true };
const A2 = { id: 2, provider: "aws", region: "us-east-1", machine_regions: [], machine_regions_denied: false };
const A3 = { id: 3, provider: "aws", region: "us-east-1", machine_regions: null, machine_regions_denied: false };
const out = {
  t1: accountRegionText(A1),
  t2: accountRegionText(A2),
  t3: accountRegionText(A3),
};
const B = { id: 4, provider: "aws", region: "us-east-1" };
applyOverview(B, { regions: [{ region: "us-west-2", count: 1, running: 0 }, { region: "ap-northeast-1", count: 2, running: 1 }], errors: [] });
out.ap = B.machine_regions; out.apr = regionOf(B); out.aps = B.machine_regions_stale; out.apd = B.machine_regions_denied;
console.log(JSON.stringify(out));
"""
    out = json.loads(subprocess.run([node, "-e", probe], capture_output=True, text=True, check=True).stdout)
    ok("js denied -> '权限被拒'", out["t1"] == "权限被拒")
    ok("js no machines no denied -> '无机器 · 默认 us-east-1 · 弗吉尼亚北部'", out["t2"] == "无机器 · 默认 us-east-1 · 弗吉尼亚北部")
    ok("js never scanned no denied -> 'us-east-1 · 弗吉尼亚北部（默认区域）'", out["t3"] == "us-east-1 · 弗吉尼亚北部（默认区域）")
    ok("js applyOverview clears denied", out["apd"] is False)

passed = sum(1 for _, x in R if x)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)