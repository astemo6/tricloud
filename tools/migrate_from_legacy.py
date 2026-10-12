#!/usr/bin/env python3
"""把旧版 TriCloud（线上无 git 的那一版，FastAPI + meta 表）的数据迁移到 TriCloud v1.5。

用法：
  python tools/migrate_from_legacy.py --legacy-db /old/data/tricloud.db --new-data /new/data --dry-run
  python tools/migrate_from_legacy.py --legacy-db /old/data/tricloud.db --new-data /new/data

- 旧库只用 SQLite URI 只读模式（mode=ro）打开，绝不写入。
- 旧密钥：--legacy-key（默认取旧库同目录的 fernet.key），或环境变量 FERNET_KEY。
- 新库：<new-data>/tricloud.db，新密钥 <new-data>/fernet.key（没有就生成）。凭证用旧密钥解密后用新密钥重新加密。
- 默认拒绝写入非空的新库（已有账号 / Credit / 审计 / 脚本 / DNS / 流量 / Token / 已删账号 任一表有数据）。
- --dry-run 只打印将迁移的条数和字段映射，不创建任何文件，也不打印任何凭证内容。
- 不迁移：sessions、jobs、login_attempts（以及面板密码 / TOTP，见 MAPPING_NOTES）。

字段映射来自旧版 app/db.py（建表 SQL）、app/providers/{oci,aws,azure}_provider.py（AccountField / creds[...]）、
app/main.py 与 app/cf.py / app/tg.py（meta 键名），对照本仓库 app/providers/*.py 的凭证字段。
"""
import argparse
import base64
import datetime as dt
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parent.parent

# 旧凭证 JSON 键 -> 本面板凭证键（None = 不迁移）
CRED_MAP = {
    "oci": {"tenancy_ocid": "tenancy", "user_ocid": "user", "private_key": "key_content", "fingerprint": "fingerprint",
            "region": "region", "default_ssh_key": "default_ssh_key", "default_subnet_ocid": "default_subnet_ocid"},
    "aws": {"access_key": "access_key", "secret_key": "secret_key", "region": "region"},
    "azure": {"client_id": "client_id", "client_secret": "client_secret", "tenant_id": "tenant_id",
              "subscription_id": "subscription_id"},
}
# 旧版 accounts 表上的代理列 -> 本面板凭证键（加密进 cred_enc）
PROXY_MAP = {"proxy_url": "proxy", "proxy_user": "proxy_user", "proxy_pass_enc（解密）": "proxy_pass"}
# 本面板必填（与 app/main.py REQUIRED 一致）
REQUIRED = {
    "oci": ["user", "tenancy", "fingerprint", "key_content", "region"],
    "aws": ["access_key", "secret_key", "region"],
    "azure": ["tenant_id", "client_id", "client_secret", "subscription_id"],
}
TABLE_MAP = [
    ("accounts", "accounts", "id 保留；creds_enc 解密→字段改名→新密钥加密；created_at→created；cloud_created_at/edu_expires_at "
                             "时间戳→YYYY-MM-DD；credit_total 原样；proxy_* 并入凭证"),
    ("account_credits", "aws_credits", "name/amount 原样；start_at→start_date，expires_at→expire_date（YYYY-MM-DD）；ce_baseline 不迁移"),
    ("audit_log", "audit", "ts/ip/action/detail 原样，actor='legacy'"),
    ("script_templates", "scripts", "name/content/created_at；os_type=windows 时名称加「[Windows] 」前缀"),
    ("dns_mappings", "dns_bindings", "account_id/instance_id/zone_name；record_name→record；zone_id 留空（首次同步时按 zone_name 查询）；仅 A 记录"),
    ("traffic_rules", "traffic_guards", "mode=rolling；instance_key→instance_id；instance_name→name（空则用规则名）；metric→direction；"
                                        "window_hours/limit_gb/enabled 原样；duration_hours→shutdown_hours；action=stop；状态重置为 ok"),
    ("api_tokens", "api_tokens", "token_hash 原样（sha256 十六进制，与本面板相同算法）；prefix='legacy'；scope readonly→read、full→full"),
    ("recycle_bin", "deleted_accounts", "provider/name/lifecycle_days；est_cost_usd→est_cost（USD）；deleted_at；source='legacy'"),
    ("password_vault + instance_passwords", "instance_secrets", "开机密码：旧密钥解密→新密钥加密"),
    ("meta: tg_bot_token / tg_chat_id", "settings: tg_token（加密）/ tg_chat_id", "旧版 tg_bot_token 为明文，迁移后用新密钥加密"),
    ("meta: cf_api_token", "settings: cf_token（加密）", "旧版为 base64(Fernet 密文)，旧密钥解密后新密钥加密"),
    ("meta: create_defaults_<provider>", "settings: default_create[<provider>]", "JSON 原样"),
    ("meta: daily_report / daily_report_hour / monitor_interval_min", "settings: daily_report / report_time / monitor_interval",
     "\"1\"→true；小时 H→\"HH:00\"；分钟数原样"),
]
MAPPING_NOTES = [
    "不迁移 sessions、jobs、login_attempts（按要求）。",
    "不迁移面板密码（旧版 PBKDF2 hex + 独立 salt，格式不同）：新版首次启动用 PANEL_PASSWORD 设定。",
    "不迁移 TOTP 二次验证：迁移后请在新版重新绑定。",
    "不迁移 billing_cache（旧版 AWS 账单缓存结构不同）与 ip_change_daily（每日计数，次日自然清零）。",
    "旧版账号级 monitor_alert / monitor_restart / monitor_ip_check / auto_change_ip 不迁移："
    "新版监控按实例设置，需在实例卡片上「监控」重新开启。",
]
NONEMPTY_TABLES = ("accounts", "aws_credits", "audit", "scripts", "dns_bindings", "traffic_guards", "api_tokens",
                   "deleted_accounts", "instance_secrets")


