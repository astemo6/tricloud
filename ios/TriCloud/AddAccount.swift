import SwiftUI
import UIKit

// v1.6 添加云账号：顶部「粘贴内容自动识别」（防抖 400ms 调 POST /accounts/parse），自动切换云厂商、填好字段和名称；
// 识别到多个账号时可切换，或「全部批量添加」（POST /accounts/batch）。

struct CredField {
    let key: String
    let label: String
    let def: String
    let type: String   // text / multi / password
}

final class AddAccountModel: ObservableObject {
    static let CRED: [String: [CredField]] = [
        "oci": [CredField(key: "user", label: "用户 OCID", def: "", type: "text"),
                CredField(key: "tenancy", label: "租户 OCID", def: "", type: "text"),
                CredField(key: "fingerprint", label: "API Key 指纹", def: "", type: "text"),
                CredField(key: "region", label: "区域", def: "ap-tokyo-1", type: "text"),
                CredField(key: "key_content", label: "私钥 PEM", def: "", type: "multi"),
                CredField(key: "pass_phrase", label: "私钥密码（可选）", def: "", type: "password"),
                CredField(key: "compartment", label: "区间 OCID（可选，默认根区间）", def: "", type: "text"),
                CredField(key: "home_region", label: "主区域（账单用，可选）", def: "", type: "text")],
        "aws": [CredField(key: "access_key", label: "Access Key ID", def: "", type: "text"),
                CredField(key: "secret_key", label: "Secret Access Key", def: "", type: "password"),
                CredField(key: "region", label: "默认区域", def: "us-east-1", type: "text")],
        "azure": [CredField(key: "tenant_id", label: "Tenant ID", def: "", type: "text"),
                  CredField(key: "client_id", label: "Client (App) ID", def: "", type: "text"),
                  CredField(key: "client_secret", label: "Client Secret", def: "", type: "password"),
                  CredField(key: "subscription_id", label: "Subscription ID", def: "", type: "text")],
        "greencloud": [CredField(key: "api_url", label: "面板地址", def: "https://cp.greencloudvps.com", type: "text"),
                       CredField(key: "servers_text", label: "服务器列表（每行一台：名称 key hash）", def: "", type: "multi")],
    ]
    static let PROXY: [CredField] = [
        CredField(key: "proxy", label: "出口代理地址（http:// 或 socks5://，留空 = 直连）", def: "", type: "text"),
        CredField(key: "proxy_user", label: "代理用户名", def: "", type: "text"),
        CredField(key: "proxy_pass", label: "代理密码", def: "", type: "password")]
    static let HINT: [String: String] = [
        "oci": "在 OCI 控制台「我的概要信息 → API 密钥」生成。",
        "aws": "建议使用仅含 EC2 / Lightsail / CloudFront / Service Quotas / CE 权限的 IAM 用户。",
        "azure": "用服务主体（应用注册）创建，并给订阅授予 Contributor 角色。",
        "greencloud": "服务器列表每行一台，格式「名称 key hash」，用空格分隔，例如：\nhk-1 ABCDE-12345 0123456789abcdef\nkey 和 hash 在 SolusVM 面板该服务器的 API 设置里生成。"]

    @Published var prov = "oci" {
        didSet { if oldValue != prov { resetFields() } }
    }
    @Published var name = ""
    var nameAuto = false
    @Published var values: [String: String] = [:]
    @Published var paste = "" {
        didSet { if oldValue != paste { schedule() } }
    }
    @Published var items: [JObj] = []
    @Published var pick = 0 {
        didSet { fill() }
    }
    @Published var hint = ""
    /// 后端已启用的云厂商（GET /api/meta 的 providers）；请求失败时保持全部四家。
    @Published var provs: [String] = MainPage.PROVS
    @Published var busy = false
    @Published var error = ""
    private var work: DispatchWorkItem?

    init() { resetFields() }

    var fields: [CredField] { AddAccountModel.CRED[prov] ?? [] }

