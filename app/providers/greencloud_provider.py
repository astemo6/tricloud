"""GreenCloud（绿云）KVM 适配：SolusVM v1 客户 API。

凭证: {"api_url": "https://cp.greencloudvps.com", "servers": [{"name": "洛杉矶", "key": "...", "hash": "..."}]}
- 每台 VPS 在绿云面板里有自己的一组 API key + hash（SolusVM「API」页生成），一个账号可以放多台。
- 接口：POST {api_url}/api/client/command.php，参数 key / hash / action（boot / reboot / shutdown / status / info）。
- 返回是类 XML 片段：<status>success</status><statusmsg>online</statusmsg><vmstat>online</vmstat>
  <ipaddr>203.0.113.10,...</ipaddr><bw>total,used,free,percent</bw>（字节；KVM 下 hdd / mem 可能为空），用正则容错解析。
- 只能开机、关机、重启、查状态和流量；终止、换 IP、改配置、改名、开放端口等 SolusVM 客户 API 都不提供。
- SSL 证书校验始终开启；key / hash 只在请求体里发送（POST），不会出现在 URL / 日志里。

可拆卸：绿云的全部后端逻辑都在本文件；其他文件只有标了 `# greencloud` 的少量钩子（grep -rn greencloud app/）。
设置 enable_greencloud=false 时不注册本 provider，绿云账号在列表 / 侧栏 / TG / 流量守护 / 监控里全部隐藏（数据保留）。
彻底删除的步骤见 docs/FEATURES.md「移除绿云」。
"""
import concurrent.futures
import hashlib
import html
import re

import httpx
from fastapi import HTTPException

DEFAULT_API_URL = "https://cp.greencloudvps.com"
API_PATH = "/api/client/command.php"
ACTIONS = {"start": "boot", "stop": "shutdown", "reboot": "reboot"}   # 面板动作 -> SolusVM action
UNSUPPORTED_MSG = "绿云 API 不支持该操作（只能开机、关机、重启、查流量）"
MAX_SERVERS = 50
TIMEOUT = 20
_TAG = re.compile(r"<\s*([A-Za-z_][\w\-]*)\s*>(.*?)<\s*/\s*\1\s*>", re.S)
_SPLIT = re.compile(r"[\s,，;；]+")


class _HttpErr(HTTPException):
    """带 HTTP 状态码的异常：在路由里直接变成对应响应，在后台任务里 str(e) 就是提示文字。"""
    status = 400

    def __init__(self, msg):
        super().__init__(self.status, str(msg))

    def __str__(self):
        return str(self.detail)


class Unsupported(_HttpErr):
    """绿云 API 不提供的操作（HTTP 400）。"""


class BadInput(_HttpErr):
    """用户填写的绿云凭证有问题（HTTP 400）。"""


class GreenCloudError(_HttpErr):
    """SolusVM 接口报错 / 连接失败（HTTP 502；信息里不含 key、hash）。"""
    status = 502


def unsupported(what=""):
    return Unsupported(f"绿云 API 不支持{what or '该操作'}（只能开机、关机、重启、查流量）")


# ---------------- 凭证 ----------------
def endpoint(api_url):
    """面板地址 -> command.php 完整地址。可填 https://host、https://host:5656、…/api/client 或完整的 …/command.php。"""
    u = str(api_url or "").strip() or DEFAULT_API_URL
    if not re.match(r"^[a-z][a-z0-9+.\-]*://", u, re.I):
        u = "https://" + u
    if not u.lower().startswith("https://"):
        raise ValueError("面板地址必须以 https:// 开头（key / hash 不能明文传输）")
    u = u.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if not re.match(r"^https://[^/\s]+", u, re.I) or re.search(r"\s", u):
        raise ValueError("面板地址格式不对，例如 https://cp.greencloudvps.com")
    low = u.lower()
    if low.endswith(API_PATH):
        return u
    if low.endswith("/api/client"):
        return u + "/command.php"
    return u + API_PATH


