import SwiftUI

/// 总览（Web pageHome）：到期提醒、账号健康度、各账号实例数，点进入管理。
final class HomePage: Page {
    override init() {
        super.init()
        title = "总览"
    }

    override var menu: [(String, () -> Void)] {
        [("添加云账号", { self.openAddAccount() }),
         ("批量添加账号", { self.openBatchAdd() }),
         ("一键测活", { self.testAll() })]
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

        for p in MainPage.PROVS {
            let list = (0..<a.count).map { a.obj($0) }.filter { $0.optString("provider") == p }
            if list.isEmpty { continue }
            section(MainPage.pname(p))
            for acc in list {
                let region = p == "azure" || p == "greencloud" ? "" : Prefs.get("region_\(acc.optInt("id"))", str(acc, "region", ""))
                let age = HomePage.ageDays(acc)
                let headDetail = (region.isEmpty ? "" : region + " · ") + (age.isEmpty ? "" : age + " · ")
                let off = acc.optInt("disabled") == 1
                let n = nav(Brand.icon(p), acc.optString("name") + (off ? "（已停用）" : ""), headDetail + "实例读取中…",
                            tint: off ? .gray : Brand.color(p)) {
                    self.push(AccountPage(acc))
                }
                if off {
                    n.detail.text = headDetail + "已停用"
                    continue
                }
                let q = region.isEmpty ? "" : "&region=" + enc(region)
                Api.call("GET", "/accounts/\(acc.optInt("id"))/instances?kind=vm" + q, nil) { res in
                    switch res {
                    case .success(let x):
                        let l = jarr(x)
                        let run = (0..<l.count).filter { l.obj($0).optString("state").lowercased() == "running" }.count
                        n.detail.text = headDetail + "\(l.count) 台（运行 \(run)）"
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
            if a.isEmpty {
                self.card("还没有云账号").muted("点击下方按钮添加 OCI / AWS / Azure / GreenCloud 账号，支持粘贴控制台内容自动识别。")
            }
            for p in MainPage.PROVS {
                let list = (0..<a.count).map { a.obj($0) }.filter { $0.optString("provider") == p }
                if list.isEmpty { continue }
                self.section(MainPage.pname(p) + " · \(list.count)")
                for acc in list {
                    let off = acc.optInt("disabled") == 1
                    var d = p == "azure" || p == "greencloud" ? "" : str(acc, "region", "-")
                    if off { d += (d.isEmpty ? "" : " · ") + "已停用" }
                    else if !acc.isNull("last_test_ok") {
                        d += (d.isEmpty ? "" : " · ") + (acc.optInt("last_test_ok") == 1 ? "连通 \(acc.optInt("last_test_ms")) ms" : "测活失败")
                    }
                    self.nav(Brand.icon(p), acc.optString("name"), d, tint: off ? .gray : Brand.color(p)) {
                        self.push(AccountPage(acc))
                    }
                }
            }
            self.section("管理")
            self.nav("key.fill", "云账号管理", "测活、编辑、代理、类型、停用、删除", tint: .blue) { self.push(MainPage()) }
            self.nav("square.stack.3d.up.fill", "批量添加", "随手复制的内容混贴，自动拆分多个账号", tint: .indigo) { self.openBatchAdd() }
            self.nav("trash.fill", "已删账号", tint: .gray) { self.push(DeletedPage()) }
            self.bigButton("＋ 添加云账号") { self.openAddAccount() }
        }
    }
}
