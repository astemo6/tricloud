import SwiftUI

// 对应 Android BaseActivity：页面由「卡片 / 按钮行 / 大按钮」组成，refresh() 里命令式构建，
// 网络请求统一走 request()：忙碌指示、401 回登录、409 免费额度护栏二次确认（confirm_overage 重试）、错误 Toast。

final class ButtonRow {
    var buttons: [(String, () -> Void)] = []
    /// 收纳到「更多」菜单里的次要操作（原生 Menu）。
    var menus: [(String, [(String, () -> Void)])] = []
    weak var page: Page?
    init(_ page: Page?) { self.page = page }
    func button(_ label: String, _ action: @escaping () -> Void) {
        buttons.append((label, action))
        page?.changed()
    }
    func menu(_ label: String, _ items: [(String, () -> Void)]) {
        if items.isEmpty { return }
        menus.append((label, items))
        page?.changed()
    }
}

/// 可在加载完成后更新的文字（总览里的实例数等）。
final class LiveText: ObservableObject {
    @Published var text: String
    init(_ t: String) { text = t }
}

/// 账号页标签：横向滚动的胶囊。
final class ChipBar {
    let items: [(String, String)]
    let selected: String
    let pick: (String) -> Void
    init(_ items: [(String, String)], _ selected: String, _ pick: @escaping (String) -> Void) {
        self.items = items; self.selected = selected; self.pick = pick
    }
}

/// 列表导航行：SF Symbol 图标 + 标题 + 副标题 + 右侧箭头。
final class NavItem {
    let icon: String
    let title: String
    let detail: LiveText
    let tint: Color
    let badge: String?
    let action: () -> Void
    init(_ icon: String, _ title: String, _ detail: String, _ tint: Color, _ badge: String?, _ action: @escaping () -> Void) {
        self.icon = icon; self.title = title; self.detail = LiveText(detail); self.tint = tint; self.badge = badge; self.action = action
    }
}

final class EditorBox: ObservableObject {
    @Published var text: String
    init(_ t: String) { text = t }
}

enum CardItem {
    case text(String, CGFloat, Bool)
    case muted(String)
    case row(ButtonRow)
    case editor(EditorBox)
    case live(LiveText)
    case meter(Double, String)
}

struct CardEntry: Identifiable {
    let id = UUID()
    let item: CardItem
}

final class Card: ObservableObject {
    var title: String?
    @Published var items: [CardEntry] = []
    weak var page: Page?
    init(_ title: String?, _ page: Page?) { self.title = title; self.page = page }

    private func add(_ i: CardItem) { items.append(CardEntry(item: i)); page?.changed() }
    func text(_ s: String, _ size: CGFloat = 14, _ bold: Bool = false) { add(.text(s, size, bold)) }
    func muted(_ s: String) { add(.muted(s)) }
    func row() -> ButtonRow { let r = ButtonRow(page); add(.row(r)); return r }
    func editor(_ t: String) -> EditorBox { let e = EditorBox(t); add(.editor(e)); return e }
    func live(_ t: String) -> LiveText { let l = LiveText(t); add(.live(l)); return l }
    /// 用量条：ratio = 已用 / 上限（> 1 显示红色）。
    func meter(_ ratio: Double, _ label: String) { add(.meter(ratio.isNaN ? 0 : ratio, label)) }
}

enum BlockKind {
    case card(Card)
    case row(ButtonRow)
    case big(String, () -> Void)
    case chips(ChipBar)
    case nav(NavItem)
    case section(String)
    case view(AnyView)
}

/// 连续的导航行合成一个分组；卡片各自成组（iOS 设置式的分组列表）。
struct BlockGroup: Identifiable {
    let id: UUID
    let header: String?
    let blocks: [Block]
}

struct Block: Identifiable {
    let id = UUID()
    let kind: BlockKind
}

class Page: ObservableObject {
    @Published var title: String = ""
    @Published var blocks: [Block] = []
    @Published var busyCount = 0
    @Published var pushActive = false
    var pushed: Page?
    weak var parent: Page?
    var started = false

    /// 右上角菜单（MainActivity 的 OptionsMenu）。
    var menu: [(String, () -> Void)] { [] }

    func refresh() {}
    func appeared() { if !started { started = true; refresh() } }
    func disappeared() {}
    func makeView() -> AnyView { AnyView(PageView(page: self)) }
    func changed() { objectWillChange.send() }

    // MARK: 导航
    func push(_ p: Page) {
        p.parent = self
        pushed = p
        pushActive = true
    }
    func finish() { parent?.pushActive = false }

    func setBusy(_ b: Bool) { busyCount = max(0, busyCount + (b ? 1 : -1)) }

