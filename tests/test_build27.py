"""build 27：域名前缀绑定 + App 切换语言立即生效（静态检查 + 后端补全）。"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
P = F = 0
def ok(name, cond):
    global P, F
    if cond: P += 1
    else: F += 1; print("FAIL", name)
def rd(*p): return open(os.path.join(ROOT, *p), encoding="utf-8").read()
from app.routers.cloudflare import full_record, _REC_RE
ok("prefix", full_record("orajp02", "example.com") == "orajp02.example.com")
ok("root @", full_record("@", "example.com") == "example.com")
ok("full name kept", full_record("a.b.example.com", "example.com") == "a.b.example.com")
ok("case/trailing dot", full_record(" Node1.EXAMPLE.com. ", "example.com") == "node1.example.com")
ok("lookalike zone appended", full_record("xexample.com", "example.com") == "xexample.com.example.com")
ok("regex rejects spaces", not _REC_RE.match("bad name.example.com") and _REC_RE.match("*.example.com") and _REC_RE.match("_acme.example.com"))
W = rd("web", "js", "settings.js")
ok("web suffix shown + follows zone", 'id="dnsSuffix"' in W and 'sel.onchange' in W and 'placeholder="node1"' in W)
I = rd("web", "js", "i18n.js")
ok("web i18n hint zh/en", I.count('"set.dnsRecordHint"') == 2 and "记录名前缀" in I and "Record prefix" in I)
J = "android/app/src/main/java/com/tricloud/app/"
A = "".join(rd(*(J + f).split("/")) for f in os.listdir(os.path.join(ROOT, J)) if f.endswith(".java"))
ok("android no static Chinese constants", not re.search(r"static[^(\n]*=[^\n]*[\u4e00-\u9fff]", A))
ok("android no stale static arrays", all(k not in A for k in ["CF_TIER_NAMES", "SHAPE_LABELS", "MODE_LABELS", "BK_TITLE", "REGION_SUB_TITLE", "PROV_HINT", "CRED.get"]))
ok("android lang switch rebuilds stack on settings", "startActivities(new Intent[]{home, new Intent(this, SettingsActivity.class)})" in rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "SettingsActivity.java"))
zh = rd("android", "app", "src", "main", "res", "values", "strings.xml"); en = rd("android", "app", "src", "main", "res", "values-en", "strings.xml")
kz = set(re.findall(r'<string name="(lx_\w+)"', zh)); ke = set(re.findall(r'<string name="(lx_\w+)"', en))
ok("android lx_ strings both languages", kz == ke and len(kz) >= 30)
for k in kz: ok("android uses " + k, "R.string." + k in A)
ok("android s0553 prefix", "记录名前缀" in zh and "Record prefix" in en)
S = rd("ios", "TriCloud", "Page.swift")
ok("ios views observe LangTick", S.count("LangTick.shared") >= 9 and "navigationTitle(L(page.title))" in S)
ok("ios setLang bumps", "LangTick.shared.bump()" in rd("ios", "TriCloud", "TriCloudApp.swift"))
ok("ios dns prefix label localized", "记录名前缀" in rd("ios", "TriCloud", "AccountPage+V16.swift") and "Record prefix" in rd("ios", "TriCloud", "en.lproj", "Localizable.strings"))
ok("version 27", "versionCode 27" in rd("android", "app", "build.gradle") and 'CURRENT_PROJECT_VERSION: "27"' in rd("ios", "project.yml"))
ok("docs build 27", "build 27" in rd("CHANGELOG.md") and "build 27" in rd(".github", "release-notes.md") and "build 27" in rd("docs", "FEATURES.md"))
print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
