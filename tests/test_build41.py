"""build 41：三端（Web / Android / iOS）侧边栏分组按厂商折叠，版本 1.6.7 / 41 静态检查。
1. 版本：Android versionCode 41 / versionName 1.6.7，iOS CURRENT_PROJECT_VERSION "41" / MARKETING_VERSION "1.6.7"
2. Web：renderSide 分组标题 data-gtoggle、gwrap 包裹、localStorage tc_side_collapsed 持久化、当前组强制展开；style.css 有 .gwrap.off
3. Android：抽屉平铺菜单 + grp_ 标题项 + navCollapsed/toggleNavGroup（SharedPreferences 持久化）、provHeader 带折叠箭头
4. iOS：SidebarRoot @AppStorage collapsedGroups + groupHeader Button + 条件渲染、当前组强制展开
5. 发布说明（release-notes.md 同步 1.6.7 / 41）与 CHANGELOG / FEATURES 同步 1.6.7
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

# 1. 版本恰为 41 / 1.6.7 且双端一致
bg = rd("android", "app", "build.gradle")
py = rd("ios", "project.yml")
_vc_and = int(re.search(r"versionCode (\d+)", bg).group(1))
_vc_ios = re.search(r'CURRENT_PROJECT_VERSION: "(\d+)"', py).group(1)
_vn_and = re.search(r"versionName '([^']+)'", bg).group(1)
_vn_ios = re.search(r'MARKETING_VERSION: "([^"]+)"', py).group(1)
ok("versionCode == 41 and CURRENT_PROJECT_VERSION == '41'", _vc_and == 41 and _vc_ios == "41")
ok("versionName == '1.6.7' and MARKETING_VERSION == '1.6.7'", _vn_and == "1.6.7" and _vn_ios == "1.6.7")

# 2. Web 折叠
router = rd("web", "js", "router.js")
css = rd("web", "style.css")
ok("web grp title has data-gtoggle", 'data-gtoggle="${prov}"' in router and 'data-gtoggle="manage"' in router)
ok("web groups wrapped in gwrap", "gwrap" in router)
ok("web collapsed persisted in localStorage", "tc_side_collapsed" in router and "sideCollapsed" in router and "wireSideCollapse" in router)
ok("web current provider group force-expanded", "p[0] !== prov" in router)
ok("web css hides collapsed wrap", ".gwrap.off" in css and ".grp[data-gtoggle]" in css)

# 3. Android 折叠
A = ("android", "app", "src", "main", "java", "com", "tricloud", "app")
base = rd(*A, "BaseActivity.java")
ok("android collapse state helpers", "navCollapsed()" in base and "toggleNavGroup" in base)
ok("android collapsed persisted in SharedPreferences", 'getSharedPreferences("nav", MODE_PRIVATE)' in base and '"collapsed"' in base)
ok("android group headers are plain items with grp_ keys", '"grp_" +' in base and '"grp_manage"' in base)
ok("android header tap toggles without closing drawer", 'k.startsWith("grp_")' in base)
ok("android provHeader takes collapsed flag and caret", "provHeader(int p, boolean collapsed)" in base and "▸" in base and "▾" in base)
ok("android no submenu left in buildNav", "addSubMenu" not in base)

# 4. iOS 折叠
shell = rd("ios", "TriCloud", "Shell.swift")
ok("ios collapsed persisted via AppStorage", '@AppStorage("collapsedGroups")' in shell)
ok("ios group header is a toggle button", "groupHeader" in shell and "toggleGroup" in shell)
ok("ios rows conditionally rendered", "if !isCol" in shell and 'if !collapsed.contains("manage")' in shell)
ok("ios current account group force-expanded", "inGroup" in shell)

# 5. 发布物料同步 1.6.7 / build 41
rn = rd(".github", "release-notes.md")
ok("release notes contain 1.6.7 and 41", "1.6.7" in rn and "build 41" in rn)
cl = rd("CHANGELOG.md")
ok("changelog contains 1.6.7 build 41", "1.6.7" in cl and "build 41" in cl)
ft = rd("docs", "FEATURES.md")
ok("features contains 1.6.7 build 41", "1.6.7 build 41" in ft)

print(f"build41: {P} passed, {F} failed")
sys.exit(1 if F else 0)
