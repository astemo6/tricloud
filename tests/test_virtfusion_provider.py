"""VirtFusion provider：按官方 API 文档（cp.green.cloud 导出，2026-11-10）的
真实结构 mock——UUID id、带单位字符串、Laravel 分页、?state=true 的
state{status,running,traffic}、电源 POST 端点、PUT 改名（全部 mock httpx）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.providers import virtfusion_provider  # noqa: E402
from app.providers.virtfusion_provider import VirtFusionProvider  # noqa: E402

SERVER = {"id": "6b32bae9-83e9-44f9-afd4-244f1fa27a49", "name": "Test VM", "hostname": None,
          "suspended": False, "deleting": False, "memory": "1024 MB", "cpu": "2 Core",
          "storage": [{"capacity": "10 GB", "enabled": True, "primary": True},
                      {"capacity": "20 GB", "enabled": False, "primary": False}],
          "network": {"primary": {"limit": None,
                                  "ipv4": [{"address": "203.0.113.20", "gateway": "203.0.113.1"}],
                                  "ipv6": [{"addresses": ["2001:db8::5"]}]},
                      "secondary": []},
          "currentMonthlyPeriod": {"start": "2025-10-17T00:00:00.000000Z", "end": "2025-11-16T23:59:59.999999Z"},
          "created": "2025-08-17T11:06:30+00:00"}
SERVER2 = dict(SERVER, id="c23c0144-dd3a-4193-aaeb-bea5ad5e4ac0", name="TEST VM2",
               memory="4096 MB", cpu="4 Core",
               storage=[{"capacity": "40 GB", "enabled": True, "primary": True}],
               network={"primary": {"limit": "20000 GB", "ipv4": [{"address": "203.0.113.21"}], "ipv6": []},
                        "secondary": []})
STATE = {"status": "running", "running": True, "cpu": "0.3 %",
         "network": {"primary": {"traffic": {"rx": 85047516, "tx": 69343413, "total": 154390929}}}}


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status
        self.content = b"x" if payload is not None else b""

    def json(self):
        return self._p


def _prov(handler):
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

        def request(self, method, url, json=None, params=None, headers=None):
            assert headers["Authorization"] == "Bearer TOK"
            path = url.split("/api/")[1]
            calls.append((method, path, params, json))
            return handler(method, path, params, json)

    orig = virtfusion_provider.httpx
    virtfusion_provider.httpx = types.SimpleNamespace(Client=FakeClient, HTTPError=real_httpx.HTTPError)
    return VirtFusionProvider({"panel_url": "https://cp.example.com/", "api_token": "TOK"}), orig, calls


def _restore(orig):
    virtfusion_provider.httpx = orig


def test_list_pagination_and_map():
    pages = {1: {"current_page": 1, "data": [SERVER], "next_page_url": "/api/server?results=100&page=2"},
             2: {"current_page": 2, "data": [SERVER2], "next_page_url": None}}

    def handler(method, path, params, body):
        assert method == "GET" and path == "server" and params["results"] == 100
        return FakeResp(pages[params["page"]])

    p, orig, _ = _prov(handler)
    try:
        lst = p.list_instances()
        assert [i["name"] for i in lst] == ["Test VM", "TEST VM2"]
        i = lst[0]
        assert i["id"] == SERVER["id"] and i["public_ip"] == "203.0.113.20"
        assert i["ipv6"] == ["2001:db8::5"]
        # 带单位字符串解析：2 Core / 1024 MB / 10 GB（未启用的 20 GB 不计）
        assert i["shape"] == "2 核 / 1G 内存 / 10G 硬盘"
        assert lst[1]["shape"] == "4 核 / 4G 内存 / 40G 硬盘"
        assert i["state"] == "unknown"          # 列表不带电源状态，不乱猜
        assert p._map(dict(SERVER, suspended=True))["state"] == "suspended"
    finally:
        _restore(orig)


def test_get_state_and_traffic():
    def handler(method, path, params, body):
        assert path == f"server/{SERVER2['id']}" and params == {"state": "true"}
        return FakeResp({"data": dict(SERVER2, state=STATE)})

    p, orig, _ = _prov(handler)
    try:
        assert p.get_state(SERVER2["id"]) == "running"
        t = p.traffic(SERVER2["id"])
        gib = 1024 ** 3
        assert t["in_gb"] == round(85047516 / gib, 3) and t["out_gb"] == round(69343413 / gib, 3)
        assert t["used_gb"] == round(154390929 / gib, 3)
        assert t["total_gb"] == 20000.0                       # network.primary.limit "20000 GB"
        assert t["period_start"] == SERVER2["currentMonthlyPeriod"]["start"]
    finally:
        _restore(orig)

    def stopped(method, path, params, body):
        return FakeResp({"data": dict(SERVER2, state=dict(STATE, status="stopped", running=False))})

    p2, orig2, _ = _prov(stopped)
    try:
        assert p2.get_state(SERVER2["id"]) == "stopped"
    finally:
        _restore(orig2)


def test_power_actions_and_rename():
    def handler(method, path, params, body):
        if method == "PUT":
            assert path == f"server/{SERVER['id']}/name" and body == {"name": "new-name"}
            return FakeResp(None, status=204)
        assert method == "POST"
        return FakeResp({"data": {"task": {"id": 2892, "status": "accepted"}}})

    p, orig, calls = _prov(handler)
    try:
        assert p.action(SERVER["id"], "start") is True
        assert p.action(SERVER["id"], "stop") is True
        assert p.action(SERVER["id"], "reboot") is True
        paths = [c[1] for c in calls]
        assert paths == [f"server/{SERVER['id']}/boot", f"server/{SERVER['id']}/shutdown",
                         f"server/{SERVER['id']}/restart"]
        assert p.rename(SERVER["id"], "new-name") == {}
    finally:
        _restore(orig)


def test_vnc_enabled_and_enable_flow():
    vnc_on = {"data": {"enabled": True, "password": "abcd1234",
                       "wss": {"token": "tok-uuid", "url": "/vnc/?token=tok-uuid"}}}

    p, orig, _ = _prov(lambda m, path, params, body: FakeResp(vnc_on))
    try:
        v = p.vnc(SERVER["id"])
        assert v == {"url": "wss://cp.example.com/vnc/?token=tok-uuid", "password": "abcd1234", "enabled": True}
    finally:
        _restore(orig)

    state = {"n": 0}

    def handler(method, path, params, body):
        if method == "POST":
            assert path == f"server/{SERVER['id']}/vnc"
            return FakeResp({"data": {"task": {"id": 1, "status": "accepted"}}})
        state["n"] += 1
        return FakeResp(vnc_on if state["n"] >= 2 else {"data": {"enabled": False, "password": "abcd1234",
                                                                "wss": {"token": "tok-uuid", "url": "/vnc/?token=tok-uuid"}}})

    p2, orig2, _ = _prov(handler)
    p2._VNC_POLL_SECONDS = 0
    try:
        v2 = p2.vnc(SERVER["id"])
        assert v2["enabled"] is True and v2["url"].startswith("wss://")
    finally:
        _restore(orig2)


def test_traffic_period_text():
    def handler(method, path, params, body):
        return FakeResp({"data": dict(SERVER2, state=STATE)})

    p, orig, _ = _prov(handler)
    try:
        t = p.traffic(SERVER2["id"])
        assert t["period"] == "2025-10-17 ~ 2025-11-16"   # 守护弹窗的 {period} 占位
    finally:
        _restore(orig)


def test_test_ok_and_401():
    p, orig, _ = _prov(lambda m, path, params, body: FakeResp({}))
    try:
        assert p.test() == {"ok": True}
    finally:
        _restore(orig)
    p2, orig2, _ = _prov(lambda m, path, params, body: FakeResp({"message": "Unauthenticated."}, status=401))
    try:
        try:
            p2.test()
            raise AssertionError("401 should raise")
        except RuntimeError as e:
            assert "API key 无效" in str(e)
    finally:
        _restore(orig2)


def test_unsupported_actions_are_explicit():
    p, orig, _ = _prov(lambda m, path, params, body: FakeResp({}))
    try:
        for act in ("terminate", "hard_reboot"):
            try:
                p.action("x", act)
                raise AssertionError(f"{act} should refuse")
            except ValueError:   # CloudUnsupportedError（ValueError 子类，面板里走友好 400）
                pass
        try:
            p.billing()
            raise AssertionError("billing should refuse")
        except ValueError:
            pass
    finally:
        _restore(orig)


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("ok")
