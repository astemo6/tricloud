"""总览卡片：每个账号在「所有有机器的区域」里的实例数（只读，免费 API）。

以前总览只查账号当前区域（AWS 默认 us-east-1），机器在东京等其他区域的账号会显示 0 台。现在：
- AWS：全区域扫描 EC2 + Lightsail（AWSProvider.scan_all_regions，每账号并发 4 个区域），结果缓存 FULL_TTL（30 分钟，
  与「区域扫描」页共用同一份缓存）；缓存有效期内的刷新只重查「已知有机器的区域 + 默认区域 + 新建过实例的区域」，
  这份结果再缓存 HOT_TTL（2 分钟）。refresh=true 强制全量扫描，但两次全量至少间隔 MIN_FULL_GAP 秒。
  IAM 没有 ec2:DescribeRegions 时依次退回 account:ListRegions / botocore 静态区域表（未启用的 opt-in 区域跳过）。
- OCI：所有 READY 的订阅区域，各 1 次 ListInstances（账号配置的区间，与实例页一致；不查 VNIC），缓存 HOT_TTL。
- Azure：订阅级 virtual_machines.list_all(status_only) 一次拿到所有区域的 VM 与电源状态（不逐台查网卡/公网 IP，
  以前首页走实例列表要逐台查 NIC，所以慢），缓存 HOT_TTL。
同一账号同一时间只跑一次查询（锁），并发打开 Web 和 App 不会重复扫描。
"""
import concurrent.futures as cf
import threading
import time

from . import core, services

FULL_TTL = 1800      # AWS 全区域扫描缓存（秒）
HOT_TTL = 120        # 总览汇总缓存（秒）
MIN_FULL_GAP = 60    # refresh=true 时两次全量扫描的最小间隔（秒）

_full = {}           # acc_id -> {"ts", "rows", "updated_at"}（AWS 全区域扫描）
_sum = {}            # acc_id -> {"ts", "data"}（总览汇总）
_extra = {}          # acc_id -> set(region)：新建过实例的区域，下次重查时带上
_locks = {}
_glock = threading.Lock()


def _lock(acc_id):
    with _glock:
        return _locks.setdefault(acc_id, threading.Lock())


def invalidate(acc_id, region=None, full=False):
    """实例新建 / 开关机 / 终止后调用：丢掉汇总缓存（下次重查已知区域）；region 记入待重查；full=True 连全量扫描一起作废。"""
    _sum.pop(acc_id, None)
    if region:
        _extra.setdefault(acc_id, set()).add(region)
    if full:
        _full.pop(acc_id, None)


def clear(acc_id=None):
    for d in (_full, _sum, _extra):
        if acc_id is None:
            d.clear()
        else:
            d.pop(acc_id, None)


# ---------------- AWS ----------------
def _has(row):
    return bool(row.get("ec2") or row.get("lightsail"))


def aws_full(acc_id, refresh=False):
    """AWS 全区域扫描（带缓存），返回 {"regions": rows, "updated_at"}；「区域扫描」页 /aws/scan 也用它。"""
    with _lock(acc_id):
        c = _full.get(acc_id)
        age = time.time() - c["ts"] if c else None
        if c and (age < (MIN_FULL_GAP if refresh else FULL_TTL)):
            return {"regions": c["rows"], "updated_at": c["updated_at"]}
        rows = services.provider(acc_id).scan_all_regions()
        c = _full[acc_id] = {"ts": time.time(), "rows": rows, "updated_at": services.now_local().strftime("%Y-%m-%d %H:%M")}
        _extra.pop(acc_id, None)
        _sum.pop(acc_id, None)
        return {"regions": rows, "updated_at": c["updated_at"]}


def _aws_rows(acc, refresh):
    """全量缓存有效时只重查热区域，否则全量扫描。返回 (rows, scope)。"""
    acc_id = acc["id"]
    c = _full.get(acc_id)
    if refresh or not c or time.time() - c["ts"] >= FULL_TTL:
        return aws_full(acc_id, refresh)["regions"], "all"
    hot = {r["region"] for r in c["rows"] if _has(r) or r.get("ec2_error")}
    hot |= _extra.get(acc_id, set())
    if acc.get("region"):
        hot.add(acc["region"])
    fresh = services.provider(acc_id).scan_all_regions(sorted(hot))
    with _lock(acc_id):
        by = {r["region"]: r for r in c["rows"]}
        for r in fresh:
            if r.get("not_enabled") and r["region"] not in by:
                continue
            by[r["region"]] = r
        c["rows"] = sorted(by.values(), key=lambda r: r["region"])
        _extra.pop(acc_id, None)
    return c["rows"], "known"


