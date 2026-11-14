"""build 36 内容同 build 35，仅升显示版本至 1.6.2。纯静态检查。"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
P = F = 0
def ok(name, cond):
    global P, F
    if cond: P += 1
    else: F += 1; print("FAIL", name)
def rd(*p): return open(os.path.join(ROOT, *p), encoding="utf-8").read()

# 1. Android versionCode >= 36 且 iOS CURRENT_PROJECT_VERSION 一致
bg = rd("android", "app", "build.gradle")
py = rd("ios", "project.yml")
_vc_and = int(re.search(r"versionCode (\d+)", bg).group(1))
_vc_ios = int(re.search(r'CURRENT_PROJECT_VERSION: "(\d+)"', py).group(1))
ok("versionCode >= 36 and Android == iOS", _vc_and >= 36 and _vc_and == _vc_ios)

# 2. Android versionName 与 iOS MARKETING_VERSION 一致且 >= '1.6.2'（双端显示版本一致）
_vn_and = re.search(r"versionName '([^']+)'", bg).group(1)
_vn_ios = re.search(r'MARKETING_VERSION: "([^"]+)"', py).group(1)
ok("versionName >= '1.6.2' and Android == iOS", tuple(map(int, _vn_and.split("."))) >= (1, 6, 2) and _vn_and == _vn_ios)

# 3. .github/release-notes.md 含 "1.6.2" 与 "36"（发布说明已同步）
rn = rd(".github", "release-notes.md")
ok("release notes contain 1.6.2 and 36", "1.6.2" in rn and "36" in rn)

print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
