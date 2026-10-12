import SwiftUI

/// v1.5 已删账号：删除账号时留档的名称、云、存活天数、预估费用。对应 DeletedActivity。
final class DeletedPage: Page {
    override init() { super.init(); title = "已删账号" }

    override func refresh() {
        get("/recycle-bin") { r in
            self.clear()
            let o = jobj(r)
            let st = o.optJSONObject("stats") ?? [:]
            var by = ""
            if let bp = st.optJSONObject("by_provider") {
                for k in bp.keys.sorted() { by += MainPage.pname(k) + " \(bp.optInt(k))  " }
            }
            let total = st.optDouble("total_est_cost_usd", 0)
            let head = self.card("共 \(st.optInt("count")) 个")
            head.muted(by.trimmingCharacters(in: .whitespaces) + "\n平均存活 " + str(st, "avg_lifecycle_days", "—") + " 天 · 最长 " + str(st, "max_lifecycle_days", "—") + " 天"
                       + "\n预估费用合计 $" + fmt2(total.isNaN ? 0 : total)
                       + "\n删除账号时自动留档（取自本地账单缓存，不调用云 API），只是记录。")
            let a = o.optJSONArray("items") ?? []
            let df = DateFormatter()
            df.dateFormat = "yyyy-MM-dd HH:mm"
            for i in 0..<a.count {
                let x = a.obj(i)
                let c = self.card(x.optString("name") + (x.optString("source") == "legacy" ? "  [旧版迁移]" : ""))
                let cost = x.isNull("est_cost") ? "—" : fmt2(x.optDouble("est_cost")) + " " + str(x, "currency", "USD")
                let when = df.string(from: Date(timeIntervalSince1970: TimeInterval(x.optLong("deleted_at"))))
                c.muted(MainPage.pname(x.optString("provider")) + " · 存活 " + (x.isNull("lifecycle_days") ? "—" : x.optString("lifecycle_days") + " 天")
                        + "（" + str(x, "age_basis", "-") + "）\n预估费用 " + cost + "（" + str(x, "cost_basis", "-") + "）\n删除于 " + when)
                let rid = x.optInt("id")
                c.row().button("移除记录") { self.del("/recycle-bin/\(rid)") { _ in self.refresh() } }
            }
            if a.isEmpty { self.card("还没有删除过账号").muted("") }
        }
    }
}
