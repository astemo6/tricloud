import SwiftUI

// build 20：AWS「新号 Credit」标签（与 Web tabAwsCredit / Android credit() 一致）。
// 显示新免费计划的剩余 credit、到期时间与 5 个官方活动的状态；每个未完成活动可「一键完成」（后台任务，用完自动清理），
// 另有「一键全部完成」（两次确认）和「清理残留」。AWS 未公开说明 API 操作是否计入活动，执行后只显示「已执行，等待 AWS 识别」。

extension AccountPage {
    static func crMoney(_ o: JObj?, _ k: String) -> String {
        guard let o = o, !o.isNull(k) else { return "-" }
        let u = str(o, "unit", "USD")
        return (u == "USD" ? "$" : u + " ") + AccountPage.numStr((o.optDouble(k, 0) * 100).rounded() / 100)
    }

    static func crDate(_ s: String) -> String {
        if s.isEmpty || s == "null" { return "-" }
        let t = s.replacingOccurrences(of: "T", with: " ")
        return t.count > 16 ? String(t.prefix(16)) : t
    }

    static func crStep(_ st: String) -> String {
        switch st {
        case "executed": return "已执行，等待 AWS 识别"
        case "failed": return "执行失败"
        case "stopped": return "已停止"
        case "skipped": return "未执行"
        case "running": return "执行中…"
        default: return "排队中"
        }
    }

    func awsCredit(_ refresh: Bool) {
        card("正在读取 Free Tier 计划与活动…").muted("freetier 免费接口，结果缓存 5 分钟")
        let g = gen
        get("/accounts/\(id)/aws/credits" + (refresh ? "?refresh=true" : "")) { r in
            guard self.cur(g), self.tab == "credit" else { return }
            self.header()
            self.crRender(jobj(r), g)
        }
    }

    private func crRender(_ d: JObj, _ g: Int) {
        let p = d.optJSONObject("plan")
        let rt = d.optJSONObject("running_task")
        let running = rt != nil
        if d.optString("state") == "ok", let p = p {
            let c = card("剩余 Credit")
            c.text(AccountPage.crMoney(p, "remaining"), 26, true)
            c.muted("计划 " + str(p, "type", "-") + " · " + str(p, "status", "-") + " · 到期 " + AccountPage.crDate(p.optString("expires")))
        } else {
            let c = card("无法读取 Free Tier 状态")
            c.text("⚠️ " + str(d, "message", "未知错误"), 13)
            if let perms = d.optJSONArray("permissions") { c.muted("需要的 IAM 只读权限：" + join(perms)) }
            if d.optString("state") == "not_applicable" {
                c.muted("只有使用新免费计划（2025-07-15 之后注册）的账号才有这些活动；下面仍可手动执行，但不会有奖励。")
            }
        }
        if let rt = rt {
            let ks = rt.optJSONArray("activities") ?? []
            let steps = rt.optJSONObject("steps") ?? [:]
            var done = 0
            for i in 0..<ks.count {
                let st = (steps.optJSONObject(ks.string(i)) ?? [:]).optString("status")
                if !st.isEmpty && st != "running" && st != "pending" { done += 1 }
            }
            let tid = rt.optInt("id")
            let c = card("任务 #\(tid) 执行中")
            c.meter(ks.count > 0 ? Double(done) / Double(ks.count) : 0, "（\(done)/\(ks.count)）" + str(rt, "message", ""))
            c.row().button("查看日志 #\(tid)") { self.openTask(tid) }
            later(4) {
                guard self.cur(g), self.tab == "credit" else { return }
                self.refresh()
            }
        }
        let ac = card("操作")
        ac.muted(str(d, "updated_at", "") + (d.optBoolean("cached") ? "（缓存，\(Int((Double(d.optInt("age")) / 60).rounded())) 分钟前）" : ""))
        let ar = ac.row()
        ar.button("刷新") { self.gen += 1; self.header(); self.awsCredit(true) }
        let pending = d.optJSONArray("pending") ?? []
        if !running && pending.count > 0 { ar.button("一键全部完成") { self.crRunAll(d) } }
        if !running { ar.button("清理残留") { self.crCleanup() } }
        let acts = d.optJSONArray("activities") ?? []
        for i in 0..<acts.count {
            let a = acts.obj(i)
            let c = card(a.optString("label") + " · " + a.optString("status_text"))
            if !a.isNull("title") && !a.optString("title").isEmpty { c.muted(a.optString("title")) }
            var when = ""
            if !a.isNull("completed_at") && !a.optString("completed_at").isEmpty { when = "完成于 " + AccountPage.crDate(a.optString("completed_at")) }
            else if !a.isNull("started_at") && !a.optString("started_at").isEmpty { when = "开始于 " + AccountPage.crDate(a.optString("started_at")) }
            c.text("奖励 " + AccountPage.crMoney(a, "reward") + (when.isEmpty ? "" : " · " + when), 13)
            c.muted(a.optString("plan"))
            if !a.isNull("note") && !a.optString("note").isEmpty { c.muted("ℹ️ " + a.optString("note")) }
            if let lr = a.optJSONObject("last_run") {
                let st = lr.optString("status")
                c.text("任务 #\(lr.optInt("task_id"))：" + AccountPage.crStep(st)
                       + (st == "failed" && !lr.optString("message").isEmpty ? "：" + lr.optString("message") : ""), 12)
            }
            if a.optBoolean("runnable") {
                if !running { c.row().button("一键完成") { self.crRun(a) } }
            } else if a.optBoolean("completed") {
                c.muted("✅ AWS 显示已完成")
            }
        }
        let notes = d.optJSONArray("notes") ?? []
        if notes.count > 0 {
            let nc = card("说明")
            for i in 0..<notes.count { nc.muted("• " + notes.string(i)) }
        }
    }

