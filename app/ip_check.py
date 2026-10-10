"""公网 IP 连通性探测：ping + TCP 端口（22/80/443/3389）。

从面板服务器（境外）发起，只能验证 IP 是否存活、端口是否开放，
不能代替从国内发起的"被墙"检测。Azure/OCI/AWS 三家通用：
按实例公网 IP 探测，monitor 定时巡检与手动"检测 IP 连通性"
都复用这一个函数。
"""
import logging
import socket
import subprocess

log = logging.getLogger(__name__)

# (端口, 用途标签)
PROBE_PORTS = [(22, "SSH"), (80, "HTTP"), (443, "HTTPS"), (3389, "RDP")]


def probe_ip(ip: str) -> dict:
    """探测单个公网 IP 的连通性。

    返回：
    {
      "ip": ip,
      "ping": "通"|"不通"|"检测失败",
      "tcp": {"22": "开放", "80": "开放", ...},
      "ok": bool,        # ping 通或任一探测端口开放
      "lines": [...],    # 可直接展示给用户的文本行
    }
    """
    result = {
        "ip": ip,
        "ping": "检测失败",
        "tcp": {},
        "ok": False,
        "lines": [f"公网 IP: {ip}"],
    }
    # ping
    try:
        r = subprocess.run(["ping", "-c", "3", "-W", "2", ip],
                           capture_output=True, timeout=15)
        result["ping"] = "通" if r.returncode == 0 else "不通"
    except Exception:  # noqa: BLE001
        result["ping"] = "检测失败"
    result["lines"].append("Ping: " + result["ping"])
    # TCP 端口
    for port, label in PROBE_PORTS:
        try:
            s = socket.create_connection((ip, port), timeout=5)
            s.close()
            result["tcp"][str(port)] = "开放"
        except Exception:  # noqa: BLE001
            result["tcp"][str(port)] = "关闭/超时"
        result["lines"].append(
            f"TCP {port}({label}): {result['tcp'][str(port)]}")
    result["ok"] = result["ping"] == "通" or any(
        v == "开放" for v in result["tcp"].values())
    result["lines"].append(
        "结论: " + ("连通" if result["ok"] else "不通（ping 不通且所有探测端口均无响应）"))
    result["lines"].append("注：此为境外探测，仅供参考；被墙检测需从国内网络发起")
    return result
