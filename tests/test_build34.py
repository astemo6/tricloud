"""build 34：CloudFront 分发卡片加「复制域名」按钮。纯静态检查。
Android / iOS 在 CloudFront 分发卡片按钮行首位新增「复制」按钮，点击只复制分发域名（dom），
按钮文案短暂切换为「已复制」（约 1.2 秒）后恢复。复用既有词条与剪贴板惯例，未新增资源。"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
P = F = 0
def ok(name, cond):
    global P, F
    if cond: P += 1
    else: F += 1; print("FAIL", name)
def rd(*p): return open(os.path.join(ROOT, *p), encoding="utf-8").read()

# 1. version 34
bg = rd("android", "app", "build.gradle")
py = rd("ios", "project.yml")
ok("version 34", "versionCode 34" in bg and 'CURRENT_PROJECT_VERSION: "34"' in py)

# 2. Android 复制接线
A = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "AccountActivity.java")
cf_idx = A.index('"/cloudfront"') if '"/cloudfront"' in A else A.index("/cloudfront")
cf_inv_idx = A.index("private void cfInvalidate")
seg_a = A[cf_idx:cf_inv_idx]
ok("android copy wiring",
   'optString("domain")' in seg_a and
   'ClipboardManager' in seg_a and
   'ClipData.newPlainText' in seg_a and
   'R.string.s0500' in seg_a and
   'R.string.s0098' in seg_a and
   'postDelayed' in seg_a)

# 3. Android strings 复用
zh = rd("android", "app", "src", "main", "res", "values", "strings.xml")
en = rd("android", "app", "src", "main", "res", "values-en", "strings.xml")
ok("android strings reuse",
   '<string name="s0500">复制</string>' in zh and
   '<string name="s0098">已复制</string>' in zh and
   '<string name="s0500">Copy</string>' in en and
   '<string name="s0098">Copied</string>' in en)

# 4. iOS 复制接线
S = rd("ios", "TriCloud", "AccountPage+AWS.swift")
s_cf_idx = S.index('"/cloudfront"') if '"/cloudfront"' in S else S.index("/cloudfront")
s_cf_inv_idx = S.index("func cfInvalidate")
seg_s = S[s_cf_idx:s_cf_inv_idx]
ok("ios copy wiring",
   'copyText(' in seg_s and
   '"复制"' in seg_s and
   '"已复制"' in seg_s and
   'later(1.2' in seg_s and
   'optString("domain")' in seg_s)

# 5. iOS Localizable 复用
ien = rd("ios", "TriCloud", "en.lproj", "Localizable.strings")
izh = rd("ios", "TriCloud", "zh-Hans.lproj", "Localizable.strings")
ok("ios Localizable reuse",
   '"复制" = "Copy";' in ien and
   '"已复制" = "Copied";' in ien and
   '"复制" = "复制";' in izh and
   '"已复制" = "已复制";' in izh)

print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
