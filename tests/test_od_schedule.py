"""build 23 OneDrive 备份计划：每 N 小时 / 每天多个时间点 / 每周多选 / 每月日期（含月末）/ 5 段 Cron（自写解析器），
预览接口、旧配置迁移、旧版 App 兼容、短周期重试不跨期、时区、闰年 2/29、DST、TG /backup、API Token、前端与 App 源码。"""
import datetime as dt
import json
import os
import re
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient

from app import core, main, od_schedule as S, onedrive, security, services, telegram

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def err(fn, *a, contains=""):
    try:
        fn(*a)
    except S.ScheduleError as e:
        return contains in str(e)
    return False


def N(**kw):
    return S.norm(kw)


def K(t):
    return t.strftime("%Y-%m-%d %H:%M")


def nx(c, now, n=3):
    return [K(t) for t in S.next_runs(c, now, n)]


T0 = dt.datetime(2026, 10, 16, 21, 40)   # 周五

# ================= 1. 迁移（旧 build 21/22 配置） =================
old_daily = {"enabled": True, "freq": "daily", "time": "03:30", "weekday": 0, "keep": 30}
old_weekly = {"enabled": True, "freq": "weekly", "time": "05:00", "weekday": 2, "keep": 7}
m1, m2 = S.norm(old_daily), S.norm(old_weekly)
ok("migrate: daily → mode daily times [03:30]", m1["mode"] == "daily" and m1["times"] == ["03:30"])
ok("migrate: weekly → mode weekly weekdays [2] times [05:00]", m2["mode"] == "weekly" and m2["weekdays"] == [2] and m2["times"] == ["05:00"])
ok("migrate: legacy view kept (freq/time/weekday)", (m2["freq"], m2["time"], m2["weekday"]) == ("weekly", "05:00", 2))
ok("migrate: empty → defaults daily 03:30", S.norm({})["mode"] == "daily" and S.norm({})["times"] == ["03:30"] and S.norm(None)["cron"] == "30 3 * * *")
ok("migrate: same slot keys as build 21 (daily)", K(S.prev_run(m1, dt.datetime(2026, 10, 16, 2, 0))) == "2026-10-15 03:30"
   and K(S.prev_run(m1, dt.datetime(2026, 10, 16, 4, 0))) == "2026-10-16 03:30")
ok("migrate: same slot keys as build 21 (weekly)", K(S.prev_run(m2, T0)) == "2026-10-14 05:00" and nx(m2, T0, 1) == ["2026-10-21 05:00"])
ok("migrate: garbage values tolerated", S.norm({"mode": "x", "freq": "weekly", "time": "99:99", "weekday": 9})["times"] == ["03:30"]
   and S.norm({"mode": "x", "freq": "weekly", "weekday": 9})["weekdays"] == [0])
ok("norm: new-format fields kept", S.norm({"mode": "monthly", "days": [31, 1, 1], "last_day": True, "times": ["23:00", "01:00"]})
   == dict(S.norm({"mode": "monthly"}), days=[1, 31], last_day=True, times=["01:00", "23:00"], time="01:00", freq="daily"))

# ================= 2. 每 N 小时 =================
h6 = N(mode="hourly", every_hours=6, minute=15)
ok("hourly 6h: day times 00:15 06:15 12:15 18:15", S.day_times(h6, dt.date(2026, 1, 1)) == [(0, 15), (6, 15), (12, 15), (18, 15)])
ok("hourly 6h: next 3 from 21:40", nx(h6, T0) == ["2026-10-17 00:15", "2026-10-17 06:15", "2026-10-17 12:15"])
ok("hourly 6h: prev = 18:15", K(S.prev_run(h6, T0)) == "2026-10-16 18:15")
h1 = N(mode="hourly", every_hours=1, minute=0)
ok("hourly 1h: 24 slots, next 22:00 23:00 00:00 (crosses midnight)", len(S.day_times(h1, dt.date(2026, 1, 1))) == 24 and nx(h1, T0) == ["2026-10-16 22:00", "2026-10-16 23:00", "2026-10-17 00:00"])
h5 = N(mode="hourly", every_hours=5, minute=0, start_hour=2)
ok("hourly 5h start 02: phase per day (02 07 12 17 22)", [h for h, _ in S.day_times(h5, dt.date(2026, 1, 1))] == [2, 7, 12, 17, 22])
h24 = N(mode="hourly", every_hours=24, minute=30, start_hour=4)
ok("hourly 24h: once a day at start_hour:minute", S.day_times(h24, dt.date(2026, 1, 1)) == [(4, 30)])
ok("hourly: exact boundary is prev, not next", K(S.prev_run(h6, dt.datetime(2026, 10, 16, 18, 15))) == "2026-10-16 18:15"
   and nx(h6, dt.datetime(2026, 10, 16, 18, 15), 1) == ["2026-10-17 00:15"])
