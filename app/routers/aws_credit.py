"""build 20：AWS 新账号 Free Tier Credit 卡片 + 一键完成活动。

GET  /api/accounts/{id}/aws/credits[?refresh=true]           计划类型 / 剩余 credit / 到期 + 5 个活动状态（缓存 5 分钟）
POST /api/accounts/{id}/aws/credits/activities/{activity}/run  执行一个活动（后台任务 aws_credit，需 confirm）
POST /api/accounts/{id}/aws/credits/run-all                    按顺序执行所有未完成活动（需 confirm）
POST /api/accounts/{id}/aws/credits/cleanup                    清理残留资源（需 confirm，可选 include_budget）

AWS 没有公开说明 API 操作是否计入活动完成：执行后只写「已执行，等待 AWS 识别」，状态以 ListAccountActivities 为准。
"""
import json
import time

from fastapi import APIRouter, Body, HTTPException, Request

from .. import core, security, services, tasks
from .common import client_ip, need_acc, run

router = APIRouter()

CREDITS_TTL = 300
_CREDITS = {}           # acc_id -> (ts, data)
ACT_KEYS = ("ec2", "budgets", "lambda", "rds", "bedrock")
ACT_LABEL = {"ec2": "EC2 启动实例", "budgets": "Budgets 成本预算", "lambda": "Lambda 网页应用", "rds": "RDS 数据库", "bedrock": "Bedrock 基础模型"}
STATUS_TEXT = {"NOT_STARTED": "未开始", "IN_PROGRESS": "进行中", "COMPLETED": "已完成", "EXPIRING": "即将过期"}
NOTES = [
    "AWS 没有公开说明用 API 完成的操作是否计入活动；面板执行后只表示「已执行，等待 AWS 识别」，不代表已获得奖励，以下方 AWS 返回的状态为准。",
    "活动状态可能需要几分钟到几小时才更新，可稍后点「刷新」。",
    "EC2 / RDS / Lambda / Bedrock 会产生极少量费用（RDS、EC2 只运行几分钟），从 Free Tier credit 中扣除；所有资源都打了标签 tricloud-credit=1，用完自动删除。",
]
HOLD = {"hold_minutes": (0, 60, 5), "keep_minutes": (0, 60, 10), "rds_hold_minutes": (0, 30, 1)}


def credits_invalidate(acc_id):
    _CREDITS.pop(acc_id, None)


def credits_store(acc_id, data):
    _CREDITS[acc_id] = (time.time(), data)


def _aws_mod():
    from ..providers import aws_credit     # 懒加载（会导入 botocore）
    return aws_credit


def fetch_state(prov):
    """调用 provider.credit_state 并把 AwsCreditError 变成 state=denied / not_applicable / unsupported / error。"""
    try:
        d = prov.credit_state()
        return dict(d, state="ok")
    except core.AwsCreditError as e:
        out = {"state": e.kind, "message": str(e)}
        if e.kind == "denied":
            out["permissions"] = list(_aws_mod().FREETIER_PERMS)
        return out
    except Exception as e:
        return {"state": "error", "message": "查询 Free Tier 状态失败：" + _aws_mod().friendly(e)}


def _credit_tasks(acc_id, limit=30):
    return core.q("SELECT * FROM tasks WHERE account_id=? AND type='aws_credit' ORDER BY id DESC LIMIT ?", (acc_id, limit))


def _jl(s):
    try:
        return json.loads(s) if s else {}
    except ValueError:
        return {}


def task_view(t):
    if not t:
        return None
    res = _jl(t.get("result"))
    p = _jl(t.get("params"))
    return {"id": t["id"], "status": t["status"], "message": t["message"], "updated": t["updated"],
            "activities": p.get("activities") or [], "current": res.get("current"), "steps": res.get("steps") or {}}


def _running(acc_id):
    return next((t for t in _credit_tasks(acc_id, 5) if t["status"] == "running"), None)


