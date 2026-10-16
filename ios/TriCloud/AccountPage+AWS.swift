import SwiftUI

// AccountActivity：CloudFront（缓存刷新 / 编辑 / 启停 / 套餐 / 删除前自动停用）、配额、闲置资源估算。

extension AccountPage {
    static let CF_TIERS = ["PAYGO", "FREE", "PRO", "BUSINESS", "PREMIUM"]
    static let CF_TIER_NAMES = ["按量付费", "Free $0/月", "Pro $15/月", "Business $200/月", "Premium $1000/月起"]

    static func cfPlanName(_ d: JObj) -> String {
        if d.isNull("plan") { return "套餐未知" }
        if let i = CF_TIERS.firstIndex(of: d.optString("plan")) { return CF_TIER_NAMES[i] }
        return d.optString("plan")
    }

    func cloudfront() {
        bigButton("＋ 新建分发") {
            self.form("新建 CloudFront 分发", "部署约 5~15 分钟；默认与 v1.4 相同（不缓存 + 全部边缘节点）", [
                Field.text("origin", "源站域名（不带 https:// 和路径）", ""),
                Field.select("origin_protocol", "回源协议", "http-only", ["http-only", "https-only", "match-viewer"], ["HTTP", "HTTPS", "跟随访客"]),
                Field.select("price_class", "价格等级", "all", ["all", "200", "100"], ["全部边缘节点", "200（含亚洲）", "100（北美+欧洲）"]),
                Field.select("cache_mode", "缓存模式", "disabled", ["disabled", "optimized"], ["不缓存（反代动态内容）", "缓存优化（静态资源）"]),
                Field.check("compress", "自动压缩", true),
                Field.text("comment", "备注", "")], "创建") { vals in
                var b = vals
                b["op"] = "create"
                self.post("/accounts/\(self.id)/cloudfront", b) { x in self.toast("已创建：" + jobj(x).optString("domain")); self.refresh() }
            }
        }
        let g = gen
        get("/accounts/\(id)/cloudfront") { r in
            guard self.cur(g) else { return }
            let a = jarr(r)
            if a.isEmpty { self.card("暂无分发").muted("") }
            for i in 0..<a.count {
                let d = a.obj(i)
                let did = d.optString("id")
                let en = d.optBoolean("enabled")
                let c = self.card(did + "  [" + d.optString("status") + "]")
                c.text(d.optString("domain") + "\n源站：" + join(d.optJSONArray("origins"))
                       + "\n" + (en ? "已启用" : "已停用") + " · " + AccountPage.cfPlanName(d) + " · 价格等级 " + str(d, "price_class", "-")
                       + (d.optString("comment").isEmpty ? "" : "\n" + d.optString("comment")), 13)
                let row = c.row()
                row.button("缓存刷新") { self.cfInvalidate(did) }
                row.button("编辑") { self.cfEdit(did) }
                row.button(en ? "停用" : "启用") {
                    self.confirm(en ? "停用分发" : "启用分发", en ? "停用后该域名将无法访问（配置保留，可再启用）。" : "启用 " + did + "？") {
                        self.post("/accounts/\(self.id)/cloudfront/toggle", ["distribution_id": did, "enabled": !en]) { x in
                            self.toast(jobj(x).optString("message"))
                            self.refresh()
                        }
                    }
                }
                row.button("套餐") { self.cfPlan(d) }
                row.button("删除") {
                    let busy = en || d.optString("status") != "Deployed"
                    let msg = busy ? "⚠️ 删除 " + did + "？它当前" + (en ? "仍在启用" : "正在部署") + "：面板会先停用、等待部署完成（通常 5~20 分钟）再自动删除。不可恢复。"
                        : "⚠️ 删除 " + did + "？不可恢复。"
                    self.confirm("删除分发", msg) {
                        self.del("/accounts/\(self.id)/cloudfront/" + enc(did) + "?confirm=true") { x in
                            let o = jobj(x)
                            if o.optBoolean("deleted") { self.toast("已删除") } else { self.taskOrToast(x, "已创建删除任务") }
                            self.refresh()
                        }
                    }
                }
            }
        }
    }

    func cfInvalidate(_ did: String) {
        form("缓存刷新 · " + did, "每行一条路径，留空 = /*。每月前 1000 条免费，/* 只算 1 条。", [Field.multi("paths", "路径", "/*")], "提交刷新") { v in
            self.post("/accounts/\(self.id)/cloudfront/invalidate", ["distribution_id": did, "paths": v.optString("paths")]) { x in
                let o = jobj(x)
                self.toast("已提交刷新 " + o.optString("invalidation_id") + "：" + join(o.optJSONArray("paths")))
            }
        }
    }

