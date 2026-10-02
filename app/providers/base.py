"""Provider 统一接口：三家云都实现同一套方法，前端只认这一套。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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
