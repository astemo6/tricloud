import SwiftUI

// 对照 Web v1.6：OCI 存储 / 对象存储 / 配额网络 / 区域订阅，AWS 区域，Azure 创建 VM / 资源组 / 配额，
// 以及实例操作：引导卷、绑定域名、附加 IP、Azure 磁盘、Lightsail 防火墙与静态 IP、账号类型与日期。

extension Page {
    /// 账号类型（OCI 免费 / 付费等），可重新查询。
    func showAccountType(_ aid: Int, _ name: String, _ refresh: Bool) {
        get("/accounts/\(aid)/account-type" + (refresh ? "?refresh=1" : "")) { r in
            let t = jobj(r)
            var lines = ["类型：" + str(t, "label", "-")]
            for (k, l) in [("plan_type", "计划"), ("account_type", "账户"), ("upgrade_state", "升级状态"), ("time_start", "开户日期"),
                           ("home_region", "主区域"), ("state", "订阅状态")] where !str(t, k, "").isEmpty {
                lines.append(l + "：" + (k == "home_region" ? Regions.label(t.optString(k)) : t.optString(k)))
            }
            if !t.isNull("age_days") { lines.append("开户天数：\(t.optInt("age_days")) 天") }
            let note = str(t, "error", str(t, "hint", ""))
            if !note.isEmpty { lines.append("\n" + note) }
            if t.optLong("checked_at") > 0 { lines.append("\n查询于 " + fmtTime(t.optLong("checked_at"))) }
            self.message("账号类型 · " + name, lines.joined(separator: "\n"),
                         primary: ("重新查询", { self.showAccountType(aid, name, true) }), cancel: "关闭")
        }
    }

    /// 账号信息：云上创建日期（OCI 可自动读取）、Azure 教育优惠到期日。
    func editAccountInfo(_ acc: JObj, _ done: @escaping () -> Void) {
        let aid = acc.optInt("id")
        let prov = acc.optString("provider")
        var f: [Field] = [Field.text("cloud_created_at", "云账号创建日期 YYYY-MM-DD", str(acc, "cloud_created_at", ""))]
        if prov == "oci" { f.append(Field.check("detect", "从 OCI 自动读取租户创建时间（忽略上面填写）", str(acc, "cloud_created_at", "").isEmpty)) }
        if prov == "azure" { f.append(Field.text("edu_expires_at", "教育优惠到期日（留空 = 创建日期 + 12 个月估算）", str(acc, "edu_expires_at", ""))) }
        let note = prov == "oci" ? "用于计算存活天数。OCI 可自动读取租户创建时间。" : "AWS / Azure 没有免费接口能读到账号创建日期，请按控制台或注册邮件填写。"
        form("账号信息 · " + acc.optString("name"), note, f, "保存") { v in
            let save = { (date: String) in
                var b: JObj = ["cloud_created_at": date]
                if v.has("edu_expires_at") { b["edu_expires_at"] = v.optString("edu_expires_at") }
                self.request("PATCH", "/accounts/\(aid)", b) { _ in self.toast("已保存"); done() }
            }
            if v.optBoolean("detect") {
                self.post("/accounts/\(aid)/detect-created", JObj()) { x in save(jobj(x).optString("cloud_created_at")) }
            } else {
                save(v.optString("cloud_created_at"))
            }
        }
    }
}

extension AccountPage {
    func accountType(_ refresh: Bool) { showAccountType(id, acc.optString("name"), refresh) }

    func accountInfo() {
        editAccountInfo(acc) {
            self.get("/accounts") { r in
                let a = jarr(r)
                AppState.shared.setAccounts(a)
                for i in 0..<a.count where a.obj(i).optInt("id") == self.id { self.acc = a.obj(i) }
                self.refresh()
            }
        }
    }

    // MARK: - 实例操作：引导卷 / 绑定域名

    func bootVolume(_ inst: JObj) {
        get("/accounts/\(id)/oci/boot-volume?instance_id=" + enc(inst.optString("id")) + "&" + rq()) { r in
            let bv = jobj(r)
            let vp = ["10", "20", "30", "40", "50", "60", "70", "80", "90", "100", "110", "120"]
            self.form("引导卷 · " + inst.optString("name"),
                      bv.optString("name") + "\n大小 \(bv.optInt("size_gb")) GB · 性能 \(bv.optInt("vpus_per_gb")) VPU/GB · " + bv.optString("state")
                      + "\n10 = 均衡（免费额度内），20+ 为高性能、按量计费。总免费额度 200 GB。",
                      [Field.num("size_gb", "扩容到 GB（只能变大，留空不改）", ""),
                       Field.select("vpus_per_gb", "性能 VPU/GB", bv.optString("vpus_per_gb", "10"), vp, nil),
                       Field.check("grow", "扩容后通过 Run Command 自动扩展根分区（需 Oracle Cloud Agent 插件）", true)], "提交") { v in
                var b = self.base(inst, "vm")
                for (k, x) in v { b[k] = x }
                self.post("/accounts/\(self.id)/oci/boot-volume", b) { x in
                    let o = jobj(x)
                    if let g = o.optJSONObject("grow") {
                        self.toast("已扩容；扩分区：" + (g.optString("status") == "ok" ? "完成" : g.optString("message")))
                    } else {
                        self.toast(str(o, "hint", "已提交"))
                    }
                }
            }
        }
    }

