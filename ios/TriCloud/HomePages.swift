import SwiftUI

/// 总览（Web pageHome）：到期提醒、账号健康度、各账号实例数，点进入管理。
final class HomePage: Page {
    private var forceScan = false   // 「重新扫描区域」：下一次刷新带 refresh=true

    override init() {
        super.init()
        title = "总览"
    }

    func rescan() {
        forceScan = true
        toast("正在重新扫描所有区域…")
        refresh()
    }

    override var menu: [(String, () -> Void)] {
        [("添加云账号", { self.openAddAccount() }),
         ("批量添加账号", { self.openBatchAdd() }),
         ("一键测活", { self.testAll() }),
         ("重新扫描区域", { self.rescan() })]
    }

    override func refresh() {
        get("/accounts") { r in
            let a = jarr(r)
            AppState.shared.setAccounts(a)
            let group = DispatchGroup()
            var alerts: JArr = []
            var health: JArr? = nil
            group.enter()
            Api.call("GET", "/expiry-alerts", nil) { res in
                if case .success(let x) = res { alerts = jarr(x) }
                group.leave()
            }
            group.enter()
            Api.call("GET", "/account-health", nil) { res in
                if case .success(let x) = res { health = jarr(x) }
                group.leave()
            }
            group.notify(queue: .main) { self.build(a, alerts, health) }
        }
    }

    private func build(_ a: JArr, _ alerts: JArr, _ health: JArr?) {
        clear()
        if a.isEmpty {
            card("还没有云账号").muted("添加 Oracle Cloud / AWS / Azure 账号后，这里会显示各账号的实例数、健康度和到期提醒。")
            bigButton("＋ 添加云账号") { self.openAddAccount() }
            return
        }
        var by: [String: Int] = [:]
        for i in 0..<a.count { by[a.obj(i).optString("provider"), default: 0] += 1 }
        let sum = card("\(a.count) 个云账号")
        sum.muted(MainPage.PROVS.filter { (by[$0] ?? 0) > 0 }.map { MainPage.pname($0) + " \(by[$0] ?? 0)" }.joined(separator: " · "))
        let qr = sum.row()
        qr.button("⚡ 一键测活") { self.testAll() }
        qr.button("免费额度体检") { self.push(FreeCheckPage()) }
        qr.button("流量守护") { self.push(TrafficPage()) }

        if !alerts.isEmpty {
            let c = card("⏰ 30 天内到期")
            for i in 0..<alerts.count {
                let x = alerts.obj(i)
                let left = x.optInt("days_left") == 0 ? "今天到期" : "剩 \(x.optInt("days_left")) 天"
                c.text((x.optInt("days_left") <= 7 ? "🔴 " : "🟠 ") + x.optString("account_name") + " · " + x.optString("name") + "  " + left, 14, true)
                c.muted(x.optString("date") + (x.optBoolean("estimated") ? "（估算）" : ""))
            }
        }

        let hc = card("🩺 账号健康度")
        if let h = health {
            if h.isEmpty { hc.muted("还没有检测记录") }
            var lines: [String] = []
            for i in 0..<h.count {
                let x = h.obj(i)
                let s = x.isNull("score") ? "未检测" : "\(x.optInt("score")) 分 · " + HealthPage.level(x.optInt("score"))
                let dot = x.isNull("score") ? "⚪️" : x.optInt("score") >= 80 ? "🟢" : x.optInt("score") >= 50 ? "🟠" : "🔴"
                lines.append(dot + " " + x.optString("name") + "  " + s)
            }
            if !lines.isEmpty { hc.text(lines.joined(separator: "\n"), 14) }
        } else {
            hc.muted("读取失败")
        }
        hc.row().button("查看详情") { self.push(HealthPage()) }

        let ov = card("🖥 实例（全部区域）")
        ov.muted("按账号所有区域统计（AWS 含 EC2 + Lightsail），30 分钟内用缓存")
        ov.row().button("↻ 重新扫描区域") { self.rescan() }
        let force = forceScan
        forceScan = false

        for p in MainPage.PROVS {
            let list = (0..<a.count).map { a.obj($0) }.filter { $0.optString("provider") == p }
            if list.isEmpty { continue }
            section(MainPage.pname(p))
            for acc in list {
                let region = p == "azure" ? "" : Regions.current(acc)
                let age = HomePage.ageDays(acc)
                let headDetail = (region.isEmpty ? "" : Regions.label(region) + " · ") + (age.isEmpty ? "" : age + " · ")
                let off = acc.optInt("disabled") == 1
                let n = nav(Brand.icon(p), acc.optString("name") + (off ? "（已停用）" : ""), headDetail + "实例读取中…",
                            tint: off ? .gray : Brand.color(p)) {
                    self.push(AccountPage(acc))
                }
                if off {
                    n.detail.text = headDetail + "已停用"
                    continue
                }
                // 后端 /overview 统计所有有机器的区域（AWS EC2+Lightsail 全区域、OCI 订阅区域、Azure 整个订阅），带缓存
                Api.call("GET", "/accounts/\(acc.optInt("id"))/overview" + (force ? "?refresh=true" : ""), nil) { res in
                    switch res {
                    case .success(let x):
                        let o = jobj(x)
                        Regions.apply(acc.optInt("id"), o)   // build 25：账号列表 / 打开账号的默认区域同步更新
                        let rs = o.optJSONArray("regions")
                        let brief = Regions.brief(rs)
                        let dr = o.isNull("default_region") ? region : o.optString("default_region")
                        let where_ = !brief.isEmpty ? brief : (dr.isEmpty ? "" : Regions.label(dr))
                        let multi = (rs?.count ?? 0) > 1
                        n.detail.text = (where_.isEmpty ? "" : where_ + " · ") + (age.isEmpty ? "" : age + " · ") + Regions.count(o)
                            + (multi ? "\n分布：" + Regions.dist(rs) : "")
                    case .failure(let e):
                        n.detail.text = headDetail + "查询失败：" + String(((e as? ApiError)?.msg ?? e.localizedDescription).prefix(60))
                    }
                }
            }
        }
    }

