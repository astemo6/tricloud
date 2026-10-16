import SwiftUI

/// 单个云账号：与 Web 端相同的标签页。对应 AccountActivity（实例 / 操作部分）。
/// 其余标签见 AccountPage+Create / +AWS / +OCI / +Billing / +Azure / +Migrate。
final class AccountPage: Page {
    var acc: JObj
    let prov: String
    let id: Int
    var tab: String
    var defaults: JObj = [:]
    var fdRegion = "swedencentral"
    /// build 19：Lightsail 支持的区域（GET /regions?service=lightsail，成功才缓存）。
    var lsRegs: [String]?
    /// build 19：安全组按子网选择（记住上次子网）。
    var sgSub: String?
    /// 对象存储：当前 Bucket 与前缀（nil = Bucket 列表）。
    var objBucket: String?
    var objPrefix = ""
    /// 安全组规则筛选（切换实例 / 刷新后保留）。
    let sgFilter = SgFilter()
    /// 切换标签 / 刷新时递增，丢弃过期的异步回调。
    var gen = 0

    // 与 Web 端 TABS 一致
    static func tabs(_ p: String) -> [(String, String)] {
        switch p {
        case "oci": return [("instances", "实例"), ("create", "创建实例"), ("snatch", "自动抢机"), ("secgroup", "安全组"), ("storage", "存储"),
                            ("objects", "对象存储"), ("traffic", "流量"), ("limits", "配额/网络"), ("billing", "账单")]   // 区域订阅收在「配额/网络」底部的二级入口（防误点）
        case "aws": return [("ec2", "EC2"), ("lightsail", "Lightsail"), ("regions", "区域"), ("cloudfront", "CloudFront"), ("quota", "配额"),
                            ("recycle", "闲置资源"), ("billing", "账单")]
        default: return [("vms", "虚拟机"), ("azcreate", "创建 VM"), ("rgs", "资源组"), ("azquota", "配额"), ("foundry", "Foundry"),
                         ("subscription", "订阅"), ("billing", "账单")]
        }
    }

    override var menu: [(String, () -> Void)] {
        return [("测活", { self.testNow() }),
         ("账号类型", { self.accountType(false) }),
         ("账号信息 / 日期", { self.accountInfo() })]
    }

    init(_ acc: JObj) {
        self.acc = acc
        prov = acc.optString("provider")
        id = acc.optInt("id")
        tab = Prefs.get("tab_\(acc.optInt("id"))", AccountPage.tabs(acc.optString("provider"))[0].0)
        super.init()
        if tab == "regionsub" { tab = "limits" }   // build 18 起区域订阅不再是单独标签
        if !AccountPage.tabs(prov).contains(where: { $0.0 == tab }) { tab = AccountPage.tabs(prov)[0].0 }
        title = MainPage.pname(prov) + " · " + acc.optString("name")
    }

    override func appeared() {
        if !started {
            started = true
            get("/settings") { r in self.defaults = jobj(r).optJSONObject("default_create") ?? [:] }
            refresh()
        }
    }

    func region() -> String { Prefs.get("region_\(id)", str(acc, "region", "")) }
    func rq() -> String { prov == "azure" ? "" : "region=" + enc(region()) }
    func base(_ inst: JObj, _ kind: String) -> JObj {
        ["instance_id": inst.optString("id"), "region": region(), "kind": kind, "name": inst.optString("name")]
    }

    func header() {
        clear()
        chips(AccountPage.tabs(prov), tab) { t in
            if t == self.tab { return }
            self.tab = t
            Prefs.set("tab_\(self.id)", t)
            self.refresh()
        }
        if prov != "azure" && !["cloudfront", "quota", "billing", "subscription", "regions"].contains(tab) {
            nav("globe.asia.australia.fill", "区域", Regions.label(region()), tint: .teal) { self.pickRegion() }
        }
    }

    func pickRegion() {
        if tab == "lightsail" {   // build 19：Lightsail 只列它支持的区域（如台北 ap-east-2 没有）
            withLsRegions { rs in self.pickRegion(rs) }
            return
        }
        get("/accounts/\(id)/regions") { x in
            let a = jarr(x)
            self.pickRegion((0..<a.count).map { a.string($0) })
        }
    }

