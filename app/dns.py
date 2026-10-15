"""Cloudflare DNS 联动：Zone 列表、记录增改、实例 IP 变化后同步（原 extras.py 拆分）。"""
import httpx

from . import core

# ---------------- Cloudflare DNS ----------------
CF_API = "https://api.cloudflare.com/client/v4"


def _cf_headers():
    tok = core.get_secret_setting("cf_token")
    if not tok:
        raise RuntimeError("未配置 Cloudflare API Token（设置页）")
    return {"Authorization": f"Bearer {tok}"}


def _cf(method, path, **kw):
    r = httpx.request(method, CF_API + path, headers=_cf_headers(), timeout=20, **kw)
    j = r.json()
    if not j.get("success"):
        raise RuntimeError("Cloudflare: " + "; ".join(e.get("message", "") for e in j.get("errors", [])))
    return j["result"]


def cf_zones():
    return [{"id": z["id"], "name": z["name"]} for z in _cf("GET", "/zones", params={"per_page": 50})]


def cf_upsert(zone_id, name, rtype, content, proxied=False):
    recs = _cf("GET", f"/zones/{zone_id}/dns_records", params={"type": rtype, "name": name})
    body = {"type": rtype, "name": name, "content": content, "ttl": 60 if not proxied else 1, "proxied": bool(proxied)}
    if recs:
        _cf("PUT", f"/zones/{zone_id}/dns_records/{recs[0]['id']}", json=body)
        return f"{name} {rtype} → {content}（已更新）"
    _cf("POST", f"/zones/{zone_id}/dns_records", json=body)
    return f"{name} {rtype} → {content}（已创建）"


def dns_sync(acc_id, inst_id, ipv4=None, ipv6=None):
    """实例 IP 变化后，按绑定更新 Cloudflare 记录。返回说明文本列表；未绑定返回空。"""
    out = []
    for b in core.q("SELECT * FROM dns_bindings WHERE account_id=? AND instance_id=?", (acc_id, inst_id)):
        try:
            if not b["zone_id"]:   # v1.5：从旧版迁移来的绑定只有 zone_name，首次同步时查出 zone_id 并保存
                z = _cf("GET", "/zones", params={"name": b["zone_name"]})
                if not z:
                    raise RuntimeError(f"Cloudflare 中找不到域名 {b['zone_name']}")
                b["zone_id"] = z[0]["id"]
                core.ex("UPDATE dns_bindings SET zone_id=? WHERE id=?", (b["zone_id"], b["id"]))
            if ipv4 and b["v4"]:
                out.append(cf_upsert(b["zone_id"], b["record"], "A", ipv4, b["proxied"]))
            if ipv6 and b["v6"]:
                out.append(cf_upsert(b["zone_id"], b["record"], "AAAA", ipv6, b["proxied"]))
        except Exception as e:
            out.append(f"DNS 更新失败 {b['record']}: {str(e)[:120]}")
    return out
