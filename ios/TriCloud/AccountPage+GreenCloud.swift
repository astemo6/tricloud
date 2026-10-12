import SwiftUI

// 绿云 GreenCloud：没有区域，只有「实例」标签；每台显示状态、IP、主机名、流量进度，操作只有开机 / 关机 / 重启。

extension AccountPage {
    static func gcState(_ s: String) -> String {
        switch s.lowercased() {
        case "running": return "🟢 运行中"
        case "stopped": return "🔴 已关机"
        default: return "⚪️ 未知"
        }
    }

    static func gb(_ bytes: Double) -> String {
        if bytes.isNaN { return "-" }
        let g = bytes / 1_073_741_824.0
        return g >= 100 ? String(format: "%.0f GB", g) : String(format: "%.2f GB", g)
    }

    func gcInstances() {
        let g = gen
        get("/accounts/\(id)/instances?kind=vm") { r in
            guard self.cur(g) else { return }
            let a = jarr(r)
            if a.isEmpty { self.card("没有实例").muted("请在「编辑」里检查面板地址和服务器列表（每行：名称 key hash）") }
            for i in 0..<a.count { self.gcCard(a.obj(i)) }
        }
    }

    func gcCard(_ inst: JObj) {
        let name = str(inst, "name", str(inst, "id", "-"))
        let c = card(name + "  " + AccountPage.gcState(inst.optString("state")))
        var all: [String] = []
        let main = str(inst, "public_ip", "")
        if !main.isEmpty { all.append(main) }
        if let more = inst.optJSONArray("ips") {
            for i in 0..<more.count {
                let ip = more.string(i)
                if !ip.isEmpty && !all.contains(ip) { all.append(ip) }
            }
        }
        c.text("IP：" + (all.isEmpty ? "-" : all.joined(separator: ", ")) + "\n主机名：" + str(inst, "hostname", "-"), 13)
        if let bw = inst.optJSONObject("bw") {
            let total = bw.optDouble("total")
            let used = bw.optDouble("used")
            var pct = bw.optDouble("percent")
            if pct.isNaN && !total.isNaN && !used.isNaN && total > 0 { pct = used / total * 100 }
            if !total.isNaN || !used.isNaN {
                let label = "流量 " + AccountPage.gb(used) + " / " + AccountPage.gb(total) + (pct.isNaN ? "" : String(format: " · %.1f%%", pct))
                c.meter(pct.isNaN ? 0 : pct / 100, label)
            }
        }
        let r = c.row()
        r.button("开机") { self.simple(inst, "vm", "start", "开机") }
        r.button("关机") { self.simple(inst, "vm", "stop", "关机") }
        r.button("重启") { self.simple(inst, "vm", "reboot", "重启") }
    }
}