    func bindDns(_ inst: JObj) {
        get("/cf/zones") { r in
            let z = jarr(r)
            if z.isEmpty { self.toast("没有可用域名，请先在「设置 → Cloudflare」填写 Token"); return }
            let vals = (0..<z.count).map { z.obj($0).optString("id") + "|" + z.obj($0).optString("name") }
            let labels = (0..<z.count).map { z.obj($0).optString("name") }
            self.form("绑定域名 · " + inst.optString("name"), "绑定后，换 IP / 分配 IPv6 会自动更新这条 Cloudflare 记录。", [
                Field.select("zone", "域名", vals[0], vals, labels),
                Field.text("record", "完整记录名（如 node1. 加上面的域名）", ""),
                Field.check("v4", "更新 A 记录（IPv4）", true),
                Field.check("v6", "更新 AAAA 记录（IPv6）", false),
                Field.check("proxied", "开启 Cloudflare 代理（橙色云）", false),
                Field.check("sync_now", "立即用当前 IP 同步一次", true)], "绑定") { v in
                let zz = v.optString("zone").components(separatedBy: "|")
                if v.optString("record").isEmpty { self.toast("请填写记录名"); return }
                var b: JObj = ["account_id": self.id, "instance_id": inst.optString("id"), "name": inst.optString("name"),
                               "zone_id": zz[0], "zone_name": zz.count > 1 ? zz[1] : "", "record": v.optString("record"),
                               "v4": v.optBoolean("v4"), "v6": v.optBoolean("v6"), "proxied": v.optBoolean("proxied"),
                               "sync_now": v.optBoolean("sync_now"), "ipv4": inst.optString("public_ip")]
                b["ipv6"] = inst.optJSONArray("ipv6") ?? []
                self.post("/dns-bindings", b) { x in
                    let d = jobj(x).optJSONArray("dns") ?? []
                    self.toast(d.isEmpty ? "已绑定" : (0..<d.count).map { d.string($0) }.joined(separator: "；"))
                }
            }
        }
    }

    // MARK: - OCI 存储（块存储卷 + 引导卷）

    func ociStorage() {
        let g = gen
        get("/accounts/\(id)/oci/volumes?" + rq()) { r in
            guard self.cur(g) else { return }
            let d = jobj(r)
            Api.call("GET", "/accounts/\(self.id)/instances?kind=vm&" + self.rq(), nil) { res in
                guard self.cur(g) else { return }
                var insts: JArr = []
                if case .success(let x) = res { insts = jarr(x) }
                self.storageBuild(d, insts)
            }
        }
    }

    private func storageBuild(_ d: JObj, _ insts: JArr) {
        let iname = { (iid: String) -> String in
            for i in 0..<insts.count where insts.obj(i).optString("id") == iid { return insts.obj(i).optString("name") }
            return iid.isEmpty ? "-" : String(iid.suffix(10))
        }
        let used = d.optDouble("used_gb", 0), free = d.optDouble("free_gb", 200)
        let c = card("块存储卷（数据盘）")
        c.meter(free > 0 ? used / free : 0, "已用 " + d.optString("used_gb") + " / " + d.optString("free_gb") + " GB（Always Free 合计含引导卷）")
        c.muted("挂载方式为半虚拟化，系统内用 lsblk 查看新盘，首次使用需分区格式化。卸载前请先在系统内 umount。")
        c.row().button("＋ 新建块存储卷") { self.volCreate(d, insts) }
        let vols = d.optJSONArray("volumes") ?? []
        if vols.isEmpty { card("暂无块存储卷").muted("") }
        for i in 0..<vols.count {
            let v = vols.obj(i)
            let att = str(v, "attached_to", "")
            let vc = card(v.optString("name") + "  [" + v.optString("state") + "]")
            let dev: String = str(v, "device", "").isEmpty ? "" : "  " + v.optString("device")
            let mountAt: String = att.isEmpty ? "未挂载" : iname(att) + dev
            let spec: String = v.optString("size_gb") + " GB · " + v.optString("vpus_per_gb") + " VPU/GB"
            vc.text(spec + "\n挂载到：" + mountAt, 13)
            let row = vc.row()
            row.button("调整") { self.volUpdate(v) }
            if !att.isEmpty {
                row.button("卸载") {
                    self.confirm("卸载块存储卷", "请先在系统内 umount 并移除 /etc/fstab 条目，否则可能丢数据或开机失败。确定卸载？") {
                        self.volOp(["op": "detach", "attachment_id": v.optString("attachment_id")], "已卸载")
                    }
                }
            } else {
                row.button("挂载") {
                    if insts.isEmpty { self.toast("本区域没有实例"); return }
                    let names = (0..<insts.count).map { insts.obj($0).optString("name") }
                    self.choose("挂载到实例（需同一可用域）", names) { k in
                        self.volOp(["op": "attach", "volume_id": v.optString("id"), "instance_id": insts.obj(k).optString("id")], "已挂载")
                    }
                }
                row.button("删除") {
                    self.confirm("删除块存储卷", "删除「" + v.optString("name") + "」？数据无法恢复。") {
                        self.volOp(["op": "delete", "volume_id": v.optString("id"), "confirm": true], "已删除")
                    }
                }
            }
        }
        let bvs = d.optJSONArray("boot_volumes") ?? []
        let bc = card("引导卷（系统盘）")
        var lines: [String] = []
        for i in 0..<bvs.count {
            let b = bvs.obj(i)
            lines.append(b.optString("name") + "\n    " + b.optString("size_gb") + " GB · " + b.optString("vpus_per_gb") + " VPU/GB · " + b.optString("state"))
        }
        bc.text(lines.isEmpty ? "暂无" : lines.joined(separator: "\n"), 13)
        bc.muted("引导卷扩容在实例「更多操作 → 引导卷」里，可勾选扩容后自动扩分区。")
    }

