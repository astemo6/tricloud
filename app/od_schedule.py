"""build 23 OneDrive 备份计划：每 N 小时 / 每天多个时间点 / 每周多选星期 / 每月指定日期（含月末）/ 5 段 Cron。

- 全部按面板时区的「墙上时间」计算（naive datetime）：夏令时切换不会多跑或漏算一期——
  春季跳过的那一小时里的计划，在跳过后的第一分钟（时间已超过它）照常触发；秋季重复的一小时同一个 slot key 只跑一次。
- Cron 解析器自写（不引入 croniter）：分 时 日 月 周，支持 * , - / 数字、月份/星期英文缩写、@daily 等宏；
  日与周同时被限定时按 Vixie cron 规则取「或」，任一为 * 开头时取「与」；周 0 和 7 都是周日。
- 旧配置 {freq: daily|weekly, time, weekday} 读取时自动迁移（norm），不改数据库；
  status 里仍返回 freq / time / weekday 兼容旧版 App。
"""
import calendar
import datetime as dt
import functools
import re

MODES = ("hourly", "daily", "weekly", "monthly", "cron")
MODE_NAMES = {"hourly": "每 N 小时", "daily": "每天", "weekly": "每周", "monthly": "每月", "cron": "Cron 表达式"}
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MAX_TIMES = 24              # 每天 / 每周 / 每月最多 24 个时间点
MIN_GAP_MIN = 30            # 两次备份至少间隔 30 分钟（防止 Cron 写成每分钟）
SEARCH_DAYS = 366 * 8 + 2   # 最稀疏的计划（2 月 29 日）也能在 8 年内找到
GAP_CHECK_N = 60            # 校验间隔时检查接下来 60 次
CRON_MAX_LEN = 120

DEFAULTS = {"mode": "daily", "times": ["03:30"], "weekdays": [0], "days": [1], "last_day": False,
            "every_hours": 6, "minute": 0, "start_hour": 0, "cron": "30 3 * * *"}
SCHED_KEYS = tuple(DEFAULTS) + ("freq", "time", "weekday")


class ScheduleError(ValueError):
    pass


