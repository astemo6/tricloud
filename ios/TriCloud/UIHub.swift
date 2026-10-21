import SwiftUI
import UIKit

// 全局弹窗中心：确认框、消息框、表单（对应 BaseActivity.form）、选择列表（choose）、Toast。
// 所有弹窗串行排队，前一个完全关闭后再弹下一个，避免 SwiftUI 连续弹窗丢失。

struct Field {
    let key: String
    let label: String
    let def: String
    let type: String          // text / number / multi / password / check / select
    let options: [String]
    let labels: [String]

    init(_ key: String, _ label: String, _ def: String?, _ type: String, _ options: [String] = [], _ labels: [String]? = nil) {
        self.key = key; self.label = label; self.def = def ?? ""; self.type = type
        self.options = options; self.labels = labels ?? options
    }
    static func text(_ k: String, _ l: String, _ d: String) -> Field { Field(k, l, d, "text") }
    static func num(_ k: String, _ l: String, _ d: String) -> Field { Field(k, l, d, "number") }
    static func multi(_ k: String, _ l: String, _ d: String) -> Field { Field(k, l, d, "multi") }
    static func pass(_ k: String, _ l: String) -> Field { Field(k, l, "", "password") }
    static func check(_ k: String, _ l: String, _ d: Bool) -> Field { Field(k, l, d ? "1" : "", "check") }
    static func select(_ k: String, _ l: String, _ d: String, _ opts: [String], _ labels: [String]?) -> Field { Field(k, l, d, "select", opts, labels) }
}

struct FormSpec {
    let title: String
    let note: String?
    let fields: [Field]
    let okText: String
    let cb: (JObj) -> Void
}

struct ChooseSpec {
    let title: String
    let labels: [String]
    let cb: (Int) -> Void
}

struct AlertSpec: Identifiable {
    let id = UUID()
    let title: String
    let message: String
    var primary: (String, () -> Void)? = nil        // 确认类按钮（可选）
    var cancel: (String, (() -> Void)?) = ("取消", nil)
}

enum SheetSpec: Identifiable {
    case form(FormSpec, FormModel, UUID)
    case choose(ChooseSpec, UUID)
    case custom(AnyView, UUID)
    var id: UUID {
        switch self { case .form(_, _, let u): return u; case .choose(_, let u): return u; case .custom(_, let u): return u }
    }
}

final class UIHub: ObservableObject {
    static let shared = UIHub()

    @Published var alert: AlertSpec?
    @Published var sheet: SheetSpec?
    @Published var toastText: String?

    private enum Modal { case alert(AlertSpec), sheet(SheetSpec) }
    private var queue: [Modal] = []
    private var lastClose = Date.distantPast
    private var toastGen = 0

    // MARK: 对外接口

    func toast(_ s: String) {
        toastGen += 1
        let g = toastGen
        if s.hasPrefix("❌") { Haptics.error() } else if s.hasPrefix("⚠️") { Haptics.warning() } else if s.hasPrefix("✅") { Haptics.success() }
        withAnimation(.spring(response: 0.4, dampingFraction: 0.78)) { toastText = s }
        DispatchQueue.main.asyncAfter(deadline: .now() + 4.5) { [weak self] in
            guard let self = self, self.toastGen == g else { return }
            withAnimation(.easeInOut(duration: 0.25)) { self.toastText = nil }
        }
    }

    func confirm(_ title: String, _ msg: String, _ ok: @escaping () -> Void) {
        present(.alert(AlertSpec(title: title, message: msg, primary: ("确认", ok), cancel: ("取消", nil))))
    }

    /// 消息框：primary 可选；cancel 为关闭按钮。
    func message(_ title: String, _ msg: String, primary: (String, () -> Void)? = nil, cancel: String = "好的", onCancel: (() -> Void)? = nil) {
        present(.alert(AlertSpec(title: title, message: msg, primary: primary, cancel: (cancel, onCancel))))
    }

    func form(_ title: String, _ note: String?, _ fields: [Field], _ okText: String, _ cb: @escaping (JObj) -> Void) {
        present(.sheet(.form(FormSpec(title: title, note: note, fields: fields, okText: okText, cb: cb), FormModel(fields), UUID())))
    }

    func choose(_ title: String, _ labels: [String], _ cb: @escaping (Int) -> Void) {
        present(.sheet(.choose(ChooseSpec(title: title, labels: labels, cb: cb), UUID())))
    }

    /// 自定义表单页（如「添加云账号」的粘贴自动识别）。
    func custom(_ v: AnyView) {
        present(.sheet(.custom(v, UUID())))
    }

    func reset() {
        queue.removeAll()
        alert = nil
        sheet = nil
    }

    // MARK: 排队

    private func present(_ m: Modal) {
        queue.append(m)
        drain()
    }

    private func drain() {
        guard alert == nil, sheet == nil, !queue.isEmpty else { return }
        let wait = 0.6 - Date().timeIntervalSince(lastClose)
        if wait > 0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + wait + 0.02) { [weak self] in self?.drain() }
            return
        }
        switch queue.removeFirst() {
        case .alert(let a): alert = a
        case .sheet(let s): sheet = s
        }
    }

    func closeAlert(_ action: (() -> Void)?) {
        guard alert != nil else { return }
        alert = nil
        lastClose = Date()
        DispatchQueue.main.async { [weak self] in
            action?()
            self?.drain()
        }
    }

    func closeSheet(_ action: (() -> Void)?) {
        guard sheet != nil else { return }
        sheet = nil
        lastClose = Date()
        DispatchQueue.main.async { [weak self] in
            action?()
            self?.drain()
        }
    }

    /// 弹窗被系统关闭（下滑表单等）。
    func didDismiss() {
        lastClose = Date()
        DispatchQueue.main.async { [weak self] in self?.drain() }
    }

    func alertBinding() -> Binding<Bool> {
        Binding(get: { self.alert != nil }, set: { v in
            if !v && self.alert != nil { self.alert = nil; self.didDismiss() }
        })
    }
}