def parse_servers_text(text):
    """多行文本 -> servers。每行「名称 key hash」，空格或逗号分隔；名称里可以有空格（取最后两段为 key / hash）。
    空行和 # 开头的行忽略。格式错误时抛 ValueError（只报行号，不回显 key / hash）。"""
    servers, errs = [], []
    for n, line in enumerate(str(text or "").replace("\r\n", "\n").split("\n"), 1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        parts = [p for p in _SPLIT.split(s) if p]
        if len(parts) < 3:
            errs.append(f"第 {n} 行需要「名称 key hash」三段")
            continue
        servers.append({"name": " ".join(parts[:-2])[:64], "key": parts[-2], "hash": parts[-1]})
    if errs:
        raise ValueError("；".join(errs[:5]))
    return servers


def servers_text(servers):
    return "\n".join(f"{s['name']} {s['key']} {s['hash']}" for s in servers or [])


def normalize_cred(cred):
    """把表单 / 导入的各种写法统一成 {"api_url", "servers": [...]}（保留 proxy 等其他字段）。有问题抛 ValueError。"""
    cred = dict(cred or {})
    out = {k: v for k, v in cred.items() if k not in ("api_url", "servers", "servers_text")}
    url = str(cred.get("api_url") or "").strip() or DEFAULT_API_URL
    endpoint(url)
    raw = cred.get("servers")
    if isinstance(raw, str):
        servers = parse_servers_text(raw)
    elif isinstance(raw, list) and raw:
        servers = []
        for i, s in enumerate(raw, 1):
            if not isinstance(s, dict):
                raise ValueError(f"第 {i} 台 VPS 格式不对")
            servers.append({k: str(s.get(k) or "").strip() for k in ("name", "key", "hash")})
    else:
        servers = parse_servers_text(cred.get("servers_text") or "")
    if not servers:
        out.update(api_url=url, servers=[])
        return out
    if len(servers) > MAX_SERVERS:
        raise ValueError(f"一个账号最多 {MAX_SERVERS} 台 VPS")
    seen = set()
    for i, s in enumerate(servers, 1):
        if not s["key"] or not s["hash"]:
            raise ValueError(f"第 {i} 台 VPS 缺少 key 或 hash")
        if not re.fullmatch(r"[A-Za-z0-9\-_]{4,128}", s["key"]) or not re.fullmatch(r"[A-Za-z0-9\-_]{4,128}", s["hash"]):
            raise ValueError(f"第 {i} 台 VPS 的 key / hash 含有非法字符")
        if s["key"] in seen:
            raise ValueError(f"第 {i} 台 VPS 的 key 与前面重复")
        seen.add(s["key"])
        s["name"] = s["name"] or f"VPS-{i}"
    out.update(api_url=url, servers=servers)
    return out


def inst_id(key):
    return "gc-" + hashlib.sha1(str(key).encode()).hexdigest()[:12]


# ---------------- 解析 ----------------
def parse_reply(text):
    """类 XML 片段 -> {tag: value}（小写键，去空白，HTML 实体还原）。解析不到任何标签返回 {}。"""
    out = {}
    for k, v in _TAG.findall(text or ""):
        out.setdefault(k.lower(), html.unescape(v).strip())
    return out


def _int(x):
    try:
        return int(float(str(x).strip()))
    except (TypeError, ValueError):
        return 0


def parse_bw(s):
    """"total,used,free,percent"（字节）-> {total, used, free, percent}；缺失 / 格式不对返回 None。"""
    parts = [p.strip() for p in str(s or "").split(",")]
    if len(parts) < 2 or not any(parts[:2]):
        return None
    total, used = _int(parts[0]), _int(parts[1])
    free = _int(parts[2]) if len(parts) > 2 and parts[2] else max(total - used, 0)
    try:
        pct = float(parts[3]) if len(parts) > 3 and parts[3] != "" else None
    except ValueError:
        pct = None
    if pct is None:
        pct = round(used / total * 100, 2) if total else 0.0
    return {"total": total, "used": used, "free": free, "percent": round(pct, 2)}


def state_of(d):
    s = (d.get("vmstat") or d.get("statusmsg") or "").strip().lower()
    if s in ("online", "running", "booted", "on"):
        return "running"
    if s in ("offline", "stopped", "shutdown", "off", "down"):
        return "stopped"
    return "unknown"


def split_ips(d):
    ips = []
    for x in [d.get("ipaddress") or ""] + re.split(r"[,\s]+", d.get("ipaddr") or ""):
        x = x.strip()
        if x and x not in ips:
            ips.append(x)
    v4 = [x for x in ips if ":" not in x]
    v6 = [x for x in ips if ":" in x]
    return ips, v4, v6


class GreenCloudProvider:
    name = "greencloud"

    def __init__(self, cred, region=None):
        c = normalize_cred(cred)
        self.cred = c
        self.url = endpoint(c["api_url"])
        self.servers = c["servers"]
        self.proxy = c.get("proxy") or None

    # ---------- HTTP ----------
    def _host(self):
        return re.sub(r"^https://([^/]+).*$", r"\1", self.url)

    def call(self, srv, action, **extra):
        """调用一次 SolusVM 客户 API，返回解析后的 dict；失败抛 GreenCloudError（带 VPS 名称，不含 key / hash）。"""
        data = {"key": srv["key"], "hash": srv["hash"], "action": action}
        data.update({k: "true" for k, v in extra.items() if v})
        name = srv.get("name") or "VPS"
        try:
            kw = {"proxy": self.proxy} if self.proxy else {}
            with httpx.Client(timeout=TIMEOUT, verify=True, follow_redirects=False, **kw) as cl:
                r = cl.post(self.url, data=data, headers={"User-Agent": "TriCloud"})
        except httpx.ConnectError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate" in str(e).lower():
                raise GreenCloudError(f"{name}：{self._host()} 的 SSL 证书校验失败（证书无效 / 过期 / 域名不符），"
                                      "请确认面板地址填写正确") from None
            raise GreenCloudError(f"{name}：连接 {self._host()} 失败：{str(e)[:120]}") from None
        except httpx.TimeoutException:
            raise GreenCloudError(f"{name}：连接 {self._host()} 超时（{TIMEOUT} 秒）") from None
        except httpx.HTTPError as e:
            raise GreenCloudError(f"{name}：请求失败：{type(e).__name__}") from None
        if r.status_code in (301, 302, 303, 307, 308):
            raise GreenCloudError(f"{name}：面板地址发生跳转（HTTP {r.status_code}），请填写完整的面板地址（可能需要带端口）")
        if r.status_code != 200:
            raise GreenCloudError(f"{name}：面板返回 HTTP {r.status_code}，请检查面板地址")
        d = parse_reply(r.text)
        if "status" not in d:
            raise GreenCloudError(f"{name}：返回内容无法识别（不是 SolusVM 客户 API，请检查面板地址）")
        if (d.get("status") or "").lower() != "success":
            msg = d.get("statusmsg") or d.get("status") or "未知错误"
            raise GreenCloudError(f"{name}：{msg}")
        return d

    def _srv(self, iid):
        for s in self.servers:
            if inst_id(s["key"]) == iid:
                return s
        raise LookupError("实例不存在（可能已从账号的 VPS 列表中移除）")

    # ---------- 通用接口 ----------
    def test(self):
        if not self.servers:
            raise GreenCloudError("没有 VPS：请按「名称 key hash」每行填写一台")
        for s in self.servers:
            try:
                self.call(s, "status")
            except GreenCloudError as e:
                raise GreenCloudError(f"VPS「{s['name']}」测试失败：{str(e).split('：', 1)[-1]}") from None
        return {"ok": True, "servers": len(self.servers)}

    def regions(self):
        return ["-"]

    def _item(self, s, d=None, err=None):
        d = d or {}
        ips, v4, v6 = split_ips(d)
        bw = parse_bw(d.get("bw"))
        item = {"id": inst_id(s["key"]), "name": s["name"], "state": state_of(d) if d else "unknown",
                "public_ip": v4[0] if v4 else None,
                "ipv6": v6, "ips": ips, "shape": "-", "region": "-", "zone": "-", "hostname": d.get("hostname") or "",
                "bw": {"total": bw["total"], "used": bw["used"], "percent": bw["percent"]} if bw else None, "created": ""}
        if err:
            item["error"] = err
        return item

    def instance(self, iid):
        s = self._srv(iid)
        return self._item(s, self.call(s, "info", ipaddr=True, bw=True, status=True))

    def list_instances(self):
        def one(s):
            try:
                return self._item(s, self.call(s, "info", ipaddr=True, bw=True, status=True))
            except GreenCloudError as e:
                return self._item(s, err=str(e)[:200])
        if not self.servers:
            return []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(self.servers))) as ex:
            return list(ex.map(one, self.servers))

    def get_state(self, iid):
        return state_of(self.call(self._srv(iid), "status"))

    def action(self, iid, action, **kw):
        if action not in ACTIONS:
            raise unsupported({"terminate": "终止 / 删除", "hard_reboot": "强制重启"}.get(action, f"「{action}」"))
        d = self.call(self._srv(iid), ACTIONS[action])
        return {"ok": True, "message": d.get("statusmsg") or ""}

    def traffic(self, iid, kind="vm", start=None, end=None):
        """本计费周期流量（绿云面板统计，出入合计）。SolusVM 不提供按时间段查询，所以不支持滚动窗口。"""
        if start is not None:
            raise unsupported("按时间窗口查询流量（只有本计费周期累计）")
        s = self._srv(iid)
        bw = parse_bw(self.call(s, "info", bw=True).get("bw"))
        if not bw:
            raise GreenCloudError(f"{s['name']}：面板没有返回流量数据")
        g = 1024 ** 3
        return {"out_gb": round(bw["used"] / g, 3), "in_gb": 0.0, "used_gb": round(bw["used"] / g, 3),
                "total_gb": round(bw["total"] / g, 3), "percent": bw["percent"], "used": bw["used"], "total": bw["total"],
                "period": "本计费周期（绿云面板统计，出入合计）"}

    def billing(self):
        raise unsupported("查询账单")



