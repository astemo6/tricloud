"""build 32：账号列表副标题新增最高优先级一态「权限被拒」（machine_regions_denied）。纯静态检查。
后端 GET /api/accounts 每行带 machine_regions_denied：机器扫描因实例接口权限被拒全面失败时为 true，
三端副标题在「有机器 / 无机器 / 默认区域」之上先判它，直接显示「权限被拒」（en: Access denied）。"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
P = F = 0
def ok(name, cond):
    global P, F
    if cond: P += 1
    else: F += 1; print("FAIL", name)
def rd(*p): return open(os.path.join(ROOT, *p), encoding="utf-8").read()

_vc = int(re.search(r"versionCode (\d+)", rd("android", "app", "build.gradle")).group(1))
ok("version >= 32 and Android == iOS", _vc >= 32 and f'CURRENT_PROJECT_VERSION: "{_vc}"' in rd("ios", "project.yml"))

A = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "Regions.java")
abody = A.split("accountText", 1)[1]
ok("android denied text", 'optBoolean("machine_regions_denied")' in A and '"权限被拒"' in A and '"Access denied"' in A)
ok("android denied first", abody.index("machine_regions_denied") < abody.index("machineRegions(acc)"))

S = rd("ios", "TriCloud", "Regions.swift")
sbody = S.split("accountText", 1)[1]
ok("ios denied text", 'optBoolean("machine_regions_denied")' in S and '"权限被拒"' in S and '"Access denied"' in S)
ok("ios denied first", sbody.index("machine_regions_denied") < sbody.index("machineRegions(acc)"))

print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