class MigrateError(Exception):
    pass


def open_legacy(path):
    p = Path(path).resolve()
    if not p.is_file():
        raise MigrateError(f"旧库不存在：{p}")
    conn = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def legacy_fernet(args, legacy_db):
    if args.legacy_key:
        key = Path(args.legacy_key).read_bytes().strip()
    elif os.environ.get("FERNET_KEY"):
        key = os.environ["FERNET_KEY"].strip().encode()
    else:
        kp = Path(legacy_db).resolve().parent / "fernet.key"
        if not kp.is_file():
            raise MigrateError("找不到旧密钥：请用 --legacy-key 指定，或设置环境变量 FERNET_KEY")
        key = kp.read_bytes().strip()
    try:
        return Fernet(key)
    except Exception:
        raise MigrateError("旧密钥格式不正确（应为 Fernet base64 密钥）")


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _rows(conn, table):
    if table not in _tables(conn):
        return []
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def _meta(conn):
    if "meta" not in _tables(conn):
        return {}
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}


def _dec(f, blob):
    if blob in (None, b"", ""):
        return None
    if isinstance(blob, str):
        blob = blob.encode()
    try:
        return f.decrypt(bytes(blob)).decode("utf-8")
    except InvalidToken:
        raise MigrateError("旧密钥无法解密旧库中的数据：请确认 fernet.key / FERNET_KEY 与旧库匹配")


def _date(ts, tz):
    if ts in (None, "", 0):
        return None
    try:
        return dt.datetime.fromtimestamp(float(ts), tz).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def map_cred(provider, legacy_creds, proxy):
    """旧凭证 dict + 代理 -> (新凭证 dict, 未映射的旧键名列表)。只处理键名，不打印值。"""
    m = CRED_MAP[provider]
    out, dropped = {}, []
    for k, v in (legacy_creds or {}).items():
        if k in ("proxy_url", "proxy_user", "proxy_pass"):
            continue   # 旧版代理独立存列，这里以列为准
        if k not in m:
            dropped.append(k)
            continue
        if isinstance(v, str):
            v = v if k == "private_key" else v.strip()
        if v in (None, ""):
            continue
        if k == "private_key":
            v = v.replace("\\n", "\n").strip() + "\n"   # 旧版允许粘贴带字面 \n 的私钥
        out[m[k]] = v
    if proxy.get("proxy_url"):
        out["proxy"] = proxy["proxy_url"].strip()
        if proxy.get("proxy_user"):
            out["proxy_user"] = proxy["proxy_user"].strip()
        if proxy.get("proxy_pass"):
            out["proxy_pass"] = proxy["proxy_pass"]
    return out, dropped


