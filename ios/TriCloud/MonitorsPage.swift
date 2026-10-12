import SwiftUI

/// 监控配置：今日换 IP 次数、查看与移除（在实例「更多操作 → 监控」添加）。对应 Web pageMonitors。
final class MonitorsPage: Page {
    override init() { super.init(); title = "监控" }

    override func refresh() {
        get("/monitors") { r in
            let a = jarr(r)
            Api.call("GET", "/ip-change-usage", nil) { res in
                var usage: JArr = []
                if case .success(let x) = res { usage = jarr(x) }
                self.build(a, usage)
            }
        }
    }

    private func build(_ a: JArr, _ usage: JArr) {
        clear()
        var used: [JObj] = []
        for i in 0..<usage.count {
            let u = usage.obj(i)
            let watched = (0..<a.count).contains { a.obj($0).optInt("account_id") == u.optInt("account_id") && a.obj($0).optInt("auto_change_ip") == 1 }
            if u.optInt("auto_used") > 0 || u.optInt("manual_used") > 0 || watched { used.append(u) }
        }
        if !used.isEmpty {
            let c = card("今日换 IP 次数")
            c.text(used.map { $0.optString("name") + " · 自动 \($0.optInt("auto_used"))/\($0.optInt("limit")) · 手动 \($0.optInt("manual_used"))" }.joined(separator: "\n"), 13)
            c.muted("自动换 IP 每账号每天最多 \(used[0].optInt("limit")) 次（设置里修改），达到上限或失败时只推送 Telegram 告警。")
        }
        card("说明").muted("在实例的「更多操作 → 监控」添加。检测间隔见设置页。非面板操作导致的停止 / 终止会推送告警，可选自动启动。")
        if a.isEmpty { card("暂无监控").muted("") }
        for i in 0..<a.count {
            let m = a.obj(i)
            let c = card(str(m, "name", "-"))
            var check = "—"
            if m.optInt("check_port") > 0 {
                check = str(m, "public_ip", "-") + ":\(m.optInt("check_port"))"
                if m.optInt("auto_change_ip") == 1 { check += " · 不通自动换 IP" }
                if m.optInt("fail_count") > 0 { check += " · 失败 \(m.optInt("fail_count"))" }
            }
            c.text(str(m, "account_name", "-") + "\n上次状态：" + str(m, "last_state", "-") + "\n自动启动：" + (m.optInt("auto_start") == 1 ? "是" : "否")
                   + "\n连通检测：" + check, 13)
            let mid = m.optInt("id")
            c.row().button("移除") {
                self.confirm("移除监控", "确定移除这台实例的监控？") { self.del("/monitors/\(mid)") { _ in self.toast("已移除"); self.refresh() } }
            }
        }
    }
}