    private func volOp(_ body: JObj, _ msg: String) {
        var b = body
        b["region"] = region()
        post("/accounts/\(id)/oci/volumes", b) { x in
            let o = jobj(x)
            self.toast(str(o, "hint", msg))
            self.refresh()
        }
    }

    private func volCreate(_ d: JObj, _ insts: JArr) {
        let vp = ["0", "10", "20", "30", "60", "90", "120"]
        let vl = ["0（低成本）", "10（均衡，免费）", "20", "30", "60", "90", "120"]
        var ids = [""], names = ["不挂载"]
        for i in 0..<insts.count { ids.append(insts.obj(i).optString("id")); names.append(insts.obj(i).optString("name")) }
        form("新建块存储卷", "当前已用 " + d.optString("used_gb") + " GB，Always Free 合计 " + d.optString("free_gb") + " GB", [
            Field.text("name", "名称", "data-1"),
            Field.num("size_gb", "大小 GB（最小 50）", "50"),
            Field.select("vpus_per_gb", "性能 VPU/GB", "10", vp, vl),
            Field.select("instance_id", "创建后挂载到（自动选同可用域）", "", ids, names)], "创建") { v in
            var b = v
            b["op"] = "create"
            b["region"] = self.region()
            self.post("/accounts/\(self.id)/oci/volumes", b) { x in
                let at = jobj(x).optJSONObject("attach")
                self.toast(at != nil && !str(at, "hint", "").isEmpty ? at!.optString("hint") : "已创建")
                self.refresh()
            }
        }
    }

    private func volUpdate(_ v: JObj) {
        let vp = ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100", "110", "120"]
        let att = str(v, "attached_to", "")
        var f: [Field] = [Field.num("size_gb", "扩容到 GB（只能变大，当前 " + v.optString("size_gb") + "，留空不改）", ""),
                          Field.select("vpus_per_gb", "性能 VPU/GB", v.optString("vpus_per_gb", "10"), vp, nil)]
        if !att.isEmpty { f.append(Field.check("grow", "扩容后通过 Run Command 让系统重新识别磁盘大小（分区需自行扩展）", true)) }
        form("调整 " + v.optString("name"), nil, f, "提交") { x in
            var b = x
            b["op"] = "update"
            b["region"] = self.region()
            b["volume_id"] = v.optString("id")
            if !att.isEmpty { b["instance_id"] = att }
            self.post("/accounts/\(self.id)/oci/volumes", b) { y in
                let o = jobj(y)
                if let g = o.optJSONObject("grow") {
                    self.toast("已提交；系统内：" + (g.optString("status") == "ok" ? "已重新识别" : g.optString("message")))
                } else { self.toast("已提交") }
                self.refresh()
            }
        }
    }

    // MARK: - OCI 对象存储

    func ociObjects() {
        let g = gen
        guard let bucket = objBucket else {
            // build 19：顶部「一键生成保号账单」卡片（仅 PAYG；先检测已有存储）
            let bkm = BillingKeepModel(self, g)
            view(AnyView(BillingKeepView(m: bkm)))
            bkm.load()
            get("/accounts/\(id)/oci/buckets?" + rq()) { r in
                guard self.cur(g) else { return }
                let d = jobj(r)
                let c = self.card("对象存储")
                c.muted("命名空间 " + d.optString("namespace") + " · Always Free 共 " + d.optString("free_gb") + " GB")
                c.row().button("＋ 新建 Bucket") {
                    self.form("新建 Bucket", "名称只能含字母、数字、- _ .", [
                        Field.text("name", "名称", ""),
                        Field.check("public", "公开读取（任何人知道链接都能下载对象，慎用）", false)], "创建") { v in
                        var b = v
                        b["op"] = "create"
                        b["region"] = self.region()
                        self.post("/accounts/\(self.id)/oci/buckets", b) { _ in self.toast("已创建"); self.refresh() }
                    }
                }
                let bs = d.optJSONArray("buckets") ?? []
                if bs.isEmpty { self.card("暂无 Bucket").muted("") } else { c.muted("大小、对象数为 OCI 定期统计的近似值，可能有几小时延迟。") }
                for i in 0..<bs.count {
                    let b = bs.obj(i)
                    let name = b.optString("name")
                    let bc = self.card("📁 " + name)
                    bc.muted(AccountPage.bucketLine(b) + "\n创建于 " + b.optString("created"))
                    let row = bc.row()
                    row.button("打开") {
                        self.objBucket = name
                        self.objPrefix = ""
                        self.refresh()
                    }
                    row.button("删除") {
                        self.confirm("删除 Bucket", "删除「" + name + "」？Bucket 需为空。") {
                            self.post("/accounts/\(self.id)/oci/buckets", ["op": "delete", "region": self.region(), "name": name, "confirm": true]) { _ in
                                self.toast("已删除")
                                self.refresh()
                            }
                        }
                    }
                }
            }
            return
        }
        let prefix = objPrefix
        let top = card(bucket + "/" + prefix)
        let tr = top.row()
        tr.button(prefix.isEmpty ? "← Bucket 列表" : "← 上一级") {
            if prefix.isEmpty { self.objBucket = nil } else { self.objPrefix = AccountPage.parentPrefix(prefix) }
            self.refresh()
        }
        tr.button("上传文件") { self.objUpload(bucket, prefix) }
        get("/accounts/\(id)/oci/objects?bucket=" + enc(bucket) + "&prefix=" + enc(prefix) + "&" + rq()) { r in
            guard self.cur(g) else { return }
            let d = jobj(r)
            let ps = d.optJSONArray("prefixes") ?? []
            for i in 0..<ps.count {
                let p = ps.string(i)
                self.nav("folder.fill", String(p.dropFirst(prefix.count)), tint: .blue) {
                    self.objPrefix = p
                    self.refresh()
                }
            }
            let os = d.optJSONArray("objects") ?? []
            var shown = 0
            for i in 0..<os.count {
                let o = os.obj(i)
                let name = o.optString("name")
                if name == prefix { continue }
                shown += 1
                let oc = self.card(String(name.dropFirst(prefix.count)))
                oc.muted(fmtBytes(o.optLong("size")) + " · " + o.optString("created"))
                let row = oc.row()
                row.button("下载链接") {
                    self.post("/accounts/\(self.id)/oci/objects", ["op": "url", "region": self.region(), "bucket": bucket, "name": name, "minutes": 60]) { x in
                        let u = jobj(x)
                        let url = u.optString("url")
                        self.message("下载链接", "预认证只读链接，" + u.optString("expires") + " 前有效，任何拿到链接的人都能下载。\n\n" + url,
                                     primary: ("复制链接", { copyText(url); self.toast("已复制") }), cancel: "关闭")
                    }
                }
                row.button("删除") {
                    self.confirm("删除对象", "删除「" + name + "」？") {
                        self.post("/accounts/\(self.id)/oci/objects", ["op": "delete", "region": self.region(), "bucket": bucket, "name": name]) { _ in
                            self.toast("已删除")
                            self.refresh()
                        }
                    }
                }
            }
            if ps.isEmpty && shown == 0 { self.card("空").muted("") }
            if !d.isNull("next") && !str(d, "next", "").isEmpty { self.card("提示").muted("只显示前 200 个对象") }
        }
    }

