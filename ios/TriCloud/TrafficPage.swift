import SwiftUI

/// 流量守护规则：在实例卡片上点「流量守护」添加。对应 TrafficActivity。
final class TrafficPage: Page {
    override init() { super.init(); title = "流量守护" }

    override func refresh() {
        get("/traffic-guards") { r in
            self.clear()
            self.card("说明").muted("本月累计或滚动窗口（最近 N 小时，出站 / 入站 / 双向）。到预警比例推送，到上限推送并可自动停机，可在 M 小时后自动开机（失败只告警、不重试）。在实例卡片上点「流量守护」添加。")
            let a = jarr(r)
            if a.isEmpty { self.card("还没有规则").muted("") }
            for i in 0..<a.count {
                let g = a.obj(i)
                let c = self.card(str(g, "name", "-"))
                let stop = g.optString("action") == "stop"
                var sh = g.optDouble("shutdown_hours", 0)
                if sh.isNaN { sh = 0 }
                let shText = sh == floor(sh) ? String(Int64(sh)) : "\(sh)"
                let onLimit = !stop ? "只推送" : sh > 0 ? "停机 " + shText + " 小时后自动开机" : "自动停机"
                let resume = g.isNull("resume_at_text") ? "" : "，预计 " + g.optString("resume_at_text") + " 开机"
                let enabled = g.optInt("enabled", 1) == 1
                c.text(str(g, "account_name", "-") + "\n" + str(g, "scope", "本月出站") + "：" + str(g, "last_gb", "-") + " / " + str(g, "limit_gb", "-") + " GB（" + str(g, "last_pct", "-") + "%）"
                       + "\n到上限：" + onLimit
                       + "\n状态：" + str(g, "status_text", "正常") + resume + (enabled ? "" : "（已停用）"), 13)
                if !g.isNull("state_msg") && g.optString("status") != "ok" { c.muted(g.optString("state_msg")) }
                let row = c.row()
                let gid = g.optInt("id")
                row.button(enabled ? "停用" : "启用") { self.patch(gid, "enabled", !enabled) }
                if !g.isNull("resume_at") { row.button("取消自动开机") { self.patch(gid, "cancel_resume", true) } }
                if g.optString("status") == "tripped" || g.optString("status") == "resume_failed" {
                    row.button("清除状态") { self.patch(gid, "reset_state", true) }
                }
                row.button("编辑") {
                    let kind = str(g, "kind", "vm")
                    self.trafficGuardForm(g.optInt("account_id"), g.optString("provider"), g.optString("instance_id"), str(g, "name", g.optString("instance_id")),
                                          str(g, "region", ""), kind) { self.refresh() }
                }
                row.button("立即检查") { self.post("/traffic-guards/\(gid)/check", nil) { _ in self.refresh() } }
                row.button("删除") {
                    self.confirm("删除规则", "删除这条流量守护？") { self.del("/traffic-guards/\(gid)") { _ in self.refresh() } }
                }
            }
        }
    }

    private func patch(_ gid: Int, _ k: String, _ v: Bool) {
        request("PATCH", "/traffic-guards/\(gid)", [k: v]) { _ in self.refresh() }
    }
}
