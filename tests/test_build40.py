"""build 40：Android / iOS 补齐 SolusVM / VirtFusion（绿云）管理，与 Web 端对齐，版本 1.6.6 / 40 静态检查。
1. 版本：Android versionCode 40 / versionName 1.6.6，iOS CURRENT_PROJECT_VERSION "40" / MARKETING_VERSION "1.6.6"
2. Android：厂商注册表五家、凭证表单 + 提示、实例页签、操作收敛（isPanel）、流量直显、监控无换 IP、迁移目标排除、字符串中英
3. iOS：厂商注册表五家、凭证表单 + 提示、实例页签、操作收敛（isPanel）、流量直显、品牌色与无 Logo 兜底
4. 后端：account-type 对面板型厂商不再误标「AWS 账号」
5. 发布说明（release-notes.md 同步 1.6.6 / 40）与 CHANGELOG / FEATURES 同步 1.6.6
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

# 1. Android versionCode >= 40 且双端一致；versionName >= '1.6.6' 且双端一致（build 41 起按惯例放宽）
bg = rd("android", "app", "build.gradle")
py = rd("ios", "project.yml")
_vc_and = int(re.search(r"versionCode (\d+)", bg).group(1))
_vc_ios = re.search(r'CURRENT_PROJECT_VERSION: "(\d+)"', py).group(1)
_vn_and = re.search(r"versionName '([^']+)'", bg).group(1)
_vn_ios = re.search(r'MARKETING_VERSION: "([^"]+)"', py).group(1)
ok("versionCode >= 40 and Android == iOS", _vc_and >= 40 and _vc_and == int(_vc_ios))
ok("versionName >= '1.6.6' and Android == iOS", _vn_and >= "1.6.6" and _vn_and == _vn_ios)

A = ("android", "app", "src", "main", "java", "com", "tricloud", "app")
and_main = rd(*A, "MainActivity.java")
and_accs = rd(*A, "AccountsActivity.java")
and_acc = rd(*A, "AccountActivity.java")
and_base = rd(*A, "BaseActivity.java")
and_zh = rd("android", "app", "src", "main", "res", "values", "strings.xml")
and_en = rd("android", "app", "src", "main", "res", "values-en", "strings.xml")

# 2. Android 绿云接入
ok("android PROVS five providers", '"solusvm", "virtfusion"' in and_main and '"SolusVM", "VirtFusion"' in and_main)
ok("android isPanel + noRegion covers panel", "isPanel" in and_main and "noRegion" in and_main)
ok("android cred fields solusvm/virtfusion", 'm.put("solusvm"' in and_accs and 'm.put("virtfusion"' in and_accs
   and "lx_panel_url" in and_accs and "lx_api_token" in and_accs)
ok("android hints solusvm/virtfusion", "lx_hint_solusvm" in and_accs and "lx_hint_virtfusion" in and_accs)
ok("android PSHORT + batch select five", '"SolusVM", "VirtFusion"}' in and_accs and '"solusvm", "virtfusion"' in and_accs)
ok("android tabs panel only instances", 'case "solusvm": case "virtfusion"' in and_acc)
ok("android instCard panel branch + traffic line", "isPanel(prov)" in and_acc and "/traffic?instance_id=" in and_acc)
ok("android monitor hides change-ip for panel", "isPanel(prov)" in and_acc and "auto_change_ip" in and_acc)
ok("android migrate excludes panel targets", "isPanel(a.optJSONObject(i)" in and_acc)
ok("android provHeader logo guard", "PROV_LOGOS.length" in and_base)
ok("android strings zh panel keys", all(k in and_zh for k in ("lx_panel_url", "lx_api_key", "lx_api_hash", "lx_api_token", "lx_hint_solusvm", "lx_hint_virtfusion")))
ok("android strings en panel keys", all(k in and_en for k in ("lx_panel_url", "lx_api_key", "lx_api_hash", "lx_api_token", "lx_hint_solusvm", "lx_hint_virtfusion")))

I = ("ios", "TriCloud")
ios_main = rd(*I, "MainPage.swift")
ios_add = rd(*I, "AddAccount.swift")
ios_acc = rd(*I, "AccountPage.swift")
ios_mig = rd(*I, "AccountPage+Migrate.swift")
ios_shell = rd(*I, "Shell.swift")

# 3. iOS 绿云接入
ok("ios PROVS five providers", '"solusvm", "virtfusion"' in ios_main and '"SolusVM", "VirtFusion"' in ios_main)
ok("ios isPanel + noRegion helpers", "isPanel" in ios_main and "noRegion" in ios_main)
ok("ios CRED_LABEL panel keys", '"panel_url": "面板地址"' in ios_main and '"api_token": "API Token（用户）"' in ios_main)
ok("ios cred fields solusvm/virtfusion", '"solusvm": [CredField' in ios_add and '"virtfusion": [CredField' in ios_add)
ok("ios tabs panel only instances", 'case "solusvm", "virtfusion"' in ios_acc)
ok("ios instCard panel traffic line", "isPanel(prov)" in ios_acc and "/traffic?instance_id=" in ios_acc)
ok("ios moreOps panel restricted", "isPanel(prov)" in ios_acc and "流量守护" in ios_acc)
ok("ios migrate excludes panel targets", "isPanel(a.obj(i)" in ios_mig)
ok("ios guard default limit from total", "panelTotal" in ios_mig)
ok("ios brand colors + empty logo fallback", "#7cb342" in ios_shell and "#26a69a" in ios_shell and 'default: return ""' in ios_shell)

# 4. 后端 account-type
acc_py = rd("app", "routers", "accounts.py")
ok("backend account-type panel label", "面板账号" in acc_py and 'elif acc["provider"] == "aws"' in acc_py)

# 5. 发布物料同步 1.6.6 / build 40
rn = rd(".github", "release-notes.md")
ok("release notes contain 1.6.6 and 40", "1.6.6" in rn and "build 40" in rn)
cl = rd("CHANGELOG.md")
ok("changelog contains 1.6.6 build 40", "1.6.6" in cl and "build 40" in cl)
ft = rd("docs", "FEATURES.md")
ok("features contains 1.6.6 build 40", "1.6.6 build 40" in ft)

print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
