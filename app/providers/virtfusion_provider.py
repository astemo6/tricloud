"""VirtFusion 适配（绿云 GreenCloud 新线路等 VirtFusion 面板服务商）。

凭证: {panel_url, api_token}
- panel_url：VirtFusion 面板根地址，如 https://cp.green.cloud
- api_token：终端用户 API key——面板 Account → API 里用户自己生成
  （VirtFusion 6.1 起；管理员可关闭该功能，关闭时任何 key 都调不通）。
  与管理员 Global API token 不同：用户 key 只能看到 / 操作自己名下的服务器。

端点与字段以绿云面板内官方 API 文档（OpenAPI 3.0.1，2026-11-10 导出核对）
为准，基址 {panel}/api，Bearer 鉴权：
- GET  connect                    测活（200 空对象）
- GET  account                    账号信息 {name, email, timezone}
- GET  server?results=N&page=M    列表（Laravel 分页：data + next_page_url）
- GET  server/{id}?state=true     详情；带 state 时附 data.state：
  {status, running, cpu "0.3 %", network.<iface>.traffic {rx, tx, total}（字节）}
- POST server/{id}/boot|shutdown|restart|powerOff   电源（200 返回 task accepted）
- PUT  server/{id}/name           改名（204 无正文）
服务器对象：id 为 UUID；cpu / memory / storage.capacity / network.limit
都是带单位的字符串（"2 Core" / "1024 MB" / "10 GB" / "20000 GB"），
统一由 _size_gb / _cores 解析。列表对象本身不带电源状态（只有
suspended / deleting 等标志位），实时状态走 ?state=true。
流量取 state 的 traffic 计数：与对象上的 currentMonthlyPeriod 同周期
口径，字节 → GiB 与其他 provider 对齐（rx=入 / tx=出）。
该 API（用户级）不提供：创建 / 删除 / 账单——对应方法明确报错。
"""
import re

import httpx

from .. import core

_GIB = 1024 ** 3
_UNIT_GB = {"GB": 1.0, "MB": 1 / 1024, "TB": 1024.0, "KB": 1 / 1024 ** 2, "B": 1.0 / _GIB}


