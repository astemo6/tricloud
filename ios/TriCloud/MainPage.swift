import SwiftUI

/// 云账号管理（Web pageAccounts）：测活、信息、类型、编辑（含代理）、停用、删除。
final class MainPage: Page {
    static let PROVS = ["oci", "aws", "azure"]
    static let PNAMES = ["Oracle Cloud", "AWS", "Azure"]

    static let CRED_LABEL: [String: String] = [
        "user": "用户 OCID", "tenancy": "租户 OCID", "fingerprint": "API Key 指纹", "key_content": "私钥 (PEM)", "pass_phrase": "私钥密码", "region": "区域",
        "compartment": "区间 OCID（可选）", "home_region": "主区域（可选）", "access_key": "Access Key ID", "secret_key": "Secret Access Key",
        "tenant_id": "Tenant ID", "client_id": "Client (App) ID", "client_secret": "Client Secret", "subscription_id": "Subscription ID"]

    static func pname(_ p: String) -> String {
        if let i = PROVS.firstIndex(of: p) { return PNAMES[i] }
        return p
    }

    override init() {
        super.init()
        title = "云账号"
    }

    override var menu: [(String, () -> Void)] {
        [("添加云账号", { self.openAddAccount() }),
         ("批量添加账号", { self.openBatchAdd() }),
         ("已删账号", { self.push(DeletedPage()) })]
    }

    override func refresh() {
        get("/accounts") { r in
            self.clear()
            let a = jarr(r)
            AppState.shared.setAccounts(a)
            if a.count > 0 {
                let top = self.row()
                top.button("⚡ 一键测活") { self.testAll() }
                top.button("到期提醒") { self.expiry() }
                top.button("批量添加") { self.openBatchAdd() }
            }
            if a.isEmpty { self.card("还没有云账号").muted("点击下方按钮添加 OCI / AWS / Azure 账号") }
            for i in 0..<a.count {
                let acc = a.obj(i)
                let aid = acc.optInt("id")
                let c = self.card(acc.optString("name") + (acc.optInt("disabled") == 1 ? "  [已停用]" : ""))
                let proxy = str(acc, "proxy", "").isEmpty ? "" : "\n代理 " + acc.optString("proxy") + (str(acc, "proxy_user", "").isEmpty ? "" : " · " + acc.optString("proxy_user"))
                c.muted(MainPage.pname(acc.optString("provider")) + " · " + str(acc, "region", "-") + MainPage.typeOf(acc) + MainPage.ageOf(acc) + MainPage.testOf(acc) + proxy)
                let row = c.row()
                row.button("管理") { self.push(AccountPage(acc)) }
                row.button("测活") {
                    self.post("/accounts/\(aid)/test", nil) { x in
                        let o = jobj(x)
                        self.toast(o.optBoolean("ok") ? "✅ 连通 · \(o.optInt("ms")) ms" : "❌ " + str(o, "error", "失败"))
                        self.refresh()
                    }
                }
                row.button("编辑") { self.editAccount(acc) }
                // v1.6：账号类型 / 被封号一键停用（不测活、不监控、停止任务；凭证保留，可再启用）
                row.button("信息") { self.editAccountInfo(acc) { self.accountsChanged() } }
                row.button("类型") { self.showAccountType(aid, acc.optString("name"), false) }
                let off = acc.optInt("disabled") == 1
                row.button(off ? "启用" : "停用") {
                    if off {
                        self.post("/accounts/\(aid)/disable", ["disabled": false]) { _ in self.toast("已启用"); self.accountsChanged() }
                        return
                    }
                    self.form("停用账号", "停用「" + acc.optString("name") + "」（比如被封号）：不再测活、不监控、不跑流量守护，运行中的任务全部停止；凭证和云上资源不动，可随时启用。",
                              [Field.text("reason", "原因（可选，如 被封号 / 欠费）", "")], "停用") { v in
                        self.post("/accounts/\(aid)/disable", ["disabled": true, "reason": v.optString("reason")]) { x in
                            let st = jobj(x).optJSONArray("stopped_tasks") ?? []
                            self.toast("已停用" + (st.isEmpty ? "" : "，停止了 \(st.count) 个任务"))
                            self.accountsChanged()
                        }
                    }
                }
                row.button("删除") {
                    self.confirm("删除账号", "仅从面板删除凭证，不影响云资源。删除记录会留在「已删账号」里。") {
                        self.del("/accounts/\(aid)") { _ in self.accountsChanged() }
                    }
                }
            }
            self.bigButton("＋ 添加云账号") { self.openAddAccount() }
        }
    }

