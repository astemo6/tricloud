"""TriCloud 面板入口：OCI / AWS / Azure 三合一管理。
这里只负责创建 app、生命周期（后台循环）、认证 / 审计中间件、异常处理，以及按顺序挂载 app/routers 下的各功能路由。"""
import asyncio
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import core, security, tasks, telegram
from .routers import (accounts, auth, aws, aws_credit, azure, billing, cloudflare, guard_agent, guard_health, instances, oci, onedrive, pages,
                      settings, tasks_monitors)
from .routers import security as security_routes
from .routers.common import VERSION, _token, client_ip
from .routers.pages import WEB_DIR, StaticWithModules


@asynccontextmanager
async def lifespan(app):
    core.init_db()
    core.fernet()
    core.ensure_password()
    r = tasks.recover_on_startup()
    if r["resumed"] or r["interrupted"]:
        print(f"[tricloud] 重启恢复：抢机任务续抢 {r['resumed']} 个，其他任务标记中断 {r['interrupted']} 个", flush=True)
    bg = [asyncio.create_task(f()) for f in (tasks.task_loop, tasks.monitor_loop, tasks.schedule_loop, telegram.poll_loop)]
    yield
    for t in bg:
        t.cancel()


app = FastAPI(title="TriCloud", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
PUBLIC = {"/api/login", "/api/health",
          "/api/guard-agent/state", "/api/guard-agent/install.sh", "/api/guard-agent/uninstall.sh"}   # agent 凭守护专属 token / 通用卸载脚本
AUDIT_SKIP = {"/api/logout", "/api/onedrive/bind/poll",   # 设备码轮询每几秒一次，绑定成功由路由自己写 onedrive-bind
              "/api/guard-agent/state"}                  # build 22：agent 每 5 分钟 POST 心跳 + 流量明细，不进审计
AGENT_RESET_RE = re.compile(r"^/api/traffic-guards/\d+/agent/reset$")
AUDIT_SKIP_OK = {("DELETE", "/api/audit")}   # 清空审计成功时路由自己写了 audit-clear，中间件不再追加一条


@app.middleware("http")
async def auth_mw(req: Request, call_next):
    path = req.url.path
    actor = "session"
    if path.startswith("/api/") and path not in PUBLIC:
        tok = _token(req)
        if core.check_session(tok):
            pass
        elif tok and (tk := security.check_api_token(tok, req.method)):
            # v1.5：从旧版迁移来的 Token（不以 tc_ 开头）在审计里只记 id，不记 Token 片段
            actor = "api_token:" + (tok[:10] if tok.startswith("tc_") else f"legacy#{tk['id']}")
            # API Token 不能管理安全设置
            if path.startswith(("/api/2fa", "/api/tokens", "/api/password", "/api/backup", "/api/restore", "/api/secrets")) \
                    or (path == "/api/audit" and req.method == "DELETE") \
                    or (path.startswith("/api/onedrive") and req.method != "GET" and path != "/api/onedrive/backup") \
                    or (req.method != "GET" and AGENT_RESET_RE.match(path)):
                # Token 不能抹掉审计痕迹；OneDrive 只能看状态 / 列表和「立即备份」，不能绑定（防止绑到别人的网盘）、改密码、恢复、解绑；
                # build 22：Token 不能重置流量守护 agent token（GET /agent 也不返回带 token 的安装命令）
                return JSONResponse({"detail": "API Token 无权访问此接口"}, status_code=403)
        else:
            return JSONResponse({"detail": "未登录"}, status_code=401)
    req.state.actor = actor
    resp = await call_next(req)
    if path.startswith("/api/") and req.method != "GET" and path not in AUDIT_SKIP \
            and not ((req.method, path) in AUDIT_SKIP_OK and resp.status_code < 400):
        try:
            security.audit(client_ip(req), actor if path != "/api/login" else "-", f"{req.method} {path}",
                           f"HTTP {resp.status_code}")
        except Exception:
            pass
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@app.exception_handler(core.LightsailRegionError)
async def ls_region_err(req, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(Exception)
async def err(req, exc):
    msg = str(exc)
    lm = re.search(r"https://lightsail\.([a-z0-9-]+)\.amazonaws\.com", msg)
    if type(exc).__name__ == "EndpointConnectionError" and lm:   # 兜底：区域表没覆盖到的 Lightsail 端点连不上
        from .providers.aws_provider import ls_region_msg
        return JSONResponse({"detail": ls_region_msg(lm.group(1))}, status_code=400)
    m = re.search(r"\((UnauthorizedOperation|AccessDenied\w*|AuthorizationFailed|NotAuthorized\w*)\)", msg) or \
        re.search(r"'code': '(NotAuthorizedOrNotFound|NotAuthenticated)'", msg)
    if m:   # 云账号权限不足：不是面板故障，给出缺哪个权限
        act = re.search(r"perform:? ([\w:.\-/]+)", msg) or re.search(r"action '([\w:.\-/]+)'", msg)
        tip = f"缺少 {act.group(1)} 权限" if act else "请检查该账号的 IAM / 角色授权"
        return JSONResponse({"detail": f"云账号权限不足（{m.group(1)}）：{tip}"}, status_code=403)
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


# 注册顺序 = 匹配顺序。各模块内部的路径互不冲突；静态页与 /static 挂载放最后。
ROUTERS = (auth, accounts, instances, oci, aws, aws_credit, azure, billing, tasks_monitors, settings, security_routes, onedrive, guard_agent,
           cloudflare, guard_health, pages)
for _m in ROUTERS:
    app.include_router(_m.router)
app.mount("/static", StaticWithModules(directory=WEB_DIR), name="static")
