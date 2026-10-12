import SwiftUI

// AccountActivity：账单、Credit 与教育优惠（v1.4）、账号日期。

extension AccountPage {
    func billing(_ force: Bool) {
        let g = gen
        get("/accounts/\(id)/billing" + (force ? "?force=true" : "")) { r in
            guard self.cur(g) else { return }
            let b = jobj(r)
            let c = self.card("本月费用")
            let noCache = b.optBoolean("no_cache")
            c.text((noCache ? "—" : b.optString("total")) + " " + b.optString("currency"), 26, true)
            c.muted(b.optString("period") + " · 数据更新于 " + b.optString("updated_at"))
            if noCache { c.muted("尚无缓存：将在 " + b.optString("next_refresh") + " 自动查询，或手动刷新（收费）") }
            if self.prov == "aws" {
                c.muted("AWS 每月仅 15 号与月末自动查询（$0.01/次）。下次：" + b.optString("next_refresh") + "，本月已调用 \(b.optInt("ce_calls_this_month")) 次")
                c.row().button("手动刷新（约 $0.02）") {
                    self.confirm("手动刷新", "将调用 Cost Explorer API（$0.01/次）") { self.header(); self.billing(true) }
                }
            }
            let s = self.card("按服务")
            let sv = b.optJSONArray("services") ?? []
            var sb = ""
            for i in 0..<sv.count { sb += sv.obj(i).optString("service") + "：" + sv.obj(i).optString("amount") + "\n" }
            s.text(sb.isEmpty ? "本月暂无费用" : sb.trimmingCharacters(in: .whitespacesAndNewlines), 13)
            self.credits()
        }
    }

    static func money(_ o: JObj?, _ k: String) -> String {
        guard let o = o, !o.isNull(k) else { return "—" }
        let d = o.optDouble(k)
        return d.isNaN ? "—" : "$" + fmt2(d)
    }

    func credits() {
        let g = gen
        get("/accounts/\(id)/credit-summary") { r in
            guard self.cur(g) else { return }
            let s = jobj(r)
            let c = self.card("Credit 与优惠")
            let al = s.optJSONArray("alerts") ?? []
            for i in 0..<al.count {
                let a = al.obj(i)
                c.text("⏰ " + a.optString("name") + " " + (a.optInt("days_left") == 0 ? "今天到期" : "还剩 \(a.optInt("days_left")) 天")
                       + "（" + a.optString("date") + (a.optBoolean("estimated") ? "，估算" : "") + "）", 13, true)
            }
            let src = s.optString("used_source") == "manual" ? "手动填写" : s.optString("used_source") == "billing" ? "按账单估算" : "估不出"
            c.text("总额 " + AccountPage.money(s, "credit_total") + (s.optBoolean("credit_total_manual") ? "（手动设置）" : "") + "\n已用 " + AccountPage.money(s, "used")
                   + "（" + src + "）\n剩余 " + AccountPage.money(s, "remaining"), 15)
            c.muted("估算依据：" + str(s, "estimate_note", "-") + (self.prov == "aws" ? "。AWS 只读账单缓存，不额外调用 Cost Explorer。" : "。先到期的先抵扣。"))
            let items = s.optJSONArray("items") ?? []
            for i in 0..<items.count {
                let it = items.obj(i)
                let ic = self.card(it.optString("name"))
                var left = ""
                if !it.isNull("days_left") { left = it.optBoolean("expired") ? "（已过期）" : "（剩 \(it.optInt("days_left")) 天）" }
                ic.text("初始 " + AccountPage.money(it, "amount") + " · 已用 " + AccountPage.money(it, "used") + (it.optString("used_source") == "manual" ? "（手填）" : "")
                        + " · 剩余 " + AccountPage.money(it, "remaining") + "\n到期：" + str(it, "expire_date", "-") + left, 13)
                let ir = ic.row()
                let cid = it.optInt("id")
                ir.button("编辑") { self.creditForm(it) }
                ir.button("删除") {
                    self.confirm("删除 Credit", it.optString("name")) { self.del("/accounts/\(self.id)/credits-manual/\(cid)") { _ in self.refresh() } }
                }
            }
            let info = self.card("账号信息")
            info.text("云上创建：" + (s.isNull("cloud_created_at") ? "未填写" : s.optString("cloud_created_at") + "（已存活 \(s.optInt("age_days")) 天）"), 13)
            if let edu = s.optJSONObject("edu") {
                info.text("教育优惠到期：" + (edu.isNull("expires_at") ? "未知" : edu.optString("expires_at") + (edu.optBoolean("estimated") ? "（估算）" : "")
                          + " · 剩 \(edu.optInt("days_left")) 天") + "\n" + edu.optString("basis"), 13)
            }
            let br = c.row()
            br.button("＋ 添加 Credit") { self.creditForm(nil) }
            br.button("设置总额") {
                self.form("Credit 总额", "留空 = 各条 Credit 之和", [
                    Field.num("credit_total", "总额 USD", s.optBoolean("credit_total_manual") ? s.optString("credit_total") : "")], "保存") { vals in
                    self.request("PUT", "/accounts/\(self.id)/credit-total", vals) { _ in self.refresh() }
                }
            }
            info.row().button("设置日期") { self.datesForm(s) }
        }
    }

    func creditForm(_ it: JObj?) {
        let edit = it != nil
        let e = it ?? [:]
        form(edit ? "编辑 Credit" : "添加 Credit", "已用额度留空 = 按账单估算；30 天内到期会提醒并推送 Telegram", [
            Field.text("name", "名称", edit ? e.optString("name") : "Credit"),
            Field.num("amount", "初始额度 USD", edit ? e.optString("amount") : ""),
            Field.num("used_manual", "已用额度（可选）", edit && !e.isNull("used_manual") ? e.optString("used_manual") : ""),
            Field.text("start_date", "起始日期 YYYY-MM-DD（可选）", edit ? str(e, "start_date", "") : ""),
            Field.text("expire_date", "到期日期 YYYY-MM-DD", edit ? str(e, "expire_date", "") : "")], "保存") { vals in
            if edit { self.request("PUT", "/accounts/\(self.id)/credits-manual/\(e.optInt("id"))", vals) { _ in self.refresh() } }
            else { self.post("/accounts/\(self.id)/credits-manual", vals) { _ in self.refresh() } }
        }
    }

    func datesForm(_ s: JObj) {
        var f: [Field] = [Field.text("cloud_created_at", "云账号创建日期 YYYY-MM-DD", str(s, "cloud_created_at", ""))]
        if prov == "azure" { f.append(Field.text("edu_expires_at", "教育优惠到期日（留空 = 创建日期 + 12 个月估算）", str(acc, "edu_expires_at", ""))) }
        form("账号日期", "用于计算存活天数与教育优惠到期", f, "保存") { vals in
            self.request("PATCH", "/accounts/\(self.id)", vals) { _ in
                self.acc["cloud_created_at"] = vals.optString("cloud_created_at")
                if vals.has("edu_expires_at") { self.acc["edu_expires_at"] = vals.optString("edu_expires_at") }
                self.refresh()
            }
        }
    }
}