ok("hourly describe", S.describe(h6) == "每 6 小时（每天 00:15、06:15、12:15、18:15）" and S.describe(h1) == "每小时整点"
   and S.describe(N(mode="hourly", every_hours=1, minute=5)) == "每小时第 5 分")

# ================= 3. 每天多个时间点 =================
d3 = N(mode="daily", times=["20:00", "08:00", "12:30", "08:00"])
ok("daily multi: sorted + dedup", d3["times"] == ["08:00", "12:30", "20:00"])
ok("daily multi: next 3", nx(d3, T0) == ["2026-10-17 08:00", "2026-10-17 12:30", "2026-10-17 20:00"])
ok("daily multi: prev 20:00 today", K(S.prev_run(d3, T0)) == "2026-10-16 20:00")
ok("daily describe", S.describe(d3) == "每天 08:00、12:30、20:00")

# ================= 4. 每周多选 =================
w = N(mode="weekly", weekdays=[0, 2, 4], times=["03:00", "22:00"])
ok("weekly multi: next from Fri 21:40 → Fri 22:00, Mon 03:00, Mon 22:00", nx(w, T0) == ["2026-10-16 22:00", "2026-10-19 03:00", "2026-10-19 22:00"])
ok("weekly multi: prev Fri 03:00", K(S.prev_run(w, T0)) == "2026-10-16 03:00")
ok("weekly describe", S.describe(w) == "每周一、三、五 03:00、22:00")
ok("weekly all 7 days describe 每天", S.describe(N(mode="weekly", weekdays=list(range(7)), times=["01:00"])) == "每天 01:00")
ok("weekly Sunday (6)", nx(N(mode="weekly", weekdays=[6], times=["09:00"]), T0, 1) == ["2026-10-18 09:00"])

# ================= 5. 每月（含月末、闰年） =================
mo = N(mode="monthly", days=[1, 15], last_day=True, times=["02:00"])
ok("monthly 1/15/月末: next", nx(mo, T0) == ["2026-10-31 02:00", "2026-11-01 02:00", "2026-11-15 02:00"])
ok("monthly: prev 10-15", K(S.prev_run(mo, T0)) == "2026-10-15 02:00")
ml = N(mode="monthly", days=[], last_day=True, times=["23:30"])
ok("monthly 月末 only: Feb 2027 → 28, Feb 2028 → 29 (leap)", "2027-02-28 23:30" in nx(ml, dt.datetime(2027, 1, 31, 23, 40), 2)
   and nx(ml, dt.datetime(2028, 1, 31, 23, 40), 1) == ["2028-02-29 23:30"])
ok("monthly 月末 Apr/Jun 30, Dec 31", nx(ml, dt.datetime(2026, 4, 1), 1) == ["2026-04-30 23:30"] and nx(ml, dt.datetime(2026, 12, 1), 1) == ["2026-12-31 23:30"])
m31 = N(mode="monthly", days=[31], times=["04:00"])
ok("monthly 31: months without 31 skipped (Oct→Dec)", nx(m31, dt.datetime(2026, 10, 31, 5, 0), 2) == ["2026-12-31 04:00", "2027-01-31 04:00"])
m29 = N(mode="monthly", days=[29], times=["04:00"])
ok("monthly 29: Feb skipped in 2027, kept in 2028", nx(m29, dt.datetime(2027, 1, 30), 1) == ["2027-03-29 04:00"]
   and nx(m29, dt.datetime(2028, 1, 30), 1) == ["2028-02-29 04:00"])
