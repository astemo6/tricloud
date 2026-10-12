import SwiftUI

// AccountActivity：EC2 / Azure VM / Lightsail 创建，OCI 创建与抢机。

extension AccountPage {
    // 规格标明是否 Always Free（免费额度只在主区域有效）
    static let SHAPES = ["VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro", "VM.Standard.E4.Flex", "VM.Standard3.Flex"]
    static let SHAPE_LABELS = [
        "A1.Flex · ARM · ✅ Always Free（免费号合计 2 OCPU / 12 GB，付费号 4 / 24）",
        "E2.1.Micro · AMD 1/8 OCPU · 1 GB · ✅ Always Free（最多 2 台）",
        "E4.Flex · AMD · 💰 付费，非 Always Free",
        "Standard3.Flex · Intel · 💰 付费，非 Always Free"]

    // v1.5：OCI「系统 + 版本」—— 列出全部组合（如「Ubuntu 22.04」），提交时拆成 os / os_version（"" = 最新）
    static let OCI_OS: [[String]] = [["Canonical Ubuntu", "Ubuntu", "", "24.04", "22.04", "20.04"], ["Oracle Linux", "Oracle Linux", "", "9", "8"]]

    static func osImageField(_ os: String, _ ver: String?) -> Field {
        var opts: [String] = [], labels: [String] = []
        for o in OCI_OS {
            for i in 2..<o.count { opts.append(o[0] + "|" + o[i]); labels.append(o[1] + " " + (o[i].isEmpty ? "最新" : o[i])) }
        }
        var def = os + "|" + (ver ?? "")
        if !opts.contains(def) {
            let known = OCI_OS.contains { $0[0] == os }
            if known { opts.append(def); labels.append(os + " " + (ver ?? "")) }   // 默认值里的版本不在列表里：临时加一个选项
            else { def = opts[0] }                                                // 已移除的系统（如 CentOS）回落到 Ubuntu 最新
        }
        return Field.select("os_image", "系统 / 版本", def, opts, labels)
    }

    static func splitOsImage(_ c: JObj) -> JObj {
        var c = c
        if let v = c.removeValue(forKey: "os_image") {
            let s = jsonText(v) ?? ""
            if let r = s.range(of: "|") {
                c["os"] = String(s[s.startIndex..<r.lowerBound])
                c["os_version"] = String(s[r.upperBound...])
            } else {
                c["os"] = s
                c["os_version"] = ""
            }
        }
        return c
    }

    func sel(_ k: String, _ label: String, _ def: String, _ a: JArr?, _ objs: Bool) -> Field {
        let a = a ?? []
        var ids: [String] = [], labels: [String] = []
        for i in 0..<a.count {
            if objs { ids.append(a.obj(i).optString("id")); labels.append(a.obj(i).optString("name")) }
            else { ids.append(a.string(i)); labels.append(a.string(i)) }
        }
        return Field.select(k, label, def, ids, labels)
    }

    // MARK: - 开机脚本模板 / 保存为默认（与 Web loginFields、saveDefaultBtn 一致）

    func loadScripts(_ cb: @escaping ([String], [String]) -> Void) {
        Api.call("GET", "/scripts", nil) { res in
            var ids: [String] = [], names: [String] = []
            if case .success(let x) = res {
                let a = jarr(x)
                for i in 0..<a.count { ids.append(a.obj(i).optString("id")); names.append(a.obj(i).optString("name")) }
            }
            cb(ids, names)
        }
    }

    static func scriptFields(_ ids: [String], _ names: [String], _ key: String) -> [Field] {
        [Field.select("script_id", "开机脚本模板", "", [""] + ids, ["不使用模板"] + names),
         Field.multi(key, "或直接填写开机脚本（以 root 执行，日志在 /root/tricloud-init.log，可选）", "")]
    }

    static func saveDefaultField(_ cloud: String) -> Field {
        Field.check("save_default", "把本次参数保存为 " + cloud + " 创建默认值（不含名称、密码、脚本）", false)
    }

    /// 勾选了「保存为默认」时 PUT /create-defaults；返回去掉该开关后的表单值。
    func handleSaveDefault(_ provider: String, _ v: JObj) -> JObj {
        var vals = v
        let save = (vals.removeValue(forKey: "save_default") as? Bool) ?? false
        if save {
            var d = vals
            for k in ["name", "interval", "max_attempts", "script", "script_id", "user_data", "password_login", "region", "location_hint"] { d.removeValue(forKey: k) }
            request("PUT", "/create-defaults", ["provider": provider, "defaults": d]) { r in
                let nd = jobj(r).optJSONObject("defaults") ?? d
                self.defaults[provider] = nd
                self.toast("已保存为默认值")
            }
        }
        return vals
    }

