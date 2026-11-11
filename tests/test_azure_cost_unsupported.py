"""Azure 学生订阅（MS-AZR-0170P）不支持成本管理 API：账单接口返回 400 友好提示而不是 500。"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from azure.core.exceptions import HttpResponseError  # noqa: E402

from app import core  # noqa: E402
from app.providers import azure_provider  # noqa: E402

ERR = ("(BadRequest) Cost management data is unavailable for subscription 0000. "
       "The offer MS-AZR-0170P is not supported. (Request ID: x)")


def _prov(exc):
    p = azure_provider.AzureProvider.__new__(azure_provider.AzureProvider)
    p.sub = "0000"
    p.credential = None
    q = types.SimpleNamespace(usage=lambda **kw: (_ for _ in ()).throw(exc))
    p._cached = lambda cls, fn: types.SimpleNamespace(query=q)
    return p


def test_unsupported_offer_is_friendly():
    try:
        _prov(HttpResponseError(message=ERR)).billing()
    except core.CloudUnsupportedError as e:
        assert "MS-AZR-0170P" in str(e) and "Azure for Students" in str(e)
    else:
        raise AssertionError("expected CloudUnsupportedError")


def test_other_errors_still_raise():
    try:
        _prov(HttpResponseError(message="(Throttled) too many")).billing()
    except core.CloudUnsupportedError:
        raise AssertionError("should not be friendly")
    except (HttpResponseError, ValueError):   # fix/azure-billing-429 起其他错误包成 err.azure_billing_failed（ValueError）
        pass


def test_handler_registered():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "main.py"), encoding="utf-8").read()
    assert "exception_handler(core.CloudUnsupportedError)" in src


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("ok")