    /// v1.6：缓存的账号类型（点「类型」查询后显示）。
    static func typeOf(_ acc: JObj) -> String {
        let raw = str(acc, "acct_type", "")
        guard let d = raw.data(using: .utf8), let t = (try? JSONSerialization.jsonObject(with: d)) as? JObj, !str(t, "label", "").isEmpty else { return "" }
        return " · " + t.optString("label") + (t.isNull("age_days") ? "" : " · \(t.optInt("age_days")) 天")
    }

    static func ageOf(_ acc: JObj) -> String {
        let d = str(acc, "cloud_created_at", "")
        if d.isEmpty { return "" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        guard let date = f.date(from: String(d.prefix(10))) else { return "" }
        let days = Int(floor(Date().timeIntervalSince(date) / 86400))
        return "\n云上创建 \(d) · 已存活 \(days) 天"
    }

    static func testOf(_ acc: JObj) -> String {
        if acc.isNull("last_test_ok") { return "" }
        return acc.optInt("last_test_ok") == 1 ? "\n连通 · \(acc.optInt("last_test_ms")) ms" : "\n测活失败：" + str(acc, "last_test_error", "")
    }

    /// v1.4 一键测活：并发测试全部账号，显示每个账号是否连通及耗时。
    private func testAll() {
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
                         cancel: "好的", onCancel: { self.refresh() })
        }
    }

    /// v1.4 30 天内到期的 Credit / 教育优惠。
    private func expiry() {
        get("/expiry-alerts") { r in
            let a = jarr(r)
            var sb = ""
            for i in 0..<a.count {
                let x = a.obj(i)
                sb += "⏰ " + x.optString("account_name") + " · " + x.optString("name") + "\n    " + x.optString("date")
                sb += (x.optBoolean("estimated") ? "（估算）" : "") + "，" + (x.optInt("days_left") == 0 ? "今天到期" : "剩 \(x.optInt("days_left")) 天") + "\n"
            }
            self.message("30 天内到期", sb.isEmpty ? "没有即将到期的 Credit 或优惠" : sb.trimmingCharacters(in: .whitespacesAndNewlines))
        }
    }

    /// v1.5 编辑账号：非敏感字段回显，密钥类留空不改；代理地址 / 用户名 / 密码分开填写。
    private func editAccount(_ acc: JObj) {
        let aid = acc.optInt("id")
        get("/accounts/\(aid)/detail") { r in
            let d = jobj(r)
            let fields = d.optJSONObject("fields") ?? [:]
            var f: [Field] = [Field.text("name", "备注名称", d.optString("name"))]
            let keys = fields.keys.sorted()
            for k in keys {
                if let o = fields[k] as? JObj {
                    let hint = o.optString("hint")
                    let lab = (MainPage.CRED_LABEL[k] ?? k) + (o.optBoolean("set") ? "（已设置" + (hint.isEmpty ? "" : " " + hint) + "，留空不改）" : "（未设置）")
                    if k == "key_content" { f.append(Field.multi("c_" + k, lab, "")) }
                    else if k.contains("secret") || k.contains("pass") { f.append(Field.pass("c_" + k, lab)) }
                    else { f.append(Field.text("c_" + k, lab, "")) }
                } else {
                    f.append(Field.text("c_" + k, MainPage.CRED_LABEL[k] ?? k, fields.optString(k)))
                }
            }
            f.append(Field.text("proxy", "代理地址（当前 " + (d.optString("proxy").isEmpty ? "直连" : d.optString("proxy")) + "；留空不改）", ""))
            f.append(Field.text("proxy_user", "代理用户名", d.optString("proxy_user")))
            f.append(Field.pass("proxy_pass", d.optBoolean("proxy_pass_set") ? "代理密码（已设置，留空不改）" : "代理密码（可选）"))
            if d.optBoolean("proxy_pass_set") { f.append(Field.check("proxy_pass_clear", "清除代理密码", false)) }
            f.append(Field.check("direct", "改为直连（清除代理）", false))
            self.form("编辑 · " + d.optString("name"), "修改了凭证会先测活，通过才保存", f, "保存") { v in
                var b: JObj = ["name": v.optString("name")]
                var cred = JObj()
                for k in keys { cred[k] = v.optString("c_" + k) }
                b["cred"] = cred
                if v.optBoolean("direct") { b["proxy"] = "" }
                else {
                    if !v.optString("proxy").isEmpty { b["proxy"] = v.optString("proxy") }
                    if v.optString("proxy_user") != d.optString("proxy_user") { b["proxy_user"] = v.optString("proxy_user") }
                    if !v.optString("proxy_pass").isEmpty { b["proxy_pass"] = v.optString("proxy_pass") }
                    if v.optBoolean("proxy_pass_clear") { b["proxy_pass_clear"] = true }
                }
                self.request("PATCH", "/accounts/\(aid)", b) { _ in self.toast("已保存"); self.accountsChanged() }
            }
        }
    }
}
