"""后台任务、实例监控、流量守护。"""
from fastapi import APIRouter, Body, HTTPException

from .. import core, tasks, telegram, traffic_guard
from .common import need_acc, run

router = APIRouter()


# ---------------- 任务 ----------------
@router.get("/api/tasks")
def list_tasks(limit: int = 50):
    rows = core.q("SELECT t.*, a.name AS account_name, a.provider FROM tasks t LEFT JOIN accounts a ON a.id=t.account_id "
                  "ORDER BY t.id DESC LIMIT ?", (limit,))
    return rows


@router.get("/api/tasks/{tid}")
def task_detail(tid: int, after: int = 0):
    """v1.4：任务状态 + 追加式日志 + 结果。after=上次拿到的最后一条日志 id，只返回新日志（轮询用）。"""
    import json as _json
    t = core.q("SELECT t.*, a.name AS account_name, a.provider FROM tasks t LEFT JOIN accounts a ON a.id=t.account_id WHERE t.id=?",
               (tid,), one=True)
    if not t:
        raise HTTPException(404, "任务不存在")
    try:
        params = _json.loads(t.pop("params") or "{}")
    except ValueError:
        params = {}
    safe = {k: params.get(k) for k in ("instance_id", "name", "region", "kind", "mode", "cidrs", "max_tries", "interval",
                                       "max_attempts", "reason", "auto", "size", "ocpus", "memory_gb", "shape") if params.get(k) not in (None, "")}
    if isinstance(params.get("create"), dict):
        safe["create"] = {k: v for k, v in params["create"].items() if k not in ("ssh_key", "script", "password")}
    try:
        t["result"] = _json.loads(t["result"]) if t.get("result") else None
    except ValueError:
        pass
    logs = tasks.get_logs(tid, after)
    t.update(params=safe, type_name=tasks.TYPE_NAME.get(t["type"], t["type"]), logs=logs,
             last_log_id=logs[-1]["id"] if logs else int(after or 0))
    return t


@router.post("/api/tasks/{tid}/stop")
def stop(tid: int):
    tasks.stop_task(tid)
    return {"ok": True}


@router.delete("/api/tasks/{tid}")
def del_task(tid: int):
    core.ex("DELETE FROM tasks WHERE id=? AND status!='running'", (tid,))
    if not core.q("SELECT 1 FROM tasks WHERE id=?", (tid,), one=True):
        core.ex("DELETE FROM task_logs WHERE task_id=?", (tid,))
    return {"ok": True}


# ---------------- 监控 ----------------
@router.get("/api/monitors")
def monitors():
    rows = core.q("SELECT m.*, a.name AS account_name, a.provider FROM monitors m LEFT JOIN accounts a ON a.id=m.account_id")
    return rows


@router.post("/api/monitors")
def add_monitor(body: dict = Body(...)):
    port = int(body.get("check_port") or 0)
    if port and not 0 < port < 65536:
        raise HTTPException(400, "端口无效")
    core.ex("INSERT INTO monitors(account_id,instance_id,region,kind,name,auto_start,last_state,check_port,auto_change_ip,public_ip) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,instance_id) DO UPDATE SET auto_start=excluded.auto_start, "
            "name=excluded.name, check_port=excluded.check_port, auto_change_ip=excluded.auto_change_ip, public_ip=excluded.public_ip",
            (body["account_id"], body["instance_id"], body.get("region"), body.get("kind", "vm"),
             body.get("name"), 1 if body.get("auto_start") else 0, body.get("state"), port,
             1 if body.get("auto_change_ip") and port else 0, body.get("public_ip")))
    return {"ok": True}


@router.delete("/api/monitors/{mid}")
def del_monitor(mid: int):
    core.ex("DELETE FROM monitors WHERE id=?", (mid,))
    return {"ok": True}


# ================= v1.3：流量守护 / 串口控制台 =================
def _guard_view(g, a=None):
    a = a or {}
    st = traffic_guard.status_of(g)
    return dict(g, account_name=a.get("name"), provider=a.get("provider"), mode=g.get("mode") or "monthly",
                direction=traffic_guard.direction_of(g), enabled=0 if g.get("enabled") == 0 else 1,
                status=st, status_text=traffic_guard.STATUS_TEXT[st],
                scope=traffic_guard.scope_text(g),
                resume_at_text=traffic_guard.fmt_ts(g["resume_at"]) if g.get("resume_at") else None)


@router.get("/api/traffic-guards")
def traffic_guards():
    names = {a["id"]: a for a in core.list_accounts()}
    return [_guard_view(g, names.get(g["account_id"])) for g in core.q("SELECT * FROM traffic_guards ORDER BY id")]