# =====================================================================
# 面板集成钩子（main / services / core / telegram / traffic_guard / tasks / accounts_import 里标 `# greencloud` 的地方调用）
# =====================================================================
PROVIDER_ID = "greencloud"
REQUIRED_FIELDS = ["api_url", "servers"]
FORM_FIELDS = ("api_url", "servers_text", "servers")   # POST /api/accounts 顶层或 cred 里都可以传
JSON_KEYS = {"servers", "servers_text", "api_url"}      # 批量导入 JSON 按这些字段推断为绿云
ALIASES = {"gc": PROVIDER_ID, "green": PROVIDER_ID, "greencloudvps": PROVIDER_ID, "绿云": PROVIDER_ID, "solusvm": PROVIDER_ID}
SCOPE_TEXT = "本计费周期（出入合计）"
TG_OPS = ["start", "stop", "reboot"]
DEFAULT_GUARD_GB = 1000
ACCOUNT_TYPE = {"label": "绿云 KVM", "plan_type": None, "hint": "SolusVM 客户 API 不提供账号类型 / 开户日期，可在「信息」里手动填写创建日期"}
OP_NAMES = {"terminate": "终止 / 删除", "hard_reboot": "强制重启", "change-ip": "换 IP", "resize": "改配置", "rename": "改名",
            "open-port": "开放端口", "reinstall": "重装系统", "create": "创建实例", "migrate": "迁移到绿云"}