    static func parentPrefix(_ p: String) -> String {
        var s = p
        if s.hasSuffix("/") { s.removeLast() }
        if let r = s.range(of: "/", options: .backwards) { return String(s[..<r.upperBound]) }
        return ""
    }

    private func objUpload(_ bucket: String, _ prefix: String) {
        DocIO.pick { url in
            guard let data = try? Data(contentsOf: url) else { self.toast("❌ 读取文件失败"); return }
            let name = url.lastPathComponent
            if data.count > 100 * 1024 * 1024 { self.toast("❌ " + name + " 超过 100MB，请用 OCI 控制台上传"); return }
            self.toast("上传 " + name + "…")
            self.setBusy(true)
            Api.raw("PUT", "/accounts/\(self.id)/oci/objects?bucket=" + enc(bucket) + "&name=" + enc(prefix + name) + "&" + self.rq(), data: data) { res in
                self.setBusy(false)
                switch res {
                case .success: self.toast("✅ " + name + " 已上传"); self.refresh()
                case .failure(let e): self.toast("❌ " + name + "：" + ((e as? ApiError)?.msg ?? e.localizedDescription))
                }
            }
        }
    }

    // MARK: - OCI 配额 / 网络

    func ociLimits() {
        let r0 = card("网络")
        r0.muted("自动创建：新建 VCN（含 IPv6）、互联网网关、路由和公有子网，安全列表默认只放行 22 与 ICMP。")
        r0.row().button("自动创建网络") {
            self.confirm("自动创建网络", "在 " + Regions.label(self.region()) + " 新建 VCN（含 IPv6）、互联网网关、路由和公有子网。确定？") {
                self.post("/accounts/\(self.id)/oci/network", ["region": self.region()]) { x in self.taskOrToast(x, "已提交") }
            }
        }
        let c = card("计算配额 · " + Regions.label(region()))
        let note = c.live("加载中…")
        // 页面最底部：区域订阅的二级入口（订阅不可撤销，不放在标签栏里，防误点）
        section("高级")
        nav("exclamationmark.triangle", "区域订阅（不可撤销）", "订阅后无法取消", tint: .red) { self.push(OciRegionSubPage(self)) }
        let g = gen
        get("/accounts/\(id)/oci/limits?" + rq()) { r in
            guard self.cur(g) else { return }
            let d = jobj(r)
            c.title = "计算配额 · " + Regions.label(str(d, "region", self.region()))
            let items = d.optJSONArray("items") ?? []
            let basis = d.optString("a1_basis")
            let a1 = basis == "paid" ? "付费号 4 OCPU / 24GB" : basis == "free" ? "免费号 2 OCPU / 12GB" : "免费号 2 OCPU / 12GB（未识别账号类型，可在右上角「账号类型」刷新）"
            note.text = "「上限」是 OCI 允许开的量，升级按量付费后会很大；「免费剩余」A1 按" + a1 + "计算（2026-06 起免费号减半），E2.1.Micro 2 台，超出部分计费。可用量为 0 时抢机必然失败。"
            if items.isEmpty { c.muted("无数据") }
            for i in 0..<items.count {
                let it = items.obj(i)
                c.text(it.optString("name"), 14, true)
                var line = "上限 " + str(it, "limit", "-") + " · 已用 " + str(it, "used", "-") + " · 可用 " + str(it, "available", "-")
                if !it.isNull("free") { line += " · 免费剩余 " + str(it, "free_left", "?") + " / " + it.optString("free") }
                c.muted(line)
            }
        }
    }

    // MARK: - AWS 区域：激活 Opt-in 区域 + 全区域实例扫描