    /// 打开添加账号页时调用：按 GET /api/meta 的 providers 过滤分段选择器（如关掉「启用绿云」后不显示 GreenCloud）。
    /// 失败、返回为空或无可识别厂商时，退回显示全部四家。
    func loadMeta() {
        Api.call("GET", "/meta", nil) { res in
            guard case .success(let r) = res else {
                self.provs = MainPage.PROVS
                return
            }
            let a = jobj(r).optJSONArray("providers") ?? []
            let got = Set((0..<a.count).map { a.string($0) })
            let list = MainPage.PROVS.filter { got.contains($0) }
            self.provs = list.isEmpty ? MainPage.PROVS : list
            if !self.provs.contains(self.prov), let first = self.provs.first {
                self.prov = first   // didSet 会重置字段
            }
        }
    }

    func resetFields() {
        var v: [String: String] = [:]
        for f in fields + AddAccountModel.PROXY { v[f.key] = f.def }
        values = v
    }

    func binding(_ k: String) -> Binding<String> {
        Binding(get: { self.values[k] ?? "" }, set: { self.values[k] = $0 })
    }

    var nameBinding: Binding<String> {
        Binding(get: { self.name }, set: { self.name = $0; self.nameAuto = false })
    }

    private func schedule() {
        work?.cancel()
        let w = DispatchWorkItem { [weak self] in self?.parse() }
        work = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4, execute: w)
    }

    func parse() {
        let t = paste
        if t.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            items = []
            hint = ""
            return
        }
        hint = "识别中…"
        Api.call("POST", "/accounts/parse", ["text": t]) { res in
            guard t == self.paste else { return }
            switch res {
            case .success(let r):
                let a = jobj(r).optJSONArray("items") ?? []
                self.items = (0..<a.count).map { a.obj($0) }.filter { self.provs.contains($0.optString("provider")) }
                if self.items.isEmpty {
                    self.hint = "没有识别到云账号凭证"
                    return
                }
                self.pick = 0   // didSet → fill()
            case .failure(let e):
                self.hint = "❌ " + ((e as? ApiError)?.msg ?? e.localizedDescription)
            }
        }
    }

    func fill() {
        guard pick >= 0 && pick < items.count else { return }
        let it = items[pick]
        let p = it.optString("provider")
        if p != prov { prov = p }   // didSet 会按新云厂商重置字段
        let keys = Set((fields + AddAccountModel.PROXY).map { $0.key })
        let cred = it.optJSONObject("cred") ?? [:]
        var v = values
        for (k, val) in cred {
            let s = jsonText(val) ?? ""
            if !s.isEmpty && keys.contains(k) { v[k] = s }
        }
        values = v
        let n = it.optString("name")
        if !n.isEmpty && (name.isEmpty || nameAuto) {
            name = n
            nameAuto = true
        }
        let ma = it.optJSONArray("missing") ?? []
        let miss = (0..<ma.count).map { ma.string($0) }
        let labels = Dictionary(uniqueKeysWithValues: (fields + AddAccountModel.PROXY).map { ($0.key, $0.label) })
        var h = "已识别为 " + MainPage.pname(p) + (miss.isEmpty ? "，字段齐全" : "，还缺：" + miss.map { labels[$0] ?? $0 }.joined(separator: "、"))
        let err = it.optString("error")
        if !err.isEmpty { h += "；" + err }
        if items.count > 1 { h += "。共识别到 \(items.count) 个账号，可在上方切换，或全部批量添加" }
        hint = h
    }

    func itemLabel(_ i: Int) -> String {
        let it = items[i]
        let n = it.optString("name")
        return "\(i + 1). " + MainPage.pname(it.optString("provider")) + " · " + (n.isEmpty ? "未命名" : n)
    }

    func submit(_ done: @escaping () -> Void) {
        var cred = JObj()
        for f in fields + AddAccountModel.PROXY {
            cred[f.key] = (values[f.key] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        }
        busy = true
        error = ""
        let nm = name.trimmingCharacters(in: .whitespacesAndNewlines)
        var body: JObj = ["provider": prov, "name": nm, "cred": cred]
        if prov == "greencloud" {
            // 绿云：顶层字段 api_url + servers_text（多行「名称 key hash」），不走 cred / 代理
            let url = (values["api_url"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            body = ["provider": prov, "name": nm,
                    "api_url": url.isEmpty ? "https://cp.greencloudvps.com" : url,
                    "servers_text": (values["servers_text"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)]
        }
        Api.call("POST", "/accounts", body) { res in
            self.busy = false
            switch res {
            case .success:
                Haptics.success()
                done()
            case .failure(let e):
                Haptics.error()
                let ae = e as? ApiError
                if ae?.code == 401 {
                    UIHub.shared.closeSheet {
                        Api.logout()
                        AppState.shared.loggedOut()
                    }
                    return
                }
                self.error = ae?.msg ?? e.localizedDescription
            }
        }
    }
}

struct AddAccountView: View {
    /// 分段控件放四家时用短名，避免截断。
    static let SHORT: [String: String] = ["oci": "OCI", "aws": "AWS", "azure": "Azure", "greencloud": "GreenCloud"]
    @ObservedObject var m: AddAccountModel
    let onDone: () -> Void
    let onBatch: (String) -> Void

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("粘贴内容自动识别"),
                        footer: Text("控制台复制的内容、环境变量、AWS accessKeys.csv、Azure 应用注册页、OCI config + 私钥都行，混在一起也能识别，自动填好下面的字段。")) {
                    ZStack(alignment: .topLeading) {
                        if m.paste.isEmpty {
                            Text("把复制的一堆内容直接贴进来")
                                .font(.subheadline)
                                .foregroundColor(Color(UIColor.placeholderText))
                                .padding(.top, 8).padding(.leading, 5)
                        }
                        TextEditor(text: $m.paste)
                            .font(.system(size: 13, design: .monospaced))
                            .frame(minHeight: 110)
                            .autocapitalization(.none)
                            .disableAutocorrection(true)
                    }
                    HStack {
                        Button {
                            Haptics.tap()
                            if let s = UIPasteboard.general.string, !s.isEmpty { m.paste = s } else { m.hint = "剪贴板里没有文字" }
                        } label: {
                            Label("从剪贴板粘贴", systemImage: "doc.on.clipboard")
                        }
                        .buttonStyle(.borderless)
                        Spacer()
                        if !m.paste.isEmpty {
                            Button(role: .destructive) {
                                m.paste = ""
                            } label: {
                                Label("清空", systemImage: "xmark.circle")
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                    if m.items.count > 1 {
                        Picker("识别到的账号", selection: $m.pick) {
                            ForEach(m.items.indices, id: \.self) { i in
                                Text(m.itemLabel(i)).tag(i)
                            }
                        }
                    }
                    if !m.hint.isEmpty {
                        Text(m.hint)
                            .font(.footnote)
                            .foregroundColor(m.hint.hasPrefix("❌") ? .red : m.hint.hasPrefix("已识别") ? .accentColor : .secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if m.items.count > 1 {
                        Button {
                            Haptics.tap()
                            onBatch(m.paste)
                        } label: {
                            Label("全部批量添加（\(m.items.count) 个）", systemImage: "square.stack.3d.up.fill")
                        }
                    }
                }

                Section(header: Text("云厂商")) {
                    Picker("云厂商", selection: $m.prov) {
                        ForEach(m.provs, id: \.self) { p in
                            Text(AddAccountView.SHORT[p] ?? MainPage.pname(p)).tag(p)
                        }
                    }
                    .pickerStyle(.segmented)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("备注名称").font(.caption).foregroundColor(.secondary)
                        TextField("例如 东京主号", text: m.nameBinding)
                            .autocapitalization(.none)
                            .disableAutocorrection(true)
                    }
                }

                Section(header: Text(m.prov == "greencloud" ? "面板与服务器" : "凭证"),
                        footer: Text((AddAccountModel.HINT[m.prov] ?? "") + (m.prov == "greencloud" ? "\n" : " ") + "凭证经 Fernet 加密保存在你的面板服务器，不经过任何第三方。")) {
                    ForEach(m.fields.indices, id: \.self) { i in
                        fieldView(m.fields[i])
                    }
                }

                if m.prov != "greencloud" {
                    Section(header: Text("出口代理（可选）")) {
                        ForEach(AddAccountModel.PROXY.indices, id: \.self) { i in
                            fieldView(AddAccountModel.PROXY[i])
                        }
                    }
                }

                if !m.error.isEmpty {
                    Section {
                        Text("❌ " + m.error).font(.footnote).foregroundColor(.red)
                    }
                }
            }
            .animation(.spring(response: 0.35, dampingFraction: 0.85), value: m.prov)
            .navigationTitle("添加云账号")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { UIHub.shared.closeSheet(nil) }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if m.busy {
                        ProgressView()
                    } else {
                        Button("校验并保存") {
                            m.submit { UIHub.shared.closeSheet { onDone() } }
                        }
                    }
                }
            }
            .interactiveDismissDisabled(m.busy)
        }
        .navigationViewStyle(.stack)
    }

    @ViewBuilder
    private func fieldView(_ f: CredField) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(f.label).font(.caption).foregroundColor(.secondary)
            switch f.type {
            case "multi":
                TextEditor(text: m.binding(f.key))
                    .font(.system(size: 12, design: .monospaced))
                    .frame(minHeight: 90)
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
            case "password":
                SecureField("", text: m.binding(f.key))
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
            default:
                TextField("", text: m.binding(f.key))
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
            }
        }
    }
}