ok("monthly 31 + 月末 on 31-day month: one run (no duplicate)", nx(N(mode="monthly", days=[31], last_day=True, times=["04:00"]), dt.datetime(2026, 10, 30), 2)
   == ["2026-10-31 04:00", "2026-11-30 04:00"])
ok("monthly describe", S.describe(mo) == "每月 1、15 日和月末 02:00" and S.describe(ml) == "每月月末 23:30")

# ================= 6. Cron 解析 =================
P = S.parse_cron
ok("cron: */15 minutes", P("*/15 * * * *").minutes == frozenset({0, 15, 30, 45}))
ok("cron: list + range + step", P("0 1,5-9/2,23 * * *").hours == frozenset({1, 5, 7, 9, 23}))
ok("cron: a/s = a..max step s", P("10/20 * * * *").minutes == frozenset({10, 30, 50}))
ok("cron: dow 7 == 0 (Sunday)", P("0 0 * * 7").dows == frozenset({0}) and P("0 0 * * 0").dows == frozenset({0}))
ok("cron: dow 0-7 = all", P("0 0 * * 0-7").dows == frozenset(range(7)))
ok("cron: names (MON-FRI, jan,jul)", P("0 0 * jan,JUL MON-fri").months == frozenset({1, 7}) and P("0 0 * * MON-fri").dows == frozenset({1, 2, 3, 4, 5}))
ok("cron: macros @daily @hourly @weekly @monthly @yearly", P("@daily").hours == frozenset({0}) and P("@hourly").hours == frozenset(range(24))
   and P("@weekly").dows == frozenset({0}) and P("@monthly").doms == frozenset({1}) and P("@yearly").months == frozenset({1}))
ok("cron: extra whitespace tolerated", P("  0   3 * *  * ").expr == "0 3 * * *")
ok("cron: boundaries 59 23 31 12 7 ok", P("59 23 31 12 7").minutes == frozenset({59}))
for bad, frag in (("", "不能为空"), ("0 3 * *", "5 段"), ("0 3 * * * *", "5 段"), ("60 * * * *", "超出范围 0–59"), ("* 24 * * *", "超出范围 0–23"),
                  ("* * 0 * *", "超出范围 1–31"), ("* * 32 * *", "超出范围 1–31"), ("* * * 13 *", "超出范围 1–12"), ("* * * * 8", "超出范围 0–7"),
                  ("*/0 * * * *", "步长"), ("*/x * * * *", "步长"), ("5-1 * * * *", "起点大于终点"), ("1,,2 * * * *", "不能为空"),
                  ("? * * * *", "不支持的字符"), ("0 3 L * *", "无法识别"), ("@reboot", "不支持的 Cron 宏"), ("0 3 * * mon#2", "不支持的字符"),
                  ("*/61 * * * *", "步长 61 太大"), ("0 " * 70, "太长")):
    ok(f"cron: invalid {bad.strip()[:20]!r} → {frag}", err(P, bad, contains=frag))
cr = N(mode="cron", cron="30 3 * * 1-5")
ok("cron weekdays 03:30: next from Fri 21:40 → Mon Tue Wed", nx(cr, T0) == ["2026-10-19 03:30", "2026-10-20 03:30", "2026-10-21 03:30"])
ok("cron: dom+dow both restricted → OR (1st of month OR Monday)", nx(N(mode="cron", cron="0 9 1 * mon"), T0) == ["2026-10-19 09:00", "2026-10-26 09:00", "2026-11-01 09:00"])
ok("cron: dom restricted, dow * → AND (only the 13th)", nx(N(mode="cron", cron="0 0 13 * *"), T0, 2) == ["2026-11-13 00:00", "2026-12-13 00:00"])
ok("cron: dow */2 (Sun Tue Thu Sat) starts with * → AND with dom *", nx(N(mode="cron", cron="0 0 * * */2"), T0, 3) == ["2026-10-17 00:00", "2026-10-18 00:00", "2026-10-20 00:00"])
ok("cron: Feb 29 → 2028, 2032", nx(N(mode="cron", cron="0 3 29 2 *"), T0, 2) == ["2028-02-29 03:00", "2032-02-29 03:00"]
   and K(S.prev_run(N(mode="cron", cron="0 3 29 2 *"), T0)) == "2024-02-29 03:00")