    /// GET /regions?service=lightsail（账号已启用 ∩ Lightsail 支持）；失败回调空数组（不做过滤）。
    func withLsRegions(_ cb: @escaping ([String]) -> Void) {
        if let l = lsRegs { cb(l); return }
        setBusy(true)
        Api.call("GET", "/accounts/\(id)/regions?service=lightsail", nil) { res in
            self.setBusy(false)
            var l: [String] = []
            switch res {
            case .success(let x):
                let a = jarr(x)
                l = (0..<a.count).map { a.string($0) }
                if !l.isEmpty { self.lsRegs = l }
            case .failure(let e):
                if let ae = e as? ApiError, ae.code == 401 { self.toLogin(); return }
            }
            cb(l)
        }
    }

    /// 当前保存的区域 Lightsail 不支持时：切到账号默认区域（若支持）或第一个可用区域，并提示。
    func lsEnsure(_ then: @escaping () -> Void) {
        let g = gen
        withLsRegions { l in
            guard self.cur(g), self.tab == "lightsail" else { return }
            let curR = self.region()
            if !l.isEmpty && !l.contains(curR) {
                let def = str(self.acc, "region", "")
                let to = l.contains(def) ? def : l[0]
                Prefs.set("region_\(self.id)", to)
                self.toast("Lightsail 不支持 " + Regions.label(curR) + "，已切换到 " + Regions.label(to))
                self.header()
            }
            then()
        }
    }

    func pickRegion(_ rs: [String]) {
        if rs.isEmpty { toast("没有可选区域"); return }
        choose("选择区域（当前 " + Regions.label(region()) + "）", rs.map { Regions.label($0) }) { i in
            Prefs.set("region_\(self.id)", rs[i])
            self.objBucket = nil
            self.objPrefix = ""
            self.refresh()
        }
    }

    /// 当前回调是否仍属于正在显示的标签（切换标签后丢弃旧结果）。
    func cur(_ g: Int) -> Bool { g == gen }

    func testNow() {
        post("/accounts/\(id)/test", nil) { x in
            let o = jobj(x)
            self.toast(o.optBoolean("ok") ? "✅ 连通 · \(o.optInt("ms")) ms" : "❌ " + str(o, "error", "失败"))
        }
    }

    override func refresh() {
        gen += 1
        header()
        switch tab {
        case "instances", "ec2", "vms": instances("vm")
        case "lightsail": lsEnsure { self.instances("lightsail") }
        case "create": ociCreate(false)
        case "snatch": ociCreate(true)
        case "cloudfront": cloudfront()
        case "quota": quota(false)
        case "recycle": recycle()
        case "billing": billing(false)
        case "subscription": subscription()
        case "foundry": foundry()
        case "secgroup": secgroup()
        case "traffic": ociTraffic()
        case "storage": ociStorage()
        case "objects": ociObjects()
        case "limits": ociLimits()
        case "regions": awsRegions(false)
        case "azcreate": azCreateTab()
        case "rgs": azRgs()
        case "azquota": azQuota()
        default: break
        }
    }

    // MARK: - 实例

    func instances(_ kind: String) {
        if kind == "lightsail" { bigButton("＋ 创建 Lightsail") { self.lightsailCreate() } }
        if prov == "aws" && kind == "vm" { bigButton("＋ 创建 EC2") { self.ec2Create() } }
        if prov == "azure" { bigButton("＋ 创建 Azure VM") { self.azureCreate() } }
        let g = gen
        get("/accounts/\(id)/instances?kind=\(kind)&" + rq()) { r in
            guard self.cur(g) else { return }
            let a = jarr(r)
            if a.isEmpty { self.card(self.prov == "azure" ? "订阅里没有虚拟机" : "该区域没有实例").muted(self.prov == "azure" ? "" : Regions.label(self.region())) }
            for i in 0..<a.count { self.instCard(a.obj(i), kind) }
            if kind == "lightsail" { self.lsStaticIps(a) }
        }
    }

