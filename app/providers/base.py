"""Provider 统一接口：三家云都实现同一套方法，前端只认这一套。"""
import ipaddress
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# 换 IP 目标网段功能：换到新 IP 后校验，不符合则重试的最多次数
IP_CHANGE_MAX_ATTEMPTS = 5


def parse_cidr_spec(cidr):
    """解析换 IP 的目标网段参数。

    格式：'192.0.2.0/24' 表示新 IP 必须落在该网段内；
    '!192.0.2.0/24' 表示排除该网段（新 IP 不得落在其中）。
    返回 (is_exclude, ip_network)；cidr 为空时返回 None（走原有逻辑）。
    非法 CIDR 格式直接抛 ValueError。
    """
    if cidr is None:
        return None
    spec = str(cidr).strip()
    if not spec:
        return None
    exclude = spec.startswith("!")
    raw = spec[1:] if exclude else spec
    try:
        net = ipaddress.ip_network(raw, strict=False)
    except ValueError:
        raise ValueError(
            f"网段格式不正确: 「{spec}」，应为 CIDR 格式"
            f"（如 192.0.2.0/24，排除网段加 ! 前缀）")
    return exclude, net


def proxy_settings(creds: dict) -> dict | None:
    """从账号 creds 提取代理设置（由 db 层注入）。

    返回 {"http": url, "https": url} 映射（requests / botocore /
    azure-core 通用的原生格式）；未配置代理时返回 None，
    调用方保持原有直连行为。
    代理用户名/密码以 URL 嵌入方式传递（各 SDK 原生支持的格式）。
    """
    url = (creds.get("proxy_url") or "").strip()
    if not url:
        return None
    user = (creds.get("proxy_user") or "").strip()
    password = creds.get("proxy_pass") or ""
    if user:
        from urllib.parse import quote, urlparse, urlunparse
        parsed = urlparse(url)
        if parsed.hostname and "@" not in parsed.netloc:
            auth = f"{quote(user, safe='')}:{quote(str(password), safe='')}@"
            url = urlunparse(parsed._replace(netloc=auth + parsed.netloc))
    return {"http": url, "https": url}


def spec_desc(spec) -> str:
    """网段要求的中文描述，用于日志和异常说明。"""
    if spec is None:
        return "任意网段"
    exclude, net = spec
    return f"{'排除' if exclude else '目标'}网段 {net}"


def ip_in_spec(ip: str, spec) -> bool:
    """判断 IP 是否符合网段要求（spec 为 None 时恒为 True，保持原有行为）。"""
    if spec is None or not ip:
        return True
    exclude, net = spec
    try:
        inside = ipaddress.ip_address(ip) in net
    except ValueError:
        return False
    return not inside if exclude else inside


@dataclass
class InstanceInfo:
    id: str
    name: str
    status: str            # 归一化：running|stopped|pending|stopping|terminated|unknown
    status_text: str = ""  # 云厂商原始状态
    shape: str = ""
    cpu: str = ""
    memory: str = ""
    public_ip: str = ""
    private_ip: str = ""
    ipv6: str = ""
    region: str = ""
    zone: str = ""
    created: str = ""
    extra: dict = field(default_factory=dict)  # 操作需要的原始 id（vnic_id 等）


@dataclass
class AccountField:
    key: str
    label: str
    field_type: str = "text"   # text|password|textarea
    required: bool = True
    placeholder: str = ""
    help: str = ""


class Provider(ABC):
    id: str = ""
    name: str = ""
    fields: list[AccountField] = []
    actions: list[dict] = []        # [{"key": "start", "label": "启动", "danger": False}]
    supports_snatch: bool = False
    supports_billing: bool = False  # 是否支持查看账单
    supports_quotas: bool = False   # 是否支持配额查询
    supports_subscription: bool = False  # 是否支持订阅信息查询（OCI）

    @abstractmethod
    def test(self, creds: dict) -> None:
        """连通性测试，失败抛异常。"""

    @abstractmethod
    def list_instances(self, creds: dict) -> list[InstanceInfo]:
        """列出实例。"""

    @abstractmethod
    def instance_action(self, creds: dict, inst: InstanceInfo, action: str, ctx) -> str:
        """执行实例操作，返回结果文本。ctx: JobCtx（log/should_stop）。"""

    @abstractmethod
    def create_options(self, creds: dict) -> dict:
        """返回创建实例对话框需要的选项（地域/规格/镜像等）。"""

    @abstractmethod
    def create_instance(self, creds: dict, params: dict, ctx) -> str:
        """创建实例，返回结果文本（含一次性密码等敏感信息）。"""

    def snatch_instance(self, creds: dict, params: dict, ctx) -> str:
        raise NotImplementedError("该云厂商不支持抢机")

    def get_billing(self, creds: dict) -> dict:
        """查看账单，返回统一结构：
        {"currency": "USD", "period": "...", "total": 12.34,
         "services": [{"name": "...", "cost": 1.23}], "note": "..."}
        """
        raise NotImplementedError("该云厂商不支持查看账单")

    def get_quotas(self, creds: dict) -> dict:
        """配额查询，返回统一结构：
        {"groups": [{"title": "...", "items": [{"name": "...", "detail": "..."}]}],
         "note": "..."}
        """
        raise NotImplementedError("该云厂商不支持配额查询")

    def get_subscription(self, creds: dict) -> dict:
        """订阅信息查询，返回 {"items": [{"name": "...", "detail": "..."}], "note": "..."}。"""
        raise NotImplementedError("该云厂商不支持订阅信息查询")
