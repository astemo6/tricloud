"""build 45：Android 抽屉折叠仍卡——NavigationView 换成自绘 RecyclerView（稳定 id + DiffUtil 只插删变化行、setHasFixedSize 不向上触发布局），版本 1.6.11 / 45。"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = F = 0
def ok(n, c):
    global P, F
    if c: P += 1
    else: F += 1; print("FAIL:", n)
rd = lambda *p: open(os.path.join(ROOT, *p), encoding="utf-8").read()
bg, py = rd("android", "app", "build.gradle"), rd("ios", "project.yml")
ok("versions 45 / 1.6.11", "versionCode 45" in bg and "versionName '1.6.11'" in bg and 'CURRENT_PROJECT_VERSION: "45"' in py and 'MARKETING_VERSION: "1.6.11"' in py)
b = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "BaseActivity.java")
ok("no NavigationView", "import com.google.android.material.navigation.NavigationView" not in b and "new NavigationView" not in b)
ok("recycler drawer", "protected androidx.recyclerview.widget.RecyclerView nav;" in b and "nav.setHasFixedSize(true)" in b)
ok("stable ids", "setHasStableIds(true)" in b and "getItemId(int pos)" in b)
ok("diff dispatch", "DiffUtil.calculateDiff" in b and "diff.dispatchUpdatesTo(navAdapter)" in b)
ok("no notifyDataSetChanged", "notifyDataSetChanged()" not in b)
ok("collapse keys kept", '"grp_" + MainActivity.PROVS[p]' in b and '"grp_manage"' in b and "toggleNavGroup(k.substring(4)); buildNav(); return;" in b)
ok("header row + logo kept", "provHeader(p, c)" in b and "R.string.s0817" in b)
ok("logout confirm kept", '"logout".equals(k)' in b and "R.string.s0821" in b)
ok("checked style", "state_selected" in b and "colorSecondaryContainer" in b)
for f, k in ((".github/release-notes.md", "1.6.11 build 45"), ("CHANGELOG.md", "1.6.11（build 45）"), ("docs/FEATURES.md", "1.6.11 build 45")):
    ok(f, k in rd(*f.split("/")))
print(f"build45: {P} passed, {F} failed")
sys.exit(1 if F else 0)
