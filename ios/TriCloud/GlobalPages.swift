import SwiftUI
import UIKit
import UniformTypeIdentifiers

// 全局页：免费额度体检、开机密码、脚本模板、DNS 联动、安全与备份（对照 Web pageFreeCheck / pageSecrets / pageScripts / pageDns / pageSecurity）。

/// 系统分享面板与文件选择（备份下载 / 恢复、对象存储上传）。
enum DocIO {
    static var pickerDelegate: PickerDelegate?

    static func topVC() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let win = scenes.flatMap { $0.windows }.first { $0.isKeyWindow } ?? scenes.first?.windows.first
        var vc = win?.rootViewController
        while let p = vc?.presentedViewController, !p.isBeingDismissed { vc = p }
        return vc
    }

    static func share(_ url: URL) {
        guard let vc = topVC() else { return }
        let av = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        if let pop = av.popoverPresentationController {
            pop.sourceView = vc.view
            pop.sourceRect = CGRect(x: vc.view.bounds.midX, y: vc.view.bounds.midY, width: 1, height: 1)
            pop.permittedArrowDirections = []
        }
        vc.present(av, animated: true)
    }

    /// 选择一个文件（拷贝到沙盒后回调本地 URL）。
    static func pick(_ done: @escaping (URL) -> Void) {
        let p = UIDocumentPickerViewController(forOpeningContentTypes: [UTType.item], asCopy: true)
        let d = PickerDelegate(done)
        pickerDelegate = d
        p.delegate = d
        p.allowsMultipleSelection = false
        topVC()?.present(p, animated: true)
    }
}

final class PickerDelegate: NSObject, UIDocumentPickerDelegate {
    let done: (URL) -> Void
    init(_ done: @escaping (URL) -> Void) { self.done = done }

    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        let cb = done
        DocIO.pickerDelegate = nil
        if let u = urls.first {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { cb(u) }
        }
    }

    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        DocIO.pickerDelegate = nil
    }
}

func fmtTime(_ ts: Int64, _ pattern: String = "yyyy-MM-dd HH:mm") -> String {
    if ts <= 0 { return "-" }
    let f = DateFormatter()
    f.dateFormat = pattern
    return f.string(from: Date(timeIntervalSince1970: TimeInterval(ts)))
}

// MARK: - 免费额度体检

final class FreeCheckPage: Page {
    override init() {
        super.init()
        title = "免费额度体检"
    }

    override func refresh() {
        clear()
        card("正在逐个检查 OCI 账号…").muted("读取主区域 / 默认区域的 A1、E2.1.Micro、块存储用量")
        get("/oci/free-check") { r in
            self.clear()
            self.card("说明").muted("逐个检查 OCI 账号（主区域 / 默认区域）的 A1、E2.1.Micro、块存储用量是否超出 Always Free。只给建议，降配需要你确认后才执行（只降不升，不会删实例）。A1 免费额度：免费号 2 OCPU / 12 GB（2026-06 起），付费号 4 OCPU / 24 GB。")
            let a = jarr(r)
            if a.isEmpty { self.card("没有启用中的 OCI 账号").muted("") }
            for i in 0..<a.count {
                let x = a.obj(i)
                let aid = x.optInt("account_id")
                if x.has("error") && !x.isNull("error") {
                    self.card(x.optString("name")).muted("❌ " + x.optString("error"))
                    continue
                }
                let ok = x.optBoolean("ok")
                let c = self.card(x.optString("name") + (ok ? "  ✅" : "  ⚠️"))
                let a1 = x.optJSONObject("a1") ?? [:], mi = x.optJSONObject("micro") ?? [:], st = x.optJSONObject("storage") ?? [:]
                FreeCheckPage.bar(c, "A1 OCPU", a1, "ocpus", "limit_ocpus", "")
                FreeCheckPage.bar(c, "A1 内存", a1, "memory_gb", "limit_mem", " GB")
                FreeCheckPage.bar(c, "E2.1.Micro", mi, "count", "limit", " 台")
                FreeCheckPage.bar(c, "块存储", st, "used_gb", "limit", " GB")
                if ok { c.text("都在免费额度内", 14, true) }
                let issues = x.optJSONArray("issues") ?? []
                for j in 0..<issues.count { c.text("• " + issues.string(j), 13) }
                let sg = x.optJSONArray("suggestions") ?? []
                let row = c.row()
                for j in 0..<sg.count {
                    let s = sg.obj(j)
                    let from = s.optString("ocpus") + "C/" + s.optString("memory_gb") + "G"
                    if s.optBoolean("delete") {
                        c.muted(s.optString("name") + "：" + from + " → 额度已用完，建议停用或删除")
                    } else {
                        let to = s.optString("to_ocpus") + "C/" + s.optString("to_memory_gb") + "G"
                        c.muted(s.optString("name") + "：" + from + " → " + to)
                        row.button("降配 " + s.optString("name")) {
                            self.confirm("降配", "把「" + s.optString("name") + "」从 " + from + " 降到 " + to + "？实例可能会重启。") {
                                let b: JObj = ["instance_id": s.optString("id"), "name": s.optString("name"), "ocpus": s.optString("to_ocpus"),
                                               "memory_gb": s.optString("to_memory_gb"), "confirm_overage": true]
                                self.post("/accounts/\(aid)/instances/resize", b) { y in self.taskOrToast(y, "已提交") }
                            }
                        }
                    }
                }
                if let acc = AppState.shared.accounts.first(where: { $0.optInt("id") == aid }) {
                    row.button("进入账号") { self.push(AccountPage(acc)) }
                }
            }
        }
    }

