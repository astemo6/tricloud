"""build 38：App 功能对齐网页版与版本 1.6.4 / 38 静态检查。
1. 版本：Android versionCode 38 / versionName 1.6.4，iOS CURRENT_PROJECT_VERSION "38" / MARKETING_VERSION "1.6.4"（build 39 起按惯例放宽）
2. 表单多选字段（multiselect）：Android BaseActivity / iOS UIHub
3. 脚本模板多选 script_ids：Android AccountActivity / iOS AccountPage+Create
4. EC2 机型价格标签（ec2TypeField / __custom__ / 系统盘默认 8G）
5. Lightsail 官网逻辑（family + ipv6_only 过滤）
6. 开放端口全协议（icmp / icmpv6 / all）
7. 安全页三件：qr_png 二维码、/sessions 已登录设备、/audit/logins 登录记录；后端 qr_png
8. 脚本预设补「更新环境」「安装 Fail2ban」
9. 发布说明（release-notes.md 同步 1.6.4 / 38）
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

# 1. Android versionCode >= 38 且 iOS CURRENT_PROJECT_VERSION 一致；versionName >= '1.6.4' 且双端一致（build 39 起按惯例放宽）
bg = rd("android", "app", "build.gradle")
py = rd("ios", "project.yml")
_vc_and = int(re.search(r"versionCode (\d+)", bg).group(1))
_vc_ios = re.search(r'CURRENT_PROJECT_VERSION: "(\d+)"', py).group(1)
_vn_and = re.search(r"versionName '([^']+)'", bg).group(1)
_vn_ios = re.search(r'MARKETING_VERSION: "([^"]+)"', py).group(1)
ok("versionCode >= 38 and Android == iOS", _vc_and >= 38 and _vc_and == int(_vc_ios))
ok("versionName >= '1.6.4' and Android == iOS", _vn_and >= "1.6.4" and _vn_and == _vn_ios)

and_base = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "BaseActivity.java")
and_acc = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "AccountActivity.java")
and_sec = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "SecurityActivity.java")
and_scr = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "ScriptsActivity.java")
ios_hub = rd("ios", "TriCloud", "UIHub.swift")
ios_create = rd("ios", "TriCloud", "AccountPage+Create.swift")
ios_account = rd("ios", "TriCloud", "AccountPage.swift")
ios_global = rd("ios", "TriCloud", "GlobalPages.swift")

# 2. multiselect 字段类型两端都有
ok("multiselect field wired",
   "multiselect" in and_base and "multiselect" in ios_hub and "multis" in ios_hub)

# 3. 脚本多选走 script_ids，且旧 script_id 单选已从创建表单消失
ok("script_ids multiselect wired",
   "script_ids" in and_acc and "script_ids" in ios_create
   and 'Field.select("script_id"' not in and_acc and 'Field.select("script_id"' not in ios_create)

# 4. EC2 价格标签 + 自定义机型 + 磁盘默认 8G
ok("ec2 priced type picker wired",
   "ec2TypeField" in and_acc and "ec2TypeField" in ios_create
   and "__custom__" in and_acc and "__custom__" in ios_create
   and '"disk_gb", "8"' in and_acc and '"disk_gb", "8"' in ios_create)

# 5. Lightsail 先套餐类型 + 网络再过滤规格
ok("lightsail family/ip filter wired",
   '"family"' in and_acc and "ipv6_only" in and_acc
   and '"family"' in ios_create and "ipv6_only" in ios_create)

# 6. 开放端口协议含 icmp/icmpv6/all
ok("open-port all protocols wired",
   '"icmp", "icmpv6", "all"' in and_acc and '"icmp", "icmpv6", "all"' in ios_account)

# 7. 安全页三件 + 后端 qr_png
backend_sec = rd("app", "routers", "security.py")
ok("security parity wired",
   "qr_png" in backend_sec
   and "qr_png" in and_sec and "qr_png" in ios_global
   and "/sessions" in and_sec and "/sessions" in ios_global
   and "/audit/logins" in and_sec and "/audit/logins" in ios_global)

# 8. 脚本预设补两条（内容与 Web SCRIPT_PRESETS 同源）
ok("script presets extended",
   "force-confold" in and_scr and "fail2ban" in and_scr
   and "force-confold" in ios_global and "fail2ban" in ios_global)

# 9. release-notes.md 含 "1.6.4" 与 "38"
rn = rd(".github", "release-notes.md")
ok("release notes contain 1.6.4 and 38", "1.6.4" in rn and "38" in rn)

print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