// MARK: - 视图

struct HubHost: ViewModifier {
    @ObservedObject var hub = UIHub.shared

    func body(content: Content) -> some View {
        content
            .overlay(alignment: .bottom) {
                if let t = hub.toastText {
                    // iOS 风格的浮动横幅：毛玻璃胶囊，自底部弹入
                    Text(L(t))
                        .font(.subheadline.weight(.medium))
                        .foregroundColor(.primary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 18).padding(.vertical, 12)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                        .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
                        .padding(.horizontal, 24).padding(.bottom, 28)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                        .onTapGesture { withAnimation(.easeInOut(duration: 0.2)) { hub.toastText = nil } }
                }
            }
            .sheet(item: $hub.sheet, onDismiss: { hub.didDismiss() }) { s in
                switch s {
                case .form(let f, let m, _): FormSheet(spec: f, model: m)
                case .choose(let c, _): ChooseSheet(spec: c)
                case .custom(let v, _): v
                }
            }
            .alert(L(hub.alert?.title ?? ""), isPresented: hub.alertBinding(), presenting: hub.alert) { a in
                if let p = a.primary {
                    Button(L(p.0), role: isDanger(a.title + p.0) ? .destructive : nil) { hub.closeAlert(p.1) }
                }
                Button(L(a.cancel.0), role: .cancel) { hub.closeAlert(a.cancel.1) }
            } message: { a in
                Text(L(a.message))
            }
    }
}

final class FormModel: ObservableObject {
    @Published var texts: [String]
    @Published var checks: [Bool]
    @Published var sels: [Int]

    init(_ fields: [Field]) {
        texts = fields.map { $0.type == "check" || $0.type == "select" ? "" : $0.def }
        checks = fields.map { !$0.def.isEmpty }
        sels = fields.map { f in f.options.firstIndex(of: f.def) ?? 0 }
    }
}

struct FormSheet: View {
    let spec: FormSpec
    @ObservedObject var model: FormModel

    var body: some View {
        NavigationView {
            Form {
                if let n = spec.note, !n.isEmpty {
                    Section { Text(L(n)).font(.footnote).foregroundColor(.secondary) }
                }
                Section {
                    ForEach(spec.fields.indices, id: \.self) { i in fieldView(i) }
                }
            }
            .navigationTitle(L(spec.title))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L("取消")) { UIHub.shared.closeSheet(nil) }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(L(spec.okText)) { submit() }
                }
            }
        }
        .navigationViewStyle(.stack)
    }

    @ViewBuilder
    private func fieldView(_ i: Int) -> some View {
        let f = spec.fields[i]
        switch f.type {
        case "check":
            Toggle(L(f.label), isOn: $model.checks[i])
        case "select":
            if f.options.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text(L(f.label)).font(.caption).foregroundColor(.secondary)
                    Text(L("（无选项）")).foregroundColor(.secondary)
                }
            } else {
                Picker(selection: $model.sels[i]) {
                    ForEach(f.options.indices, id: \.self) { j in
                        Text(L(j < f.labels.count ? f.labels[j] : f.options[j])).tag(j)
                    }
                } label: {
                    Text(L(f.label))
                }
            }
        case "multi":
            VStack(alignment: .leading, spacing: 4) {
                Text(L(f.label)).font(.caption).foregroundColor(.secondary)
                TextEditor(text: $model.texts[i])
                    .font(.system(size: 13, design: .monospaced))
                    .frame(minHeight: 90)
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
            }
        case "password":
            VStack(alignment: .leading, spacing: 4) {
                Text(L(f.label)).font(.caption).foregroundColor(.secondary)
                SecureField("", text: $model.texts[i])
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
            }
        default:
            VStack(alignment: .leading, spacing: 4) {
                Text(L(f.label)).font(.caption).foregroundColor(.secondary)
                TextField("", text: $model.texts[i])
                    .keyboardType(f.type == "number" ? .decimalPad : .default)
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
            }
        }
    }

    private func submit() {
        var o = JObj()
        for (i, f) in spec.fields.enumerated() {
            switch f.type {
            case "select":
                let idx = model.sels[i]
                o[f.key] = idx >= 0 && idx < f.options.count ? f.options[idx] : ""
            case "check":
                o[f.key] = model.checks[i]
            default:
                o[f.key] = model.texts[i].trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }
        let cb = spec.cb
        UIHub.shared.closeSheet { cb(o) }
    }
}

struct ChooseSheet: View {
    let spec: ChooseSpec

    var body: some View {
        NavigationView {
            List {
                ForEach(spec.labels.indices, id: \.self) { i in
                    Button {
                        let cb = spec.cb
                        UIHub.shared.closeSheet { cb(i) }
                    } label: {
                        Text(L(spec.labels[i])).foregroundColor(isDanger(spec.labels[i]) ? .red : .primary)
                    }
                }
            }
            .navigationTitle(L(spec.title))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L("取消")) { UIHub.shared.closeSheet(nil) }
                }
            }
        }
        .navigationViewStyle(.stack)
    }
}

func copyText(_ s: String) {
    UIPasteboard.general.string = s
}