    // MARK: 构建
    func clear() { blocks = [] }
    @discardableResult func card(_ title: String?) -> Card {
        let c = Card(title, self)
        blocks.append(Block(kind: .card(c)))
        return c
    }
    func row() -> ButtonRow {
        let r = ButtonRow(self)
        blocks.append(Block(kind: .row(r)))
        return r
    }
    func bigButton(_ label: String, _ action: @escaping () -> Void) {
        blocks.append(Block(kind: .big(label, action)))
    }
    func chips(_ items: [(String, String)], _ selected: String, _ pick: @escaping (String) -> Void) {
        blocks.append(Block(kind: .chips(ChipBar(items, selected, pick))))
    }
    @discardableResult func nav(_ icon: String, _ title: String, _ detail: String = "", tint: Color = .accentColor, badge: String? = nil,
                                _ action: @escaping () -> Void) -> NavItem {
        let n = NavItem(icon, title, detail, tint, badge, action)
        blocks.append(Block(kind: .nav(n)))
        return n
    }
    /// 自定义 SwiftUI 内容（需要局部交互、不想整页重建的部分，如安全组筛选）。
    func view(_ v: AnyView) { blocks.append(Block(kind: .view(v))) }
    /// 分组标题：作用于紧随其后的一组。
    func section(_ title: String) { blocks.append(Block(kind: .section(title))) }

    static func groups(_ blocks: [Block]) -> [BlockGroup] {
        var out: [BlockGroup] = []
        var header: String? = nil
        var navs: [Block] = []
        for b in blocks {
            switch b.kind {
            case .section(let t):
                if !navs.isEmpty { out.append(BlockGroup(id: navs[0].id, header: header, blocks: navs)); navs = []; header = nil }
                header = t
            case .nav:
                navs.append(b)
            default:
                if !navs.isEmpty { out.append(BlockGroup(id: navs[0].id, header: header, blocks: navs)); navs = []; header = nil }
                out.append(BlockGroup(id: b.id, header: header, blocks: [b]))
                header = nil
            }
        }
        if !navs.isEmpty { out.append(BlockGroup(id: navs[0].id, header: header, blocks: navs)) }
        return out
    }

    // MARK: 对话框
    func toast(_ s: String) { UIHub.shared.toast(s) }
    func confirm(_ title: String, _ msg: String, _ ok: @escaping () -> Void) { UIHub.shared.confirm(title, msg, ok) }
    func form(_ title: String, _ note: String?, _ fields: [Field], _ okText: String, _ cb: @escaping (JObj) -> Void) {
        UIHub.shared.form(title, note, fields, okText, cb)
    }
    func choose(_ title: String, _ labels: [String], _ cb: @escaping (Int) -> Void) { UIHub.shared.choose(title, labels, cb) }
    func message(_ title: String, _ msg: String, primary: (String, () -> Void)? = nil, cancel: String = "好的", onCancel: (() -> Void)? = nil) {
        UIHub.shared.message(title, msg, primary: primary, cancel: cancel, onCancel: onCancel)
    }

    // MARK: 任务
    /// v1.4：打开任务实时日志页（轮询）。
    func openTask(_ tid: Int) {
        if tid <= 0 { return }
        push(TaskLogPage(tid))
    }
    /// v1.4：接口返回 task_id 时自动打开任务日志，否则 Toast。
    func taskOrToast(_ r: Any, _ fallback: String) {
        let o = jobj(r)
        if o.optInt("task_id") > 0 { openTask(o.optInt("task_id")) } else { toast(fallback) }
    }

    func toLogin() {
        Api.logout()
        AppState.shared.loggedOut()
    }

    // MARK: 网络
    func request(_ method: String, _ path: String, _ body: JObj?, _ cb: ((Any) -> Void)?) {
        setBusy(true)
        Api.call(method, path, body) { res in
            self.setBusy(false)
            switch res {
            case .success(let r):
                cb?(r)
            case .failure(let err):
                guard let e = err as? ApiError else { self.toast("❌ " + err.localizedDescription); return }
                if e.code == 401 {
                    self.toLogin()
                } else if e.code == 409, let g = e.guardList, let b = body {
                    var sb = ""
                    for i in 0..<g.count { sb += "• " + g.string(i) + "\n\n" }
                    sb += "免费额度以云厂商公示和账号类型为准。可在设置里关闭护栏。"
                    self.message("⚠️ 可能超出免费额度", sb, primary: ("仍然继续", {
                        var nb = b
                        nb["confirm_overage"] = true
                        self.request(method, path, nb, cb)
                    }), cancel: "取消")
                } else {
                    self.toast("❌ " + e.msg)
                }
            }
        }
    }
    func get(_ p: String, _ cb: ((Any) -> Void)?) { request("GET", p, nil, cb) }
    func post(_ p: String, _ b: JObj?, _ cb: ((Any) -> Void)?) { request("POST", p, b, cb) }
    func del(_ p: String, _ cb: ((Any) -> Void)?) { request("DELETE", p, nil, cb) }

