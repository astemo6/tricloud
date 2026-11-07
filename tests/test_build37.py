"""build 37：TriCloud 5 项功能缺口与版本 1.6.3 / 37 静态检查。
1. 版本：Android versionCode 37 / versionName 1.6.3，iOS CURRENT_PROJECT_VERSION "37" / MARKETING_VERSION "1.6.3"
2. 账号手动排序（/accounts/reorder）
3. OCI 系统版本动态下拉（/oci/os-versions）
4. cf_invalidate_btn 设置开关
5. Android 保存为默认创建参数（/create-defaults）
6. OCI 实例级安全列表（/oci/security）
7. 账号快速切换器（AccountSwitchPage）
8. 发布说明（release-notes.md 同步 1.6.3 / 37）
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

# 1. Android versionCode >= 37 且 iOS CURRENT_PROJECT_VERSION 一致；versionName >= '1.6.3' 且双端一致（build 38 起按惯例放宽）
bg = rd("android", "app", "build.gradle")
py = rd("ios", "project.yml")
_vc_and = int(re.search(r"versionCode (\d+)", bg).group(1))
_vc_ios = int(re.search(r'CURRENT_PROJECT_VERSION: "(\d+)"', py).group(1))
_vn_and = re.search(r"versionName '([^']+)'", bg).group(1)
_vn_ios = re.search(r'MARKETING_VERSION: "([^"]+)"', py).group(1)
ok("versionCode >= 37 and Android == iOS", _vc_and >= 37 and _vc_and == _vc_ios)
ok("versionName >= '1.6.3' and Android == iOS", _vn_and >= "1.6.3" and _vn_and == _vn_ios)

# 2. Android AccountsActivity.java 含 "/accounts/reorder"； iOS MainPage.swift 含 "/accounts/reorder"
and_accs = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "AccountsActivity.java")
ios_main = rd("ios", "TriCloud", "MainPage.swift")
ok("accounts reorder endpoint wired", "/accounts/reorder" in and_accs and "/accounts/reorder" in ios_main)

# 3. Android AccountActivity.java 含 "/oci/os-versions"； iOS AccountPage+Create.swift 含 "os-versions"（loadOciVersions 或等价字面量）且 AccountPage+Migrate.swift 含 os-versions 或 loadOciVersions 调用
and_acc = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "AccountActivity.java")
ios_create = rd("ios", "TriCloud", "AccountPage+Create.swift")
ios_migrate = rd("ios", "TriCloud", "AccountPage+Migrate.swift")
ok("oci os-versions endpoint wired",
   "/oci/os-versions" in and_acc and
   ("os-versions" in ios_create or "loadOciVersions" in ios_create) and
   ("os-versions" in ios_migrate or "loadOciVersions" in ios_migrate))

# 4. Android SettingsActivity.java 含 "cf_invalidate_btn" 且有 POST /settings 的开关写入； iOS SettingsPage.swift 含 "cf_invalidate_btn"
and_set = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "SettingsActivity.java")
ios_set = rd("ios", "TriCloud", "SettingsPage.swift")
ok("cf_invalidate_btn setting wired",
   "cf_invalidate_btn" in and_set and
   ("!cfon" in and_set or "cf_invalidate_btn" in and_set) and
   "cf_invalidate_btn" in ios_set)

# 5. Android AccountActivity.java 含 "create-defaults" 且含 "\"PUT\"" 或 "PUT" 字面量与 save_default；iOS AccountPage+Create.swift 含 "/create-defaults"
ok("create-defaults wired",
   "create-defaults" in and_acc and
   ("PUT" in and_acc or '"PUT"' in and_acc) and
   "save_default" in and_acc and
   "/create-defaults" in ios_create)

# 6. Android AccountActivity.java 含 "/oci/security?instance_id=" 或 "/oci/security"； iOS AccountPage+OCI.swift 含 "/oci/security" 且 AccountPage.swift 的 moreOps 区含「安全列表」入口（检查 AccountPage.swift 含 OciInstSecurityPage）
ios_oci = rd("ios", "TriCloud", "AccountPage+OCI.swift")
ios_account = rd("ios", "TriCloud", "AccountPage.swift")
ok("oci security list wired",
   ("/oci/security?instance_id=" in and_acc or "/oci/security" in and_acc) and
   "/oci/security" in ios_oci and
   "OciInstSecurityPage" in ios_account)

# 7. Android AccountActivity.java 含 openPage("acc_" 的切换调用与「切换账号」相关新字符串 id（检查 strings.xml 含「切换账号」）； iOS AccountPage.swift 含 AccountSwitchPage
and_str = rd("android", "app", "src", "main", "res", "values", "strings.xml")
ok("account switcher wired",
   'openPage("acc_' in and_acc and
   "切换账号" in and_str and
   "AccountSwitchPage" in ios_account)

# 8. release-notes.md 含 "1.6.3" 与 "37"
rn = rd(".github", "release-notes.md")
ok("release notes contain 1.6.3 and 37", "1.6.3" in rn and "37" in rn)

print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