    // MARK: - v1.5：EC2 / Azure VM 创建

    func ec2Create() {
        get("/accounts/\(id)/aws/ec2-options") { r in
            let o = jobj(r)
            let d = self.defaults.optJSONObject("aws") ?? [:]
            let types = o.optJSONArray("types")
            var f: [Field] = []
            f.append(Field.text("name", "名称", "ec2-" + base36Now()))
            f.append((types?.count ?? 0) > 0 ? self.sel("type", "实例类型", d.optString("type", "t3.micro"), types, false)
                     : Field.text("type", "实例类型", d.optString("type", "t3.micro")))
            f.append(self.sel("os", "系统", d.optString("os"), o.optJSONArray("os"), false))
            f.append(Field.num("disk_gb", "系统盘 GB (gp3)", d.optString("disk_gb", "10")))
            f.append(Field.text("ports", "额外放行端口（默认只开 22）", d.optString("ports", "")))
            f.append(Field.check("password_login", "生成随机 root 密码（加密保存，可在「开机密码」查看）", true))
            self.loadScripts { ids, names in
            f += AccountPage.scriptFields(ids, names, "script")
            f.append(AccountPage.saveDefaultField("AWS"))
            self.form("创建 EC2（" + self.region() + "）", nil, f, "创建") { v in
                var b = self.handleSaveDefault("aws", v)
                b["region"] = self.region()
                self.post("/accounts/\(self.id)/aws/ec2-create", b) { x in
                    self.created(jobj(x))
                    self.later(4) { self.refresh() }
                }
            }
            }
        }
    }

    func azureCreate() {
        get("/accounts/\(id)/azure/locations") { r in
            let d = self.defaults.optJSONObject("azure") ?? [:]
            var f: [Field] = []
            f.append(Field.text("name", "名称", "vm-" + base36Now()))
            f.append(self.sel("location", "区域", Prefs.get("azloc_\(self.id)", d.optString("location", "eastasia")), jarr(r), false))
            f.append(Field.text("size", "大小", d.optString("size", "Standard_B1s")))
            f.append(Field.select("os", "系统", d.optString("os", "debian-12"), ["debian-12", "ubuntu-24.04", "ubuntu-22.04"], nil))
            f.append(Field.num("disk_gb", "系统盘 GB", d.optString("disk_gb", "30")))
            f.append(Field.select("disk_type", "磁盘类型", "StandardSSD_LRS", ["StandardSSD_LRS", "Standard_LRS", "Premium_LRS"], nil))
            f.append(Field.text("resource_group", "资源组（留空=新建）", ""))
            f.append(Field.text("ports", "额外放行端口（默认只开 22）", ""))
            f.append(Field.check("ipv6", "同时分配公网 IPv6", false))
            f.append(Field.multi("ssh_key", "SSH 公钥（可选）", d.optString("ssh_key", "")))
            f.append(Field.check("password_login", "生成随机密码（加密保存，可在「开机密码」查看）", true))
            self.loadScripts { ids, names in
                f += AccountPage.scriptFields(ids, names, "script")
                f.append(AccountPage.saveDefaultField("Azure"))
                self.form("创建 Azure VM", "学生订阅免费额度：B1s 750 小时/月 + 2×64GB P6 SSD。创建约 2–4 分钟，后台执行并推送通知。", f, "创建") { v in
                    let b = self.handleSaveDefault("azure", v)
                    Prefs.set("azloc_\(self.id)", b.optString("location"))
                    self.post("/accounts/\(self.id)/azure/create", b) { x in self.taskOrToast(x, "已提交，完成后可在「开机密码」查看密码") }
                }
            }
        }
    }

    // MARK: - Lightsail 创建

