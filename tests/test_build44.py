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
ok("versions 44 / 1.6.10", "versionCode 44" in bg and "versionName '1.6.10'" in bg and 'CURRENT_PROJECT_VERSION: "44"' in py and 'MARKETING_VERSION: "1.6.10"' in py)
b = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "BaseActivity.java")
ok("batch rebuild", "stopDispatchingItemsChanged()" in b and "startDispatchingItemsChanged()" in b and "buildNavItems(m)" in b)
ok("start in finally", "finally { if (mb != null) mb.startDispatchingItemsChanged(); }" in b)
ok("deferred rebuild kept", "nav.post(() -> buildNav())" in b)
for f, k in ((".github/release-notes.md", "1.6.10 build 44"), ("CHANGELOG.md", "1.6.10（build 44）"), ("docs/FEATURES.md", "1.6.10 build 44")):
    ok(f, k in rd(*f.split("/")))
print(f"build44: {P} passed, {F} failed")
sys.exit(1 if F else 0)
