"""自测：面板型云（VirtFusion / SolusVM）实例列表隐藏 API 不提供的「内网 IP」「地域」。
- VirtFusion：_map 默认 private_ip=None；network.secondary 有 IPv4 时取第一个作为 private_ip（兼容 list/dict）。
- SolusVM：新增 location 字段（面板没给时为空串），region 保持原值（向后兼容 App）。
- Web：core.js 新增 NO_PRIVATE_IP / NO_ZONE；instTable / instCard 按值隐藏列/项（jsdom 实际渲染，没有 node/jsdom 时跳过渲染部分）。
全部离线，不连接任何真实面板。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from app.providers import solusvm_provider  # noqa: E402
from app.providers.virtfusion_provider import VirtFusionProvider  # noqa: E402

R = []


def ok(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if not cond and extra else ""))


SRV = {"id": "6b32bae9-83e9-44f9-afd4-244f1fa27a49", "name": "VM", "memory": "1024 MB", "cpu": "1 Core",
       "storage": [{"capacity": "10 GB", "enabled": True}],
       "network": {"primary": {"ipv4": [{"address": "203.0.113.20"}], "ipv6": []}, "secondary": []}}

m = VirtFusionProvider._map(SRV)
ok("vf: secondary empty → private_ip None", m["private_ip"] is None, m)
ok("vf: keys unchanged (backward compatible)", {"id", "name", "state", "public_ip", "private_ip", "ipv6", "shape", "region", "zone", "created"} <= set(m) and m["region"] == "-" and m["zone"] == "-")
m = VirtFusionProvider._map(dict(SRV, network={"primary": SRV["network"]["primary"],
                                               "secondary": [{"ipv4": [{"address": "10.0.0.5"}, {"address": "10.0.0.6"}]}]}))
ok("vf: secondary list ipv4 → first as private_ip", m["private_ip"] == "10.0.0.5" and m["public_ip"] == "203.0.113.20", m)
m = VirtFusionProvider._map(dict(SRV, network={"primary": SRV["network"]["primary"], "secondary": {"ipv4": [{"address": "10.1.0.9"}]}}))
ok("vf: secondary dict ipv4 → private_ip", m["private_ip"] == "10.1.0.9", m)
m = VirtFusionProvider._map(dict(SRV, network={"primary": SRV["network"]["primary"], "secondary": [{"ipv4": []}, "junk", None]}))
ok("vf: secondary without ipv4 → None", m["private_ip"] is None, m)
m = VirtFusionProvider._map(dict(SRV, network=None))
ok("vf: network None tolerated", m["private_ip"] is None and m["public_ip"] is None, m)


class _P(solusvm_provider.SolusVMProvider):
    def __init__(self, info):
        self.panel, self._i = "https://cp.example.com", info

    def _info(self):
        return self._i


base = {"hostname": "h", "ipaddr": "203.0.113.10", "statusmsg": "online", "status": "success"}
lst = _P(dict(base, location="Tokyo, Japan")).list_instances()
ok("sv: location kept + region unchanged", lst[0]["location"] == "Tokyo, Japan" and lst[0]["region"] == "Tokyo, Japan" and lst[0]["private_ip"] is None, lst)
lst = _P(dict(base)).list_instances()
ok("sv: no location → '' (region still panel host)", lst[0]["location"] == "" and lst[0]["region"] == "cp.example.com", lst)

js = {f: open(os.path.join(ROOT, "web/js", f), encoding="utf-8").read() for f in ("core.js", "instances.js")}
ok("core exports NO_PRIVATE_IP / NO_ZONE", 'export const NO_PRIVATE_IP = new Set(["solusvm", "virtfusion"])' in js["core.js"]
   and 'export const NO_ZONE = new Set(["solusvm", "virtfusion"])' in js["core.js"])
ok("instances imports the flags", "NO_PRIVATE_IP, NO_ZONE" in js["instances.js"])

# ---- 真实渲染（jsdom）----
JD = os.environ.get("TC_JSDOM_DIR") or "/workspace/projects/eaddfdd1-95d5-4717-aeac-26c5e0655a1d/work/jd"
if shutil.which("node") and os.path.isdir(os.path.join(JD, "node_modules", "jsdom")):
    script = r'''
import { createRequire } from "module";
const require = createRequire(process.argv[3] + "/package.json");
const { JSDOM } = require("jsdom");
const dom = new JSDOM("<!doctype html><body></body>", { url: "http://x/" });
for (const k of ["window", "document", "localStorage", "navigator", "HTMLElement", "location"]) Object.defineProperty(globalThis, k, { value: dom.window[k], configurable: true, writable: true });
localStorage.setItem("tc_lang", "zh");
const m = await import(process.argv[2] + "/web/js/instances.js");
const vf = { provider: "virtfusion", id: 1 }, sv = { provider: "solusvm", id: 2 }, oci = { provider: "oci", id: 3 }, aws = { provider: "aws", id: 4 };
const I = (o) => Object.assign({ id: "a", name: "n", state: "running", public_ip: "203.0.113.5", private_ip: null, ipv6: [], shape: "x", region: "-", zone: "-", created: "" }, o);
console.log(JSON.stringify({
  vfT: m.instTable(vf, [I({})], "vm"), vfC: m.instCard(vf, I({}), "vm"),
  vfPrivT: m.instTable(vf, [I({}), I({ id: "b", private_ip: "10.0.0.5" })], "vm"), vfPrivC: m.instCard(vf, I({ private_ip: "10.0.0.5" }), "vm"),
  svT: m.instTable(sv, [I({ region: "cp.example.com", location: "" })], "vm"), svC: m.instCard(sv, I({ region: "cp.example.com", location: "" }), "vm"),
  svLocT: m.instTable(sv, [I({ location: "Tokyo, Japan" })], "vm"), svLocC: m.instCard(sv, I({ location: "Tokyo, Japan" }), "vm"),
  ociT: m.instTable(oci, [I({ zone: "ap-tokyo-1" })], "vm"), ociC: m.instCard(oci, I({ zone: "ap-tokyo-1" }), "vm"),
  awsT: m.instTable(aws, [I({ private_ip: "172.31.0.4", zone: "ap-northeast-1a" })], "vm"),
}));
'''
    d = tempfile.mkdtemp()
    p = os.path.join(d, "r.mjs")
    open(p, "w").write(script)
    r = subprocess.run(["node", p, os.path.abspath(ROOT), JD], capture_output=True, text=True, timeout=60)
    try:
        o = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        o = None
    ok("jsdom render ran", o is not None, r.stderr[-500:])
    if o:
        hdr = lambda h: h.split("</tr>")[0]  # noqa: E731
        ok("vf table: no 内网 IP / 地域 header", "内网 IP" not in hdr(o["vfT"]) and "地域" not in hdr(o["vfT"]) and o["vfT"].count("<th>") == 6)
        ok("vf table: row cells match header", o["vfT"].count("<td") == 6)
        ok("vf card: no 内网 / 可用区 / 地域", "内网" not in o["vfC"] and "可用区" not in o["vfC"] and "地域" not in o["vfC"])
        ok("vf table: real private ip shows column for all rows", "内网 IP" in hdr(o["vfPrivT"]) and "10.0.0.5" in o["vfPrivT"] and o["vfPrivT"].count("<td") == 14, o["vfPrivT"].count("<td"))
        ok("vf card: real private ip shown", "内网" in o["vfPrivC"] and "10.0.0.5" in o["vfPrivC"])
        ok("sv: empty location → no 地域, no panel host", "地域" not in o["svT"] and "cp.example.com" not in o["svT"] and "地域" not in o["svC"] and "内网" not in o["svT"] + o["svC"])
        ok("sv: location → 地域 column + card item", "地域" in hdr(o["svLocT"]) and "Tokyo, Japan" in o["svLocT"] and "地域" in o["svLocC"] and "Tokyo, Japan" in o["svLocC"] and "内网" not in o["svLocT"])
        ok("oci unchanged: 内网 IP + 地域 columns, card 内网 + 可用区", "内网 IP" in hdr(o["ociT"]) and "地域" in hdr(o["ociT"]) and o["ociT"].count("<th>") == 8 and "内网" in o["ociC"] and "可用区" in o["ociC"])
        ok("aws unchanged", "172.31.0.4" in o["awsT"] and o["awsT"].count("<th>") == 8)
    shutil.rmtree(d, ignore_errors=True)
else:
    print("SKIP jsdom render (node/jsdom not found)")

bad = [n for n, v in R if not v]
print(f"{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
