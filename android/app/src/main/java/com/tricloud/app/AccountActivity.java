package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;

import com.google.android.material.tabs.TabLayout;

/** 单个云账号：与 Web 端相同的标签页（实例/Lightsail/CloudFront/配额/创建/抢机/安全组/账单）。v1.5 移除串口控制台。 */
public class AccountActivity extends BaseActivity {
    private JSONObject acc;
    private String prov, tab;
    private int id;
    private JSONObject defaults = new JSONObject();

    static String[][] tabs(String p) {
        switch (p) {
            case "oci": return new String[][]{{"instances", "实例"}, {"create", "创建实例"}, {"snatch", "自动抢机"}, {"secgroup", "安全组"}, {"storage", "存储"},
                    {"objects", "对象存储"}, {"traffic", "流量"}, {"limits", "配额/网络"}, {"regionsub", "区域订阅"}, {"billing", "账单"}};
            case "aws": return new String[][]{{"ec2", "EC2"}, {"lightsail", "Lightsail"}, {"regions", "区域"}, {"cloudfront", "CloudFront"}, {"quota", "配额"}, {"recycle", "闲置资源"}, {"billing", "账单"}};
            case "greencloud": return new String[][]{{"gcinst", "实例"}};
            default: return new String[][]{{"vms", "虚拟机"}, {"azcreate", "创建 VM"}, {"rgs", "资源组"}, {"azquota", "配额"}, {"foundry", "Foundry"}, {"subscription", "订阅"}, {"billing", "账单"}};
        }
    }

    @Override
    protected void onCreate(Bundle s) {
        super.onCreate(s);
        try { acc = new JSONObject(getIntent().getStringExtra("acc")); } catch (Exception e) { finish(); return; }
        prov = acc.optString("provider");
        id = acc.optInt("id");
        tab = s != null ? s.getString("tab", tabs(prov)[0][0]) : Api.pref("tab_" + id, tabs(prov)[0][0]);
        boolean known = false;
        for (String[] t : tabs(prov)) if (t[0].equals(tab)) known = true;
        if (!known) tab = tabs(prov)[0][0];
        setTitle(MainActivity.pname(prov) + " · " + acc.optString("name"));
        buildNav();
        // Material 3 TabLayout：可横向滚动，固定在内容区上方
        TabLayout tl = new TabLayout(this);
        tl.setTabMode(TabLayout.MODE_SCROLLABLE);
        tl.setTabGravity(TabLayout.GRAVITY_START);
        tl.setBackgroundColor(attr(com.google.android.material.R.attr.colorSurface));
        int sel = 0;
        String[][] ts = tabs(prov);
        for (int i = 0; i < ts.length; i++) {
            tl.addTab(tl.newTab().setText(ts[i][1]).setTag(ts[i][0]), false);
            if (ts[i][0].equals(tab)) sel = i;
        }
        topBar.addView(tl, new LinearLayout.LayoutParams(-1, -2));
        TabLayout.Tab st = tl.getTabAt(sel);
        if (st != null) st.select();
        tl.post(() -> tl.setScrollPosition(tl.getSelectedTabPosition(), 0f, true));
        tl.addOnTabSelectedListener(new TabLayout.OnTabSelectedListener() {
            @Override public void onTabSelected(TabLayout.Tab t) { tab = (String) t.getTag(); Api.setPref("tab_" + id, tab); objBucket = null; objPrefix = ""; refresh(); }
            @Override public void onTabUnselected(TabLayout.Tab t) { }
            @Override public void onTabReselected(TabLayout.Tab t) { refresh(); }
        });
        Api.get(this, "/settings", r -> { defaults = Api.obj(r).optJSONObject("default_create"); if (defaults == null) defaults = new JSONObject(); });
        Api.quiet("/scripts", r -> scripts = Api.arr(r));
        refresh();
    }

    @Override
    protected String navKey() { return "acc_" + id; }

    private JSONArray scripts = new JSONArray();

    /** 开机脚本模板下拉（脚本模板页维护），与 Web loginFields 一致。 */
    private Field scriptField() {
        int n = scripts.length();
        String[] ids = new String[n + 1], labels = new String[n + 1];
        ids[0] = ""; labels[0] = "不使用模板";
        for (int i = 0; i < n; i++) { ids[i + 1] = String.valueOf(scripts.optJSONObject(i).optInt("id")); labels[i + 1] = scripts.optJSONObject(i).optString("name"); }
        return Field.select("script_id", "开机脚本模板", "", ids, labels);
    }

    @Override
    protected void onSaveInstanceState(Bundle o) { super.onSaveInstanceState(o); o.putString("tab", tab); }

    String region() { return Api.pref("region_" + id, str(acc, "region", "")); }
    String rq() { return MainActivity.noRegion(prov) ? "" : "region=" + Api.enc(region()); }
    JSONObject base(JSONObject inst, String kind) throws Exception {
        return new JSONObject().put("instance_id", inst.optString("id")).put("region", region()).put("kind", kind).put("name", inst.optString("name"));
    }

    private void header() {
        clear();
        if (!MainActivity.noRegion(prov) && !Arrays.asList("cloudfront", "quota", "billing", "subscription", "regions", "regionsub").contains(tab)) {
            LinearLayout r2 = row(body);
            button(r2, "区域：" + region(), v -> Api.get(this, "/accounts/" + id + "/regions", x -> {
                JSONArray a = Api.arr(x);
                String[] rs = new String[a.length()];
                for (int i = 0; i < rs.length; i++) rs[i] = a.optString(i);
                choose("选择区域", rs, i -> { Api.setPref("region_" + id, rs[i]); refresh(); });
            }));
        }
    }

    @Override
    protected void refresh() {
        header();
        switch (tab) {
            case "instances": case "ec2": case "vms": instances("vm"); break;
            case "gcinst": gcInstances(); break;
            case "lightsail": instances("lightsail"); break;
            case "create": ociCreate(false); break;
            case "snatch": ociCreate(true); break;
            case "cloudfront": cloudfront(); break;
            case "quota": quota(false); break;
            case "recycle": recycle(); break;
            case "billing": billing(false); break;
            case "subscription": subscription(); break;
            case "foundry": foundry(); break;
            case "secgroup": secgroup(); break;
            case "traffic": ociTraffic(); break;
            case "storage": ociStorage(); break;
            case "objects": ociObjects(); break;
            case "limits": ociLimits(); break;
            case "regionsub": ociRegionSub(); break;
            case "regions": awsRegions(false); break;
            case "azcreate": azCreateTab(); break;
            case "rgs": azRgs(); break;
            case "azquota": azQuota(); break;
        }
    }

