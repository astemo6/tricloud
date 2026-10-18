import SwiftUI

// TriCloud iOS 原生 App（SwiftUI），功能与 Android 原生版一致：直连自托管面板 /api（Bearer token）。
// 面板地址存 UserDefaults，token 存 Keychain；代码中不含任何域名或凭证。

@main
struct TriCloudApp: App {
    var body: some Scene {
        WindowGroup { RootView() }
    }
}

final class AppState: ObservableObject {
    static let shared = AppState()
    @Published var loggedIn: Bool
    @Published var theme: String
    /// 云账号列表（侧栏 / 账号分组 / 总览共用）。
    @Published var accounts: [JObj] = []
    /// 运行中的任务数（任务标签角标）。
    @Published var runningTasks = 0
    @Published var tab = 0
    private(set) var pages = RootPages()

    init() {
        loggedIn = !Api.token.isEmpty && !Api.server.isEmpty
        theme = Prefs.get("theme", "system")
    }

    func loggedOut() {
        UIHub.shared.reset()
        loggedIn = false
    }

    func loggedInNow() {
        pages = RootPages()
        accounts = []
        tab = 0
        loggedIn = true
    }

    func reloadAccounts() {
        Api.call("GET", "/accounts", nil) { res in
            if case .success(let r) = res { self.accounts = (0..<jarr(r).count).map { jarr(r).obj($0) } }
        }
    }

    func setAccounts(_ a: JArr) {
        accounts = (0..<a.count).map { a.obj($0) }
        Regions.hints = [:]   // build 25：/accounts 带的 machine_regions 是后端最新记录
    }

    func pollTasks() {
        guard loggedIn else { return }
        Api.call("GET", "/tasks?limit=20", nil) { res in
            if case .success(let r) = res {
                let a = jarr(r)
                self.runningTasks = (0..<a.count).filter { a.obj($0).optString("status") == "running" }.count
            }
        }
    }

    func setTheme(_ t: String) {
        Prefs.set("theme", t)
        theme = t
    }

    var scheme: ColorScheme? { theme == "dark" ? .dark : theme == "light" ? .light : nil }
}

struct RootView: View {
    @ObservedObject var app = AppState.shared

    var body: some View {
        Group {
            if app.loggedIn {
                MainShell()
            } else {
                LoginView()
            }
        }
        .modifier(HubHost())
        .preferredColorScheme(app.scheme)
    }
}