ok("cron: month restriction", nx(N(mode="cron", cron="0 0 1 3,9 *"), T0, 2) == ["2027-03-01 00:00", "2027-09-01 00:00"])
ok("cron describe", S.describe(cr) == "Cron「30 3 * * 1-5」")

# ================= 7. apply / check（保存前校验） =================
base = S.norm(old_daily)
c, ch = S.apply(base, {"mode": "hourly", "every_hours": "4", "minute": 5})
ok("apply: hourly from strings", ch and c["mode"] == "hourly" and c["every_hours"] == 4 and c["minute"] == 5)
c, ch = S.apply(base, {"mode": "daily", "times": "08:00, 20:00，9:05"})
ok("apply: times from comma string (incl. full-width comma, H:MM)", c["times"] == ["08:00", "09:05", "20:00"])
c, _ = S.apply(base, {"mode": "monthly", "days": "1,15,L"})
ok("apply: days with L → last_day", c["days"] == [1, 15] and c["last_day"] is True)
c, _ = S.apply(base, {"mode": "monthly", "days": [], "last_day": True})
ok("apply: only 月末 ok", c["days"] == [] and c["last_day"])
for body, frag in (({"mode": "yearly"}, "频率模式"), ({"mode": "hourly", "every_hours": 0}, "1~24"), ({"mode": "hourly", "every_hours": 25}, "1~24"),
                   ({"minute": 60}, "0~59"), ({"start_hour": 24}, "0~23"), ({"times": ["25:00"]}, "HH:MM"), ({"times": []}, "至少需要一个"),
                   ({"times": [f"{h:02d}:00" for h in range(24)] + ["00:30"]}, "最多 24"), ({"weekdays": [7]}, "0（周一）"), ({"weekdays": []}, "至少选一天"),
                   ({"days": [0]}, "1~31"), ({"days": [32]}, "1~31"), ({"days": [], "last_day": False}, "至少选一个日期"),
                   ({"mode": "cron", "cron": "bad"}, "5 段"), ({"mode": "cron", "cron": ""}, "不能为空"), ({"freq": "hourly"}, "daily（每天）"),
                   ({"time": "7:7"}, "HH:MM"), ({"weekday": 7}, "0（周一）")):
    ok(f"apply: invalid {json.dumps(body, ensure_ascii=False)[:40]} → {frag}", err(S.apply, base, body, contains=frag))
c, _ = S.apply(base, {"mode": "daily", "cron": "garbage"})
ok("apply: invalid cron draft ignored when mode is not cron", c["cron"] == "30 3 * * *" and c["mode"] == "daily")
c, _ = S.apply(base, {"mode": "daily", "cron": "0 4 * * *"})
ok("apply: valid cron draft stored when mode is not cron", c["cron"] == "0 4 * * *")
ok("check: every 10 min cron rejected (min gap 30)", err(S.check, N(mode="cron", cron="*/10 * * * *"), T0, contains="至少间隔 30 分钟"))
ok("check: daily times 15 min apart rejected", err(S.check, N(mode="daily", times=["08:00", "08:15"]), T0, contains="至少间隔"))
ok("check: every 30 min cron allowed", len(S.check(N(mode="cron", cron="*/30 * * * *"), T0)) == 3)
ok("check: 23:50 + 00:10 next day rejected (gap across midnight)", err(S.check, N(mode="daily", times=["00:10", "23:50"]), T0, contains="至少间隔"))
ok("check: never-firing (Feb 30) rejected", err(S.check, N(mode="cron", cron="0 0 30 2 *"), T0, contains="不会触发"))
ok("check: Feb 31 / Apr 31 never fire", err(S.check, N(mode="cron", cron="0 0 31 2,4,6 *"), T0, contains="不会触发"))
ok("check: sparse cron (Feb 29) returns 2 within 8 years", len(S.check(N(mode="cron", cron="0 3 29 2 *"), T0)) == 2)