    func awsRegions(_ refresh: Bool) {
        let g = gen
        let st = card("区域激活")
        st.muted("香港、雅加达等 Opt-in 区域需先激活才能开机。")
        let stl = st.live("读取区域状态…")
        let sc = card("全区域实例")
        let scl = sc.live("全区域实例扫描（串行，约 30–60 秒）…")
        Api.call("GET", "/accounts/\(id)/aws/regions-status", nil) { res in
            guard self.cur(g) else { return }
            switch res {
            case .success(let x):
                let a = jarr(x)
                var lines: [String] = [], disabled: [String] = []
                for i in 0..<a.count {
                    let r = a.obj(i)
                    let s = r.optString("status")
                    let on = s == "ENABLED_BY_DEFAULT" || s == "ENABLED"
                    lines.append((on ? "🟢 " : s == "DISABLED" ? "⚪️ " : "🟠 ") + Regions.label(r.optString("region")) + "  " + s)
                    if s == "DISABLED" { disabled.append(r.optString("region")) }
                }
                stl.text = lines.joined(separator: "\n")
                if !disabled.isEmpty {
                    st.row().button("激活区域…") {
                        self.choose("激活区域", disabled.map { Regions.label($0) }) { i in
                            self.post("/accounts/\(self.id)/aws/enable-region", ["region": disabled[i]]) { y in
                                self.toast(str(jobj(y), "hint", "已提交激活"))
                                self.refresh()
                            }
                        }
                    }
                }
            case .failure(let e):
                stl.text = "❌ " + ((e as? ApiError)?.msg ?? e.localizedDescription) + "\n需要 account:ListRegions / account:EnableRegion 权限"
            }
        }
        Api.call("GET", "/accounts/\(id)/aws/scan" + (refresh ? "?refresh=true" : ""), nil) { res in
            guard self.cur(g) else { return }
            switch res {
            case .success(let x):
                let d = jobj(x)
                let rs = d.optJSONArray("regions") ?? []
                var lines: [String] = [], with: [String] = []
                for i in 0..<rs.count {
                    let r = rs.obj(i)
                    if r.optInt("ec2") == 0 && r.optInt("lightsail") == 0 { continue }
                    with.append(r.optString("region"))
                    lines.append(Regions.label(r.optString("region")) + "  EC2 \(r.optInt("ec2"))（运行 \(r.optInt("ec2_running"))）· Lightsail " + str(r, "lightsail", "-"))
                }
                scl.text = (lines.isEmpty ? "所有区域都没有实例" : lines.joined(separator: "\n")) + "\n\n更新于 " + d.optString("updated_at")
                let row = sc.row()
                for reg in with {
                    row.button("查看 " + reg) {
                        Prefs.set("region_\(self.id)", reg)
                        self.tab = "ec2"
                        Prefs.set("tab_\(self.id)", "ec2")
                        self.refresh()
                    }
                }
                row.button("重新扫描") {
                    self.gen += 1
                    self.header()
                    self.awsRegions(true)
                }
            case .failure(let e):
                scl.text = "❌ " + ((e as? ApiError)?.msg ?? e.localizedDescription)
            }
        }
    }

    // MARK: - Azure：创建 VM / 资源组 / 配额

    func azCreateTab() {
        let c = card("创建 Azure VM")
        c.muted("学生订阅免费额度：B1s 750 小时/月 + 2×64GB P6 SSD。创建约 2–4 分钟，后台执行并推送通知；随机密码可在「开机密码」查看。默认值来自 设置 → 默认创建参数。")
        c.row().button("填写参数并创建") { self.azureCreate() }
    }

    func azRgs() {
        let top = card("资源组")
        top.row().button("＋ 新建资源组") {
            self.get("/accounts/\(self.id)/azure/locations") { r in
                let a = jarr(r)
                let locs = (0..<a.count).map { a.string($0) }
                let def = Prefs.get("azloc_\(self.id)", "eastasia")
                self.form("新建资源组", nil, [Field.text("name", "名称", ""),
                                            Field.select("location", "区域", locs.contains(def) ? def : (locs.first ?? ""), locs, locs.map { Regions.label($0) })], "创建") { v in
                    if v.optString("name").isEmpty { self.toast("请填写名称"); return }
                    self.post("/accounts/\(self.id)/azure/rgs", v) { _ in self.toast("已创建"); self.refresh() }
                }
            }
        }
        let g = gen
        get("/accounts/\(id)/azure/rgs") { r in
            guard self.cur(g) else { return }
            let a = jarr(r)
            if a.isEmpty { top.muted("暂无资源组") }
            for i in 0..<a.count {
                let x = a.obj(i)
                let name = x.optString("name")
                let c = self.card(name)
                c.muted(Regions.label(x.optString("location")) + " · " + x.optString("state"))
                c.row().button("删除") {
                    self.form("删除资源组", "⚠️ 将删除资源组「" + name + "」内的全部资源（VM、磁盘、IP、网络），不可恢复。", [Field.text("confirm", "输入资源组名称确认", "")], "删除") { v in
                        if v.optString("confirm") != name { self.toast("名称不一致"); return }
                        self.post("/accounts/\(self.id)/azure/rgs", ["op": "delete", "name": name, "confirm": v.optString("confirm")]) { _ in
                            self.toast("已提交删除，几分钟后完成")
                            self.later(3) { self.refresh() }
                        }
                    }
                }
            }
        }
    }

