import SwiftUI

/// build 22 流量守护 agent 与端口流量明细（对应 Android GuardAgentActivity / Web guardAgentDialog + guardPortsDialog）：
/// agent 在线状态与最后心跳、当前是否限速、可复制的安装 / 卸载命令、重置 token、流量明细开关；
/// 今日 / 本月按端口和按服务的 Top（入站、出站、合计 + 占比条）。面板不会远程执行任何命令。
final class GuardAgentPage: Page {
    private let gid: Int
    private let name: String
    private var range = "today"
    private var byService = false
    private var gen = 0

    init(_ gid: Int, _ name: String) {
        self.gid = gid
        self.name = name
        super.init()
        title = "流量守护 · " + (name.isEmpty ? "#\(gid)" : name)
    }

    private var base: String { enc(Api.server) }

    static func agentLine(_ a: JObj?, _ throttleAction: Bool, _ throttled: Bool) -> String {
        guard let a = a else { return "" }
        let st = !a.optBoolean("installed") ? "⚪ agent 未安装" : a.optBoolean("online") ? "🟢 agent 在线" : "🔴 agent 离线"
        let seen = a.isNull("last_seen_text") ? "" : "，最后心跳 " + a.optString("last_seen_text")
        let thr = !throttleAction ? "" : a.optBoolean("applied") ? " · 🐢 当前已限速" : throttled ? " · 应限速（等 agent 生效）" : " · 当前未限速"
        return st + seen + thr
    }

    override func refresh() {
        gen += 1
        let g = gen
        get("/traffic-guards/\(gid)/agent?base=" + base) { r in
            guard g == self.gen else { return }
            self.clear()
            self.renderAgent(jobj(r))
            self.loadPorts(g)
        }
    }

    private func renderAgent(_ d: JObj) {
        let a = d.optJSONObject("agent") ?? [:]
        let throttled = d.optBoolean("throttled")
        let c = card("agent 状态")
        var s = GuardAgentPage.agentLine(a, true, throttled)
        s += "\n超限后出站限速：" + str(d, "throttle_mbps", "1") + " Mbps（SSH 端口不限，仅「推送并限速」规则生效）"
        s += "\n当前：" + (throttled ? "已触发限速" : "未触发限速") + (a.optBoolean("applied") ? "（agent 已生效）" : "")
        if !a.isNull("iface") { s += "\n网卡：" + a.optString("iface") }
        if !a.isNull("ssh_ports") { s += "  SSH 端口：" + a.optString("ssh_ports") }
        let be = a.isNull("acct_backend_text") ? "等待 agent 上报"
            : a.optString("acct_backend_text") + (a.isNull("acct_ports") ? "" : "，\(a.optInt("acct_ports")) 个端口")
        let acct = a.optBoolean("acct_enabled")
        s += "\n流量明细：" + (acct ? "已开启（" + be + "）" : "未开启")
        c.text(s, 14)
        c.row().button(acct ? "关闭流量明细" : "开启流量明细") {
            self.request("PATCH", "/traffic-guards/\(self.gid)", ["acct_enabled": !acct]) { _ in
                self.toast(!acct ? "已开启流量明细，agent 下次心跳（≤5 分钟）建立计数规则" : "已关闭流量明细，agent 下次心跳删除计数规则")
                self.refresh()
            }
        }
        c.muted("流量明细：按端口 / 服务统计入站、出站（nftables 独立 table，只计数不拦截；没有 nft 时用 iptables 计数链）。")

        let k = card("安装 / 卸载命令")
        guard let cm = d.optJSONObject("commands") else { k.muted("API Token 只能查看状态，不显示安装命令。"); return }
        k.muted("在这台实例上用 root 运行（面板不会远程执行任何命令）。agent 是 bash 脚本 + systemd timer，每 \(d.optInt("poll_secs", 300) / 60) 分钟用这条守护的专属 token 拉取状态并上报流量明细；超过 \(d.optInt("offline_secs", 900) / 60) 分钟没心跳算离线。")
        for (label, key) in [("安装命令", "install"), ("卸载命令（面板）", "uninstall"), ("卸载命令（本机）", "uninstall_local"), ("查看状态", "status")] {
            let v = cm.optString(key)
            k.text(label + "：\n" + v, 12)
            k.row().button("复制" + label) { copyText(v); self.toast("已复制") }
        }
        k.muted("安装命令里含这条守护的 token，只能读写这条守护的状态和流量明细；泄露了点「重置 token」，旧 agent 会自动解除限速并删除计数规则。")
        k.row().button("重置 token") {
            self.message("重置 agent token", "重置后旧的安装命令立即失效，实例上的旧 agent 会解除限速并删除计数规则，需要在实例上重新运行新的安装命令。确定重置？",
                         primary: ("重置", {
                self.post("/traffic-guards/\(self.gid)/agent/reset?base=" + self.base, [:]) { _ in self.toast("已重置，请重新安装"); self.refresh() }
            }), cancel: "取消")
        }
    }

