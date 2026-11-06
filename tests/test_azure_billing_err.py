"""自测：Azure 账单查询的错误翻译。
成本接口 429 限流 → ValueError 友好提示（不再冒泡成 500）；其它 HttpResponseError → 带详情的 ValueError；
订阅不支持成本 API → 仍走 CloudUnsupportedError 专门通道；账单路由 ValueError 转 400 且不吞 CloudUnsupportedError。"""
import os
import sys
import tempfile

os.environ.update(TRICLOUD_DATA=tempfile.mkdtemp())
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from azure.core.exceptions import HttpResponseError

from app import core
from app.providers.azure_provider import AzureProvider

core.init_db()
R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def provider_raising(err):
    p = AzureProvider.__new__(AzureProvider)
    p.sub = "00000000-0000-0000-0000-000000000000"
    p.credential = object()

    class FakeQuery:
        @staticmethod
        def usage(scope, parameters):
            raise err

    class FakeCM:
        query = FakeQuery()

    p._cached = lambda cls, mk: FakeCM()
    return p


def grab(err):
    try:
        provider_raising(err).billing()
        return None
    except Exception as e:
        return e


e429 = HttpResponseError("(429) Too many requests. Please retry.")
e429.status_code = 429
x = grab(e429)
ok("429 -> ValueError with friendly throttle msg",
   type(x) is ValueError and "429" in str(x) and "限流" in str(x))

e500 = HttpResponseError("Internal server error from ARM")
e500.status_code = 500
x = grab(e500)
ok("500 -> ValueError with detail", type(x) is ValueError and "Internal server error" in str(x))

euns = HttpResponseError("The offer MS-AZR-0170P is not supported for cost management")
euns.status_code = 400
x = grab(euns)
ok("unsupported offer -> CloudUnsupportedError (special channel kept)",
   isinstance(x, core.CloudUnsupportedError) and "Azure for Students" in str(x))

route = open(os.path.join(ROOT, "app/routers/billing.py"), encoding="utf-8").read()
ok("route: CloudUnsupportedError re-raised, ValueError -> 400",
   "except core.CloudUnsupportedError" in route and "except ValueError" in route and "HTTPException(400" in route)
i18n = open(os.path.join(ROOT, "app/i18n.py"), encoding="utf-8").read()
ok("i18n pairs", i18n.count('"err.azure_throttled"') == 2 and i18n.count('"err.azure_billing_failed"') == 2)

import app.main  # noqa: F401  导入链完整（路由注册不炸）
ok("app.main imports cleanly", True)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