    func azQuota() {
        let loc = Prefs.get("azloc_\(id)", "eastasia")
        nav("globe.asia.australia.fill", "区域", loc, tint: .teal) {
            self.get("/accounts/\(self.id)/azure/locations") { r in
                let a = jarr(r)
                let locs = (0..<a.count).map { a.string($0) }
                self.choose("选择区域（当前 " + loc + "）", locs) { i in
                    Prefs.set("azloc_\(self.id)", locs[i])
                    self.refresh()
                }
            }
        }
        let g = gen
        get("/accounts/\(id)/azure/quotas?location=" + enc(loc)) { r in
            guard self.cur(g) else { return }
            let items = jobj(r).optJSONArray("items") ?? []
            let c = self.card("计算配额 · " + loc)
            if items.isEmpty { c.muted("无数据") }
            for i in 0..<items.count {
                let it = items.obj(i)
                let used = it.optDouble("used", 0), lim = it.optDouble("limit", 0)
                if used > 0 && lim > 0 {
                    c.meter(used / lim, it.optString("name") + "  " + it.optString("used") + " / " + it.optString("limit"))
                } else {
                    c.text(it.optString("name") + "  " + it.optString("used") + " / " + it.optString("limit"), 13)
                }
            }
        }
    }

    // MARK: - Lightsail 静态 IP

    func lsStaticIps(_ insts: JArr) {
        let g = gen
        let names = (0..<insts.count).map { insts.obj($0).optString("name") }
        Api.call("GET", "/accounts/\(id)/lightsail/static-ips?" + rq(), nil) { res in
            guard self.cur(g) else { return }
            let c = self.card("静态 IP")
            c.muted("绑定在实例上的静态 IP 免费；未绑定的按小时计费，不用请释放。")
            c.row().button("＋ 分配静态 IP") {
                self.form("分配静态 IP", nil, [Field.text("name", "名称", "ip-" + base36Now()),
                                              Field.select("instance", "立即绑定到", "", [""] + names, ["不绑定（会计费）"] + names)], "分配") { v in
                    var b = v
                    b["op"] = "allocate"
                    b["region"] = self.region()
                    self.post("/accounts/\(self.id)/lightsail/static-ips", b) { x in self.toast("已分配 " + jobj(x).optString("ip")); self.refresh() }
                }
            }
            guard case .success(let x) = res else {
                if case .failure(let e) = res { c.muted("❌ " + ((e as? ApiError)?.msg ?? e.localizedDescription)) }
                return
            }
            let ips = jarr(x)
            if ips.isEmpty { c.muted("暂无静态 IP") }
            for i in 0..<ips.count {
                let s = ips.obj(i)
                let n = s.optString("name")
                let att = s.optBoolean("attached")
                let ic = self.card(n + "  " + s.optString("ip"))
                ic.muted(att ? "绑定到 " + s.optString("attached_to") : "未绑定 · 计费中")
                let row = ic.row()
                let op = { (body: JObj, msg: String) in
                    var b = body
                    b["region"] = self.region()
                    b["name"] = n
                    self.post("/accounts/\(self.id)/lightsail/static-ips", b) { y in self.toast(str(jobj(y), "hint", msg)); self.refresh() }
                }
                if att {
                    row.button("解绑") {
                        self.confirm("解绑静态 IP", "解绑后实例会换成新的动态 IP，静态 IP 开始计费。确定？") { op(["op": "detach"], "已解绑") }
                    }
                } else {
                    row.button("绑定") {
                        if names.isEmpty { self.toast("本区域没有实例"); return }
                        self.choose("绑定到实例（原公网 IP 会被替换）", names) { k in op(["op": "attach", "instance": names[k]], "已绑定") }
                    }
                    row.button("释放") {
                        self.confirm("释放静态 IP", "释放后这个 IP 无法找回。确定？") { op(["op": "release"], "已释放") }
                    }
                }
            }
        }
    }
}

// MARK: - 附加 IP（OCI 辅助 IP / 辅助网卡 / 预留公网 IP）

final class OciIpsPage: Page {
    let ap: AccountPage
    let inst: JObj

    init(_ ap: AccountPage, _ inst: JObj) {
        self.ap = ap
        self.inst = inst
        super.init()
        title = "附加 IP · " + inst.optString("name")
    }

    private func op(_ body: JObj) {
        var b = body
        b["region"] = ap.region()
        b["instance_id"] = inst.optString("id")
        post("/accounts/\(ap.id)/oci/ips", b) { x in
            let o = jobj(x)
            if !str(o, "hint", "").isEmpty { self.message("已完成", o.optString("hint")) } else { self.toast("已完成") }
            self.refresh()
        }
    }