    static func bar(_ c: Card, _ label: String, _ o: JObj, _ k: String, _ lk: String, _ unit: String) {
        let v = o.optDouble(k, 0), lim = o.optDouble(lk, 0)
        let vs = o.isNull(k) ? "-" : o.optString(k)
        let over: String = v > lim && lim > 0 ? "（超出）" : ""
        let text: String = label + "  " + vs + " / " + o.optString(lk) + unit + over
        c.meter(lim > 0 ? v / lim : 0, text)
    }
}

// MARK: - 开机密码

final class SecretsPage: Page {
    override init() {
        super.init()
        title = "开机密码"
    }

    override func refresh() {
        get("/secrets") { r in
            self.clear()
            self.card("说明").muted("面板创建 / 抢机 / 重装生成的随机密码，经 Fernet 加密保存。查看需要输入面板密码。")
            let a = jarr(r)
            if a.isEmpty { self.card("暂无").muted("创建实例时勾选「生成随机 root 密码」后会出现在这里") }
            for i in 0..<a.count {
                let x = a.obj(i)
                let sid = x.optInt("id")
                let c = self.card(x.optString("name"))
                c.muted(str(x, "account_name", "-") + " · 用户 " + x.optString("username") + "\n创建于 " + fmtTime(x.optLong("created")))
                let row = c.row()
                row.button("查看") {
                    self.form("验证面板密码", "查看「" + x.optString("name") + "」的开机密码", [Field.pass("password", "面板密码")], "查看") { v in
                        self.post("/secrets/\(sid)/reveal", ["password": v.optString("password")]) { y in
                            let o = jobj(y)
                            let pw = o.optString("password")
                            self.message("开机密码 · " + x.optString("name"), "用户：" + o.optString("username") + "\n密码：" + pw,
                                         primary: ("复制密码", { copyText(pw); self.toast("已复制") }), cancel: "关闭")
                        }
                    }
                }
                row.button("删除") {
                    self.confirm("删除", "删除后无法再找回此密码。确定？") { self.del("/secrets/\(sid)") { _ in self.refresh() } }
                }
            }
        }
    }
}

// MARK: - 脚本模板

final class ScriptsPage: Page {
    static let PRESETS: [(String, String)] = [
        ("开启 BBR", "#!/bin/bash\necho 'net.core.default_qdisc=fq' >> /etc/sysctl.conf\necho 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.conf\nsysctl -p"),
        ("2GB Swap", "#!/bin/bash\nfallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile\necho '/swapfile none swap sw 0 0' >> /etc/fstab"),
        ("关闭 OCI 系统防火墙", "#!/bin/bash\niptables -P INPUT ACCEPT; iptables -P FORWARD ACCEPT; iptables -P OUTPUT ACCEPT; iptables -F\nnetfilter-persistent save 2>/dev/null || true\nsystemctl disable --now firewalld 2>/dev/null || true"),
        ("时区上海 + 常用工具", "#!/bin/bash\ntimedatectl set-timezone Asia/Shanghai\n(apt-get update && apt-get install -y curl wget unzip htop) || (dnf install -y curl wget unzip htop)"),
    ]

    override init() {
        super.init()
        title = "脚本模板"
    }

    override var menu: [(String, () -> Void)] { [("新建模板", { self.newScript() })] }

    override func refresh() {
        get("/scripts") { r in
            self.clear()
            self.card("说明").muted("创建 EC2 / Lightsail / OCI / Azure 实例时可选用，以 root 在首次开机执行（日志在 /root/tricloud-init.log）。不建议 curl | bash 来源不明的远程脚本。")
            let a = jarr(r)
            if a.isEmpty { self.card("暂无模板").muted("") }
            for i in 0..<a.count {
                let x = a.obj(i)
                let c = self.card(x.optString("name"))
                let content = x.optString("content")
                c.muted(String(content.prefix(160)) + (content.count > 160 ? "…" : ""))
                let row = c.row()
                row.button("编辑") { self.edit(x) }
                row.button("复制内容") { copyText(content); self.toast("已复制") }
                row.button("删除") {
                    self.confirm("删除模板", "确定删除「" + x.optString("name") + "」？") {
                        self.del("/scripts/\(x.optInt("id"))") { _ in self.toast("已删除"); self.refresh() }
                    }
                }
            }
            self.bigButton("＋ 新建模板") { self.newScript() }
        }
    }

