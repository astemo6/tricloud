"""网络工具：TCP 连通检测、换 IP 网段（支持 ! 排除）、IP 质量检测（原 extras.py 拆分）。"""
import socket
import time

import httpx

from . import core

# ---------------- TCP 连通检测 ----------------
def tcp_alive(host, port=22, timeout=4, tries=2):
    for _ in range(tries):
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except OSError:
            time.sleep(1)
    return False


# ---------------- v1.4：换 IP 网段（支持 ! 排除） ----------------
def split_cidrs(cidrs):
    """把 ["129.146.0.0/16", "!129.146.10.0/24"] 拆成 (包含网段, 排除网段)。非法网段抛 ValueError。
    也接受逗号/换行分隔的字符串。只有排除网段时 = 任意 IP 只要不落在排除网段内即可。"""
    import ipaddress
    if isinstance(cidrs, str):
        cidrs = cidrs.replace("，", ",").replace("\n", ",").split(",")
    inc, exc = [], []
    for c in cidrs or []:
        c = str(c or "").strip()
        if not c:
            continue
        neg = c.startswith("!")
        c = c[1:].strip() if neg else c
        if not c:
            raise ValueError("! 后面缺少网段")
        (exc if neg else inc).append(ipaddress.ip_network(c, strict=False))
    return inc, exc


def ip_matches(ip, cidrs):
    """新 IP 是否满足网段要求：落在任一包含网段内（没有包含网段则不限），且不在任何排除网段内。"""
    import ipaddress
    inc, exc = split_cidrs(cidrs)
    if not ip:
        return False
    a = ipaddress.ip_address(ip)
    return (not inc or any(a in n for n in inc if n.version == a.version)) and not any(a in n for n in exc if n.version == a.version)


# ---------------- v1.6：IP 质量检测 ----------------
# 风险分来自 proxycheck.io（0~100，越低越干净；无 Key 每天 100 次，设置里可填免费 Key 提到 1000 次），
# 归属 / 机房标记来自 ip-api.com（免费、非商用）。只发送要检测的公网 IP，不发送任何凭证。
QUALITY_SOURCES = "proxycheck.io（风险分）+ ip-api.com（归属地 / ISP）"


def ip_quality(ip, timeout=8):
    import ipaddress
    ipaddress.ip_address(ip)   # 校验，非法直接抛 ValueError
    res = {"ip": ip, "risk": None, "type": None, "proxy": None, "country": None, "country_code": None,
           "isp": None, "asn": None, "hosting": None, "source": QUALITY_SOURCES}
    key = core.get_secret_setting("proxycheck_key") or ""
    try:
        r = httpx.get(f"https://proxycheck.io/v2/{ip}", params={"vpn": 1, "risk": 1, "asn": 1, **({"key": key} if key else {})},
                      timeout=timeout).json()
        d = r.get(ip) or {}
        if r.get("status") in ("ok", "warning") and d:
            res.update(risk=int(d["risk"]) if str(d.get("risk", "")).isdigit() else None, type=d.get("type"),
                       proxy=d.get("proxy") == "yes", country=d.get("country"), country_code=d.get("isocode"),
                       isp=d.get("provider") or d.get("organisation"), asn=d.get("asn"))
        elif r.get("message"):
            res["error"] = "proxycheck：" + str(r["message"])[:120]
    except Exception as e:
        res["error"] = f"proxycheck 查询失败：{str(e)[:80]}"
    try:
        g = httpx.get(f"http://ip-api.com/json/{ip}", params={"fields": "status,country,countryCode,isp,org,as,proxy,hosting"},
                      timeout=timeout).json()
        if g.get("status") == "success":
            res["country"] = res["country"] or g.get("country")
            res["country_code"] = res["country_code"] or g.get("countryCode")
            res["isp"] = res["isp"] or g.get("isp")
            res["asn"] = res["asn"] or (g.get("as") or "").split(" ")[0] or None
            res["org"] = g.get("org")
            res["hosting"] = bool(g.get("hosting"))
    except Exception:
        pass
    return res


def quality_ok(q, max_risk=None, country=None):
    """换 IP 的质量条件：风险分 ≤ max_risk；country（如 "US,JP"）非空时归属国家需在其中。查询失败视为不合格。"""
    why = []
    if max_risk not in (None, ""):
        if q.get("risk") is None:
            why.append("风险分查询失败")
        elif q["risk"] > int(max_risk):
            why.append(f"风险分 {q['risk']} > {int(max_risk)}")
    cc = [c.strip().upper() for c in str(country or "").replace("，", ",").split(",") if c.strip()]
    if cc and (q.get("country_code") or "").upper() not in cc:
        why.append(f"归属 {q.get('country_code') or '未知'} 不在 {','.join(cc)}")
    return not why, "；".join(why)
