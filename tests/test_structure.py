"""结构整理自测：路由按模块拆分后的注册情况、云 SDK 按需导入、客户端复用、任务类型注册表、前端 ES 模块与版本号。
不连接任何真实云。"""
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import threading

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123",
                  AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

from fastapi.testclient import TestClient

from app import main, services, tasks, telegram

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


async def noop():
    await asyncio.sleep(3600)


for f in ("task_loop", "monitor_loop", "schedule_loop"):
    setattr(tasks, f, noop)
telegram.poll_loop = noop

# ================= 1. 路由拆分 =================
api = [r for r in main.app.routes if getattr(r, "path", "").startswith("/api/")]
ok("routers: 155 API routes + / + /login registered once each",
   len(api) == 155 and len({(r.path, tuple(sorted(r.methods))) for r in api}) == 155
   and sum(1 for r in main.app.routes if getattr(r, "path", "") in ("/", "/login")) == 2)
ok("routers: every route comes from app.routers.*",
   all(r.endpoint.__module__.startswith("app.routers.") for r in main.app.routes if hasattr(r, "endpoint")))
ok("routers: /static mount registered last", type(main.app.routes[-1]).__name__ == "Mount" and main.app.routes[-1].path == "/static")
src = open(os.path.join(ROOT, "app", "main.py"), encoding="utf-8").read()
ok("main.py only wires the app (no route handlers)", "@app.get" not in src and "@app.post" not in src and len(src.splitlines()) < 120)
ok("old modules removed (extras.py / routes_v16.py)",
   not os.path.exists(os.path.join(ROOT, "app", "extras.py")) and not os.path.exists(os.path.join(ROOT, "app", "routes_v16.py")))

# ================= 2. 云 SDK 按需导入 =================
code = ("import os,sys,tempfile;os.environ['TRICLOUD_DATA']=tempfile.mkdtemp();sys.path.insert(0,%r);import app.main;"
        "print(sorted({m.split('.')[0] for m in sys.modules if m.split('.')[0] in ('boto3','botocore','oci','azure')}));"
        "from app import services;print(list(services.PROVIDERS));services.PROVIDERS['aws'];"
        "print(sorted({m.split('.')[0] for m in sys.modules if m.split('.')[0] in ('boto3','botocore','oci','azure')}))") % ROOT
out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120).stdout.splitlines()
ok("lazy: importing app.main loads no cloud SDK", out[:1] == ["[]"])
ok("lazy: PROVIDERS keys / order unchanged without importing", out[1:2] == ["['oci', 'aws', 'azure']"])
ok("lazy: first use of AWS imports only boto3/botocore", out[2:3] == ["['boto3', 'botocore']"])
ok("lazy: services.OCIProvider still resolvable", services.OCIProvider.__name__ == "OCIProvider"
   and services.PROVIDERS["azure"].__name__ == "AzureProvider")

# ================= 3. 客户端复用 =================
from app.providers.aws_provider import AWSProvider
p = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})
ok("aws client cached per (service, region)", p.c("ec2") is p.c("ec2") and p.c("ec2") is p.c("ec2", "us-east-1")
   and p.c("ec2", "ap-northeast-1") is not p.c("ec2") and p.c("sts") is not p.c("ec2"))
got = []
q = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "eu-west-1"})
ths = [threading.Thread(target=lambda: got.append(q.c("lightsail"))) for _ in range(8)]
[t.start() for t in ths]
[t.join() for t in ths]
ok("aws client cache is thread-safe (one client for concurrent callers)", len({id(x) for x in got}) == 1)
ok("aws proxy config kept on cached client",
   AWSProvider({"access_key": "a", "secret_key": "b", "region": "us-east-1", "proxy": "http://127.0.0.1:3128"}).c("sts").meta.config.proxies
   == {"http": "http://127.0.0.1:3128", "https": "http://127.0.0.1:3128"})

from app.providers.oci_provider import OCIProvider
made = []


class _FakeCls:
    def __init__(self, cfg):
        made.append(cfg["region"])
        self.base_client = mock.Mock()