# ---------------- Cron ----------------
_CRON_FIELDS = (("分钟", 0, 59), ("小时", 0, 23), ("日", 1, 31), ("月", 1, 12), ("星期", 0, 7))
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_DOWS = {d: i for i, d in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
_MACROS = {"@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *", "@weekly": "0 0 * * 0",
           "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@hourly": "0 * * * *"}
_CRON_CHARS = re.compile(r"^[0-9A-Za-z*,/\- @]+$")


class CronSpec:
    __slots__ = ("minutes", "hours", "doms", "months", "dows", "dom_star", "dow_star", "expr")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def day_match(self, d):
        if d.month not in self.months:
            return False
        dom_ok = d.day in self.doms
        dow_ok = (d.weekday() + 1) % 7 in self.dows      # cron：0=周日
        if self.dom_star or self.dow_star:
            return dom_ok and dow_ok
        return dom_ok or dow_ok

    def times(self):
        return [(h, m) for h in sorted(self.hours) for m in sorted(self.minutes)]


def _cron_num(tok, idx, lo, hi):
    name, _, _ = _CRON_FIELDS[idx]
    t = tok.lower()
    if idx == 3 and t in _MONTHS:
        return _MONTHS[t]
    if idx == 4 and t in _DOWS:
        return _DOWS[t]
    if not t.isdigit():
        raise ScheduleError(f"Cron 第 {idx + 1} 段（{name}）：无法识别「{tok}」")
    v = int(t)
    if not lo <= v <= hi:
        raise ScheduleError(f"Cron 第 {idx + 1} 段（{name}）：{v} 超出范围 {lo}–{hi}")
    return v


def _cron_field(part, idx):
    name, lo, hi = _CRON_FIELDS[idx]
    out = set()
    for item in part.split(","):
        if not item:
            raise ScheduleError(f"Cron 第 {idx + 1} 段（{name}）：逗号之间不能为空")
        base, step = item, 1
        if "/" in item:
            base, _, st = item.partition("/")
            if not st.isdigit() or int(st) < 1:
                raise ScheduleError(f"Cron 第 {idx + 1} 段（{name}）：步长「{st}」应为正整数")
            step = int(st)
            if step > hi - lo + 1 and idx != 4:
                raise ScheduleError(f"Cron 第 {idx + 1} 段（{name}）：步长 {step} 太大（最大 {hi - lo + 1}）")
        if base == "*":
            a, b = lo, hi
        elif "-" in base:
            x, _, y = base.partition("-")
            a, b = _cron_num(x, idx, lo, hi), _cron_num(y, idx, lo, hi)
            if a > b:
                raise ScheduleError(f"Cron 第 {idx + 1} 段（{name}）：范围 {x}-{y} 起点大于终点")
        else:
            a = _cron_num(base, idx, lo, hi)
            b = hi if "/" in item else a
        out.update(range(a, b + 1, step))
    if idx == 4 and 7 in out:
        out.discard(7)
        out.add(0)
    return frozenset(out)


@functools.lru_cache(maxsize=64)
def parse_cron(expr):
    e = " ".join(str(expr or "").split())
    if not e:
        raise ScheduleError("Cron 表达式不能为空")
    if len(e) > CRON_MAX_LEN:
        raise ScheduleError(f"Cron 表达式太长（最多 {CRON_MAX_LEN} 个字符）")
    if not _CRON_CHARS.match(e):
        bad = "".join(sorted({ch for ch in e if not re.match(r"[0-9A-Za-z*,/\- @]", ch)}))
        raise ScheduleError(f"Cron 表达式含不支持的字符「{bad}」（只支持数字、* , - / 和英文缩写）")
    if e.startswith("@"):
        if e.lower() not in _MACROS:
            raise ScheduleError(f"不支持的 Cron 宏「{e}」（可用 {', '.join(sorted(_MACROS))}）")
        e2 = _MACROS[e.lower()]
    else:
        e2 = e
    parts = e2.split(" ")
    if len(parts) != 5:
        raise ScheduleError(f"Cron 需要 5 段：分 时 日 月 周（当前 {len(parts)} 段）")
    f = [_cron_field(p, i) for i, p in enumerate(parts)]
    return CronSpec(minutes=f[0], hours=f[1], doms=f[2], months=f[3], dows=f[4],
                    dom_star=parts[2].startswith("*"), dow_star=parts[4].startswith("*"), expr=e)


# ---------------- 规范化 / 迁移 ----------------
def _hm(s):
    m = TIME_RE.match(str(s or "").strip())
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _int(v, lo, hi, default):
    try:
        i = int(v)
    except (TypeError, ValueError):
        return default
    return i if lo <= i <= hi else default


def norm(raw):
    """存储的配置 → 完整计划字段（容错，不抛异常）。旧版只有 freq/time/weekday 时自动迁移成 daily / weekly。"""
    raw = raw or {}
    c = {}
    mode = raw.get("mode")
    if mode not in MODES:
        mode = "weekly" if raw.get("freq") == "weekly" else "daily"
        legacy = True
    else:
        legacy = False
    c["mode"] = mode
    if legacy:
        times = [raw.get("time") or DEFAULTS["times"][0]]
        wds = [raw.get("weekday", 0)]
    else:
        times = raw.get("times") or DEFAULTS["times"]
        wds = raw.get("weekdays") if raw.get("weekdays") is not None else DEFAULTS["weekdays"]
    c["times"] = sorted({t for t in (_hm(x) for x in (times if isinstance(times, list) else [times])) if t})[:MAX_TIMES] or list(DEFAULTS["times"])
    c["weekdays"] = sorted({_int(x, 0, 6, -1) for x in (wds if isinstance(wds, list) else [wds])} - {-1}) or [0]
    days = raw.get("days") if isinstance(raw.get("days"), list) else DEFAULTS["days"]
    c["days"] = sorted({_int(x, 1, 31, -1) for x in days} - {-1})
    c["last_day"] = bool(raw.get("last_day", False))
    if not c["days"] and not c["last_day"]:
        c["days"] = [1]
    c["every_hours"] = _int(raw.get("every_hours"), 1, 24, DEFAULTS["every_hours"])
    c["minute"] = _int(raw.get("minute"), 0, 59, 0)
    c["start_hour"] = _int(raw.get("start_hour"), 0, 23, 0)
    c["cron"] = str(raw.get("cron") or DEFAULTS["cron"])
    c.update(legacy_view(c))
    return c


def legacy_view(c):
    """给旧版 App 看的 freq / time / weekday（build 21/22 只认这三个）。"""
    # 每 N 小时 / 每月 / Cron 对旧版 App 显示为 daily：旧版下拉框只有每天 / 每周，原样保存时与这里一致，不会覆盖新计划
    m = c["mode"]
    return {"freq": m if m in ("daily", "weekly") else "daily", "time": (c.get("times") or ["03:30"])[0],
            "weekday": (c.get("weekdays") or [0])[0]}


def _list(v):
    if isinstance(v, str):
        return [x for x in re.split(r"[\s,，、;；]+", v.strip()) if x]
    if isinstance(v, (list, tuple)):
        return list(v)
    if v is None:
        return []
    return [v]


def apply(cur, body):
    """把请求里的计划字段合并进当前（已规范化的）配置并严格校验。返回 (新配置, 是否改了计划)。
    旧版 App 只发 freq/time/weekday（每次保存都带上）：与当前配置的旧视图一致时视为没改计划，不会把多时间点 / Cron 覆盖掉。"""
    c = dict(cur)
    changed = False
    if "mode" in body:
        if body["mode"] not in MODES:
            raise ScheduleError("频率模式只能是 " + " / ".join(f"{k}（{v}）" for k, v in MODE_NAMES.items()))
        if body["mode"] != c["mode"]:
            c["mode"] = body["mode"]
            changed = True
    elif any(k in body for k in ("freq", "time", "weekday")):
        lv = legacy_view(cur)
        freq = body.get("freq", lv["freq"])
        if freq not in ("daily", "weekly") and "freq" in body:
            raise ScheduleError("频率只能是 daily（每天）或 weekly（每周）")
        t = _hm(body["time"]) if "time" in body else lv["time"]
        if t is None:
            raise ScheduleError("时间格式应为 HH:MM（24 小时制）")
        wd = lv["weekday"]
        if "weekday" in body:
            wd = _int(body["weekday"], 0, 6, -1)
            if wd < 0:
                raise ScheduleError("星期需为 0（周一）~6（周日）")
        same = freq == lv["freq"] and t == lv["time"] and (freq != "weekly" or wd == lv["weekday"])
        if not same:
            if freq not in ("daily", "weekly"):
                freq = "daily"
            c["mode"], c["times"] = freq, [t]
            if freq == "weekly":
                c["weekdays"] = [wd]
            changed = True
    if "times" in body:
        ts = []
        for x in _list(body["times"]):
            h = _hm(x)
            if h is None:
                raise ScheduleError(f"时间「{x}」格式应为 HH:MM（24 小时制）")
            ts.append(h)
        ts = sorted(set(ts))
        if not ts:
            raise ScheduleError("至少需要一个时间点")
        if len(ts) > MAX_TIMES:
            raise ScheduleError(f"时间点最多 {MAX_TIMES} 个")
        changed |= ts != c["times"]
        c["times"] = ts
    if "weekdays" in body:
        wds = set()
        for x in _list(body["weekdays"]):
            v = _int(x, 0, 6, -1)
            if v < 0:
                raise ScheduleError(f"星期「{x}」需为 0（周一）~6（周日）")
            wds.add(v)
        if not wds:
            raise ScheduleError("每周至少选一天")
        changed |= sorted(wds) != c["weekdays"]
        c["weekdays"] = sorted(wds)
    if "days" in body or "last_day" in body:
        days, last = set(), bool(c["last_day"])
        if "last_day" in body:
            v = body["last_day"]
            last = v.strip().lower() not in ("0", "false", "no", "off", "") if isinstance(v, str) else bool(v)
        if "days" in body:
            for x in _list(body["days"]):
                if str(x).strip().upper() in ("L", "LAST", "月末"):
                    last = True
                    continue
                v = _int(x, 1, 31, -1)
                if v < 0:
                    raise ScheduleError(f"日期「{x}」需为 1~31 或 L（月末）")
                days.add(v)
        else:
            days = set(c["days"])
        if not days and not last:
            raise ScheduleError("每月至少选一个日期（或月末）")
        changed |= sorted(days) != c["days"] or last != c["last_day"]
        c["days"], c["last_day"] = sorted(days), last
    for k, lo, hi, label in (("every_hours", 1, 24, "间隔小时数需为 1~24"), ("minute", 0, 59, "起始分钟需为 0~59"),
                             ("start_hour", 0, 23, "起始小时需为 0~23")):
        if k in body:
            v = _int(body[k], lo, hi, -1)
            if v < 0:
                raise ScheduleError(label)
            changed |= v != c[k]
            c[k] = v
    if "cron" in body:
        e = " ".join(str(body["cron"] or "").split())
        if c["mode"] == "cron":
            parse_cron(e)      # 当前模式是 Cron：严格校验（空 / 非法都报错）
        else:
            try:               # 其他模式顺带提交的 Cron 草稿：合法才保存，不合法忽略，不影响保存当前模式
                parse_cron(e)
            except ScheduleError:
                e = ""
        if e:
            changed |= e != c["cron"]
            c["cron"] = e
    if c["mode"] == "cron":
        parse_cron(c["cron"])
    c.update(legacy_view(c))
    return c, changed


# ---------------- 计算 ----------------
def day_times(c, d):
    """日期 d 当天的全部计划时间 [(h, m)]（已排序），不在计划内返回 []。"""
    m = c["mode"]
    if m == "hourly":
        n, sh = c["every_hours"], c["start_hour"]
        return [(h, c["minute"]) for h in range(24) if (h - sh) % n == 0]
    if m == "cron":
        spec = parse_cron(c["cron"])
        return spec.times() if spec.day_match(d) else []
    tl = [tuple(int(x) for x in t.split(":")) for t in c["times"]]
    if m == "daily":
        return tl
    if m == "weekly":
        return tl if d.weekday() in c["weekdays"] else []
    if m == "monthly":
        last = calendar.monthrange(d.year, d.month)[1]
        return tl if d.day in c["days"] or (c["last_day"] and d.day == last) else []
    return []


def _naive(now):
    return now.replace(tzinfo=None, second=0, microsecond=0) if now.tzinfo else now.replace(second=0, microsecond=0)


def prev_run(c, now):
    """≤ now 的最近一次计划时间（naive 墙上时间），8 年内没有返回 None。"""
    n = _naive(now)
    d0 = n.date()
    for i in range(SEARCH_DAYS):
        d = d0 - dt.timedelta(days=i)
        for h, m in reversed(day_times(c, d)):
            t = dt.datetime(d.year, d.month, d.day, h, m)
            if t <= n:
                return t
    return None


def iter_next(c, now, limit_days=SEARCH_DAYS):
    """> now 的计划时间（naive），按时间顺序产出。"""
    n = _naive(now)
    d0 = n.date()
    for i in range(limit_days):
        d = d0 + dt.timedelta(days=i)
        for h, m in day_times(c, d):
            t = dt.datetime(d.year, d.month, d.day, h, m)
            if t > n:
                yield t


def next_runs(c, now, count=3):
    out = []
    for t in iter_next(c, now):
        out.append(t)
        if len(out) >= count:
            break
    return out


def check(c, now):
    """校验当前模式的计划能触发且间隔不小于 MIN_GAP_MIN。返回接下来 3 次（naive）。"""
    nxt = []
    prev = None
    for t in iter_next(c, now):
        if prev is not None and (t - prev) < dt.timedelta(minutes=MIN_GAP_MIN):
            raise ScheduleError(f"两次备份至少间隔 {MIN_GAP_MIN} 分钟（{prev:%m-%d %H:%M} 与 {t:%H:%M} 太近）")
        nxt.append(t)
        prev = t
        if len(nxt) >= GAP_CHECK_N:
            break
    if not nxt:
        raise ScheduleError("这个计划在未来 8 年内都不会触发（例如 2 月 30 日），请检查日期")
    return nxt[:3]


def period_seconds(c, slot):
    """slot（naive）这一期的长度：到下一次计划时间的秒数；找不到按 1 天算。"""
    for t in iter_next(c, slot, limit_days=400):
        return (t - slot).total_seconds()
    return 86400.0


def retry_gap(period):
    """失败重试间隔：周期 ≥4 小时沿用 1 小时；短周期按周期的 1/4（至少 10 分钟），保证每期 3 次都落在本期内。"""
    if period >= 4 * 3600:
        return 3600
    return max(600, int(period // 4))


# ---------------- 描述 ----------------
def _join_times(ts, limit=8):
    s = "、".join(ts[:limit])
    return s + (f" 等 {len(ts)} 个时间点" if len(ts) > limit else "")


def describe(c):
    m = c["mode"]
    if m == "hourly":
        n = c["every_hours"]
        hs = [f"{h:02d}:{mm:02d}" for h, mm in day_times(c, dt.date(2000, 1, 3))]
        if n == 1:
            return f"每小时第 {c['minute']} 分" if c["minute"] else "每小时整点"
        return f"每 {n} 小时（每天 {_join_times(hs, 6)}）"
    if m == "daily":
        return "每天 " + _join_times(c["times"])
    if m == "weekly":
        wds = c["weekdays"]
        w = "每天" if len(wds) == 7 else "每周" + "、".join(WEEKDAYS[i][1:] for i in wds)
        return w + " " + _join_times(c["times"])
    if m == "monthly":
        parts = [str(d) for d in c["days"]]
        ds = ("、".join(parts) + " 日" if parts else "") + (("和" if parts else "") + "月末" if c["last_day"] else "")
        return ("每月 " + ds if parts else "每月" + ds) + " " + _join_times(c["times"])
    if m == "cron":
        return "Cron「" + c["cron"] + "」"
    return m


def label(t):
    return f"{t:%Y-%m-%d %H:%M}（{WEEKDAYS[t.weekday()]}）"