# 旧版 App 兼容：带着与当前一致的 freq/time/weekday 保存（只改保留份数）不会覆盖新计划
for cur in (N(mode="hourly", every_hours=3), N(mode="cron", cron="0 4 * * 1"), N(mode="monthly", days=[5], times=["06:00"]),
            N(mode="daily", times=["08:00", "20:00"]), N(mode="weekly", weekdays=[1, 3], times=["07:00", "19:00"])):
    lv = S.legacy_view(cur)
    c, ch = S.apply(cur, {"enabled": True, "freq": lv["freq"], "time": lv["time"], "weekday": str(lv["weekday"]), "keep": "9"})
    ok(f"old app save keeps {cur['mode']} plan", not ch and c["mode"] == cur["mode"] and c["times"] == cur["times"])
c, ch = S.apply(N(mode="daily", times=["08:00", "20:00"]), {"freq": "weekly", "time": "06:00", "weekday": 4})
ok("old app changing freq/time → legacy weekly single time", ch and c["mode"] == "weekly" and c["times"] == ["06:00"] and c["weekdays"] == [4])
ok("legacy view of non-daily modes is daily (old App spinner has only daily/weekly)", S.legacy_view(N(mode="cron"))["freq"] == "daily")

# ================= 8. 重试间隔（短周期不跨期） =================
ok("retry gap: ≥4h → 1h", S.retry_gap(4 * 3600) == 3600 and S.retry_gap(86400) == 3600)
ok("retry gap: 1h → 15min, 2h → 30min, 3h → 45min", (S.retry_gap(3600), S.retry_gap(7200), S.retry_gap(10800)) == (900, 1800, 2700))
ok("retry gap: min 10 min (30 min period)", S.retry_gap(1800) == 600)

# ================= 9. 面板集成：due / status / 预览接口 / TG =================
c = TestClient(main.app)
c.__enter__()
lr = c.post("/api/login", json={"password": "devpassword123", "client": "app"})
c.cookies.clear()
H = {"Authorization": "Bearer " + lr.json()["token"]}


def g(p):
    return c.get(p, headers=H)


def post(p, body=None):
    return c.post(p, json=body or {}, headers=H)


TZ = services.tz()
core.set_secret_setting(onedrive.K_TOKEN, {"refresh_token": "rt-x", "account": {"folder": "TriCloud Backup"}})
core.set_secret_setting(onedrive.K_PW, "pw")
core.set_setting(onedrive.K_CFG, old_weekly)   # 线上旧格式
core.set_setting(onedrive.K_STATE, {"slot": "2026-10-14 05:00", "slot_tries": 1, "last_result": "ok"})
s = g("/api/onedrive").json()
ok("status (old cfg in DB): migrated view, mode weekly, desc, next 3", s["cfg"]["mode"] == "weekly" and s["cfg"]["weekdays"] == [2] and s["cfg"]["keep"] == 7
   and s["desc"] == "每周三 05:00" and len(s["next_runs"]) == 3 and s["next_run"] == s["next_runs"][0] and s["next_run"].endswith("05:00")
   and dt.date.fromisoformat(s["next_run"][:10]).weekday() == 2 and "（周三）" in s["next_runs_label"][0])
ok("status: legacy fields for old App", (s["cfg"]["freq"], s["cfg"]["time"], s["cfg"]["weekday"]) == ("weekly", "05:00", 2))
ok("status: modes + min gap exposed", s["modes"]["cron"] == "Cron 表达式" and s["min_gap_minutes"] == 30)
ok("read-only status does not rewrite old cfg in DB", core.get_setting(onedrive.K_CFG) == old_weekly)
wed = dt.datetime(2026, 10, 14, 6, 0, tzinfo=TZ)
ok("due after migration: same slot key → no extra run", onedrive.due(wed) is None)
ok("due after migration: next Wednesday 05:00 → run", onedrive.due(dt.datetime(2026, 10, 21, 5, 0, tzinfo=TZ)) == "2026-10-21 05:00")

r = post("/api/onedrive/schedule/preview", {"mode": "monthly", "days": [1, 15], "last_day": True, "times": ["02:00"]})
j = r.json()
ok("preview: 200 desc + 3 next + labels + tz", r.status_code == 200 and j["desc"] == "每月 1、15 日和月末 02:00" and len(j["next_runs"]) == 3
   and j["timezone"] == "Asia/Shanghai" and all("（周" in x for x in j["next_runs_label"]))
