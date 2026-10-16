import SwiftUI
import UIKit

// build 21 OneDrive 定期备份（对照 Web pageOneDrive / Android OneDriveActivity）：
// 状态、设备码绑定（microsoft.com/devicelogin + 轮询）、计划 / 保留 / 备份密码、立即备份、备份列表与恢复（密码 + 二次确认）、解绑。

final class OneDrivePage: Page {
    static let loginURL = "https://microsoft.com/devicelogin"
    static let weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    private var pollGen = 0
    private var justSaved = false   // build 22：刚保存 client_id 且未绑定 → 提示「点绑定 OneDrive 获取代码」
    private var pollingGen = -1   // 已经在轮询的那一代，避免刷新页面时重复开轮询
    private var visible = false

    override init() {
        super.init()
        title = "OneDrive 备份"
    }

    override func appeared() { visible = true; super.appeared() }
    override func disappeared() { visible = false }

    static func plan(_ c: JObj) -> String {
        let wd = max(0, min(6, c.optInt("weekday")))
        return (c.optString("freq") == "weekly" ? "每" + weekdays[wd] + " " : "每天 ") + c.optString("time", "03:30") + "，保留 \(c.optInt("keep", 30)) 份"
    }

    override func refresh() {
        get("/onedrive") { r in self.build(jobj(r)) }
    }

