import SwiftUI

// build 30：OCI 一键切换受限 API（对应 Web accounts.js restrictDialog / Android AccountsActivity.restrictFlow）。
// 流程：状态 → 强确认（说明云端原 Key 不删除不撤销、几分钟生效可关闭窗口、切换后不能管理 IAM / 身份域）
// → 发 Telegram 验证码 → 勾选「已保存原 Key」+ 输入 6 位验证码 → 后台任务（打开任务日志看进度）。

extension Page {
    func restrictFlow(_ acc: JObj) {
        let aid = acc.optInt("id")
        get("/accounts/\(aid)/oci/restrict") { r in
            let s = jobj(r)
            if let info = s["restricted"] as? JObj {
                let at = info.optLong("at")
                let lines = [
                    L("用户") + "：" + str(info, "user_name", "-"),
                    L("组") + "：" + str(info, "group_name", "-"),
                    L("策略") + "：" + str(info, "policy_name", "-"),
                    L("指纹") + "：" + str(info, "fingerprint", "-"),
                    L("切换时间") + "：" + (at > 0 ? fmtTime(at) : "-"),
                    "",
                    L("OCI 云端原 API Key 仍然保留（面板没有删除或撤销）。如需恢复全权限，在「编辑」里重新填入原 Key 即可（受限标记会自动去掉）。"),
                ]
                self.message(L("受限 API"), lines.joined(separator: "\n"))
                return
            }
            if let t = s["task"] as? JObj, t.optString("status") == "running" {
                self.toast(L("切换任务正在进行中"))
                self.openTask(t.optInt("id"))
                return
            }
            if !s.optBoolean("tg_bound") {
                self.message(L("切换为受限 API"), L("切换受限 API 需要 Telegram 验证码。请先在「设置 → Telegram 通知」填写 Bot Token 和 Chat ID。"))
                return
            }
            let arr = s.optJSONArray("statements") ?? []
            let stm = (0..<arr.count).map { arr.string($0) }.joined(separator: "\n")
            var msg = L("将用当前的全权限 API Key，在 OCI 租户根区间创建一个受限用户（组 + 策略 + 用户，名字带 TriCloud 前缀），生成新的 API Key，自检通过后把面板保存的 Key 换成受限 Key。即使面板所在服务器被攻破，拿到的也只是受限 Key。")
            msg += "\n\n• " + L("不会删除或撤销 OCI 云端原来的 API Key，其他程序仍可使用；面板会删除本地保存的旧私钥，请务必自己保存好原全权限 Key。")
            msg += "\n• " + L("新 Key 生效可能需要几分钟（最多约 10 分钟），后台任务执行，期间可以关闭窗口。")
            msg += "\n• " + L("切换后面板不能再管理 IAM / 身份域（用户、组、策略），也不能订阅新区域；这些请在 OCI 控制台用全权限账号操作。")
            msg += "\n• " + L("失败会自动回滚（删除本次创建的用户 / 组 / 策略 / 新 Key），面板里的凭证保持不变。仅支持 Default 域、有 IAM 管理权限的用户。")
            if let t = s["task"] as? JObj, t.optString("status") != "done" {
                msg += "\n\n" + L("上次切换") + " #\(t.optInt("id"))：" + t.optString("message")
            }
            msg += "\n\n" + L("将创建的策略：") + "\n" + stm
            self.message(L("切换为受限 API"), msg, primary: ("发送 Telegram 验证码", { self.restrictSendCode(aid) }), cancel: "取消")
        }
    }

    private func restrictSendCode(_ aid: Int) {
        post("/accounts/\(aid)/oci/restrict/code", [:]) { _ in
            self.form("输入 Telegram 验证码", "已发送到 Telegram，5 分钟内有效，只能用一次。",
                      [Field.check("kept", "我已自己保存好原来的全权限 API Key", false), Field.num("code", "Telegram 验证码（6 位数字）", "")],
                      "开始切换") { v in
                let code = v.optString("code")
                guard (v["kept"] as? Bool) == true else { self.toast(L("请先确认已保存原全权限 API Key")); return }
                guard code.count == 6, code.allSatisfy({ $0.isASCII && $0.isNumber }) else { self.toast(L("请输入 6 位 Telegram 验证码")); return }
                self.post("/accounts/\(aid)/oci/restrict", ["code": code, "confirm": true]) { r in
                    self.toast(L("已开始切换，可以关闭窗口，进度见任务日志"))
                    self.accountsChanged()
                    self.openTask(jobj(r).optInt("task_id"))
                }
            }
        }
    }
}