def build_view(acc_id, data, cached=False, age=0):
    m = _aws_mod()
    out = dict(data, cached=cached, age=age, notes=NOTES, keys=list(ACT_KEYS))
    tl = _credit_tasks(acc_id)
    aws_acts = data.get("activities") or []
    by_key = {}
    for a in aws_acts:
        if a.get("key") and a["key"] not in by_key:
            by_key[a["key"]] = a
    acts = []
    for k in ACT_KEYS:
        a = dict(by_key.get(k) or {"activity_id": None, "title": None, "status": None, "reward": None, "unit": "USD"})
        info = m.ACT_INFO[k]
        last = None
        for t in tl:
            v = task_view(t)
            if k in v["activities"] and (k in v["steps"] or t["status"] == "running"):
                last = v
                break
        step = (last or {}).get("steps", {}).get(k)
        a.update(key=k, label=ACT_LABEL[k], plan=info["plan"], note=info.get("note"), permissions=info["perms"],
                 status_text=STATUS_TEXT.get(a.get("status") or "", "AWS 未返回" if data.get("state") == "ok" else "未知"),
                 completed=a.get("status") == "COMPLETED", runnable=a.get("status") != "COMPLETED",
                 last_run=({"task_id": last["id"], "task_status": last["status"], **(step or {"status": "running" if last["status"] == "running" else "pending"})}
                           if last else None))
        acts.append(a)
    extra = [dict(a, label=a.get("title"), runnable=False, status_text=STATUS_TEXT.get(a.get("status") or "", a.get("status") or "-"))
             for a in aws_acts if not a.get("key")]
    rt = _running(acc_id)
    out.update(activities=acts, extra_activities=extra, running_task=task_view(rt),
               pending=[a["key"] for a in acts if a["runnable"]])
    return out


@router.get("/api/accounts/{acc_id}/aws/credits")
async def aws_credits(acc_id: int, refresh: bool = False):
    need_acc(acc_id, "aws")
    hit = _CREDITS.get(acc_id)
    if hit and not refresh and time.time() - hit[0] < CREDITS_TTL:
        return build_view(acc_id, hit[1], True, int(time.time() - hit[0]))
    data = await run(fetch_state, services.provider(acc_id))
    data["updated_at"] = services.now_local().strftime("%Y-%m-%d %H:%M:%S")
    if data["state"] != "error":
        credits_store(acc_id, data)
    return build_view(acc_id, data)


def _opts(body):
    o = {}
    for k, (lo, hi, dflt) in HOLD.items():
        v = body.get(k)
        if v in (None, ""):
            o[k] = dflt
            continue
        try:
            v = int(float(v))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{k} 需为数字")
        if not lo <= v <= hi:
            raise HTTPException(400, f"{k} 范围 {lo}–{hi} 分钟")
        o[k] = v
    o["keep_budget"] = body.get("keep_budget", True) not in (False, "false", 0, "0")
    return o


def _resolve(acc_id, activity):
    a = str(activity or "").strip()
    if a.lower() in ACT_KEYS:
        return a.lower()
    hit = _CREDITS.get(acc_id)
    for x in ((hit[1].get("activities") if hit else None) or []):
        if x.get("activity_id") == a and x.get("key"):
            return x["key"]
    raise HTTPException(400, f"未知活动：{a}（可选 {' / '.join(ACT_KEYS)}）")


async def _precheck(acc_id, key):
    try:
        return await run(services.provider(acc_id).credit_precheck, key)
    except core.AwsCreditError as e:
        raise HTTPException(400, f"{ACT_LABEL[key]}：{e}")
    except Exception as e:
        raise HTTPException(400, f"{ACT_LABEL[key]}：{_aws_mod().friendly(e, key)}")


def _audit(req, action, detail):
    try:
        security.audit(client_ip(req), getattr(req.state, "actor", "session"), action, detail)
    except Exception:
        pass


def _start(req, acc, keys, opts, action):
    tid = tasks.create_task("aws_credit", acc["id"], dict(opts, activities=keys, region=acc.get("region") or None,
                                                         name="新号 Credit · " + "、".join(ACT_LABEL[k] for k in keys)))
    _audit(req, action, f"账号 {acc['id']} 任务 #{tid}：" + "、".join(ACT_LABEL[k] for k in keys))
    return tid