DISABLED_MSG = "绿云已在「设置」中关闭"
_REGISTRIES = []   # [(dict, value)]：services.PROVIDERS ← GreenCloudProvider，main.REQUIRED ← REQUIRED_FIELDS


def is_gc(x):
    """x 可以是 provider 字符串，也可以是带 provider 的账号 dict。"""
    return (x.get("provider") if isinstance(x, dict) else x) == PROVIDER_ID


def enabled():
    """设置 enable_greencloud（默认开）。顺带让注册表与开关保持一致。"""
    try:
        from .. import core
        v = core.get_setting("enable_greencloud", True)
    except Exception:   # 数据库还没初始化（导入期）
        v = True
    on = not (v is False or str(v).strip().lower() in ("0", "false", "off", "no", ""))
    _apply(on)
    return on


def hidden(prov):
    """该 provider 的账号是否要隐藏（= 绿云且开关关闭）。"""
    return is_gc(prov) and not enabled()


def _apply(on):
    for reg, val in _REGISTRIES:
        if on:
            reg.setdefault(PROVIDER_ID, val)
        else:
            reg.pop(PROVIDER_ID, None)


def register(reg, value):
    """小注册点：把绿云放进某个「provider -> 东西」的表，开关关闭时自动移除。"""
    _REGISTRIES.append((reg, value))
    _apply(enabled())


def sync():
    return enabled()


def check_op(acc, op):
    """绿云只支持开机 / 关机 / 重启：其他实例操作抛 Unsupported（→ 400）。"""
    if is_gc(acc) and op not in ACTIONS:
        raise unsupported(OP_NAMES.get(op, ""))


def clean_cred(cred):
    """main._clean_cred 的绿云分支：返回 (cred, 缺少的字段)。"""
    if not enabled():
        raise BadInput(DISABLED_MSG)
    try:
        c = normalize_cred({k: (v.strip() if isinstance(v, str) else v) for k, v in (cred or {}).items() if v})
    except ValueError as e:
        raise BadInput(str(e)) from None
    return c, [k for k in REQUIRED_FIELDS if not c.get(k)]


def merge_body(body, cred):
    """约定：POST /api/accounts 收 {provider, name, api_url, servers_text}，也兼容放在 cred 里。"""
    return dict(cred or {}, **{k: body[k] for k in FORM_FIELDS if body.get(k)})


