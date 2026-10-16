import SwiftUI
import UIKit

// build 23 OneDrive 备份计划编辑（对照 Web odSchedForm / Android OneDriveScheduleActivity）：
// 每 N 小时 / 每天多个时间点 / 每周多选 / 每月日期（含月末）/ Cron；修改时调用 POST /onedrive/schedule/preview
// 实时显示「接下来 3 次」，非法配置直接显示后端的友好错误。iOS 原生分组 Form（HIG）。

final class OneDriveSchedulePage: Page {
    static let modes: [(String, String)] = [("hourly", "每 N 小时"), ("daily", "每天"), ("weekly", "每周"), ("monthly", "每月"), ("cron", "Cron")]

    @Published var enabled = true
    @Published var mode = "daily" { didSet { schedulePreview() } }
    @Published var everyHours = 6 { didSet { schedulePreview() } }
    @Published var minute = 0 { didSet { schedulePreview() } }
    @Published var startHour = 0 { didSet { schedulePreview() } }
    @Published var times: [String] = ["03:30"] { didSet { schedulePreview() } }
    @Published var weekdays: Set<Int> = [0] { didSet { schedulePreview() } }
    @Published var days: Set<Int> = [1] { didSet { schedulePreview() } }
    @Published var lastDay = false { didSet { schedulePreview() } }
    @Published var cron = "30 3 * * *" { didSet { schedulePreview() } }
    @Published var keep = 30
    @Published var newTime = Date()
    @Published var previewText = "计算中…"
    @Published var previewError = false
    let tz: String
    var onSaved: (() -> Void)?
    private var seq = 0

    init(cfg c: JObj, tz: String) {
        self.tz = tz
        super.init()
        title = "备份计划"
        enabled = c.optBoolean("enabled", true)
        mode = c.isNull("mode") ? (c.optString("freq") == "weekly" ? "weekly" : "daily") : c.optString("mode")
        everyHours = c.optInt("every_hours", 6)
        minute = c.optInt("minute", 0)
        startHour = c.optInt("start_hour", 0)
        let ts = c.optJSONArray("times") ?? []
        times = ts.isEmpty ? [c.optString("time", "03:30")] : (0..<ts.count).map { ts.string($0) }
        let wd = c.optJSONArray("weekdays") ?? []
        weekdays = wd.isEmpty ? [c.optInt("weekday", 0)] : Set((0..<wd.count).map { Int(wd.string($0)) ?? 0 })
        if let ds = c.optJSONArray("days") { days = Set((0..<ds.count).compactMap { Int(ds.string($0)) }) }
        lastDay = c.optBoolean("last_day")
        cron = c.optString("cron", "30 3 * * *")
        keep = c.optInt("keep", 30)
    }

    override func makeView() -> AnyView { AnyView(OneDriveScheduleView(page: self)) }
    override func refresh() { schedulePreview() }
    override func disappeared() { seq += 1 }

    func body() -> JObj {
        var b: JObj = ["mode": mode]
        switch mode {
        case "hourly":
            b["every_hours"] = everyHours; b["minute"] = minute; b["start_hour"] = startHour
        case "cron":
            b["cron"] = cron.trimmingCharacters(in: .whitespacesAndNewlines)
        default:
            b["times"] = times.sorted()
            if mode == "weekly" { b["weekdays"] = weekdays.sorted() }
            if mode == "monthly" { b["days"] = days.sorted(); b["last_day"] = lastDay }
        }
        return b
    }

    func schedulePreview() {
        seq += 1
        let my = seq
        later(0.4) { if my == self.seq { self.loadPreview(my) } }
    }

    private func loadPreview(_ my: Int) {
        Api.call("POST", "/onedrive/schedule/preview", body()) { res in
            guard my == self.seq else { return }
            switch res {
            case .success(let r):
                let o = jobj(r)
                let l = o.optJSONArray("next_runs_label") ?? []
                var s = o.optString("desc") + "（" + o.optString("timezone") + "）"
                for i in 0..<l.count { s += "\n· " + l.string(i) }
                self.previewText = s
                self.previewError = false
            case .failure(let err):
                if let e = err as? ApiError, e.code == 401 { self.toLogin(); return }
                self.previewText = "⚠️ " + ((err as? ApiError)?.msg ?? err.localizedDescription)
                self.previewError = true
            }
        }
    }

    static let hm: DateFormatter = { let f = DateFormatter(); f.dateFormat = "HH:mm"; f.locale = Locale(identifier: "en_US_POSIX"); return f }()

    func addTime() {
        let t = OneDriveSchedulePage.hm.string(from: newTime)
        if times.count >= 24 { toast("最多 24 个时间点"); return }
        if !times.contains(t) { times = (times + [t]).sorted() }
        Haptics.select()
    }

    func removeTimes(_ idx: IndexSet) {
        if times.count - idx.count < 1 { toast("至少保留一个时间点"); return }
        var t = times
        t.remove(atOffsets: idx)
        times = t
    }

