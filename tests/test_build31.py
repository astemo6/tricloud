"""build 31：双端 App 功能补齐（对齐 2026-11-03/04 网页版）。纯静态检查，不连任何真实云。
覆盖：CF 创建/编辑表单新字段（双端口/创建选套餐/IPv6 回源/ws_mode）、分发已用流量、
账单手动刷新次数 + 增加入口、缓存刷新按钮纳入 cf_invalidate_btn 开关、版本号 >= 31（双端一致）。"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
P = F = 0
def ok(name, cond):
    global P, F
    if cond: P += 1
    else: F += 1; print("FAIL", name)
def rd(*p): return open(os.path.join(ROOT, *p), encoding="utf-8").read()

_vc = int(re.search(r"versionCode (\d+)", rd("android", "app", "build.gradle")).group(1))
ok("version >= 31 and Android == iOS", _vc >= 31 and f'CURRENT_PROJECT_VERSION: "{_vc}"' in rd("ios", "project.yml"))

# ---------------- Android ----------------
A = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "AccountActivity.java")
for k in ('Field.num("http_port"', 'Field.num("https_port"', 'Field.select("plan_tier"', 'Field.select("ip_address_type"',
          'Field.check("ws_mode"', '"/cloudfront/plan"', "cfBytes("):
    ok("android cf form: " + k, k in A)
ok("android cf traffic", '"/cloudfront/traffic"' in A and 'optJSONObject("items")' in A and 'optLong("quota_bytes")' in A)
ok("android billing allowance", '"/billing/allowance"' in A and 'optJSONObject("manual_ce")' in A)
ok("android invalidate gated by setting", "cf_invalidate_btn" in A and "if (cfInvBtn) button(row, getString(R.string.s0210)" in A)
ok("android ws edit locked on", 'v.put("ws_mode", true)' in A)
zh = rd("android", "app", "src", "main", "res", "values", "strings.xml")
en = rd("android", "app", "src", "main", "res", "values-en", "strings.xml")
new_keys = [f"s{n}" for n in range(1240, 1256)]
ok("android new strings zh", all(f'name="{k}"' in zh for k in new_keys))
ok("android new strings en", all(f'name="{k}"' in en for k in new_keys))
ok("android strings counts match", zh.count("<string name=") == en.count("<string name="))
for k in new_keys: ok("android uses " + k, "R.string." + k in A)

# ---------------- iOS ----------------
S = rd("ios", "TriCloud", "AccountPage+AWS.swift")
for k in ('Field.num("http_port"', 'Field.num("https_port"', 'Field.select("plan_tier"', 'Field.select("ip_address_type"',
          'Field.check("ws_mode"', "cloudfront/plan", "cfBytes"):
    ok("ios cf form: " + k, k in S)
ok("ios cf traffic", "cloudfront/traffic" in S and 'optJSONObject("items")' in S and 'optLong("quota_bytes")' in S)
ok("ios invalidate gated by setting", "cf_invalidate_btn" in rd("ios", "TriCloud", "AccountPage.swift") and 'if self.cfInvBtn { row.button("缓存刷新")' in S)
ok("ios ws edit locked on", 'vv["ws_mode"] = true' in S)
B = rd("ios", "TriCloud", "AccountPage+Billing.swift")
ok("ios billing allowance", "billing/allowance" in B and 'optJSONObject("manual_ce")' in B)
IE = rd("ios", "TriCloud", "en.lproj", "Localizable.strings")
IZ = rd("ios", "TriCloud", "zh-Hans.lproj", "Localizable.strings")
for lit in ("HTTP 回源端口", "HTTPS 回源端口", "源站 IP 类型", "IPv4（默认）", "双栈", "WebSocket 节点模式",
            "WebSocket 节点模式（已开启，不可关闭）", "增加次数", "增加手动刷新次数", "增加次数（1–20 次调用）"):
    ok("ios lproj: " + lit, f'"{lit}" = ' in IE and f'"{lit}" = ' in IZ)

print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