ok("preview: does not save", core.get_setting(onedrive.K_CFG) == old_weekly)
r = post("/api/onedrive/schedule/preview", {"mode": "cron", "cron": "0 25 * * *"})
ok("preview: invalid cron 400 friendly", r.status_code == 400 and "第 2 段（小时）" in r.json()["detail"])
ok("preview: too frequent 400", post("/api/onedrive/schedule/preview", {"mode": "cron", "cron": "* * * * *"}).status_code == 400)
ok("preview: never fires 400", "不会触发" in post("/api/onedrive/schedule/preview", {"mode": "cron", "cron": "0 0 30 2 *"}).json()["detail"])
ok("preview: empty body → current plan", post("/api/onedrive/schedule/preview", {}).json()["desc"] == "每周三 05:00")
ok("preview: not audited", not core.q("SELECT 1 FROM audit WHERE action LIKE '%schedule/preview%'", one=True))
ok("preview: unauthenticated 401", c.post("/api/onedrive/schedule/preview", json={}).status_code == 401)
tok = security.new_api_token("bot", "full")
TH = {"Authorization": "Bearer " + tok}
ok("API Token: config 403 (unchanged rule)", c.post("/api/onedrive/config", json={"mode": "hourly"}, headers=TH).status_code == 403)
ok("API Token: preview 403 too (non-GET /api/onedrive* rule unchanged)", c.post("/api/onedrive/schedule/preview", json={}, headers=TH).status_code == 403)
ok("API Token: GET status 200 with desc", c.get("/api/onedrive", headers=TH).json()["desc"] == "每周三 05:00")

r = post("/api/onedrive/config", {"mode": "hourly", "every_hours": 2, "minute": 10, "keep": 5})
j = r.json()
ok("config save: hourly stored in new format + changed=schedule,keep", r.status_code == 200 and "schedule" in j["changed"] and "keep" in j["changed"]
   and core.get_setting(onedrive.K_CFG)["mode"] == "hourly" and core.get_setting(onedrive.K_CFG)["freq"] == "daily" and j["cfg"]["keep"] == 5)
now = services.now_local()
ok("config save: slot reset to current period (no immediate run)", onedrive.state()["slot"] == onedrive.slot_key(onedrive.cfg(), now) and onedrive.due(now) is None)
ok("config save: next_run is next even hour :10", j["next_run"].endswith(":10") and int(j["next_run"][11:13]) % 2 == 0)
ok("config save invalid → 400, nothing stored", post("/api/onedrive/config", {"mode": "cron", "cron": "*/5 * * * *"}).status_code == 400
   and core.get_setting(onedrive.K_CFG)["mode"] == "hourly")
r = post("/api/onedrive/config", {"enabled": True, "freq": "daily", "time": onedrive.cfg()["time"], "weekday": 0, "keep": 6})
ok("config save from old App (same legacy view) keeps hourly", r.status_code == 200 and onedrive.cfg()["mode"] == "hourly" and onedrive.cfg()["keep"] == 6
   and "schedule" not in r.json()["changed"])