    private func loadPorts(_ g: Int) {
        let p = card("端口流量明细")
        let sw = p.row()
        sw.button((range == "today" ? "● " : "") + "今日") { self.range = "today"; self.refresh() }
        sw.button((range == "month" ? "● " : "") + "本月") { self.range = "month"; self.refresh() }
        sw.button(byService ? "按端口" : "按服务") { self.byService.toggle(); self.refresh() }
        get("/traffic-guards/\(gid)/ports?range=" + range + "&limit=20") { r in
            guard g == self.gen else { return }
            let t = jobj(r)
            let a = t.optJSONObject("agent") ?? [:]
            let span = t.optString("start") == t.optString("end") ? t.optString("start") : t.optString("start") + " ~ " + t.optString("end")
            p.text(t.optString("title") + "（" + span + "）合计 " + t.optString("total_text") + "：入站 " + t.optString("in_text") + " / 出站 " + t.optString("out_text"), 14, true)
            if !t.optBoolean("acct_enabled") { p.muted("流量明细未开启：点上面「开启流量明细」并在实例上安装 agent。") }
            else if !a.optBoolean("installed") { p.muted("agent 尚未安装 / 尚未上报。") }
            let rows = (self.byService ? t.optJSONArray("services") : t.optJSONArray("ports")) ?? []
            if rows.isEmpty { p.muted(t.optString("title") + "还没有数据"); return }
            var items: [PortShare] = []
            for i in 0..<rows.count {
                let x = rows.obj(i)
                let label = self.byService ? x.optString("service") : x.optString("label")
                let ports = self.byService ? join(x.optJSONArray("ports")) : ""
                var pct = x.optDouble("pct", 0)
                if pct.isNaN { pct = 0 }
                items.append(PortShare(rank: i + 1, label: label, sub: ports, total: x.optString("total_text"), inText: x.optString("in_text"),
                                       outText: x.optString("out_text"), pct: pct))
            }
            self.view(AnyView(PortShareList(items: items)))
            let foot = self.card(nil)
            foot.muted("非监听端口的流量（比如本机主动访问外网、代理的出站连接）归为「其他/出站连接」。agent 每 5 分钟上报，按天保存 \(t.optInt("retain_days", 90)) 天。")
        }
    }
}

struct PortShare: Identifiable {
    let id = UUID()
    let rank: Int
    let label: String
    let sub: String
    let total: String
    let inText: String
    let outText: String
    let pct: Double
}

/// 端口 / 服务 Top 列表：每行名称 + 合计 + 入 / 出 + 占比条（ProgressView，HIG 原生控件）。
struct PortShareList: View {
    let items: [PortShare]
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(items) { it in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("\(it.rank). " + it.label).font(.subheadline.weight(.semibold)).lineLimit(2)
                        Spacer()
                        Text(it.total).font(.subheadline.monospacedDigit())
                    }
                    if !it.sub.isEmpty { Text(it.sub).font(.caption).foregroundColor(.secondary) }
                    ProgressView(value: min(100, max(0, it.pct)), total: 100)
                    HStack {
                        Text("入 " + it.inText + " · 出 " + it.outText).font(.caption).foregroundColor(.secondary)
                        Spacer()
                        Text(String(format: "%.1f%%", it.pct)).font(.caption.monospacedDigit()).foregroundColor(.secondary)
                    }
                }
                .accessibilityElement(children: .combine)
            }
        }
        .padding(.vertical, 6)
    }
}