    func cfEdit(_ did: String) {
        get("/accounts/\(id)/cloudfront/" + enc(did) + "/config") { r in
            let c = jobj(r)
            var f: [Field] = [
                Field.text("comment", "备注", c.optString("comment")),
                Field.text("origin_domain", "源站域名", c.optString("origin_domain")),
                Field.select("price_class", "价格等级", c.optString("price_class"), ["100", "200", "All"], nil),
                Field.text("default_root_object", "默认根对象", c.optString("default_root_object"))]
            if !c.optString("origin_protocol").isEmpty {
                f.append(Field.select("origin_protocol", "回源协议", c.optString("origin_protocol"), ["http-only", "https-only", "match-viewer"], nil))
            }
            self.form("编辑分发 · " + did, "保存后重新部署，约几分钟生效", f, "保存") { v in
                self.request("PUT", "/accounts/\(self.id)/cloudfront/" + enc(did), v) { x in
                    self.toast(jobj(x).optString("message"))
                    self.refresh()
                }
            }
        }
    }

    func cfPlan(_ d: JObj) {
        let did = d.optString("id")
        choose("切换套餐（当前：" + AccountPage.cfPlanName(d) + "）", AccountPage.CF_TIER_NAMES) { i in
            let tier = AccountPage.CF_TIERS[i]
            let paid = i >= 2
            let go = {
                self.post("/accounts/\(self.id)/cloudfront/plan", ["distribution_id": did, "plan_tier": tier, "confirm": paid]) { x in
                    self.toast(jobj(x).optString("message"))
                    self.refresh()
                }
            }
            if paid {
                self.confirm("确认订阅付费套餐", "⚠️ 为分发 " + did + " 订阅 " + AccountPage.CF_TIER_NAMES[i] + "，将立即开始按月计费（价格以 AWS 官网为准）。", go)
            } else { go() }
        }
    }

    // MARK: - 配额

    func quota(_ force: Bool) {
        card("正在逐区域查询…").muted("串行查询以避免限流，约 10–30 秒，结果缓存 6 小时")
        let g = gen
        get("/accounts/\(id)/quotas" + (force ? "?refresh=true" : "")) { r in
            guard self.cur(g) else { return }
            self.header()
            let q = jobj(r)
            let v = q.optJSONObject("standard_vcpu"), cf = q.optJSONObject("cloudfront_distributions")
            let c1 = self.card("Standard vCPU 上限")
            c1.text(v == nil ? "-" : v!.optString("value") + " " + v!.optString("unit"), 26, true)
            c1.muted("全区域最大值，来自 " + (v == nil ? "-" : Regions.label(v!.optString("region"))) + "（L-1216C47A）")
            let c2 = self.card("CloudFront 分发数上限")
            c2.text(cf == nil ? "-" : str(cf, "value", "-") + " " + cf!.optString("unit"), 26, true)
            c2.muted("每账号（L-24B04930）· 更新于 " + q.optString("updated_at"))
            self.bigButton("重新查询") { self.header(); self.quota(true) }
        }
    }

    // MARK: - 闲置资源估算

    func recycle() {
        card("正在扫描闲置资源…").muted("仅用免费的 EC2/Lightsail API；账单数据只读缓存，不调用 Cost Explorer")
        let g = gen
        get("/accounts/\(id)/recycle?" + rq()) { r in
            guard self.cur(g) else { return }
            self.header()
            let d = jobj(r)
            let items = d.optJSONArray("items") ?? []
            let n = items.count
            let c = self.card("闲置资源月费估算")
            c.text("$" + d.optString("monthly_total"), 26, true)
            c.muted("区域 " + Regions.label(d.optString("region")) + " · \(n) 项 · 按公示单价估算，实际以账单为准")
            let b = self.card("账单参考（缓存）")
            b.text(d.isNull("month_to_date") ? "—" : "$" + d.optString("month_to_date"), 22, true)
            b.muted("本月已产生 · 数据更新于 " + d.optString("billing_updated_at"))
            if !d.isNull("credit_remaining") {
                let m = d.isNull("credit_months_for_idle") ? "" : "，仅闲置资源可再扣约 " + d.optString("credit_months_for_idle") + " 个月"
                b.muted("Credit 余 $" + d.optString("credit_remaining") + m)
            }
            if n == 0 { self.card("明细").muted("没有闲置计费资源"); return }
            for i in 0..<n {
                let it = items.obj(i)
                let ic = self.card(it.optString("name") + "  $" + it.optString("monthly") + "/月")
                ic.muted(it.optString("detail"))
                ic.muted(it.optString("tip"))
            }
        }
    }
}