    static func ageDays(_ acc: JObj) -> String {
        let d = str(acc, "cloud_created_at", "")
        if d.isEmpty { return "" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        guard let date = f.date(from: String(d.prefix(10))) else { return "" }
        return "存活 \(Int(floor(Date().timeIntervalSince(date) / 86400))) 天"
    }

    func testAll() {
        toast("正在并发测活…")
        post("/accounts/test-all", nil) { r in
            let o = jobj(r)
            let rs = o.optJSONArray("results") ?? []
            var sb = ""
            for i in 0..<rs.count {
                let x = rs.obj(i)
                sb += (x.optBoolean("ok") ? "✅ " : "❌ ") + x.optString("name") + "  \(x.optInt("ms")) ms"
                if !x.optBoolean("ok") { sb += "\n    " + str(x, "error", "") }
                sb += "\n"
            }
            self.message("测活：\(o.optInt("ok"))/\(o.optInt("total")) 连通", sb.trimmingCharacters(in: .whitespacesAndNewlines),
                         cancel: "好的", onCancel: { self.accountsChanged() })
        }
    }
}

/// 账号：按云分组列出各账号（Web 侧栏 OCI / AWS / Azure 分组）。
final class AccountsPage: Page {
    override init() {
        super.init()
        title = "账号"
    }

    override var menu: [(String, () -> Void)] {
        [("添加云账号", { self.openAddAccount() }),
         ("批量添加账号", { self.openBatchAdd() }),
         ("云账号管理", { self.push(MainPage()) }),
         ("已删账号", { self.push(DeletedPage()) })]
    }

    override func refresh() {
        get("/accounts") { r in
            let a = jarr(r)
            AppState.shared.setAccounts(a)
            self.clear()
            var items: [Int: (NavItem, JObj)] = [:]
            if a.isEmpty {
                self.card("还没有云账号").muted("点击下方按钮添加 OCI / AWS / Azure 账号，支持粘贴控制台内容自动识别。")
            }
            for p in MainPage.PROVS {
                let list = (0..<a.count).map { a.obj($0) }.filter { $0.optString("provider") == p }
                if list.isEmpty { continue }
                self.section(MainPage.pname(p) + " · \(list.count)")
                for acc in list {
                    let off = acc.optInt("disabled") == 1
                    let n = self.nav(Brand.icon(p), acc.optString("name"), AccountsPage.detail(acc), tint: off ? .gray : Brand.color(p)) {
                        self.push(AccountPage(acc))
                    }
                    items[acc.optInt("id")] = (n, acc)
                }
            }
            self.section("管理")
            self.nav("key.fill", "云账号管理", "测活、编辑、代理、类型、停用、删除", tint: .blue) { self.push(MainPage()) }
            self.nav("square.stack.3d.up.fill", "批量添加", "随手复制的内容混贴，自动拆分多个账号", tint: .indigo) { self.openBatchAdd() }
            self.nav("trash.fill", "已删账号", tint: .gray) { self.push(DeletedPage()) }
            self.bigButton("＋ 添加云账号") { self.openAddAccount() }
            // build 25：还没有区域记录 / 记录过期的账号，逐个（一次一个）查总览后更新这一行
            Regions.refreshHints((0..<a.count).map { a.obj($0) }) { id in
                if let it = items[id] { it.0.detail.text = AccountsPage.detail(it.1) }
            }
        }
    }

    /// 账号行副标题：有机器的区域（没有机器 / 还没扫描时注明默认区域）· 连通 / 已停用。
    static func detail(_ acc: JObj) -> String {
        var d = Regions.accountText(acc)
        if acc.optInt("disabled") == 1 { d += (d.isEmpty ? "" : " · ") + "已停用" }
        else if !acc.isNull("last_test_ok") {
            d += (d.isEmpty ? "" : " · ") + (acc.optInt("last_test_ok") == 1 ? "连通 \(acc.optInt("last_test_ms")) ms" : "测活失败")
        }
        return d
    }
}
