import SwiftUI

/// 登录：填写面板地址（如 https://panel.example.com）与面板密码，换取 Bearer token。对应 LoginActivity。
final class LoginPage: Page {
    override func toLogin() { toast("密码或验证码错误（开启了 2FA 需填验证码）") }

    func login(server: String, password: String, otp: String) {
        var url = server.trimmingCharacters(in: .whitespacesAndNewlines)
        while url.hasSuffix("/") { url.removeLast() }
        if !url.hasPrefix("http") { toast("请填写完整地址（含 https://）"); return }
        Api.save(server: url, token: "")
        let b: JObj = ["password": password, "client": "app", "otp": otp.trimmingCharacters(in: .whitespacesAndNewlines)]
        post("/login", b) { r in
            Api.save(server: url, token: jobj(r).optString("token"))
            AppState.shared.loggedInNow()
        }
    }
}

struct LoginView: View {
    @StateObject private var page = LoginPage()
    @State private var server = Api.server
    @State private var password = ""
    @State private var otp = ""
    @State private var appeared = false

    var body: some View {
        NavigationView {
            Form {
                Section {
                    VStack(spacing: 10) {
                        Image(systemName: "cloud.fill")
                            .font(.system(size: 54, weight: .regular))
                            .foregroundStyle(LinearGradient(colors: [.accentColor, .accentColor.opacity(0.65)],
                                                            startPoint: .topLeading, endPoint: .bottomTrailing))
                            .scaleEffect(appeared ? 1 : 0.6)
                            .opacity(appeared ? 1 : 0)
                        (Text("Tri").bold() + Text("Cloud").bold().foregroundColor(.accentColor))
                            .font(.largeTitle)
                        Text("OCI · AWS · Azure 三合一管理\n直连你自托管的面板，凭证不经过第三方。")
                            .font(.footnote)
                            .foregroundColor(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .listRowBackground(Color.clear)
                }
                Section(header: Text("面板"), footer: Text("未开启二次验证可不填验证码。")) {
                    TextField("面板地址 https://panel.example.com", text: $server)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                    SecureField("面板密码", text: $password)
                        .textContentType(.password)
                    TextField("二次验证码", text: $otp)
                        .keyboardType(.numberPad)
                        .textContentType(.oneTimeCode)
                }
                Section {
                    Button {
                        Haptics.tap()
                        page.login(server: server, password: password, otp: otp)
                    } label: {
                        HStack {
                            Spacer()
                            if page.busyCount > 0 { ProgressView().tint(.white).padding(.trailing, 6) }
                            Text("登录").font(.body.weight(.semibold))
                            Spacer()
                        }
                        .frame(minHeight: 36)
                    }
                    .buttonStyle(.borderedProminent)
                    .buttonBorderShape(.roundedRectangle(radius: 12))
                    .controlSize(.large)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
                    .disabled(page.busyCount > 0)
                }
            }
            .navigationBarHidden(true)
            .onAppear { withAnimation(.spring(response: 0.6, dampingFraction: 0.7).delay(0.1)) { appeared = true } }
        }
        .navigationViewStyle(.stack)
    }
}