    func lightsailCreate() {
        get("/accounts/\(id)/lightsail/options?" + rq()) { r in
            let o = jobj(r)
            let d = self.defaults.optJSONObject("lightsail") ?? [:]
            var f: [Field] = []
            f.append(Field.text("name", "名称", "ls-" + base36Now()))
            f.append(self.sel("zone", "可用区", d.optString("zone"), o.optJSONArray("zones"), false))
            f.append(self.sel("blueprint", "系统镜像", d.optString("blueprint"), o.optJSONArray("blueprints"), true))
            f.append(self.sel("bundle", "套餐", d.optString("bundle"), o.optJSONArray("bundles"), true))
            f.append(Field.select("ip_type", "网络", "dualstack", ["dualstack", "ipv6"], ["IPv4 + IPv6", "仅 IPv6"]))
            f.append(Field.check("password_login", "生成随机 root 密码（加密保存，可在「开机密码」查看）", true))
            self.loadScripts { ids, names in
                f += AccountPage.scriptFields(ids, names, "user_data")
                f.append(AccountPage.saveDefaultField("Lightsail"))
                self.form("创建 Lightsail", nil, f, "创建") { v in
                    var b = self.handleSaveDefault("lightsail", v)
                    b["region"] = self.region()
                    self.post("/accounts/\(self.id)/lightsail/create", b) { x in
                        self.created(jobj(x))
                        self.later(3) { self.refresh() }
                    }
                }
            }
        }
    }

    // MARK: - OCI 创建 / 抢机

    func ociCreate(_ snatch: Bool) {
        let d = defaults.optJSONObject("oci") ?? [:]
        let c = card(snatch ? "自动抢机" : "创建实例")
        c.muted(snatch ? "容量不足时按间隔重试，成功/失败/停止推送 Telegram。" : "默认值来自 设置 → 默认创建参数")
        var f: [Field] = [
            Field.text("name", "实例名称", "oci-" + base36Now()),
            Field.select("shape", "规格", d.optString("shape", AccountPage.SHAPES[0]), AccountPage.SHAPES, AccountPage.SHAPE_LABELS),
            Field.num("ocpus", "OCPU", d.optString("ocpus", "4")),
            Field.num("memory_gb", "内存 GB", d.optString("memory_gb", "24")),
            Field.num("disk_gb", "引导卷 GB", d.optString("disk_gb", "50")),
            AccountPage.osImageField(d.optString("os", "Canonical Ubuntu"), str(d, "os_version", "")),
            Field.text("ad", "可用域（留空=第一个）", str(d, "ad", "")),
            Field.text("subnet_id", "子网 OCID（留空=自动）", str(d, "subnet_id", "")),
            Field.multi("ssh_key", "SSH 公钥", str(d, "ssh_key", "")),
            Field.check("ipv6", "分配 IPv6", d.optBoolean("ipv6", false)),
            Field.check("password_login", "生成随机 root 密码（加密保存，可在「开机密码」查看）", true)]
        if snatch {
            f.append(Field.num("interval", "重试间隔秒（≥30）", "60"))
            f.append(Field.num("max_attempts", "最大次数（0=不限）", "0"))
        }
        let fields = f
        c.row().button(snatch ? "填写参数并开始抢机" : "填写参数并创建") {
            self.loadScripts { ids, names in
            let all = fields + AccountPage.scriptFields(ids, names, "script") + [AccountPage.saveDefaultField("OCI")]
            self.form(snatch ? "抢机参数" : "创建参数", nil, all, snatch ? "开始" : "创建") { vals0 in
                let vals = self.handleSaveDefault("oci", AccountPage.splitOsImage(vals0))
                var create = vals
                let interval = create.removeValue(forKey: "interval")
                let maxa = create.removeValue(forKey: "max_attempts")
                var b: JObj = ["region": self.region(), "create": create]
                if snatch {
                    b["interval"] = interval
                    b["max_attempts"] = maxa
                    self.post("/accounts/\(self.id)/oci/snatch", b) { x in self.taskOrToast(x, "抢机任务已启动") }
                } else {
                    self.post("/accounts/\(self.id)/oci/create", b) { x in self.created(jobj(x)) }
                }
            }
            }
        }
    }

    /// 创建成功：随机密码只显示这一次。
    func created(_ o: JObj) {
        let pw = o.optString("password", "")
        if pw.isEmpty || pw == "null" { toast("已提交创建：" + o.optString("name")); return }
        message("创建已提交：" + o.optString("name"),
                "用户：" + o.optString("username") + "\n密码：" + pw + "\n\n只显示这一次，之后可在「更多 → 开机密码」输入面板密码查看。",
                primary: ("复制密码", { copyText(pw); self.toast("已复制") }), cancel: "关闭")
    }
}