def collect(conn, f, tz):
    """读旧库并转换成新库的行（内存中），同时生成不含凭证的摘要。"""
    meta = _meta(conn)
    plan = {"accounts": [], "credits": [], "audit": [], "scripts": [], "dns": [], "traffic": [], "tokens": [],
            "deleted": [], "secrets": [], "settings": {}, "secret_settings": {}, "summary": [], "warnings": []}
    acc_ids = set()
    for a in _rows(conn, "accounts"):
        prov = a["provider"]
        if prov not in CRED_MAP:
            plan["warnings"].append(f"账号 #{a['id']} 云厂商 {prov} 不支持，跳过")
            continue
        creds = json.loads(_dec(f, a["creds_enc"]) or "{}")
        proxy = {"proxy_url": a.get("proxy_url") or "", "proxy_user": a.get("proxy_user") or "",
                 "proxy_pass": _dec(f, a.get("proxy_pass_enc")) if a.get("proxy_pass_enc") else ""}
        cred, dropped = map_cred(prov, creds, proxy)
        miss = [k for k in REQUIRED[prov] if not cred.get(k)]
        if miss:
            plan["warnings"].append(f"账号 #{a['id']}（{a['name']}）缺少字段 {', '.join(miss)}，仍会迁移，请迁移后在面板补全")
        plan["accounts"].append({"id": a["id"], "provider": prov, "name": a["name"], "region": cred.get("region"), "cred": cred,
                                 "created": int(a.get("created_at") or 0) or None,
                                 "cloud_created_at": _date(a.get("cloud_created_at"), tz),
                                 "credit_total": a.get("credit_total"), "edu_expires_at": _date(a.get("edu_expires_at"), tz)})
        acc_ids.add(a["id"])
        plan["summary"].append({"id": a["id"], "provider": prov, "name": a["name"], "fields": sorted(cred),
                                "dropped": sorted(dropped), "proxy": bool(proxy["proxy_url"]),
                                "proxy_auth": bool(proxy["proxy_user"] or proxy["proxy_pass"])})
    for c in _rows(conn, "account_credits"):
        if c["account_id"] not in acc_ids:
            continue
        plan["credits"].append({"account_id": c["account_id"], "name": c["name"], "amount": c["amount"],
                                "start_date": _date(c.get("start_at"), tz), "expire_date": _date(c.get("expires_at"), tz)})
    for r in _rows(conn, "audit_log"):
        plan["audit"].append({"ts": int(r["ts"] or 0), "ip": r.get("ip") or "", "action": r["action"],
                              "detail": (r.get("detail") or "")[:500]})
    for r in _rows(conn, "script_templates"):
        name = r["name"] if (r.get("os_type") or "linux") == "linux" else f"[Windows] {r['name']}"
        plan["scripts"].append({"name": name, "content": r.get("content") or "", "created": int(r.get("created_at") or 0)})
    for r in _rows(conn, "dns_mappings"):
        if r["account_id"] not in acc_ids:
            continue
        plan["dns"].append({"account_id": r["account_id"], "instance_id": r["instance_id"], "zone_name": r["zone_name"],
                            "record": r["record_name"]})
    for r in _rows(conn, "traffic_rules"):
        if r["account_id"] not in acc_ids:
            continue
        metric = r.get("metric") if r.get("metric") in ("out", "in", "both") else "out"
        plan["traffic"].append({"account_id": r["account_id"], "instance_id": r["instance_key"],
                                "name": r.get("instance_name") or r.get("name") or r["instance_key"],
                                "limit_gb": float(r["limit_gb"]), "window_hours": int(r.get("window_hours") or 24),
                                "direction": metric, "enabled": 1 if r.get("enabled", 1) else 0,
                                "shutdown_hours": float(r.get("duration_hours") or 0), "rule_name": r.get("name")})
    for r in _rows(conn, "api_tokens"):
        h = (r.get("token_hash") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", h):
            plan["warnings"].append(f"API Token #{r['id']} 的哈希不是 sha256 十六进制，跳过")
            continue
        plan["tokens"].append({"name": (r.get("name") or "legacy")[:40], "token_hash": h,
                               "scope": "full" if r.get("scope") == "full" else "read",
                               "created": int(r.get("created_at") or 0), "last_used": int(r.get("last_used_at") or 0)})
    for r in _rows(conn, "recycle_bin"):
        plan["deleted"].append({"provider": r["provider"], "name": r["name"], "lifecycle_days": r.get("lifecycle_days"),
                                "est_cost": r.get("est_cost_usd"), "deleted_at": int(r.get("deleted_at") or 0)})
    for r in _rows(conn, "password_vault"):
        plan["secrets"].append({"account_id": r.get("account_id"), "instance_id": r["instance_id"],
                                "name": r.get("instance_name") or "", "username": "root",
                                "password": _dec(f, r["password_enc"]), "created": int(r.get("created_at") or 0)})
    seen = {(s["instance_id"], s["password"]) for s in plan["secrets"]}
    for r in _rows(conn, "instance_passwords"):
        pw = _dec(f, r["password_enc"])
        if (r["instance_id"], pw) in seen:
            continue
        plan["secrets"].append({"account_id": r.get("account_id"), "instance_id": r["instance_id"], "name": "",
                                "username": r.get("username") or "root", "password": pw, "created": int(r.get("created_at") or 0)})
    # ---- meta 设置（键名取自旧版 app/tg.py、app/cf.py、app/main.py、app/monitor.py）----
    if meta.get("tg_bot_token"):
        plan["secret_settings"]["tg_token"] = meta["tg_bot_token"].strip()
    if meta.get("tg_chat_id"):
        plan["settings"]["tg_chat_id"] = meta["tg_chat_id"].strip()
    if meta.get("cf_api_token"):
        try:
            plan["secret_settings"]["cf_token"] = _dec(f, base64.b64decode(meta["cf_api_token"]))
        except (ValueError, TypeError):
            plan["warnings"].append("meta.cf_api_token 格式无法识别，跳过")
    dc = {}
    for k, v in meta.items():
        if k.startswith("create_defaults_"):
            try:
                val = json.loads(v or "{}")
            except ValueError:
                continue
            if isinstance(val, dict) and val:
                dc[k[len("create_defaults_"):]] = val
    if dc:
        plan["settings"]["default_create"] = dc
    if "daily_report" in meta:
        plan["settings"]["daily_report"] = meta["daily_report"] == "1"
    if (meta.get("daily_report_hour") or "").isdigit():
        plan["settings"]["report_time"] = f"{max(0, min(23, int(meta['daily_report_hour']))):02d}:00"
    if (meta.get("monitor_interval_min") or "").isdigit():
        plan["settings"]["monitor_interval"] = max(1, int(meta["monitor_interval_min"]))
    return plan


def print_plan(plan, legacy_conn):
    t = _tables(legacy_conn)
    skipped = {k: len(_rows(legacy_conn, k)) for k in ("sessions", "jobs", "login_attempts") if k in t}
    print("== 将迁移的条数 ==")
    for label, key in (("accounts → accounts", "accounts"), ("account_credits → aws_credits", "credits"),
                       ("audit_log → audit", "audit"), ("script_templates → scripts", "scripts"),
                       ("dns_mappings → dns_bindings", "dns"), ("traffic_rules → traffic_guards", "traffic"),
                       ("api_tokens → api_tokens", "tokens"), ("recycle_bin → deleted_accounts", "deleted"),
                       ("password_vault/instance_passwords → instance_secrets", "secrets")):
        print(f"  {label:<55} {len(plan[key])}")
    print(f"  {'设置（明文项）':<52} {', '.join(sorted(plan['settings'])) or '-'}")
    print(f"  {'设置（加密项）':<52} {', '.join(sorted(plan['secret_settings'])) or '-'}")
    print("  不迁移：" + "，".join(f"{k} {n} 条" for k, n in skipped.items()) if skipped else "  不迁移：sessions / jobs / login_attempts")
    print("\n== 凭证字段映射（旧 → 新）==")
    for prov, m in CRED_MAP.items():
        print(f"  [{prov}] " + "，".join(f"{a}→{b}" for a, b in m.items()))
    print("  [代理] " + "，".join(f"{a}→{b}" for a, b in PROXY_MAP.items()))
    print("\n== 表映射 ==")
    for a, b, how in TABLE_MAP:
        print(f"  {a} → {b}：{how}")
    print("\n== 账号（只列字段名，不含任何凭证值）==")
    for s in plan["summary"]:
        print(f"  #{s['id']} {s['provider']} {s['name']}：字段 {', '.join(s['fields'])}"
              + (f"；代理{'（含账密）' if s['proxy_auth'] else ''}" if s["proxy"] else "")
              + (f"；未映射的旧字段 {', '.join(s['dropped'])}" if s["dropped"] else ""))
    for w in plan["warnings"]:
        print("  ⚠ " + w)
    print("\n== 说明 ==")
    for n in MAPPING_NOTES:
        print("  · " + n)


def check_new_empty(new_data):
    db = Path(new_data) / "tricloud.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    try:
        have = _tables(conn)
        return [f"{t}={n}" for t in NONEMPTY_TABLES if t in have
                for n in [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]] if n]
    finally:
        conn.close()


