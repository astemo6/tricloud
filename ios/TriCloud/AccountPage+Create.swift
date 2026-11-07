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

    private static func buildOsImageField(_ os: String, _ ver: String?, _ rows: [[String]]) -> Field {
        var opts: [String] = [], labels: [String] = []
        for o in rows {
            for i in 2..<o.count { opts.append(o[0] + "|" + o[i]); labels.append(o[1] + " " + (o[i].isEmpty ? "最新" : o[i])) }
        }
        var def = os + "|" + (ver ?? "")
        if !opts.contains(def) {
            let known = rows.contains { $0[0] == os }
            if known { opts.append(def); labels.append(os + " " + (ver ?? "")) }   // 默认值里的版本不在列表里：临时加一个选项
            else if !opts.isEmpty { def = opts[0] }                               // 已移除的系统（如 CentOS）回落到第一个
        }
        return Field.select("os_image", "系统 / 版本", def, opts, labels)
    }

    static func osImageField(_ os: String, _ ver: String?) -> Field {
        buildOsImageField(os, ver, OCI_OS)
    }

    static func osImageField(_ os: String, _ ver: String?, _ osv: [String: [String]]?) -> Field {
        guard let osv = osv, !osv.isEmpty else { return osImageField(os, ver) }
        var systems = osv.keys.filter { !(osv[$0]?.isEmpty ?? true) }
        if systems.isEmpty { return osImageField(os, ver) }
        systems.sort { a, b in
            let pa = a == "Canonical Ubuntu" ? 0 : a == "Oracle Linux" ? 1 : 2
            let pb = b == "Canonical Ubuntu" ? 0 : b == "Oracle Linux" ? 1 : 2
            if pa != pb { return pa < pb }
            return a.localizedCaseInsensitiveCompare(b) == .orderedAscending
        }
        var rows: [[String]] = []
        for sys in systems {
            let shortLabel = sys == "Canonical Ubuntu" ? "Ubuntu" : sys == "Oracle Linux" ? "Oracle Linux" : sys
            let versions = osv[sys] ?? []
            rows.append([sys, shortLabel, ""] + versions)
        }
        return buildOsImageField(os, ver, rows)
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

    /// 区域下拉字段：值为纯代码，显示带城市名（ap-northeast-1 · 东京）。
    func regionSel(_ k: String, _ label: String, _ def: String, _ a: JArr?) -> Field {
        let a = a ?? []
        let ids = (0..<a.count).map { a.string($0) }
        return Field.select(k, label, def, ids, ids.map { Regions.label($0) })
    }

    /// A1 免费额度按账号类型（与后端 core.oci_a1_free 一致）：plan_type 为 FREE_TIER → free，其他非空 → paid，未知 → unknown。
    func a1Basis() -> String {
        let raw = str(acc, "acct_type", "")
        guard !raw.isEmpty, let data = raw.data(using: .utf8),
              let t = (try? JSONSerialization.jsonObject(with: data)) as? JObj else { return "unknown" }
        let plan = str(t, "plan_type", "")
        if plan.isEmpty { return "unknown" }
        return plan == "FREE_TIER" ? "free" : "paid"
    }

    func shapeLabels() -> [String] {
        var l = AccountPage.SHAPE_LABELS
        switch a1Basis() {
        case "free": l[0] = "A1.Flex · ARM · ✅ Always Free（免费号合计 2 OCPU / 12 GB）"
        case "paid": l[0] = "A1.Flex · ARM · ✅ Always Free（PAYG 合计 4 OCPU / 24 GB）"
        default: break
        }
        return l
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

    func loadOciVersions(_ accId: Int, _ shape: String, _ region: String, _ cb: @escaping ([String: [String]]?) -> Void) {
        setBusy(true)
        Api.call("GET", "/accounts/\(accId)/oci/os-versions?shape=" + enc(shape) + (region.isEmpty ? "" : "&region=" + enc(region)), nil) { res in
            self.setBusy(false)
            var map: [String: [String]] = [:]
            switch res {
            case .success(let x):
                let obj = jobj(x)
                for (k, v) in obj {
                    if let arr = v as? [Any] {
                        let versions = arr.compactMap { jsonText($0) }
                        if !versions.isEmpty {
                            map[k] = versions
                        }
                    }
                }
            case .failure(let e):
                if let ae = e as? ApiError, ae.code == 401 { self.toLogin(); return }
            }
            cb(map.isEmpty ? nil : map)
        }
    }

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

    /// build 38：脚本模板改多选（与 Web loginFields 一致，后端按序拼接）；defIds 为默认值里的预选。
    static func scriptFields(_ ids: [String], _ names: [String], _ key: String, _ defIds: [String] = []) -> [Field] {
        var def = ""
        if !defIds.isEmpty, let data = try? JSONSerialization.data(withJSONObject: defIds),
           let s = String(data: data, encoding: .utf8) { def = s }
        return [Field.multiselect("script_ids", "开机脚本模板", def, ids, names),
         Field.multi(key, "或直接填写开机脚本（以 root 执行，日志在 /root/tricloud-init.log，可选）", "")]
    }

    static func strArr(_ o: JObj, _ k: String) -> [String] {
        guard let a = o[k] as? [Any] else { return [] }
        return a.compactMap { x in (x as? String) ?? (x as? NSNumber)?.stringValue }
    }

    static func trimNum(_ x: Double) -> String { x == x.rounded() ? String(Int(x)) : String(x) }

    /// build 38：EC2 机型下拉带规格 + 官方月价（与 Web 同源 specs），最低价标「最便宜」，末尾附手动输入项（与 type_custom 字段配合）。
    func ec2TypeField(_ o: JObj, _ d: JObj) -> Field {
        let types = o.optJSONArray("types")
        let specs = o.optJSONObject("specs") ?? [:]
        guard let types = types, types.count > 0 else { return Field.text("type", "实例类型", d.optString("type", "t3.micro")) }
        var cheap = "", best = Double.greatestFiniteMagnitude
        for i in 0..<types.count {
            let m = specs.optJSONObject(types.string(i))?.optDouble("monthly", 0) ?? 0
            if m > 0 && m < best { best = m; cheap = types.string(i) }
        }
        var ids: [String] = [], labels: [String] = []
        for i in 0..<types.count {
            let tp = types.string(i)
            var lb = tp
            if let s = specs.optJSONObject(tp) {
                if s.optDouble("vcpu", 0) > 0 { lb += " · " + AccountPage.trimNum(s.optDouble("vcpu")) + "C/" + AccountPage.trimNum(s.optDouble("ram")) + "G" }
                let m = s.optDouble("monthly", 0)
                if m > 0 { lb += " · ≈$" + AccountPage.trimNum(m) + "/月" }
            }
            if tp == cheap { lb += " · 最便宜" }
            ids.append(tp); labels.append(lb)
        }
        ids.append("__custom__"); labels.append("手动输入其他机型…")
        return Field.select("type", "实例类型", d.optString("type", "t3.micro"), ids, labels)
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
            for k in ["name", "interval", "max_attempts", "script", "user_data", "password_login", "region", "location_hint"] { d.removeValue(forKey: k) }
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
            var f: [Field] = []
            f.append(Field.text("name", "名称", "ec2-" + base36Now()))
            f.append(self.ec2TypeField(o, d))
            f.append(Field.text("type_custom", "自定义机型", ""))
            f.append(self.sel("os", "系统", d.optString("os"), o.optJSONArray("os"), false))
            f.append(Field.num("disk_gb", "系统盘 GB (gp3)", d.optString("disk_gb", "8")))
            f.append(Field.text("ports", "额外放行端口（默认只开 22）", d.optString("ports", "")))
            f.append(Field.check("password_login", "生成随机 root 密码（加密保存，可在「开机密码」查看）", true))
            self.loadScripts { ids, names in
            f += AccountPage.scriptFields(ids, names, "script", AccountPage.strArr(d, "script_ids"))
            f.append(AccountPage.saveDefaultField("AWS"))
            self.form("创建 EC2（" + Regions.label(self.region()) + "）", nil, f, "创建") { v in
                var b = self.handleSaveDefault("aws", v)
                if b.optString("type") == "__custom__" { b["type"] = b.optString("type_custom") }
                b.removeValue(forKey: "type_custom")
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
            f.append(self.regionSel("location", "区域", Prefs.get("azloc_\(self.id)", d.optString("location", "eastasia")), jarr(r)))
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
                f += AccountPage.scriptFields(ids, names, "script", AccountPage.strArr(d, "script_ids"))
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

    // build 38：与 Web/官网同逻辑——先定套餐类型 + 网络，规格只列两者都匹配的（后端已标注 family / ipv6_only）
    func lightsailCreate() {
        get("/accounts/\(id)/lightsail/options?" + rq()) { r in
            let o = jobj(r)
            let d = self.defaults.optJSONObject("lightsail") ?? [:]
            let bundles = o.optJSONArray("bundles")
            var dFam = d.optString("family", ""), dIp = d.optString("ip_type", "")
            if let bundles = bundles {
                for i in 0..<bundles.count {
                    let b0 = bundles.obj(i)
                    if b0.optString("id") == d.optString("bundle") {
                        if dFam.isEmpty { dFam = b0.optString("family", "general") }
                        if dIp.isEmpty { dIp = b0.optBoolean("ipv6_only") ? "ipv6" : "dualstack" }
                        break
                    }
                }
            }
            if dFam.isEmpty { dFam = "general" }
            if dIp.isEmpty { dIp = "dualstack" }
            var f1: [Field] = []
            f1.append(Field.text("name", "名称", "ls-" + base36Now()))
            f1.append(self.regionSel("zone", "可用区", d.optString("zone"), o.optJSONArray("zones")))
            f1.append(self.sel("blueprint", "系统镜像", d.optString("blueprint"), o.optJSONArray("blueprints"), true))
            f1.append(Field.select("family", "套餐类型", dFam, ["general", "memory", "compute"], ["通用型", "内存型", "计算型"]))
            f1.append(Field.select("ip_type", "网络", dIp, ["dualstack", "ipv6"], ["IPv4 + IPv6", "仅 IPv6"]))
            self.form("创建 Lightsail", nil, f1, "下一步") { v1 in
                var filt: [(String, String)] = []
                let v6 = v1.optString("ip_type") == "ipv6"
                if let bundles = bundles {
                    for i in 0..<bundles.count {
                        let b0 = bundles.obj(i)
                        if b0.optString("family", "general") == v1.optString("family") && b0.optBoolean("ipv6_only") == v6 {
                            filt.append((b0.optString("id"), b0.optString("name")))
                        }
                    }
                }
                if filt.isEmpty { self.toast("暂无数据"); return }
                self.loadScripts { ids, names in
                    var f: [Field] = []
                    f.append(Field.select("bundle", "套餐", d.optString("bundle"), filt.map { $0.0 }, filt.map { $0.1 }))
                    f.append(Field.check("password_login", "生成随机 root 密码（加密保存，可在「开机密码」查看）", true))
                    f += AccountPage.scriptFields(ids, names, "user_data", AccountPage.strArr(d, "script_ids"))
                    f.append(AccountPage.saveDefaultField("Lightsail"))
                    self.form("创建 Lightsail", nil, f, "创建") { v in
                        var merged = v1
                        for (k2, val) in v { merged[k2] = val }
                        var b = self.handleSaveDefault("lightsail", merged)
                        b["region"] = self.region()
                        self.post("/accounts/\(self.id)/lightsail/create", b) { x in
                            self.created(jobj(x))
                            self.later(3) { self.refresh() }
                        }
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
        let basis = a1Basis()
        let a1Note: String = basis == "paid" ? "PAYG 账号 4 OCPU / 24 GB" : basis == "free" ? "免费号 2 OCPU / 12 GB（2026-06 起）"
            : "免费号 2 OCPU / 12 GB，PAYG 4 OCPU / 24 GB（未识别账号类型，可在右上角「账号类型」刷新）"
        c.muted("A1 免费额度：" + a1Note + "，超出部分计费。")
        let freeA1 = basis != "paid"   // 免费号 / 未知按 2 OCPU / 12 GB 给默认值

        func buildMainFields(_ curD: JObj, _ osv: [String: [String]]?) -> [Field] {
            var f: [Field] = [
                Field.text("name", "实例名称", "oci-" + base36Now()),
                Field.num("ocpus", "OCPU", curD.optString("ocpus", freeA1 ? "2" : "4")),
                Field.num("memory_gb", "内存 GB", curD.optString("memory_gb", freeA1 ? "12" : "24")),
                Field.num("disk_gb", "引导卷 GB", curD.optString("disk_gb", "50")),
                AccountPage.osImageField(curD.optString("os", "Canonical Ubuntu"), str(curD, "os_version", ""), osv),
                Field.text("ad", "可用域（留空=第一个）", str(curD, "ad", "")),
                Field.text("subnet_id", "子网 OCID（留空=自动）", str(curD, "subnet_id", "")),
                Field.multi("ssh_key", "SSH 公钥", str(curD, "ssh_key", "")),
                Field.check("ipv6", "分配 IPv6", curD.optBoolean("ipv6", false)),
                Field.check("password_login", "生成随机 root 密码（加密保存，可在「开机密码」查看）", true)]
            if snatch {
                f.append(Field.num("interval", "重试间隔秒（≥30）", "60"))
                f.append(Field.num("max_attempts", "最大次数（0=不限）", "0"))
            }
            return f
        }

        c.row().button(snatch ? "填写参数并开始抢机" : "填写参数并创建") {
            let curD = self.defaults.optJSONObject("oci") ?? [:]
            self.form(snatch ? "抢机参数" : "创建参数", nil,
                      [Field.select("shape", "规格", curD.optString("shape", AccountPage.SHAPES[0]), AccountPage.SHAPES, self.shapeLabels())],
                      "下一步") { sVals in
                let shape = sVals.optString("shape", AccountPage.SHAPES[0])
                self.loadOciVersions(self.id, shape, self.region()) { osv in
                    self.loadScripts { ids, names in
                        let all = buildMainFields(curD, osv) + AccountPage.scriptFields(ids, names, "script", AccountPage.strArr(curD, "script_ids")) + [AccountPage.saveDefaultField("OCI")]
                        self.form(snatch ? "抢机参数" : "创建参数", nil, all, snatch ? "开始" : "创建") { vals0 in
                            var v0 = vals0
                            v0["shape"] = shape
                            let vals = self.handleSaveDefault("oci", AccountPage.splitOsImage(v0))
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
