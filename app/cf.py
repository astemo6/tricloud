"""Cloudflare DNS 联动：实例换公网 IP 后自动更新对应 A 记录。

Token 存在 meta 表（key: cf_api_token），Fernet 加密——与 tg_bot_token
模式一致：加密存、只返回是否已设置、不回显明文。
DNS 更新走 Cloudflare REST API（urllib 直调，无额外依赖）。
"""
import base64
import json
import logging
import urllib.parse
import urllib.request

from . import db
from .crypto import decrypt_secret, encrypt_secret

log = logging.getLogger(__name__)

CF_API = "https://api.cloudflare.com/client/v4"
_TIMEOUT = 15


# ---------- Token 存取 ----------
def set_token(token: str) -> None:
    """加密保存 Cloudflare API Token（只存 meta，不回显）。"""
    db.meta_set("cf_api_token", base64.b64encode(
        encrypt_secret(token)).decode("ascii"))


def get_token() -> str:
    """解密读取 Token（仅供 Cloudflare API 调用使用，绝不回显给前端）。"""
    raw = db.meta_get("cf_api_token")
    if not raw:
        return ""
    try:
        return decrypt_secret(base64.b64decode(raw))
    except Exception as e:  # noqa: BLE001 - 解密失败按未配置处理
        log.warning("cf_api_token decrypt failed: %s", e)
        return ""


def token_configured() -> bool:
    return bool(get_token())


# ---------- Cloudflare API ----------
def _api(method: str, path: str, payload: dict | None = None) -> dict:
    token = get_token()
    if not token:
        raise RuntimeError("未配置 Cloudflare API Token")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(CF_API + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _zone_id(zone_name: str) -> str:
    resp = _api("GET", "/zones?name=" + urllib.parse.quote(zone_name))
    if not resp.get("success"):
        raise RuntimeError("查询 zone 失败: " + str(resp.get("errors") or resp))
    zones = resp.get("result") or []
    if not zones:
        raise RuntimeError(f"zone 不存在或无权限访问: {zone_name}")
    return zones[0]["id"]


def _record(zone_id: str, record_name: str) -> dict:
    resp = _api("GET", "/zones/%s/dns_records?type=A&name=%s"
                % (zone_id, urllib.parse.quote(record_name)))
    if not resp.get("success"):
        raise RuntimeError("查询 DNS 记录失败: " + str(resp.get("errors") or resp))
    records = resp.get("result") or []
    if not records:
        raise RuntimeError(f"A 记录不存在: {record_name}")
    return records[0]


def update_a_record(zone_name: str, record_name: str, new_ip: str) -> None:
    """把 zone 下指定 A 记录的 content 更新为新 IP。失败抛异常。"""
    zone_id = _zone_id(zone_name)
    rec = _record(zone_id, record_name)
    if rec.get("content") == new_ip:
        return
    resp = _api("PUT", f"/zones/{zone_id}/dns_records/{rec['id']}", {
        "type": "A",
        "name": record_name,
        "content": new_ip,
        "ttl": rec.get("ttl") or 1,
        "proxied": bool(rec.get("proxied")),
    })
    if not resp.get("success"):
        raise RuntimeError("更新 DNS 记录失败: " + str(resp.get("errors") or resp))


# ---------- 换 IP 联动 ----------
def sync_dns(ctx, instance_id: str, new_ip: str) -> None:
    """换 IP 成功后，按 DNS 映射（dns_mappings 表）更新 Cloudflare A 记录。

    任何失败只记日志，绝不抛异常、不阻断换 IP 主流程。
    """
    try:
        if not instance_id or not new_ip:
            return
        account_id = None
        job_id = getattr(ctx, "job_id", None)
        if job_id:
            job = db.job_get(job_id)
            if job:
                account_id = job.get("account_id")
        mappings = db.dns_mappings_for_instance(account_id, instance_id)
        if not mappings:
            return
        for m in mappings:
            try:
                update_a_record(m["zone_name"], m["record_name"], new_ip)
                log.info("cloudflare dns updated: %s (%s) -> %s",
                         m["record_name"], m["zone_name"], new_ip)
            except Exception as e:  # noqa: BLE001 - 单条失败继续下一条
                log.warning("cloudflare dns update failed for %s.%s: %s",
                            m["record_name"], m["zone_name"], e)
    except Exception as e:  # noqa: BLE001 - 绝不阻断换 IP 主流程
        log.warning("cloudflare dns sync failed: %s", e)
