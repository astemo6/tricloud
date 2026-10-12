import SwiftUI

// AccountActivity：OCI 安全组（v1.5）。

extension AccountPage {
    // MARK: - OCI 流量：本区域实例本月出站 / 入站（OCI Monitoring，免费）

    static func gb(_ o: JObj, _ k: String) -> String {
        if o.isNull(k) { return "-" }
        let v = o.optDouble(k, 0)
        return v >= 1024 ? String(format: "%.2f TB", v / 1024) : String(format: "%.2f GB", v)
    }

    func ociTraffic() {
        card("正在读取各实例流量…").muted("来自 OCI Monitoring（免费），有 5~15 分钟延迟")
        let g = gen
        get("/accounts/\(id)/oci/traffic-summary?" + rq()) { r in
            guard self.cur(g) else { return }
            self.header()
            let d = jobj(r)
            let free = d.optDouble("free_out_gb", 10240), out = d.optDouble("out_gb", 0)
            let c = self.card("本区域本月出站")
            c.text(AccountPage.gb(d, "out_gb") + " / " + AccountPage.gb(d, "free_out_gb"), 24, true)
            c.muted(String(format: "已用 %.2f%%", free > 0 ? out / free * 100 : 0) + " · 入站 " + AccountPage.gb(d, "in_gb") + "（不计费）· " + d.optString("period") + " UTC")
            c.muted("10TB 免费出站按整个租户所有区域合计。需要超量提醒或自动停机，用「流量守护」。")
            let items = d.optJSONArray("items") ?? []
            if items.isEmpty { self.card("本区域没有实例").muted(self.region()); return }
            for i in 0..<items.count {
                let it = items.obj(i)
                let ic = self.card(it.optString("name") + " · " + it.optString("state"))
                if it.has("error") { ic.muted("读取失败：" + it.optString("error")) }
                else { ic.text("出站 " + AccountPage.gb(it, "out_gb") + "    入站 " + AccountPage.gb(it, "in_gb"), 16, true) }
                ic.muted(str(it, "public_ip", "-") + " · " + it.optString("shape"))
                ic.row().button("流量守护") { self.traffic(it, "vm") }
            }
        }
    }

    func secgroup() {
        let g = gen
        get("/accounts/\(id)/instances?kind=vm&" + rq()) { r in
            guard self.cur(g) else { return }
            let a = jarr(r)
            if a.isEmpty { self.card("该区域没有实例").muted(self.region()); return }
            let ids = (0..<a.count).map { a.obj($0).optString("id") }
            let names = (0..<a.count).map { a.obj($0).optString("name") }
            if self.sgInst == nil || !ids.contains(self.sgInst!) { self.sgInst = Prefs.get("sg_\(self.id)", ids[0]) }
            if !ids.contains(self.sgInst!) { self.sgInst = ids[0] }
            let inst = self.sgInst!
            let curName = names[ids.firstIndex(of: inst) ?? 0]
            let top = self.row()
            top.button("实例：" + curName) {
                self.choose("选择实例", names) { i in
                    self.sgInst = ids[i]
                    Prefs.set("sg_\(self.id)", ids[i])
                    self.refresh()
                }
            }
            top.button("＋ 添加规则") { self.sgAdd() }
            self.get("/accounts/\(self.id)/security-rules?instance_id=" + enc(inst) + "&" + self.rq()) { x in
                guard self.cur(g) else { return }
                let o = jobj(x)
                let ra = o.optJSONArray("rules") ?? []
                let rules = (0..<ra.count).map { ra.obj($0) }
                self.card("规则作用于实例所在子网的安全列表").muted("同子网实例共享；不支持对 0.0.0.0/0 放行全部端口")
                // 全部 / 入站 / 出站 分段切换（始终显示）；规则超过 10 条时显示筛选框（端口、IP/CIDR、协议、描述）
                self.view(AnyView(SgRulesView(f: self.sgFilter, rules: rules, onDelete: { ru in self.sgDelete(inst, ru) })))
            }
        }
    }

    func sgDelete(_ inst: String, _ ru: JObj) {
        let inbound = ru.optString("direction") == "ingress"
        let warn22: String = inbound && ru.optString("port") == "22" ? "\n⚠️ 删除 22 端口规则可能导致无法 SSH 登录。" : ""
        confirm("删除规则", "删除这条规则？" + warn22) {
            let p = ru.optString("protocol")
            let proto = p == "全部" ? "all" : p.lowercased()
            var b: JObj = ["instance_id": inst, "region": self.region(), "sl_id": ru.optString("sl_id"),
                           "direction": ru.optString("direction"), "protocol": proto, "cidr": ru.optString("cidr")]
            if let pm = ru.opt("port_min") { b["port_min"] = pm }
            if let px = ru.opt("port_max") { b["port_max"] = px }
            self.request("DELETE", "/accounts/\(self.id)/security-rules", b) { _ in self.toast("已删除"); self.refresh() }
        }
    }