def summarize_aws(rows, default_region):
    regions, errors = [], []
    tot = {"ec2": 0, "ec2_running": 0, "lightsail": 0, "lightsail_running": 0}
    ls_failed = False
    for r in rows:
        if r.get("not_enabled"):
            continue
        if r.get("ec2_error"):   # Lightsail 失败只标 lightsail_failed，不算区域查询失败
            errors.append({"region": r["region"], "error": r["ec2_error"]})
        if r.get("lightsail_error"):
            ls_failed = True
        for k in tot:
            tot[k] += r.get(k) or 0
        n = (r.get("ec2") or 0) + (r.get("lightsail") or 0)
        if n:
            regions.append({"region": r["region"], "count": n,
                            "running": (r.get("ec2_running") or 0) + (r.get("lightsail_running") or 0),
                            "ec2": r.get("ec2") or 0, "lightsail": r.get("lightsail") or 0})
    scanned = sum(1 for r in rows if not r.get("not_enabled"))
    if rows and len(errors) >= scanned and not regions:
        raise RuntimeError("所有区域查询失败：" + ", ".join(sorted({e["error"] for e in errors}))[:200])
    return dict(tot, total=tot["ec2"] + tot["lightsail"], running=tot["ec2_running"] + tot["lightsail_running"],
                regions=regions, errors=errors, scanned=scanned, lightsail_failed=ls_failed,
                default_region=default_region)


# ---------------- OCI ----------------
def _oci(acc):
    import oci
    p = services.provider(acc["id"])
    try:
        subs = p.identity.list_region_subscriptions(p.cfg["tenancy"]).data
        regions = [s.region_name for s in subs if (getattr(s, "status", None) or "READY") == "READY"]
    except Exception:
        regions = []
    regions = regions or [p.cfg["region"]]

    def one(rg):
        try:
            c = p._c(oci.core.ComputeClient, dict(p.cfg, region=rg))
            st = [i.lifecycle_state for i in oci.pagination.list_call_get_all_results(
                c.list_instances, compartment_id=p.compartment).data if i.lifecycle_state != "TERMINATED"]
            return {"region": rg, "count": len(st), "running": sum(1 for s in st if s == "RUNNING")}
        except Exception as e:
            return {"region": rg, "error": str(getattr(e, "code", None) or type(e).__name__)[:80]}
    with cf.ThreadPoolExecutor(max_workers=min(4, len(regions))) as ex:
        rows = list(ex.map(one, regions))
    return _generic(rows, acc.get("region"))


# ---------------- Azure ----------------
def _azure(acc):
    p = services.provider(acc["id"])
    by = {}
    for vm in p.compute.virtual_machines.list_all(status_only="true"):
        ps = [s.code for s in (vm.instance_view.statuses if vm.instance_view else []) if (s.code or "").startswith("PowerState/")]
        st = ps[0].split("/")[1] if ps else "unknown"
        r = by.setdefault((vm.location or "-").lower(), {"region": (vm.location or "-").lower(), "count": 0, "running": 0})
        r["count"] += 1
        r["running"] += st == "running"
    return _generic(list(by.values()), None)


def _generic(rows, default_region):
    errors = [{"region": r["region"], "error": r["error"]} for r in rows if r.get("error")]
    if rows and len(errors) == len(rows):
        raise RuntimeError("所有区域查询失败：" + ", ".join(sorted({e["error"] for e in errors}))[:200])
    regions = [r for r in rows if not r.get("error") and r["count"]]
    return {"total": sum(r["count"] for r in regions), "running": sum(r["running"] for r in regions),
            "regions": regions, "errors": errors, "scanned": len(rows), "default_region": default_region}


# ---------------- 入口 ----------------
def summary(acc_id, refresh=False):
    acc = core.get_account(acc_id)
    if not acc:
        raise KeyError("账号不存在")
    c = _sum.get(acc_id)
    if c and not refresh and time.time() - c["ts"] < HOT_TTL:
        return dict(c["data"], cached=True)
    pv = acc["provider"]
    with _lock(("sum", acc_id)):   # 同一账号同时只查一次；等锁的请求直接用刚查到的结果
        c = _sum.get(acc_id)
        if c and not refresh and time.time() - c["ts"] < HOT_TTL:
            return dict(c["data"], cached=True)
        if pv == "aws":
            rows, scope = _aws_rows(acc, refresh)
            data = dict(summarize_aws(rows, acc.get("region")), scope=scope,
                        full_scan_at=(_full.get(acc_id) or {}).get("updated_at"))
        else:
            data = dict(_oci(acc) if pv == "oci" else _azure(acc), scope="all")
        data["regions"].sort(key=lambda r: (-r["count"], r["region"]))
        data.update(account_id=acc_id, provider=pv, updated_at=services.now_local().strftime("%Y-%m-%d %H:%M:%S"))
        _sum[acc_id] = {"ts": time.time(), "data": data}
    return dict(data, cached=False)
