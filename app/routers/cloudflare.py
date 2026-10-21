"""Cloudflare DNS 联动：Zone 列表、域名绑定。"""
from fastapi import APIRouter, Body, HTTPException

from .. import core, dns
from ..i18n import msg
from .common import need_acc, run

router = APIRouter()


# ---------------- Cloudflare DNS 联动 ----------------
@router.get("/api/cf/zones")
async def cf_zones():
    try:
        return await run(dns.cf_zones)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/api/dns-bindings")
def dns_bindings():
    return core.q("SELECT d.*, a.name AS account_name FROM dns_bindings d LEFT JOIN accounts a ON a.id=d.account_id ORDER BY d.id")


@router.post("/api/dns-bindings")
async def add_dns_binding(body: dict = Body(...)):
    need_acc(body["account_id"])
    rec = (body.get("record") or "").strip().lower().rstrip(".")
    zone_name = body.get("zone_name") or ""
    if not rec or not rec.endswith(zone_name):
        raise HTTPException(400, msg("err.record_zone", zone=zone_name))
    core.ex("INSERT INTO dns_bindings(account_id,instance_id,name,zone_id,zone_name,record,proxied,v4,v6) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(account_id,instance_id,record) DO UPDATE SET proxied=excluded.proxied, v4=excluded.v4, v6=excluded.v6",
            (body["account_id"], body["instance_id"], body.get("name"), body["zone_id"], zone_name, rec,
             1 if body.get("proxied") else 0, 1 if body.get("v4", True) else 0, 1 if body.get("v6") else 0))
    out = []
    if body.get("sync_now"):
        out = await run(dns.dns_sync, body["account_id"], body["instance_id"], body.get("ipv4"),
                        (body.get("ipv6") or [None])[0] if isinstance(body.get("ipv6"), list) else body.get("ipv6"))
    return {"ok": True, "dns": out}


@router.delete("/api/dns-bindings/{bid}")
def del_dns_binding(bid: int):
    core.ex("DELETE FROM dns_bindings WHERE id=?", (bid,))
    return {"ok": True}
