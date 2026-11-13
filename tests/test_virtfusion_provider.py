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


def test_traffic_period_text():
    def handler(method, path, params, body):
        return FakeResp({"data": dict(SERVER2, state=STATE)})

    p, orig, _ = _prov(handler)
    try:
        t = p.traffic(SERVER2["id"])
        assert t["period"] == "2025-10-17 ~ 2025-11-16"   # 守护弹窗的 {period} 占位（真实 API 为 ISO，UTC 日期）
        assert t["period_start"] == SERVER2["currentMonthlyPeriod"]["start"]   # 原字段保持兼容
        assert t["period_end"] == SERVER2["currentMonthlyPeriod"]["end"]
        assert t["reset_at"] == "2025" + "-11-17T00:00:00+00:00"   # 周期结束 23:59:59.999999Z 的下一分钟取整
        assert t["days_left"] == 0                             # 2025 年的周期早已过去
    finally:
        _restore(orig)


def test_parse_period_time_formats():
    import datetime as dt
    ppt = virtfusion_provider.parse_period_time
    cst = dt.timezone(dt.timedelta(hours=8))
    assert ppt(SERVER["currentMonthlyPeriod"]["start"]) == dt.datetime(2025, 10, 17, tzinfo=dt.timezone.utc)   # 真实格式 ISO + 微秒 + Z
    assert ppt(SERVER["currentMonthlyPeriod"]["end"]) == dt.datetime(2025, 11, 16, 23, 59, 59, tzinfo=dt.timezone.utc)
    # 人类可读格式（部分面板 / 文档截图里的写法）也能解析
    assert ppt("Fri 2025-10-17 8:00 AM CST (UTC+08:00)") == dt.datetime(2025, 10, 17, 8, 0, tzinfo=cst)
    assert ppt("Mon 2025-11-17 7:59 AM CST (UTC+08:00)") == dt.datetime(2025, 11, 17, 7, 59, tzinfo=cst)
    assert ppt("2025-11-17 7:59 PM CST (UTC+08:00)") == dt.datetime(2025, 11, 17, 19, 59, tzinfo=cst)   # 无星期
    assert ppt("Sat 2025-11-01 12:00 AM EDT (UTC-04:00)") == dt.datetime(2025, 11, 1, 0, 0, tzinfo=dt.timezone(-dt.timedelta(hours=4)))
    assert ppt("Sat 2025-11-01 12:30 PM UTC (UTC+00:00)").hour == 12
    assert ppt("Thu 2025-12-04 5:30 AM IST (UTC+05:30)").utcoffset() == dt.timedelta(hours=5, minutes=30)
    assert ppt("2025-11-17T07:59:00+08:00") == dt.datetime(2025, 11, 17, 7, 59, tzinfo=cst)   # ISO
    assert ppt("2025-11-17T07:59:00Z") == dt.datetime(2025, 11, 17, 7, 59, tzinfo=dt.timezone.utc)
    assert ppt("2025-11-17 07:59:30") == dt.datetime(2025, 11, 17, 7, 59, 30, tzinfo=dt.timezone.utc)   # 无偏移按 UTC
    assert ppt("2025-11-17") == dt.datetime(2025, 11, 17, tzinfo=dt.timezone.utc)
    for bad in (None, "", "next month", "2025-13-01 8:00 AM", "Fri 2025-10-17 13:00 PM CST (UTC+08:00)", "2025-10-17 8:00 AM (UTC+25:00)"):
        assert ppt(bad) is None, bad


def test_period_info_reset_and_days_left():
    import datetime as dt
    pi = virtfusion_provider.period_info
    cst = dt.timezone(dt.timedelta(hours=8))
    s, e = "Fri 2026-10-17 8:00 AM CST (UTC+08:00)", "Tue 2026-11-17 7:59 AM CST (UTC+08:00)"
    r = pi(s, e, now=dt.datetime(2026, 11, 13, 13, 43, tzinfo=cst))
    assert r["period"] == "2026-10-17 ~ 2026-11-17"
    assert r["reset_at"] == "2026-11-17T08:00:00+08:00" and r["days_left"] == 4 and r["hours_left"] == 91
    assert pi(s, e, now=dt.datetime(2026, 11, 17, 7, 0, tzinfo=cst))["days_left"] == 0      # 当天重置
    assert pi(s, e, now=dt.datetime(2026, 11, 18, tzinfo=cst))["days_left"] == 0            # 已过期
    # 秒级结束（23:59:59）→ 下一分钟取整到 00:00
    r2 = pi("2026-10-01T00:00:00+00:00", "2026-10-31T23:59:59+00:00", now=dt.datetime(2026, 10, 30, tzinfo=dt.timezone.utc))
    assert r2["reset_at"] == "2026-11-01T00:00:00+00:00" and r2["days_left"] == 2
    # 解析不了：period 退回原文，不给 reset_at
    r3 = pi("someday", "later")
    assert r3 == {"period": "someday ~ later"}
    assert pi(None, None) == {}


def test_with_reset_text_panel_timezone():
    import datetime as dt

    from app import core, services
    orig_get, orig_now = core.get_setting, services.now_local
    try:
        core.get_setting = lambda k, d=None: "Asia/Shanghai" if k == "timezone" else d
        services.now_local = lambda: dt.datetime(2026, 11, 13, 13, 43, tzinfo=services.tz())
        r = services.with_reset_text({"used_gb": 1, "reset_at": "2026-11-17T08:00:00+08:00"})
        assert r["reset_text"] == "11-17 08:00" and r["days_left"] == 4 and r["used_gb"] == 1
        r = services.with_reset_text({"reset_at": "2026-11-17T00:00:00+00:00"})   # UTC → 面板时区
        assert r["reset_text"] == "11-17 08:00"
        core.get_setting = lambda k, d=None: "America/Los_Angeles" if k == "timezone" else d
        services.now_local = lambda: dt.datetime(2026, 11, 13, 0, 0, tzinfo=services.tz())
        r = services.with_reset_text({"reset_at": "2026-11-17T08:00:00+08:00"})
        assert r["reset_text"] == "11-16 16:00" and r["days_left"] == 3
        assert services.with_reset_text({"period": "x"}) == {"period": "x"}   # SolusVM 等：原样
        assert services.with_reset_text({"reset_at": "garbage"}) == {"reset_at": "garbage"}
    finally:
        core.get_setting, services.now_local = orig_get, orig_now


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
