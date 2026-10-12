import SwiftUI

/// v1.4 任务实时日志：GET /api/tasks/{id}?after=N 轮询，运行中每 2 秒刷新并滚到最底部；可停止 / 删除。对应 TaskLogActivity。
struct LogLine: Identifiable {
    let id: Int
    let text: String
    let level: String
}

final class TaskLogPage: Page {
    let tid: Int
    private var last: Int64 = 0
    private var gen = 0
    private var visible = false
    private var lineSeq = 0
    @Published var head = "读取中…"
    @Published var msg = ""
    @Published var lines: [LogLine] = []
    @Published var resultText = ""
    @Published var running = true
    @Published var loaded = false

    init(_ tid: Int) {
        self.tid = tid
        super.init()
        title = "任务 #\(tid)"
    }

    override func makeView() -> AnyView { AnyView(TaskLogView(page: self)) }

    override func appeared() {
        visible = true
        if !started { started = true; refresh() }
        else if running { poll() }
    }

    override func disappeared() {
        visible = false
        gen += 1
    }

    override func refresh() {
        gen += 1
        last = 0
        lines = []
        poll()
    }

    static let timeFmt: DateFormatter = { let f = DateFormatter(); f.dateFormat = "HH:mm:ss"; return f }()

    func poll() {
        gen += 1
        let g = gen
        get("/tasks/\(tid)?after=\(last)") { r in
            let t = jobj(r)
            self.loaded = true
            self.running = t.optString("status") == "running"
            self.head = str(t, "type_name", t.optString("type")) + " · " + TaskLogPage.stName(t.optString("status")) + "\n"
                + str(t, "account_name", "-") + (t.optInt("attempts") > 1 ? " · 已尝试 \(t.optInt("attempts")) 次" : "")
            self.msg = str(t, "message", "")
            let a = t.optJSONArray("logs") ?? []
            var newLines = self.lines
            for i in 0..<a.count {
                let l = a.obj(i)
                let ts = TaskLogPage.timeFmt.string(from: Date(timeIntervalSince1970: TimeInterval(l.optLong("ts"))))
                self.lineSeq += 1
                newLines.append(LogLine(id: self.lineSeq, text: ts + "  " + l.optString("msg"), level: l.optString("level")))
            }
            // 与 Android 一致：超过约 60000 字符时裁掉前面的日志
            var total = newLines.reduce(0) { $0 + $1.text.count + 1 }
            if total > 60000 {
                while total > 50000 && !newLines.isEmpty { total -= newLines[0].text.count + 1; newLines.removeFirst() }
            }
            self.lines = newLines
            if !t.isNull("last_log_id") { self.last = t.optLong("last_log_id") }
            var sb = ""
            if let res = t.optJSONObject("result") {
                for k in res.keys.sorted() { sb += k + "：" + (jsonText(res[k]) ?? "null") + "\n" }
            }
            self.resultText = sb.trimmingCharacters(in: .whitespacesAndNewlines)
            if self.running {
                self.later(2) { if self.visible && self.gen == g { self.poll() } }
            }
        }
    }

    func stopTask() {
        confirm("停止任务", "停止任务 #\(tid)？") { self.post("/tasks/\(self.tid)/stop", nil) { _ in self.poll() } }
    }

    func deleteTask() {
        confirm("删除记录", "删除任务 #\(tid) 及其日志？") { self.del("/tasks/\(self.tid)") { _ in self.finish() } }
    }

    static func stName(_ s: String) -> String {
        switch s {
        case "running": return "运行中"
        case "done": return "完成"
        case "failed": return "失败"
        case "stopped": return "已停止"
        case "interrupted": return "已中断（服务重启）"
        default: return s
        }
    }

    static func colorOf(_ level: String) -> Color {
        switch level {
        case "ok": return Color(red: 0x7e / 255.0, green: 0xe2 / 255.0, blue: 0xa0 / 255.0)
        case "warn": return Color(red: 1.0, green: 0xcf / 255.0, blue: 0x7a / 255.0)
        case "error": return Color(red: 1.0, green: 0x9e / 255.0, blue: 0x98 / 255.0)
        default: return Color(red: 0xd7 / 255.0, green: 0xd9 / 255.0, blue: 0xe0 / 255.0)
        }
    }
}

struct TaskLogView: View {
    @ObservedObject var page: TaskLogPage

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text(page.head).font(.system(size: 16, weight: .bold)).textSelection(.enabled)
                if !page.msg.isEmpty {
                    Text(page.msg).font(.system(size: 13)).textSelection(.enabled)
                }
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 1) {
                            if page.lines.isEmpty {
                                Text(page.loaded ? "暂无日志" : "").font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(TaskLogPage.colorOf(""))
                            }
                            ForEach(page.lines) { l in
                                Text(l.text)
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(TaskLogPage.colorOf(l.level))
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .textSelection(.enabled)
                                    .id(l.id)
                            }
                        }
                        .padding(.horizontal, 10).padding(.vertical, 8)
                    }
                    .frame(height: 360)
                    .background(Color(red: 0x11 / 255.0, green: 0x13 / 255.0, blue: 0x18 / 255.0))
                    .cornerRadius(8)
                    .onChange(of: page.lines.count) { _ in
                        if let lastId = page.lines.last?.id {
                            withAnimation { proxy.scrollTo(lastId, anchor: .bottom) }   // 自动滚到最底部
                        }
                    }
                }
                if !page.resultText.isEmpty {
                    Text(page.resultText).font(.system(size: 12)).textSelection(.enabled)
                }
                HStack(spacing: 8) {
                    if page.running {
                        Button { page.stopTask() } label: { Text("停止任务").frame(maxWidth: .infinity) }
                            .buttonStyle(.bordered)
                    } else {
                        Button { page.deleteTask() } label: { Text("删除记录").frame(maxWidth: .infinity) }
                            .buttonStyle(.bordered)
                    }
                    Button { page.refresh() } label: { Text("刷新").frame(maxWidth: .infinity) }
                        .buttonStyle(.bordered)
                }
            }
            .padding(14)
        }
        .modifier(PageChrome(page: page))
    }
}