o = OCIProvider.__new__(OCIProvider)
o.cfg, o.proxy = {"region": "ap-tokyo-1"}, None
a1 = o._c(_FakeCls)
ok("oci client cached per (class, region)", a1 is o._c(_FakeCls) and o._c(_FakeCls, dict(o.cfg, region="us-ashburn-1")) is not a1
   and made == ["ap-tokyo-1", "us-ashburn-1"])

from app.providers.azure_provider import AzureProvider
z = AzureProvider.__new__(AzureProvider)
n = []
ok("azure on-demand clients cached", z._cached("x", lambda: n.append(1) or object()) is z._cached("x", lambda: n.append(1) or object()) and n == [1])

# ================= 4. 任务类型注册表 =================
ok("tasks: registry covers every one-shot task type",
   set(tasks.ONCE_HANDLERS) == {"change_ip", "ipv6", "azure_create", "ensure_network", "migrate", "cf_delete", "resize", "reinstall",
                                "net500m", "foundry", "billing_keep"} and tasks.TASK_RUNNERS == {"snatch": "_run_snatch"})
calls = []


async def fake_once(t):
    calls.append(("once", t["type"]))


async def fake_snatch(t):
    calls.append(("snatch", t["type"]))


with mock.patch.object(tasks, "_run_once", fake_once), mock.patch.object(tasks, "_run_snatch", fake_snatch):
    asyncio.run(tasks._dispatch({"id": 1, "type": "snatch"}))
    asyncio.run(tasks._dispatch({"id": 2, "type": "resize"}))
ok("tasks: dispatch snatch vs one-shot", calls == [("snatch", "snatch"), ("once", "resize")])

# ================= 5. 前端 ES 模块 / 版本号 / 演示页 =================
JS = os.path.join(ROOT, "web", "js")
mods = sorted(f for f in os.listdir(JS) if f.endswith(".js"))
ok("web: app.js split into ES modules", not os.path.exists(os.path.join(ROOT, "web", "app.js")) and len(mods) >= 10 and "main.js" in mods)
names = {}
for f in mods:
    for line in open(os.path.join(JS, f), encoding="utf-8").read().splitlines():
        m = re.match(r"export (?:async )?(?:function|const|let|class) ([\w$]+)", line)
        if m:
            found = [m.group(1)]
            if re.match(r"export (?:const|let) ", line):   # 一行多个简单声明：const A = {}, B = {};
                found += re.findall(r",\s*([\w$]+) = (?:\{\}|\[\]|0)(?=[,;])", line)
            for x in found:
                names.setdefault(x, []).append(f)
bad = []
for f in mods:
    for m in re.finditer(r'^import \{([^}]*)\} from "\./([\w-]+\.js)";', open(os.path.join(JS, f), encoding="utf-8").read(), re.M):
        bad += [(f, x.strip()) for x in m.group(1).split(",") if m.group(2) not in names.get(x.strip(), [])]
ok("web: every imported name is exported by that module", not bad and all(len(v) == 1 for v in names.values()))
with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    html = c.get("/").text
    im = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html).group(1))["imports"]
    ok("index: import map versions every module", sorted(im) == [f"/static/js/{f}" for f in mods]
       and all(re.fullmatch(r"/static/js/[\w-]+\.js\?v=[0-9a-f]{10}", v) for v in im.values()))
    ok("index: module entry script", re.search(r'<script type="module" src="/static/js/main\.js\?v=[0-9a-f]{10}"></script>', html) is not None)
    r = c.get("/static/js/core.js")
    ok("static: modules served as JS with no-cache", r.status_code == 200 and "javascript" in r.headers["content-type"]
       and r.headers.get("cache-control") == "no-cache" and c.get("/static/style.css").headers.get("cache-control") is None)
demo = open(os.path.join(ROOT, "demo", "index.html"), encoding="utf-8").read()
ok("demo: single file, modules inlined as one classic script", "/static/js/" not in demo and 'type="module"' not in demo
   and "export function" not in demo and "function pageHome" in demo and "function setAccounts" in demo)

# ================= 6. 部署相关 =================
dk = open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8").read()
ok("Dockerfile: MALLOC_ARENA_MAX=2 after pip layer", "ENV MALLOC_ARENA_MAX=2" in dk and dk.index("pip install") < dk.index("MALLOC_ARENA_MAX"))

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