    private func newScript() {
        choose("从预设开始", ["空白"] + ScriptsPage.PRESETS.map { $0.0 }) { i in
            if i == 0 { self.edit(nil) } else { self.edit(["name": ScriptsPage.PRESETS[i - 1].0, "content": ScriptsPage.PRESETS[i - 1].1]) }
        }
    }

    private func edit(_ x: JObj?) {
        let isEdit = (x?.optInt("id") ?? 0) > 0
        form(isEdit ? "编辑模板" : "新建模板", "以 root 在首次开机执行", [
            Field.text("name", "名称", x?.optString("name") ?? ""),
            Field.multi("content", "脚本", x?.optString("content") ?? "#!/bin/bash\n")], "保存") { v in
            if v.optString("name").isEmpty { self.toast("请填写名称"); return }
            var b: JObj = ["name": v.optString("name"), "content": v.optString("content")]
            if isEdit { b["id"] = x!.optInt("id") }
            self.post("/scripts", b) { _ in self.toast("已保存"); self.refresh() }
        }
    }
}

// MARK: - DNS 联动

final class DnsPage: Page {
    override init() {
        super.init()
        title = "DNS 联动"
    }

    override func refresh() {
        get("/dns-bindings") { r in
            self.clear()
            self.card("Cloudflare DNS 联动").muted("在实例的「更多操作 → 绑定域名」添加。绑定后换 IP / 分配 IPv6 会自动更新这条 Cloudflare 记录。API Token 在「设置 → Cloudflare」配置。")
            let a = jarr(r)
            if a.isEmpty { self.card("暂无绑定").muted("") }
            for i in 0..<a.count {
                let d = a.obj(i)
                let c = self.card(d.optString("record"))
                var t = (d.optBoolean("v4") || d.optInt("v4") == 1) ? "A " : ""
                if d.optBoolean("v6") || d.optInt("v6") == 1 { t += "AAAA " }
                if d.optBoolean("proxied") || d.optInt("proxied") == 1 { t += "· 代理" }
                c.muted(str(d, "name", "-") + " · " + str(d, "account_name", "-") + "\n" + (t.isEmpty ? "-" : t))
                c.row().button("解绑") {
                    self.confirm("解绑域名", "解绑后换 IP 不再自动更新这条解析（Cloudflare 上的记录保留）。确定？") {
                        self.del("/dns-bindings/\(d.optInt("id"))") { _ in self.toast("已解绑"); self.refresh() }
                    }
                }
            }
        }
    }
}

// MARK: - 安全与备份

final class SecurityPage: Page {
    override init() {
        super.init()
        title = "安全与备份"
    }

    override func refresh() {
        get("/settings") { sr in
            let s = jobj(sr)
            self.get("/tokens") { tr in
                self.get("/audit?limit=100") { lr in self.build(s, jarr(tr), jarr(lr)) }
            }
        }
    }

