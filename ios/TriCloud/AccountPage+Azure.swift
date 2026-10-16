import SwiftUI

// AccountActivity：Azure 订阅（只读）与 Foundry（Azure AI Services：配额、资源、模型部署、Endpoint/Key）。

extension AccountPage {
    func subscription() {
        let g = gen
        get("/accounts/\(id)/azure/subscription") { r in
            guard self.cur(g) else { return }
            let s = jobj(r)
            let c = self.card("订阅（只读）")
            if s.has("error") { c.text("❌ " + s.optString("error"), 13) }
            else {
                c.text("名称：" + str(s, "display_name", "-") + "\n状态：" + str(s, "state", "-") + "\n类型：" + str(s, "offer", "-")
                       + "\nSpending limit：" + str(s, "spending_limit", "-") + "\nquotaId：" + str(s, "quota_id", "-") + "\n订阅 ID：" + str(s, "subscription_id", "-"), 13)
            }
            let edu = s.optJSONObject("edu")
            let e = self.card("教育优惠")
            if let edu = edu {
                e.text(edu.isNull("expires_at") ? "未知" : edu.optString("expires_at") + (edu.optBoolean("estimated") ? "（估算）" : "") + " · 剩 \(edu.optInt("days_left")) 天", 15, true)
                e.muted(edu.optString("basis"))
            }
            if !s.isNull("age_days") { e.muted("账号已存活 \(s.optInt("age_days")) 天") }
        }
    }

    func foundry() {
        let g = gen
        get("/accounts/\(id)/azure/foundry?region=" + fdRegion) { r in
            guard self.cur(g) else { return }
            let d = jobj(r)
            let top = self.card("Foundry（Azure AI）")
            top.muted("创建 AI Services 资源并部署 GPT 等模型，拿到 Endpoint 和 Key 可按 OpenAI 接口调用。按调用量计费，会消耗订阅额度。\n当前区域：" + Regions.label(self.fdRegion))
            let tr = top.row()
            let regs = d.optJSONArray("regions")
            tr.button("切换区域") {
                guard let regs = regs else { return }
                let l = (0..<regs.count).map { regs.string($0) }
                self.choose("区域", l.map { Regions.label($0) }) { idx in self.fdRegion = l[idx]; self.refresh() }
            }
            tr.button("＋ 新建资源并部署") { self.fdDeploy(nil, d.optJSONArray("models")) }
            let res = d.optJSONArray("resources") ?? []
            if res.isEmpty { self.card("AI 资源").muted("订阅里还没有 AI Services / Azure OpenAI 资源") }
            for i in 0..<res.count {
                let x = res.obj(i)
                let c = self.card(x.optString("name") + "  [" + x.optString("kind") + "]")
                var sb = Regions.label(x.optString("region")) + " · " + x.optString("resource_group") + "\n" + str(x, "endpoint", "-")
                let deps = x.optJSONArray("deployments") ?? []
                for j in 0..<deps.count {
                    let dp = deps.obj(j)
                    sb += "\n• " + dp.optString("name") + "：" + dp.optString("model") + " " + dp.optString("version")
                        + " · " + dp.optString("sku") + " \(dp.optInt("capacity"))K TPM"
                }
                c.text(sb, 13)
                let rr = c.row()
                let rid = x.optString("id")
                rr.button("Endpoint / Key") {
                    self.confirm("查看密钥", "Key 等同于调用权限，泄露会被盗刷额度。确定显示？") {
                        self.post("/accounts/\(self.id)/azure/foundry", ["op": "keys", "resource_id": rid, "confirm": true]) { k in
                            let o = jobj(k)
                            let key = o.optString("key1")
                            let txt = "base_url：" + o.optString("openai_base_url") + "\nKey：" + key
                            self.message("Endpoint / Key", txt + "\n\nmodel 填部署名。",
                                         primary: ("复制 Key", { copyText(key); self.toast("已复制") }), cancel: "关闭")
                        }
                    }
                }
                rr.button("部署模型") { self.fdDeploy(rid, d.optJSONArray("models")) }
                if !deps.isEmpty {
                    rr.button("删除部署") {
                        let l = (0..<deps.count).map { deps.obj($0).optString("name") }
                        self.choose("删除哪个部署", l) { idx in
                            self.confirm("删除部署", "删除「" + l[idx] + "」？用这个部署名的调用会立刻失败。") {
                                self.post("/accounts/\(self.id)/azure/foundry", ["op": "delete_deployment", "resource_id": rid, "deployment": l[idx], "confirm": true]) { _ in
                                    self.toast("已删除")
                                    self.refresh()
                                }
                            }
                        }
                    }
                }
                rr.button("删除资源") {
                    self.confirm("删除 AI 资源", "删除「" + x.optString("name") + "」及其全部部署？Key 立刻失效，48 小时内不能同名重建。") {
                        self.post("/accounts/\(self.id)/azure/foundry", ["op": "delete_resource", "resource_id": rid, "confirm": true]) { _ in
                            self.toast("已删除")
                            self.refresh()
                        }
                    }
                }
            }
            let qc = self.card("模型配额 · " + self.fdRegion)
            let q = d.optJSONArray("quotas") ?? []
            var qs = ""
            for i in 0..<q.count { qs += q.obj(i).optString("name") + "：\(q.obj(i).optInt("used")) / \(q.obj(i).optInt("limit"))\n" }
            qc.text(qs.isEmpty ? "该区域没有可用配额" : qs.trimmingCharacters(in: .whitespacesAndNewlines), 12)
        }
    }