@router.post("/api/traffic-guards")
async def traffic_guard_save(body: dict = Body(...)):
    acc = need_acc(int(body["account_id"]))
    limit = float(body.get("limit_gb") or traffic_guard.DEFAULT_LIMIT[acc["provider"]])
    warn = int(body.get("warn_pct") or 80)
    if limit <= 0 or not 10 <= warn <= 99:
        raise HTTPException(400, "上限需大于 0，预警比例 10~99")
    action = "stop" if body.get("action") == "stop" else "notify"
    # v1.4：滚动窗口 / 方向 / 关机 M 小时 / 启停（都可省略，省略时与 v1.3 行为一致）
    mode = body.get("mode") or "monthly"
    if mode not in ("monthly", "rolling"):
        raise HTTPException(400, "mode 只能是 monthly 或 rolling")
    try:
        window = int(body["window_hours"]) if body.get("window_hours") not in (None, "") else 24
        shut = float(body["shutdown_hours"]) if body.get("shutdown_hours") not in (None, "") else 0.0
    except (TypeError, ValueError):
        raise HTTPException(400, "窗口小时数 / 关机小时数需为数字")
    if not 1 <= window <= 720:
        raise HTTPException(400, "滚动窗口 1~720 小时")
    if not 0 <= shut <= 720:
        raise HTTPException(400, "关机时长 0~720 小时")
    direction = body.get("direction") or ("both" if body.get("count_in") else "out")
    if direction not in traffic_guard.DIRECTIONS:
        raise HTTPException(400, "direction 只能是 out / in / both")
    enabled = 0 if body.get("enabled") in (False, 0, "0", "false") else 1
    core.ex("INSERT INTO traffic_guards(account_id,instance_id,region,kind,name,limit_gb,warn_pct,action,count_in,mode,window_hours,"
            "direction,shutdown_hours,enabled) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(account_id,instance_id) DO UPDATE SET limit_gb=excluded.limit_gb, warn_pct=excluded.warn_pct, "
            "action=excluded.action, count_in=excluded.count_in, name=excluded.name, region=excluded.region, checked_at=0, "
            "notified=CASE WHEN COALESCE(traffic_guards.mode,'monthly')=excluded.mode THEN traffic_guards.notified ELSE 0 END, "
            "mode=excluded.mode, window_hours=excluded.window_hours, direction=excluded.direction, "
            "shutdown_hours=excluded.shutdown_hours, enabled=excluded.enabled",
            (acc["id"], body["instance_id"], body.get("region"), body.get("kind") or "vm", body.get("name"), limit, warn, action,
             1 if direction == "both" else 0, mode, window, direction, shut if action == "stop" else 0, enabled))
    g = core.q("SELECT * FROM traffic_guards WHERE account_id=? AND instance_id=?", (acc["id"], body["instance_id"]), one=True)
    try:   # 立即读一次用量（不触发停机，避免刚设的上限立刻关机）
        await run(traffic_guard.check, g, False)
    except Exception as e:
        return {"ok": True, "id": g["id"], "warning": f"已保存，但读取流量失败：{str(e)[:150]}"}
    return {"ok": True, "id": g["id"], **core.q("SELECT last_gb, last_pct FROM traffic_guards WHERE id=?", (g["id"],), one=True)}


@router.patch("/api/traffic-guards/{gid}")
def traffic_guard_patch(gid: int, body: dict = Body(...)):
    """v1.4：启用 / 停用规则；cancel_resume 取消待执行的自动开机；reset_state 清除「已触发 / 开机失败」状态。"""
    g = core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True)
    if not g:
        raise HTTPException(404, "规则不存在")
    if "enabled" in body:
        core.ex("UPDATE traffic_guards SET enabled=?, checked_at=0 WHERE id=?", (1 if body["enabled"] else 0, gid))
    if body.get("cancel_resume") and g.get("state") == "tripped":
        core.ex("UPDATE traffic_guards SET resume_at=NULL, state_msg=? WHERE id=?", ("已取消自动开机", gid))
    if body.get("reset_state"):
        core.ex("UPDATE traffic_guards SET state='ok', resume_at=NULL, tripped_at=NULL, state_msg=NULL, checked_at=0 WHERE id=?", (gid,))
    a = core.get_account(g["account_id"]) or {}
    return _guard_view(core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True), a)


@router.post("/api/traffic-guards/{gid}/check")
async def traffic_guard_check(gid: int):
    g = core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True)
    if not g:
        raise HTTPException(404, "规则不存在")
    txt = await run(traffic_guard.check, g)
    if txt:
        await telegram.send(txt)
    g = core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True)
    return _guard_view(g, core.get_account(g["account_id"]))


@router.delete("/api/traffic-guards/{gid}")
def traffic_guard_del(gid: int):
    core.ex("DELETE FROM traffic_guards WHERE id=?", (gid,))
    return {"ok": True}