    func toggleWeekday(_ i: Int) {
        if weekdays.contains(i) { weekdays.remove(i) } else { weekdays.insert(i) }
        Haptics.select()
    }

    func toggleDay(_ d: Int) {
        if days.contains(d) { days.remove(d) } else { days.insert(d) }
        Haptics.select()
    }

    func save() {
        var b = body()
        b["enabled"] = enabled
        b["keep"] = keep
        post("/onedrive/config", b) { x in
            let o = jobj(x)
            Haptics.success()
            self.toast("已保存：" + o.optString("desc") + (o.isNull("next_run") ? "" : "，下次 " + o.optString("next_run")))
            self.onSaved?()
            self.finish()
        }
    }
}

struct OneDriveScheduleView: View {
    @ObservedObject var page: OneDriveSchedulePage
    private let cols = Array(repeating: GridItem(.flexible(), spacing: 6), count: 7)

    var body: some View {
        Form {
            Section(footer: Text(verbatim: "时间按面板时区（\(page.tz)）。两次备份至少间隔 30 分钟。")) {
                Toggle("启用定时备份", isOn: $page.enabled)
                Picker("频率", selection: $page.mode) {
                    ForEach(OneDriveSchedulePage.modes, id: \.0) { m in Text(m.1).tag(m.0) }
                }
            }
            modeSections
            Section(header: Text("保留")) {
                Stepper(value: $page.keep, in: 1...365) { Text(verbatim: "保留最近 \(page.keep) 份") }
            }
            Section(header: Text("接下来 3 次")) {
                Text(verbatim: page.previewText)
                    .font(.subheadline)
                    .foregroundColor(page.previewError ? .red : .primary)
                    .textSelection(.enabled)
            }
            Section {
                Button { page.save() } label: { Text("保存计划").font(.headline).frame(maxWidth: .infinity) }
            }
        }
        .modifier(PageChrome(page: page))
    }

    @ViewBuilder
    private var modeSections: some View {
        if page.mode == "hourly" {
            Section(header: Text("每 N 小时"), footer: Text("每天从起始小时起按间隔对齐，0 分 = 整点。例：每 6 小时、第 15 分、起始 0 点 = 00:15、06:15、12:15、18:15。")) {
                Stepper(value: $page.everyHours, in: 1...24) { Text(verbatim: "每隔 \(page.everyHours) 小时") }
                Stepper(value: $page.minute, in: 0...59) { Text(verbatim: "第 \(page.minute) 分") }
                Stepper(value: $page.startHour, in: 0...23) { Text(verbatim: "起始 \(page.startHour) 点") }
            }
        }
        if page.mode == "daily" || page.mode == "weekly" || page.mode == "monthly" {
            Section(header: Text("时间点（左滑删除）")) {
                ForEach(page.times, id: \.self) { t in
                    Text(verbatim: t).font(.body.monospacedDigit())
                }
                .onDelete { page.removeTimes($0) }
                HStack {
                    DatePicker("新时间", selection: $page.newTime, displayedComponents: .hourAndMinute)
                    Button("添加") { page.addTime() }
                        .buttonStyle(.borderless)
                }
            }
        }
        if page.mode == "weekly" {
            Section(header: Text("星期（可多选）")) {
                ForEach(0..<7, id: \.self) { i in
                    Button { page.toggleWeekday(i) } label: {
                        HStack {
                            Text(verbatim: OneDrivePage.weekdays[i]).foregroundColor(.primary)
                            Spacer()
                            if page.weekdays.contains(i) { Image(systemName: "checkmark").foregroundColor(.accentColor) }
                        }
                    }
                }
            }
        }
        if page.mode == "monthly" {
            Section(header: Text("日期（可多选）"), footer: Text("没有这一天的月份会跳过（如 31 日），每月最后一天请打开「月末」。")) {
                LazyVGrid(columns: cols, spacing: 6) {
                    ForEach(1...31, id: \.self) { d in
                        Button { page.toggleDay(d) } label: {
                            Text(verbatim: "\(d)")
                                .font(.subheadline.monospacedDigit())
                                .frame(maxWidth: .infinity, minHeight: 34)
                                .foregroundColor(page.days.contains(d) ? .white : .primary)
                                .background(page.days.contains(d) ? Color.accentColor : Color(UIColor.tertiarySystemFill))
                                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        }
                        .buttonStyle(.borderless)
                    }
                }
                .padding(.vertical, 4)
                Toggle("月末", isOn: $page.lastDay)
            }
        }
        if page.mode == "cron" {
            Section(header: Text("Cron 表达式（分 时 日 月 周）"),
                    footer: Text("支持 * , - / 和数字、mon/jan 等缩写、@daily。例：30 3 * * 1-5 工作日 03:30；0 */6 * * * 每 6 小时；0 4 1,15 * * 每月 1、15 日。日和周都指定时满足任一即可。")) {
                TextField("30 3 * * 1-5", text: $page.cron)
                    .font(.system(.body, design: .monospaced))
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
            }
        }
    }
}
