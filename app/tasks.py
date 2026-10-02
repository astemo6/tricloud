"""后台任务的实际执行函数：供 API 和 Telegram Bot 共用。"""
from . import db, jobs
from .providers import get_provider
from .providers.base import InstanceInfo


def job_action(ctx, provider_id: str, account_id: int, inst_dict: dict, action: str, params: dict):
    provider = get_provider(provider_id)
    acc = db.account_get(account_id)
    if not acc:
        raise ValueError("账号不存在")
    inst = InstanceInfo(**{k: v for k, v in inst_dict.items()
                           if k in InstanceInfo.__dataclass_fields__})
    if provider_id == "oci" and action == "update_shape":
        return provider.update_shape(
            acc["creds"], inst.id, params.get("shape"),
            float(params["ocpus"]) if params.get("ocpus") else None,
            float(params["memory_gbs"]) if params.get("memory_gbs") else None,
            ctx)
    ctx.log(f"执行操作: {action} / {inst.name}")
    return provider.instance_action(acc["creds"], inst, action, ctx)


def job_create(ctx, provider_id: str, account_id: int, params: dict):
    provider = get_provider(provider_id)
    acc = db.account_get(account_id)
    if not acc:
        raise ValueError("账号不存在")
    params["_account_id"] = account_id
    return provider.create_instance(acc["creds"], params, ctx)


def job_snatch(ctx, provider_id: str, account_id: int, params: dict):
    provider = get_provider(provider_id)
    acc = db.account_get(account_id)
    if not acc:
        raise ValueError("账号不存在")
    params["_account_id"] = account_id
    return provider.snatch_instance(acc["creds"], params, ctx)


def submit_action(provider_id: str, account_id: int, inst_dict: dict,
                  action: str, params: dict, title: str) -> str:
    return jobs.submit("action", provider_id, account_id, title,
                       job_action, provider_id, account_id, inst_dict, action, params)
