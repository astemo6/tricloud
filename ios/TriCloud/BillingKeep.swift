import SwiftUI

// OCI 一键生成保号账单（仅 PAYG 升级号，build 19 补到 App，与 Web billingKeepCard 一致）：
// 先检测已有存储（所有已订阅区域的 Bucket），标准层补足到约 11 GB、超出 10 GB 免费额度，每月约 $0.02–0.03。

extension AccountPage {
    static let BK_TITLE = "一键生成保号账单"

    /// 存储层：standard / autotier（标准层但开了自动分层）/ archive / unknown。
    static func tierLabel(_ b: JObj) -> String {
        var t = str(b, "tier", "")
        if t.isEmpty {
            let st = str(b, "storage_tier", "")
            let at = str(b, "auto_tiering", "Disabled")
            if st == "Archive" { t = "archive" } else if st == "Standard" { t = at != "Disabled" ? "autotier" : "standard" } else { t = "unknown" }
        }
        switch t {
        case "standard": return "标准"
        case "autotier": return "标准 · 自动分层"
        case "archive": return "归档"
        default: return "—"
        }
    }

    /// 去掉多余的 0：11.0 → 11，7.80 → 7.8。
    static func numStr(_ v: Double) -> String {
        if v.isNaN { return "-" }
        var s = String(format: "%.2f", v)
        while s.contains(".") && (s.hasSuffix("0") || s.hasSuffix(".")) { s.removeLast() }
        return s
    }
    static func gib(_ n: Int64) -> String { String(format: "%.2f GiB", Double(n) / 1073741824.0) }
    static func gb2(_ v: Double) -> String { String(format: "%.2f GB", v.isNaN ? 0 : v) }

    static func bucketLine(_ b: JObj) -> String {
        let size: String = b.isNull("size") ? "—" : fmtBytes(b.optLong("size"))
        return "大小 " + size + " · 对象 " + str(b, "count", "—") + " · 存储层 " + AccountPage.tierLabel(b)
    }
}

final class BillingKeepModel: ObservableObject {
    weak var page: AccountPage?
    let accId: Int
    let gen: Int
    /// loading / error / ineligible / running / ready
    @Published var phase = "loading"
    @Published var d: JObj = [:]
    @Published var scan: JObj?
    @Published var scanErr = ""
    @Published var scanning = false
    @Published var errText = ""
    @Published var size = ""
    @Published var showBuckets = false

    init(_ page: AccountPage, _ gen: Int) {
        self.page = page
        self.accId = page.id
        self.gen = gen
    }

    /// 卡片仍在当前页面上（切换标签 / 打开 Bucket / 刷新后丢弃过期回调，也停止轮询）。
    var alive: Bool {
        guard let p = page else { return false }
        return p.cur(gen) && p.tab == "objects" && p.objBucket == nil
    }

    var plan: String { d.optString("plan") }
    var planBadge: String { plan == "paid" ? "PAYG" : plan == "free" ? "免费号" : "类型未知" }
    var task: JObj { d.optJSONObject("task") ?? [:] }
    var over: Bool { scan?.optBoolean("over_free") ?? false }
    var used: Double { scan?.optDouble("standard_gb", 0) ?? 0 }
    var defGb: Double {
        let def = d.optDouble("default_gb", 11)
        if let s = scan { return s.optDouble("fill_gb", def) }
        return def
    }
    var minGb: Double { d.optDouble("min_gb", 0.5) }
    var maxGb: Double { d.optDouble("max_gb", 20) }
    var pending: Int { (d.optJSONArray("pending_uploads") ?? []).count }
    var resumable: Bool {
        let st = task.optString("status")
        return pending > 0 && ["failed", "stopped", "interrupted"].contains(st) && task.optLong("uploaded") > 0
    }
    var goText: String {
        if resumable { return "继续上传（已传 " + AccountPage.gib(task.optLong("uploaded")) + "）" }
        return over ? "仍要生成" : "生成保号账单"
    }
    var progress: Double {
        let tot = task.optLong("total")
        return tot > 0 ? min(1, Double(task.optLong("uploaded")) / Double(tot)) : 0
    }
    var progressText: String {
        let pct = Int(progress * 100)
        return "上传中：" + AccountPage.gib(task.optLong("uploaded")) + " / " + AccountPage.gib(task.optLong("total")) + "（\(pct)%）"
    }
    var lastTaskText: String {
        let st = task.optString("status")
        if task.isEmpty || st == "done" || st.isEmpty { return "" }
        return "上次任务 #\(task.optInt("id"))：" + st + " · " + str(task, "message", "")
    }
    var existsText: String {
        "✅ 已存在保号对象 " + d.optString("bucket") + "/" + d.optString("object") + "：" + AccountPage.gib(d.optLong("size"))
            + "（" + Regions.label(d.optString("region")) + " · " + str(d, "storage_tier", "Standard") + "）"
    }