    private func build(_ s: JObj) {
        clear()
        let c = s.optJSONObject("cfg") ?? [:]
        let st = s.optJSONObject("state") ?? [:]
        let acc = s.optJSONObject("account") ?? [:]
        let bound = s.optBoolean("bound"), pwSet = s.optBoolean("password_set")
        let running = s.optInt("running_task_id")

        let a = card("状态")
        var lines: [String] = []
        let folder = str(acc, "folder", "")
        lines.append(bound ? "✅ 已绑定" + (folder.isEmpty ? "" : "（OneDrive / 应用 / \(folder)）") : "未绑定")
        lines.append("备份密码：" + (pwSet ? "已设置" : "未设置"))
        if s.optBoolean("ready") {
            lines.append("定时：" + OneDrivePage.plan(c) + "（" + s.optString("timezone") + "）")
            lines.append("下次备份：" + str(s, "next_run", "-"))
        } else {
            lines.append(!bound ? "绑定 OneDrive 并设置备份密码后开始定时备份" : !pwSet ? "设置备份密码后开始定时备份" : "定时备份已停用")
        }
        if st.optLong("last_ok") > 0 {
            lines.append("上次成功：" + fmtTime(st.optLong("last_ok")) + " · " + str(st, "last_file", "")
                         + (st.optLong("last_size") > 0 ? " · " + fmtBytes(st.optLong("last_size")) : ""))
        }
        if str(st, "last_result", "") == "failed" { lines.append("❌ 上次失败：" + str(st, "last_error", "")) }
        if !str(st, "auth_error", "").isEmpty { lines.append("⚠️ " + str(st, "auth_error", "")) }
        if running > 0 { lines.append("⏳ 备份进行中（任务 #\(running)）") }
        a.text(lines.joined(separator: "\n"), 14)
        let ar = a.row()
        if bound && pwSet && running == 0 {
            ar.button("立即备份") {
                self.post("/onedrive/backup", nil) { x in self.taskOrToast(x, "已开始备份"); self.later(1.5) { self.refresh() } }
            }
        }
        if running > 0 { ar.button("查看进度") { self.openTask(running) } }
        if bound {
            ar.button("解绑 OneDrive") {
                self.confirm("解绑 OneDrive", "将删除本机保存的 OneDrive 授权，定时备份停止。\nOneDrive 上已有的备份文件不会删除，以后重新绑定还能恢复。确定解绑？") {
                    self.del("/onedrive/bind?confirm=true") { _ in self.toast("已解绑"); self.refresh() }
                }
            }
        }

        if let p = s.optJSONObject("pending") { pendingCard(p) }

        let ap = card("1. Azure 应用与绑定")
        ap.muted("在 Azure 门户注册你自己的应用（公共客户端、允许个人 Microsoft 帐户、启用「允许公共客户端流」），把「应用程序(客户端) ID」填到这里。只申请 Files.ReadWrite.AppFolder + offline_access，看不到网盘里的其他文件。教程见 docs/api-credentials.md「OneDrive 备份」。")
        let cid = str(s, "client_id", "")
        ap.text("client_id：" + (cid.isEmpty ? "未填写" : cid) + "\n登录端点：" + s.optString("tenant", "consumers"), 13)
        if !bound {
            ap.muted(cid.isEmpty ? "先点「填写 client_id」保存，然后点下面蓝色「绑定 OneDrive」获取代码。"
                     : (justSaved ? "✅ 已保存。" : "") + "点下面蓝色「绑定 OneDrive」获取代码，代码会显示在下方。")
        }
        justSaved = false
        let apr = ap.row()
        apr.button(cid.isEmpty ? "填写 client_id" : "修改 client_id") {
            self.form("Azure 应用", "client_id 为「应用程序(客户端) ID」；换应用会解除当前绑定。", [
                Field.text("client_id", "client_id", cid),
                Field.select("tenant", "登录端点", s.optString("tenant", "consumers"), ["consumers", "common"],
                             ["consumers（个人 Microsoft 帐户，推荐）", "common（个人 + 工作/学校帐户）"])], "保存") { v in
                self.post("/onedrive/config", v) { x in
                    let o = jobj(x)
                    let ch = o.optJSONArray("changed") ?? []
                    let unb = (0..<ch.count).contains { ch.string($0) == "unbound" }
                    let need = !o.optBoolean("bound") && !str(o, "client_id", "").isEmpty
                    self.toast(unb ? "已保存；换了应用，原绑定已解除。点「绑定 OneDrive」获取代码" : need ? "已保存，点「绑定 OneDrive」获取代码" : "已保存")
                    self.justSaved = need
                    self.refresh()
                }
            }
        }
        if !cid.isEmpty && bound {
            apr.button("重新绑定") {
                self.post("/onedrive/bind", nil) { x in self.startPending(jobj(x)) }
            }
        }
        if !cid.isEmpty && !bound {   // 未绑定：单独的醒目主按钮（borderedProminent），代码点它才出现
            bigButton("绑定 OneDrive") {
                self.post("/onedrive/bind", nil) { x in self.startPending(jobj(x)) }
            }
        }

        let pl = card("2. 计划、保留与备份密码")
        pl.muted("启用：" + (c.optBoolean("enabled", true) ? "是" : "否") + " · " + OneDrivePage.plan(c)
                 + "\n备份文件用备份密码加密（scrypt + AES-256-GCM）；为了无人值守定时运行，密码用面板 Fernet 密钥加密后保存在面板数据库里。")
        let plr = pl.row()
        plr.button("修改计划") {
            self.form("备份计划", "时间按面板时区（" + s.optString("timezone") + "）。", [
                Field.check("enabled", "启用定时备份", c.optBoolean("enabled", true)),
                Field.select("freq", "频率", c.optString("freq", "daily"), ["daily", "weekly"], ["每天", "每周"]),
                Field.select("weekday", "星期（每周时）", String(c.optInt("weekday")), ["0", "1", "2", "3", "4", "5", "6"], OneDrivePage.weekdays),
                Field.text("time", "时间 HH:MM", c.optString("time", "03:30")),
                Field.num("keep", "保留最近几份（1–365）", String(c.optInt("keep", 30)))], "保存") { v in
                self.post("/onedrive/config", v) { _ in self.toast("已保存"); self.refresh() }
            }
        }
        plr.button(pwSet ? "修改备份密码" : "设置备份密码") {
            self.form("备份密码", "不能为空，长度不限；恢复时需要，丢失无法恢复，请另外记下来。",
                      [Field.pass("password", "备份密码"), Field.pass("password2", "再输一次")], "保存") { v in
                if v.optString("password").trimmingCharacters(in: .whitespaces).isEmpty { self.toast("备份密码不能为空"); return }
                if v.optString("password") != v.optString("password2") { self.toast("两次输入的备份密码不一致"); return }
                self.post("/onedrive/config", v) { _ in self.toast("备份密码已保存"); self.refresh() }
            }
        }

        let hp = card("新装机恢复 / 离线解密")
        hp.muted("1）装好面板并登录 2）这里填 client_id 并绑定同一个 Microsoft 帐户 3）下方列表选一份 → 恢复 → 输入备份密码 4）面板自动重启，用备份时的面板密码重新登录。\n恢复前面板会在 data/ 下自动保存一份当前数据。\n离线解密：python -m tools.decrypt_backup 文件 输出目录")

        let ls = card("OneDrive 上的备份")
        guard bound else { ls.muted("绑定后显示"); return }
        get("/onedrive/backups") { x in
            let o = jobj(x)
            let items = o.optJSONArray("items") ?? []
            if items.isEmpty { ls.muted("还没有备份，点「立即备份」试一次"); return }
            ls.muted("共 \(items.count) 份，保留最近 \(o.optInt("keep")) 份。")
            for i in 0..<items.count {
                let it = items.obj(i)
                let when = str(it, "time", str(it, "created", ""))
                let iid = it.optString("id"), nm = it.optString("name")
                ls.text(when + " · " + fmtBytes(it.optLong("size")) + "\n" + nm, 13)
                ls.row().button("恢复这份") { self.restore(iid, nm) }
            }
        }
    }