    func later(_ sec: Double, _ f: @escaping () -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + sec, execute: f)
    }
}

// MARK: - 视图

struct ButtonGrid: View {
    let row: ButtonRow
    private let cols = Array(repeating: GridItem(.flexible(), spacing: 6), count: 3)

    var body: some View {
        LazyVGrid(columns: cols, spacing: 6) {
            ForEach(row.buttons.indices, id: \.self) { i in
                let b = row.buttons[i]
                let danger = isDanger(b.0)
                Button(role: danger ? .destructive : nil) {
                    Haptics.tap()
                    b.1()
                } label: {
                    Text(b.0)
                        .font(.footnote.weight(.medium))
                        .lineLimit(2)
                        .minimumScaleFactor(0.8)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity, minHeight: 30)
                }
                .buttonStyle(.bordered)
                .buttonBorderShape(.roundedRectangle(radius: 10))
                .tint(danger ? .red : .accentColor)
            }
            ForEach(row.menus.indices, id: \.self) { i in
                let m = row.menus[i]
                Menu {
                    ForEach(m.1.indices, id: \.self) { j in
                        let it = m.1[j]
                        Button(role: isDanger(it.0) ? .destructive : nil) { it.1() } label: { Text(it.0) }
                    }
                } label: {
                    Label(m.0, systemImage: "ellipsis.circle")
                        .font(.footnote.weight(.medium))
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                        .frame(maxWidth: .infinity, minHeight: 30)
                }
                .buttonStyle(.bordered)
                .buttonBorderShape(.roundedRectangle(radius: 10))
                .tint(.accentColor)
            }
        }
        .padding(.vertical, 2)
    }
}

