"""build 39：基于最新仓库重新出包，版本 1.6.5 / 39 静态检查。
1. 版本：Android versionCode 39 / versionName 1.6.5，iOS CURRENT_PROJECT_VERSION "39" / MARKETING_VERSION "1.6.5"
2. 发布说明（release-notes.md 同步 1.6.5 / 39）与 CHANGELOG / FEATURES 同步 1.6.5
注：自 build 38 起 android/ 与 ios/ 原生代码零改动；本次改动在后端/Web（cft 套餐显示、账号编辑 500、SolusVM/VirtFusion 厂商、VNC 移除），App 配合最新面板生效。
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

P = F = 0

def ok(name, cond):
    global P, F
    if cond:
        P += 1
    else:
        F += 1
        print("FAIL:", name)

def rd(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()

# 1. Android versionCode 恰为 39、iOS CURRENT_PROJECT_VERSION 恰为 "39"；Android versionName 恰为 '1.6.5'、iOS MARKETING_VERSION 恰为 "1.6.5"
bg = rd("android", "app", "build.gradle")
py = rd("ios", "project.yml")
_vc_and = int(re.search(r"versionCode (\d+)", bg).group(1))
_vc_ios = re.search(r'CURRENT_PROJECT_VERSION: "(\d+)"', py).group(1)
_vn_and = re.search(r"versionName '([^']+)'", bg).group(1)
_vn_ios = re.search(r'MARKETING_VERSION: "([^"]+)"', py).group(1)
ok("versionCode == 39 and CURRENT_PROJECT_VERSION == '39'", _vc_and == 39 and _vc_ios == "39")
ok("versionName == '1.6.5' and MARKETING_VERSION == '1.6.5'", _vn_and == "1.6.5" and _vn_ios == "1.6.5")

# 2. release-notes.md 含 "1.6.5" 与 "39"；CHANGELOG 与 FEATURES 同步 1.6.5
rn = rd(".github", "release-notes.md")
ok("release notes contain 1.6.5 and 39", "1.6.5" in rn and "39" in rn)
cl = rd("CHANGELOG.md")
ok("changelog contains 1.6.5 build 39", "1.6.5" in cl and "build 39" in cl)
ft = rd("docs", "FEATURES.md")
ok("features contains 1.6.5 build 39", "1.6.5 build 39" in ft)

print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