extension Page {
    /// 账号增删后：刷新全局账号列表（侧栏 / 分组）与当前页。
    func accountsChanged() {
        AppState.shared.reloadAccounts()
        refresh()
    }

    func openAddAccount() {
        let m = AddAccountModel()
        m.loadMeta()
        let v = AddAccountView(m: m, onDone: { [weak self] in
            self?.toast("✅ 账号已添加")
            self?.accountsChanged()
        }, onBatch: { [weak self] text in
            UIHub.shared.closeSheet { self?.openBatchAdd(text) }
        })
        UIHub.shared.custom(AnyView(v))
    }

    /// 批量添加：随手复制的内容（控制台页面、环境变量、AWS CSV、Azure 门户、OCI config + 私钥、JSON）混贴，自动拆分多个账号。
    func openBatchAdd(_ prefill: String = "") {
        form("批量添加云账号",
             "直接粘贴复制来的一堆内容：控制台页面、环境变量、AWS accessKeys.csv、Azure 应用注册页、OCI config + 私钥，或 JSON，混在一起也能自动识别、自动拆分成多个账号。每条都会在线校验凭证，最多 50 个。",
             [Field.multi("text", "内容", prefill),
              Field.select("provider", "无法判断云厂商时按", "", ["", "oci", "aws", "azure"], ["不猜测（报错）", "Oracle Cloud", "AWS", "Azure"]),
              Field.check("dry_run", "只检查格式，不校验、不保存", false)], "校验并添加") { v in
            let text = v.optString("text")
            if text.isEmpty { self.toast("请粘贴内容"); return }
            var b: JObj = ["text": text, "dry_run": v.optBoolean("dry_run")]
            if !v.optString("provider").isEmpty { b["provider"] = v.optString("provider") }
            self.toast("正在逐条校验…")
            self.post("/accounts/batch", b) { r in
                let o = jobj(r)
                let rs = o.optJSONArray("results") ?? []
                var sb = ""
                for i in 0..<rs.count {
                    let x = rs.obj(i)
                    sb += (x.optBoolean("ok") ? "✅ " : "❌ ") + MainPage.pname(str(x, "provider", "?")) + " · " + str(x, "name", "-")
                    if x.optBoolean("ok") && x.optInt("ms") > 0 { sb += "  \(x.optInt("ms")) ms" }
                    if !x.optBoolean("ok") { sb += "\n    " + str(x, "error", "") }
                    sb += "\n"
                }
                let dry = v.optBoolean("dry_run")
                let title = (dry ? "格式检查：" : "批量添加：成功 ") + "\(o.optInt("ok")) / 共 \(o.optInt("total"))"
                let msg = sb.trimmingCharacters(in: .whitespacesAndNewlines)
                if dry && o.optInt("ok") > 0 {
                    var nb = b
                    nb["dry_run"] = false
                    self.message(title, msg, primary: ("校验并添加", {
                        self.post("/accounts/batch", nb) { y in
                            self.toast("已添加 \(jobj(y).optInt("ok")) 个")
                            self.accountsChanged()
                        }
                    }), cancel: "取消")
                } else {
                    self.message(title, msg, cancel: "好的", onCancel: { self.accountsChanged() })
                }
            }
        }
    }
}
