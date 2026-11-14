"""build 44：Android 抽屉折叠卡顿——buildNav 批量重建（暂停菜单变更分发），版本 1.6.10 / 44。"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = F = 0
def ok(n, c):
    global P, F
    if c: P += 1
    else: F += 1; print("FAIL:", n)
rd = lambda *p: open(os.path.join(ROOT, *p), encoding="utf-8").read()
bg, py = rd("android", "app", "build.gradle"), rd("ios", "project.yml")
import re as _re
_vc = int(_re.search(r"versionCode (\d+)", bg).group(1)); _vn = _re.search(r"versionName '([\d.]+)'", bg).group(1)
ok("versions >= 44 / 1.6.10 and in sync", _vc >= 44 and tuple(map(int, _vn.split("."))) >= (1, 6, 10) and f'CURRENT_PROJECT_VERSION: "{_vc}"' in py and f'MARKETING_VERSION: "{_vn}"' in py)
b = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "BaseActivity.java")
# build 45 起 NavigationView 换成自绘 RecyclerView + DiffUtil，批量重建由差异派发取代
_new = "DiffUtil.calculateDiff" in b
ok("batch rebuild", _new or ("stopDispatchingItemsChanged()" in b and "startDispatchingItemsChanged()" in b and "buildNavItems(m)" in b))
ok("start in finally", _new or "finally { if (mb != null) mb.startDispatchingItemsChanged(); }" in b)
ok("deferred rebuild kept", _new or "nav.post(() -> buildNav())" in b)
for f, k in ((".github/release-notes.md", "1.6.10 build 44"), ("CHANGELOG.md", "1.6.10（build 44）"), ("docs/FEATURES.md", "1.6.10 build 44")):
    ok(f, k in rd(*f.split("/")))
print(f"build44: {P} passed, {F} failed")
sys.exit(1 if F else 0)