    override func refresh() {
        get("/accounts/\(ap.id)/oci/ips?instance_id=" + enc(inst.optString("id")) + "&" + ap.rq()) { r in
            self.clear()
            let d = jobj(r)
            let vn = d.optJSONArray("vnics") ?? []
            for i in 0..<vn.count {
                let v = vn.obj(i)
                let primary = v.optBoolean("primary")
                let c = self.card((primary ? "主网卡" : "辅助网卡") + (str(v, "name", "").isEmpty ? "" : " · " + v.optString("name")))
                let ips = v.optJSONArray("ips") ?? []
                var lines: [String] = []
                let row = c.row()
                if primary { row.button("＋ 辅助 IP") { self.op(["op": "add_secondary", "vnic_id": v.optString("vnic_id")]) } }
                else {
                    row.button("卸载网卡") {
                        self.confirm("卸载辅助网卡", "卸载后该网卡上的 IP 全部释放。确定？") { self.op(["op": "detach_vnic", "attachment_id": v.optString("attachment_id")]) }
                    }
                }
                for j in 0..<ips.count {
                    let ip = ips.obj(j)
                    var line = ip.optString("ip") + (ip.optBoolean("primary") ? "（主）" : "")
                    if let pub = ip.optJSONObject("public") {
                        line += " → " + pub.optString("ip") + (pub.optString("lifetime") == "RESERVED" ? "（预留）" : "（临时）")
                    }
                    lines.append(line)
                    if !ip.optBoolean("primary") {
                        row.button("删除 " + ip.optString("ip")) {
                            self.confirm("删除辅助 IP", "删除这个辅助私网 IP（及其公网 IP）？") { self.op(["op": "delete_private", "private_ip_id": ip.optString("id")]) }
                        }
                    }
                }
                c.text(lines.isEmpty ? "-" : lines.joined(separator: "\n"), 13)
            }
            self.row().button("＋ 辅助网卡") { self.op(["op": "attach_vnic"]) }
            let rc = self.card("预留公网 IP")
            rc.muted("换机 / 重装后 IP 不变。绑到本机会替换当前临时公网 IP。辅助 IP / 辅助网卡需要在系统内配置后才生效（完成后会给出命令）。")
            rc.row().button("＋ 新建预留 IP") { self.op(["op": "create_reserved"]) }
            let rs = d.optJSONArray("reserved") ?? []
            for i in 0..<rs.count {
                let x = rs.obj(i)
                let c = self.card(x.optString("ip"))
                c.muted(x.optBoolean("assigned") ? "已绑定" : "未绑定")
                let row = c.row()
                if x.optBoolean("assigned") {
                    row.button("解绑") {
                        self.confirm("解绑预留 IP", "解绑后会自动给实例分配一个新的临时公网 IP。确定？") { self.op(["op": "unassign_reserved", "public_ip_id": x.optString("id")]) }
                    }
                } else {
                    row.button("绑到本机") {
                        self.confirm("绑定预留 IP", "把 " + x.optString("ip") + " 绑到「" + self.inst.optString("name") + "」？当前临时公网 IP 会被释放。") {
                            self.op(["op": "assign_reserved", "public_ip_id": x.optString("id"), "ip": x.optString("ip")])
                        }
                    }
                    row.button("删除") {
                        self.confirm("删除预留 IP", "删除后这个 IP 无法找回。确定？") { self.op(["op": "delete_reserved", "public_ip_id": x.optString("id")]) }
                    }
                }
            }
        }
    }
}

// MARK: - Azure 磁盘

final class AzureDisksPage: Page {
    let ap: AccountPage
    let inst: JObj

    init(_ ap: AccountPage, _ inst: JObj) {
        self.ap = ap
        self.inst = inst
        super.init()
        title = "磁盘 · " + inst.optString("name")
    }

    override func refresh() {
        get("/accounts/\(ap.id)/azure/disks?instance_id=" + enc(inst.optString("id"))) { r in
            self.clear()
            let d = jobj(r)
            let skus = (0..<(d.optJSONArray("skus") ?? []).count).map { (d.optJSONArray("skus") ?? []).string($0) }
            let tiers = (0..<(d.optJSONArray("tiers") ?? []).count).map { (d.optJSONArray("tiers") ?? []).string($0) }
            let ds = d.optJSONArray("disks") ?? []
            for i in 0..<ds.count {
                let k = ds.obj(i)
                let c = self.card(k.optString("role") == "os" ? "系统盘" : "数据盘 LUN " + k.optString("lun"))
                c.text(k.optString("size_gb") + " GB · " + str(k, "sku", "-") + " · 性能层 " + str(k, "tier", "-"), 14)
                c.muted(k.optString("name"))
                c.row().button("调整") {
                    var f: [Field] = [Field.num("size_gb", "大小 GB（只能变大，当前 " + k.optString("size_gb") + "，留空不改）", "")]
                    if !skus.isEmpty { f.append(Field.select("sku", "类型", k.optString("sku"), skus, nil)) }
                    f.append(Field.select("tier", "Premium 性能层（只对 Premium SSD 有效）", "", [""] + tiers, ["不变"] + tiers))
                    self.form("调整 " + k.optString("name"), nil, f, "提交") { v in
                        var b = v
                        if v.optString("sku") == k.optString("sku") { b.removeValue(forKey: "sku") }
                        b["instance_id"] = self.inst.optString("id")
                        b["disk_id"] = k.optString("id")
                        self.post("/accounts/\(self.ap.id)/azure/disks", b) { x in self.toast(str(jobj(x), "hint", "已调整")); self.refresh() }
                    }
                }
            }
            if !str(d, "hint", "").isEmpty { self.card("说明").muted(d.optString("hint")) }
        }
    }
}

// MARK: - Lightsail 防火墙

final class LsPortsPage: Page {
    let ap: AccountPage
    let inst: JObj

    init(_ ap: AccountPage, _ inst: JObj) {
        self.ap = ap
        self.inst = inst
        super.init()
        title = "防火墙 · " + inst.optString("name")
    }