    func sgAdd() {
        form("添加安全规则", "端口可批量：80, 443, 8000-8100（每段一条规则，已存在的跳过）", [
            Field.select("direction", "方向", "ingress", ["ingress", "egress"], ["入站", "出站"]),
            Field.select("protocol", "协议", "tcp", ["tcp", "udp", "icmp", "icmpv6", "all"], ["TCP", "UDP", "ICMP", "ICMPv6", "全部协议"]),
            Field.text("cidr", "来源 CIDR（出站为目标）", ""),
            Field.multi("ports", "端口（TCP / UDP）", ""),
            Field.text("description", "描述（可选）", "")], "添加") { v in
            var b = v
            b["instance_id"] = self.sgInst ?? ""
            b["region"] = self.region()
            let cidr = v.optString("cidr").replacingOccurrences(of: " ", with: "")
            let isPublic = v.optString("direction") == "ingress" && (cidr == "0.0.0.0/0" || cidr == "::/0")
            if isPublic { b["confirm_public"] = true }
            let body = b
            let send = {
                self.post("/accounts/\(self.id)/security-rules", body) { x in
                    let o = jobj(x)
                    self.toast("已添加 \(o.optInt("added")) 条" + (o.optInt("skipped") > 0 ? "，跳过已存在 \(o.optInt("skipped")) 条" : ""))
                    self.refresh()
                }
            }
            if isPublic {
                self.confirm("⚠️ 对整个互联网开放", "来源 " + cidr + " 表示任何人都能访问这些端口。请确认服务有密码 / 密钥保护；只需自己访问时建议填写你的 IP 段。", send)
            } else { send() }
        }
    }
}

// MARK: - 安全组规则列表（带轻量筛选）

final class SgFilter: ObservableObject {
    @Published var dir = "all"
    @Published var q = ""
}

struct SgRulesView: View {
    @ObservedObject var f: SgFilter
    let rules: [JObj]
    let onDelete: (JObj) -> Void

    private var filtered: [JObj] {
        let q = f.q.trimmingCharacters(in: .whitespaces).lowercased()
        let useQ = rules.count > 10 && !q.isEmpty
        return rules.filter { r in
            if f.dir != "all" && r.optString("direction") != f.dir { return false }
            if !useQ { return true }
            let hay = [r.optString("port"), r.optString("cidr"), r.optString("protocol"), r.optString("desc")].joined(separator: " ").lowercased()
            return hay.contains(q)
        }
    }

    var body: some View {
        let list = filtered
        VStack(alignment: .leading, spacing: 10) {
            Picker("方向", selection: $f.dir) {
                Text("全部").tag("all")
                Text("入站").tag("ingress")
                Text("出站").tag("egress")
            }
            .pickerStyle(.segmented)
            if rules.count > 10 {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass").foregroundColor(.secondary).font(.footnote)
                    TextField("筛选：端口、IP/CIDR、协议、描述", text: $f.q)
                        .font(.subheadline)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                    if !f.q.isEmpty {
                        Button {
                            f.q = ""
                        } label: {
                            Image(systemName: "xmark.circle.fill").foregroundColor(.secondary)
                        }
                        .buttonStyle(.borderless)
                    }
                }
                .padding(.horizontal, 8).padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Color(UIColor.tertiarySystemFill)))
            }
            Text(list.count == rules.count ? "共 \(rules.count) 条" : "显示 \(list.count) / \(rules.count) 条")
                .font(.caption).foregroundColor(.secondary)
            if list.isEmpty {
                Text(rules.isEmpty ? "没有规则" : "没有匹配的规则").font(.subheadline).foregroundColor(.secondary)
            }
            ForEach(list.indices, id: \.self) { i in
                SgRuleRow(ru: list[i], onDelete: onDelete)
                if i < list.count - 1 { Divider() }
            }
        }
        .padding(.vertical, 6)
        .animation(.spring(response: 0.3, dampingFraction: 0.85), value: f.dir)
    }
}

struct SgRuleRow: View {
    let ru: JObj
    let onDelete: (JObj) -> Void

    var body: some View {
        let inbound = ru.optString("direction") == "ingress"
        let cidr = ru.optString("cidr")
        let pub = inbound && (cidr == "0.0.0.0/0" || cidr == "::/0")
        let desc = ru.optString("desc")
        let sub: String = cidr + (desc.isEmpty ? "" : " · " + desc) + " · " + ru.optString("sl_name")
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: inbound ? "arrow.down.circle.fill" : "arrow.up.circle.fill")
                .foregroundColor(inbound ? .green : .blue)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(ru.optString("protocol") + " · 端口 " + ru.optString("port")).font(.subheadline.weight(.semibold))
                    if pub {
                        Text("公网").font(.caption2.weight(.semibold)).foregroundColor(.orange)
                            .padding(.horizontal, 6).padding(.vertical, 1)
                            .background(Capsule().fill(Color.orange.opacity(0.15)))
                    }
                }
                Text(sub).font(.caption).foregroundColor(.secondary).textSelection(.enabled)
            }
            Spacer(minLength: 4)
            Button(role: .destructive) {
                Haptics.tap()
                onDelete(ru)
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.borderless)
        }
    }
}
