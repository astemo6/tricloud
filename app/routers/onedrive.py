"""build 21 OneDrive 定期备份：状态 / 设置 / 设备码绑定 / 立即备份 / 备份列表 / 恢复 / 解绑。
API Token 只能 GET 状态与列表、调用立即备份；绑定、设置、恢复、解绑都返回 403（见 main.py 中间件）。"""
from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request

from .. import core, onedrive, security, services, tasks
from .common import client_ip, run

router = APIRouter()


async def _call(fn, *a, **kw):
    try:
        return await run(fn, *a, **kw)
    except onedrive.ODError as e:
        raise HTTPException(400, str(e))


def running_task():
    r = core.q("SELECT id FROM tasks WHERE type='onedrive_backup' AND status='running' ORDER BY id DESC LIMIT 1", one=True)
    return r["id"] if r else None


def start_backup(trigger="manual"):
    """创建一个 onedrive_backup 任务（同时只允许一个）。返回任务 id；已在运行则抛 409。"""
    if running_task():
        raise HTTPException(409, "已有 OneDrive 备份在运行，请等它结束")
    if not onedrive.bound():
        raise HTTPException(400, "尚未绑定 OneDrive")
    if not onedrive.password():
        raise HTTPException(400, "尚未设置备份密码")
    return tasks.create_task("onedrive_backup", 0, {"name": "OneDrive 备份", "trigger": trigger})


@router.get("/api/onedrive")
def od_status():
    v = onedrive.status_view()
    v["running_task_id"] = running_task()
    return v


@router.post("/api/onedrive/config")
async def od_config(body: dict = Body(...)):
    changed = await _call(onedrive.save_config, body)
    v = od_status()
    v["changed"] = changed
    return v


@router.post("/api/onedrive/schedule/preview")
async def od_schedule_preview(body: dict = Body(...)):
    """build 23：不保存，预览计划描述与接下来 3 次备份时间；非法配置 400（友好提示）。"""
    return await _call(onedrive.preview, body)


@router.post("/api/onedrive/bind")
async def od_bind():
    return await _call(onedrive.bind_start)


@router.post("/api/onedrive/bind/poll")
async def od_bind_poll(req: Request):
    r = await _call(onedrive.bind_poll)
    if r.get("status") == "ok" and r.get("account") is not None:
        security.audit(client_ip(req), getattr(req.state, "actor", "session"), "onedrive-bind",
                       "绑定 OneDrive" + (f"（{r['account'].get('folder')}）" if r["account"].get("folder") else ""))
    return r


@router.delete("/api/onedrive/bind")
def od_unbind(confirm: bool = False, pending_only: bool = False):
    if pending_only:
        onedrive.bind_cancel()
        return {"ok": True}
    if not confirm:
        raise HTTPException(400, "解绑会删除本地保存的 OneDrive 授权（OneDrive 上的备份文件不会删除），需 confirm=true")
    if running_task():
        raise HTTPException(409, "OneDrive 备份正在运行，请等它结束再解绑")
    onedrive.unbind()
    return {"ok": True}


@router.post("/api/onedrive/backup")
def od_backup_now():
    tid = start_backup("manual")
    return {"ok": True, "task_id": tid, "message": f"已开始备份（任务 #{tid}）"}


@router.get("/api/onedrive/backups")
async def od_list():
    if not onedrive.bound():
        raise HTTPException(400, "尚未绑定 OneDrive")
    items = await _call(onedrive.list_backups)
    return {"items": items, "keep": onedrive.cfg()["keep"]}


@router.post("/api/onedrive/restore")
async def od_restore(req: Request, bg: BackgroundTasks, body: dict = Body(...)):
    if not body.get("confirm"):
        raise HTTPException(400, "恢复会用备份覆盖当前全部数据（账号、设置、任务），需 confirm")
    item = str(body.get("item_id") or "").strip()
    if not item:
        raise HTTPException(400, "缺少参数：item_id")
    if not body.get("password"):
        raise HTTPException(400, "请输入备份密码")
    if not onedrive.bound():
        raise HTTPException(400, "尚未绑定 OneDrive")
    if running_task():
        raise HTTPException(409, "OneDrive 备份正在运行，请等它结束再恢复")
    r = await _call(onedrive.restore, item, str(body["password"]))
    services._cache.clear()
    core.drop_all_sessions()   # 备份里的旧会话一律作废，所有设备重新登录
    security.audit(client_ip(req), getattr(req.state, "actor", "session"), "onedrive-restore",
                   f"从 {r['name']} 恢复；恢复前快照 {r['snapshot'].rsplit('/', 1)[-1]}")
    restart = onedrive.restart_enabled()
    if restart:
        bg.add_task(onedrive.schedule_restart)
    return {"ok": True, "name": r["name"], "snapshot": r["snapshot"].rsplit("/", 1)[-1], "restart": restart,
            "message": "已恢复，" + ("面板将自动重启（约 10 秒），" if restart else "") + "请重新登录"}
