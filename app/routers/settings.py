"""设置、Telegram 测试、开机脚本模板、默认创建参数。"""
import time

from fastapi import APIRouter, Body, HTTPException

from .. import core, security, tasks, telegram
from ..i18n import msg
from .common import VERSION

router = APIRouter()


# ---------------- 设置 ----------------
SETTING_KEYS = ("tg_chat_id", "daily_report", "report_time", "monitor_interval", "timezone", "default_create", "free_guard",
                "auto_ip_daily_limit")


@router.get("/api/settings")
def get_settings():
    s = {k: core.get_setting(k) for k in SETTING_KEYS}
    s["auto_ip_daily_limit"] = tasks.auto_ip_limit()
    tok = core.get_secret_setting("tg_token")
    s["tg_token_set"] = bool(tok)
    s["tg_token_hint"] = (tok.split(":")[0] + ":***") if tok else ""
    s["cf_token_set"] = bool(core.get_secret_setting("cf_token"))
    s["proxycheck_key_set"] = bool(core.get_secret_setting("proxycheck_key"))
    s["totp_enabled"] = security.totp_enabled()
    s["version"] = VERSION
    return s


@router.post("/api/settings")
def save_settings(body: dict = Body(...)):
    if "auto_ip_daily_limit" in body:
        try:
            body["auto_ip_daily_limit"] = int(body["auto_ip_daily_limit"])
        except (TypeError, ValueError):
            raise HTTPException(400, msg("err.auto_ip_int"))
        if not 0 <= body["auto_ip_daily_limit"] <= 50:
            raise HTTPException(400, msg("err.auto_ip_range"))
    for k in SETTING_KEYS:
        if k in body:
            core.set_setting(k, body[k])
    if body.get("tg_token"):
        core.set_secret_setting("tg_token", body["tg_token"].strip())
    if body.get("tg_token_clear"):
        core.set_secret_setting("tg_token", "")
    if body.get("cf_token"):
        core.set_secret_setting("cf_token", body["cf_token"].strip())
    if body.get("cf_token_clear"):
        core.set_secret_setting("cf_token", "")
    if body.get("proxycheck_key"):   # v1.6：IP 质量检测（proxycheck.io 免费 Key，可选）
        core.set_secret_setting("proxycheck_key", str(body["proxycheck_key"]).strip())
    if body.get("proxycheck_key_clear"):
        core.set_secret_setting("proxycheck_key", "")
    return {"ok": True}


@router.post("/api/settings/tg-test")
async def tg_test():
    ok = await telegram.send(telegram.L("tg.testMsg"))
    if not ok:
        raise HTTPException(400, msg("err.tg_send_failed"))
    return {"ok": True}


# ---------------- 开机脚本模板 ----------------
@router.get("/api/scripts")
def scripts():
    return core.q("SELECT * FROM scripts ORDER BY id")


@router.post("/api/scripts")
def save_script(body: dict = Body(...)):
    name, content = (body.get("name") or "").strip(), body.get("content") or ""
    if not name or not content.strip():
        raise HTTPException(400, msg("err.name_content_required"))
    if len(content) > 16000:
        raise HTTPException(400, msg("err.script_too_long"))
    if body.get("id"):
        core.ex("UPDATE scripts SET name=?, content=? WHERE id=?", (name, content, int(body["id"])))
        return {"id": int(body["id"])}
    return {"id": core.ex("INSERT INTO scripts(name,content,created) VALUES(?,?,?)", (name, content, int(time.time())))}


@router.delete("/api/scripts/{sid}")
def del_script(sid: int):
    core.ex("DELETE FROM scripts WHERE id=?", (sid,))
    return {"ok": True}


# ---------------- 默认创建参数（与「设置 → 默认创建参数」JSON 是同一份数据） ----------------
CREATE_DEFAULT_KINDS = ("oci", "aws", "lightsail", "azure")


CREATE_DEFAULT_DROP = ("password", "confirm", "confirm_overage", "region")


@router.get("/api/create-defaults/{provider}")
def create_defaults_get(provider: str):
    if provider not in CREATE_DEFAULT_KINDS:
        raise HTTPException(400, msg("err.provider_kinds", kinds="/".join(CREATE_DEFAULT_KINDS)))
    d = core.get_setting("default_create") or {}
    return (d.get(provider) if isinstance(d, dict) else None) or {}


@router.put("/api/create-defaults")
def create_defaults_put(body: dict = Body(...)):
    import json as _json
    prov, vals = body.get("provider"), body.get("defaults")
    if prov not in CREATE_DEFAULT_KINDS:
        raise HTTPException(400, msg("err.provider_kinds", kinds="/".join(CREATE_DEFAULT_KINDS)))
    if not isinstance(vals, dict):
        raise HTTPException(400, msg("err.defaults_object"))
    vals = {str(k): v for k, v in vals.items() if k not in CREATE_DEFAULT_DROP and not isinstance(v, (dict, list))}
    if len(_json.dumps(vals)) > 16000:
        raise HTTPException(400, msg("err.defaults_too_big"))
    d = core.get_setting("default_create") or {}
    d = dict(d) if isinstance(d, dict) else {}
    d[prov] = vals
    core.set_setting("default_create", d)
    return {"ok": True, "defaults": vals}