def _size_gb(value, bare_unit="GB"):
    """把 "10 GB" / "1024 MB" / 数字 解析成 GB（float）；解析不了返回 0。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value) * _UNIT_GB.get(bare_unit, 1.0)
    m = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)?", str(value))
    if not m:
        return 0.0
    return float(m.group(1)) * _UNIT_GB.get((m.group(2) or bare_unit).upper(), 1.0)


def _cores(value):
    """cpu 字段："2 Core" / 2 → 2。"""
    if isinstance(value, (int, float)):
        return int(value)
    m = re.match(r"\s*(\d+)", str(value or ""))
    return int(m.group(1)) if m else 0


class VirtFusionProvider:
    # TriCloud 动作名 → VirtFusion 电源端点（powerOff 是强制断电，与
    # hard_reboot 语义不同，不映射，见 action()）
    _POWER = {"start": "boot", "stop": "shutdown", "reboot": "restart"}

    def __init__(self, cred, region=None):
        self.cred = cred or {}
        self.panel = (self.cred.get("panel_url") or "").strip().rstrip("/")
        self.token = (self.cred.get("api_token") or "").strip()

    # ---------------- 基础请求 ----------------
    def _req(self, method, path, json_body=None, params=None):
        if not self.panel or not self.token:
            raise ValueError("VirtFusion 凭证不完整：需要 panel_url / api_token")
        # trust_env=False：只用账号里配的出口代理，不偷偷继承进程环境变量的代理
        try:
            with httpx.Client(trust_env=False, proxy=self.cred.get("proxy") or None, timeout=30) as cl:
                r = cl.request(method, f"{self.panel}/api/{path}", json=json_body, params=params,
                               headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise RuntimeError(f"连接 VirtFusion 面板失败：{e}") from e
        if r.status_code == 401:
            raise RuntimeError("VirtFusion API key 无效，或该面板未开启终端用户 API（管理员可在设置中关闭）")
        if r.status_code >= 400:
            detail = ""
            try:
                body = r.json() or {}
                errs = body.get("errors") or []
                detail = str(errs[0]) if errs else str(body.get("message") or "")
            except Exception:
                pass
            raise RuntimeError(f"VirtFusion API 错误（HTTP {r.status_code}）{('：' + detail) if detail else ''}")
        return r.json() if r.content else {}

    def _servers(self):
        out, page = [], 1
        while True:
            d = self._req("GET", "server", params={"results": 100, "page": page})
            out.extend(d.get("data") or [])
            if not d.get("next_page_url"):
                return out
            page += 1

    def _server_state(self, inst_id):
        """GET server/{id}?state=true → (服务器对象, state 对象|None)。"""
        d = self._req("GET", f"server/{inst_id}", params={"state": "true"})
        data = d.get("data") or {}
        return data, data.get("state")

    @staticmethod
    def _map(s):
        net = ((s.get("network") or {}).get("primary") or {})
        ipv4 = [x.get("address") for x in (net.get("ipv4") or []) if isinstance(x, dict) and x.get("address")]
        ipv6 = []
        for g in net.get("ipv6") or []:
            if isinstance(g, dict):
                ipv6.extend(g.get("addresses") or [])
        disk = sum(_size_gb(x.get("capacity")) for x in (s.get("storage") or [])
                   if isinstance(x, dict) and x.get("enabled", True))
        mem_gb = _size_gb(s.get("memory"), bare_unit="MB")
        cores = _cores(s.get("cpu"))
        shape_bits = [f"{cores} 核"] if cores else []
        if mem_gb:
            shape_bits.append(f"{mem_gb:g}G 内存")
        if disk:
            shape_bits.append(f"{disk:g}G 硬盘")
        if s.get("deleting"):
            state = "deleting"
        elif s.get("suspended"):
            state = "suspended"
        else:
            state = "unknown"   # 列表不带电源状态，实时状态走 get_state()
        return {"id": str(s.get("id")), "name": s.get("name") or s.get("hostname") or str(s.get("id")), "state": state,
                "public_ip": ipv4[0] if ipv4 else None, "private_ip": None, "ipv6": ipv6,
                "shape": " / ".join(shape_bits) or "-", "region": "-", "zone": "-", "created": str(s.get("created") or "")}

    @staticmethod
    def _state_of(state):
        """state 对象 → TriCloud 状态字符串。"""
        if not isinstance(state, dict):
            return "unknown"
        if isinstance(state.get("running"), bool):
            return "running" if state["running"] else "stopped"
        status = str(state.get("status") or "").lower()
        if "run" in status:
            return "running"
        return "stopped" if status else "unknown"

    # ---------------- Provider 接口 ----------------
    def test(self):
        self._req("GET", "connect")
        return {"ok": True}

    def regions(self):
        return []

    def list_instances(self):
        return [self._map(s) for s in self._servers()]

    def get_state(self, inst_id):
        _, state = self._server_state(inst_id)
        return self._state_of(state)

    def action(self, inst_id, action, wait=False):
        if action == "terminate":
            raise core.CloudUnsupportedError("VirtFusion 用户 API 不支持删除实例（退订请在服务商客户区操作）")
        if action == "hard_reboot":
            raise core.CloudUnsupportedError("VirtFusion 用户 API 没有强制重启端点：restart 是正常重启，powerOff 是强制关机（不等同重启），未做映射")
        endpoint = self._POWER.get(action)
        if not endpoint:
            raise core.CloudUnsupportedError(f"VirtFusion 不支持该操作：{action}")
        self._req("POST", f"server/{inst_id}/{endpoint}")
        return True

    def rename(self, inst_id, name):
        self._req("PUT", f"server/{inst_id}/name", json_body={"name": name})
        return {}

    def traffic(self, inst_id, kind="vm", start=None, end=None):
        data, state = self._server_state(inst_id)
        if not isinstance(state, dict):
            raise RuntimeError("VirtFusion 未返回服务器状态（state），无法读取流量")
        rx = tx = 0
        for iface in (state.get("network") or {}).values():
            t = (iface or {}).get("traffic") or {}
            rx += int(t.get("rx") or 0)
            tx += int(t.get("tx") or 0)
        net = data.get("network") or {}
        total_gb = sum(_size_gb((net.get(k) or {}).get("limit")) for k in ("primary", "secondary")
                       if isinstance(net.get(k), dict))
        period = data.get("currentMonthlyPeriod") or {}
        return {"in_gb": round(rx / _GIB, 3), "out_gb": round(tx / _GIB, 3),
                "used_gb": round((rx + tx) / _GIB, 3), "total_gb": round(total_gb, 3),
                "period_start": period.get("start"), "period_end": period.get("end")}

    def billing(self):
        raise core.CloudUnsupportedError("VirtFusion（绿云等）不提供账单 API，费用与续费请在服务商客户区查看")