def write_new(plan, new_data):
    os.environ["TRICLOUD_DATA"] = str(Path(new_data).resolve())
    sys.path.insert(0, str(ROOT))
    from app import core   # 按新数据目录初始化（建表 + 新密钥）
    core.init_db()
    core.fernet()
    with core.db() as c:
        for a in plan["accounts"]:
            c.execute("INSERT INTO accounts(id,provider,name,region,cred_enc,created,cloud_created_at,credit_total,edu_expires_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (a["id"], a["provider"], a["name"], a["region"], core.encrypt(a["cred"]), a["created"],
                       a["cloud_created_at"], a["credit_total"], a["edu_expires_at"]))
        for x in plan["credits"]:
            c.execute("INSERT INTO aws_credits(account_id,name,amount,start_date,expire_date) VALUES(?,?,?,?,?)",
                      (x["account_id"], x["name"], x["amount"], x["start_date"], x["expire_date"]))
        for x in plan["audit"]:
            c.execute("INSERT INTO audit(ts,ip,actor,action,detail) VALUES(?,?,?,?,?)",
                      (x["ts"], x["ip"], "legacy", x["action"], x["detail"]))
        for x in plan["scripts"]:
            c.execute("INSERT INTO scripts(name,content,created) VALUES(?,?,?)", (x["name"], x["content"], x["created"]))
        for x in plan["dns"]:
            c.execute("INSERT OR IGNORE INTO dns_bindings(account_id,instance_id,name,zone_id,zone_name,record,proxied,v4,v6) "
                      "VALUES(?,?,?,?,?,?,0,1,0)", (x["account_id"], x["instance_id"], x["record"], "", x["zone_name"], x["record"]))
        for x in plan["traffic"]:
            c.execute("INSERT OR IGNORE INTO traffic_guards(account_id,instance_id,kind,name,limit_gb,action,mode,window_hours,"
                      "direction,enabled,shutdown_hours,state,month) VALUES(?,?,'vm',?,?,'stop','rolling',?,?,?,?,'ok',NULL)",
                      (x["account_id"], x["instance_id"], x["name"], x["limit_gb"], x["window_hours"], x["direction"],
                       x["enabled"], x["shutdown_hours"]))
        for x in plan["tokens"]:
            c.execute("INSERT OR IGNORE INTO api_tokens(name,token_hash,prefix,scope,created,last_used) VALUES(?,?,'legacy',?,?,?)",
                      (x["name"], x["token_hash"], x["scope"], x["created"], x["last_used"]))
        for x in plan["deleted"]:
            c.execute("INSERT INTO deleted_accounts(provider,name,lifecycle_days,age_basis,est_cost,currency,cost_basis,deleted_at,source) "
                      "VALUES(?,?,?,?,?,'USD',?,?,'legacy')",
                      (x["provider"], x["name"], x["lifecycle_days"], "旧版记录", x["est_cost"], "旧版记录（删除时的本月账单）",
                       x["deleted_at"]))
        for x in plan["secrets"]:
            c.execute("INSERT INTO instance_secrets(account_id,instance_id,name,username,password_enc,created) VALUES(?,?,?,?,?,?)",
                      (x["account_id"], x["instance_id"], x["name"], x["username"], core.encrypt(x["password"]), x["created"]))
        for k, v in plan["settings"].items():
            c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))
        for k, v in plan["secret_settings"].items():
            c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(core.encrypt(v))))
    return core.DB_PATH