struct EditorView: View {
    @ObservedObject var box: EditorBox
    var body: some View {
        TextEditor(text: $box.text)
            .font(.system(size: 12, design: .monospaced))
            .frame(minHeight: 180)
            .autocapitalization(.none)
            .disableAutocorrection(true)
            .padding(6)
            .background(Color(UIColor.tertiarySystemFill))
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

struct CardView: View {
    @ObservedObject var card: Card
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let t = card.title {
                Text(t).font(.headline).textSelection(.enabled)
            }
            ForEach(card.items) { e in
                switch e.item {
                case .text(let s, let size, let bold):
                    if !s.isEmpty {
                        Text(s).font(CardView.font(size, bold)).textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                case .muted(let s):
                    if !s.isEmpty {
                        Text(s).font(.footnote).foregroundColor(.secondary).textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                case .row(let r):
                    if !r.buttons.isEmpty || !r.menus.isEmpty { ButtonGrid(row: r) }
                case .editor(let box):
                    EditorView(box: box)
                case .live(let l):
                    LiveTextView(live: l, font: .subheadline)
                case .meter(let r, let label):
                    MeterView(ratio: r, label: label)
                }
            }
        }
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// 映射到 iOS 动态字体（跟随系统字号设置）。
    static func font(_ size: CGFloat, _ bold: Bool) -> Font {
        let f: Font = size >= 18 ? .title3 : size >= 16 ? .headline : size >= 14 ? .subheadline : size >= 13 ? .footnote : .caption
        return bold ? f.weight(.semibold) : f
    }
}

func isDanger(_ label: String) -> Bool {
    label.contains("删除") || label.contains("终止") || label.contains("销毁") || label.contains("清空") || label.contains("仍要生成")
}

/// 触感反馈（iOS 15 兼容，用 UIKit 生成器）。
enum Haptics {
    static func tap() { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
    static func success() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func error() { UINotificationFeedbackGenerator().notificationOccurred(.error) }
    static func warning() { UINotificationFeedbackGenerator().notificationOccurred(.warning) }
    static func select() { UISelectionFeedbackGenerator().selectionChanged() }
}

struct PageView: View {
    @ObservedObject var page: Page

    var body: some View {
        List {
            ForEach(Page.groups(page.blocks)) { g in
                if let h = g.header {
                    Section(header: SectionHeader(title: h)) { rows(g) }
                } else {
                    Section { rows(g) }
                }
            }
        }
        .listStyle(.insetGrouped)
        .animation(.spring(response: 0.38, dampingFraction: 0.86), value: page.blocks.count)
        .refreshable { page.refresh() }
        .modifier(PageChrome(page: page))
    }

    @ViewBuilder
    private func rows(_ g: BlockGroup) -> some View {
        ForEach(g.blocks) { b in
            switch b.kind {
            case .card(let c):
                CardView(card: c)
            case .row(let r):
                ButtonGrid(row: r)
            case .big(let label, let action):
                Button {
                    Haptics.tap()
                    action()
                } label: {
                    Text(label).font(.body.weight(.semibold)).frame(maxWidth: .infinity, minHeight: 36)
                }
                .buttonStyle(.borderedProminent)
                .buttonBorderShape(.roundedRectangle(radius: 12))
                .controlSize(.large)
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
            case .chips(let bar):
                ChipBarView(bar: bar)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
            case .nav(let n):
                NavRowView(item: n)
            case .view(let v):
                v
            case .section:
                EmptyView()
            }
        }
    }
}

struct LiveTextView: View {
    @ObservedObject var live: LiveText
    var font: Font = .subheadline
    var body: some View {
        if !live.text.isEmpty {
            Text(live.text).font(font).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
        }
    }
}

struct MeterView: View {
    let ratio: Double
    let label: String
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if !label.isEmpty {
                Text(label).font(.footnote).foregroundColor(ratio > 1 ? .red : .secondary)
            }
            ProgressView(value: min(max(ratio, 0), 1))
                .tint(ratio > 1 ? .red : ratio >= 0.8 ? .orange : .accentColor)
        }
        .padding(.vertical, 2)
    }
}

struct ChipBarView: View {
    let bar: ChipBar
    var body: some View {
        ScrollViewReader { proxy in
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(bar.items.indices, id: \.self) { i in
                        let it = bar.items[i]
                        let on = it.0 == bar.selected
                        Button {
                            Haptics.select()
                            bar.pick(it.0)
                        } label: {
                            Text(it.1)
                                .font(.subheadline.weight(on ? .semibold : .regular))
                                .lineLimit(1)
                                .padding(.horizontal, 14).padding(.vertical, 7)
                                .foregroundColor(on ? .white : .primary)
                                .background(Capsule().fill(on ? Color.accentColor : Color(UIColor.tertiarySystemFill)))
                        }
                        .buttonStyle(.plain)
                        .id(it.0)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 4)
            }
            .onAppear { proxy.scrollTo(bar.selected, anchor: .center) }
        }
    }
}

struct NavRowView: View {
    let item: NavItem
    var body: some View {
        Button {
            Haptics.tap()
            item.action()
        } label: {
            HStack(spacing: 12) {
                Image(systemName: item.icon)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(.white)
                    .frame(width: 30, height: 30)
                    .background(RoundedRectangle(cornerRadius: 7, style: .continuous).fill(item.tint))
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.title).font(.body).foregroundColor(.primary).lineLimit(1)
                    LiveTextView(live: item.detail, font: .caption)
                        .foregroundColor(.secondary)
                }
                Spacer(minLength: 4)
                if let b = item.badge, !b.isEmpty {
                    Text(b).font(.subheadline).foregroundColor(.secondary)
                }
                Image(systemName: "chevron.right")
                    .font(.footnote.weight(.semibold))
                    .foregroundColor(Color(UIColor.tertiaryLabel))
            }
            .padding(.vertical, 2)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// 标题、忙碌指示、菜单、隐藏的导航链接（打开账号 / 任务日志等）。
struct PageChrome: ViewModifier {
    @ObservedObject var page: Page

    func body(content: Content) -> some View {
        content
            .navigationTitle(page.title)
            // 首页用大标题，二级页内联标题（iOS 惯例）
            .navigationBarTitleDisplayMode(page.parent == nil ? .large : .inline)
            .overlay(alignment: .top) {
                if page.busyCount > 0 {
                    ProgressView()
                        .padding(10)
                        .background(.regularMaterial, in: Capsule())
                        .shadow(color: .black.opacity(0.08), radius: 8, y: 2)
                        .padding(.top, 6)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .animation(.spring(response: 0.35, dampingFraction: 0.8), value: page.busyCount > 0)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    let items = page.menu
                    if !items.isEmpty {
                        Menu {
                            ForEach(items.indices, id: \.self) { i in
                                Button(items[i].0) { items[i].1() }
                            }
                        } label: {
                            Image(systemName: "ellipsis.circle")
                        }
                    }
                }
            }
            .background(
                NavigationLink(destination: PushedView(page: page), isActive: $page.pushActive) { EmptyView() }
                    .hidden()
            )
            .onAppear { page.appeared() }
            .onDisappear { page.disappeared() }
    }
}

struct PushedView: View {
    @ObservedObject var page: Page
    var body: some View {
        if let p = page.pushed { p.makeView() } else { EmptyView() }
    }
}
