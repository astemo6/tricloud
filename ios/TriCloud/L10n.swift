import Foundation

/// 渲染层查表本地化（与 Android 的 strings.xml 机制对应）：
/// Page / UIHub / Shell 在渲染字符串时调用 L() 查 Localizable.strings。
/// 语言来源：Prefs 的 app_lang（system / zh / en）；选了具体语言时用对应 .lproj bundle 查表，
/// 跟随系统时走 NSLocalizedString（系统语言）。查不到时原样返回（拼接句/数据文本不受影响）。
enum L10n {
    static var lang: String { Prefs.get("app_lang", "system") }

    static var isEN: Bool {
        switch lang {
        case "en": return true
        case "zh": return false
        default: return (Locale.preferredLanguages.first ?? "zh").hasPrefix("en")
        }
    }

    private static var bundle: Bundle? {
        let l = lang
        if l == "system" { return nil }
        let code = l == "zh" ? "zh-Hans" : "en"
        if let p = Bundle.main.path(forResource: code, ofType: "lproj") { return Bundle(path: p) }
        return nil
    }

    static func t(_ s: String) -> String {
        if let b = bundle {
            let v = b.localizedString(forKey: s, value: nil, table: nil)
            return v == s ? s : v
        }
        return NSLocalizedString(s, comment: "")
    }
}

/// 全局简写：渲染层查表
func L(_ s: String) -> String { L10n.t(s) }

/// 语言切换信号：渲染层视图观察它，切换语言时 bump 一次，已打开的页面立即按新语言重绘（不用重启 App）。
final class LangTick: ObservableObject {
    static let shared = LangTick()
    @Published var v = 0
    func bump() { v += 1 }
}