    // MARK: 检测结果文字

    var usedText: String {
        guard let s = scan else { return "" }
        return "标准层已用 " + AccountPage.gb2(used) + " / 免费 " + AccountPage.numStr(s.optDouble("free_gb", 10)) + " GB"
    }
    var scanMeta: String {
        guard let s = scan else { return "" }
        let nr = (s.optJSONArray("regions") ?? []).count
        let nb = (s.optJSONArray("buckets") ?? []).count
        var t = "\(nr) 个区域 · \(nb) 个 Bucket"
        if s.optBoolean("cached") { t += " · \(Int((Double(s.optInt("age")) / 60).rounded())) 分钟前检测" }
        return t
    }
    var verdict: String {
        guard let s = scan else { return "" }
        if over { return "✅ 已满足：标准层已超出 10 GB 免费额度，已经会产生小额账单，无需生成。" }
        let short = AccountPage.numStr(s.optDouble("short_gb", 0))
        return "还差 " + short + " GB 才超出 10 GB 免费额度；建议补足 " + AccountPage.numStr(defGb) + " GB，补足后标准层合计约 " + AccountPage.gb2(used + defGb) + "。"
    }
    var extraText: String {
        guard let s = scan else { return "" }
        var ex: [String] = []
        let at = s.optDouble("autotier_gb", 0), ar = s.optDouble("archive_gb", 0)
        if at > 0 { ex.append("另有 " + AccountPage.gb2(at) + " 在开了自动分层的标准层 Bucket 里（久未访问的对象会转低频层，未计入标准层）") }
        if ar > 0 { ex.append("归档层 " + AccountPage.gb2(ar) + "（归档层单独计免费额度，不计入标准层）") }
        if s.optInt("unknown_count") > 0 { ex.append("\(s.optInt("unknown_count")) 个 Bucket 读不到大小（显示 —，未计入）") }
        let errs = s.optJSONArray("errors") ?? []
        if !errs.isEmpty {
            let rs = (0..<errs.count).map { Regions.label(errs.obj($0).optString("region")) }
            ex.append("部分区域读取失败：" + rs.joined(separator: "、"))
        }
        if s.optBoolean("compartments_truncated") { ex.append("区间太多，只检测了前 \(s.optInt("compartments")) 个") }
        return ex.isEmpty ? "" : ex.joined(separator: "；") + "。"
    }
    var bucketLines: [String] {
        guard let s = scan else { return [] }
        let bs = s.optJSONArray("buckets") ?? []
        return (0..<bs.count).map { i in
            let b = bs.obj(i)
            let tag: String = b.optBoolean("billing_keep") ? " [保号]" : ""
            return b.optString("name") + tag + " · " + Regions.label(b.optString("region")) + " · " + AccountPage.bucketLine(b)
        }
    }
    var afterText: String {
        if scan == nil { return "" }
        let v = Double(size.trimmingCharacters(in: .whitespaces)) ?? 0
        return "补足后标准层合计约 " + AccountPage.gb2(used + v)
    }

