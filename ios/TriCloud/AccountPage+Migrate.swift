import SwiftUI

// AccountActivity：跨账号迁移（v1.2 / v1.3）与流量守护规则添加。

extension AccountPage {
    func migrate(_ inst: JObj) {
        get("/accounts") { r in
            let a = jarr(r)
            var ts: [JObj] = []
            for i in 0..<a.count where a.obj(i).optInt("id") != self.id { ts.append(a.obj(i)) }
            if ts.isEmpty { self.toast("至少需要两个云账号"); return }
            let labels = ts.map { MainPage.pname($0.optString("provider")) + " · " + $0.optString("name") }
            self.choose("迁移到哪个账号", labels) { idx in
                let to = ts[idx]
                let tp = to.optString("provider")
                var f: [Field] = [Field.text("name", "新实例名称", inst.optString("name") + "-new")]
                if tp == "oci" {
                    f.append(Field.select("shape", "规格", "VM.Standard.A1.Flex", ["VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"],
                                          [AccountPage.SHAPE_LABELS[0], AccountPage.SHAPE_LABELS[1]]))
                    f.append(Field.num("ocpus", "OCPU", "1"))
                    f.append(Field.num("memory_gb", "内存 GB", "6"))
                    f.append(Field.num("disk_gb", "系统盘 GB", "50"))
                    f.append(AccountPage.osImageField("Canonical Ubuntu", ""))
                } else if tp == "aws" {
                    f.append(Field.text("type", "实例类型", "t3.micro"))
                    f.append(Field.select("os", "系统", "debian-12", ["debian-12", "ubuntu-24.04"], ["Debian 12", "Ubuntu 24.04"]))
                    f.append(Field.num("disk_gb", "系统盘 GB", "10"))
                } else {
                    f.append(Field.text("location", "区域", "eastasia"))
                    f.append(Field.text("size", "大小", "Standard_B1s"))
                    f.append(Field.select("disk_type", "磁盘", "Premium_LRS", ["Premium_LRS", "StandardSSD_LRS"], ["Premium SSD（免费 P6）", "Standard SSD"]))
                    f.append(Field.num("disk_gb", "系统盘 GB", "64"))
                }
                f.append(Field.check("switch_dns", "完成后把域名切到新 IP", true))
                f.append(Field.check("copy_monitor", "复制监控设置", true))
                f.append(Field.check("stop_source", "完成后停掉源实例（不删除）", false))
                self.form("迁移到 " + to.optString("name"), "用开机脚本在目标账号重建，⚠️ 不复制磁盘数据。", f, "开始迁移") { v in
                    var create = AccountPage.splitOsImage(v)
                    for k in ["switch_dns", "copy_monitor", "stop_source"] { create.removeValue(forKey: k) }
                    var b: JObj = ["from_account_id": self.id, "from_region": self.region(), "instance_id": inst.optString("id"),
                                   "name": inst.optString("name"), "to_account_id": to.optInt("id"), "create": create,
                                   "switch_dns": v.optBoolean("switch_dns"), "copy_monitor": v.optBoolean("copy_monitor"), "stop_source": v.optBoolean("stop_source")]
                    if tp != "azure" { b["region"] = Prefs.get("region_\(to.optInt("id"))", str(to, "region", "")) }
                    self.post("/migrate", b) { x in self.taskOrToast(x, "已提交") }
                }
            }
        }
    }

    func traffic(_ inst: JObj, _ kind: String) {
        trafficGuardForm(id, prov, inst.optString("id"), inst.optString("name"), prov == "azure" ? "" : region(), kind, nil)
    }
}

extension Page {
    /// 流量守护规则（新建 / 编辑同一接口 POST /traffic-guards）；existing 为已有规则时回显。
    func trafficGuardForm(_ accId: Int, _ prov: String, _ instId: String, _ name: String, _ region: String, _ kind: String,
                          _ onSaved: (() -> Void)?) {
        let free = prov == "oci" ? "10240" : "100"
        let rq = region.isEmpty ? "" : "&region=" + enc(region)
        get("/traffic-guards") { gr in
            let gs = jarr(gr)
            var g: JObj = [:]
            for i in 0..<gs.count where gs.obj(i).optInt("account_id") == accId && gs.obj(i).optString("instance_id") == instId { g = gs.obj(i) }
            Api.call("GET", "/accounts/\(accId)/traffic?instance_id=" + enc(instId) + "&kind=" + kind + rq, nil) { res in
                var use = ""
                switch res {
                case .success(let x):
                    let t = jobj(x)
                    use = "本月出站 " + t.optString("out_gb") + " GB，入站 " + t.optString("in_gb") + " GB。"
                case .failure(let e):
                    use = "读取流量失败：" + ((e as? ApiError)?.msg ?? e.localizedDescription)
                }
                let dir = str(g, "direction", g.optBoolean("count_in") ? "both" : "out")
                var f: [Field] = []
                f.append(Field.select("mode", "统计方式", str(g, "mode", "monthly"), ["monthly", "rolling"], ["本月累计", "滚动窗口（最近 N 小时）"]))
                f.append(Field.num("window_hours", "窗口小时数 N（滚动窗口）", str(g, "window_hours", "24")))
                f.append(Field.select("direction", "方向", dir, ["out", "in", "both"], ["出站", "入站", "双向（出+入）"]))
                f.append(Field.num("limit_gb", "上限 GB（免费出站 " + free + " GB/月）", str(g, "limit_gb", free)))
                f.append(Field.num("warn_pct", "预警比例 %", str(g, "warn_pct", "80")))
                f.append(Field.select("action", "到达上限后", str(g, "action", "notify"), ["notify", "stop"], ["只推送", "推送并自动停机"]))
                f.append(Field.num("shutdown_hours", "关机多少小时后自动开机（0 = 不自动开机）", str(g, "shutdown_hours", "0")))
                f.append(Field.check("enabled", "启用这条规则", g.isNull("enabled") || g.optInt("enabled", 1) == 1))
                self.form("流量守护 · " + name, use + "\n月度模式每 30 分钟、滚动窗口每 10 分钟查一次平台指标（有 5~15 分钟延迟）。自动开机失败只推送告警、不重试。",
                          f, "保存") { v in
                    var b = v
                    b["account_id"] = accId
                    b["instance_id"] = instId
                    if !region.isEmpty { b["region"] = region }
                    b["kind"] = kind
                    b["name"] = name
                    self.post("/traffic-guards", b) { y in
                        let o = jobj(y)
                        let ok: String = "已保存，当前已用 " + str(o, "last_gb", "-") + " GB（" + str(o, "last_pct", "-") + "%）"
                        self.toast(o.isNull("warning") ? ok : "⚠️ " + o.optString("warning"))
                        onSaved?()
                    }
                }
            }
        }
    }
}