    func instCard(_ inst: JObj, _ kind: String) {
        let c = card(inst.optString("name") + "  [" + inst.optString("state") + "]")
        let v6 = inst.optJSONArray("ipv6")
        let spec = prov == "oci" ? inst.optString("shape") + " " + str(inst, "ocpus", "?") + "C/" + str(inst, "memory_gb", "?") + "G" : inst.optString("shape")
        c.text("公网 IP：" + str(inst, "public_ip", "-") + "\n内网 IP：" + str(inst, "private_ip", "-")
               + "\nIPv6：" + ((v6?.count ?? 0) > 0 ? join(v6) : "-")
               + "\n规格：" + spec + "\n可用区：" + Regions.label(str(inst, "zone", "-")), 13)
        if kind == "lightsail" { c.muted("镜像 " + str(inst, "blueprint", "-") + " · 静态 IP " + (inst.optBoolean("static_ip") ? "是" : "否")) }
        if prov == "azure" && !inst.isNull("resource_group") { c.muted("资源组 " + inst.optString("resource_group")) }
        let r = c.row()
        r.button("启动") { self.simple(inst, kind, "start", "启动") }
        r.button(prov == "azure" ? "停止(释放)" : "停止") { self.simple(inst, kind, "stop", "停止") }
        r.button("重启") { self.simple(inst, kind, "reboot", "重启") }
        r.button("换 IP") { self.changeIp(inst, kind) }
        r.menu("更多操作", moreOps(inst, kind))
    }

    /// 次要操作收进「更多」菜单（与 Web 端「更多 ▾」同样的顺序）。
    func moreOps(_ inst: JObj, _ kind: String) -> [(String, () -> Void)] {
        var more: [(String, () -> Void)] = []
        if prov == "oci" {
            more.append(("加 IPv6", {
                self.confirm("一键 IPv6", "将按需为所在 VCN 开启 IPv6、给子网分配 /64、添加 ::/0 路由和出站规则，再给实例分配 IPv6。确定？") {
                    self.post("/accounts/\(self.id)/oci/ipv6", self.base(inst, kind)) { x in self.taskOrToast(x, "已提交") }
                }
            }))
            more.append(("删 IPv6", {
                self.confirm("删除 IPv6", "⚠️ 将删除「" + inst.optString("name") + "」主网卡上的全部 IPv6 地址（VCN / 子网配置保留）。") {
                    var b = self.base(inst, kind)
                    b["confirm"] = true
                    self.post("/accounts/\(self.id)/oci/ipv6/delete", b) { x in
                        self.toast("已删除：" + join(jobj(x).optJSONArray("deleted")))
                        self.refresh()
                    }
                }
            }))
            more.append(("改配置", { self.resizeOci(inst) }))
        }
        if kind != "lightsail" { more.append(("改名", { self.rename(inst, kind) })) }   // v1.5：Lightsail 不支持改名
        if prov == "oci" {
            more.append(("引导卷", { self.bootVolume(inst) }))
            more.append(("附加 IP", { self.push(OciIpsPage(self, inst)) }))
            more.append(("500M 下行", { self.net500(inst, kind) }))
        }
        if kind != "lightsail" { more.append(("开放端口", { self.openPort(inst, kind) })) }
        more.append(("流量守护", { self.traffic(inst, kind) }))
        if prov == "azure" {
            more.append(("改大小", { self.resizeAzure(inst) }))
            more.append(("磁盘", { self.push(AzureDisksPage(self, inst)) }))
        }
        if kind == "lightsail" { more.append(("防火墙", { self.push(LsPortsPage(self, inst)) })) }
        if kind != "lightsail" { more.append(("迁移", { self.migrate(inst) })) }
        more.append(("绑定域名", { self.bindDns(inst) }))
        more.append(("监控", { self.monitor(inst, kind) }))
        more.append(("IP 质量", { self.ipQuality(inst) }))
        if kind != "lightsail" { more.append(("重装系统", { self.reinstall(inst, kind) })) }
        more.append((prov == "azure" || kind == "lightsail" ? "删除" : "终止", { self.simple(inst, kind, "terminate", "终止") }))
        return more
    }

    // MARK: - v1.6