# 短周期重试：2 小时一期，失败后 30 分钟重试，不跨期
core.set_setting(onedrive.K_CFG, dict(onedrive.cfg(), mode="hourly", every_hours=2, minute=0, start_hour=0))
core.set_setting(onedrive.K_STATE, {"slot": "2026-10-16 10:00"})
k = onedrive.due(dt.datetime(2026, 10, 16, 12, 1, tzinfo=TZ))
ok("hourly 2h: new period 12:00", k == "2026-10-16 12:00")
onedrive.mark_try(k)
onedrive.set_state(last_result="failed", failed_slot=k)
ok("2h period: not retried before 30 min", onedrive.due(dt.datetime(2026, 10, 16, 12, 20, tzinfo=TZ)) is None)
onedrive.set_state(last_try=int(time.time()) - 1810)
ok("2h period: retried after 30 min", onedrive.due(dt.datetime(2026, 10, 16, 12, 31, tzinfo=TZ)) == k)
ok("retry_info: gap 1800, next period 14:00", onedrive.retry_info(onedrive.cfg(), k) == (1800, dt.datetime(2026, 10, 16, 14, 0)))
ok("2h period: no retry within 5 min of next period", onedrive.due(dt.datetime(2026, 10, 16, 13, 57, tzinfo=TZ)) is None)
ok("next period: key changes → normal run (no cross-period retry)", onedrive.due(dt.datetime(2026, 10, 16, 14, 0, tzinfo=TZ)) == "2026-10-16 14:00")
onedrive.set_state(slot_tries=3)
ok("max 3 tries in a short period", onedrive.due(dt.datetime(2026, 10, 16, 12, 50, tzinfo=TZ)) is None)
ok("retry_text: exhausted mentions 下一次计划时间", "下一次计划时间" in onedrive.retry_text(k))
_n = services.now_local().replace(second=0, microsecond=0)
k_now = f"{_n:%Y-%m-%d} {_n.hour // 2 * 2:02d}:00"      # 真实时钟所在的这一期（2 小时一期）
onedrive.set_state(slot=k_now, slot_tries=1, last_try=int(time.time()) - (_n.hour % 2) * 3600 - _n.minute * 60)   # 刚到期就失败
ok("retry_text: 30 分钟后自动重试", "30 分钟后自动重试" in onedrive.retry_text(k_now) and "还剩 2 次" in onedrive.retry_text(k_now))
core.set_setting(onedrive.K_CFG, dict(onedrive.cfg(), every_hours=1))
ok("1h period: retry gap 15 min", onedrive.retry_info(onedrive.cfg(), "2026-10-16 12:00")[0] == 900)
core.set_setting(onedrive.K_CFG, dict(onedrive.cfg(), mode="daily", times=["03:30"]))
ok("daily: retry gap stays 1 hour (build 21 rule)", onedrive.retry_info(onedrive.cfg(), "2026-10-16 03:30")[0] == 3600)
# 上次尝试固定为该期开始后 1 分钟（以前用当前时间，日期过了下一期就变成「离下一期太近」）
onedrive.set_state(slot="2026-10-16 03:30", slot_tries=1,
                   last_try=int(dt.datetime(2026, 10, 16, 3, 31, tzinfo=onedrive.now_local().tzinfo).timestamp()))
ok("retry_text daily: 1 小时后自动重试", "1 小时后自动重试" in onedrive.retry_text("2026-10-16 03:30"))

# 时区：面板时区换成 UTC，计划按新时区墙上时间
core.set_setting("timezone", "UTC")
s = g("/api/onedrive").json()
ok("timezone: status uses panel tz", s["timezone"] == "UTC" and s["next_run"].endswith("03:30"))
core.set_setting("timezone", "Asia/Shanghai")

# DST（America/New_York 2026-03-08 02:00→03:00，2026-11-01 02:00→01:00）
NY = ZoneInfo("America/New_York")
core.set_setting(onedrive.K_CFG, {"enabled": True, "keep": 3, "mode": "daily", "times": ["02:30"]})
core.set_setting(onedrive.K_STATE, {"slot": "2026-03-07 02:30"})
ok("DST spring: 01:59 EST still previous period", onedrive.due(dt.datetime(2026, 3, 8, 1, 59, tzinfo=NY)) is None)
ok("DST spring: skipped 02:30 runs once at 03:00 EDT", onedrive.due(dt.datetime(2026, 3, 8, 3, 0, tzinfo=NY)) == "2026-03-08 02:30")
onedrive.mark_try("2026-03-08 02:30")
onedrive.set_state(last_result="ok")
ok("DST spring: not again at 03:30", onedrive.due(dt.datetime(2026, 3, 8, 3, 30, tzinfo=NY)) is None)
core.set_setting(onedrive.K_CFG, {"enabled": True, "keep": 3, "mode": "daily", "times": ["01:30"]})
core.set_setting(onedrive.K_STATE, {"slot": "2026-10-31 01:30"})
first = dt.datetime(2026, 11, 1, 1, 30, tzinfo=NY)            # EDT
second = dt.datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=NY)   # EST（重复的那一小时）
ok("DST fall: two different instants", first.utcoffset() != second.utcoffset())
k1 = onedrive.due(first)
onedrive.mark_try(k1)
onedrive.set_state(last_result="ok")
ok("DST fall: 01:30 runs once (EDT), repeated 01:30 EST same key → no duplicate", k1 == "2026-11-01 01:30" and onedrive.due(second) is None)
ok("DST: hourly 1h across fall-back no duplicate key", K(S.prev_run(N(mode="hourly", every_hours=1), first)) == K(S.prev_run(N(mode="hourly", every_hours=1), second)))

