import SwiftUI

// AccountActivity：OCI 流量、安全组（build 19 起按子网选择，可改子网 / VCN 名称）。

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
            if items.isEmpty { self.card("本区域没有实例").muted(Regions.label(self.region())); return }
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

    /// 「VCN / 子网 CIDR · 实例1、实例2」，实例多于 4 台时「… 等 N 台」，与 Web subnetLabel 一致。
    static func subnetLabel(_ s: JObj) -> String {
        let ins = s.optJSONArray("instances") ?? []
        let names = (0..<min(ins.count, 4)).map { str(ins.obj($0), "name", "?") }
        let tail: String = ins.isEmpty ? "无实例" : names.joined(separator: "、") + (ins.count > 4 ? " 等 \(ins.count) 台" : "")
        let vcn = str(s, "vcn_name", "")
        return (vcn.isEmpty ? "" : vcn + " / ") + str(s, "name", "子网") + " " + str(s, "cidr", "") + " · " + tail
    }

    /// build 19：安全组按子网选择（安全列表挂在子网上，同子网实例共享）；查看 / 添加 / 删除都带 subnet_id。
    func secgroup() {
        let g = gen
        get("/accounts/\(id)/oci/security-subnets?" + rq()) { r in
            guard self.cur(g) else { return }
            let a = jobj(r).optJSONArray("subnets") ?? []
            if a.isEmpty { self.card("该区域没有子网").muted(Regions.label(self.region())); return }
            let subs = (0..<a.count).map { a.obj($0) }
            let ids = subs.map { $0.optString("id") }
            let labels = subs.map { AccountPage.subnetLabel($0) }
            var chosen = self.sgSub ?? Prefs.get("sgsub_\(self.id)", "")
            if !ids.contains(chosen) {   // 旧版记的是实例：换成该实例所在的子网
                let li = Prefs.get("sg_\(self.id)", "")
                chosen = ids[0]
                for s in subs {
                    let ins = s.optJSONArray("instances") ?? []
                    if (0..<ins.count).contains(where: { ins.obj($0).optString("id") == li }) { chosen = s.optString("id") }
                }
            }
            self.sgSub = chosen
            Prefs.set("sgsub_\(self.id)", chosen)
            let idx = ids.firstIndex(of: chosen) ?? 0
            let sub = subs[idx]
            let sc = self.card("子网")
            sc.text(labels[idx], 14, true)
            sc.muted("安全列表跟着子网走：规则对该子网里的所有实例生效；不支持对 0.0.0.0/0 放行全部端口")
            let top = sc.row()
            top.button("切换子网") {
                self.choose("选择子网", labels) { i in
                    self.sgSub = ids[i]
                    Prefs.set("sgsub_\(self.id)", ids[i])
                    self.refresh()
                }
            }
            top.button("改名") { self.renameSubnet(sub) }
            top.button("＋ 添加规则") { self.sgAdd() }
            // 实例另挂的 NSG：只读提示
            let ins = sub.optJSONArray("instances") ?? []
            var nsgLines: [String] = []
            for i in 0..<ins.count {
                let it = ins.obj(i)
                let gs = it.optJSONArray("nsgs") ?? []
                if gs.isEmpty { continue }
                let gn = (0..<gs.count).map { str(gs.obj($0), "name", "?") }.joined(separator: "、")
                nsgLines.append(str(it, "name", "?") + "：此实例另挂 NSG：" + gn)
            }
            let sid = chosen
            let nsgText = nsgLines.joined(separator: "\n")
            self.get("/accounts/\(self.id)/security-rules?subnet_id=" + enc(sid) + "&" + self.rq()) { x in
                guard self.cur(g) else { return }
                let ra = jobj(x).optJSONArray("rules") ?? []
                let rules = (0..<ra.count).map { ra.obj($0) }
                // 全部 / 入站 / 出站 分段切换（始终显示）；规则超过 10 条时显示筛选框（端口、IP/CIDR、协议、描述）
                self.view(AnyView(SgRulesView(f: self.sgFilter, rules: rules, onDelete: { ru in self.sgDelete(sid, ru) })))
                if !nsgText.isEmpty {
                    let nc = self.card("网络安全组（NSG，只读）")
                    nc.text(nsgText, 13)
                    nc.muted("NSG 规则与安全列表同时生效（取并集），App 不修改 NSG，请到 OCI 控制台查看。")
                }
            }
        }
    }

    /// 子网 / VCN 改名：只改显示名称（display_name），不影响实例、IP、安全规则；保存后刷新并保持选中。
    func renameSubnet(_ s: JObj) {
        let sid = s.optString("id"), vid = str(s, "vcn_id", "")
        let oldS = str(s, "name", ""), oldV = str(s, "vcn_name", "")
        var f: [Field] = [Field.text("subnet", "子网名称", oldS)]
        if !vid.isEmpty { f.append(Field.text("vcn", "所属 VCN 名称（可一并修改）", oldV)) }
        form("子网改名", "只修改显示名称，不影响子网里的实例、IP 和安全规则。" + str(s, "cidr", ""), f, "保存") { v in
            let ns = v.optString("subnet").trimmingCharacters(in: .whitespacesAndNewlines)
            let nv = v.optString("vcn").trimmingCharacters(in: .whitespacesAndNewlines)
            if ns.isEmpty || (!vid.isEmpty && nv.isEmpty) { self.toast("名称不能为空"); return }
            if ns.count > 255 || nv.count > 255 { self.toast("名称最多 255 个字符"); return }
            let chS = ns != oldS
            let chV = !vid.isEmpty && nv != oldV
            if !chS && !chV { self.toast("名称没有变化"); return }
            let done: () -> Void = {
                self.toast("已改名")
                self.sgSub = sid
                Prefs.set("sgsub_\(self.id)", sid)
                self.refresh()
            }
            let vcnStep: () -> Void = {
                if chV { self.patchName("/oci/vcns/" + enc(vid), nv, done) } else { done() }
            }
            if chS { self.patchName("/oci/subnets/" + enc(sid), ns, vcnStep) } else { vcnStep() }
        }
    }

    func patchName(_ path: String, _ name: String, _ then: @escaping () -> Void) {
        request("PATCH", "/accounts/\(id)" + path, ["display_name": name, "region": region()]) { _ in then() }
    }

    func sgDelete(_ subnetId: String, _ ru: JObj) {
        let inbound = ru.optString("direction") == "ingress"
        let warn22: String = inbound && ru.optString("port") == "22" ? "\n⚠️ 删除 22 端口规则可能导致无法 SSH 登录。" : ""
        confirm("删除规则", "删除这条规则？" + warn22) {
            let p = ru.optString("protocol")
            let proto = p == "全部" ? "all" : p.lowercased()
            var b: JObj = ["subnet_id": subnetId, "region": self.region(), "sl_id": ru.optString("sl_id"),
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
            b["subnet_id"] = self.sgSub ?? ""
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
