"""build 42：修 Android 抽屉分组折叠「时好时坏」，版本 1.6.8 / 42 静态检查。
根因：NavigationView（material 1.12.0 NavigationMenuPresenter）的条目点击处理先 setUpdateSuspended(true)
再分发 performItemAction，build 41 在分发内同步 buildNav() 重建菜单，presenter 的 prepareMenuItems()
遇 updateSuspended 直接 return，界面不刷新，要等下一次无关重建（点别的条目 / 重开抽屉）才显形。
修法：onNav 处理 grp_ 时把 buildNav 推迟到点击分发结束后（nav.post）。
1. 版本：Android versionCode 42 / versionName 1.6.8，iOS CURRENT_PROJECT_VERSION "42" / MARKETING_VERSION "1.6.8"
2. Android：onNav 的 grp_ 分支用 nav.post 推迟重建；折叠其余实现（grp_ 键 / toggleNavGroup / SharedPreferences）仍在
3. 发布说明（release-notes.md 同步 1.6.8 / 42）与 CHANGELOG / FEATURES 同步 1.6.8
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

# 1. 版本恰为 42 / 1.6.8 且双端一致
bg = rd("android", "app", "build.gradle")
py = rd("ios", "project.yml")
_vc_and = int(re.search(r"versionCode (\d+)", bg).group(1))
_vc_ios = re.search(r'CURRENT_PROJECT_VERSION: "(\d+)"', py).group(1)
_vn_and = re.search(r"versionName '([^']+)'", bg).group(1)
_vn_ios = re.search(r'MARKETING_VERSION: "([^"]+)"', py).group(1)
ok("versionCode == 42 and CURRENT_PROJECT_VERSION == '42'", _vc_and == 42 and _vc_ios == "42")
ok("versionName == '1.6.8' and MARKETING_VERSION == '1.6.8'", _vn_and == "1.6.8" and _vn_ios == "1.6.8")

# 2. Android 折叠重建推迟 + 其余实现仍在
A = ("android", "app", "src", "main", "java", "com", "tricloud", "app")
base = rd(*A, "BaseActivity.java")
ok("grp_ toggle defers rebuild via nav.post", "nav.post(() -> buildNav())" in base)
ok("grp_ branch no longer rebuilds synchronously", 'toggleNavGroup(k.substring(4)); buildNav()' not in base)
ok("collapse helpers still present", "navCollapsed()" in base and "toggleNavGroup" in base and '"grp_" +' in base)

# 3. 发布物料同步 1.6.8 / build 42
rn = rd(".github", "release-notes.md")
ok("release notes contain 1.6.8 and 42", "1.6.8" in rn and "build 42" in rn)
cl = rd("CHANGELOG.md")
ok("changelog contains 1.6.8 build 42", "1.6.8" in cl and "build 42" in cl)
ft = rd("docs", "FEATURES.md")
ok("features contains 1.6.8 build 42", "1.6.8 build 42" in ft)

print(f"build42: {P} passed, {F} failed")
sys.exit(1 if F else 0)