    // ---------------- 实例 ----------------
    private void instances(String kind) {
        if ("lightsail".equals(kind)) bigButton("＋ 创建 Lightsail", v -> lightsailCreate());
        if ("aws".equals(prov) && "vm".equals(kind)) bigButton("＋ 创建 EC2", v -> ec2Create());
        if ("azure".equals(prov)) bigButton("＋ 创建 Azure VM", v -> azureCreate());
        Api.get(this, "/accounts/" + id + "/instances?kind=" + kind + "&" + rq(), r -> {
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card("该区域没有实例"), region());
            for (int i = 0; i < a.length(); i++) instCard(a.optJSONObject(i), kind);
            if ("lightsail".equals(kind)) lsStaticIps(a);
        });
    }

    private void instCard(JSONObject inst, String kind) {
        LinearLayout c = card(inst.optString("name") + "  [" + inst.optString("state") + "]");
        JSONArray v6 = inst.optJSONArray("ipv6");
        String spec = "oci".equals(prov) ? inst.optString("shape") + " " + str(inst, "ocpus", "?") + "C/" + str(inst, "memory_gb", "?") + "G" : inst.optString("shape");
        text(c, "公网 IP：" + str(inst, "public_ip", "-") + "\n内网 IP：" + str(inst, "private_ip", "-")
                + "\nIPv6：" + (v6 != null && v6.length() > 0 ? join(v6) : "-")
                + "\n规格：" + spec + "\n可用区：" + str(inst, "zone", "-"), 13, false);
        LinearLayout r = row(c);
        button(r, "启动", v -> simple(inst, kind, "start", "启动"));
        button(r, "azure".equals(prov) ? "停止(释放)" : "停止", v -> simple(inst, kind, "stop", "停止"));
        button(r, "重启", v -> simple(inst, kind, "reboot", "重启"));
        button(r, "换 IP", v -> changeIp(inst, kind));
        if ("oci".equals(prov)) {
            button(r, "加 IPv6", v -> { try { Api.post(this, "/accounts/" + id + "/oci/ipv6", base(inst, kind), x -> taskOrToast(x, "已提交")); } catch (Exception ignored) { } });
            button(r, "删 IPv6", v -> confirm("删除 IPv6", "⚠️ 将删除「" + inst.optString("name") + "」主网卡上的全部 IPv6 地址（VCN / 子网配置保留）。", () -> {
                try { Api.post(this, "/accounts/" + id + "/oci/ipv6/delete", base(inst, kind).put("confirm", true), x -> { toast("已删除：" + join(Api.obj(x).optJSONArray("deleted"))); refresh(); }); }
                catch (Exception ignored) { }
            }));
            button(r, "改配置", v -> resizeOci(inst));
            button(r, "引导卷", v -> bootVol(inst, kind));
            button(r, "附加 IP", v -> ociIps(inst));
        }
        if ("azure".equals(prov)) { button(r, "改大小", v -> resizeAzure(inst)); button(r, "磁盘", v -> azDisks(inst)); }
        if ("lightsail".equals(kind)) button(r, "防火墙", v -> lsPorts(inst));
        if (!"lightsail".equals(kind)) button(r, "改名", v -> rename(inst, kind));   // v1.5：Lightsail 不支持改名
        if (!"lightsail".equals(kind)) button(r, "开放端口", v -> openPort(inst, kind));
        button(r, "流量守护", v -> traffic(inst, kind));
        if (!"lightsail".equals(kind)) {
            button(r, "迁移", v -> migrate(inst));
        }
        button(r, "绑定域名", v -> bindDns(inst));
        button(r, "监控", v -> monitor(inst, kind));
        // v1.6：IP 质量 / 免费 AMD 下行 500Mbps / 重装系统
        button(r, "IP 质量", v -> ipQuality(inst));
        if ("oci".equals(prov) && "VM.Standard.E2.1.Micro".equals(inst.optString("shape"))) button(r, "500M 下行", v -> net500(inst, kind));
        if (!"lightsail".equals(kind)) button(r, "重装系统", v -> reinstall(inst, kind));
        button(r, "azure".equals(prov) || "lightsail".equals(kind) ? "删除" : "终止", v -> simple(inst, kind, "terminate", "终止"));
    }

    // ---------------- GreenCloud（v1.6.0 build 11）：只有实例列表 + 开机/关机/重启 ----------------
    private void gcInstances() {
        Api.get(this, "/accounts/" + id + "/instances", r -> {
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card("没有服务器"), "在「云账号 → 编辑」里按「名称 key hash」每行一台补充服务器列表。");
            for (int i = 0; i < a.length(); i++) gcCard(a.optJSONObject(i));
        });
    }

    private static String gb(long bytes) { return String.format(Locale.US, "%.2f", bytes / 1073741824.0); }

    private void gcCard(JSONObject inst) {
        String st = str(inst, "state", "unknown");
        String dot = "running".equals(st) ? "🟢 运行中" : "stopped".equals(st) ? "🔴 已关机" : "⚪ 未知";
        LinearLayout c = card(inst.optString("name"));
        JSONArray ips = inst.optJSONArray("ips");
        String ipLine = str(inst, "public_ip", "-");
        if (ips != null && ips.length() > 1) ipLine = join(ips);
        text(c, "状态：" + dot + "\nIP：" + ipLine + "\n主机名：" + str(inst, "hostname", "-"), 13, false);
        JSONObject bw = inst.optJSONObject("bw");
        if (bw != null && bw.optLong("total") > 0) {
            long used = bw.optLong("used"), total = bw.optLong("total");
            double pct = bw.has("percent") && !bw.isNull("percent") ? bw.optDouble("percent") : used * 100.0 / total;
            if (Double.isNaN(pct)) pct = used * 100.0 / total;
            muted(c, "流量：" + gb(used) + " / " + gb(total) + " GB（" + String.format(Locale.US, "%.1f", pct) + "%）");
            com.google.android.material.progressindicator.LinearProgressIndicator pb = new com.google.android.material.progressindicator.LinearProgressIndicator(this);
            pb.setMax(1000);
            pb.setProgressCompat((int) Math.max(0, Math.min(1000, Math.round(pct * 10))), false);
            pb.setTrackCornerRadius(dp(3));
            pb.setTrackThickness(dp(6));
            if (pct >= 90) pb.setIndicatorColor(0xFFE53935);
            else if (pct >= 70) pb.setIndicatorColor(0xFFFB8C00);
            else pb.setIndicatorColor(0xFF43A047);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.setMargins(0, dp(4), 0, dp(4));
            c.addView(pb, lp);
        } else muted(c, "流量：-");
        LinearLayout r = row(c);
        button(r, "开机", v -> gcAction(inst, "start", "开机"));
        button(r, "关机", v -> gcAction(inst, "stop", "关机"));
        button(r, "重启", v -> gcAction(inst, "reboot", "重启"));
    }

    private void gcAction(JSONObject inst, String act, String label) {
        confirm(label, "确定" + label + "「" + inst.optString("name") + "」？", () -> {
            try {
                JSONObject b = new JSONObject().put("instance_id", inst.optString("id")).put("region", "-").put("kind", "vm")
                        .put("name", inst.optString("name")).put("action", act).put("confirm", false);
                Api.post(this, "/accounts/" + id + "/instances/action", b, x -> { toast(label + "指令已发送"); body.postDelayed(this::refresh, 2500); });
            } catch (Exception ignored) { }
        });
    }

    // ---------------- v1.6 ----------------
    private void reinstall(JSONObject inst, String kind) {
        List<Field> f = new ArrayList<>();
        if ("oci".equals(prov)) {
            f.add(Field.select("os", "系统", "Canonical Ubuntu", new String[]{"Canonical Ubuntu", "Oracle Linux"}, null));
            f.add(Field.select("os_version", "系统版本", "", new String[]{"", "24.04", "22.04", "20.04", "9", "8"}, new String[]{"最新", "Ubuntu 24.04", "Ubuntu 22.04", "Ubuntu 20.04", "Oracle Linux 9", "Oracle Linux 8"}));
            f.add(Field.num("disk_gb", "新引导卷大小 GB（留空 = 与当前相同）", ""));
        } else if ("aws".equals(prov)) {
            f.add(Field.select("os", "系统", "debian-12", new String[]{"debian-12", "ubuntu-24.04", "ubuntu-22.04", "al2023"}, new String[]{"Debian 12", "Ubuntu 24.04", "Ubuntu 22.04", "Amazon Linux 2023"}));
        } else {
            f.add(Field.select("os", "系统", "debian-12", new String[]{"debian-12", "ubuntu-24.04", "ubuntu-22.04"}, new String[]{"Debian 12", "Ubuntu 24.04", "Ubuntu 22.04"}));
        }
        if (!"aws".equals(prov)) f.add(Field.check("password_login", "生成新的随机 root 密码（在「开机密码」查看）", true));
        f.add(Field.check("confirm", "我已确认要清空系统盘数据", false));
        form("重装系统", "⚠️ 将重装「" + inst.optString("name") + "」，系统盘上的全部数据会被清空，不可恢复。实例会停机几分钟。", f, "开始重装", v -> {
            if (!v.optBoolean("confirm")) { toast("请先勾选确认"); return; }
            try {
                JSONObject b = base(inst, kind).put("confirm", true);
                for (String k : new String[]{"os", "os_version", "disk_gb"}) if (!v.optString(k).isEmpty()) b.put(k, v.optString(k));
                if (v.has("password_login")) b.put("password_login", v.optBoolean("password_login"));
                Api.post(this, "/accounts/" + id + "/instances/reinstall", b, x -> taskOrToast(x, "已提交"));
            } catch (Exception ignored) { }
        });
    }

    private void ipQuality(JSONObject inst) {
        String ip = inst.optString("public_ip", "");
        if (ip.isEmpty() || "null".equals(ip)) { toast("实例没有公网 IP"); return; }
        Api.get(this, "/ip-quality?ip=" + ip, r -> {
            JSONObject q = Api.obj(r);
            String risk = q.isNull("risk") ? "查询失败" : q.optInt("risk") + "（0~100，越低越干净）";
            new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("IP 质量 · " + inst.optString("name"))
                    .setMessage("IP：" + ip + "\n风险分：" + risk + "\n类型：" + str(q, "type", "-") + (q.optBoolean("proxy") ? "（被标记为代理/VPN）" : "")
                            + "\n归属：" + str(q, "country", "-") + " " + str(q, "country_code", "") + "\nISP：" + str(q, "isp", "-") + " " + str(q, "asn", "")
                            + "\n\n数据源：" + q.optString("source"))
                    .setPositiveButton("关闭", null).show();
        });
    }

    private void net500(JSONObject inst, String kind) {
        Api.get(this, "/accounts/" + id + "/oci/500m?instance_id=" + android.net.Uri.encode(inst.optString("id")) + "&" + rq(), r -> {
            JSONObject st = Api.obj(r);
            boolean on = st.optBoolean("enabled");
            String msg = on ? "当前已开启，入口 IP：" + st.optString("public_ip") + "\n关闭后删除负载均衡器，恢复用原公网 IP 入站。"
                    : "新建网络负载均衡器（Always Free 1 个）转发全部端口，入口 IP 变成负载均衡器的公网 IP；实例改走 NAT 网关出站。账号里已有其他负载均衡器时不会动它。";
            confirm(on ? "关闭下行 500Mbps" : "开启下行 500Mbps", msg, () -> {
                try { Api.post(this, "/accounts/" + id + "/oci/500m", base(inst, kind).put("enable", !on).put("confirm", true), x -> taskOrToast(x, "已提交")); }
                catch (Exception ignored) { }
            });
        });
    }

    private void simple(JSONObject inst, String kind, String act, String label) {
        if ("terminate".equals(act) && "oci".equals(prov)) {
            form(label, "⚠️ 确定终止「" + inst.optString("name") + "」？不可恢复，引导卷默认一并删除。", Arrays.asList(
                    Field.check("preserve_boot_volume", "保留引导卷（可稍后挂回或救援，保留期间计费）", false)), "终止", v -> {
                try {
                    Api.post(this, "/accounts/" + id + "/instances/action", base(inst, kind).put("action", act).put("confirm", true)
                            .put("preserve_boot_volume", v.optBoolean("preserve_boot_volume")), r -> { toast(label + "指令已发送"); body.postDelayed(this::refresh, 2500); });
                } catch (Exception ignored) { }
            });
            return;
        }
        String msg = "terminate".equals(act) ? "⚠️ 确定" + label + "「" + inst.optString("name") + "」？不可恢复，磁盘一并删除。"
                : "确定" + label + "「" + inst.optString("name") + "」？" + ("stop".equals(act) && "azure".equals(prov) ? "\nAzure 将 deallocate 释放计算资源。" : "");
        confirm(label, msg, () -> {
            try {
                Api.post(this, "/accounts/" + id + "/instances/action", base(inst, kind).put("action", act).put("confirm", "terminate".equals(act)),
                        r -> { toast(label + "指令已发送"); body.postDelayed(this::refresh, 2500); });
            } catch (Exception ignored) { }
        });
    }

    // v1.5 改名 + 同步系统主机名（通过云厂商 Run Command 执行固定命令，不走 SSH）
    private void rename(JSONObject inst, String kind) {
        form("实例改名", "Azure 直接生效；OCI 需开启 Oracle Cloud Agent 的 Run Command 插件；AWS 需 SSM 托管；重新登录 SSH 后可见。",
                Arrays.asList(Field.text("new_name", "新名称", inst.optString("name")),
                        Field.check("sync_hostname", "同步修改系统主机名（SSH 显示）", true)), "保存", v -> {
            String name = v.optString("new_name").trim();
            if (name.isEmpty()) { toast("名称不能为空"); return; }
            try {
                JSONObject b = base(inst, kind).put("new_name", name).put("sync_hostname", v.optBoolean("sync_hostname", true));
                Api.post(this, "/accounts/" + id + "/instances/rename", b, x -> { renameResult(Api.obj(x)); refresh(); });
            } catch (Exception ignored) { }
        });
    }

    private void renameResult(JSONObject o) {
        JSONObject h = o.optJSONObject("hostname");
        if (h == null || "ok".equals(h.optString("status"))) { toast(h == null ? "已改名" : "已改名，系统主机名已同步"); return; }
        String msg = h.optString("message");
        String cmd = h.optString("manual_cmd", "");
        if ("pending".equals(h.optString("status")) || cmd.isEmpty()) { toast("已改名。" + msg); return; }
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("failed".equals(h.optString("status")) ? "已改名，主机名同步失败" : "已改名，主机名未自动同步")
                .setMessage(msg + "\n\n可 SSH 登录后手动执行：\n" + cmd)
                .setPositiveButton("复制命令", (d, w) -> {
                    android.content.ClipboardManager cm = (android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                    if (cm != null) cm.setPrimaryClip(android.content.ClipData.newPlainText("cmd", cmd));
                    toast("已复制");
                }).setNegativeButton("关闭", null).show();
    }

    // v1.5 实例操作「开放端口」：来源 0.0.0.0/0；填端口后先弹公网警告再提交（与 Web / TG 同一接口）
    private void openPort(JSONObject inst, String kind) {
        String where = "oci".equals(prov) ? "子网安全列表" : "aws".equals(prov) ? "实例关联的全部安全组" : "网卡 / 子网的 NSG";
        form("开放端口", "在「" + inst.optString("name") + "」的" + where + "放行入站端口，来源 0.0.0.0/0。\n每个端口 / 范围一条规则，已存在的跳过；不支持 1-65535。",
                Arrays.asList(Field.text("port", "端口（如 8443 或 80, 443, 8000-8100）", ""),
                        Field.select("protocol", "协议", "tcp", new String[]{"tcp", "udp"}, new String[]{"TCP", "UDP"})), "下一步", v -> {
            String port = v.optString("port").trim();
            if (port.isEmpty()) { toast("请填写端口"); return; }
            String proto = v.optString("protocol", "tcp");
            confirm("⚠️ 对整个互联网开放", "来源 0.0.0.0/0 表示任何人都能访问 " + proto.toUpperCase(Locale.ROOT) + " 端口 " + port
                    + "。\n请确认这些端口上的服务有密码 / 密钥保护并保持更新。", () -> {
                try {
                    JSONObject b = base(inst, kind).put("port", port).put("protocol", proto).put("confirm_public", true);
                    Api.post(this, "/accounts/" + id + "/instances/" + Api.enc(inst.optString("id")) + "/open-port", b, x -> {
                        JSONObject o = Api.obj(x);
                        new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("已开放：新增 " + o.optInt("added") + " 条")
                                .setMessage(o.optString("msg")).setPositiveButton("好的", null).show();
                    });
                } catch (Exception ignored) { }
            });
        });
    }

    private void changeIp(JSONObject inst, String kind) {
        List<Field> f = new ArrayList<>();
        if ("aws".equals(prov) && "vm".equals(kind))
            f.add(Field.select("mode", "方式", "auto", new String[]{"auto", "eip", "stopstart"},
                    new String[]{"自动", "重分配弹性 IP（不停机）", "停机再启动（会中断）"}));
        boolean oci = "oci".equals(prov);
        f.add(Field.text("cidrs", "目标网段（可选，逗号分隔；! 开头 = 排除，如 !10.0.0.0/8）", ""));
        f.add(Field.num("max_tries", "最多尝试次数（指定网段或质量要求时生效）", oci ? "20" : "5"));
        f.add(Field.num("quality_max_risk", "IP 风险分上限（0~100，可选，不合格自动重换）", ""));
        f.add(Field.text("quality_country", "归属国家（可选，如 US 或 US,JP）", ""));
        Api.get(this, "/accounts/" + id + "/ip-change-usage", u -> changeIpForm(inst, kind, f, Api.obj(u)));
    }

    private void changeIpForm(JSONObject inst, String kind, List<Field> f, JSONObject u) {
        String usage = u.has("limit") ? "\n今日已换：手动 " + u.optInt("manual_used") + " 次 · 自动 " + u.optInt("auto_used") + "/" + u.optInt("limit") + " 次" : "";
        form("更换 IP", "当前：" + str(inst, "public_ip", "-") + usage, f, "更换", v -> {
            try {
                JSONObject b = base(inst, kind);
                if (v.has("mode")) b.put("mode", v.getString("mode"));
                if (!v.optString("cidrs").isEmpty()) b.put("cidrs", v.getString("cidrs")).put("max_tries", v.optString("max_tries", "20"));
                if (!v.optString("quality_max_risk").isEmpty()) b.put("quality_max_risk", v.getString("quality_max_risk")).put("max_tries", v.optString("max_tries", "20"));
                if (!v.optString("quality_country").isEmpty()) b.put("quality_country", v.getString("quality_country")).put("max_tries", v.optString("max_tries", "20"));
                Api.post(this, "/accounts/" + id + "/instances/change-ip", b, r -> {
                    JSONObject o = Api.obj(r);
                    if (o.has("task_id")) openTask(o.optInt("task_id")); else toast("新 IP：" + o.optString("new_ip"));
                    refresh();
                });
            } catch (Exception ignored) { }
        });
    }

    private void resizeOci(JSONObject inst) {
        form("修改配置", "Flex 实例可调整 OCPU/内存", Arrays.asList(
                Field.num("ocpus", "OCPU", inst.optString("ocpus", "1")),
                Field.num("memory_gb", "内存 GB", inst.optString("memory_gb", "6"))), "提交", v -> {
            try {
                JSONObject b = base(inst, "vm").put("ocpus", v.optString("ocpus")).put("memory_gb", v.optString("memory_gb"));
                Api.post(this, "/accounts/" + id + "/instances/resize", b, r -> taskOrToast(r, "已提交"));
            } catch (Exception ignored) { }
        });
    }

    private void resizeAzure(JSONObject inst) {
        Api.get(this, "/accounts/" + id + "/azure/sizes?instance_id=" + Api.enc(inst.optString("id")), r -> {
            JSONArray a = Api.arr(r);
            String[] names = new String[a.length()], labels = new String[a.length()];
            for (int i = 0; i < a.length(); i++) {
                JSONObject s = a.optJSONObject(i);
                names[i] = s.optString("name");
                labels[i] = names[i] + " · " + s.optInt("cores") + "C/" + String.format(java.util.Locale.US, "%.1f", s.optInt("memory_mb") / 1024.0) + "G";
            }
            choose("新大小（会重启 VM）", labels, i -> {
                try {
                    Api.post(this, "/accounts/" + id + "/instances/resize", base(inst, "vm").put("size", names[i]),
                            x -> taskOrToast(x, "已提交"));
                } catch (Exception ignored) { }
            });
        });
    }

    private void monitor(JSONObject inst, String kind) {
        form("加入监控", "监控「" + inst.optString("name") + "」，非面板操作导致停止/终止时推送 Telegram 告警。\n连通检测从面板所在服务器发起；跨境时结果反映的是这条线路的连通性。", Arrays.asList(
                Field.check("auto_start", "异常停止时自动启动", false),
                Field.num("check_port", "IP 连通检测端口（0 = 不检测，常用 22）", "0"),
                Field.check("auto_change_ip", "连续 3 次连不上时自动换 IP（并更新已绑定域名）", false)), "保存", v -> {
            try {
                JSONObject b = new JSONObject().put("account_id", id).put("instance_id", inst.optString("id")).put("region", region())
                        .put("kind", kind).put("name", inst.optString("name")).put("state", inst.optString("state"))
                        .put("auto_start", v.optBoolean("auto_start")).put("public_ip", inst.optString("public_ip"))
                        .put("check_port", v.optString("check_port", "0")).put("auto_change_ip", v.optBoolean("auto_change_ip"));
                Api.post(this, "/monitors", b, r -> toast("已加入监控"));
            } catch (Exception ignored) { }
        });
    }

    // ---------------- v1.5：EC2 / Azure VM 创建（对照线上 android-native 的创建实例页） ----------------
    private void ec2Create() {
        Api.get(this, "/accounts/" + id + "/aws/ec2-options", r -> {
            JSONObject o = Api.obj(r);
            JSONObject d = defaults.optJSONObject("aws");
            if (d == null) d = new JSONObject();
            JSONArray types = o.optJSONArray("types");
            List<Field> f = new ArrayList<>();
            f.add(Field.text("name", "名称", "ec2-" + Long.toString(System.currentTimeMillis() / 1000, 36)));
            f.add(types != null && types.length() > 0 ? sel("type", "实例类型", d.optString("type", "t3.micro"), types, false) : Field.text("type", "实例类型", d.optString("type", "t3.micro")));
            f.add(sel("os", "系统", d.optString("os"), o.optJSONArray("os"), false));
            f.add(Field.num("disk_gb", "系统盘 GB (gp3)", d.optString("disk_gb", "10")));
            f.add(Field.text("ports", "额外放行端口（默认只开 22）", d.optString("ports", "")));
            f.add(Field.check("password_login", "生成随机 root 密码（可在「开机密码」查看）", true));
            f.add(scriptField());
            f.add(Field.multi("script", "或直接填写开机脚本（可选）", ""));
            form("创建 EC2（" + region() + "）", null, f, "创建", v -> {
                try { Api.post(this, "/accounts/" + id + "/aws/ec2-create", v.put("region", region()), x -> { created(Api.obj(x)); body.postDelayed(this::refresh, 4000); }); }
                catch (Exception ignored) { }
            });
        });
    }

    private void azureCreate() {
        Api.get(this, "/accounts/" + id + "/azure/locations", r -> {
            JSONObject d = defaults.optJSONObject("azure");
            if (d == null) d = new JSONObject();
            List<Field> f = new ArrayList<>();
            f.add(Field.text("name", "名称", "vm-" + Long.toString(System.currentTimeMillis() / 1000, 36)));
            f.add(sel("location", "区域", Api.pref("azloc_" + id, d.optString("location", "eastasia")), Api.arr(r), false));
            String[] sizes = {"Standard_B1s", "Standard_B1ms", "Standard_B2ats_v2", "Standard_B2pts_v2", "Standard_B2s", "Standard_D2as_v5"};
            String ds = d.optString("size", "Standard_B1s");
            if (!Arrays.asList(sizes).contains(ds)) { sizes = Arrays.copyOf(sizes, sizes.length + 1); sizes[sizes.length - 1] = ds; }
            f.add(Field.select("size", "大小", ds, sizes, null));
            f.add(Field.select("os", "系统", d.optString("os", "debian-12"), new String[]{"debian-12", "ubuntu-24.04", "ubuntu-22.04"}, null));
            f.add(Field.num("disk_gb", "系统盘 GB", d.optString("disk_gb", "30")));
            f.add(Field.select("disk_type", "磁盘类型", "StandardSSD_LRS", new String[]{"StandardSSD_LRS", "Standard_LRS", "Premium_LRS"}, null));
            f.add(Field.text("resource_group", "资源组（留空=新建 名称-rg）", ""));
            f.add(Field.text("ports", "额外放行端口（默认只开 22）", ""));
            f.add(Field.check("ipv6", "同时分配公网 IPv6", false));
            f.add(Field.multi("ssh_key", "SSH 公钥（可选）", d.optString("ssh_key", "")));
            f.add(Field.check("password_login", "生成随机密码（可在「开机密码」查看）", true));
            f.add(scriptField());
            f.add(Field.multi("script", "或直接填写开机脚本（可选）", ""));
            form("创建 Azure VM", "学生订阅免费额度：B1s 750 小时/月。创建约 2–4 分钟，后台执行。", f, "创建", v -> {
                Api.setPref("azloc_" + id, v.optString("location"));
                Api.post(this, "/accounts/" + id + "/azure/create", v, x -> taskOrToast(x, "已创建任务，完成后可在「开机密码」查看密码"));
            });
        });
    }

    // ---------------- Lightsail 创建 ----------------
    private void lightsailCreate() {
        Api.get(this, "/accounts/" + id + "/lightsail/options?" + rq(), r -> {
            JSONObject o = Api.obj(r);
            JSONObject d = defaults.optJSONObject("lightsail");
            if (d == null) d = new JSONObject();
            List<Field> f = new ArrayList<>();
            f.add(Field.text("name", "名称", "ls-" + Long.toString(System.currentTimeMillis() / 1000, 36)));
            f.add(sel("zone", "可用区", d.optString("zone"), o.optJSONArray("zones"), false));
            f.add(sel("blueprint", "系统镜像", d.optString("blueprint"), o.optJSONArray("blueprints"), true));
            f.add(sel("bundle", "套餐", d.optString("bundle"), o.optJSONArray("bundles"), true));
            f.add(Field.select("ip_type", "网络", "dualstack", new String[]{"dualstack", "ipv6"}, new String[]{"IPv4 + IPv6", "仅 IPv6"}));
            f.add(Field.check("password_login", "生成随机 root 密码", true));
            f.add(scriptField());
            f.add(Field.multi("user_data", "或直接填写启动脚本（可选）", ""));
            form("创建 Lightsail", null, f, "创建", v -> {
                try { Api.post(this, "/accounts/" + id + "/lightsail/create", v.put("region", region()), x -> { created(Api.obj(x)); body.postDelayed(this::refresh, 3000); }); }
                catch (Exception ignored) { }
            });
        });
    }

    private Field sel(String k, String label, String def, JSONArray a, boolean objs) {
        int n = a == null ? 0 : a.length();
        String[] ids = new String[n], labels = new String[n];
        for (int i = 0; i < n; i++) {
            if (objs) { ids[i] = a.optJSONObject(i).optString("id"); labels[i] = a.optJSONObject(i).optString("name"); }
            else ids[i] = labels[i] = a.optString(i);
        }
        return Field.select(k, label, def, ids, labels);
    }

    // ---------------- OCI 创建 / 抢机 ----------------
    // 规格标明是否 Always Free（免费额度只在主区域有效）
    static final String[] SHAPES = {"VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro", "VM.Standard.E4.Flex", "VM.Standard3.Flex"};
    static final String[] SHAPE_LABELS = {
            "A1.Flex · ARM · ✅ Always Free（免费号合计 2 OCPU / 12 GB，付费号 4 / 24）",
            "E2.1.Micro · AMD 1/8 OCPU · 1 GB · ✅ Always Free（最多 2 台）",
            "E4.Flex · AMD · 💰 付费，非 Always Free",
            "Standard3.Flex · Intel · 💰 付费，非 Always Free"};
    private void ociCreate(boolean snatch) {
        JSONObject d = defaults.optJSONObject("oci");
        if (d == null) d = new JSONObject();
        LinearLayout c = card(snatch ? "自动抢机" : "创建实例");
        muted(c, snatch ? "容量不足时按间隔重试，成功/失败/停止推送 Telegram。" : "默认值来自 设置 → 默认创建参数");
        String[] shapes = SHAPES;
        List<Field> f = new ArrayList<>(Arrays.asList(
                Field.text("name", "实例名称", "oci-" + Long.toString(System.currentTimeMillis() / 1000, 36)),
                Field.select("shape", "规格", d.optString("shape", shapes[0]), shapes, SHAPE_LABELS),
                Field.num("ocpus", "OCPU", d.optString("ocpus", "4")),
                Field.num("memory_gb", "内存 GB", d.optString("memory_gb", "24")),
                Field.num("disk_gb", "引导卷 GB", d.optString("disk_gb", "50")),
                osImageField(d.optString("os", "Canonical Ubuntu"), str(d, "os_version", "")),
                Field.text("ad", "可用域（留空=第一个）", str(d, "ad", "")),
                Field.text("subnet_id", "子网 OCID（留空=自动）", str(d, "subnet_id", "")),
                Field.multi("ssh_key", "SSH 公钥", str(d, "ssh_key", "")),
                Field.check("ipv6", "分配 IPv6", d.optBoolean("ipv6", false)),
                Field.check("password_login", "生成随机 root 密码（可在「开机密码」查看）", true),
                scriptField(),
                Field.multi("script", "或直接填写开机脚本（可选）", "")));
        if (snatch) {
            f.add(Field.num("interval", "重试间隔秒（≥30）", "60"));
            f.add(Field.num("max_attempts", "最大次数（0=不限）", "0"));
        }
        LinearLayout r = row(c);
        button(r, snatch ? "填写参数并开始抢机" : "填写参数并创建", v -> form(snatch ? "抢机参数" : "创建参数", null, f, snatch ? "开始" : "创建", vals -> {
            try {
                JSONObject create = splitOsImage(new JSONObject(vals.toString()));
                Object interval = create.remove("interval"), maxa = create.remove("max_attempts");
                JSONObject b = new JSONObject().put("region", region()).put("create", create);
                if (snatch) {
                    b.put("interval", interval).put("max_attempts", maxa);
                    Api.post(this, "/accounts/" + id + "/oci/snatch", b, x -> taskOrToast(x, "抢机任务已启动"));
                } else {
                    Api.post(this, "/accounts/" + id + "/oci/create", b, x -> created(Api.obj(x)));
                }
            } catch (Exception e) { toast(e.getMessage()); }
        }));
    }

    // v1.5：OCI「系统 + 版本」—— Field 不支持联动，所以列出全部组合（如「Ubuntu 22.04」），提交时拆成 os / os_version（"" = 最新）
    static final String[][] OCI_OS = {{"Canonical Ubuntu", "Ubuntu", "", "24.04", "22.04", "20.04"}, {"Oracle Linux", "Oracle Linux", "", "9", "8"}};

    static Field osImageField(String os, String ver) {
        List<String> opts = new ArrayList<>(), labels = new ArrayList<>();
        for (String[] o : OCI_OS)
            for (int i = 2; i < o.length; i++) { opts.add(o[0] + "|" + o[i]); labels.add(o[1] + " " + (o[i].isEmpty() ? "最新" : o[i])); }
        String def = os + "|" + (ver == null ? "" : ver);
        if (!opts.contains(def)) {
            boolean known = false;
            for (String[] o : OCI_OS) if (o[0].equals(os)) known = true;
            if (known) { opts.add(def); labels.add(os + " " + ver); }   // 默认值里的版本不在列表里：临时加一个选项
            else def = opts.get(0);                                       // 已移除的系统（如 CentOS）回落到 Ubuntu 最新
        }
        return Field.select("os_image", "系统 / 版本", def, opts.toArray(new String[0]), labels.toArray(new String[0]));
    }

    static JSONObject splitOsImage(JSONObject c) throws Exception {
        Object v = c.remove("os_image");
        if (v != null) {
            String s = v.toString();
            int i = s.indexOf('|');
            c.put("os", i < 0 ? s : s.substring(0, i)).put("os_version", i < 0 ? "" : s.substring(i + 1));
        }
        return c;
    }

    /** 创建成功：随机密码只显示这一次。 */
    private void created(JSONObject o) {
        String pw = o.optString("password", "");
        if (pw.isEmpty() || "null".equals(pw)) { toast("已提交创建：" + o.optString("name")); return; }
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("创建已提交：" + o.optString("name"))
                .setMessage("用户：" + o.optString("username") + "\n密码：" + pw + "\n\n只显示这一次，之后需在 Web 端「开机密码」输入面板密码查看。")
                .setPositiveButton("复制密码", (dd, w) -> {
                    android.content.ClipboardManager cm = (android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                    cm.setPrimaryClip(android.content.ClipData.newPlainText("pw", pw));
                    toast("已复制");
                }).setNegativeButton("关闭", null).show();
    }

    // ---------------- CloudFront（v1.5：缓存刷新 / 编辑 / 启停 / 套餐 / 删除前自动停用） ----------------
    static final String[] CF_TIERS = {"PAYGO", "FREE", "PRO", "BUSINESS", "PREMIUM"};
    static final String[] CF_TIER_NAMES = {"按量付费", "Free $0/月", "Pro $15/月", "Business $200/月", "Premium $1000/月起"};

    static String cfPlanName(JSONObject d) {
        if (d.isNull("plan") || !d.has("plan")) return "套餐未知";
        int i = Arrays.asList(CF_TIERS).indexOf(d.optString("plan"));
        return i >= 0 ? CF_TIER_NAMES[i] : d.optString("plan");
    }

    private void cloudfront() {
        bigButton("＋ 新建分发", v -> form("新建 CloudFront 分发", "部署约 5~15 分钟；默认与 v1.4 相同（不缓存 + 全部边缘节点）", Arrays.asList(
                Field.text("origin", "源站域名（不带 https:// 和路径）", ""),
                Field.select("origin_protocol", "回源协议", "http-only", new String[]{"http-only", "https-only", "match-viewer"}, new String[]{"HTTP", "HTTPS", "跟随访客"}),
                Field.select("price_class", "价格等级", "all", new String[]{"all", "200", "100"}, new String[]{"全部边缘节点", "200（含亚洲）", "100（北美+欧洲）"}),
                Field.select("cache_mode", "缓存模式", "disabled", new String[]{"disabled", "optimized"}, new String[]{"不缓存（反代动态内容）", "缓存优化（静态资源）"}),
                Field.check("compress", "自动压缩", true),
                Field.text("comment", "备注", "")), "创建", vals -> {
            try { Api.post(this, "/accounts/" + id + "/cloudfront", vals.put("op", "create"), x -> { toast("已创建：" + Api.obj(x).optString("domain")); refresh(); }); }
            catch (Exception ignored) { }
        }));
        Api.get(this, "/accounts/" + id + "/cloudfront", r -> {
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card("暂无分发"), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject d = a.optJSONObject(i);
                String did = d.optString("id");
                boolean en = d.optBoolean("enabled");
                LinearLayout c = card(did + "  [" + d.optString("status") + "]");
                text(c, d.optString("domain") + "\n源站：" + join(d.optJSONArray("origins"))
                        + "\n" + (en ? "已启用" : "已停用") + " · " + cfPlanName(d) + " · 价格等级 " + str(d, "price_class", "-")
                        + (d.optString("comment").isEmpty() ? "" : "\n" + d.optString("comment")), 13, false);
                LinearLayout row = row(c);
                button(row, "缓存刷新", v -> cfInvalidate(did));
                button(row, "编辑", v -> cfEdit(did));
                button(row, en ? "停用" : "启用", v -> confirm(en ? "停用分发" : "启用分发", en ? "停用后该域名将无法访问（配置保留，可再启用）。" : "启用 " + did + "？", () -> {
                    try { Api.post(this, "/accounts/" + id + "/cloudfront/toggle", new JSONObject().put("distribution_id", did).put("enabled", !en), x -> { toast(Api.obj(x).optString("message")); refresh(); }); }
                    catch (Exception ignored) { }
                }));
                button(row, "套餐", v -> cfPlan(d));
                button(row, "删除", v -> confirm("删除分发", (en || !"Deployed".equals(d.optString("status")))
                        ? "⚠️ 删除 " + did + "？它当前" + (en ? "仍在启用" : "正在部署") + "：面板会先停用、等待部署完成（通常 5~20 分钟）再自动删除。不可恢复。"
                        : "⚠️ 删除 " + did + "？不可恢复。", () -> Api.del(this, "/accounts/" + id + "/cloudfront/" + Api.enc(did) + "?confirm=true", x -> {
                    JSONObject o = Api.obj(x);
                    if (o.optBoolean("deleted")) toast("已删除"); else taskOrToast(x, "已创建删除任务");
                    refresh();
                })));
            }
        });
    }

    private void cfInvalidate(String did) {
        form("缓存刷新 · " + did, "每行一条路径，留空 = /*。每月前 1000 条免费，/* 只算 1 条。", Arrays.asList(Field.multi("paths", "路径", "/*")), "提交刷新", v -> {
            try {
                Api.post(this, "/accounts/" + id + "/cloudfront/invalidate", new JSONObject().put("distribution_id", did).put("paths", v.optString("paths")), x -> {
                    JSONObject o = Api.obj(x);
                    toast("已提交刷新 " + o.optString("invalidation_id") + "：" + join(o.optJSONArray("paths")));
                });
            } catch (Exception ignored) { }
        });
    }

    private void cfEdit(String did) {
        Api.get(this, "/accounts/" + id + "/cloudfront/" + Api.enc(did) + "/config", r -> {
            JSONObject c = Api.obj(r);
            List<Field> f = new ArrayList<>(Arrays.asList(
                    Field.text("comment", "备注", c.optString("comment")),
                    Field.text("origin_domain", "源站域名", c.optString("origin_domain")),
                    Field.select("price_class", "价格等级", c.optString("price_class"), new String[]{"100", "200", "All"}, null),
                    Field.text("default_root_object", "默认根对象", c.optString("default_root_object"))));
            if (!c.optString("origin_protocol").isEmpty())
                f.add(Field.select("origin_protocol", "回源协议", c.optString("origin_protocol"), new String[]{"http-only", "https-only", "match-viewer"}, null));
            form("编辑分发 · " + did, "保存后重新部署，约几分钟生效", f, "保存", v ->
                    Api.async(this, "PUT", "/accounts/" + id + "/cloudfront/" + Api.enc(did), v, x -> { toast(Api.obj(x).optString("message")); refresh(); }));
        });
    }

    private void cfPlan(JSONObject d) {
        String did = d.optString("id");
        choose("切换套餐（当前：" + cfPlanName(d) + "）", CF_TIER_NAMES, i -> {
            String tier = CF_TIERS[i];
            boolean paid = i >= 2;
            Runnable go = () -> {
                try { Api.post(this, "/accounts/" + id + "/cloudfront/plan", new JSONObject().put("distribution_id", did).put("plan_tier", tier).put("confirm", paid),
                        x -> { toast(Api.obj(x).optString("message")); refresh(); }); }
                catch (Exception ignored) { }
            };
            if (paid) confirm("确认订阅付费套餐", "⚠️ 为分发 " + did + " 订阅 " + CF_TIER_NAMES[i] + "，将立即开始按月计费（价格以 AWS 官网为准）。", go);
            else go.run();
        });
    }

    // ---------------- OCI 安全组（v1.5） ----------------
    private String sgInst;

    private void secgroup() {
        Api.get(this, "/accounts/" + id + "/instances?kind=vm&" + rq(), r -> {
            JSONArray a = Api.arr(r);
            if (a.length() == 0) { muted(card("该区域没有实例"), region()); return; }
            String[] ids = new String[a.length()], names = new String[a.length()];
            for (int i = 0; i < a.length(); i++) { ids[i] = a.optJSONObject(i).optString("id"); names[i] = a.optJSONObject(i).optString("name"); }
            if (sgInst == null || !Arrays.asList(ids).contains(sgInst)) sgInst = Api.pref("sg_" + id, ids[0]);
            if (!Arrays.asList(ids).contains(sgInst)) sgInst = ids[0];
            String cur = names[Arrays.asList(ids).indexOf(sgInst)];
            LinearLayout top = row(body);
            button(top, "实例：" + cur, v -> choose("选择实例", names, i -> { sgInst = ids[i]; Api.setPref("sg_" + id, sgInst); refresh(); }));
            button(top, "＋ 添加规则", v -> sgAdd());
            Api.get(this, "/accounts/" + id + "/security-rules?instance_id=" + Api.enc(sgInst) + "&" + rq(), x -> {
                JSONObject o = Api.obj(x);
                JSONArray rules = o.optJSONArray("rules");
                muted(card("规则作用于实例所在子网的安全列表"), "同子网实例共享；不支持对 0.0.0.0/0 放行全部端口");
                sgRules = rules == null ? new JSONArray() : rules;
                sgFilterBar();
            });
        });
    }

    // ---------- 安全组规则轻量筛选：方向分段切换（始终显示）+ 超过 10 条时显示关键词框 ----------
    private JSONArray sgRules = new JSONArray();
    private String sgDir = "all", sgQuery = "";
    private final List<android.view.View> sgCards = new ArrayList<>();
    private android.widget.TextView sgCount;

    private void sgFilterBar() {
        LinearLayout c = card(null);
        com.google.android.material.button.MaterialButtonToggleGroup g = new com.google.android.material.button.MaterialButtonToggleGroup(this);
        g.setSingleSelection(true);
        g.setSelectionRequired(true);
        String[][] opts = {{"all", "全部"}, {"ingress", "入站"}, {"egress", "出站"}};
        int[] ids = new int[3];
        for (int i = 0; i < 3; i++) {
            com.google.android.material.button.MaterialButton b = new com.google.android.material.button.MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle);
            b.setText(opts[i][1]);
            b.setAllCaps(false);
            b.setPadding(dp(2), b.getPaddingTop(), dp(2), b.getPaddingBottom());
            b.setMinWidth(0);
            b.setMinimumWidth(0);
            ids[i] = android.view.View.generateViewId();
            b.setId(ids[i]);
            g.addView(b, new LinearLayout.LayoutParams(0, -2, 1));
            if (opts[i][0].equals(sgDir)) g.check(ids[i]);
        }
        g.addOnButtonCheckedListener((gg, bid, checked) -> {
            if (!checked) return;
            for (int i = 0; i < 3; i++) if (ids[i] == bid) sgDir = opts[i][0];
            sgRender();
        });
        c.addView(g, new LinearLayout.LayoutParams(-1, -2));
        if (sgRules.length() > 10) {
            com.google.android.material.textfield.TextInputLayout til = inputLayout("筛选", "端口 / IP 或 CIDR / 协议 / 描述", android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
            til.setEndIconMode(com.google.android.material.textfield.TextInputLayout.END_ICON_CLEAR_TEXT);
            android.widget.EditText e = til.getEditText();
            e.setSingleLine(true);
            e.setTextSize(14);
            e.setText(sgQuery);
            e.addTextChangedListener(new android.text.TextWatcher() {
                @Override public void beforeTextChanged(CharSequence q, int x, int y, int z) { }
                @Override public void onTextChanged(CharSequence q, int x, int y, int z) { }
                @Override public void afterTextChanged(android.text.Editable q) { sgQuery = q.toString(); sgRender(); }
            });
            c.addView(til);
        } else sgQuery = "";
        sgCount = muted(c, "");
        sgRender();
    }

    private boolean sgMatch(JSONObject ru) {
        if (!"all".equals(sgDir) && !sgDir.equals(ru.optString("direction"))) return false;
        String q = sgQuery.trim().toLowerCase(Locale.ROOT);
        if (q.isEmpty()) return true;
        String hay = (ru.optString("port") + " " + ru.optString("port_min") + "-" + ru.optString("port_max") + " " + ru.optString("cidr") + " "
                + ru.optString("protocol") + " " + ru.optString("desc")).toLowerCase(Locale.ROOT);
        for (String w : q.split("\\s+")) if (!hay.contains(w)) return false;
        return true;
    }

    private void sgRender() {
        for (android.view.View v : sgCards) body.removeView(v);
        sgCards.clear();
        int shown = 0;
        for (int i = 0; i < sgRules.length(); i++) {
            JSONObject ru = sgRules.optJSONObject(i);
            if (!sgMatch(ru)) continue;
            shown++;
            boolean in = "ingress".equals(ru.optString("direction"));
            boolean pub = in && ("0.0.0.0/0".equals(ru.optString("cidr")) || "::/0".equals(ru.optString("cidr")));
            LinearLayout c = card((in ? "入站 " : "出站 ") + ru.optString("protocol") + " · 端口 " + ru.optString("port") + (pub ? "  ⚠ 公网" : ""));
            sgCards.add((android.view.View) c.getParent());
            muted(c, ru.optString("cidr") + (ru.optString("desc").isEmpty() ? "" : " · " + ru.optString("desc")) + " · " + ru.optString("sl_name"));
            button(row(c), "删除", v -> confirm("删除规则", "删除这条规则？" + (in && "22".equals(ru.optString("port")) ? "\n⚠️ 删除 22 端口规则可能导致无法 SSH 登录。" : ""), () -> {
                try {
                    String p = ru.optString("protocol");
                    String proto = "全部".equals(p) ? "all" : p.toLowerCase(Locale.ROOT);
                    JSONObject b = new JSONObject().put("instance_id", sgInst).put("region", region()).put("sl_id", ru.optString("sl_id"))
                            .put("direction", ru.optString("direction")).put("protocol", proto).put("cidr", ru.optString("cidr"))
                            .put("port_min", ru.opt("port_min")).put("port_max", ru.opt("port_max"));
                    Api.async(this, "DELETE", "/accounts/" + id + "/security-rules", b, y -> { toast("已删除"); refresh(); });
                } catch (Exception ignored) { }
            }));
        }
        if (shown == 0) {
            LinearLayout c = card(sgRules.length() == 0 ? "没有规则" : "没有匹配的规则");
            sgCards.add((android.view.View) c.getParent());
        }
        if (sgCount != null) sgCount.setText(shown == sgRules.length() ? "共 " + shown + " 条规则" : "显示 " + shown + " / " + sgRules.length() + " 条");
    }

    private void sgAdd() {
        form("添加安全规则", "端口可批量：80, 443, 8000-8100（每段一条规则，已存在的跳过）", Arrays.asList(
                Field.select("direction", "方向", "ingress", new String[]{"ingress", "egress"}, new String[]{"入站", "出站"}),
                Field.select("protocol", "协议", "tcp", new String[]{"tcp", "udp", "icmp", "icmpv6", "all"}, new String[]{"TCP", "UDP", "ICMP", "ICMPv6", "全部协议"}),
                Field.text("cidr", "来源 CIDR（出站为目标）", ""),
                Field.multi("ports", "端口（TCP / UDP）", ""),
                Field.text("description", "描述（可选）", "")), "添加", v -> {
            try {
                JSONObject b = new JSONObject(v.toString()).put("instance_id", sgInst).put("region", region());
                String cidr = v.optString("cidr").replace(" ", "");
                Runnable send = () -> Api.post(this, "/accounts/" + id + "/security-rules", b, x -> {
                    JSONObject o = Api.obj(x);
                    toast("已添加 " + o.optInt("added") + " 条" + (o.optInt("skipped") > 0 ? "，跳过已存在 " + o.optInt("skipped") + " 条" : ""));
                    refresh();
                });
                if ("ingress".equals(v.optString("direction")) && ("0.0.0.0/0".equals(cidr) || "::/0".equals(cidr))) {
                    b.put("confirm_public", true);
                    confirm("⚠️ 对整个互联网开放", "来源 " + cidr + " 表示任何人都能访问这些端口。请确认服务有密码 / 密钥保护；只需自己访问时建议填写你的 IP 段。", send);
                } else send.run();
            } catch (Exception ignored) { }
        });
    }

    // ---------------- 配额 ----------------
    // ---------------- OCI 流量：本区域实例本月出站 / 入站 ----------------
    private static String gb(JSONObject o, String k) {
        if (o.isNull(k)) return "-";
        double v = o.optDouble(k, 0);
        return v >= 1024 ? String.format(java.util.Locale.US, "%.2f TB", v / 1024) : String.format(java.util.Locale.US, "%.2f GB", v);
    }

    private void ociTraffic() {
        muted(card("正在读取各实例流量…"), "来自 OCI Monitoring（免费），有 5~15 分钟延迟");
        Api.get(this, "/accounts/" + id + "/oci/traffic-summary?" + rq(), r -> {
            header();
            JSONObject d = Api.obj(r);
            double free = d.optDouble("free_out_gb", 10240), out = d.optDouble("out_gb", 0);
            LinearLayout c = card("本区域本月出站");
            text(c, gb(d, "out_gb") + " / " + gb(d, "free_out_gb"), 24, true);
            muted(c, String.format(java.util.Locale.US, "已用 %.2f%% · 入站 %s（不计费）· %s UTC", free > 0 ? out / free * 100 : 0, gb(d, "in_gb"), d.optString("period")));
            muted(c, "10TB 免费出站按整个租户所有区域合计。需要超量提醒或自动停机，用「流量守护」。");
            JSONArray items = d.optJSONArray("items");
            if (items == null || items.length() == 0) { muted(card("本区域没有实例"), region()); return; }
            java.util.Map<String, android.widget.TextView> gtv = new java.util.HashMap<>();
            java.util.Map<String, LinearLayout> grow = new java.util.HashMap<>();
            for (int i = 0; i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i);
                LinearLayout ic = card(it.optString("name") + " · " + it.optString("state"));
                if (it.has("error")) muted(ic, "读取失败：" + it.optString("error"));
                else text(ic, "出站 " + gb(it, "out_gb") + "    入站 " + gb(it, "in_gb"), 16, true);
                muted(ic, str(it, "public_ip", "-") + " · " + it.optString("shape"));
                gtv.put(it.optString("id"), muted(ic, "流量守护：读取中…"));
                LinearLayout rr = row(ic);
                grow.put(it.optString("id"), rr);
            }
            Api.quiet("/traffic-guards", gr -> {
                JSONArray gs = Api.arr(gr);
                for (int i = 0; i < items.length(); i++) {
                    JSONObject it = items.optJSONObject(i);
                    JSONObject g = null;
                    for (int j = 0; j < gs.length(); j++)
                        if (gs.optJSONObject(j).optInt("account_id") == id && it.optString("id").equals(gs.optJSONObject(j).optString("instance_id"))) g = gs.optJSONObject(j);
                    android.widget.TextView tv = gtv.get(it.optString("id"));
                    LinearLayout rr = grow.get(it.optString("id"));
                    if (tv == null || rr == null) continue;
                    if (g == null) { tv.setText("流量守护：未设置"); button(rr, "设置守护", v -> traffic(it, "vm")); continue; }
                    tv.setText("流量守护：" + (g.optInt("enabled", 1) == 1 ? str(g, "status_text", "正常") : "已关闭") + " · " + str(g, "last_gb", "-") + " / " + str(g, "limit_gb", "-") + " GB"
                            + ("stop".equals(g.optString("action")) ? " · 超限停机" : " · 只推送"));
                    int gid = g.optInt("id");
                    button(rr, "编辑守护", v -> traffic(it, "vm"));
                    button(rr, "立即检查", v -> Api.post(this, "/traffic-guards/" + gid + "/check", null, x -> { toast("已检查"); refresh(); }));
                    button(rr, "删除守护", v -> confirm("删除规则", "删除这台实例的流量守护？", () -> Api.del(this, "/traffic-guards/" + gid, x -> { toast("已删除"); refresh(); })));
                }
            });
        });
    }

    private void quota(boolean force) {
        muted(card("正在逐区域查询…"), "串行查询以避免限流，约 10–30 秒，结果缓存 6 小时");
        Api.get(this, "/accounts/" + id + "/quotas" + (force ? "?refresh=true" : ""), r -> {
            header();
            JSONObject q = Api.obj(r);
            JSONObject v = q.optJSONObject("standard_vcpu"), cf = q.optJSONObject("cloudfront_distributions");
            LinearLayout c1 = card("Standard vCPU 上限");
            text(c1, v == null ? "-" : v.optString("value") + " " + v.optString("unit"), 26, true);
            muted(c1, "全区域最大值，来自 " + (v == null ? "-" : v.optString("region")) + "（L-1216C47A）");
            LinearLayout c2 = card("CloudFront 分发数上限");
            text(c2, cf == null ? "-" : str(cf, "value", "-") + " " + cf.optString("unit"), 26, true);
            muted(c2, "每账号（L-24B04930）· 更新于 " + q.optString("updated_at"));
            bigButton("重新查询", x -> { header(); quota(true); });
        });
    }

    // ---------------- 回收站估算 ----------------
    private void recycle() {
        LinearLayout wait = card("正在扫描闲置资源…");
        muted(wait, "仅用免费的 EC2/Lightsail API；账单数据只读缓存，不调用 Cost Explorer");
        Api.get(this, "/accounts/" + id + "/recycle?" + rq(), r -> {
            header();
            JSONObject d = Api.obj(r);
            JSONArray items = d.optJSONArray("items");
            int n = items == null ? 0 : items.length();
            LinearLayout c = card("闲置资源月费估算");
            text(c, "$" + d.optString("monthly_total"), 26, true);
            muted(c, "区域 " + d.optString("region") + " · " + n + " 项 · 按公示单价估算，实际以账单为准");
            LinearLayout b = card("账单参考（缓存）");
            text(b, d.isNull("month_to_date") ? "—" : "$" + d.optString("month_to_date"), 22, true);
            muted(b, "本月已产生 · 数据更新于 " + d.optString("billing_updated_at"));
            if (!d.isNull("credit_remaining")) {
                String m = d.isNull("credit_months_for_idle") ? "" : "，仅闲置资源可再扣约 " + d.optString("credit_months_for_idle") + " 个月";
                muted(b, "Credit 余 $" + d.optString("credit_remaining") + m);
            }
            if (n == 0) { muted(card("明细"), "没有闲置计费资源"); return; }
            for (int i = 0; i < n; i++) {
                JSONObject it = items.optJSONObject(i);
                LinearLayout ic = card(it.optString("name") + "  $" + it.optString("monthly") + "/月");
                muted(ic, it.optString("detail"));
                muted(ic, it.optString("tip"));
            }
        });
    }

    // ---------------- 账单 ----------------
    private void billing(boolean force) {
        Api.get(this, "/accounts/" + id + "/billing" + (force ? "?force=true" : ""), r -> {
            JSONObject b = Api.obj(r);
            LinearLayout c = card("本月费用");
            boolean noCache = b.optBoolean("no_cache");
            text(c, (noCache ? "—" : b.optString("total")) + " " + b.optString("currency"), 26, true);
            muted(c, b.optString("period") + " · 数据更新于 " + b.optString("updated_at"));
            if (noCache) muted(c, "尚无缓存：将在 " + b.optString("next_refresh") + " 自动查询，或手动刷新（收费）");
            boolean aws = "aws".equals(prov);
            if (aws) {
                muted(c, "AWS 每月仅 15 号与月末自动查询（$0.01/次）。下次：" + b.optString("next_refresh") + "，本月已调用 " + b.optInt("ce_calls_this_month") + " 次");
                LinearLayout rr = row(c);
                button(rr, "手动刷新（约 $0.02）", v -> confirm("手动刷新", "将调用 Cost Explorer API（$0.01/次）", () -> { header(); billing(true); }));
            }
            LinearLayout s = card("按服务");
            JSONArray sv = b.optJSONArray("services");
            StringBuilder sb = new StringBuilder();
            for (int i = 0; sv != null && i < sv.length(); i++)
                sb.append(sv.optJSONObject(i).optString("service")).append("：").append(sv.optJSONObject(i).optString("amount")).append("\n");
            text(s, sb.length() == 0 ? "本月暂无费用" : sb.toString().trim(), 13, false);
            credits();
        });
    }

    // ================= v1.4：Credit 与教育优惠 / Azure 订阅 =================
    static String money(JSONObject o, String k) { return o == null || !o.has(k) || o.isNull(k) ? "—" : "$" + String.format(Locale.US, "%.2f", o.optDouble(k)); }

    private void credits() {
        Api.get(this, "/accounts/" + id + "/credit-summary", r -> {
            JSONObject s = Api.obj(r);
            LinearLayout c = card("Credit 与优惠");
            JSONArray al = s.optJSONArray("alerts");
            for (int i = 0; al != null && i < al.length(); i++) {
                JSONObject a = al.optJSONObject(i);
                text(c, "⏰ " + a.optString("name") + " " + (a.optInt("days_left") == 0 ? "今天到期" : "还剩 " + a.optInt("days_left") + " 天")
                        + "（" + a.optString("date") + (a.optBoolean("estimated") ? "，估算" : "") + "）", 13, true);
            }
            String src = "manual".equals(s.optString("used_source")) ? "手动填写" : "billing".equals(s.optString("used_source")) ? "按账单估算" : "估不出";
            text(c, "总额 " + money(s, "credit_total") + (s.optBoolean("credit_total_manual") ? "（手动设置）" : "") + "\n已用 " + money(s, "used") + "（" + src + "）\n剩余 " + money(s, "remaining"), 15, false);
            muted(c, "估算依据：" + str(s, "estimate_note", "-") + ("aws".equals(prov) ? "。AWS 只读账单缓存，不额外调用 Cost Explorer。" : "。先到期的先抵扣。"));
            JSONArray items = s.optJSONArray("items");
            for (int i = 0; items != null && i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i);
                LinearLayout ic = card(it.optString("name"));
                text(ic, "初始 " + money(it, "amount") + " · 已用 " + money(it, "used") + ("manual".equals(it.optString("used_source")) ? "（手填）" : "")
                        + " · 剩余 " + money(it, "remaining") + "\n到期：" + str(it, "expire_date", "-")
                        + (it.has("days_left") && !it.isNull("days_left") ? (it.optBoolean("expired") ? "（已过期）" : "（剩 " + it.optInt("days_left") + " 天）") : ""), 13, false);
                LinearLayout ir = row(ic);
                int cid = it.optInt("id");
                button(ir, "编辑", v -> creditForm(it));
                button(ir, "删除", v -> confirm("删除 Credit", it.optString("name"), () -> Api.del(this, "/accounts/" + id + "/credits-manual/" + cid, x -> refresh())));
            }
            LinearLayout info = card("账号信息");
            text(info, "云上创建：" + (s.isNull("cloud_created_at") ? "未填写" : s.optString("cloud_created_at") + "（已存活 " + s.optInt("age_days") + " 天）"), 13, false);
            JSONObject edu = s.optJSONObject("edu");
            if (edu != null) text(info, "教育优惠到期：" + (edu.isNull("expires_at") ? "未知" : edu.optString("expires_at") + (edu.optBoolean("estimated") ? "（估算）" : "")
                    + " · 剩 " + edu.optInt("days_left") + " 天") + "\n" + edu.optString("basis"), 13, false);
            LinearLayout br = row(c);
            button(br, "＋ 添加 Credit", v -> creditForm(null));
            button(br, "设置总额", v -> form("Credit 总额", "留空 = 各条 Credit 之和", Arrays.asList(
                    Field.num("credit_total", "总额 USD", s.optBoolean("credit_total_manual") ? s.optString("credit_total") : "")), "保存",
                    vals -> Api.async(this, "PUT", "/accounts/" + id + "/credit-total", vals, x -> refresh())));
            button(row(info), "设置日期", v -> datesForm(s));
        });
    }

    private void creditForm(JSONObject it) {
        boolean edit = it != null;
        form(edit ? "编辑 Credit" : "添加 Credit", "已用额度留空 = 按账单估算；30 天内到期会提醒并推送 Telegram", Arrays.asList(
                Field.text("name", "名称", edit ? it.optString("name") : "Credit"),
                Field.num("amount", "初始额度 USD", edit ? it.optString("amount") : ""),
                Field.num("used_manual", "已用额度（可选）", edit && !it.isNull("used_manual") ? it.optString("used_manual") : ""),
                Field.text("start_date", "起始日期 YYYY-MM-DD（可选）", edit ? str(it, "start_date", "") : ""),
                Field.text("expire_date", "到期日期 YYYY-MM-DD", edit ? str(it, "expire_date", "") : "")), "保存", vals -> {
            if (edit) Api.async(this, "PUT", "/accounts/" + id + "/credits-manual/" + it.optInt("id"), vals, x -> refresh());
            else Api.post(this, "/accounts/" + id + "/credits-manual", vals, x -> refresh());
        });
    }

    private void datesForm(JSONObject s) {
        List<Field> f = new ArrayList<>();
        f.add(Field.text("cloud_created_at", "云账号创建日期 YYYY-MM-DD", str(s, "cloud_created_at", "")));
        if ("azure".equals(prov)) f.add(Field.text("edu_expires_at", "教育优惠到期日（留空 = 创建日期 + 12 个月估算）", str(acc, "edu_expires_at", "")));
        form("账号日期", "用于计算存活天数与教育优惠到期", f, "保存", vals -> Api.async(this, "PATCH", "/accounts/" + id, vals, x -> {
            try { acc.put("cloud_created_at", vals.optString("cloud_created_at")); if (vals.has("edu_expires_at")) acc.put("edu_expires_at", vals.optString("edu_expires_at")); } catch (Exception ignored) { }
            refresh();
        }));
    }

    private void subscription() {
        Api.get(this, "/accounts/" + id + "/azure/subscription", r -> {
            JSONObject s = Api.obj(r);
            LinearLayout c = card("订阅（只读）");
            if (s.has("error")) text(c, "❌ " + s.optString("error"), 13, false);
            else text(c, "名称：" + str(s, "display_name", "-") + "\n状态：" + str(s, "state", "-") + "\n类型：" + str(s, "offer", "-")
                    + "\nSpending limit：" + str(s, "spending_limit", "-") + "\nquotaId：" + str(s, "quota_id", "-") + "\n订阅 ID：" + str(s, "subscription_id", "-"), 13, false);
            JSONObject edu = s.optJSONObject("edu");
            LinearLayout e = card("教育优惠");
            if (edu != null) text(e, edu.isNull("expires_at") ? "未知" : edu.optString("expires_at") + (edu.optBoolean("estimated") ? "（估算）" : "") + " · 剩 " + edu.optInt("days_left") + " 天", 15, true);
            if (edu != null) muted(e, edu.optString("basis"));
            if (!s.isNull("age_days") && s.has("age_days")) muted(e, "账号已存活 " + s.optInt("age_days") + " 天");
        });
    }

    // ================= Foundry（Azure AI Services） =================
    private String fdRegion = "swedencentral";

    private void foundry() {
        Api.get(this, "/accounts/" + id + "/azure/foundry?region=" + fdRegion, r -> {
            JSONObject d = Api.obj(r);
            LinearLayout top = card("Foundry（Azure AI）");
            muted(top, "创建 AI Services 资源并部署 GPT 等模型，拿到 Endpoint 和 Key 可按 OpenAI 接口调用。按调用量计费，会消耗订阅额度。\n当前区域：" + fdRegion);
            LinearLayout tr = row(top);
            JSONArray regs = d.optJSONArray("regions");
            button(tr, "切换区域", v -> {
                if (regs == null) return;
                String[] l = new String[regs.length()];
                for (int i = 0; i < l.length; i++) l[i] = regs.optString(i);
                choose("区域", l, idx -> { fdRegion = l[idx]; refresh(); });
            });
            button(tr, "＋ 新建资源并部署", v -> fdDeploy(null, d.optJSONArray("models")));
            JSONArray res = d.optJSONArray("resources");
            if (res == null || res.length() == 0) muted(card("AI 资源"), "订阅里还没有 AI Services / Azure OpenAI 资源");
            for (int i = 0; res != null && i < res.length(); i++) {
                JSONObject x = res.optJSONObject(i);
                LinearLayout c = card(x.optString("name") + "  [" + x.optString("kind") + "]");
                StringBuilder sb = new StringBuilder(x.optString("region") + " · " + x.optString("resource_group") + "\n" + str(x, "endpoint", "-"));
                JSONArray deps = x.optJSONArray("deployments");
                for (int j = 0; deps != null && j < deps.length(); j++) {
                    JSONObject dp = deps.optJSONObject(j);
                    sb.append("\n• ").append(dp.optString("name")).append("：").append(dp.optString("model")).append(" ").append(dp.optString("version"))
                            .append(" · ").append(dp.optString("sku")).append(" ").append(dp.optInt("capacity")).append("K TPM");
                }
                text(c, sb.toString(), 13, false);
                LinearLayout rr = row(c);
                String rid = x.optString("id");
                button(rr, "Endpoint / Key", v -> confirm("查看密钥", "Key 等同于调用权限，泄露会被盗刷额度。确定显示？", () -> {
                    try { Api.post(this, "/accounts/" + id + "/azure/foundry", new JSONObject().put("op", "keys").put("resource_id", rid).put("confirm", true), k -> {
                        JSONObject o = Api.obj(k);
                        String txt = "base_url：" + o.optString("openai_base_url") + "\nKey：" + o.optString("key1");
                        new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("Endpoint / Key").setMessage(txt + "\n\nmodel 填部署名。")
                                .setPositiveButton("复制 Key", (dd, w) -> {
                                    android.content.ClipboardManager cm = (android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                                    if (cm != null) cm.setPrimaryClip(android.content.ClipData.newPlainText("key", o.optString("key1")));
                                    toast("已复制");
                                }).setNegativeButton("关闭", null).show();
                    }); } catch (Exception ignored) { }
                }));
                button(rr, "部署模型", v -> fdDeploy(rid, d.optJSONArray("models")));
                if (deps != null && deps.length() > 0) button(rr, "删除部署", v -> {
                    String[] l = new String[deps.length()];
                    for (int j = 0; j < l.length; j++) l[j] = deps.optJSONObject(j).optString("name");
                    choose("删除哪个部署", l, idx -> confirm("删除部署", "删除「" + l[idx] + "」？用这个部署名的调用会立刻失败。", () -> {
                        try { Api.post(this, "/accounts/" + id + "/azure/foundry", new JSONObject().put("op", "delete_deployment").put("resource_id", rid).put("deployment", l[idx]).put("confirm", true), k -> { toast("已删除"); refresh(); }); }
                        catch (Exception ignored) { }
                    }));
                });
                button(rr, "删除资源", v -> confirm("删除 AI 资源", "删除「" + x.optString("name") + "」及其全部部署？Key 立刻失效，48 小时内不能同名重建。", () -> {
                    try { Api.post(this, "/accounts/" + id + "/azure/foundry", new JSONObject().put("op", "delete_resource").put("resource_id", rid).put("confirm", true), k -> { toast("已删除"); refresh(); }); }
                    catch (Exception ignored) { }
                }));
            }
            LinearLayout qc = card("模型配额 · " + fdRegion);
            JSONArray q = d.optJSONArray("quotas");
            StringBuilder qs = new StringBuilder();
            for (int i = 0; q != null && i < q.length(); i++) qs.append(q.optJSONObject(i).optString("name")).append("：").append(q.optJSONObject(i).optInt("used")).append(" / ").append(q.optJSONObject(i).optInt("limit")).append("\n");
            text(qc, qs.length() == 0 ? "该区域没有可用配额" : qs.toString().trim(), 12, false);
        });
    }

    private void fdDeploy(String rid, JSONArray models) {
        List<Field> f = new ArrayList<>();
        if (rid == null) {
            f.add(Field.text("name", "资源名称（全局唯一，字母数字和 -）", ""));
            f.add(Field.text("resource_group", "资源组（可选）", ""));
        }
        int n = models == null ? 0 : models.length();
        String[] mv = new String[Math.max(n, 1)], ml = new String[Math.max(n, 1)];
        if (n == 0) { mv[0] = "gpt-4o-mini|"; ml[0] = "gpt-4o-mini"; }
        for (int i = 0; i < n; i++) { JSONObject m = models.optJSONObject(i); mv[i] = m.optString("name") + "|" + m.optString("version"); ml[i] = m.optString("name") + " " + m.optString("version"); }
        f.add(Field.select("model", "模型", mv[0], mv, ml));
        f.add(Field.select("sku", "部署类型", "GlobalStandard", new String[]{"GlobalStandard", "Standard"}, new String[]{"Global Standard", "Standard（仅本区域）"}));
        f.add(Field.num("capacity", "容量（千 TPM）", "10"));
        f.add(Field.text("deployment", "部署名（可选，默认模型名）", ""));
        form(rid == null ? "新建资源并部署模型（" + fdRegion + "）" : "部署模型", "容量受配额限制；完成后在「Endpoint / Key」里拿调用地址。", f, "开始部署", v -> {
            try {
                String[] mm = v.optString("model").split("\\|", -1);
                JSONObject b = new JSONObject().put("op", "deploy").put("model", mm[0]).put("sku", v.optString("sku")).put("capacity", v.optString("capacity", "10"));
                if (mm.length > 1 && !mm[1].isEmpty()) b.put("version", mm[1]);
                if (!v.optString("deployment").isEmpty()) b.put("deployment", v.optString("deployment"));
                if (rid != null) b.put("resource_id", rid);
                else {
                    if (!v.optString("name").matches("[a-zA-Z0-9][a-zA-Z0-9-]{1,62}")) { toast("资源名称 2~63 位，只能含字母、数字和 -"); return; }
                    b.put("name", v.optString("name")).put("region", fdRegion);
                    if (!v.optString("resource_group").isEmpty()) b.put("resource_group", v.optString("resource_group"));
                }
                Api.post(this, "/accounts/" + id + "/azure/foundry", b, x -> taskOrToast(x, "已提交"));
            } catch (Exception ignored) { }
        });
    }

    // ================= v1.2 / v1.3 =================
    private void migrate(JSONObject inst) {
        Api.get(this, "/accounts", r -> {
            JSONArray a = Api.arr(r);
            List<JSONObject> ts = new ArrayList<>();
            for (int i = 0; i < a.length(); i++) if (a.optJSONObject(i).optInt("id") != id && !"greencloud".equals(a.optJSONObject(i).optString("provider"))) ts.add(a.optJSONObject(i));
            if (ts.isEmpty()) { toast("至少需要两个云账号"); return; }
            String[] labels = new String[ts.size()];
            for (int i = 0; i < labels.length; i++) labels[i] = MainActivity.pname(ts.get(i).optString("provider")) + " · " + ts.get(i).optString("name");
            choose("迁移到哪个账号", labels, idx -> {
                JSONObject to = ts.get(idx);
                String tp = to.optString("provider");
                List<Field> f = new ArrayList<>();
                f.add(Field.text("name", "新实例名称", inst.optString("name") + "-new"));
                if ("oci".equals(tp)) {
                    f.add(Field.select("shape", "规格", "VM.Standard.A1.Flex", new String[]{"VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"}, new String[]{SHAPE_LABELS[0], SHAPE_LABELS[1]}));
                    f.add(Field.num("ocpus", "OCPU", "1"));
                    f.add(Field.num("memory_gb", "内存 GB", "6"));
                    f.add(Field.num("disk_gb", "系统盘 GB", "50"));
                    f.add(osImageField("Canonical Ubuntu", ""));
                } else if ("aws".equals(tp)) {
                    f.add(Field.text("type", "实例类型", "t3.micro"));
                    f.add(Field.select("os", "系统", "debian-12", new String[]{"debian-12", "ubuntu-24.04"}, new String[]{"Debian 12", "Ubuntu 24.04"}));
                    f.add(Field.num("disk_gb", "系统盘 GB", "10"));
                } else {
                    f.add(Field.text("location", "区域", "eastasia"));
                    f.add(Field.text("size", "大小", "Standard_B1s"));
                    f.add(Field.select("disk_type", "磁盘", "Premium_LRS", new String[]{"Premium_LRS", "StandardSSD_LRS"}, new String[]{"Premium SSD（免费 P6）", "Standard SSD"}));
                    f.add(Field.num("disk_gb", "系统盘 GB", "64"));
                }
                f.add(Field.check("switch_dns", "完成后把域名切到新 IP", true));
                f.add(Field.check("copy_monitor", "复制监控设置", true));
                f.add(Field.check("stop_source", "完成后停掉源实例（不删除）", false));
                form("迁移到 " + to.optString("name"), "用开机脚本在目标账号重建，⚠️ 不复制磁盘数据。", f, "开始迁移", v -> {
                    try {
                        JSONObject create = splitOsImage(new JSONObject(v.toString()));
                        for (String k : new String[]{"switch_dns", "copy_monitor", "stop_source"}) create.remove(k);
                        JSONObject b = new JSONObject().put("from_account_id", id).put("from_region", region()).put("instance_id", inst.optString("id"))
                                .put("name", inst.optString("name")).put("to_account_id", to.optInt("id")).put("create", create)
                                .put("switch_dns", v.optBoolean("switch_dns")).put("copy_monitor", v.optBoolean("copy_monitor")).put("stop_source", v.optBoolean("stop_source"));
                        if (!"azure".equals(tp)) b.put("region", Api.pref("region_" + to.optInt("id"), str(to, "region", "")));
                        Api.post(this, "/migrate", b, x -> taskOrToast(x, "已提交"));
                    } catch (Exception ignored) { }
                });
            });
        });
    }

    private void traffic(JSONObject inst, String kind) {
        trafficDialog(id, prov, region(), inst.optString("id"), inst.optString("name"), kind, "traffic".equals(tab) ? this::refresh : null);
    }

    // ======================= 实例附加操作（同 Web v16Ops / instOp） =======================
    private JSONObject rb() throws Exception { return new JSONObject().put("region", region()); }

    /** OCI 引导卷：查看、扩容、调性能，可选扩容后自动扩根分区。 */
    private void bootVol(JSONObject inst, String kind) {
        toast("读取引导卷…");
        Api.get(this, "/accounts/" + id + "/oci/boot-volume?instance_id=" + Api.enc(inst.optString("id")) + "&" + rq(), r -> {
            JSONObject bv = Api.obj(r);
            String[] vp = {"10", "20", "30", "40", "50", "60", "70", "80", "90", "100", "110", "120"};
            form("引导卷 · " + inst.optString("name"), "名称：" + bv.optString("name") + "\n大小：" + bv.optString("size_gb") + " GB · 性能 " + bv.optString("vpus_per_gb") + " VPU/GB · " + bv.optString("state")
                            + "\n10 = 均衡（免费额度内），20+ 为高性能，按量计费。总免费额度 200GB。", Arrays.asList(
                    Field.num("size_gb", "扩容到 GB（只能变大，留空不改）", ""),
                    Field.select("vpus_per_gb", "性能 VPU/GB", bv.optString("vpus_per_gb", "10"), vp, null),
                    Field.check("grow", "扩容后通过 Run Command 自动扩展根分区（需 Oracle Cloud Agent 插件）", true)), "提交", v -> {
                try {
                    JSONObject b = base(inst, kind).put("vpus_per_gb", v.optString("vpus_per_gb")).put("grow", v.optBoolean("grow"));
                    if (!v.optString("size_gb").isEmpty()) b.put("size_gb", v.optString("size_gb"));
                    Api.post(this, "/accounts/" + id + "/oci/boot-volume", b, x -> {
                        JSONObject o = Api.obj(x);
                        JSONObject g = o.optJSONObject("grow");
                        toast(g != null ? "已扩容；扩分区：" + ("ok".equals(g.optString("status")) ? "完成" : g.optString("message")) : str(o, "hint", "已提交"));
                    });
                } catch (Exception ignored) { }
            });
        });
    }

    /** OCI 附加 IP：辅助私网 IP、辅助网卡、预留公网 IP。 */
    private void ociIps(JSONObject inst) {
        toast("读取网卡与 IP…");
        Api.get(this, "/accounts/" + id + "/oci/ips?instance_id=" + Api.enc(inst.optString("id")) + "&" + rq(), r -> {
            JSONObject d = Api.obj(r);
            List<String> labels = new ArrayList<>();
            List<Runnable> acts = new ArrayList<>();
            StringBuilder sb = new StringBuilder();
            JSONArray vnics = d.optJSONArray("vnics");
            for (int i = 0; vnics != null && i < vnics.length(); i++) {
                JSONObject v = vnics.optJSONObject(i);
                boolean pri = v.optBoolean("primary");
                sb.append(pri ? "主网卡" : "辅助网卡").append(" · ").append(v.optString("name")).append("\n");
                JSONArray ips = v.optJSONArray("ips");
                for (int j = 0; ips != null && j < ips.length(); j++) {
                    JSONObject ip = ips.optJSONObject(j);
                    JSONObject pub = ip.optJSONObject("public");
                    sb.append("  ").append(ip.optString("ip")).append(ip.optBoolean("primary") ? "（主）" : "").append(" → ")
                            .append(pub == null ? "-" : pub.optString("ip") + ("RESERVED".equals(pub.optString("lifetime")) ? "（预留）" : "（临时）")).append("\n");
                    if (!ip.optBoolean("primary")) {
                        String pid = ip.optString("id");
                        labels.add("删除辅助 IP " + ip.optString("ip"));
                        acts.add(() -> confirm("删除辅助 IP", "删除这个辅助私网 IP（及其公网 IP）？", () -> ipOp(inst, "delete_private", "private_ip_id", pid)));
                    }
                }
                if (pri) { String vid = v.optString("vnic_id"); labels.add("＋ 主网卡添加辅助 IP"); acts.add(() -> ipOp(inst, "add_secondary", "vnic_id", vid)); }
                else { String aid = v.optString("attachment_id"); labels.add("卸载辅助网卡 " + v.optString("name")); acts.add(() -> confirm("卸载辅助网卡", "卸载后该网卡上的 IP 全部释放。确定？", () -> ipOp(inst, "detach_vnic", "attachment_id", aid))); }
            }
            labels.add("＋ 添加辅助网卡"); acts.add(() -> ipOp(inst, "attach_vnic", null, null));
            sb.append("\n预留公网 IP（换机 / 重装后 IP 不变）：\n");
            JSONArray res = d.optJSONArray("reserved");
            if (res == null || res.length() == 0) sb.append("  暂无\n");
            for (int i = 0; res != null && i < res.length(); i++) {
                JSONObject x = res.optJSONObject(i);
                String rid = x.optString("id"), ip = x.optString("ip");
                sb.append("  ").append(ip).append(x.optBoolean("assigned") ? "（已绑定）" : "（未绑定）").append("\n");
                if (x.optBoolean("assigned")) { labels.add("解绑预留 IP " + ip); acts.add(() -> confirm("解绑预留 IP", "解绑后会自动给实例分配一个新的临时公网 IP。确定？", () -> ipOp(inst, "unassign_reserved", "public_ip_id", rid))); }
                else {
                    labels.add("把 " + ip + " 绑到本机");
                    acts.add(() -> confirm("绑定预留 IP", "把 " + ip + " 绑到「" + inst.optString("name") + "」？当前临时公网 IP 会被释放。", () -> {
                        try { Api.post(this, "/accounts/" + id + "/oci/ips", rb().put("instance_id", inst.optString("id")).put("op", "assign_reserved").put("public_ip_id", rid).put("ip", ip), y -> ipDone(y, inst)); }
                        catch (Exception ignored) { }
                    }));
                    labels.add("删除预留 IP " + ip); acts.add(() -> confirm("删除预留 IP", "删除后这个 IP 无法找回。确定？", () -> ipOp(inst, "delete_reserved", "public_ip_id", rid)));
                }
            }
            labels.add("＋ 新建预留 IP"); acts.add(() -> ipOp(inst, "create_reserved", null, null));
            sb.append("\n辅助 IP / 辅助网卡需要在系统内配置后才生效（完成后会给出命令）。");
            new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("附加 IP · " + inst.optString("name")).setMessage(sb.toString())
                    .setPositiveButton("操作…", (dd, w) -> choose("选择操作", labels.toArray(new String[0]), k -> acts.get(k).run()))
                    .setNegativeButton("关闭", null).show();
        });
    }

    private void ipOp(JSONObject inst, String op, String k, String v) {
        try {
            JSONObject b = rb().put("instance_id", inst.optString("id")).put("op", op);
            if (k != null) b.put(k, v);
            Api.post(this, "/accounts/" + id + "/oci/ips", b, y -> ipDone(y, inst));
        } catch (Exception ignored) { }
    }

    private void ipDone(Object y, JSONObject inst) {
        String hint = str(Api.obj(y), "hint", "");
        if (!hint.isEmpty()) new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("已完成").setMessage(hint)
                .setPositiveButton("复制", (d, w) -> copy("hint", hint)).setNegativeButton("知道了", (d, w) -> ociIps(inst)).show();
        else { toast("已完成"); ociIps(inst); }
    }

    /** Azure 磁盘：系统盘 / 数据盘扩容、换类型、调性能层。 */
    private void azDisks(JSONObject inst) {
        toast("读取磁盘…");
        Api.get(this, "/accounts/" + id + "/azure/disks?instance_id=" + Api.enc(inst.optString("id")), r -> {
            JSONObject d = Api.obj(r);
            JSONArray ks = d.optJSONArray("disks");
            int n = ks == null ? 0 : ks.length();
            String[] labels = new String[n];
            for (int i = 0; i < n; i++) {
                JSONObject k = ks.optJSONObject(i);
                labels[i] = ("os".equals(k.optString("role")) ? "系统盘" : "数据盘 LUN " + k.optString("lun")) + " · " + k.optString("size_gb") + " GB · " + str(k, "sku", "-") + " · " + str(k, "tier", "-");
            }
            if (n == 0) { info("磁盘 · " + inst.optString("name"), "没有磁盘\n" + d.optString("hint")); return; }
            new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("磁盘 · " + inst.optString("name") + "（点选调整）")
                    .setItems(labels, (dd, w) -> azDiskEdit(inst, d, ks.optJSONObject(w))).setNegativeButton("关闭", null).show();
            if (!d.optString("hint").isEmpty()) toast(d.optString("hint"));
        });
    }

    private void azDiskEdit(JSONObject inst, JSONObject d, JSONObject k) {
        JSONArray sk = d.optJSONArray("skus"), tr = d.optJSONArray("tiers");
        String[] skus = new String[sk == null ? 0 : sk.length()];
        for (int i = 0; i < skus.length; i++) skus[i] = sk.optString(i);
        String[] tiers = new String[(tr == null ? 0 : tr.length()) + 1], tl = new String[tiers.length];
        tiers[0] = ""; tl[0] = "不变";
        for (int i = 1; i < tiers.length; i++) tiers[i] = tl[i] = tr.optString(i - 1);
        List<Field> f = new ArrayList<>();
        f.add(Field.num("size_gb", "大小 GB（只能变大，留空不改；当前 " + k.optString("size_gb") + "）", ""));
        if (skus.length > 0) f.add(Field.select("sku", "类型", k.optString("sku"), skus, null));
        f.add(Field.select("tier", "Premium 性能层（只对 Premium SSD 有效）", "", tiers, tl));
        form("调整 " + k.optString("name"), null, f, "提交", v -> {
            try {
                JSONObject b = new JSONObject().put("instance_id", inst.optString("id")).put("disk_id", k.optString("id"));
                if (!v.optString("size_gb").isEmpty()) b.put("size_gb", v.optString("size_gb"));
                if (v.has("sku") && !v.optString("sku").equals(k.optString("sku"))) b.put("sku", v.optString("sku"));
                if (!v.optString("tier").isEmpty()) b.put("tier", v.optString("tier"));
                Api.post(this, "/accounts/" + id + "/azure/disks", b, x -> { toast(str(Api.obj(x), "hint", "已调整")); azDisks(inst); });
            } catch (Exception ignored) { }
        });
    }

    /** Lightsail 防火墙：查看已开放端口、关闭、开放（0.0.0.0/0 二次确认）。 */
    private void lsPorts(JSONObject inst) {
        Api.get(this, "/accounts/" + id + "/lightsail/ports?instance=" + Api.enc(inst.optString("id")) + "&" + rq(), r -> {
            JSONArray ps = Api.arr(r);
            String[] labels = new String[ps.length()];
            for (int i = 0; i < ps.length(); i++) {
                JSONObject p = ps.optJSONObject(i);
                String port = p.optInt("from") == p.optInt("to") ? p.optString("from") : p.optString("from") + "-" + p.optString("to");
                List<String> c = new ArrayList<>();
                JSONArray c4 = p.optJSONArray("cidrs"), c6 = p.optJSONArray("ipv6_cidrs");
                for (int j = 0; c4 != null && j < c4.length(); j++) c.add(c4.optString(j));
                for (int j = 0; c6 != null && j < c6.length(); j++) c.add(c6.optString(j));
                labels[i] = p.optString("protocol") + " " + port + " · " + (c.isEmpty() ? "-" : String.join(", ", c)) + "（点选关闭）";
            }
            com.google.android.material.dialog.MaterialAlertDialogBuilder db = new com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
                    .setTitle("防火墙 · " + inst.optString("name"))
                    .setPositiveButton("开放端口", (dd, w) -> lsOpen(inst)).setNegativeButton("关闭", null);
            if (labels.length == 0) db.setMessage("没有开放的端口");
            else db.setItems(labels, (dd, w) -> {
                JSONObject p = ps.optJSONObject(w);
                confirm("关闭端口", "关闭 " + p.optString("protocol") + " " + p.optString("from") + "-" + p.optString("to") + "？", () -> {
                    try {
                        Api.post(this, "/accounts/" + id + "/lightsail/ports", rb().put("op", "close").put("instance", inst.optString("id")).put("protocol", p.optString("protocol"))
                                .put("from_port", p.optInt("from")).put("to_port", p.optInt("to")), x -> { toast("已关闭"); lsPorts(inst); });
                    } catch (Exception ignored) { }
                });
            });
            db.show();
        });
    }

    private void lsOpen(JSONObject inst) {
        form("开放端口", "来源 0.0.0.0/0 表示对整个互联网开放，会再确认一次。", Arrays.asList(
                Field.select("protocol", "协议", "tcp", new String[]{"tcp", "udp", "icmp"}, new String[]{"TCP", "UDP", "ICMP"}),
                Field.text("port", "端口（单个或范围，如 8443 或 8000-8100）", ""),
                Field.text("cidrs", "来源 CIDR（逗号分隔）", "0.0.0.0/0")), "开放", v -> {
            try {
                String proto = v.optString("protocol");
                java.util.regex.Matcher m = java.util.regex.Pattern.compile("^(\\d+)(?:\\s*-\\s*(\\d+))?$").matcher(v.optString("port"));
                boolean ok = m.matches();
                if (!"icmp".equals(proto) && !ok) { toast("请填写端口，如 8443 或 8000-8100"); return; }
                int a = "icmp".equals(proto) ? 0 : Integer.parseInt(m.group(1));
                int b = "icmp".equals(proto) ? 0 : Integer.parseInt(m.group(2) != null ? m.group(2) : m.group(1));
                JSONObject body = rb().put("op", "open").put("instance", inst.optString("id")).put("protocol", proto).put("from_port", a).put("to_port", b).put("cidrs", v.optString("cidrs"));
                Runnable send = () -> Api.post(this, "/accounts/" + id + "/lightsail/ports", body, x -> { toast("已开放"); lsPorts(inst); });
                if (v.optString("cidrs").contains("0.0.0.0/0") || v.optString("cidrs").contains("::/0")) {
                    body.put("confirm_public", true);
                    confirm("⚠️ 对整个互联网开放", "任何人都能访问 " + ("icmp".equals(proto) ? "ICMP" : v.optString("port")) + "。确定？", send);
                } else send.run();
            } catch (Exception ignored) { }
        });
    }

    /** Lightsail 静态 IP（Lightsail 标签页下方）。 */
    private void lsStaticIps(JSONArray insts) {
        LinearLayout c = card("静态 IP");
        android.widget.TextView t = muted(c, "读取中…");
        String[] names = new String[insts.length()];
        for (int i = 0; i < names.length; i++) names[i] = insts.optJSONObject(i).optString("name");
        Api.job(this, () -> {
            try { return Api.call("GET", "/accounts/" + id + "/lightsail/static-ips?" + rq(), null); }
            catch (Exception e) { return new JSONObject().put("error", e.getMessage()); }
        }, r -> {
            if (r instanceof JSONObject) { t.setText("❌ " + ((JSONObject) r).optString("error")); return; }
            JSONArray ips = Api.arr(r);
            t.setText("绑定在实例上的静态 IP 免费；未绑定的按小时计费，不用请释放。");
            LinearLayout row = row(c);
            button(row, "＋ 分配", v -> {
                String[] opts = new String[names.length + 1], labs = new String[names.length + 1];
                opts[0] = ""; labs[0] = "不绑定（会计费）";
                for (int i = 0; i < names.length; i++) opts[i + 1] = labs[i + 1] = names[i];
                form("分配静态 IP", null, Arrays.asList(Field.text("name", "名称", "ip-" + Long.toString(System.currentTimeMillis() / 1000, 36)),
                        Field.select("instance", "立即绑定到", "", opts, labs)), "分配", f -> lsIpOp(f, "allocate", "已分配"));
            });
            for (int i = 0; i < ips.length(); i++) {
                JSONObject s = ips.optJSONObject(i);
                String nm = s.optString("name");
                boolean att = s.optBoolean("attached");
                text(c, nm + " · " + s.optString("ip") + " · " + (att ? "绑定到 " + s.optString("attached_to") : "未绑定 · 计费中"), 13, false);
                LinearLayout rr = row(c);
                if (att) button(rr, "解绑 " + nm, v -> confirm("解绑静态 IP", "解绑后实例会换成新的动态 IP，静态 IP 开始计费。确定？", () -> lsIpOp(new JSONObject(), "detach", "已解绑", "name", nm)));
                else {
                    button(rr, "绑定 " + nm, v -> {
                        if (names.length == 0) { toast("该区域没有 Lightsail 实例"); return; }
                        choose("绑定到实例（原公网 IP 会被替换）", names, k -> lsIpOp(new JSONObject(), "attach", "已绑定", "name", nm, "instance", names[k]));
                    });
                    button(rr, "释放 " + nm, v -> confirm("释放静态 IP", "释放后这个 IP 无法找回。确定？", () -> lsIpOp(new JSONObject(), "release", "已释放", "name", nm)));
                }
            }
        });
    }

    private void lsIpOp(JSONObject b, String op, String msg, String... kv) {
        try {
            b.put("op", op).put("region", region());
            for (int i = 0; i + 1 < kv.length; i += 2) b.put(kv[i], kv[i + 1]);
            Api.post(this, "/accounts/" + id + "/lightsail/static-ips", b, x -> {
                JSONObject o = Api.obj(x);
                toast(!str(o, "ip", "").isEmpty() && "allocate".equals(op) ? "已分配 " + o.optString("ip") : str(o, "hint", msg));
                refresh();
            });
        } catch (Exception ignored) { }
    }

    /** 绑定 Cloudflare 域名：换 IP / 分配 IPv6 后自动更新记录。 */
    private void bindDns(JSONObject inst) {
        Api.get(this, "/cf/zones", r -> {
            JSONArray z = Api.arr(r);
            if (z.length() == 0) { toast("没有可用的域名，请先在设置页填写 Cloudflare Token"); return; }
            String[] ids = new String[z.length()], names = new String[z.length()];
            for (int i = 0; i < ids.length; i++) { ids[i] = z.optJSONObject(i).optString("id") + "|" + z.optJSONObject(i).optString("name"); names[i] = z.optJSONObject(i).optString("name"); }
            form("绑定域名 · " + inst.optString("name"), "绑定后，换 IP / 分配 IPv6 会自动更新这条 Cloudflare 记录。", Arrays.asList(
                    Field.select("zone", "域名", ids[0], ids, names),
                    Field.text("record", "完整记录名（如 node1.example.com）", ""),
                    Field.check("v4", "更新 A 记录（IPv4）", true),
                    Field.check("v6", "更新 AAAA 记录（IPv6）", false),
                    Field.check("proxied", "开启 Cloudflare 代理（橙色云）", false),
                    Field.check("sync_now", "立即用当前 IP 同步一次", true)), "绑定", v -> {
                try {
                    String[] zz = v.optString("zone").split("\\|", 2);
                    JSONObject b = new JSONObject().put("account_id", id).put("instance_id", inst.optString("id")).put("name", inst.optString("name"))
                            .put("zone_id", zz[0]).put("zone_name", zz.length > 1 ? zz[1] : "").put("record", v.optString("record"))
                            .put("v4", v.optBoolean("v4")).put("v6", v.optBoolean("v6")).put("proxied", v.optBoolean("proxied")).put("sync_now", v.optBoolean("sync_now"))
                            .put("ipv4", inst.opt("public_ip")).put("ipv6", inst.opt("ipv6"));
                    Api.post(this, "/dns-bindings", b, x -> {
                        JSONArray dn = Api.obj(x).optJSONArray("dns");
                        StringBuilder sb = new StringBuilder();
                        for (int i = 0; dn != null && i < dn.length(); i++) sb.append(i > 0 ? "；" : "").append(dn.optString(i));
                        toast(sb.length() > 0 ? sb.toString() : "已绑定");
                    });
                } catch (Exception ignored) { }
            });
        });
    }

    // ======================= OCI：存储 / 对象存储 / 配额网络 / 区域订阅 =======================
    private void ociStorage() {
        Api.get(this, "/accounts/" + id + "/oci/volumes?" + rq(), r -> Api.job(this, () -> {
            try { return Api.call("GET", "/accounts/" + id + "/instances?kind=vm&" + rq(), null); } catch (Exception e) { return new JSONArray(); }
        }, ir -> {
            JSONObject d = Api.obj(r);
            JSONArray insts = Api.arr(ir);
            String[] iids = new String[insts.length()], inames = new String[insts.length()];
            for (int i = 0; i < iids.length; i++) { iids[i] = insts.optJSONObject(i).optString("id"); inames[i] = insts.optJSONObject(i).optString("name"); }
            LinearLayout top = card("块存储卷（数据盘）");
            muted(top, "已用 " + d.optString("used_gb") + " / " + d.optString("free_gb") + " GB（Always Free 合计含引导卷）。\n挂载方式为半虚拟化，系统内用 lsblk 查看新盘，首次使用需分区格式化。卸载前请先在系统内 umount。");
            button(row(top), "＋ 新建块存储卷", v -> {
                String[] opts = new String[iids.length + 1], labs = new String[iids.length + 1];
                opts[0] = ""; labs[0] = "不挂载";
                for (int i = 0; i < iids.length; i++) { opts[i + 1] = iids[i]; labs[i + 1] = inames[i]; }
                form("新建块存储卷", "当前已用 " + d.optString("used_gb") + " GB，Always Free 合计 " + d.optString("free_gb") + " GB", Arrays.asList(
                        Field.text("name", "名称", "data-1"),
                        Field.num("size_gb", "大小 GB（最小 50）", "50"),
                        Field.select("vpus_per_gb", "性能 VPU/GB", "10", new String[]{"0", "10", "20", "30", "60", "90", "120"},
                                new String[]{"0（低成本）", "10（均衡，免费）", "20", "30", "60", "90", "120"}),
                        Field.select("instance_id", "创建后挂载到（可选，自动选同可用域）", "", opts, labs)), "创建", f -> {
                    try {
                        Api.post(this, "/accounts/" + id + "/oci/volumes", f.put("op", "create").put("region", region()), x -> {
                            JSONObject at = Api.obj(x).optJSONObject("attach");
                            toast(at != null && !str(at, "hint", "").isEmpty() ? at.optString("hint") : "已创建");
                            refresh();
                        });
                    } catch (Exception ignored) { }
                });
            });
            JSONArray vs = d.optJSONArray("volumes");
            if (vs == null || vs.length() == 0) muted(card("暂无块存储卷"), "");
            for (int i = 0; vs != null && i < vs.length(); i++) {
                JSONObject v = vs.optJSONObject(i);
                String att = str(v, "attached_to", "");
                int ix = Arrays.asList(iids).indexOf(att);
                LinearLayout c = card(v.optString("name") + "  [" + v.optString("state") + "]");
                text(c, v.optString("size_gb") + " GB · " + v.optString("vpus_per_gb") + " VPU/GB\n挂载到：" + (att.isEmpty() ? "未挂载"
                        : (ix >= 0 ? inames[ix] : att.substring(Math.max(0, att.length() - 10))) + (str(v, "device", "").isEmpty() ? "" : " " + v.optString("device"))), 13, false);
                LinearLayout rr = row(c);
                String vid = v.optString("id");
                button(rr, "调整", x -> volUpdate(v));
                if (!att.isEmpty()) button(rr, "卸载", x -> confirm("卸载块存储卷", "请先在系统内 umount 并移除 /etc/fstab 条目，否则可能丢数据或开机失败。确定卸载？",
                        () -> volOp("detach", "attachment_id", v.optString("attachment_id"), "已卸载")));
                else {
                    button(rr, "挂载", x -> {
                        if (iids.length == 0) { toast("该区域没有实例"); return; }
                        choose("挂载到实例（需同一可用域）", inames, k -> volOp("attach", "volume_id", vid, "instance_id", iids[k], "已挂载"));
                    });
                    button(rr, "删除", x -> confirm("删除块存储卷", "删除后数据无法恢复。确定？", () -> volOp("delete", "volume_id", vid, "confirm", "1", "已删除")));
                }
            }
            LinearLayout bc = card("引导卷（系统盘）");
            JSONArray bs = d.optJSONArray("boot_volumes");
            StringBuilder sb = new StringBuilder();
            for (int i = 0; bs != null && i < bs.length(); i++) {
                JSONObject b = bs.optJSONObject(i);
                sb.append(b.optString("name")).append(" · ").append(b.optString("size_gb")).append(" GB · ").append(b.optString("vpus_per_gb")).append(" VPU/GB · ").append(b.optString("state")).append("\n");
            }
            text(bc, sb.length() == 0 ? "暂无" : sb.toString().trim(), 13, false);
            muted(bc, "引导卷扩容在实例卡片「引导卷」里，可勾选扩容后自动扩分区。");
        }));
    }

    /** kv：键值对，最后一个参数是成功提示。值 "1" 的 confirm 会转成布尔。 */
    private void volOp(String op, String... kv) {
        try {
            JSONObject b = rb().put("op", op);
            for (int i = 0; i + 1 < kv.length; i += 2) b.put(kv[i], "confirm".equals(kv[i]) ? (Object) true : kv[i + 1]);
            String msg = kv[kv.length - 1];
            Api.post(this, "/accounts/" + id + "/oci/volumes", b, x -> { toast(str(Api.obj(x), "hint", msg)); refresh(); });
        } catch (Exception ignored) { }
    }

    private void volUpdate(JSONObject v) {
        String[] vp = {"0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100", "110", "120"};
        List<Field> f = new ArrayList<>(Arrays.asList(Field.num("size_gb", "扩容到 GB（只能变大，留空不改；当前 " + v.optString("size_gb") + "）", ""),
                Field.select("vpus_per_gb", "性能 VPU/GB", v.optString("vpus_per_gb"), vp, null)));
        boolean att = !str(v, "attached_to", "").isEmpty();
        if (att) f.add(Field.check("grow", "扩容后通过 Run Command 让系统重新识别磁盘大小（分区需自行扩展）", true));
        form("调整 " + v.optString("name"), null, f, "提交", x -> {
            try {
                JSONObject b = rb().put("op", "update").put("volume_id", v.optString("id")).put("vpus_per_gb", x.optString("vpus_per_gb"));
                if (!x.optString("size_gb").isEmpty()) b.put("size_gb", x.optString("size_gb"));
                if (att) b.put("instance_id", v.optString("attached_to")).put("grow", x.optBoolean("grow"));
                Api.post(this, "/accounts/" + id + "/oci/volumes", b, y -> {
                    JSONObject g = Api.obj(y).optJSONObject("grow");
                    toast(g != null ? "已提交；系统内：" + ("ok".equals(g.optString("status")) ? "已重新识别" : g.optString("message")) : "已提交");
                    refresh();
                });
            } catch (Exception ignored) { }
        });
    }

    // ---------- 对象存储 ----------
    private String objBucket, objPrefix = "";
    private final androidx.activity.result.ActivityResultLauncher<String[]> pickFiles = registerForActivityResult(
            new androidx.activity.result.contract.ActivityResultContracts.OpenMultipleDocuments(), this::upload);

    private void ociObjects() {
        if (objBucket == null) {
            Api.get(this, "/accounts/" + id + "/oci/buckets?" + rq(), r -> {
                JSONObject d = Api.obj(r);
                LinearLayout top = card("对象存储");
                muted(top, "命名空间 " + d.optString("namespace") + " · Always Free 共 " + d.optString("free_gb") + " GB");
                button(row(top), "＋ 新建 Bucket", v -> form("新建 Bucket", null, Arrays.asList(Field.text("name", "名称（字母、数字、- _ .）", ""),
                        Field.check("public", "公开读取（任何人知道链接都能下载对象，慎用）", false)), "创建", f -> {
                    try { Api.post(this, "/accounts/" + id + "/oci/buckets", f.put("op", "create").put("region", region()), x -> { toast("已创建"); refresh(); }); }
                    catch (Exception ignored) { }
                }));
                JSONArray bs = d.optJSONArray("buckets");
                if (bs == null || bs.length() == 0) muted(card("暂无 Bucket"), "");
                for (int i = 0; bs != null && i < bs.length(); i++) {
                    JSONObject b = bs.optJSONObject(i);
                    String nm = b.optString("name");
                    LinearLayout c = card("📁 " + nm);
                    muted(c, "创建于 " + b.optString("created"));
                    LinearLayout rr = row(c);
                    button(rr, "打开", v -> { objBucket = nm; objPrefix = ""; refresh(); });
                    button(rr, "删除", v -> confirm("删除 Bucket", "删除「" + nm + "」？Bucket 需为空。", () -> {
                        try { Api.post(this, "/accounts/" + id + "/oci/buckets", rb().put("op", "delete").put("name", nm).put("confirm", true), x -> { toast("已删除"); refresh(); }); }
                        catch (Exception ignored) { }
                    }));
                }
            });
            return;
        }
        LinearLayout top = card(objBucket + "/" + objPrefix);
        LinearLayout tr = row(top);
        button(tr, "← 返回", v -> {
            if (objPrefix.isEmpty()) objBucket = null;
            else objPrefix = objPrefix.replaceAll("[^/]+/$", "");
            refresh();
        });
        button(tr, "上传文件", v -> pickFiles.launch(new String[]{"*/*"}));
        Api.get(this, "/accounts/" + id + "/oci/objects?bucket=" + Api.enc(objBucket) + "&prefix=" + Api.enc(objPrefix) + "&" + rq(), r -> {
            JSONObject d = Api.obj(r);
            JSONArray ps = d.optJSONArray("prefixes"), os = d.optJSONArray("objects");
            int shown = 0;
            for (int i = 0; ps != null && i < ps.length(); i++) {
                String p = ps.optString(i);
                LinearLayout c = card("📁 " + p.substring(Math.min(objPrefix.length(), p.length())));
                button(row(c), "打开", v -> { objPrefix = p; refresh(); });
                shown++;
            }
            for (int i = 0; os != null && i < os.length(); i++) {
                JSONObject o = os.optJSONObject(i);
                String nm = o.optString("name");
                if (nm.equals(objPrefix)) continue;
                LinearLayout c = card(nm.substring(Math.min(objPrefix.length(), nm.length())));
                muted(c, fmtBytes(o.optLong("size")) + " · " + o.optString("created"));
                LinearLayout rr = row(c);
                button(rr, "下载链接", v -> {
                    try {
                        Api.post(this, "/accounts/" + id + "/oci/objects", rb().put("op", "url").put("bucket", objBucket).put("name", nm).put("minutes", 60), x -> {
                            JSONObject u = Api.obj(x);
                            String url = u.optString("url");
                            new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("下载链接")
                                    .setMessage("预认证只读链接，" + u.optString("expires") + " 前有效，任何拿到链接的人都能下载。")
                                    .setPositiveButton("打开", (dd, w) -> { try { startActivity(new android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url))); } catch (Exception e) { toast("没有可打开链接的应用"); } })
                                    .setNeutralButton("复制", (dd, w) -> copy("url", url)).setNegativeButton("关闭", null).show();
                        });
                    } catch (Exception ignored) { }
                });
                button(rr, "删除", v -> confirm("删除对象", "删除「" + nm + "」？", () -> {
                    try { Api.post(this, "/accounts/" + id + "/oci/objects", rb().put("op", "delete").put("bucket", objBucket).put("name", nm), x -> { toast("已删除"); refresh(); }); }
                    catch (Exception ignored) { }
                }));
                shown++;
            }
            if (shown == 0) muted(card("空"), "");
            if (!d.isNull("next") && d.has("next") && !d.optString("next").isEmpty()) muted(card(null), "只显示前 200 个对象");
        });
    }

    static String fmtBytes(long b) {
        if (b < 1024) return b + " B";
        if (b < 1024 * 1024) return String.format(Locale.US, "%.1f KB", b / 1024.0);
        if (b < 1024L * 1024 * 1024) return String.format(Locale.US, "%.1f MB", b / 1048576.0);
        return String.format(Locale.US, "%.2f GB", b / 1073741824.0);
    }

    private void upload(List<android.net.Uri> uris) {
        if (uris == null || uris.isEmpty() || objBucket == null) return;
        String bucket = objBucket, prefix = objPrefix;
        Api.job(this, () -> {
            StringBuilder sb = new StringBuilder();
            for (android.net.Uri u : uris) {
                String name = "upload";
                long size = -1;
                try (android.database.Cursor c = getContentResolver().query(u, null, null, null, null)) {
                    if (c != null && c.moveToFirst()) {
                        int ni = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME), si = c.getColumnIndex(android.provider.OpenableColumns.SIZE);
                        if (ni >= 0) name = c.getString(ni);
                        if (si >= 0 && !c.isNull(si)) size = c.getLong(si);
                    }
                }
                if (size > 100L * 1024 * 1024) { sb.append(name).append(" 超过 100MB，请用 OCI 控制台上传\n"); continue; }
                byte[] data;
                try (java.io.InputStream in = getContentResolver().openInputStream(u); java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream()) {
                    byte[] buf = new byte[65536];
                    int n;
                    while ((n = in.read(buf)) > 0) { bo.write(buf, 0, n); if (bo.size() > 100 * 1024 * 1024) break; }
                    data = bo.toByteArray();
                }
                if (data.length > 100 * 1024 * 1024) { sb.append(name).append(" 超过 100MB，请用 OCI 控制台上传\n"); continue; }
                try {
                    Api.putBytes("/accounts/" + id + "/oci/objects?bucket=" + Api.enc(bucket) + "&name=" + Api.enc(prefix + name) + "&" + rq(), data);
                    sb.append(name).append(" 已上传\n");
                } catch (Exception e) { sb.append(name).append("：").append(e.getMessage()).append("\n"); }
            }
            return sb.toString().trim();
        }, r -> { info("上传结果", String.valueOf(r)); refresh(); });
    }

    // ---------- 配额 / 网络 ----------
    private void ociLimits() {
        LinearLayout nc = card("网络");
        muted(nc, "自动创建网络：新建 VCN（含 IPv6）、互联网网关、路由和公有子网，安全列表默认只放行 22 与 ICMP。");
        button(row(nc), "自动创建网络", v -> confirm("自动创建网络", "新建 VCN（含 IPv6）、互联网网关、路由和公有子网，安全列表默认只放行 22 与 ICMP。确定？", () -> {
            try { Api.post(this, "/accounts/" + id + "/oci/network", rb(), x -> taskOrToast(x, "已提交")); } catch (Exception ignored) { }
        }));
        Api.get(this, "/accounts/" + id + "/oci/limits?" + rq(), r -> {
            JSONObject d = Api.obj(r);
            JSONArray items = d.optJSONArray("items");
            LinearLayout c = card("计算配额 · " + d.optString("region"));
            if (items == null || items.length() == 0) muted(c, "无数据");
            for (int i = 0; items != null && i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i);
                String free = it.isNull("free") || !it.has("free") ? "-" : str(it, "free_left", "?") + " / " + it.optString("free");
                text(c, it.optString("name"), 14, true);
                muted(c, "上限 " + it.optString("limit") + " · 已用 " + str(it, "used", "-") + " · 可用 " + str(it, "available", "-") + " · 免费剩余 " + free);
            }
            String basis = d.optString("a1_basis");
            muted(c, "「上限」是 OCI 允许开的量，升级按量付费（PAYG）后会很大；「免费剩余」A1 按"
                    + ("paid".equals(basis) ? "付费号 4 OCPU / 24GB" : "free".equals(basis) ? "免费号 2 OCPU / 12GB" : "免费号 2 OCPU / 12GB（未识别账号类型，可在云账号页「类型」里刷新）")
                    + "计算（2026-06 起免费号减半），E2.1.Micro 2 台，超出部分计费。可用量为 0 时抢机必然失败。");
        });
    }

    private void ociRegionSub() {
        Api.get(this, "/accounts/" + id + "/oci/region-subscriptions", r -> {
            JSONObject d = Api.obj(r);
            JSONArray rs = d.optJSONArray("regions");
            int sub = 0;
            for (int i = 0; rs != null && i < rs.length(); i++) if (rs.optJSONObject(i).optBoolean("subscribed")) sub++;
            LinearLayout top = card("已订阅 " + sub + " 个区域 · 主区域 " + str(d, "home", "-"));
            muted(top, str(d, "limit_hint", "") + "。订阅不可撤销，订阅后可在区域选择里切换。");
            for (int i = 0; rs != null && i < rs.length(); i++) {
                JSONObject x = rs.optJSONObject(i);
                boolean s = x.optBoolean("subscribed");
                LinearLayout c = card(x.optString("name") + (x.optBoolean("home") ? "  [主区域]" : ""));
                muted(c, x.optString("key") + " · " + (s ? str(x, "status", "已订阅") : "未订阅"));
                if (!s) button(row(c), "订阅", v -> confirm("订阅区域", "订阅 " + x.optString("name") + "（" + x.optString("key") + "）？\n⚠️ 订阅后无法取消，免费账号的额外区域名额通常只有 1 个；Always Free 资源仍只在主区域。", () -> {
                    try {
                        Api.post(this, "/accounts/" + id + "/oci/region-subscriptions", new JSONObject().put("region_key", x.optString("key")).put("confirm", true), y -> {
                            JSONObject o = Api.obj(y);
                            toast("已提交订阅：" + o.optString("region") + "（" + o.optString("status") + "），几分钟后生效");
                            refresh();
                        });
                    } catch (Exception ignored) { }
                }));
            }
        });
    }

    // ======================= AWS 区域 =======================
    private void awsRegions(boolean rescan) {
        LinearLayout st = card("区域激活");
        android.widget.TextView stT = muted(st, "读取区域状态…");
        LinearLayout sc = card("全区域实例");
        android.widget.TextView scT = muted(sc, "全区域实例扫描（串行，约 30–60 秒）…");
        Api.job(this, () -> {
            try { return Api.call("GET", "/accounts/" + id + "/aws/regions-status", null); } catch (Exception e) { return new JSONObject().put("error", e.getMessage()); }
        }, r -> {
            if (r instanceof JSONObject) { stT.setText("❌ " + ((JSONObject) r).optString("error") + "\n需要 account:ListRegions / account:EnableRegion 权限"); return; }
            JSONArray rs = Api.arr(r);
            stT.setText("香港、雅加达等 Opt-in 区域需先激活才能开机。");
            StringBuilder sb = new StringBuilder();
            LinearLayout rr = row(st);
            for (int i = 0; i < rs.length(); i++) {
                JSONObject x = rs.optJSONObject(i);
                String status = x.optString("status");
                boolean on = "ENABLED_BY_DEFAULT".equals(status) || "ENABLED".equals(status);
                sb.append(on ? "✅ " : "DISABLED".equals(status) ? "⛔ " : "⏳ ").append(x.optString("region")).append("  ").append(status).append("\n");
                if ("DISABLED".equals(status)) button(rr, "激活 " + x.optString("region"), v -> {
                    try { Api.post(this, "/accounts/" + id + "/aws/enable-region", new JSONObject().put("region", x.optString("region")), y -> { toast(str(Api.obj(y), "hint", "已提交")); refresh(); }); }
                    catch (Exception ignored) { }
                });
            }
            text(st, sb.toString().trim(), 12, false);
        });
        Api.job(this, () -> {
            try { return Api.call("GET", "/accounts/" + id + "/aws/scan" + (rescan ? "?refresh=true" : ""), null); } catch (Exception e) { return new JSONObject().put("error", e.getMessage()); }
        }, r -> {
            JSONObject d = Api.obj(r);
            if (d.has("error")) { scT.setText("❌ " + d.optString("error")); return; }
            scT.setText("扫描于 " + d.optString("updated_at"));
            JSONArray rs = d.optJSONArray("regions");
            LinearLayout rr = row(sc);
            button(rr, "重新扫描", v -> { header(); awsRegions(true); });
            int n = 0;
            for (int i = 0; rs != null && i < rs.length(); i++) {
                JSONObject x = rs.optJSONObject(i);
                if (x.optInt("ec2") == 0 && x.optInt("lightsail") == 0) continue;
                n++;
                String reg = x.optString("region");
                text(sc, reg + " · EC2 " + x.optInt("ec2") + "（运行 " + x.optInt("ec2_running") + "）· Lightsail " + str(x, "lightsail", "-"), 13, false);
                button(row(sc), "查看 " + reg, v -> { Api.setPref("region_" + id, reg); selectTab("ec2"); });
            }
            if (n == 0) muted(sc, "所有区域都没有实例");
        });
    }

    private void selectTab(String key) {
        TabLayout tl = (TabLayout) topBar.getChildAt(0);
        for (int i = 0; i < tl.getTabCount(); i++) {
            TabLayout.Tab t = tl.getTabAt(i);
            if (t != null && key.equals(t.getTag())) { t.select(); return; }
        }
    }

    // ======================= Azure：创建 VM / 资源组 / 配额 =======================
    private JSONArray azLocs;

    private void withLocs(Api.Cb cb) {
        if (azLocs != null) { cb.ok(azLocs); return; }
        Api.get(this, "/accounts/" + id + "/azure/locations", r -> { azLocs = Api.arr(r); cb.ok(azLocs); });
    }

    private void azCreateTab() {
        LinearLayout c = card("创建 Azure VM");
        muted(c, "学生订阅免费额度：B1s 750 小时/月 + 2×64GB P6 SSD。创建约 2–4 分钟，后台执行并推送通知；随机密码可在「开机密码」查看。默认值来自 设置 → 默认创建参数。");
        button(row(c), "填写参数并创建", v -> azureCreate());
    }

    private void azRgs() {
        bigButton("＋ 新建资源组", v -> withLocs(l -> form("新建资源组", null, Arrays.asList(Field.text("name", "名称", ""),
                sel("location", "区域", Api.pref("azloc_" + id, "eastasia"), Api.arr(l), false)), "创建",
                f -> Api.post(this, "/accounts/" + id + "/azure/rgs", f, x -> { toast("已创建"); refresh(); }))));
        Api.get(this, "/accounts/" + id + "/azure/rgs", r -> {
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card("暂无资源组"), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject g = a.optJSONObject(i);
                String nm = g.optString("name");
                LinearLayout c = card(nm);
                muted(c, g.optString("location") + " · " + g.optString("state"));
                button(row(c), "删除", v -> form("删除资源组", "⚠️ 将删除资源组 " + nm + " 内的全部资源（VM、磁盘、IP、网络），不可恢复。",
                        Arrays.asList(Field.text("confirm", "输入资源组名称确认", "")), "删除", f -> {
                    if (!nm.equals(f.optString("confirm"))) { toast("名称不一致"); return; }
                    try { Api.post(this, "/accounts/" + id + "/azure/rgs", f.put("op", "delete").put("name", nm), x -> { toast("已提交删除，几分钟后完成"); body.postDelayed(this::refresh, 3000); }); }
                    catch (Exception ignored) { }
                }));
            }
        });
    }

    private void azQuota() {
        withLocs(l -> {
            JSONArray locs = Api.arr(l);
            String cur = Api.pref("azloc_" + id, "eastasia");
            LinearLayout top = row(body);
            button(top, "区域：" + cur, v -> {
                String[] ls = new String[locs.length()];
                for (int i = 0; i < ls.length; i++) ls[i] = locs.optString(i);
                choose("选择区域", ls, i -> { Api.setPref("azloc_" + id, ls[i]); refresh(); });
            });
            Api.get(this, "/accounts/" + id + "/azure/quotas?location=" + Api.enc(cur), r -> {
                JSONArray items = Api.obj(r).optJSONArray("items");
                LinearLayout c = card("配额 · " + cur);
                StringBuilder sb = new StringBuilder();
                for (int i = 0; items != null && i < items.length(); i++) {
                    JSONObject it = items.optJSONObject(i);
                    sb.append(it.optString("name")).append("：").append(it.optString("used")).append(" / ").append(it.optString("limit")).append("\n");
                }
                text(c, sb.length() == 0 ? "无数据" : sb.toString().trim(), 13, false);
            });
        });
    }
}