@router.post("/api/accounts/{acc_id}/aws/credits/activities/{activity}/run")
async def aws_credit_run(req: Request, acc_id: int, activity: str, body: dict = Body(default={})):
    acc = need_acc(acc_id, "aws")
    key = _resolve(acc_id, activity)
    opts = _opts(body or {})
    if not body.get("confirm"):
        raise HTTPException(400, "会在账号里创建资源并从 credit 扣极少量费用，需确认")
    if _running(acc_id):
        raise HTTPException(409, "已有新号 Credit 任务在运行，请等它结束")
    hit = _CREDITS.get(acc_id)
    done = next((a for a in ((hit[1].get("activities") if hit else None) or []) if a.get("key") == key and a.get("status") == "COMPLETED"), None)
    if done and not body.get("force"):
        raise HTTPException(400, f"{ACT_LABEL[key]} 已完成，无需再执行")
    check = await _precheck(acc_id, key)
    tid = _start(req, acc, [key], opts, "aws-credit-run")
    return {"ok": True, "task_id": tid, "activity": key, "precheck": check,
            "message": f"已开始执行 {ACT_LABEL[key]}；完成后显示「已执行，等待 AWS 识别」，活动状态以 AWS 返回为准"}


@router.post("/api/accounts/{acc_id}/aws/credits/run-all")
async def aws_credit_run_all(req: Request, acc_id: int, body: dict = Body(default={})):
    acc = need_acc(acc_id, "aws")
    opts = _opts(body or {})
    if not body.get("confirm"):
        raise HTTPException(400, "会依次创建 EC2 / RDS / Lambda 等资源，从 credit 扣少量费用（RDS、EC2 运行数分钟，金额极小），需确认")
    if _running(acc_id):
        raise HTTPException(409, "已有新号 Credit 任务在运行，请等它结束")
    hit = _CREDITS.get(acc_id)
    data = hit[1] if hit else None
    if data is None:
        data = await run(fetch_state, services.provider(acc_id))
        if data["state"] != "error":
            credits_store(acc_id, data)
    if data.get("state") == "ok" and data.get("activities"):
        st = {a["key"]: a.get("status") for a in data["activities"] if a.get("key")}
        keys = [k for k in ACT_KEYS if st.get(k) != "COMPLETED"]
    else:
        keys = list(ACT_KEYS)        # 读不到状态（如缺 freetier 权限）时全部执行
    if body.get("activities"):
        want = {str(x).lower() for x in body["activities"]}
        keys = [k for k in keys if k in want]
    if not keys:
        raise HTTPException(400, "全部活动都已完成，无需执行")
    skipped = []
    ok_keys = []
    for k in keys:
        try:
            await _precheck(acc_id, k)
            ok_keys.append(k)
        except HTTPException as e:
            skipped.append({"activity": k, "reason": e.detail})
    if not ok_keys:
        raise HTTPException(400, "所有待执行活动都没有通过权限检查：" + "；".join(s["reason"] for s in skipped))
    tid = _start(req, acc, ok_keys, opts, "aws-credit-run-all")
    return {"ok": True, "task_id": tid, "activities": ok_keys, "skipped": skipped,
            "message": f"已开始依次执行 {len(ok_keys)} 个活动" + (f"，{len(skipped)} 个因权限不足跳过" if skipped else "")}


@router.post("/api/accounts/{acc_id}/aws/credits/cleanup")
async def aws_credit_cleanup(req: Request, acc_id: int, body: dict = Body(default={})):
    acc = need_acc(acc_id, "aws")
    if not body.get("confirm"):
        raise HTTPException(400, "清理会删除带 tricloud-credit=1 标签的 EC2 / RDS 以及 Lambda 函数与角色，需确认")
    if _running(acc_id):
        raise HTTPException(409, "新号 Credit 任务仍在运行，请先在任务里停止（停止后会自动清理）")
    regions = [acc.get("region")] if acc.get("region") else []
    for t in _credit_tasks(acc_id):
        rg = _jl(t.get("params")).get("region")
        if rg:
            regions.append(rg)
    if body.get("region"):
        regions.append(str(body["region"]))
    regions = list(dict.fromkeys(r for r in regions if r)) or None
    try:
        r = await run(services.provider(acc_id).credit_cleanup, regions, bool(body.get("include_budget")))
    except core.AwsCreditError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "清理失败：" + _aws_mod().friendly(e))
    _audit(req, "aws-credit-cleanup", f"账号 {acc_id} 清理 {len(r['deleted'])} 项" + (f"，失败 {len(r['errors'])} 项" if r["errors"] else "")
           + (" · " + "、".join(f"{d['type']}:{d['id']}" for d in r["deleted"])[:300] if r["deleted"] else ""))
    return r
