"""v1.5：实例改名后同步系统主机名（SSH 登录看到的 hostname）。

只通过云厂商自带的 Run Command API 在实例内执行一条**固定命令**，不走 SSH / 远程控制台：
- Azure：virtual_machines.begin_run_command（RunShellScript，仅 Linux）
- OCI：先更新主 VNIC 的 hostname_label（内网 DNS 名），再用 Oracle Cloud Agent「Compute Instance Run Command」插件执行
- AWS EC2：SSM send_command（AWS-RunShellScript），实例需被 SSM 托管
- Lightsail：不支持改名，也不同步

主机名一律先经 normalize() 规范化、再经 validate() 严格校验（只允许 a-z 0-9 -），绝不把用户原始输入拼进命令。
同步是尽力而为的：改名本身照常成功，结果里带 hostname: {status: ok|pending|unsupported|failed, message, manual_cmd}。
"""
import re

_VALID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# OCI Run Command 插件默认以 ocarun 用户执行，需要 sudo 免密（Oracle 官方文档给出的做法）
OCI_SUDO_HINT = ('OCI Run Command 默认以 ocarun 用户执行，需在实例内允许其免密 sudo：'
                 'echo "ocarun ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/101-oracle-cloud-agent-run-command')


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


def root_wrap(h):
    """包成 sh -c '…'：命令里只有双引号，h 只含 [a-z0-9-]，单引号包裹是安全的。
    非 root（OCI 的 ocarun）用 sudo -n 提权。"""
    c = build_cmd(h)
    return f"if [ \"$(id -u)\" = 0 ]; then sh -c '{c}'; else sudo -n sh -c '{c}'; fi"


def manual_cmd(h):
    """给用户在 SSH 里手动执行的版本。"""
    return f"sudo sh -c '{build_cmd(h)}'"


def result(status, message, h=None, with_manual=True):
    r = {"status": status, "message": message}
    if h and with_manual and status != "ok":
        r["manual_cmd"] = manual_cmd(h)
    return r


def err_text(e):
    """云 SDK 异常 → 短文本。"""
    msg = getattr(e, "message", None) or str(e)
    code = getattr(e, "code", None) or getattr(e, "status", None) or ""
    s = f"{code} {msg}".strip() if code and str(code) not in str(msg) else str(msg)
    return s[:300]


def sync(acc, prov, inst_id, display_name, kind="vm", wait=None):
    """改名成功后调用。返回 hostname 结果 dict；绝不抛异常。"""
    h = normalize(display_name)
    if not h:
        return result("unsupported", "名称规范化后为空（只保留 a-z 0-9 -），已跳过主机名同步", None)
    if acc["provider"] == "aws" and kind == "lightsail":
        return result("unsupported", "Lightsail 实例不支持改名，不同步主机名", None)
    fn = getattr(prov, "sync_hostname", None)
    if fn is None:
        return result("unsupported", "该云暂不支持主机名同步", h)
    try:
        kw = {} if wait is None else {"wait": wait}
        r = fn(inst_id, h, **kw) or {}
    except Exception as e:   # 兜底：任何异常都降级为手动命令
        return result("failed", f"同步主机名失败：{err_text(e)}", h)
    r.setdefault("status", "pending")
    r.setdefault("message", "")
    if r["status"] != "ok" and "manual_cmd" not in r and r.get("_manual", True):
        r["manual_cmd"] = manual_cmd(h)
    r.pop("_manual", None)
    r["hostname"] = h
    return r
