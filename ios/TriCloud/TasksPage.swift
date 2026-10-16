import SwiftUI

/// 任务列表：抢机 / 换 IP / 改配置等，可查看实时日志、停止运行中的任务。对应 TasksActivity（每 10 秒自动刷新）。
final class TasksPage: Page {
    private var gen = 0
    private var visible = false

    override init() {
        super.init()
        title = "任务"
    }

    static func tn(_ t: String) -> String {
        switch t {
        case "snatch": return "抢机"
        case "change_ip": return "换 IP"
        case "resize": return "改配置"
        case "ipv6": return "IPv6"
        case "azure_create": return "创建 VM"
        case "ensure_network": return "自动建网"
        case "snapshot": return "快照（已移除）"
        case "migrate": return "迁移"
        case "cf_delete": return "删除 CDN 分发"
        case "reinstall": return "重装系统"
        case "net500m": return "下行 500Mbps"
        case "foundry": return "部署 AI 模型"
        case "billing_keep": return "保号账单"
        case "aws_credit": return "新号 Credit"
        case "onedrive_backup": return "OneDrive 备份"
        default: return t
        }
    }

    override func appeared() {
        visible = true
        if !started { started = true }
        refresh()
    }

    override func disappeared() {
        visible = false
        gen += 1
    }

    override func refresh() {
        gen += 1
        let g = gen
        get("/tasks") { r in
            self.clear()
            let a = jarr(r)
            if a.isEmpty { self.card("暂无任务").muted("") }
            let f = DateFormatter()
            f.dateFormat = "MM-dd HH:mm:ss"
            for i in 0..<a.count {
                let t = a.obj(i)
                let tid = t.optInt("id")
                let c = self.card("#\(tid) " + TasksPage.tn(t.optString("type")) + "  [" + t.optString("status") + "]")
                c.text(str(t, "account_name", "-") + " · 尝试 \(t.optInt("attempts")) 次\n" + str(t, "message", ""), 13)
                c.muted("更新于 " + f.string(from: Date(timeIntervalSince1970: TimeInterval(t.optLong("updated")))))
                let row = c.row()
                row.button("日志") { self.openTask(tid) }
                if t.optString("status") == "running" {
                    row.button("停止") {
                        self.confirm("停止任务", "#\(tid)") { self.post("/tasks/\(tid)/stop", nil) { _ in self.refresh() } }
                    }
                } else {
                    row.button("删除") { self.del("/tasks/\(tid)") { _ in self.refresh() } }
                }
            }
            self.later(10) {
                if self.visible && self.gen == g { self.refresh() }
            }
        }
    }
}