# TG /backup 显示新计划描述 + 下次时间
core.set_setting(onedrive.K_CFG, {"enabled": True, "keep": 4, "mode": "weekly", "weekdays": [0, 3], "times": ["04:00", "16:00"]})
txt = telegram.backup_command("status")
ok("tg /backup status: desc + next + following", "计划：每周一、四 04:00、16:00" in txt and "下次：" in txt and "之后：" in txt and "保留 4 份" in txt)
core.set_setting(onedrive.K_CFG, {"enabled": True, "keep": 4, "mode": "cron", "cron": "0 */6 * * *"})
ok("tg /backup cron desc", "Cron「0 */6 * * *」" in telegram.backup_command("status"))
ok("restore keeps working with new slot_key (string, not '-')", onedrive.slot_key(onedrive.cfg(), services.now_local()) != "-")
ok("slot_key '-' when nothing in 8 years (defensive)", onedrive.slot_key({"mode": "cron", "cron": "0 0 30 2 *"}, services.now_local()) == "-")
core.set_setting(onedrive.K_CFG, {"enabled": True, "keep": 4, "mode": "cron", "cron": "0 0 30 2 *"})
ok("due: never-firing stored cfg → None (no crash)", onedrive.due(services.now_local()) is None)
ok("tasks.py retry text via onedrive.retry_text", "onedrive.retry_text(" in open(os.path.join(ROOT, "app", "tasks.py"), encoding="utf-8").read())
c.__exit__(None, None, None)

# ================= 10. 前端 / App / 文档 =================
rd = lambda *p: open(os.path.join(ROOT, *p), encoding="utf-8").read()   # noqa: E731
W = rd("web", "js", "onedrive.js")
ok("web: preview endpoint + 5 modes + month-end + cron", "/onedrive/schedule/preview" in W and all(m in W for m in ('"hourly"', '"daily"', '"weekly"', '"monthly"', '"cron"'))
   and "月末" in W and "接下来 3 次" in W)
ok("web: add/remove time rows", "odAddTime" in W and "data-odrm" in W)
AJ = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "OneDriveScheduleActivity.java")
ok("android: schedule activity (Material 3 chips, preview, save)", "/onedrive/schedule/preview" in AJ and "ChipGroup" in AJ and "/onedrive/config" in AJ and "月末" in AJ)
ok("android: manifest registers activity", "OneDriveScheduleActivity" in rd("android", "app", "src", "main", "AndroidManifest.xml"))
ok("android: OneDriveActivity opens schedule editor + shows desc", "OneDriveScheduleActivity" in rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "OneDriveActivity.java"))
IS = rd("ios", "TriCloud", "OneDriveSchedule.swift")
ok("ios: schedule page (SwiftUI Form, preview, save)", "/onedrive/schedule/preview" in IS and "Form" in IS and "/onedrive/config" in IS and "月末" in IS)
ok("ios: OneDrivePage pushes schedule page + desc", "OneDriveSchedulePage" in rd("ios", "TriCloud", "OneDrivePage.swift"))
_vc = re.search(r"versionCode (\d+)", rd("android", "app", "build.gradle")).group(1)
ok("android versionCode ≥ 23 == iOS build", int(_vc) >= 23 and f'CURRENT_PROJECT_VERSION: "{_vc}"' in rd("ios", "project.yml"))
DOC = rd("docs", "api-credentials.md")
ok("docs: schedule modes + cron + preview", "schedule/preview" in DOC and "Cron" in DOC and "月末" in DOC)
ok("changelog / features mention build 23; release notes current build", "build 23" in rd("CHANGELOG.md") and "build 23" in rd("docs", "FEATURES.md")
   and f"build {_vc}" in rd(".github", "release-notes.md"))
ok("demo mock: preview route", "/onedrive/schedule/preview" in rd("demo", "mock.js"))
ok("no croniter dependency", "croniter" not in rd("requirements.txt"))

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