    // MARK: 网络

    func load(wasRunning: Bool = false, rescan: Bool = false) {
        Api.call("GET", "/accounts/\(accId)/oci/billing-keep", nil) { res in
            guard self.alive else { return }
            switch res {
            case .failure(let e):
                if let ae = e as? ApiError, ae.code == 401 { self.page?.toLogin(); return }
                self.errText = (e as? ApiError)?.msg ?? e.localizedDescription
                self.phase = "error"
            case .success(let x):
                let d = jobj(x)
                self.d = d
                if !d.optBoolean("eligible") { self.phase = "ineligible"; return }
                if self.task.optString("status") == "running" {
                    self.phase = "running"
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                        guard let self = self, self.alive else { return }
                        self.load(wasRunning: true)
                    }
                    return
                }
                self.phase = "ready"
                self.scanning = true
                self.scan = nil
                self.scanErr = ""
                self.size = AccountPage.numStr(self.defGb)
                let fresh = rescan || wasRunning
                Api.call("GET", "/accounts/\(self.accId)/oci/billing-keep/scan" + (fresh ? "?refresh=true" : ""), nil) { sr in
                    guard self.alive else { return }
                    self.scanning = false
                    switch sr {
                    case .success(let y): self.scan = jobj(y)
                    case .failure(let e): self.scanErr = (e as? ApiError)?.msg ?? e.localizedDescription
                    }
                    self.size = AccountPage.numStr(self.defGb)
                }
            }
        }
    }

    func go() {
        guard let p = page else { return }
        let v = Double(size.trimmingCharacters(in: .whitespaces)) ?? defGb
        if !(v >= minGb && v <= maxGb) { p.toast("大小范围 " + AccountPage.numStr(minGb) + "–" + AccountPage.numStr(maxGb) + " GB"); return }
        let tot: String = scan != nil ? "，补足后标准层合计约 " + AccountPage.gb2(used + v) : ""
        let msg = d.optString("note") + "\n\n本次大小：" + AccountPage.numStr(v) + " GB" + tot + "（标准层超出 10 GB 的部分按量计费）。删除对象即停止计费。确认开始？"
        let start: () -> Void = {
            p.confirm(AccountPage.BK_TITLE, msg) {
                p.post("/accounts/\(self.accId)/oci/billing-keep", ["size_gb": v, "confirm": true]) { x in
                    let o = jobj(x)
                    if o.optBoolean("existed") { p.toast("对象已存在：" + AccountPage.gib(o.optLong("size")) + "，未重复上传") }
                    else { p.toast(o.optBoolean("resumed") ? "已继续上传" : "已开始上传") }
                    if self.alive { self.load() }
                }
            }
        }
        if over {
            // 已满足：先多一次红色确认（标题 + 按钮「仍要生成」→ destructive）
            p.message("无需生成", "标准层已用 " + AccountPage.gb2(used) + "，已超出 10 GB 免费额度，已经会产生小额账单，无需生成。\n再生成会让账单变多，仍要继续？",
                      primary: ("仍要生成", start), cancel: "取消")
        } else {
            start()
        }
    }

    func delete() {
        guard let p = page else { return }
        p.confirm("删除保号对象", "删除 tricloud-billing-keep 里的保号对象并中止未完成的上传（Bucket 空了一并删除）？之后不再产生这笔账单。") {
            p.del("/accounts/\(self.accId)/oci/billing-keep?confirm=true") { _ in
                p.toast("已删除")
                if self.alive { self.load(rescan: true) }
            }
        }
    }
}

