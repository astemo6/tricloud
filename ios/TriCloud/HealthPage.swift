import SwiftUI

/// 账号健康度：0–100 分，每天 07:30 自动检测，掉分推送 Telegram。对应 HealthActivity。
final class HealthPage: Page {
    override init() { super.init(); title = "账号健康度" }

    static func level(_ sc: Int) -> String { sc >= 80 ? "健康" : sc >= 50 ? "注意" : "危险" }

    override func refresh() {
        get("/account-health") { r in
            self.clear()
            self.card("说明").muted("检查凭证/封禁、被动停机、实例消失、非容量类任务失败、OCI A1 配额、AWS Credit、Azure 订阅状态。只用免费只读接口。")
            self.bigButton("全部重新检测") { self.post("/account-health/refresh", JObj()) { _ in self.toast("检测完成"); self.refresh() } }
            let a = jarr(r)
            for i in 0..<a.count {
                let h = a.obj(i)
                let has = !h.isNull("score")
                let c = self.card(h.optString("name") + "  " + (has ? "\(h.optInt("score")) 分 · " + HealthPage.level(h.optInt("score")) : "未检测"))
                c.muted(MainPage.pname(h.optString("provider")))
                let items = h.optJSONArray("items") ?? []
                var sb = ""
                for j in 0..<items.count {
                    let it = items.obj(j)
                    sb += (it.optBoolean("ok") ? "✓ " : "! ") + it.optString("name")
                    if it.optInt("penalty") > 0 { sb += "  -\(it.optInt("penalty"))" }
                    sb += "\n   " + it.optString("detail") + "\n"
                }
                if !sb.isEmpty { c.text(sb.trimmingCharacters(in: .whitespacesAndNewlines), 13) }
                let aid = h.optInt("account_id")
                c.row().button("检测") { self.post("/account-health/refresh", ["account_id": aid]) { _ in self.refresh() } }
            }
        }
    }
}
