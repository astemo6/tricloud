"""SolusVM 适配（绿云 GreenCloud 等 SolusVM 面板服务商的 KVM / OpenVZ VPS）。

凭证: {panel_url, key, hash}
- panel_url：SolusVM 面板根地址，如 https://cp.greencloudvps.com
- key / hash：在该 VPS 的 SolusVM 面板「API」页生成，**一对凭证只对应一台 VPS**
  （SolusVM Client API 是单机粒度，没有账号级实例列表）。因此一个 TriCloud
  「账号」= 一台 VPS，list_instances 恒返回这一台。

走 SolusVM 官方 Client API：POST {panel}/api/client/command.php，
字段 key / hash / action，可选 bw / hdd / mem / ipaddr / status / location=true，
返回 XML。可用 action：info / status / boot / reboot / shutdown。
bw / hdd / mem 的格式为 "total,used,free,percentage"，单位字节
（hdd / mem 在 KVM 上可能不返回，按缺失处理）。
该 API 不提供：创建 / 删除 / 换 IP / 开端口 / 账单——对应方法明确报错。
"""
import re

import httpx

from .. import core

_INFO_FLAGS = {"ipaddr": "true", "hdd": "true", "bw": "true", "mem": "true", "status": "true", "location": "true"}
_STATE = {"online": "running", "offline": "stopped"}


def _parse_xml(text):
    """SolusVM 返回的是无根节点的 XML 片段（<a>1</a><b>2</b>），按标签名收成 dict。"""
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"<([\w]+)>([^<]*)</\1>", text or "")}


def _quad(v):
    """ "total,used,free,pct"（字节）→ (total, used) 整数，格式不对返回 (0, 0)。"""
    try:
        p = [float(x) for x in str(v).split(",")]
        return int(p[0]), int(p[1])
    except Exception:
        return 0, 0


def _gb(n):
    return round(n / 1024 ** 3, 2)


class SolusVMProvider:
    def __init__(self, cred, region=None):
        self.cred = cred or {}
        self.panel = (self.cred.get("panel_url") or "").strip().rstrip("/")
        self.key = (self.cred.get("key") or "").strip()
        self.hash = (self.cred.get("hash") or "").strip()

    # ---------------- 基础请求 ----------------
    def _call(self, action, extra=None):
        if not self.panel or not self.key or not self.hash:
            raise ValueError("SolusVM 凭证不完整：需要 panel_url / key / hash")
        data = {"key": self.key, "hash": self.hash, "action": action}
        data.update(extra or {})
        # trust_env=False：只用账号里配的出口代理，不偷偷继承进程环境变量的代理
        try:
            with httpx.Client(trust_env=False, proxy=self.cred.get("proxy") or None, timeout=30) as cl:
                r = cl.post(f"{self.panel}/api/client/command.php", data=data)
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(f"连接 SolusVM 面板失败：{e}") from e
        out = _parse_xml(r.text)
        if (out.get("status") or "").lower() in ("error", "failed"):
            raise RuntimeError(f"SolusVM API 错误：{out.get('statusmsg') or out.get('status')}")
        return out

    def _info(self):
        return self._call("info", _INFO_FLAGS)

    @staticmethod
    def _state_of(info):
        for k in ("vmstat", "state"):
            if info.get(k):
                return _STATE.get(info[k].lower(), info[k].lower())
        sm = (info.get("statusmsg") or "").lower()   # 带 status=true 时在线状态在 statusmsg 里
        if sm in _STATE:
            return _STATE[sm]
        return "unknown"

    # ---------------- Provider 接口 ----------------
    def test(self):
        info = self._info()
        ips = [x for x in (info.get("ipaddr") or "").split(",") if x.strip()]
        return {"ok": True, "hostname": info.get("hostname") or None, "ip": ips[0] if ips else None}

    def regions(self):
        return []

    def list_instances(self):
        info = self._info()
        ips = [x.strip() for x in (info.get("ipaddr") or "").split(",") if x.strip()]
        ipv4 = [x for x in ips if ":" not in x]
        ipv6 = [x for x in ips if ":" in x]
        mem_t, _ = _quad(info.get("mem"))
        hdd_t, _ = _quad(info.get("hdd"))
        shape = " / ".join(x for x in (f"{_gb(mem_t)}G 内存" if mem_t else "", f"{_gb(hdd_t)}G 硬盘" if hdd_t else "")) or "-"
        name = info.get("hostname") or (ipv4[0] if ipv4 else "solusvm")
        return [{"id": name, "name": name, "state": self._state_of(info),
                 "public_ip": ipv4[0] if ipv4 else None, "private_ip": None, "ipv6": ipv6,
                 "shape": shape, "memory_gb": _gb(mem_t) if mem_t else None,
                 "region": info.get("location") or self.panel.split("//")[-1], "zone": "-", "created": ""}]

    def get_state(self, inst_id):
        try:
            out = self._call("status", {"status": "true"})
            st = self._state_of(out)
            if st != "unknown":
                return st
        except Exception:
            pass
        return self._state_of(self._info())

    def action(self, inst_id, action, wait=False):
        m = {"start": "boot", "stop": "shutdown", "reboot": "reboot", "hard_reboot": "reboot"}
        if action == "terminate":
            raise core.CloudUnsupportedError("SolusVM 客户 API 不支持删除实例（退订请在服务商客户区操作）")
        if action not in m:
            raise core.CloudUnsupportedError(f"SolusVM 不支持的操作：{action}")
        self._call(m[action])
        return {"ok": True}

    def traffic(self, inst_id, kind="vm", start=None, end=None):
        """SolusVM 只给计费周期内的合计流量（入+出，不拆分）：合计计入 out_gb，
        流量守护按 out+in 求和，口径仍正确。"""
        info = self._info()
        total, used = _quad(info.get("bw"))
        return {"period": "当前计费周期（SolusVM 口径）", "out_gb": _gb(used), "in_gb": 0,
                "used_gb": _gb(used), "total_gb": _gb(total) if total else None}

    def billing(self):
        raise core.CloudUnsupportedError("SolusVM（绿云等）不提供账单 API，费用与续费请在服务商客户区查看")