def form_cred(cred):
    """/accounts/parse 回填表单：面板地址 + 多行 VPS 列表（只是把刚粘贴的内容整理回去）。"""
    return {"api_url": (cred or {}).get("api_url") or DEFAULT_API_URL, "servers_text": servers_text((cred or {}).get("servers") or [])}


def mask(v):
    return "****" + str(v or "")[-4:]


def masked_text(servers):
    """编辑回显：每行「名称 ****key末4位 ****hash末4位」。"""
    return "\n".join(f"{s['name']} {mask(s['key'])} {mask(s['hash'])}" for s in servers or [])


def detail(acc, cred, proxy_view):
    """GET /accounts/{id}/detail：面板地址明文，VPS 列表 key / hash 打码，绝不返回原值。"""
    srv = (cred or {}).get("servers") or []
    out = {k: acc.get(k) for k in ("id", "name", "provider", "region", "cloud_created_at", "credit_total", "edu_expires_at")}
    out.update(proxy_view, fields={"api_url": cred.get("api_url") or DEFAULT_API_URL, "servers_text": masked_text(srv)},
               servers=[{"id": inst_id(s["key"]), "name": s["name"], "key": mask(s["key"]), "hash": mask(s["hash"])} for s in srv])
    return out


def _unmask(rows, orig):
    """把仍是打码值（****1234）的 key / hash 换回原值。按末 4 位匹配，同名优先。"""
    out = []
    for i, r in enumerate(rows, 1):
        k, h, src = r["key"], r["hash"], None
        if k.startswith("****"):
            cand = [o for o in orig if o["key"].endswith(k[4:]) and (not h.startswith("****") or o["hash"].endswith(h[4:]))]
            src = next((o for o in cand if o["name"] == r["name"]), cand[0] if len(cand) == 1 else None)
            if not src:
                raise BadInput(f"第 {i} 行「{r['name']}」的 key 是打码值，找不到原来的 key，请填写完整 key")
            k = src["key"]
        if h.startswith("****"):
            cand = [src] if src else [o for o in orig if o["hash"].endswith(h[4:])]
            src2 = next((o for o in cand if o["name"] == r["name"]), cand[0] if len(cand) == 1 else None)
            if not src2 or not src2["hash"].endswith(h[4:]):
                raise BadInput(f"第 {i} 行「{r['name']}」的 hash 是打码值，找不到原来的 hash，请填写完整 hash")
            h = src2["hash"]
        out.append({"name": r["name"], "key": k, "hash": h})
    return out


def patch_cred(cred, patch):
    """PATCH 凭证：api_url 提交即改（空 = 默认地址）；servers_text 非空时整体替换 VPS 列表，
    其中仍为打码值的 key / hash 沿用原值。返回 (新 cred, 是否有变化)。"""
    old = normalize_cred(cred)
    new = dict(old)
    if "api_url" in patch:
        new["api_url"] = str(patch.get("api_url") or "").strip() or DEFAULT_API_URL
    txt = str(patch.get("servers_text") or "").strip()
    try:
        if txt:
            new["servers"] = _unmask(parse_servers_text(txt), old["servers"])
        new = normalize_cred(new)
    except ValueError as e:
        raise BadInput(str(e)) from None
    if not new["servers"]:
        raise BadInput("VPS 列表不能为空")
    return new, new != old


def billing_stub(now):
    return {"period": "-", "currency": "USD", "total": None, "services": [], "unsupported": True,
            "note": "绿云 API 不提供账单", "cached": False, "updated_at": now.strftime("%Y-%m-%d %H:%M")}


def guard_body(body):
    """流量守护保存：只支持本计费周期累计（出入合计）；额度默认取面板 bw.total（检查时自动同步）。"""
    if (body.get("mode") or "monthly") != "monthly":
        raise unsupported("滚动窗口流量统计（只有本计费周期累计）")
    return dict(body, mode="monthly", direction="both", window_hours=None, limit_gb=body.get("limit_gb") or DEFAULT_GUARD_GB)


def guard_measure(g):
    """流量守护：已用 GB = bw.used；额度跟随 bw.total（写回规则的 limit_gb，g 原地更新）。"""
    from .. import core, services
    u = services.provider(g["account_id"], g.get("region")).traffic(g["instance_id"])
    total = float(u.get("total_gb") or 0)
    if total > 0 and abs(total - float(g.get("limit_gb") or 0)) > 0.001:
        core.ex("UPDATE traffic_guards SET limit_gb=? WHERE id=?", (round(total, 3), g["id"]))
        g["limit_gb"] = round(total, 3)
    return float(u.get("used_gb") or 0)


