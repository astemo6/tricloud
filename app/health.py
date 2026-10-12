"""v1.2 账号健康度：把「快被回收 / 被封 / 被限制」的早期迹象汇总成 0–100 分。

只用免费的只读 API（不调 AWS Cost Explorer，账单只读缓存）。每天定时跑一次，也可手动刷新；
分数比上次下降 ≥15 或跌到「危险」时推送 Telegram。
"""
import datetime as dt
import html
import json
import time

from . import core, services

DOWN = {"stopped", "deallocated", "terminated", "stopping", "deallocating"}


def level(score):
    return "good" if score >= 80 else ("warn" if score >= 50 else "bad")


LEVEL_TEXT = {"good": "健康", "warn": "注意", "bad": "危险"}


def _item(items, name, ok, detail, penalty=0):
    items.append({"name": name, "ok": ok, "detail": detail, "penalty": 0 if ok else penalty})


def compute(acc_id):
    acc = core.get_account(acc_id, with_cred=True)
    if not acc:
        raise KeyError("账号不存在")
    prev = core.q("SELECT * FROM account_health WHERE account_id=?", (acc_id,), one=True)
    prev_data = json.loads(prev["data"]) if prev else {}
    memo = dict(prev_data.get("memo") or {})
    items = []
    prov = services.provider(acc_id)

    # 1. 凭证 / 账号可用
    try:
        prov.test()
        _item(items, "凭证与账号状态", True, "API 调用正常")
        cred_ok = True
    except Exception as e:
        msg = str(e)[:160]
        hint = "凭证失效或账号被暂停/封禁" if any(k in msg for k in ("NotAuthenticated", "401", "403", "AuthFailure",
                                                                 "InvalidClientTokenId", "AuthorizationFailed", "disabled",
                                                                 "SubscriptionNotFound", "Suspended")) else "接口暂时不可用"
        _item(items, "凭证与账号状态", False, f"{hint}：{msg}", 50)
        cred_ok = False

    # 2. 实例列表 + 非面板操作导致的停机
    if cred_ok:
        try:
            insts = prov.list_instances()
            mons = {m["instance_id"]: m for m in core.q("SELECT * FROM monitors WHERE account_id=?", (acc_id,))}
            odd = [i["name"] for i in insts if i.get("state") in DOWN and i["id"] in mons
                   and not str(mons[i["id"]].get("last_state") or "").startswith("user:")]
            _item(items, "实例异常停机", not odd, "无" if not odd else "被动停机：" + "、".join(odd[:5]), min(30, 10 * len(odd)))
            gone = [n for iid, n in (memo.get("instances") or {}).items() if iid not in {i["id"] for i in insts}
                    and not core.q("SELECT 1 FROM tasks WHERE account_id=? AND params LIKE ? AND updated>?",
                                   (acc_id, f"%{iid}%", int(time.time()) - 86400 * 2))]
            _item(items, "实例消失", not gone, "无" if not gone else "上次还在、现在不见了：" + "、".join(gone[:5])
                  + "（可能被回收或删除）", min(30, 15 * len(gone)))
            memo["instances"] = {i["id"]: i["name"] for i in insts}
        except Exception as e:
            _item(items, "实例列表", False, f"读取失败：{str(e)[:120]}", 15)

    # 3. 近 24 小时任务失败（排除容量不足）
    since = int(time.time()) - 86400
    fails = core.q("SELECT message FROM tasks WHERE account_id=? AND status='failed' AND updated>?", (acc_id, since))
    fails = [f for f in fails if "容量" not in (f["message"] or "") and "capacity" not in (f["message"] or "").lower()]
    _item(items, "近 24 小时任务失败", not fails, f"{len(fails)} 次" if fails else "无", min(20, 5 * len(fails)))

    # 4. 各家专项
    if cred_ok and acc["provider"] == "oci":
        try:
            lim = {x["name"]: x for x in prov.limits()["items"]}
            a1 = next((v for k, v in lim.items() if "A1" in k and "OCPU" in k), None)
            if a1 is not None:
                was = memo.get("a1_limit")
                memo["a1_limit"] = a1["limit"]
                dropped = was and a1["limit"] < was
                _item(items, "A1 配额", a1["limit"] > 0 and not dropped,
                      f"上限 {a1['limit']} OCPU" + (f"（上次 {was}，被下调）" if dropped else "")
                      + ("；为 0 常见于账号受限或试用转换期" if a1["limit"] == 0 else ""), 30 if a1["limit"] == 0 else 20)
        except Exception as e:
            _item(items, "A1 配额", False, f"读取失败：{str(e)[:120]}", 5)
    if acc["provider"] == "aws":
        today = dt.date.today()
        soon = []
        for c in core.q("SELECT * FROM aws_credits WHERE account_id=? AND expire_date IS NOT NULL", (acc_id,)):
            try:
                d = (dt.date.fromisoformat(c["expire_date"]) - today).days
                if 0 <= d <= 30:
                    soon.append(f"{c['name']} 还剩 {d} 天")
            except ValueError:
                pass
        _item(items, "Credit 到期", not soon, "；".join(soon) if soon else "30 天内无到期", 5 * len(soon))
        cache = core.q("SELECT data FROM billing_cache WHERE account_id=?", (acc_id,), one=True)
        if cache:
            b = json.loads(cache["data"])
            rem = (b.get("credits") or {}).get("remaining")
            if rem is not None:
                _item(items, "Credit 余额", rem > 5, f"剩余 ${rem}（账单缓存）", 10)
    if cred_ok and acc["provider"] == "azure":
        try:
            from azure.mgmt.resource import SubscriptionClient
            st = SubscriptionClient(prov.credential, **prov.kw).subscriptions.get(prov.sub).state
            st = str(getattr(st, "value", st))
            _item(items, "订阅状态", st == "Enabled", st, 40 if st in ("Disabled", "Deleted") else 15)
        except Exception as e:
            _item(items, "订阅状态", False, f"读取失败：{str(e)[:120]}", 5)

    score = max(0, 100 - sum(i["penalty"] for i in items))
    data = {"items": items, "memo": memo}
    now = int(time.time())
    core.ex("INSERT OR REPLACE INTO account_health(account_id, score, data, checked_at) VALUES(?,?,?,?)",
            (acc_id, score, json.dumps(data, ensure_ascii=False), now))
    return {"account_id": acc_id, "name": acc["name"], "provider": acc["provider"], "score": score, "level": level(score),
            "items": items, "checked_at": now, "prev_score": prev["score"] if prev else None}


def list_cached():
    rows = {r["account_id"]: r for r in core.q("SELECT * FROM account_health")}
    out = []
    for a in core.list_accounts():
        r = rows.get(a["id"])
        d = json.loads(r["data"]) if r else {}
        out.append({"account_id": a["id"], "name": a["name"], "provider": a["provider"],
                    "score": r["score"] if r else None, "level": level(r["score"]) if r else None,
                    "items": d.get("items", []), "checked_at": r["checked_at"] if r else None})
    return out


def alert_text(r):
    """分数下降 ≥15 或进入危险时返回推送文本，否则 None。"""
    prev = r.get("prev_score")
    if not ((prev is not None and prev - r["score"] >= 15) or (r["level"] == "bad" and (prev is None or level(prev) != "bad"))):
        return None
    bad = [f"· {html.escape(i['name'])}：{html.escape(i['detail'])}" for i in r["items"] if not i["ok"]]
    return (f"🩺 <b>账号健康度下降</b>：{html.escape(r['name'])}\n{prev if prev is not None else '-'} → <b>{r['score']}</b>"
            f"（{LEVEL_TEXT[r['level']]}）\n" + "\n".join(bad[:6]))
