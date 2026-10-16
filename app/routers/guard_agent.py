"""build 22 流量守护 agent 接口：「推送并限速」+ 按端口 / 服务的流量明细。
- 公开（无需登录，main.PUBLIC）：GET|POST /api/guard-agent/state（凭守护专属 token：返回本守护是否限速 + 速率 + 是否统计流量明细，
  顺带记心跳；POST 正文是流量明细增量，只写这条守护自己的数据）、
  GET /api/guard-agent/install.sh?token=（token 有效才返回安装脚本）、GET /api/guard-agent/uninstall.sh（通用卸载脚本）。
- 需登录：GET /api/traffic-guards/{gid}/agent（安装 / 卸载命令 + 在线状态）、POST /api/traffic-guards/{gid}/agent/reset（重置 token）。
面板只回答 agent 的拉取，不会远程在实例上执行任何命令。"""
import asyncio
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .. import core, port_traffic, traffic_guard
from .common import client_ip

router = APIRouter()
SH = "text/x-shellscript; charset=utf-8"
NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}
BASE_RE = re.compile(r"^https?://[A-Za-z0-9.\-:\[\]]+(/[A-Za-z0-9._~/-]*)?$")


def _token_of(req: Request):
    return (req.headers.get("x-tricloud-guard-token") or req.query_params.get("token") or "").strip()


def _base(req: Request, given=None):
    """安装命令里的面板地址：优先用客户端传来的（Web 的 location.origin / App 的服务器地址），否则按请求头推断。"""
    if given and BASE_RE.match(given.strip().rstrip("/")):
        return given.strip().rstrip("/")
    proto = (req.headers.get("x-forwarded-proto") or req.url.scheme or "https").split(",")[0].strip()
    host = (req.headers.get("x-forwarded-host") or req.headers.get("host") or req.url.netloc).split(",")[0].strip()
    b = f"{proto}://{host}"
    if not BASE_RE.match(b):
        raise HTTPException(400, "无法确定面板地址，请传 base 参数")
    return b


def _state_resp(st, format):
    if format == "env":
        txt = (f"throttle={1 if st['throttle'] else 0}\nrate_kbit={st['rate_kbit']}\nacct={1 if st['acct'] else 0}\n"
               f"interval={st['interval']}\n" + (f"acct_ok={st['acct_ok']}\n" if "acct_ok" in st else ""))
        return PlainTextResponse(txt, headers=NO_STORE)
    return JSONResponse(st, headers=NO_STORE)


@router.get("/api/guard-agent/state")
def agent_state(req: Request, format: str = "json"):
    g = traffic_guard.guard_by_token(_token_of(req))
    if not g:
        return JSONResponse({"detail": "token 无效"}, status_code=401, headers=NO_STORE)
    return _state_resp(traffic_guard.agent_heartbeat(g, dict(req.query_params)), format)


@router.post("/api/guard-agent/state")
async def agent_report(req: Request, format: str = "json"):
    """心跳 + 流量明细增量（正文每行：协议 端口 进程名 入站字节 出站字节）。守护由 token 反查，agent 不能指定写哪条守护。"""
    g = await asyncio.to_thread(traffic_guard.guard_by_token, _token_of(req))
    if not g:
        return JSONResponse({"detail": "token 无效"}, status_code=401, headers=NO_STORE)
    body = await req.body()
    if len(body) > port_traffic.MAX_BODY:
        return JSONResponse({"detail": "上报内容过大"}, status_code=413, headers=NO_STORE)
    rows, bad = port_traffic.parse_report(body.decode("utf-8", "replace"))

    def work():
        st = traffic_guard.agent_heartbeat(g, dict(req.query_params))
        if rows and g.get("acct_enabled"):   # 面板里关了流量明细就不再记录
            st["acct_ok"] = port_traffic.record(g["id"], rows)
        elif rows:
            st["acct_ok"] = 0
        if bad:
            st["acct_bad"] = bad
        return st
    return _state_resp(await asyncio.to_thread(work), format)


@router.get("/api/guard-agent/install.sh")
def agent_install(req: Request, token: str = "", base: str = ""):
    g = traffic_guard.guard_by_token(token.strip())
    if not g:
        return PlainTextResponse("echo 'TriCloud: token 无效（守护已删除或 token 已重置），请回面板复制新的安装命令' >&2; exit 1\n",
                                 status_code=404, media_type=SH, headers=NO_STORE)
    try:
        sh = traffic_guard.render_install(_base(req, base or None), token.strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    from .. import security
    security.audit(client_ip(req), "guard-agent", "guard-agent-install", f"守护 #{g['id']} 下载安装脚本")
    return PlainTextResponse(sh, media_type=SH, headers=NO_STORE)


@router.get("/api/guard-agent/uninstall.sh")
def agent_uninstall():
    return PlainTextResponse(traffic_guard.uninstall_script(), media_type=SH, headers=NO_STORE)


def _need_guard(gid):
    g = core.q("SELECT * FROM traffic_guards WHERE id=?", (gid,), one=True)
    if not g:
        raise HTTPException(404, "规则不存在")
    return g


def _agent_payload(req, g, base, token):
    cmds = traffic_guard.install_commands(_base(req, base), token)
    g = core.q("SELECT * FROM traffic_guards WHERE id=?", (g["id"],), one=True)
    return {"guard_id": g["id"], "commands": cmds, "agent": traffic_guard.agent_view(g), "throttled": bool(g.get("throttled")),
            "throttle_mbps": traffic_guard.throttle_mbps(g), "poll_secs": traffic_guard.AGENT_POLL_SECS,
            "offline_secs": traffic_guard.AGENT_OFFLINE_SECS}


def _is_api_token(req):
    return str(getattr(req.state, "actor", "")).startswith("api_token")


@router.get("/api/traffic-guards/{gid}/agent")
def guard_agent_info(gid: int, req: Request, base: str = ""):
    g = _need_guard(gid)
    if _is_api_token(req):   # 安装命令里带 agent token，API Token 只能看状态
        out = _agent_payload(req, g, base, "tg_" + "x" * 43)
        out.update(commands=None, commands_hidden=True)
        return out
    return _agent_payload(req, g, base, traffic_guard.agent_token(gid))


@router.post("/api/traffic-guards/{gid}/agent/reset")
def guard_agent_reset(gid: int, req: Request, base: str = ""):
    g = _need_guard(gid)
    out = _agent_payload(req, g, base, traffic_guard.agent_token(gid, reset=True))
    from .. import security
    security.audit(client_ip(req), getattr(req.state, "actor", "session"), "guard-agent-reset", f"守护 #{gid} 重置 agent token")
    return out


@router.get("/api/traffic-guards/{gid}/ports")
def guard_ports(gid: int, range: str = "today", limit: int = 20):
    g = _need_guard(gid)
    try:
        t = port_traffic.top(gid, range, limit)
    except ValueError as e:
        raise HTTPException(400, str(e))
    t.update(guard_id=gid, acct_enabled=bool(g.get("acct_enabled")), agent=traffic_guard.agent_view(g),
             retain_days=port_traffic.RETAIN_DAYS)
    return t
