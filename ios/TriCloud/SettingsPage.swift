import SwiftUI
import UIKit

/// 设置：Telegram、每日报告、监控间隔、默认创建参数、免费额度护栏、自动换 IP 上限、面板密码、App 配色。对应 SettingsActivity。
final class SettingsPage: Page {
    override init() { super.init(); title = "设置" }

    static let defaultCreateTemplate = "{\n  \"oci\": {\"shape\": \"VM.Standard.A1.Flex\", \"ocpus\": 4, \"memory_gb\": 24, \"disk_gb\": 50, \"os\": \"Canonical Ubuntu\", \"ssh_key\": \"\"},\n  \"lightsail\": {\"blueprint\": \"debian_12\", \"bundle\": \"nano_3_0\"}\n}"

    override func refresh() {
        get("/settings") { r in
            self.clear()
            let s = jobj(r)
            let tg = self.card("Telegram")
            tg.muted("Bot Token：" + (s.optBoolean("tg_token_set") ? "已设置 " + s.optString("tg_token_hint") : "未设置")
                     + "\nChat ID：" + str(s, "tg_chat_id", "-") + "\n每日报告：" + (s.optBoolean("daily_report") ? "开 " + str(s, "report_time", "09:00") : "关")
                     + "\n监控间隔：" + str(s, "monitor_interval", "5") + " 分钟")
            let r1 = tg.row()
            r1.button("修改") {
                self.form("Telegram 设置", "Token 留空保持不变", [
                    Field.pass("tg_token", "Bot Token"),
                    Field.text("tg_chat_id", "Chat ID", str(s, "tg_chat_id", "")),
                    Field.check("daily_report", "每日账单报告", s.optBoolean("daily_report")),
                    Field.text("report_time", "报告时间 HH:MM", str(s, "report_time", "09:00")),
                    Field.num("monitor_interval", "监控间隔（分钟）", str(s, "monitor_interval", "5")),
                    Field.text("timezone", "时区", str(s, "timezone", "Asia/Shanghai"))], "保存") { vals in
                    var v = vals
                    if v.optString("tg_token").isEmpty { v.removeValue(forKey: "tg_token") }
                    self.post("/settings", v) { _ in self.toast("已保存"); self.refresh() }
                }
            }
            r1.button("发送测试") { self.post("/settings/tg-test", nil) { _ in self.toast("测试消息已发送") } }

            let cf = self.card("Cloudflare")
            cf.muted("用于换 IP 后自动更新 DNS（DNS 联动）。建议创建仅含「Zone.DNS 编辑」权限、限定域名的 API Token。\n当前：" + (s.optBoolean("cf_token_set") ? "已设置" : "未设置"))
            let cr = cf.row()
            cr.button(s.optBoolean("cf_token_set") ? "更换 Token" : "填写 Token") {
                self.form("Cloudflare API Token", nil, [Field.pass("cf_token", "API Token")], "保存") { v in
                    if v.optString("cf_token").isEmpty { self.toast("请输入 Token"); return }
                    self.post("/settings", v) { _ in self.toast("已保存"); self.refresh() }
                }
            }
            if s.optBoolean("cf_token_set") {
                cr.button("清除") { self.post("/settings", ["cf_token_clear": true]) { _ in self.toast("已清除"); self.refresh() } }
            }

            let pc = self.card("IP 质量检测")
            pc.muted("风险分来自 proxycheck.io：不填 Key 每天 100 次，免费注册的 Key 每天 1000 次。只发送要检测的公网 IP。\n当前 Key：" + (s.optBoolean("proxycheck_key_set") ? "已设置" : "未设置"))
            let pr = pc.row()
            pr.button(s.optBoolean("proxycheck_key_set") ? "更换 Key" : "填写 Key") {
                self.form("proxycheck.io Key", nil, [Field.pass("proxycheck_key", "Key")], "保存") { v in
                    if v.optString("proxycheck_key").isEmpty { self.toast("请输入 Key"); return }
                    self.post("/settings", v) { _ in self.toast("已保存"); self.refresh() }
                }
            }
            if s.optBoolean("proxycheck_key_set") {
                pr.button("清除") { self.post("/settings", ["proxycheck_key_clear": true]) { _ in self.toast("已清除"); self.refresh() } }
            }

            let dc = self.card("默认创建参数（JSON）")
            var initial = SettingsPage.defaultCreateTemplate
            if let d = s.optJSONObject("default_create"),
               let data = try? JSONSerialization.data(withJSONObject: d, options: [.prettyPrinted, .sortedKeys]),
               let t = String(data: data, encoding: .utf8) {
                initial = t
            }
            let editor = dc.editor(initial)
            dc.row().button("保存") {
                guard let data = editor.text.data(using: .utf8),
                      let obj = try? JSONSerialization.jsonObject(with: data), obj is JObj else {
                    self.toast("JSON 格式错误")
                    return
                }
                self.post("/settings", ["default_create": obj]) { _ in self.toast("已保存") }
            }

            let fg = self.card("免费额度护栏")
            let on = s.isNull("free_guard") || s.optBoolean("free_guard", true)
            fg.muted("创建、改配置、扩容前估算是否超出免费额度，超出时二次确认。当前：" + (on ? "开" : "关"))
            fg.row().button(on ? "关闭护栏" : "开启护栏") { self.post("/settings", ["free_guard": !on]) { _ in self.refresh() } }

            let ai = self.card("自动换 IP 每日上限")
            let limit = s.optInt("auto_ip_daily_limit", 3)
            ai.muted("IP 不通触发的自动换 IP，每账号每天最多 \(limit) 次；达到上限或失败只推送 Telegram 告警。")
            ai.row().button("修改") {
                self.form("自动换 IP 每日上限", "0 = 不自动换（0~50）", [Field.num("auto_ip_daily_limit", "每账号每天次数", String(limit))], "保存") { vals in
                    guard let n = Int(vals.optString("auto_ip_daily_limit", "3")) else { self.toast("请输入整数"); return }
                    self.post("/settings", ["auto_ip_daily_limit": n]) { _ in self.refresh() }
                }
            }

            let pw = self.card("面板密码")
            pw.row().button("修改密码") {
                self.form("修改面板密码", "修改后所有设备需重新登录", [Field.pass("old", "原密码"), Field.pass("new", "新密码（≥10 位）")], "修改") { vals in
                    self.post("/password", vals) { _ in self.toast("已修改"); self.toLogin() }
                }
            }

            let th = self.card("配色")
            let r4 = th.row()
            let cur = AppState.shared.theme
            for m in [("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")] {
                r4.button((m.0 == cur ? "● " : "") + m.1) { AppState.shared.setTheme(m.0); self.refresh() }
            }

            let lg = self.card("界面语言")
            let lgr = lg.row()
            let curl = AppState.shared.lang
            for m in [("system", "跟随系统"), ("zh", "中文"), ("en", "English")] {
                lgr.button((m.0 == curl ? "● " : "") + m.1) { AppState.shared.setLang(m.0); self.refresh() }
            }

            let od = self.card("OneDrive 备份")
            od.muted("把数据库和加密密钥用你的备份密码加密后，定期上传到你自己的 OneDrive「应用」文件夹（只授权这一个文件夹）。")
            od.row().button("打开 OneDrive 备份") { self.push(OneDrivePage()) }

            let sv = self.card("服务器")
            sv.muted(Api.server)
            // iOS 额外入口：在 Safari 打开网页版面板
            sv.row().button("在浏览器打开网页版") {
                if let u = URL(string: Api.server), !Api.server.isEmpty { UIApplication.shared.open(u) }
            }
        }
    }
}