def main(argv=None):
    ap = argparse.ArgumentParser(description="旧版 TriCloud → v1.5 数据迁移（旧库只读）")
    ap.add_argument("--legacy-db", required=True, help="旧库 tricloud.db 路径")
    ap.add_argument("--legacy-key", help="旧 fernet.key 路径（默认旧库同目录；也可用环境变量 FERNET_KEY）")
    ap.add_argument("--new-data", required=True, help="新数据目录（写入 tricloud.db 与 fernet.key）")
    ap.add_argument("--tz", default="Asia/Shanghai", help="时间戳转日期用的时区（默认 Asia/Shanghai）")
    ap.add_argument("--dry-run", action="store_true", help="只打印条数和字段映射，不写入，不打印凭证")
    args = ap.parse_args(argv)
    try:
        legacy = open_legacy(args.legacy_db)
        f = legacy_fernet(args, args.legacy_db)
        plan = collect(legacy, f, ZoneInfo(args.tz))
        nonempty = check_new_empty(args.new_data)
        print_plan(plan, legacy)
        legacy.close()
        if nonempty:
            print(f"\n✖ 新库不是空库（{', '.join(nonempty)}），拒绝写入。请换一个空的数据目录。")
            return 2
        if args.dry_run:
            print("\n（dry-run：未写入任何文件）")
            return 0
        path = write_new(plan, args.new_data)
        print(f"\n✔ 迁移完成：{path}")
        return 0
    except MigrateError as e:
        print(f"✖ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
