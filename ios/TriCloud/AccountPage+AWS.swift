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

    /// 与 Web cfBytes 等价：1024 进制、1 位小数并去掉尾随 .0。
    static func cfBytes(_ n: Int64) -> String {
        var v = Double(n)
        let u = ["B", "KB", "MB", "GB", "TB"]
        var i = 0
        while v >= 1024 && i < 4 { v /= 1024; i += 1 }
        if i == 0 { return "\(n) B" }
        var s = String(format: "%.1f", v)
        if s.hasSuffix(".0") { s = String(s.dropLast(2)) }
        return s + " " + u[i]
    }

    func cloudfront() {
        bigButton("＋ 新建分发") {
            self.form("新建 CloudFront 分发", "部署约 5~15 分钟；默认与 v1.4 相同（不缓存 + 全部边缘节点）。开启后禁用缓存、转发全部请求头，适合 ws 节点套 CloudFront；回源端口只能是 80、443 或 1024–65535。", [
                Field.text("origin", "源站域名（不带 https:// 和路径）", ""),
                Field.select("origin_protocol", "回源协议", "http-only", ["http-only", "https-only", "match-viewer"], ["HTTP", "HTTPS", "跟随访客"]),
                Field.select("price_class", "价格等级", "all", ["all", "200", "100"], ["全部边缘节点", "200（含亚洲）", "100（北美+欧洲）"]),
                Field.select("plan_tier", "套餐", "PAYGO", AccountPage.CF_TIERS, AccountPage.CF_TIER_NAMES),
                Field.select("cache_mode", "缓存模式", "disabled", ["disabled", "optimized"], ["不缓存（反代动态内容）", "缓存优化（静态资源）"]),
                Field.check("compress", "自动压缩", true),
                Field.num("http_port", "HTTP 回源端口", "80"),
                Field.num("https_port", "HTTPS 回源端口", "443"),
                Field.select("ip_address_type", "源站 IP 类型", "ipv4", ["ipv4", "ipv6", "dualstack"], ["IPv4（默认）", "IPv6 only", "双栈"]),
                Field.check("ws_mode", "WebSocket 节点模式", false),
                Field.text("comment", "备注", "")], "创建") { vals in
                var b = vals
                b["op"] = "create"
                self.post("/accounts/\(self.id)/cloudfront", b) { x in
                    let o = jobj(x)
                    self.toast("已创建：" + o.optString("domain"))
                    self.refresh()
                    // 选了包月套餐：分发建好后接着订阅（同 Web）；付费档先确认，订阅失败只提示、不影响已建分发
                    let tier = vals.optString("plan_tier")
                    if tier.isEmpty || tier == "PAYGO" { return }
                    let paid = tier != "FREE"
                    let did = o.optString("id")
                    let go = {
                        self.post("/accounts/\(self.id)/cloudfront/plan", ["distribution_id": did, "plan_tier": tier, "confirm": paid]) { y in
                            self.toast(jobj(y).optString("message"))
                            self.refresh()
                        }
                    }
                    if paid {
                        let nm = AccountPage.CF_TIERS.firstIndex(of: tier).map { AccountPage.CF_TIER_NAMES[$0] } ?? tier
                        self.confirm("确认订阅付费套餐", "⚠️ 为分发 " + did + " 订阅 " + nm + "，将立即开始按月计费（价格以 AWS 官网为准）。", go)
                    } else { go() }
                }
            }
        }
        let g = gen
        get("/accounts/\(id)/cloudfront") { r in
            guard self.cur(g) else { return }
            let a = jarr(r)
            if a.isEmpty { self.card("暂无分发").muted("") }
            var cards: [String: Card] = [:]
            for i in 0..<a.count {
                let d = a.obj(i)
                let did = d.optString("id")
                let en = d.optBoolean("enabled")
                let c = self.card(did + "  [" + d.optString("status") + "]")
                cards[did] = c
                c.text(d.optString("domain") + "\n源站：" + join(d.optJSONArray("origins"))
                       + "\n" + (en ? "已启用" : "已停用") + " · " + AccountPage.cfPlanName(d) + " · 价格等级 " + str(d, "price_class", "-")
                       + (d.optString("comment").isEmpty ? "" : "\n" + d.optString("comment")), 13)
                let row = c.row()
                if self.cfInvBtn { row.button("缓存刷新") { self.cfInvalidate(did) } }
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
            // 已用流量：异步给每个分发卡片补一行（拉不到就静默不显示，同 Web）
            Api.call("GET", "/accounts/\(self.id)/cloudfront/traffic", nil) { res in
                guard self.cur(g) else { return }
                switch res {
                case .success(let tr):
                    guard let items = jobj(tr).optJSONObject("items") else { return }
                    for (did, c) in cards {
                        guard let it = items.optJSONObject(did) else { continue }
                        let total = it.optLong("total"), quota = it.optLong("quota_bytes")
                        let main = quota > 0 ? AccountPage.cfBytes(total) + " / " + AccountPage.cfBytes(quota) : AccountPage.cfBytes(total)
                        c.muted("已用流量 " + main + " · ↓ " + AccountPage.cfBytes(it.optLong("down")) + " · ↑ " + AccountPage.cfBytes(it.optLong("up")))
                        if it.has("total30d") { c.muted("近30天 " + AccountPage.cfBytes(it.optLong("total30d")))}
                    }
                case .failure:
                    break
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
            let hp = c.optInt("http_port"), sp = c.optInt("https_port")
            f.append(Field.num("http_port", "HTTP 回源端口", hp > 0 ? "\(hp)" : "80"))
            f.append(Field.num("https_port", "HTTPS 回源端口", sp > 0 ? "\(sp)" : "443"))
            f.append(Field.select("ip_address_type", "源站 IP 类型", str(c, "ip_address_type", "ipv4"), ["ipv4", "ipv6", "dualstack"], ["IPv4（默认）", "IPv6 only", "双栈"]))
            let wsOn = c.optBoolean("ws_mode")
            f.append(Field.check("ws_mode", wsOn ? "WebSocket 节点模式（已开启，不可关闭）" : "WebSocket 节点模式", wsOn))
            self.form("编辑分发 · " + did, "保存后重新部署，约几分钟生效。开启后禁用缓存、转发全部请求头，适合 ws 节点套 CloudFront；回源端口只能是 80、443 或 1024–65535。", f, "保存") { v in
                var vv = v
                if wsOn { vv["ws_mode"] = true }   // ws 只能开不能关（后端同语义）：已开启时强制保持
                self.request("PUT", "/accounts/\(self.id)/cloudfront/" + enc(did), vv) { x in
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
