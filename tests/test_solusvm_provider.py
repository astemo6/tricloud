"""SolusVM provider：Client API 的 XML 解析、实例映射、动作映射（全部 mock httpx，不发真请求）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.providers import solusvm_provider  # noqa: E402
from app.providers.solusvm_provider import SolusVMProvider  # noqa: E402

INFO = ("<status>success</status><statusmsg>online</statusmsg><hostname>vps1.example.com</hostname>"
        "<ipaddr>203.0.113.10,2001:db8::1</ipaddr>"
        "<bw>1099511627776,107374182400,992137445376,9</bw>"
        "<mem>2147483648,536870912,1610612736,25</mem>"
        "<hdd>42949672960,10737418240,32212254720,25</hdd>"
        "<location>Tokyo, Japan</location>")


class FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _prov(monkey_resp):
    import types

    import httpx as real_httpx

    calls = []

    class FakeClient:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def post(self, url, data=None):
            calls.append((url, data))
            return FakeResp(monkey_resp(data))

    orig = solusvm_provider.httpx
    solusvm_provider.httpx = types.SimpleNamespace(Client=FakeClient, HTTPError=real_httpx.HTTPError)
    p = SolusVMProvider({"panel_url": "https://cp.greencloudvps.com/", "key": "K", "hash": "H"})
    return p, calls, orig


def _restore(orig):
    solusvm_provider.httpx = orig


def test_parse_and_quad():
    d = solusvm_provider._parse_xml(INFO)
    assert d["hostname"] == "vps1.example.com" and d["statusmsg"] == "online"
    assert solusvm_provider._quad(d["bw"]) == (1099511627776, 107374182400)
    assert solusvm_provider._quad("bad") == (0, 0)


def test_test_and_list():
    p, calls, orig = _prov(lambda data: INFO)
    try:
        assert p.test() == {"ok": True, "hostname": "vps1.example.com", "ip": "203.0.113.10"}
        assert calls[0][0] == "https://cp.greencloudvps.com/api/client/command.php"
        assert calls[0][1]["action"] == "info" and calls[0][1]["bw"] == "true"
        lst = p.list_instances()
        assert len(lst) == 1
        i = lst[0]
        assert i["name"] == "vps1.example.com" and i["state"] == "running"
        assert i["public_ip"] == "203.0.113.10" and i["ipv6"] == ["2001:db8::1"]
        assert i["memory_gb"] == 2.0 and "40.0G 硬盘" in i["shape"]
        assert i["region"] == "Tokyo, Japan"
    finally:
        _restore(orig)


def test_state_offline_and_actions():
    seq = {"status": "<status>success</status><statusmsg>offline</statusmsg>",
           "boot": "<status>success</status><statusmsg>booted</statusmsg>",
           "shutdown": "<status>success</status><statusmsg>shutdown</statusmsg>",
           "reboot": "<status>success</status><statusmsg>rebooted</statusmsg>"}
    p, calls, orig = _prov(lambda data: seq[data["action"]])
    try:
        assert p.get_state("vps1.example.com") == "stopped"
        assert p.action("vps1.example.com", "start") == {"ok": True}
        assert p.action("vps1.example.com", "stop") == {"ok": True}
        assert p.action("vps1.example.com", "hard_reboot") == {"ok": True}
        acts = [c[1]["action"] for c in calls]
        assert acts == ["status", "boot", "shutdown", "reboot"]
        try:
            p.action("vps1.example.com", "terminate")
            raise AssertionError("terminate should refuse")
        except ValueError as e:
            assert "不支持删除" in str(e)
    finally:
        _restore(orig)


def test_traffic_and_error():
    p, calls, orig = _prov(lambda data: INFO)
    try:
        t = p.traffic("vps1.example.com")
        assert t["used_gb"] == 100.0 and t["total_gb"] == 1024.0 and t["out_gb"] == 100.0 and t["in_gb"] == 0
    finally:
        _restore(orig)
    p2, _, orig2 = _prov(lambda data: "<status>error</status><statusmsg>Invalid key</statusmsg>")
    try:
        try:
            p2.test()
            raise AssertionError("error resp should raise")
        except RuntimeError as e:
            assert "Invalid key" in str(e)
    finally:
        _restore(orig2)


def test_registered():
    from app import services
    from app.routers.common import REQUIRED
    assert list(services.PROVIDERS)[-2:] == ["solusvm", "virtfusion"]
    assert REQUIRED["solusvm"] == ["panel_url", "key", "hash"]


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("ok")
