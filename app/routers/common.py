"""路由共用的小工具：认证取 Token / 客户端 IP、线程池执行、免费额度护栏、账号校验、参数解析。"""
import asyncio
import os

from fastapi import HTTPException, Request

from .. import cloudinit, core, guard, services


VERSION = "1.6.0"


REQUIRED = {
    "oci": ["user", "tenancy", "fingerprint", "key_content", "region"],
    "aws": ["access_key", "secret_key", "region"],
    "azure": ["tenant_id", "client_id", "client_secret", "subscription_id"],
}


def _token(req: Request):
    auth = req.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return req.cookies.get("tc_session")


def client_ip(req: Request):
    if os.environ.get("TRUST_PROXY", "false").lower() == "true":
        for h in ("cf-connecting-ip", "x-real-ip"):
            if req.headers.get(h):
                return req.headers[h]
        xff = req.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return req.client.host if req.client else "unknown"


def run(fn, *a, **kw):
    return asyncio.to_thread(fn, *a, **kw)


async def guarded(acc_id, op, body, region=None):
    """免费额度护栏：可能超额时返回 409 + 警告列表，前端二次确认后带 confirm_overage 重发。"""
    if body.get("confirm_overage") or core.get_setting("free_guard", True) is False:
        return
    w = await run(guard.check, acc_id, op, body, region)
    if w:
        raise HTTPException(409, {"msg": "可能超出免费额度", "guard": w})


def need_acc(acc_id, provider=None):
    acc = core.get_account(acc_id)
    if not acc:
        raise HTTPException(404, "账号不存在")
    if provider and acc["provider"] != provider:
        raise HTTPException(400, f"该接口仅支持 {provider}")
    return acc


def _valid_date(v, field):
    if v in (None, ""):
        return None
    import datetime as _dt
    try:
        return _dt.date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise HTTPException(400, f"{field} 日期格式应为 YYYY-MM-DD")


def _num_or_none(v, field, minimum=0.0):
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field} 需为数字")
    if x < minimum:
        raise HTTPException(400, f"{field} 不能小于 {minimum:g}")
    return x


def _truthy(v, default=True):
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(v)


def _public_guard(direction, protocol, cidr, port, confirmed):
    """入站来源为 0.0.0.0/0 或 ::/0：不允许放行全部端口；单条规则需二次确认（409）。"""
    if direction != "ingress" or str(cidr or "").replace(" ", "") not in PUBLIC_CIDRS:
        return
    from ..providers.oci_provider import OCIProvider
    try:
        ranges = OCIProvider.parse_ports(port) if protocol in ("tcp", "udp") and str(port or "").strip() else []
    except ValueError as e:
        raise HTTPException(400, str(e))
    if protocol == "all" or (protocol in ("tcp", "udp") and (not ranges or any(a <= 1 and b >= 65535 for a, b in ranges))):
        raise HTTPException(400, "不支持对 0.0.0.0/0（或 ::/0）放行全部端口，请填写具体端口")
    if not confirmed:
        raise HTTPException(409, {"msg": "来源为 0.0.0.0/0：将对整个互联网开放", "public_warning": True})


def _created(acc_id, r):
    """创建成功后：随机 root 密码加密留存，前端只显示一次。"""
    if r.get("password"):
        cloudinit.save_instance_secret(acc_id, r["id"], r["name"], r["username"], r["password"])
    return r


# ---------------- OCI 安全组：按规则内容增删、批量端口、对公网放行二次确认 ----------------
PUBLIC_CIDRS = ("0.0.0.0/0", "::/0")


async def call(fn, *a, **kw):
    try:
        return await run(fn, *a, **kw)
    except (RuntimeError, ValueError, KeyError) as e:
        raise HTTPException(400, str(e).strip("'\"")[:400])


def P(acc_id, region=None):
    return services.provider(acc_id, region)


def _req(body, *keys):
    for k in keys:
        if not str(body.get(k) or "").strip():
            raise HTTPException(400, f"缺少参数：{k}")