    func reinstall(_ inst: JObj, _ kind: String) {
        var f: [Field] = []
        if prov == "oci" {
            f.append(Field.select("os", "系统", "Canonical Ubuntu", ["Canonical Ubuntu", "Oracle Linux"], nil))
            f.append(Field.select("os_version", "系统版本", "", ["", "24.04", "22.04", "20.04", "9", "8"],
                                  ["最新", "Ubuntu 24.04", "Ubuntu 22.04", "Ubuntu 20.04", "Oracle Linux 9", "Oracle Linux 8"]))
            f.append(Field.num("disk_gb", "新引导卷大小 GB（留空 = 与当前相同）", ""))
        } else if prov == "aws" {
            f.append(Field.select("os", "系统", "debian-12", ["debian-12", "ubuntu-24.04", "ubuntu-22.04", "al2023"],
                                  ["Debian 12", "Ubuntu 24.04", "Ubuntu 22.04", "Amazon Linux 2023"]))
        } else {
            f.append(Field.select("os", "系统", "debian-12", ["debian-12", "ubuntu-24.04", "ubuntu-22.04"], ["Debian 12", "Ubuntu 24.04", "Ubuntu 22.04"]))
        }
        if prov != "aws" { f.append(Field.check("password_login", "生成新的随机 root 密码（在「开机密码」查看）", true)) }
        f.append(Field.check("confirm", "我已确认要清空系统盘数据", false))
        form("重装系统", "⚠️ 将重装「" + inst.optString("name") + "」，系统盘上的全部数据会被清空，不可恢复。实例会停机几分钟。", f, "开始重装") { v in
            if !v.optBoolean("confirm") { self.toast("请先勾选确认"); return }
            var b = self.base(inst, kind)
            b["confirm"] = true
            for k in ["os", "os_version", "disk_gb"] where !v.optString(k).isEmpty { b[k] = v.optString(k) }
            if v.has("password_login") { b["password_login"] = v.optBoolean("password_login") }
            self.post("/accounts/\(self.id)/instances/reinstall", b) { x in self.taskOrToast(x, "已提交") }
        }
    }

    func ipQuality(_ inst: JObj) {
        let ip = inst.optString("public_ip", "")
        if ip.isEmpty || ip == "null" { toast("实例没有公网 IP"); return }
        get("/ip-quality?ip=" + ip) { r in
            let q = jobj(r)
            let risk = q.isNull("risk") ? "查询失败" : "\(q.optInt("risk"))（0~100，越低越干净）"
            self.message("IP 质量 · " + inst.optString("name"),
                         "IP：" + ip + "\n风险分：" + risk + "\n类型：" + str(q, "type", "-") + (q.optBoolean("proxy") ? "（被标记为代理/VPN）" : "")
                         + "\n归属：" + str(q, "country", "-") + " " + str(q, "country_code", "") + "\nISP：" + str(q, "isp", "-") + " " + str(q, "asn", "")
                         + "\n\n数据源：" + q.optString("source"), cancel: "关闭")
        }
    }

    func net500(_ inst: JObj, _ kind: String) {
        get("/accounts/\(id)/oci/500m?instance_id=" + enc(inst.optString("id")) + "&" + rq()) { r in
            let st = jobj(r)
            let on = st.optBoolean("enabled")
            let msg = on ? "当前已开启，入口 IP：" + st.optString("public_ip") + "\n关闭后删除负载均衡器，恢复用原公网 IP 入站。"
                : "新建网络负载均衡器（Always Free 1 个）转发全部端口，入口 IP 变成负载均衡器的公网 IP；实例改走 NAT 网关出站。账号里已有其他负载均衡器时不会动它。"
            if on {
                self.confirm("关闭下行 500Mbps", msg) {
                    var b = self.base(inst, kind)
                    b["enable"] = false
                    b["confirm"] = true
                    self.post("/accounts/\(self.id)/oci/500m", b) { x in self.taskOrToast(x, "已提交") }
                }
                return
            }
            self.form("开启下行 500Mbps", msg, [Field.num("ssh_port", "健康检查端口（SSH 端口）", "22")], "开启") { v in
                var b = self.base(inst, kind)
                b["enable"] = true
                b["confirm"] = true
                b["ssh_port"] = v.optString("ssh_port", "22")
                self.post("/accounts/\(self.id)/oci/500m", b) { x in self.taskOrToast(x, "已提交，完成后会推送新的入口 IP") }
            }
        }
    }

    func simple(_ inst: JObj, _ kind: String, _ act: String, _ label: String) {
        if act == "terminate" && prov == "oci" {
            form("终止实例", "⚠️ 确定终止「" + inst.optString("name") + "」？不可恢复，默认引导卷一并删除。",
                 [Field.check("preserve_boot_volume", "保留引导卷（可稍后挂回或救援，保留期间计费）", false),
                  Field.check("confirm", "我已确认要终止这台实例", false)], "终止") { v in
                if !v.optBoolean("confirm") { self.toast("请先勾选确认"); return }
                var b = self.base(inst, kind)
                b["action"] = "terminate"
                b["confirm"] = true
                b["preserve_boot_volume"] = v.optBoolean("preserve_boot_volume")
                self.post("/accounts/\(self.id)/instances/action", b) { _ in
                    self.toast("终止指令已发送")
                    self.later(2.5) { self.refresh() }
                }
            }
            return
        }
        let msg = act == "terminate" ? "⚠️ 确定" + label + "「" + inst.optString("name") + "」？不可恢复，磁盘一并删除。"
            : "确定" + label + "「" + inst.optString("name") + "」？" + (act == "stop" && prov == "azure" ? "\nAzure 将 deallocate 释放计算资源。" : "")
        confirm(label, msg) {
            var b = self.base(inst, kind)
            b["action"] = act
            b["confirm"] = act == "terminate"
            self.post("/accounts/\(self.id)/instances/action", b) { _ in
                self.toast(label + "指令已发送")
                self.later(2.5) { self.refresh() }
            }
        }
    }