    private func build(_ s: JObj, _ toks: JArr, _ logs: JArr) {
        clear()
        let tf = card("二次验证（TOTP）")
        if s.optBoolean("totp_enabled") {
            tf.text("✅ 已开启：登录需要身份验证器 App 上的 6 位验证码。", 14)
            tf.row().button("关闭") {
                self.form("关闭二次验证", nil, [Field.pass("password", "面板密码"), Field.num("code", "当前验证码", "")], "关闭") { v in
                    self.post("/2fa/disable", v) { _ in self.toast("已关闭"); self.refresh() }
                }
            }
        } else {
            tf.muted("支持 Google Authenticator、1Password、Authy 等。开启后即使面板密码泄露也无法登录。")
            tf.row().button("开启") { self.setup2fa() }
        }

        let bk = card("加密备份 / 恢复")
        bk.muted("备份包含全部账号凭证、设置和加密密钥，整包再用你设置的口令加密（scrypt + Fernet）。口令丢失则无法恢复。下载后可存到「文件」或 AirDrop。")
        let br = bk.row()
        br.button("下载备份") { self.backup() }
        br.button("从备份恢复") { self.restore() }

        let tk = card("API Token")
        tk.muted("给脚本、自建 Bot 调用面板 API 用（Header：Authorization: Bearer tc_...）。只读 Token 只能 GET；任何 Token 都不能改密码、2FA、备份。")
        for i in 0..<toks.count {
            let t = toks.obj(i)
            tk.text(t.optString("name") + "  ·  " + t.optString("prefix") + "…  ·  " + (t.optString("scope") == "read" ? "只读" : "完全"), 14, true)
            tk.muted("最近使用：" + (t.optLong("last_used") > 0 ? fmtTime(t.optLong("last_used")) : "从未"))
        }
        if toks.isEmpty { tk.muted("暂无 Token") }
        let tr = tk.row()
        tr.button("＋ 新建") {
            self.form("新建 API Token", nil, [Field.text("name", "名称", "bot"),
                                             Field.select("scope", "权限", "read", ["read", "full"], ["只读", "完全（可开关机、换 IP）"])], "生成") { v in
                self.post("/tokens", v) { y in
                    let tok = jobj(y).optString("token")
                    self.message("Token 已生成", "只显示这一次，请立即保存：\n\n" + tok,
                                 primary: ("复制", { copyText(tok); self.toast("已复制") }), cancel: "关闭", onCancel: { self.refresh() })
                }
            }
        }
        if !toks.isEmpty {
            tr.button("吊销…") {
                let labels = (0..<toks.count).map { toks.obj($0).optString("name") + " · " + toks.obj($0).optString("prefix") + "…" }
                self.choose("吊销哪个 Token", labels) { i in
                    self.confirm("吊销 Token", "使用此 Token 的程序将立即失效。确定？") {
                        self.del("/tokens/\(toks.obj(i).optInt("id"))") { _ in self.toast("已吊销"); self.refresh() }
                    }
                }
            }
        }

        let au = card("审计日志")
        au.muted("最近 100 条写操作，保留 180 天")
        var lines: [String] = []
        for i in 0..<logs.count {
            let l = logs.obj(i)
            lines.append(fmtTime(l.optLong("ts"), "MM-dd HH:mm") + "  " + l.optString("action") + "  " + l.optString("detail")
                         + "\n    " + l.optString("ip") + " · " + l.optString("actor"))
        }
        au.text(lines.isEmpty ? "暂无" : lines.joined(separator: "\n"), 12)
    }

    private func setup2fa() {
        post("/2fa/setup", nil) { r in
            let o = jobj(r)
            let secret = o.optString("secret"), uri = o.optString("uri")
            self.message("开启二次验证", "在身份验证器 App 中「手动输入密钥」：\n\n" + secret + "\n\n复制后回到这里输入 App 显示的 6 位验证码完成绑定。",
                         primary: ("复制密钥并继续", {
                            copyText(secret)
                            self.form("输入验证码", "密钥已复制。也可以把这个链接复制到支持的 App：\n" + uri, [Field.num("code", "6 位验证码", "")], "开启") { v in
                                self.post("/2fa/enable", ["code": v.optString("code")]) { _ in self.toast("✅ 二次验证已开启"); self.refresh() }
                            }
                         }), cancel: "取消")
        }
    }

    private func backup() {
        form("下载加密备份", "恢复时需要备份口令，请牢记。", [Field.pass("password", "面板密码"), Field.pass("passphrase", "备份口令（≥10 位）")], "下载") { v in
            self.setBusy(true)
            Api.raw("POST", "/backup", json: v) { res in
                self.setBusy(false)
                switch res {
                case .success(let (data, name)):
                    let url = FileManager.default.temporaryDirectory.appendingPathComponent(name.isEmpty ? "tricloud.tcbk" : name)
                    do {
                        try data.write(to: url, options: .atomic)
                        Haptics.success()
                        DocIO.share(url)
                    } catch {
                        self.toast("❌ 保存失败：" + error.localizedDescription)
                    }
                case .failure(let e):
                    self.toast("❌ " + ((e as? ApiError)?.msg ?? e.localizedDescription))
                }
            }
        }
    }

    private func restore() {
        confirm("从备份恢复", "⚠️ 当前所有数据将被备份内容覆盖，所有设备需重新登录。接下来选择 .tcbk 备份文件。") {
            DocIO.pick { url in
                guard let data = try? Data(contentsOf: url), !data.isEmpty else { self.toast("❌ 读取文件失败"); return }
                self.form("从备份恢复", "文件：" + url.lastPathComponent + "（" + fmtBytes(Int64(data.count)) + "）",
                          [Field.pass("passphrase", "备份口令"), Field.pass("password", "当前面板密码")], "恢复") { v in
                    var b = v
                    b["file_b64"] = data.base64EncodedString()
                    self.post("/restore", b) { _ in
                        self.toast("已恢复，请重新登录")
                        self.later(1.2) { self.toLogin() }
                    }
                }
            }
        }
    }
}

func fmtBytes(_ n: Int64) -> String {
    var v = Double(n)
    let u = ["B", "KB", "MB", "GB", "TB"]
    var i = 0
    while v >= 1024 && i < 4 { v /= 1024; i += 1 }
    return i == 0 ? "\(Int(v)) B" : String(format: "%.1f ", v) + u[i]
}