    private func pendingCard(_ p: JObj) {
        let code = p.optString("user_code")
        let url = str(p, "verification_uri", OneDrivePage.loginURL)
        let pc = card("等待授权")
        pc.text("1）打开 " + url.replacingOccurrences(of: "https://", with: "") + "\n2）输入代码：" + code + "\n3）用要存备份的 Microsoft 帐户登录并同意授权", 14)
        pc.muted("授权后这里会自动显示已绑定（\(max(1, p.optInt("expires_in", 900) / 60)) 分钟内有效）。")
        let r = pc.row()
        r.button("复制代码并打开") {
            copyText(code)
            if let u = URL(string: url) { UIApplication.shared.open(u) }
        }
        r.button("取消") {
            self.pollGen += 1
            self.del("/onedrive/bind?pending_only=true") { _ in self.refresh() }
        }
        if pollingGen != pollGen {
            pollingGen = pollGen
            schedulePoll(pollGen, max(2, p.optInt("interval", 5)))
        }
    }

    private func startPending(_ p: JObj) {
        pollGen += 1
        refresh()   // 页面里显示「等待授权」卡片并开始轮询
        let code = p.optString("user_code")
        let url = str(p, "verification_uri", OneDrivePage.loginURL)
        message("绑定 OneDrive", "在 " + OneDrivePage.loginURL.replacingOccurrences(of: "https://", with: "") + " 输入代码：\n\n" + code,
                primary: ("复制代码并打开", { copyText(code); if let u = URL(string: url) { UIApplication.shared.open(u) } }), cancel: "稍后")
    }

    private func schedulePoll(_ gen: Int, _ interval: Int) {
        later(Double(interval)) {
            guard gen == self.pollGen else { return }
            if !self.visible { self.schedulePoll(gen, interval); return }   // 去浏览器授权时暂停，回来继续
            Api.call("POST", "/onedrive/bind/poll", nil) { res in
                guard gen == self.pollGen else { return }
                switch res {
                case .success(let r):
                    let o = jobj(r)
                    switch o.optString("status") {
                    case "ok":
                        self.pollGen += 1
                        Haptics.success()
                        self.toast("OneDrive 已绑定")
                        self.refresh()
                    case "pending", "slow_down":
                        self.schedulePoll(gen, max(interval, o.optInt("interval", interval)))
                    default:
                        self.pollGen += 1
                        self.toast("❌ " + o.optString("message", "绑定失败"))
                        self.refresh()
                    }
                case .failure:
                    self.schedulePoll(gen, interval)
                }
            }
        }
    }

    private func restore(_ iid: String, _ name: String) {
        form("从 OneDrive 恢复", "备份：" + name + "\n⚠️ 当前全部数据（云账号、设置、任务、审计）将被这份备份覆盖。恢复前会自动在 data/ 下保存一份当前数据。",
             [Field.pass("password", "这份备份的备份密码")], "下一步") { v in
            let pw = v.optString("password")
            if pw.isEmpty { self.toast("请输入备份密码"); return }
            self.message("确认恢复", "确定用 " + name + " 覆盖当前全部数据？\n所有设备需要重新登录，面板会自动重启。",
                         primary: ("恢复并覆盖", {
                            self.post("/onedrive/restore", ["item_id": iid, "password": pw, "confirm": true]) { x in
                                let o = jobj(x)
                                self.toast(o.optString("message", "已恢复，请重新登录"))
                                self.later(o.optBoolean("restart") ? 10 : 1.5) { self.toLogin() }
                            }
                         }), cancel: "取消")
        }
    }
}
