"""三家云 provider 注册表。"""
from .base import Provider
from .oci_provider import OciProvider
from .aws_provider import AwsProvider
from .azure_provider import AzureProvider

_PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (OciProvider(), AwsProvider(), AzureProvider())
}


def get_provider(provider_id: str) -> Provider:
    try:
        return _PROVIDERS[provider_id]
    except KeyError:
        raise ValueError(f"未知的云厂商: {provider_id}") from None


def list_providers() -> list[Provider]:
    return list(_PROVIDERS.values())
