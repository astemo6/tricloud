"""build 43：App 跟进绿云 VirtFusion「下次重置」与隐藏内网 IP / 可用区，版本 1.6.9 / 43 静态检查。"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = F = 0

def ok(name, cond):
    global P, F
    if cond: P += 1
    else:
        F += 1; print("FAIL:", name)

def rd(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()

bg = rd("android", "app", "build.gradle"); py = rd("ios", "project.yml")
import re as _re
ok("versions >= 43 and in sync", int(_re.search(r"versionCode (\d+)", bg).group(1)) >= 43 and _re.search(r"versionCode (\d+)", bg).group(1) == _re.search(r'CURRENT_PROJECT_VERSION: "(\d+)"', py).group(1))

A = ("android", "app", "src", "main", "java", "com", "tricloud", "app")
base, acc, trf = rd(*A, "BaseActivity.java"), rd(*A, "AccountActivity.java"), rd(*A, "TrafficActivity.java")
ok("android resetLine helper", "public String resetLine(JSONObject d, String prefix)" in base and "R.string.vf_reset" in base)
ok("android reset in card / dialog / guard list", "resetLine(td" in acc and "resetLine(t," in base and "resetLine(g" in trf)
ok("android panel card hides private ip / zone", "R.string.vf_inst_info" in acc and "R.string.vf_priv" in acc and "R.string.vf_loc" in acc)
for lang in ("values", "values-en"):
    s = rd("android", "app", "src", "main", "res", lang, "strings.xml")
    ok(f"{lang} strings", all(f'name="{k}"' in s for k in ("vf_reset", "vf_reset_today", "vf_inst_info", "vf_priv", "vf_loc")))

I = ("ios", "TriCloud")
ok("ios trafResetLine", "func trafResetLine(_ d: JObj, _ prefix: String) -> String" in rd(*I, "TrafficPage.swift"))
ok("ios reset in card / form / guard list", "trafResetLine(td" in rd(*I, "AccountPage.swift") and "trafResetLine(t," in rd(*I, "AccountPage+Migrate.swift") and "trafResetLine(g" in rd(*I, "TrafficPage.swift"))
ok("ios panel card hides private ip / zone", '"\\n地域："' in rd(*I, "AccountPage.swift") and 'pip.isEmpty' in rd(*I, "AccountPage.swift"))

ok("release notes 1.6.9 build 43", "1.6.9 build 43" in rd(".github", "release-notes.md"))
ok("changelog 1.6.9 build 43", "1.6.9（build 43）" in rd("CHANGELOG.md"))
ok("features 1.6.9 build 43", "1.6.9 build 43" in rd("docs", "FEATURES.md"))

print(f"build43: {P} passed, {F} failed")
sys.exit(1 if F else 0)