    func fdDeploy(_ rid: String?, _ models: JArr?) {
        var f: [Field] = []
        if rid == nil {
            f.append(Field.text("name", "资源名称（全局唯一，字母数字和 -）", ""))
            f.append(Field.text("resource_group", "资源组（可选）", ""))
        }
        let m = models ?? []
        var mv: [String] = [], ml: [String] = []
        if m.isEmpty { mv = ["gpt-4o-mini|"]; ml = ["gpt-4o-mini"] }
        for i in 0..<m.count {
            let x = m.obj(i)
            mv.append(x.optString("name") + "|" + x.optString("version"))
            ml.append(x.optString("name") + " " + x.optString("version"))
        }
        f.append(Field.select("model", "模型", mv[0], mv, ml))
        f.append(Field.select("sku", "部署类型", "GlobalStandard", ["GlobalStandard", "Standard"], ["Global Standard", "Standard（仅本区域）"]))
        f.append(Field.num("capacity", "容量（千 TPM）", "10"))
        f.append(Field.text("deployment", "部署名（可选，默认模型名）", ""))
        form(rid == nil ? "新建资源并部署模型（" + fdRegion + "）" : "部署模型", "容量受配额限制；完成后在「Endpoint / Key」里拿调用地址。", f, "开始部署") { v in
            let mm = v.optString("model").components(separatedBy: "|")
            var b: JObj = ["op": "deploy", "model": mm[0], "sku": v.optString("sku"), "capacity": v.optString("capacity", "10")]
            if mm.count > 1 && !mm[1].isEmpty { b["version"] = mm[1] }
            if !v.optString("deployment").isEmpty { b["deployment"] = v.optString("deployment") }
            if let rid = rid { b["resource_id"] = rid }
            else {
                let name = v.optString("name")
                if name.range(of: "^[a-zA-Z0-9][a-zA-Z0-9-]{1,62}$", options: .regularExpression) == nil {
                    self.toast("资源名称 2~63 位，只能含字母、数字和 -")
                    return
                }
                b["name"] = name
                b["region"] = self.fdRegion
                if !v.optString("resource_group").isEmpty { b["resource_group"] = v.optString("resource_group") }
            }
            self.post("/accounts/\(self.id)/azure/foundry", b) { x in self.taskOrToast(x, "已提交") }
        }
    }
}