    override func refresh() {
        get("/accounts/\(ap.id)/lightsail/ports?instance=" + enc(inst.optString("id")) + "&" + ap.rq()) { r in
            self.clear()
            let ps = jarr(r)
            self.bigButton("＋ 开放端口") { self.open() }
            if ps.isEmpty { self.card("没有开放的端口").muted("") }
            for i in 0..<ps.count {
                let p = ps.obj(i)
                let from = p.optInt("from"), to = p.optInt("to")
                let range = from == to ? "\(from)" : "\(from)-\(to)"
                let c = self.card(p.optString("protocol").uppercased() + " · " + range)
                let cidrs = join(p.optJSONArray("cidrs")) + ((p.optJSONArray("ipv6_cidrs") ?? []).isEmpty ? "" : ", " + join(p.optJSONArray("ipv6_cidrs")))
                c.muted(cidrs.isEmpty ? "-" : cidrs)
                c.row().button("关闭") {
                    self.confirm("关闭端口", "关闭 " + p.optString("protocol") + " " + range + "？") {
                        self.post("/accounts/\(self.ap.id)/lightsail/ports", ["op": "close", "instance": self.inst.optString("id"), "region": self.ap.region(),
                                                                             "protocol": p.optString("protocol"), "from_port": from, "to_port": to]) { _ in
                            self.toast("已关闭")
                            self.refresh()
                        }
                    }
                }
            }
        }
    }

    private func open() {
        form("开放端口", "单个或范围，如 8443 或 8000-8100；ICMP 不需要端口。", [
            Field.select("protocol", "协议", "tcp", ["tcp", "udp", "icmp"], ["TCP", "UDP", "ICMP"]),
            Field.text("port", "端口", ""),
            Field.text("cidrs", "来源 CIDR（逗号分隔）", "0.0.0.0/0")], "开放") { v in
            let proto = v.optString("protocol")
            var from = -1, to = -1
            if proto == "icmp" { from = 0; to = 0 }
            else {
                let parts = v.optString("port").replacingOccurrences(of: " ", with: "").components(separatedBy: "-")
                guard let a = Int(parts[0]) else { self.toast("请填写端口，如 8443 或 8000-8100"); return }
                from = a
                to = parts.count > 1 ? (Int(parts[1]) ?? a) : a
            }
            let cidrs = v.optString("cidrs")
            var b: JObj = ["op": "open", "instance": self.inst.optString("id"), "region": self.ap.region(), "protocol": proto,
                           "from_port": from, "to_port": to, "cidrs": cidrs]
            let send = { (pub: Bool) in
                if pub { b["confirm_public"] = true }
                self.post("/accounts/\(self.ap.id)/lightsail/ports", b) { _ in self.toast("已开放"); self.refresh() }
            }
            if cidrs.contains("0.0.0.0/0") || cidrs.contains("::/0") {
                self.confirm("⚠️ 对整个互联网开放", "来源 0.0.0.0/0：任何人都能访问 " + (proto == "icmp" ? "ICMP" : v.optString("port")) + "。请确认服务有密码 / 密钥保护。") { send(true) }
            } else { send(false) }
        }
    }
}

// MARK: - OCI 区域订阅（build 18：从标签栏移到「配额/网络」底部的二级入口；提交前须手动输入区域标识，如 ap-osaka-1）

final class OciRegionSubPage: Page {
    let ap: AccountPage

    init(_ ap: AccountPage) {
        self.ap = ap
        super.init()
        title = "区域订阅（不可撤销）"
    }

    override func refresh() {
        get("/accounts/\(ap.id)/oci/region-subscriptions") { r in
            self.clear()
            let d = jobj(r)
            let rs = d.optJSONArray("regions") ?? []
            var subd: [JObj] = [], unsub: [JObj] = []
            for i in 0..<rs.count { if rs.obj(i).optBoolean("subscribed") { subd.append(rs.obj(i)) } else { unsub.append(rs.obj(i)) } }
            let c = self.card("已订阅 \(subd.count) 个区域 · 主区域 " + Regions.label(str(d, "home", "-")))
            c.muted(d.optString("limit_hint") + "。订阅不可撤销，订阅后可在实例等标签的「区域」里切换。")
            var lines: [String] = []
            for x in subd {
                let home: String = x.optBoolean("home") ? " · 主区域" : ""
                let head: String = Regions.label(x.optString("name")) + " (" + x.optString("key") + ")"
                lines.append(head + home + " · " + str(x, "status", "已订阅"))
            }
            c.text(lines.joined(separator: "\n"), 13)
            if !unsub.isEmpty {
                c.row().button("订阅新区域…") {
                    self.choose("订阅区域（不可撤销）", unsub.map { Regions.label($0.optString("name")) + " · " + $0.optString("key") }) { i in
                        self.subscribe(unsub[i])
                    }
                }
            }
        }
    }

    private func subscribe(_ x: JObj) {
        let key = x.optString("key"), name = x.optString("name")
        confirm("订阅区域", "订阅 " + name + "（" + key + "）？\n⚠️ 订阅后无法取消，免费账号的额外区域名额通常只有 1 个；Always Free 资源仍只在主区域。") {
            self.form("再次确认：订阅区域", "订阅 " + name + "（" + key + "）后无法取消。请手动输入区域标识「" + name + "」以确认。",
                      [Field.text("region_name", "区域标识（如 ap-osaka-1）", "")], "确认订阅") { v in
                if v.optString("region_name").trimmingCharacters(in: .whitespacesAndNewlines) != name {
                    self.toast("输入的区域标识不一致，未订阅")
                    return
                }
                self.post("/accounts/\(self.ap.id)/oci/region-subscriptions", ["region_key": key, "confirm": true]) { y in
                    let o = jobj(y)
                    self.toast("已提交订阅：" + o.optString("region") + "（" + o.optString("status") + "），几分钟后生效")
                    self.refresh()
                }
            }
        }
    }
}
