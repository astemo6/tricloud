import SwiftUI

// 导航外壳：与 Web 侧栏（renderSide）同样的分类。
// iPhone：TabView（总览 / 账号 / 任务 / 更多）；iPad（宽屏）：侧栏 = 总览 + 按云分组的账号 + 管理。

enum Brand {
    static func color(_ prov: String) -> Color {
        switch prov {
        case "oci": return .red
        case "aws": return .orange
        default: return .blue
        }
    }
    static func icon(_ prov: String) -> String { "cloud.fill" }
    /// 各家官方 Logo（Assets 里的 LogoOCI / LogoAWS / LogoAzure，AWS 有深色模式版本）。
    static func logo(_ prov: String) -> String {
        switch prov {
        case "oci": return "LogoOCI"
        case "aws": return "LogoAWS"
        default: return "LogoAzure"
        }
    }
    /// 分组标题以云厂商名开头时（如「Oracle Cloud · 1」）返回对应厂商。
    static func prov(forTitle t: String) -> String? {
        MainPage.PROVS.first { t.hasPrefix(MainPage.pname($0)) }
    }
}

/// 列表分组标题：保留原大小写（不转全大写）；云厂商分组前加 Logo。
struct SectionHeader: View {
    let title: String
    var body: some View {
        HStack(spacing: 6) {
            if let p = Brand.prov(forTitle: title) {
                Image(Brand.logo(p)).resizable().scaledToFit()
                    .frame(height: p == "aws" ? 18 : 13)
                    .offset(y: p == "aws" ? 4 : 0)  // 「aws」字母只占图上半部，下移与文字齐平
                    .accessibilityHidden(true)
            }
            Text(L(title))
        }
        .textCase(nil)
    }
}

struct MenuEntry {
    let key: String
    let icon: String
    let title: String
    let tint: Color
    let make: () -> Page
}

enum Menus {
    /// 管理分类（顺序与 Web 侧栏一致）。
    static let manage: [MenuEntry] = [
        MenuEntry(key: "accounts", icon: "key.fill", title: "云账号", tint: .blue, make: { MainPage() }),
        MenuEntry(key: "health", icon: "heart.text.square.fill", title: "账号健康度", tint: .pink, make: { HealthPage() }),
        MenuEntry(key: "freecheck", icon: "gift.fill", title: "免费额度体检", tint: .green, make: { FreeCheckPage() }),
        MenuEntry(key: "traffic", icon: "chart.bar.fill", title: "流量守护", tint: .orange, make: { TrafficPage() }),
        MenuEntry(key: "tasks", icon: "clock.arrow.circlepath", title: "任务", tint: .indigo, make: { TasksPage() }),
        MenuEntry(key: "monitors", icon: "waveform.path.ecg", title: "监控", tint: .red, make: { MonitorsPage() }),
        MenuEntry(key: "secrets", icon: "lock.fill", title: "开机密码", tint: .gray, make: { SecretsPage() }),
        MenuEntry(key: "scripts", icon: "doc.text.fill", title: "脚本模板", tint: .brown, make: { ScriptsPage() }),
        MenuEntry(key: "dns", icon: "globe", title: "DNS 联动", tint: .teal, make: { DnsPage() }),
        MenuEntry(key: "security", icon: "shield.lefthalf.filled", title: "安全与备份", tint: .purple, make: { SecurityPage() }),
        MenuEntry(key: "onedrive", icon: "icloud.and.arrow.up.fill", title: "OneDrive 备份", tint: .blue, make: { OneDrivePage() }),
        MenuEntry(key: "deleted", icon: "trash.fill", title: "已删账号", tint: .gray, make: { DeletedPage() }),
        MenuEntry(key: "settings", icon: "gearshape.fill", title: "设置", tint: .gray, make: { SettingsPage() }),
    ]
}

/// 根页面：登录后创建，退出登录时丢弃。
final class RootPages {
    let home = HomePage()
    let accounts = AccountsPage()
    let tasks = TasksPage()
    let more = MorePage()
    private var cache: [String: Page] = [:]

    func cached(_ key: String, _ make: () -> Page) -> Page {
        if key == "tasks" { return tasks }
        if let p = cache[key] { return p }
        let p = make()
        cache[key] = p
        return p
    }

    func account(_ acc: JObj) -> Page {
        let key = "acc\(acc.optInt("id"))"
        if let p = cache[key] { return p }
        let p = AccountPage(acc)
        cache[key] = p
        return p
    }
}