struct BillingKeepView: View {
    @ObservedObject var m: BillingKeepModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(AccountPage.BK_TITLE).font(.headline)
                if m.phase != "loading" && m.phase != "error" {
                    Text(m.planBadge).font(.caption2.weight(.semibold))
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Capsule().fill(Color.accentColor.opacity(0.15)))
                }
                Spacer()
            }
            if m.phase == "loading" {
                HStack(spacing: 8) { ProgressView(); Text("加载中…").font(.footnote).foregroundColor(.secondary) }
            } else if m.phase == "error" {
                Text("❌ " + m.errText).font(.footnote)
            } else if m.phase == "ineligible" {
                Text(m.d.optString("hint")).font(.footnote).foregroundColor(.secondary)
            } else if m.phase == "running" {
                note
                ProgressView(value: m.progress)
                Text(m.progressText).font(.footnote)
                Button {
                    Haptics.tap()
                    m.page?.openTask(m.task.optInt("id"))
                } label: {
                    Text("查看任务 #\(m.task.optInt("id"))").font(.footnote.weight(.medium))
                }
                .buttonStyle(.bordered)
            } else {
                note
                scanSection
                actions
            }
        }
        .padding(.vertical, 6)
    }

    private var note: some View {
        Text(m.d.optString("note")).font(.footnote).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
    }

    @ViewBuilder private var scanSection: some View {
        if m.scanning {
            HStack(spacing: 8) { ProgressView(); Text("正在检测已有存储…").font(.footnote).foregroundColor(.secondary) }
        } else if m.scan != nil {
            Text(m.usedText).font(.subheadline.weight(.semibold))
            Text(m.scanMeta).font(.caption).foregroundColor(.secondary)
            Text(m.verdict).font(.footnote).foregroundColor(m.over ? .green : .primary).fixedSize(horizontal: false, vertical: true)
            if !m.extraText.isEmpty {
                Text(m.extraText).font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            if m.bucketLines.isEmpty {
                Text("没有找到已有 Bucket。").font(.caption).foregroundColor(.secondary)
            } else {
                DisclosureGroup(isExpanded: $m.showBuckets) {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(m.bucketLines.indices, id: \.self) { i in
                            Text(m.bucketLines[i]).font(.caption).textSelection(.enabled)
                        }
                    }
                } label: {
                    Text("已有 Bucket（\(m.bucketLines.count)）").font(.footnote)
                }
            }
            Text("大小为 OCI 定期统计的近似值（approximateSize），刚上传的数据可能要几小时后才计入。").font(.caption2).foregroundColor(.secondary)
        } else {
            Text("⚠️ 检测已有存储失败：" + m.scanErr + "。无法确认标准层已用量，默认按 " + AccountPage.numStr(m.defGb) + " GB 生成。")
                .font(.footnote).fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder private var actions: some View {
        if m.d.optBoolean("exists") {
            Text(m.existsText).font(.footnote).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Button("重新检测") { m.load(rescan: true) }.buttonStyle(.bordered)
                Button(role: .destructive) { m.delete() } label: { Text("删除") }
                    .buttonStyle(.bordered).tint(.red)
            }
        } else if !m.scanning {
            if !m.lastTaskText.isEmpty { Text(m.lastTaskText).font(.caption).foregroundColor(.secondary) }
            HStack(spacing: 8) {
                Text("大小 GB").font(.subheadline)
                TextField(AccountPage.numStr(m.defGb), text: $m.size)
                    .keyboardType(.decimalPad)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 96)
                Text(AccountPage.numStr(m.minGb) + "–" + AccountPage.numStr(m.maxGb)).font(.caption).foregroundColor(.secondary)
                Spacer()
            }
            if !m.afterText.isEmpty { Text(m.afterText).font(.caption).foregroundColor(.secondary) }
            HStack(spacing: 8) {
                if m.over {
                    Button(m.goText) { Haptics.tap(); m.go() }.buttonStyle(.bordered)
                } else {
                    Button(m.goText) { Haptics.tap(); m.go() }.buttonStyle(.borderedProminent)
                }
                Button("重新检测") { m.load(rescan: true) }.buttonStyle(.bordered)
            }
            if m.pending > 0 {
                Button(role: .destructive) { m.delete() } label: { Text("删除未完成的上传") }
                    .buttonStyle(.bordered).tint(.red)
            }
        }
    }
}