def bw_text(bw):
    """已用 / 总量（百分比）。bw = {total, used, percent}（字节）。"""
    if not bw:
        return ""
    g = 1024 ** 3
    return f"{(bw.get('used') or 0) / g:.1f} / {(bw.get('total') or 0) / g:.0f} GB（{float(bw.get('percent') or 0):.0f}%）"


def tg_label(i):
    return f" · {float(i['bw']['percent']):.0f}%" if i.get("bw") else ""


def tg_extra(i):
    return {"bw": i["bw"]} if i.get("bw") else {}


def tg_bw_line(d):
    return f"\n流量：{bw_text(d['bw'])}" if is_gc(d.get("p")) and d.get("bw") else ""


def tg_refresh(d):
    """TG「刷新状态」：一次 info 同时刷新状态、IP 和流量。"""
    from .. import services
    d = dict(d)
    try:
        it = services.provider(d["a"]).instance(d["i"])
        d.update(s=it["state"], ip=it.get("public_ip"), **tg_extra(it))
    except Exception as e:
        d["s"] = f"查询失败 {str(e)[:60]}"
    return d


# ---------- 批量导入 / 粘贴识别 ----------
_HINT = re.compile(r"greencloud|绿云|solusvm", re.I)
_KEY = re.compile(r"[A-Z0-9]{5}(?:-[A-Z0-9]{5}){2,}")      # SolusVM API key 常见形如 ABCDE-FGHIJ-KLMNO
_HASH = re.compile(r"[0-9a-f]{40}")                         # API hash 为 40 位十六进制
_URL = re.compile(r"https?://[^\s,;\"'<>，；]+", re.I)
_NAME = re.compile(r"^\s*(?:name|名称|备注|备注名|账号名|remark)\s*[:：=]\s*(.+?)\s*$", re.I)
_SECTION = re.compile(r"^\s*\[([^\]\r\n\"{}]+)\]\s*$")


def from_json(obj, name, cred):
    """accounts_import.from_json 的绿云分支。"""
    if not enabled():
        return {"provider": PROVIDER_ID, "name": name, "cred": {}, "error": DISABLED_MSG}
    try:
        c = normalize_cred({k: v for k, v in (cred or {}).items() if v not in (None, "")})
    except ValueError as e:
        return {"provider": PROVIDER_ID, "name": name, "cred": {}, "error": f"绿云：{e}"}
    return {"provider": PROVIDER_ID, "name": name, "cred": c, "cloud_created_at": obj.get("cloud_created_at")}


def sniff(seg):
    """粘贴文本：面板地址 + 每行「名称 key hash」。要么带 greencloud / 绿云 / solusvm 字样，
    要么每行都是 SolusVM 典型格式（key 为 XXXXX-XXXXX-XXXXX，hash 为 40 位十六进制），避免误认其他云的凭证。"""
    if not enabled():
        return []
    hint = bool(_HINT.search(seg))
    url, name, lines = None, "", []
    for raw in seg.split("\n"):
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        sm, nm = _SECTION.match(s), _NAME.match(s)
        if sm or nm:
            name = name or (sm or nm).group(1).strip()
            continue
        um = _URL.search(s)
        if um:
            url = url or um.group(0).rstrip("/.")
            continue
        parts = [p for p in _SPLIT.split(s) if p]
        if len(parts) >= 3 and re.fullmatch(r"[A-Za-z0-9\-_]{8,128}", parts[-2]) and re.fullmatch(r"[A-Za-z0-9\-_]{16,128}", parts[-1]):
            lines.append((parts, bool(_KEY.fullmatch(parts[-2]) and _HASH.fullmatch(parts[-1]))))
        elif hint and not name and len(parts) <= 3 and _HINT.search(s):
            name = _HINT.sub("", s).strip(" :：-|")   # 「绿云 洛杉矶」这种标题行：去掉品牌词当账号名
    if not lines or not (hint or all(strict for _, strict in lines)):
        return []
    try:
        cred = normalize_cred({"api_url": url or "", "servers_text": "\n".join(" ".join(p) for p, _ in lines)})
    except ValueError as e:
        return [{"provider": PROVIDER_ID, "name": name, "cred": {}, "error": f"绿云：{e}"}]
    return [{"provider": PROVIDER_ID, "name": name, "cred": cred}]
