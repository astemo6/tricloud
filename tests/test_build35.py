"""build 35：CloudFront 分发卡片备注/ID 互换。纯静态检查。
Android / iOS 在 CloudFront 分发卡片标题优先显示备注（空回退 ID），
原备注行改为显示 ID（仅备注非空时显示）。与网页版一致。"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
P = F = 0
def ok(name, cond):
    global P, F
    if cond: P += 1
    else: F += 1; print("FAIL", name)
def rd(*p): return open(os.path.join(ROOT, *p), encoding="utf-8").read()

# 1. version 35
bg = rd("android", "app", "build.gradle")
py = rd("ios", "project.yml")
ok("version 35", "versionCode 35" in bg and 'CURRENT_PROJECT_VERSION: "35"' in py)

# 2. Android CF 段
A = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "AccountActivity.java")
cf_idx = A.index('"/cloudfront"') if '"/cloudfront"' in A else A.index("/cloudfront")
cf_inv_idx = A.index("private void cfInvalidate")
seg_a = A[cf_idx:cf_inv_idx]
ok("android cf comment/id swap",
   'optString("comment")' in seg_a and
   'cmt.isEmpty() ? did : cmt' in seg_a and
   '(cmt.isEmpty() ? "" : "\\n" + did)' in seg_a and
   '"\\n" + d.optString("comment")' not in seg_a)

# 3. iOS CF 段
S = rd("ios", "TriCloud", "AccountPage+AWS.swift")
s_cf_idx = S.index('"/cloudfront"') if '"/cloudfront"' in S else S.index("/cloudfront")
s_cf_inv_idx = S.index("func cfInvalidate")
seg_s = S[s_cf_idx:s_cf_inv_idx]
ok("ios cf comment/id swap",
   'optString("comment")' in seg_s and
   'cmt.isEmpty ? did : cmt' in seg_s and
   '(cmt.isEmpty ? "" : "\\n" + did)' in seg_s and
   '"\\n" + d.optString("comment")' not in seg_s)

print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
