"""实例改名与系统主机名（SSH 登录看到的 hostname）。

v1.6 起关停「改名后自动同步系统主机名」（2026-10-23 用户决定）：自动同步要借各云的
Run Command / SSM 通道在实例内执行命令，等同于面板常驻系统内执行权，风险过高。
现在改名只改云端显示名；系统主机名由 manual_result() 生成一条**固定命令**随改名结果
返回，用户 SSH 登录实例后自行执行。面板不经任何通道向实例下发命令。

主机名一律先经 normalize() 规范化、再经 validate() 严格校验（只允许 a-z 0-9 -），
绝不把用户原始输入拼进命令。
"""
import re

_VALID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize(name):
    """显示名 → 合法主机名：小写；空白 / 下划线 / 点 视作 -；只保留 a-z 0-9 -；连续 - 合并；
    最长 63；不能以 - 开头或结尾。结果为空返回 ""（调用方跳过同步）。"""
    s = str(name or "").strip().lower()
    s = re.sub(r"[\s_.]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:63].strip("-")


def validate(h):
    """命令拼接前的最后一道闸：不是规范主机名就拒绝。"""
    if not isinstance(h, str) or not _VALID.match(h):
        raise ValueError(f"非法主机名：{h!r}")
    return h


def build_cmd(h):
    """在实例内（root）执行的固定命令。h 必须已通过 validate()。"""
    h = validate(h)
    return (f'hostnamectl set-hostname {h} 2>/dev/null || echo {h} > /etc/hostname && hostname {h}; '
            f'sed -i "s/^127.0.1.1.*/127.0.1.1 {h}/" /etc/hosts || true; '
            f'grep -q "127.0.1.1" /etc/hosts || echo "127.0.1.1 {h}" >> /etc/hosts; '
            'mkdir -p /etc/cloud/cloud.cfg.d 2>/dev/null; '
            'echo "preserve_hostname: true" > /etc/cloud/cloud.cfg.d/99-tricloud-hostname.cfg')


def manual_cmd(h):
    """给用户在 SSH 里手动执行的版本。"""
    return f"sudo sh -c '{build_cmd(h)}'"


def manual_result(display_name):
    """改名结果里的 hostname 块：面板只改显示名，系统主机名给手动命令（不下发任何命令）。"""
    h = normalize(display_name)
    if not h:
        return {"status": "unsupported", "hostname": None,
                "message": "名称规范化后为空（只保留 a-z 0-9 -），无法生成主机名命令"}
    return {"status": "manual", "hostname": h,
            "message": "已修改显示名。面板不自动同步系统主机名——SSH 登录实例后执行下面的命令，即可把主机名改成一致",
            "manual_cmd": manual_cmd(h)}
