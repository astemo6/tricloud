"""VirtFusion provider：终端用户 API 的列表分页 / 字段映射 / 鉴权错误（全部 mock httpx）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.providers import virtfusion_provider  # noqa: E402
from app.providers.virtfusion_provider import VirtFusionProvider  # noqa: E402

SERVER = {"id": 69, "name": "vps1", "cpu": "2", "memory": "2048",
          "storage": [{"capacity": "40", "enabled": True, "primary": True},
                      {"capacity": "10", "enabled": False, "primary": False}],
          "network": {"primary": {"ipv4": [{"address": "203.0.113.20"}],
                                  "ipv6": [{"addresses": ["2001:db8::5", "2001:db8::6"]}]}}}


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status
        self.content = b"x" if payload is not None else b""

    def json(self):
        return self._p


def _prov(handler):
    import types

    import httpx as real_httpx

    class FakeClient:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url, headers=None):
            assert headers["Authorization"] == "Bearer TOK"
            return handler(url)

    orig = virtfusion_provider.httpx
    virtfusion_provider.httpx = types.SimpleNamespace(Client=FakeClient, HTTPError=real_httpx.HTTPError)
    return VirtFusionProvider({"panel_url": "https://cp.example.com/", "api_token": "TOK"}), orig


def _restore(orig):
    virtfusion_provider.httpx = orig


def test_list_pagination_and_map():
    pages = {"server?page=1": {"data": [SERVER], "next_page_url": "https://cp.example.com/api/server?page=2"},
             "server?page=2": {"data": [dict(SERVER, id=70, name="vps2")], "next_page_url": None}}

    def handler(url):
        return FakeResp(pages[url.split("/api/")[1]])

    p, orig = _prov(handler)
    try:
        lst = p.list_instances()
        assert [i["name"] for i in lst] == ["vps1", "vps2"]
        i = lst[0]
        assert i["id"] == "69" and i["public_ip"] == "203.0.113.20"
        assert i["ipv6"] == ["2001:db8::5", "2001:db8::6"]
        assert i["shape"] == "2 核 / 2G 内存 / 40G 硬盘"   # 未启用的第二块盘不计
        assert p.get_state("70") == "unknown"              # 列表无状态字段时 unknown，不乱猜
    finally:
        _restore(orig)


def test_test_ok_and_401():
    p, orig = _prov(lambda url: FakeResp({}))
    try:
        assert p.test() == {"ok": True}
    finally:
        _restore(orig)
    p2, orig2 = _prov(lambda url: FakeResp(None, status=401))
    try:
        try:
            p2.test()
            raise AssertionError("401 should raise")
        except RuntimeError as e:
            assert "API key 无效" in str(e)
    finally:
        _restore(orig2)


def test_unsupported_actions_are_explicit():
    p, orig = _prov(lambda url: FakeResp({}))
    try:
        try:
            p.action("69", "terminate")
            raise AssertionError("terminate should refuse")
        except ValueError:
            pass
        try:
            p.action("69", "start")
            raise AssertionError("power should be explicit pending")
        except ValueError as e:   # CloudUnsupportedError（ValueError 子类，面板里走友好 400）
            assert "待实测" in str(e)
        try:
            p.traffic("69")
            raise AssertionError("traffic should be explicit pending")
        except ValueError as e:
            assert "待实测" in str(e)
    finally:
        _restore(orig)


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("ok")
