"""区域城市名：web/js/core.js 的 REGION_CITY / regionCity / regionLabel / regionOpt。
用 node 只执行这段纯函数（不加载整个前端），核对 AWS 官方 34 个商用区域全部覆盖、下拉 value 为纯代码。"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = open(os.path.join(ROOT, "web", "js", "core.js"), encoding="utf-8").read()
R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


# AWS 官方区域列表（docs.aws.amazon.com/global-infrastructure/latest/regions/aws-regions.html，2026-10 共 34 个）
AWS = ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "af-south-1", "ap-east-1", "ap-south-2", "ap-southeast-3", "ap-southeast-5",
       "ap-southeast-4", "ap-south-1", "ap-southeast-6", "ap-northeast-3", "ap-northeast-2", "ap-southeast-1", "ap-southeast-2", "ap-east-2",
       "ap-southeast-7", "ap-northeast-1", "ca-central-1", "ca-west-1", "eu-central-1", "eu-west-1", "eu-west-2", "eu-south-1", "eu-west-3",
       "eu-south-2", "eu-north-1", "eu-central-2", "il-central-1", "mx-central-1", "me-south-1", "me-central-1", "sa-east-1"]
EXPECT = {"ap-east-1": "香港", "ap-east-2": "台北", "ap-northeast-1": "东京", "ap-northeast-2": "首尔", "ap-northeast-3": "大阪",
          "ap-south-1": "孟买", "ap-south-2": "海得拉巴", "ap-southeast-1": "新加坡", "ap-southeast-2": "悉尼", "ap-southeast-3": "雅加达",
          "ap-southeast-4": "墨尔本", "ap-southeast-5": "吉隆坡", "ap-southeast-7": "曼谷", "ca-central-1": "蒙特利尔", "ca-west-1": "卡尔加里",
          "eu-central-1": "法兰克福", "eu-central-2": "苏黎世", "eu-north-1": "斯德哥尔摩", "eu-south-1": "米兰", "eu-south-2": "西班牙",
          "eu-west-1": "爱尔兰", "eu-west-2": "伦敦", "eu-west-3": "巴黎", "il-central-1": "特拉维夫", "me-central-1": "阿联酋",
          "me-south-1": "巴林", "mx-central-1": "墨西哥", "sa-east-1": "圣保罗", "us-east-1": "弗吉尼亚北部", "us-east-2": "俄亥俄",
          "us-west-1": "加州北部", "us-west-2": "俄勒冈", "af-south-1": "开普敦"}

m = re.search(r"export const REGION_CITY = .*?export const regionOpt = [^\n]*\n", SRC, re.S)
ok("core.js: REGION_CITY .. regionOpt block present", m)
node = shutil.which("node")
ok("node available", node)
if m and node:
    js = re.sub(r"^export ", "", m.group(0), flags=re.M)
    esc = re.search(r"^export const esc = [^\n]*\n", SRC, re.M).group(0).replace("export ", "")
    probe = esc + js + r"""
const zones = ["ap-northeast-1a", "AP-TOKYO-1-AD-1", "Uocm:NRT-AD-1", "Abcd:SJC-AD-1", "ap-tokyo-1-ad-2", "-", "", "xx-test-9", "us-west-2-lax-1a"];
console.log(JSON.stringify({ map: REGION_CITY, zones: zones.map((z) => [z, regionCity(z), regionLabel(z)]),
  opt: regionOpt("ap-northeast-1", true), opt2: regionOpt("xx-test-9", false), opt3: regionOpt('a"<b', false), nul: regionLabel(null) }));
"""
    out = json.loads(subprocess.run([node, "-e", probe], capture_output=True, text=True, check=True).stdout)
    mp = out["map"]
    ok("AWS: all 34 official commercial regions mapped", all(r in mp for r in AWS) and len(AWS) == 34)
    bad = {k: (mp.get(k), v) for k, v in EXPECT.items() if mp.get(k) != v}
    ok("AWS: city names as specified", not bad)
    if bad:
        print(bad)
    ok("OCI: tokyo / sanjose / osaka / seoul / chuncheon / ashburn / phoenix", mp.get("ap-tokyo-1") == "东京" and mp.get("us-sanjose-1") == "圣何塞"
       and mp.get("ap-osaka-1") == "大阪" and mp.get("ap-seoul-1") == "首尔" and mp.get("ap-chuncheon-1") == "春川"
       and mp.get("us-ashburn-1") == "阿什本" and mp.get("us-phoenix-1") == "凤凰城")
    ok("OCI: at least 45 commercial regions", sum(1 for k in mp if re.match(r"^[a-z]{2}-[a-z]+-\d$", k) and not re.match(r"^[a-z]{2}-(east|west|north|south|central|northeast|southeast)-\d$", k)) >= 45)
    ok("Azure: japaneast / eastasia / southeastasia / koreacentral", mp.get("japaneast") == "东日本" and mp.get("eastasia") == "香港"
       and mp.get("southeastasia") == "新加坡" and mp.get("koreacentral") == "韩国中部")
    ok("all keys lowercase codes, values non-empty", all(re.match(r"^[a-z0-9-]+$", k) and v for k, v in mp.items()))
    z = {a: (b, c) for a, b, c in out["zones"]}
    ok("zone: AWS AZ ap-northeast-1a -> 东京", z["ap-northeast-1a"] == ("东京", "ap-northeast-1a · 东京"))
    ok("zone: OCI AD by identifier / key", z["AP-TOKYO-1-AD-1"][0] == "东京" and z["Uocm:NRT-AD-1"][0] == "东京"
       and z["Abcd:SJC-AD-1"][0] == "圣何塞" and z["ap-tokyo-1-ad-2"][0] == "东京")
    ok("unknown / empty -> code only", z["xx-test-9"] == ("", "xx-test-9") and z["-"] == ("", "-") and z[""] == ("", "")
       and z["us-west-2-lax-1a"] == ("", "us-west-2-lax-1a") and out["nul"] == "")
    ok("regionOpt: value is pure code, label has city, selected", out["opt"] == '<option value="ap-northeast-1" selected>ap-northeast-1 · 东京</option>')
    ok("regionOpt: unknown region value == text", out["opt2"] == '<option value="xx-test-9">xx-test-9</option>')
    ok("regionOpt: escapes value and text", out["opt3"] == '<option value="a&quot;&lt;b">a&quot;&lt;b</option>')

ok("regionSelect uses regionOpt (option has value attr)", "regionOpt(r, r === cur)" in SRC and "regionOpt(cur, true)" in SRC
   and '${regionOpt(regionOf(acc), true)}</select>' in SRC and "sel.value = cur;" in SRC)
ok("regionSelect: no bare <option> without value left", not re.search(r"<option( selected| \$\{[^}]*\})?>\$\{esc\(r(egionOf\(acc\))?\)\}", SRC))
web = os.path.join(ROOT, "web", "js")
alljs = "".join(open(os.path.join(web, f), encoding="utf-8").read() for f in os.listdir(web) if f.endswith(".js"))
ok("aws.js regions tab uses regionLabel", "<tr><td>${esc(regionLabel(r.region))}</td><td>${r.ec2}" in alljs
   and "<tr><td>${esc(regionLabel(r.region))}</td><td><span class=\"badge" in alljs)
ok("data-go / data-en keep pure code", 'data-go="${esc(r.region)}"' in alljs and 'data-en="${esc(r.region)}"' in alljs)
ok("azure location selects carry value", "locs.map((l) => regionOpt(l, l === last))" in alljs and "regionOpt(r, r === region)" in alljs)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
