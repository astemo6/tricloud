"""build 33：CloudFront 分发卡片流量行新增近 30 天总量（total30d）。纯静态检查。
后端 GET /api/accounts/{id}/cloudfront/traffic 的每个 item 新增 total30d 字段（近 30 天下行+上行总字节），
Android / iOS 在周期已用流量行下方新增一行显示近 30 天总量。"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
P = F = 0
def ok(name, cond):
    global P, F
    if cond: P += 1
    else: F += 1; print("FAIL", name)
def rd(*p): return open(os.path.join(ROOT, *p), encoding="utf-8").read()

# version 33
ok("version 33", "versionCode 33" in rd("android", "app", "build.gradle") and 'CURRENT_PROJECT_VERSION: "33"' in rd("ios", "project.yml"))

# android total30d
A = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "AccountActivity.java")
ok("android total30d", 'has("total30d")' in A and 'optLong("total30d")' in A and 'R.string.s1256' in A and A.index("total30d") > A.index("s1249"))

# android strings
zh = rd("android", "app", "src", "main", "res", "values", "strings.xml")
en = rd("android", "app", "src", "main", "res", "values-en", "strings.xml")
ok("android strings", '<string name="s1256">近30天' in zh and '<string name="s1256">Last 30 days' in en)

# ios total30d
S = rd("ios", "TriCloud", "AccountPage+AWS.swift")
ok("ios total30d", 'has("total30d")' in S and 'optLong("total30d")' in S and '近30天' in S)

# ios Localizable
ien = rd("ios", "TriCloud", "en.lproj", "Localizable.strings")
izh = rd("ios", "TriCloud", "zh-Hans.lproj", "Localizable.strings")
ok("ios Localizable", '"近30天 %@" = "Last 30 days %@"' in ien and '"近30天 %@" = "近30天 %@"' in izh)

print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
