"""VirtFusion 适配（绿云 GreenCloud 新线路等 VirtFusion 面板服务商）。

凭证: {panel_url, api_token}
- panel_url：VirtFusion 面板根地址，如 https://cp.example.com
- api_token：终端用户 API key——VirtFusion 6.1 起面板 Account → API 里
  用户自己生成（管理员可关闭该功能，关闭时任何 key 都调不通）。
  与管理员 Global API token 不同：用户 key 只能看到 / 操作自己名下的服务器。

走终端用户 API：{panel}/api/...，Bearer 鉴权，JSON。
已据公开客户端（Raycast 扩展）核实的端点：
- GET  connect            测活
- GET  server?page=N      服务器列表（分页，data + next_page_url）
电源 / 流量端点未公开（文档只在各用户面板的 Account → API 页内），
先明确报错、留待实测后在 _power() / traffic() 两处补齐，不猜端点乱发请求。
该 API（用户级）不提供：创建 / 删除 / 账单——对应方法明确报错。
"""
import httpx

from .. import core


class VirtFusionProvider:
    def __init__(self, cred, region=None):
        self.cred = cred or {}
        self.panel = (self.cred.get("panel_url") or "").strip().rstrip("/")
        self.token = (self.cred.get("api_token") or "").strip()

    # ---------------- 基础请求 ----------------
    def _req(self, path):
        if not self.panel or not self.token:
            raise ValueError("VirtFusion 凭证不完整：需要 panel_url / api_token")
        # trust_env=False：只用账号里配的出口代理，不偷偷继承进程环境变量的代理
        try:
            with httpx.Client(trust_env=False, proxy=self.cred.get("proxy") or None, timeout=30) as cl:
                r = cl.get(f"{self.panel}/api/{path}",
                           headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise RuntimeError(f"连接 VirtFusion 面板失败：{e}") from e
        if r.status_code == 401:
            raise RuntimeError("VirtFusion API key 无效，或该面板未开启终端用户 API（管理员可在设置中关闭）")
        if r.status_code >= 400:
            try:
                errs = (r.json() or {}).get("errors") or []
            except Exception:
                errs = []
            raise RuntimeError(f"VirtFusion API 错误（HTTP {r.status_code}）{('：' + str(errs[0])) if errs else ''}")
        return r.json() if r.content else {}

    def _servers(self):
        out, page = [], 1
        while True:
            d = self._req(f"server?page={page}")
            out.extend(d.get("data") or [])
            if not d.get("next_page_url"):
                return out
            page += 1

    @staticmethod
    def _map(s):
        net = ((s.get("network") or {}).get("primary") or {})
        ipv4 = [x.get("address") for x in (net.get("ipv4") or []) if x.get("address")]
        ipv6 = []
        for g in net.get("ipv6") or []:
            ipv6.extend(g.get("addresses") or [])
        disk = sum(int(x.get("capacity") or 0) for x in (s.get("storage") or []) if x.get("enabled", True))
        mem = s.get("memory")
        shape_bits = [f"{s['cpu']} 核"] if s.get("cpu") else []
        if mem:
            shape_bits.append(f"{int(mem) / 1024:g}G 内存" if str(mem).isdigit() else f"{mem} 内存")
        if disk:
            shape_bits.append(f"{disk}G 硬盘")
        state = str(s.get("state") or s.get("status") or "unknown").lower()
        state = {"powered on": "running", "on": "running", "powered off": "stopped", "off": "stopped"}.get(state, state)
        return {"id": str(s.get("id")), "name": s.get("name") or str(s.get("id")), "state": state,
                "public_ip": ipv4[0] if ipv4 else None, "private_ip": None, "ipv6": ipv6,
                "shape": " / ".join(shape_bits) or "-", "region": "-", "zone": "-", "created": str(s.get("created") or "")}

    # ---------------- Provider 接口 ----------------
    def test(self):
        self._req("connect")
        return {"ok": True}

    def regions(self):
        return []

    def list_instances(self):
        return [self._map(s) for s in self._servers()]

    def get_state(self, inst_id):
        for s in self._servers():
            if str(s.get("id")) == str(inst_id):
                return self._map(s)["state"]
        raise KeyError(f"实例不存在：{inst_id}")

    def action(self, inst_id, action, wait=False):
        if action == "terminate":
            raise core.CloudUnsupportedError("VirtFusion 用户 API 不支持删除实例（退订请在服务商客户区操作）")
        raise core.CloudUnsupportedError("VirtFusion 终端用户 API 的电源端点未公开（文档在面板 Account → API 页内），待实测确认后补齐")

    def traffic(self, inst_id, kind="vm", start=None, end=None):
        raise core.CloudUnsupportedError("VirtFusion 终端用户 API 的流量端点未公开（文档在面板 Account → API 页内），待实测确认后补齐")

    def billing(self):
        raise core.CloudUnsupportedError("VirtFusion（绿云等）不提供账单 API，费用与续费请在服务商客户区查看")