    // v1.5 改名 + 同步系统主机名（通过云厂商 Run Command 执行固定命令，不走 SSH）
    func rename(_ inst: JObj, _ kind: String) {
        form("实例改名", "Azure 直接生效；OCI 需开启 Oracle Cloud Agent 的 Run Command 插件；AWS 需 SSM 托管；重新登录 SSH 后可见。",
             [Field.text("new_name", "新名称", inst.optString("name")), Field.check("sync_hostname", "同步修改系统主机名（SSH 显示）", true)], "保存") { v in
            let name = v.optString("new_name").trimmingCharacters(in: .whitespacesAndNewlines)
            if name.isEmpty { self.toast("名称不能为空"); return }
            var b = self.base(inst, kind)
            b["new_name"] = name
            b["sync_hostname"] = v.optBoolean("sync_hostname", true)
            self.post("/accounts/\(self.id)/instances/rename", b) { x in self.renameResult(jobj(x)); self.refresh() }
        }
    }

    func renameResult(_ o: JObj) {
        let h = o.optJSONObject("hostname")
        if h == nil || h!.optString("status") == "ok" { toast(h == nil ? "已改名" : "已改名，系统主机名已同步"); return }
        let hh = h!
        let msg = hh.optString("message")
        let cmd = hh.optString("manual_cmd", "")
        if hh.optString("status") == "pending" || cmd.isEmpty { toast("已改名。" + msg); return }
        message(hh.optString("status") == "failed" ? "已改名，主机名同步失败" : "已改名，主机名未自动同步",
                msg + "\n\n可 SSH 登录后手动执行：\n" + cmd,
                primary: ("复制命令", { copyText(cmd); self.toast("已复制") }), cancel: "关闭")
    }

    // v1.5 实例操作「开放端口」：来源 0.0.0.0/0；填端口后先弹公网警告再提交（与 Web / TG 同一接口）
    func openPort(_ inst: JObj, _ kind: String) {
        let whereText = prov == "oci" ? "子网安全列表" : prov == "aws" ? "实例关联的全部安全组" : "网卡 / 子网的 NSG"
        form("开放端口", "在「" + inst.optString("name") + "」的" + whereText + "放行入站端口，来源 0.0.0.0/0。\n每个端口 / 范围一条规则，已存在的跳过；不支持 1-65535。",
             [Field.text("port", "端口（如 8443 或 80, 443, 8000-8100）", ""),
              Field.select("protocol", "协议", "tcp", ["tcp", "udp"], ["TCP", "UDP"])], "下一步") { v in
            let port = v.optString("port").trimmingCharacters(in: .whitespacesAndNewlines)
            if port.isEmpty { self.toast("请填写端口"); return }
            let proto = v.optString("protocol", "tcp")
            self.confirm("⚠️ 对整个互联网开放", "来源 0.0.0.0/0 表示任何人都能访问 " + proto.uppercased() + " 端口 " + port
                         + "。\n请确认这些端口上的服务有密码 / 密钥保护并保持更新。") {
                var b = self.base(inst, kind)
                b["port"] = port
                b["protocol"] = proto
                b["confirm_public"] = true
                self.post("/accounts/\(self.id)/instances/" + enc(inst.optString("id")) + "/open-port", b) { x in
                    let o = jobj(x)
                    self.message("已开放：新增 \(o.optInt("added")) 条", o.optString("msg"))
                }
            }
        }
    }