    private func crRun(_ a: JObj) {
        let key = a.optString("key")
        let note: String = a.isNull("note") ? "" : a.optString("note") + "\n\n"
        confirm("一键完成：" + a.optString("label"), a.optString("plan") + "\n\n" + note
                + "资源打标签 tricloud-credit=1，用完自动清理。完成后显示「已执行，等待 AWS 识别」——AWS 未公开说明 API 操作是否计入活动，最终以 AWS 返回的活动状态为准（可能要几分钟到几小时）。确认执行？") {
            self.post("/accounts/\(self.id)/aws/credits/activities/" + enc(key) + "/run", ["confirm": true]) { x in
                self.toast(jobj(x).optString("message"))
                if self.tab == "credit" { self.refresh() }
            }
        }
    }

    private func crRunAll(_ d: JObj) {
        let acts = d.optJSONArray("activities") ?? []
        let pend = d.optJSONArray("pending") ?? []
        let pl = (0..<pend.count).map { pend.string($0) }
        let names = (0..<acts.count).map { acts.obj($0) }.filter { pl.contains($0.optString("key")) }.map { $0.optString("label") }
        confirm("一键全部完成", "将按顺序执行未完成的活动：" + names.joined(separator: "、") + "。\n每个活动用完自动清理；全部跑完约 20–40 分钟（RDS 最久）。") {
            self.message("再次确认：会产生少量费用",
                         "EC2、RDS 会各运行几分钟，Lambda / Bedrock 调用极少，费用金额极小，从 credit 中扣。\n执行后只表示「已执行，等待 AWS 识别」，不代表已拿到奖励。确认开始？",
                         primary: ("开始执行", {
                            self.post("/accounts/\(self.id)/aws/credits/run-all", ["confirm": true]) { x in
                                let o = jobj(x)
                                let sk = o.optJSONArray("skipped") ?? []
                                let reasons = (0..<sk.count).map { sk.obj($0).optString("reason") }
                                self.toast(o.optString("message") + (reasons.isEmpty ? "" : "：" + reasons.joined(separator: "；")))
                                if self.tab == "credit" { self.refresh() }
                            }
                         }), cancel: "取消")
        }
    }

    private func crCleanup() {
        form("清理残留资源", "删除带 tricloud-credit=1 标签的 EC2 实例、名称以 tricloud-credit-db 开头的 RDS 实例、Lambda 函数 tricloud-credit-web 和角色 tricloud-credit-lambda-role（不会动其他资源）。",
             [Field.check("include_budget", "同时删除预算 tricloud-credit-budget（预算免费，一般不用删）", false)], "清理") { v in
            self.post("/accounts/\(self.id)/aws/credits/cleanup", ["confirm": true, "include_budget": v.optBoolean("include_budget")]) { x in
                let o = jobj(x)
                let del = o.optJSONArray("deleted") ?? []
                let er = o.optJSONArray("errors") ?? []
                var s = ""
                if del.count > 0 {
                    s = "已清理 \(del.count) 项：" + (0..<del.count).map { del.obj($0).optString("id") }.joined(separator: "、")
                } else if er.count == 0 {
                    s = "没有残留资源"
                }
                if er.count > 0 {
                    s += (del.count > 0 ? "；失败：" : "清理失败：") + (0..<er.count).map { er.obj($0).optString("error") }.joined(separator: "；")
                }
                self.toast(s)
            }
        }
    }
}