func confirmLogout(_ page: Page?) {
    UIHub.shared.confirm("退出登录", "退出后需要重新输入面板密码。") {
        Api.call("POST", "/logout", nil) { _ in
            Api.logout()
            AppState.shared.loggedOut()
        }
    }
}

struct MainShell: View {
    @Environment(\.horizontalSizeClass) private var hsc
    @ObservedObject var app = AppState.shared
    private let timer = Timer.publish(every: 20, on: .main, in: .common).autoconnect()

    var body: some View {
        Group {
            if hsc == .regular {
                SidebarRoot()
            } else {
                TabsRoot()
            }
        }
        .onAppear {
            app.reloadAccounts()
            app.pollTasks()
        }
        .onReceive(timer) { _ in app.pollTasks() }
    }
}

struct TabsRoot: View {
    @ObservedObject var app = AppState.shared

    var body: some View {
        TabView(selection: $app.tab) {
            NavigationView { app.pages.home.makeView() }
                .navigationViewStyle(.stack)
                .tabItem { Label(L("总览"), systemImage: "square.grid.2x2") }
                .tag(0)
            NavigationView { app.pages.accounts.makeView() }
                .navigationViewStyle(.stack)
                .tabItem { Label(L("账号"), systemImage: "cloud") }
                .tag(1)
            NavigationView { app.pages.tasks.makeView() }
                .navigationViewStyle(.stack)
                .tabItem { Label(L("任务"), systemImage: "clock.arrow.circlepath") }
                .badge(app.runningTasks)
                .tag(2)
            NavigationView { app.pages.more.makeView() }
                .navigationViewStyle(.stack)
                .tabItem { Label(L("更多"), systemImage: "ellipsis.circle") }
                .tag(3)
        }
    }
}

struct SidebarRoot: View {
    @ObservedObject var app = AppState.shared
    @State private var sel: String? = "home"

    var body: some View {
        NavigationView {
            List {
                NavigationLink(destination: app.pages.home.makeView(), tag: "home", selection: $sel) {
                    Label(L("总览"), systemImage: "square.grid.2x2")
                }
                ForEach(MainPage.PROVS, id: \.self) { p in
                    let list = app.accounts.filter { $0.optString("provider") == p }
                    if !list.isEmpty {
                        Section(header: SectionHeader(title: MainPage.pname(p))) {
                            ForEach(list.indices, id: \.self) { i in
                                let acc = list[i]
                                NavigationLink(destination: app.pages.account(acc).makeView(), tag: "acc\(acc.optInt("id"))", selection: $sel) {
                                    Label {
                                        Text(acc.optString("name") + (acc.optInt("disabled") == 1 ? "（已停用）" : ""))
                                    } icon: {
                                        Image(systemName: Brand.icon(p)).foregroundColor(Brand.color(p))
                                    }
                                }
                            }
                        }
                    }
                }
                Section(header: SectionHeader(title: "管理")) {
                    ForEach(Menus.manage.indices, id: \.self) { i in
                        let m = Menus.manage[i]
                        NavigationLink(destination: app.pages.cached(m.key, m.make).makeView(), tag: m.key, selection: $sel) {
                            Label {
                                Text(m.title)
                            } icon: {
                                Image(systemName: m.icon).foregroundColor(m.tint)
                            }
                        }
                        .badge(m.key == "tasks" ? app.runningTasks : 0)
                    }
                    Button {
                        confirmLogout(nil)
                    } label: {
                        Label(L("退出登录"), systemImage: "rectangle.portrait.and.arrow.right").foregroundColor(.red)
                    }
                }
            }
            .listStyle(.sidebar)
            .navigationTitle("TriCloud")
            .refreshable { app.reloadAccounts() }

            app.pages.home.makeView()
        }
        .navigationViewStyle(.columns)
    }
}

/// 「更多」：管理分类入口（iPhone）。
final class MorePage: Page {
    override init() {
        super.init()
        title = "更多"
    }

    override func refresh() {
        clear()
        section("管理")
        for m in Menus.manage where m.key != "tasks" {
            nav(m.icon, m.title, tint: m.tint) { self.push(m.make()) }
        }
        section("面板")
        nav("safari.fill", "在浏览器打开网页版", Api.server, tint: .blue) {
            if let u = URL(string: Api.server), !Api.server.isEmpty { UIApplication.shared.open(u) }
        }
        nav("rectangle.portrait.and.arrow.right", "退出登录", tint: .red) { confirmLogout(self) }
    }
}