    func changeIp(_ inst: JObj, _ kind: String) {
        var f: [Field] = []
        if prov == "aws" && kind == "vm" {
            f.append(Field.select("mode", "方式", "auto", ["auto", "eip", "stopstart"], ["自动", "重分配弹性 IP（不停机）", "停机再启动（会中断）"]))
        }
        let oci = prov == "oci"
        f.append(Field.text("cidrs", "目标网段（可选，逗号分隔；! 开头 = 排除，如 !10.0.0.0/8）", ""))
        f.append(Field.num("max_tries", "最多尝试次数（指定网段或质量要求时生效）", oci ? "20" : "5"))
        f.append(Field.num("quality_max_risk", "IP 风险分上限（0~100，可选，不合格自动重换）", ""))
        f.append(Field.text("quality_country", "归属国家（可选，如 US 或 US,JP）", ""))
        get("/accounts/\(id)/ip-change-usage") { u in self.changeIpForm(inst, kind, f, jobj(u)) }
    }

    func changeIpForm(_ inst: JObj, _ kind: String, _ f: [Field], _ u: JObj) {
        let usage = u.has("limit") ? "\n今日已换：手动 \(u.optInt("manual_used")) 次 · 自动 \(u.optInt("auto_used"))/\(u.optInt("limit")) 次" : ""
        form("更换 IP", "当前：" + str(inst, "public_ip", "-") + usage, f, "更换") { v in
            var b = self.base(inst, kind)
            if v.has("mode") { b["mode"] = v.optString("mode") }
            let tries = v.optString("max_tries", "20")
            if !v.optString("cidrs").isEmpty { b["cidrs"] = v.optString("cidrs"); b["max_tries"] = tries }
            if !v.optString("quality_max_risk").isEmpty { b["quality_max_risk"] = v.optString("quality_max_risk"); b["max_tries"] = tries }
            if !v.optString("quality_country").isEmpty { b["quality_country"] = v.optString("quality_country"); b["max_tries"] = tries }
            self.post("/accounts/\(self.id)/instances/change-ip", b) { r in
                let o = jobj(r)
                if o.has("task_id") { self.openTask(o.optInt("task_id")) } else { self.toast("新 IP：" + o.optString("new_ip")) }
                self.refresh()
            }
        }
    }

    func resizeOci(_ inst: JObj) {
        form("修改配置", "Flex 实例可调整 OCPU/内存", [
            Field.num("ocpus", "OCPU", inst.optString("ocpus", "1")),
            Field.num("memory_gb", "内存 GB", inst.optString("memory_gb", "6"))], "提交") { v in
            var b = self.base(inst, "vm")
            b["ocpus"] = v.optString("ocpus")
            b["memory_gb"] = v.optString("memory_gb")
            self.post("/accounts/\(self.id)/instances/resize", b) { r in self.taskOrToast(r, "已提交") }
        }
    }

    func resizeAzure(_ inst: JObj) {
        get("/accounts/\(id)/azure/sizes?instance_id=" + enc(inst.optString("id"))) { r in
            let a = jarr(r)
            var names: [String] = [], labels: [String] = []
            for i in 0..<a.count {
                let s = a.obj(i)
                names.append(s.optString("name"))
                labels.append(s.optString("name") + " · \(s.optInt("cores"))C/" + String(format: "%.1f", Double(s.optInt("memory_mb")) / 1024.0) + "G")
            }
            self.choose("新大小（会重启 VM）", labels) { i in
                var b = self.base(inst, "vm")
                b["size"] = names[i]
                self.post("/accounts/\(self.id)/instances/resize", b) { x in self.taskOrToast(x, "已提交") }
            }
        }
    }

    func monitor(_ inst: JObj, _ kind: String) {
        form("加入监控", "监控「" + inst.optString("name") + "」，非面板操作导致停止 / 终止时推送 Telegram 告警。连通检测从面板所在服务器发起。",
             [Field.check("auto_start", "异常停止时自动启动", false),
              Field.num("check_port", "IP 连通检测端口（0 = 不检测，常用 22）", "0"),
              Field.check("auto_change_ip", "连续 3 次连不上时自动换 IP（并更新已绑定域名）", false)], "保存") { v in
            let b: JObj = ["account_id": self.id, "instance_id": inst.optString("id"), "region": self.region(),
                           "kind": kind, "name": inst.optString("name"), "state": inst.optString("state"),
                           "auto_start": v.optBoolean("auto_start"), "public_ip": inst.optString("public_ip"),
                           "check_port": v.optString("check_port", "0"), "auto_change_ip": v.optBoolean("auto_change_ip")]
            self.post("/monitors", b) { _ in self.toast("已加入监控") }
        }
    }
}
