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
            case "oci": return new String[][]{{"instances", getString(R.string.s0001)}, {"create", getString(R.string.s0002)}, {"snatch", getString(R.string.s0003)}, {"secgroup", getString(R.string.s0004)}, {"storage", getString(R.string.s0005)},
                    {"objects", getString(R.string.s0006)}, {"traffic", getString(R.string.s0007)}, {"limits", getString(R.string.s0008)}, {"billing", getString(R.string.s0009)}};   // 区域订阅收在「配额/网络」页底部（防误点）
            case "aws": return new String[][]{{"ec2", "EC2"}, {"lightsail", "Lightsail"}, {"regions", getString(R.string.s0010)}, {"cloudfront", "CloudFront"}, {"quota", getString(R.string.s0011)}, {"recycle", getString(R.string.s0012)}, {"billing", getString(R.string.s0009)}, {"credit", getString(R.string.s0013)}};
            default: return new String[][]{{"vms", getString(R.string.s0014)}, {"azcreate", getString(R.string.s0015)}, {"rgs", getString(R.string.s0016)}, {"azquota", getString(R.string.s0011)}, {"foundry", "Foundry"}, {"subscription", getString(R.string.s0017)}, {"billing", getString(R.string.s0009)}};
        }
    }

    @Override
    protected void onCreate(Bundle s) {
        super.onCreate(s);
        try { acc = new JSONObject(getIntent().getStringExtra("acc")); } catch (Exception e) { finish(); return; }
        prov = acc.optString("provider");
        id = acc.optInt("id");
        tab = s != null ? s.getString("tab", tabs(prov)[0][0]) : Api.pref("tab_" + id, tabs(prov)[0][0]);
        if ("regionsub".equals(tab)) tab = "limits";   // build 18 起区域订阅不再是单独标签
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

    // ---------------- build 25：默认选中有机器的区域 ----------------
    static final List<String> NO_REGION_TABS = Arrays.asList("cloudfront", "quota", "billing", "subscription", "regions", "credit");

    /** 没手动选过区域、也还没有区域记录时，先查一次总览（有缓存）定位有机器的区域。 */
    private boolean located;

    private boolean needLocate() {
        return !located && !MainActivity.noRegion(prov) && !NO_REGION_TABS.contains(tab) && acc.optInt("disabled") != 1
                && Api.pref("region_" + id, "").isEmpty() && Regions.machineRegions(acc) == null;
    }

    /** 最多等 8 秒；失败 / 超时用账号默认区域。 */
    private void locate() {
        located = true;
        clear();
        muted(card(getString(R.string.s0018)), getString(R.string.s0019));
        final boolean[] done = {false};
        Runnable go = () -> { if (done[0] || isFinishing()) return; done[0] = true; refresh(); };
        body.postDelayed(go, 8000);
        Api.job(this, () -> {
            try { return Api.call("GET", "/accounts/" + id + "/overview", null); }
            catch (Api.ApiError e) { if (e.code == 401) throw e; return new JSONObject(); }
            catch (Exception e) { return new JSONObject(); }
        }, x -> {
            if (x instanceof JSONObject) Regions.apply(id, (JSONObject) x);
            go.run();
        });
    }

    @Override
    protected String navKey() { return "acc_" + id; }

    private JSONArray scripts = new JSONArray();

    /** 开机脚本模板下拉（脚本模板页维护），与 Web loginFields 一致。 */
    private Field scriptField() {
        int n = scripts.length();
        String[] ids = new String[n + 1], labels = new String[n + 1];
        ids[0] = ""; labels[0] = getString(R.string.s0020);
        for (int i = 0; i < n; i++) { ids[i + 1] = String.valueOf(scripts.optJSONObject(i).optInt("id")); labels[i + 1] = scripts.optJSONObject(i).optString("name"); }
        return Field.select("script_id", getString(R.string.s0021), "", ids, labels);
    }

    @Override
    protected void onSaveInstanceState(Bundle o) { super.onSaveInstanceState(o); o.putString("tab", tab); }

    /** 手动选过的区域 > 机器最多的区域（build 25）> 账号默认区域。 */
    String region() { return Regions.current(acc); }
    String rq() { return MainActivity.noRegion(prov) ? "" : "region=" + Api.enc(region()); }
    JSONObject base(JSONObject inst, String kind) throws Exception {
        return new JSONObject().put("instance_id", inst.optString("id")).put("region", region()).put("kind", kind).put("name", inst.optString("name"));
    }

    private void header() {
        clear();
        if (!MainActivity.noRegion(prov) && !Arrays.asList("cloudfront", "quota", "billing", "subscription", "regions", "credit").contains(tab)) {
            LinearLayout r2 = row(body);
            boolean ls = "lightsail".equals(tab);   // build 19：Lightsail 只列它支持的区域（如台北 ap-east-2 没有）
            button(r2, getString(R.string.s0022, Regions.label(region())), v -> {
                if (ls) withLsRegions(this::pickRegion);
                else Api.get(this, "/accounts/" + id + "/regions", this::pickRegion);
            });
        }
    }

    /** 区域选择：显示「代码 · 城市」，保存纯代码。 */
    private void pickRegion(Object x) {
        JSONArray a = Api.arr(x);
        if (a.length() == 0) { toast(getString(R.string.s0023)); return; }
        String[] rs = new String[a.length()];
        for (int i = 0; i < rs.length; i++) rs[i] = a.optString(i);
        choose(getString(R.string.s0024, Regions.label(region())), Regions.labels(rs), i -> { Api.setPref("region_" + id, rs[i]); refresh(); });
    }

    // ---------------- Lightsail 区域（build 19） ----------------
    private JSONArray lsRegs;

    /** GET /regions?service=lightsail（账号已启用 ∩ Lightsail 支持）；失败回调空列表（不做过滤），成功才缓存。 */
    private void withLsRegions(Api.Cb cb) {
        if (lsRegs != null) { cb.ok(lsRegs); return; }
        Api.job(this, () -> {
            try { return Api.call("GET", "/accounts/" + id + "/regions?service=lightsail", null); }
            catch (Api.ApiError e) { if (e.code == 401) throw e; return new JSONArray(); }
            catch (Exception e) { return new JSONArray(); }
        }, r -> {
            JSONArray a = Api.arr(r);
            if (a.length() > 0) lsRegs = a;
            cb.ok(a);
        });
    }

    /** 当前保存的区域 Lightsail 不支持时：切到账号默认区域（若支持）或第一个可用区域，并提示。 */
    private void lsEnsure(Runnable then) {
        withLsRegions(x -> {
            if (!"lightsail".equals(tab)) return;
            JSONArray a = Api.arr(x);
            List<String> l = new ArrayList<>();
            for (int i = 0; i < a.length(); i++) l.add(a.optString(i));
            String cur = region();
            if (!l.isEmpty() && !l.contains(cur)) {
                String def = str(acc, "region", "");
                String to = l.contains(def) ? def : l.get(0);
                Api.setPref("region_" + id, to);
                toast(getString(R.string.s0025, Regions.label(cur), Regions.label(to)));
                header();
            }
            then.run();
        });
    }

    /** 区域下拉字段：值为纯代码，显示带城市名。 */
    private Field regionSel(String k, String label, String def, JSONArray a) {
        int n = a == null ? 0 : a.length();
        String[] ids = new String[n];
        for (int i = 0; i < n; i++) ids[i] = a.optString(i);
        return Field.select(k, label, def, ids, Regions.labels(ids));
    }

    @Override
    protected void refresh() {
        if (needLocate()) { locate(); return; }
        header();
        switch (tab) {
            case "instances": case "ec2": case "vms": instances("vm"); break;
            case "lightsail": lsEnsure(() -> instances("lightsail")); break;
            case "create": ociCreate(false); break;
            case "snatch": ociCreate(true); break;
            case "cloudfront": cloudfront(); break;
            case "quota": quota(false); break;
            case "recycle": recycle(); break;
            case "credit": credit(false); break;
            case "billing": billing(false); break;
            case "subscription": subscription(); break;
            case "foundry": foundry(); break;
            case "secgroup": secgroup(); break;
            case "traffic": ociTraffic(); break;
            case "storage": ociStorage(); break;
            case "objects": ociObjects(); break;
            case "limits": ociLimits(); break;
            case "regions": awsRegions(false); break;
            case "azcreate": azCreateTab(); break;
            case "rgs": azRgs(); break;
            case "azquota": azQuota(); break;
        }
    }

    // ---------------- 实例 ----------------
    private void instances(String kind) {
        if ("lightsail".equals(kind)) bigButton(getString(R.string.s0026), v -> lightsailCreate());
        if ("aws".equals(prov) && "vm".equals(kind)) bigButton(getString(R.string.s0027), v -> ec2Create());
        if ("azure".equals(prov)) bigButton(getString(R.string.s0028), v -> azureCreate());
        Api.get(this, "/accounts/" + id + "/instances?kind=" + kind + "&" + rq(), r -> {
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card(getString(R.string.s0029)), Regions.label(region()));
            for (int i = 0; i < a.length(); i++) instCard(a.optJSONObject(i), kind);
            if ("lightsail".equals(kind)) lsStaticIps(a);
        });
    }

    private void instCard(JSONObject inst, String kind) {
        LinearLayout c = card(inst.optString("name") + "  [" + inst.optString("state") + "]");
        JSONArray v6 = inst.optJSONArray("ipv6");
        String spec = "oci".equals(prov) ? inst.optString("shape") + " " + str(inst, "ocpus", "?") + "C/" + str(inst, "memory_gb", "?") + "G" : inst.optString("shape");
        text(c, getString(R.string.s0030, str(inst, "public_ip", "-"), str(inst, "private_ip", "-"), (v6 != null && v6.length() > 0 ? join(v6) : "-"), spec, Regions.label(str(inst, "zone", "-"))), 13, false);
        LinearLayout r = row(c);
        button(r, getString(R.string.s0031), v -> simple(inst, kind, "start", getString(R.string.s0031)));
        button(r, "azure".equals(prov) ? getString(R.string.s0032) : getString(R.string.s0033), v -> simple(inst, kind, "stop", getString(R.string.s0033)));
        button(r, getString(R.string.s0034), v -> simple(inst, kind, "reboot", getString(R.string.s0034)));
        button(r, getString(R.string.s0035), v -> changeIp(inst, kind));
        if ("oci".equals(prov)) {
            button(r, getString(R.string.s0036), v -> { try { Api.post(this, "/accounts/" + id + "/oci/ipv6", base(inst, kind), x -> taskOrToast(x, getString(R.string.s0037))); } catch (Exception ignored) { } });
            button(r, getString(R.string.s0038), v -> confirm(getString(R.string.s0039), getString(R.string.s0040, inst.optString("name")), () -> {
                try { Api.post(this, "/accounts/" + id + "/oci/ipv6/delete", base(inst, kind).put("confirm", true), x -> { toast(getString(R.string.s0041, join(Api.obj(x).optJSONArray("deleted")))); refresh(); }); }
                catch (Exception ignored) { }
            }));
            button(r, getString(R.string.s0042), v -> resizeOci(inst));
            button(r, getString(R.string.s0043), v -> bootVol(inst, kind));
            button(r, getString(R.string.s0044), v -> ociIps(inst));
        }
        if ("azure".equals(prov)) { button(r, getString(R.string.s0045), v -> resizeAzure(inst)); button(r, getString(R.string.s0046), v -> azDisks(inst)); }
        if ("lightsail".equals(kind)) button(r, getString(R.string.s0047), v -> lsPorts(inst));
        if (!"lightsail".equals(kind)) button(r, getString(R.string.s0048), v -> rename(inst, kind));   // v1.5：Lightsail 不支持改名
        if (!"lightsail".equals(kind)) button(r, getString(R.string.s0049), v -> openPort(inst, kind));
        button(r, getString(R.string.s0050), v -> traffic(inst, kind));
        if (!"lightsail".equals(kind)) {
            button(r, getString(R.string.s0051), v -> migrate(inst));
        }
        button(r, getString(R.string.s0052), v -> bindDns(inst));
        button(r, getString(R.string.s0053), v -> monitor(inst, kind));
        // v1.6：IP 质量 / 免费 AMD 下行 500Mbps / 重装系统
        button(r, getString(R.string.s0054), v -> ipQuality(inst));
        if ("oci".equals(prov) && "VM.Standard.E2.1.Micro".equals(inst.optString("shape"))) button(r, getString(R.string.s0055), v -> net500(inst, kind));
        if (!"lightsail".equals(kind)) button(r, getString(R.string.s0056), v -> reinstall(inst, kind));
        button(r, "azure".equals(prov) || "lightsail".equals(kind) ? getString(R.string.s0057) : getString(R.string.s0058), v -> simple(inst, kind, "terminate", getString(R.string.s0058)));
    }

    // ---------------- v1.6 ----------------
    private void reinstall(JSONObject inst, String kind) {
        List<Field> f = new ArrayList<>();
        if ("oci".equals(prov)) {
            f.add(Field.select("os", getString(R.string.s0059), "Canonical Ubuntu", new String[]{"Canonical Ubuntu", "Oracle Linux"}, null));
            f.add(Field.select("os_version", getString(R.string.s0060), "", new String[]{"", "24.04", "22.04", "20.04", "9", "8"}, new String[]{getString(R.string.s0061), "Ubuntu 24.04", "Ubuntu 22.04", "Ubuntu 20.04", "Oracle Linux 9", "Oracle Linux 8"}));
            f.add(Field.num("disk_gb", getString(R.string.s0062), ""));
        } else if ("aws".equals(prov)) {
            f.add(Field.select("os", getString(R.string.s0059), "debian-12", new String[]{"debian-12", "ubuntu-24.04", "ubuntu-22.04", "al2023"}, new String[]{"Debian 12", "Ubuntu 24.04", "Ubuntu 22.04", "Amazon Linux 2023"}));
        } else {
            f.add(Field.select("os", getString(R.string.s0059), "debian-12", new String[]{"debian-12", "ubuntu-24.04", "ubuntu-22.04"}, new String[]{"Debian 12", "Ubuntu 24.04", "Ubuntu 22.04"}));
        }
        if (!"aws".equals(prov)) f.add(Field.check("password_login", getString(R.string.s0063), true));
        f.add(Field.check("confirm", getString(R.string.s0064), false));
        form(getString(R.string.s0056), getString(R.string.s0065, inst.optString("name")), f, getString(R.string.s0066), v -> {
            if (!v.optBoolean("confirm")) { toast(getString(R.string.s0067)); return; }
            try {
                JSONObject b = base(inst, kind).put("confirm", true);
                for (String k : new String[]{"os", "os_version", "disk_gb"}) if (!v.optString(k).isEmpty()) b.put(k, v.optString(k));
                if (v.has("password_login")) b.put("password_login", v.optBoolean("password_login"));
                Api.post(this, "/accounts/" + id + "/instances/reinstall", b, x -> taskOrToast(x, getString(R.string.s0037)));
            } catch (Exception ignored) { }
        });
    }

    private void ipQuality(JSONObject inst) {
        String ip = inst.optString("public_ip", "");
        if (ip.isEmpty() || "null".equals(ip)) { toast(getString(R.string.s0068)); return; }
        Api.get(this, "/ip-quality?ip=" + ip, r -> {
            JSONObject q = Api.obj(r);
            String risk = q.isNull("risk") ? getString(R.string.s0069) : getString(R.string.s0070, q.optInt("risk"));
            new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s0071, inst.optString("name")))
                    .setMessage(getString(R.string.s0073, ip, risk, str(q, "type", "-"), (q.optBoolean("proxy") ? getString(R.string.s0072) : ""), str(q, "country", "-"), str(q, "country_code", ""), str(q, "isp", "-"), str(q, "asn", ""), q.optString("source")))
                    .setPositiveButton(getString(R.string.s0074), null).show();
        });
    }

    private void net500(JSONObject inst, String kind) {
        Api.get(this, "/accounts/" + id + "/oci/500m?instance_id=" + android.net.Uri.encode(inst.optString("id")) + "&" + rq(), r -> {
            JSONObject st = Api.obj(r);
            boolean on = st.optBoolean("enabled");
            String msg = on ? getString(R.string.s0075, st.optString("public_ip"))
                    : getString(R.string.s0076);
            confirm(on ? getString(R.string.s0077) : getString(R.string.s0078), msg, () -> {
                try { Api.post(this, "/accounts/" + id + "/oci/500m", base(inst, kind).put("enable", !on).put("confirm", true), x -> taskOrToast(x, getString(R.string.s0037))); }
                catch (Exception ignored) { }
            });
        });
    }

    private void simple(JSONObject inst, String kind, String act, String label) {
        if ("terminate".equals(act) && "oci".equals(prov)) {
            form(label, getString(R.string.s0079, inst.optString("name")), Arrays.asList(
                    Field.check("preserve_boot_volume", getString(R.string.s0080), false)), getString(R.string.s0058), v -> {
                try {
                    Api.post(this, "/accounts/" + id + "/instances/action", base(inst, kind).put("action", act).put("confirm", true)
                            .put("preserve_boot_volume", v.optBoolean("preserve_boot_volume")), r -> { toast(getString(R.string.s0081, label)); body.postDelayed(this::refresh, 2500); });
                } catch (Exception ignored) { }
            });
            return;
        }
        String msg = "terminate".equals(act) ? getString(R.string.s0082, label, inst.optString("name"))
                : getString(R.string.s0084, label, inst.optString("name"), ("stop".equals(act) && "azure".equals(prov) ? getString(R.string.s0083) : ""));
        confirm(label, msg, () -> {
            try {
                Api.post(this, "/accounts/" + id + "/instances/action", base(inst, kind).put("action", act).put("confirm", "terminate".equals(act)),
                        r -> { toast(getString(R.string.s0081, label)); body.postDelayed(this::refresh, 2500); });
            } catch (Exception ignored) { }
        });
    }

    // v1.5 改名 + 同步系统主机名（通过云厂商 Run Command 执行固定命令，不走 SSH）
    private void rename(JSONObject inst, String kind) {
        form(getString(R.string.s0085), getString(R.string.s0086),
                Arrays.asList(Field.text("new_name", getString(R.string.s0087), inst.optString("name")),
                        Field.check("sync_hostname", getString(R.string.s0088), true)), getString(R.string.s0089), v -> {
            String name = v.optString("new_name").trim();
            if (name.isEmpty()) { toast(getString(R.string.s0090)); return; }
            try {
                JSONObject b = base(inst, kind).put("new_name", name).put("sync_hostname", v.optBoolean("sync_hostname", true));
                Api.post(this, "/accounts/" + id + "/instances/rename", b, x -> { renameResult(Api.obj(x)); refresh(); });
            } catch (Exception ignored) { }
        });
    }

    private void renameResult(JSONObject o) {
        JSONObject h = o.optJSONObject("hostname");
        if (h == null || "ok".equals(h.optString("status"))) { toast(h == null ? getString(R.string.s0091) : getString(R.string.s0092)); return; }
        String msg = h.optString("message");
        String cmd = h.optString("manual_cmd", "");
        if ("pending".equals(h.optString("status")) || cmd.isEmpty()) { toast(getString(R.string.s0093, msg)); return; }
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("failed".equals(h.optString("status")) ? getString(R.string.s0094) : getString(R.string.s0095))
                .setMessage(getString(R.string.s0096, msg, cmd))
                .setPositiveButton(getString(R.string.s0097), (d, w) -> {
                    android.content.ClipboardManager cm = (android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                    if (cm != null) cm.setPrimaryClip(android.content.ClipData.newPlainText("cmd", cmd));
                    toast(getString(R.string.s0098));
                }).setNegativeButton(getString(R.string.s0074), null).show();
    }

    // v1.5 实例操作「开放端口」：来源 0.0.0.0/0；填端口后先弹公网警告再提交（与 Web / TG 同一接口）
    private void openPort(JSONObject inst, String kind) {
        String where = "oci".equals(prov) ? getString(R.string.s0099) : "aws".equals(prov) ? getString(R.string.s0100) : getString(R.string.s0101);
        form(getString(R.string.s0049), getString(R.string.s0102, inst.optString("name"), where),
                Arrays.asList(Field.text("port", getString(R.string.s0103), ""),
                        Field.select("protocol", getString(R.string.s0104), "tcp", new String[]{"tcp", "udp"}, new String[]{"TCP", "UDP"})), getString(R.string.s0105), v -> {
            String port = v.optString("port").trim();
            if (port.isEmpty()) { toast(getString(R.string.s0106)); return; }
            String proto = v.optString("protocol", "tcp");
            confirm(getString(R.string.s0107), getString(R.string.s0108, proto.toUpperCase(Locale.ROOT), port), () -> {
                try {
                    JSONObject b = base(inst, kind).put("port", port).put("protocol", proto).put("confirm_public", true);
                    Api.post(this, "/accounts/" + id + "/instances/" + Api.enc(inst.optString("id")) + "/open-port", b, x -> {
                        JSONObject o = Api.obj(x);
                        new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s0109, o.optInt("added")))
                                .setMessage(o.optString("msg")).setPositiveButton(getString(R.string.s0110), null).show();
                    });
                } catch (Exception ignored) { }
            });
        });
    }

    private void changeIp(JSONObject inst, String kind) {
        List<Field> f = new ArrayList<>();
        if ("aws".equals(prov) && "vm".equals(kind))
            f.add(Field.select("mode", getString(R.string.s0111), "auto", new String[]{"auto", "eip", "stopstart"},
                    new String[]{getString(R.string.s0112), getString(R.string.s0113), getString(R.string.s0114)}));
        boolean oci = "oci".equals(prov);
        f.add(Field.text("cidrs", getString(R.string.s0115), ""));
        f.add(Field.num("max_tries", getString(R.string.s0116), oci ? "20" : "5"));
        f.add(Field.num("quality_max_risk", getString(R.string.s0117), ""));
        f.add(Field.text("quality_country", getString(R.string.s0118), ""));
        Api.get(this, "/accounts/" + id + "/ip-change-usage", u -> changeIpForm(inst, kind, f, Api.obj(u)));
    }

    private void changeIpForm(JSONObject inst, String kind, List<Field> f, JSONObject u) {
        String usage = u.has("limit") ? getString(R.string.s0119, u.optInt("manual_used"), u.optInt("auto_used"), u.optInt("limit")) : "";
        form(getString(R.string.s0120), getString(R.string.s0121, str(inst, "public_ip", "-"), usage), f, getString(R.string.s0122), v -> {
            try {
                JSONObject b = base(inst, kind);
                if (v.has("mode")) b.put("mode", v.getString("mode"));
                if (!v.optString("cidrs").isEmpty()) b.put("cidrs", v.getString("cidrs")).put("max_tries", v.optString("max_tries", "20"));
                if (!v.optString("quality_max_risk").isEmpty()) b.put("quality_max_risk", v.getString("quality_max_risk")).put("max_tries", v.optString("max_tries", "20"));
                if (!v.optString("quality_country").isEmpty()) b.put("quality_country", v.getString("quality_country")).put("max_tries", v.optString("max_tries", "20"));
                Api.post(this, "/accounts/" + id + "/instances/change-ip", b, r -> {
                    JSONObject o = Api.obj(r);
                    if (o.has("task_id")) openTask(o.optInt("task_id")); else toast(getString(R.string.s0123, o.optString("new_ip")));
                    refresh();
                });
            } catch (Exception ignored) { }
        });
    }

    private void resizeOci(JSONObject inst) {
        form(getString(R.string.s0124), getString(R.string.s0125), Arrays.asList(
                Field.num("ocpus", "OCPU", inst.optString("ocpus", "1")),
                Field.num("memory_gb", getString(R.string.s0126), inst.optString("memory_gb", "6"))), getString(R.string.s0127), v -> {
            try {
                JSONObject b = base(inst, "vm").put("ocpus", v.optString("ocpus")).put("memory_gb", v.optString("memory_gb"));
                Api.post(this, "/accounts/" + id + "/instances/resize", b, r -> taskOrToast(r, getString(R.string.s0037)));
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
            choose(getString(R.string.s0128), labels, i -> {
                try {
                    Api.post(this, "/accounts/" + id + "/instances/resize", base(inst, "vm").put("size", names[i]),
                            x -> taskOrToast(x, getString(R.string.s0037)));
                } catch (Exception ignored) { }
            });
        });
    }

    private void monitor(JSONObject inst, String kind) {
        form(getString(R.string.s0129), getString(R.string.s0130, inst.optString("name")), Arrays.asList(
                Field.check("auto_start", getString(R.string.s0131), false),
                Field.num("check_port", getString(R.string.s0132), "0"),
                Field.check("auto_change_ip", getString(R.string.s0133), false)), getString(R.string.s0089), v -> {
            try {
                JSONObject b = new JSONObject().put("account_id", id).put("instance_id", inst.optString("id")).put("region", region())
                        .put("kind", kind).put("name", inst.optString("name")).put("state", inst.optString("state"))
                        .put("auto_start", v.optBoolean("auto_start")).put("public_ip", inst.optString("public_ip"))
                        .put("check_port", v.optString("check_port", "0")).put("auto_change_ip", v.optBoolean("auto_change_ip"));
                Api.post(this, "/monitors", b, r -> toast(getString(R.string.s0134)));
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
            f.add(Field.text("name", getString(R.string.s0135), "ec2-" + Long.toString(System.currentTimeMillis() / 1000, 36)));
            f.add(types != null && types.length() > 0 ? sel("type", getString(R.string.s0136), d.optString("type", "t3.micro"), types, false) : Field.text("type", getString(R.string.s0136), d.optString("type", "t3.micro")));
            f.add(sel("os", getString(R.string.s0059), d.optString("os"), o.optJSONArray("os"), false));
            f.add(Field.num("disk_gb", getString(R.string.s0137), d.optString("disk_gb", "10")));
            f.add(Field.text("ports", getString(R.string.s0138), d.optString("ports", "")));
            f.add(Field.check("password_login", getString(R.string.s0139), true));
            f.add(scriptField());
            f.add(Field.multi("script", getString(R.string.s0140), ""));
            form(getString(R.string.s0141, Regions.label(region())), null, f, getString(R.string.s0142), v -> {
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
            f.add(Field.text("name", getString(R.string.s0135), "vm-" + Long.toString(System.currentTimeMillis() / 1000, 36)));
            f.add(regionSel("location", getString(R.string.s0010), Api.pref("azloc_" + id, d.optString("location", "eastasia")), Api.arr(r)));
            String[] sizes = {"Standard_B1s", "Standard_B1ms", "Standard_B2ats_v2", "Standard_B2pts_v2", "Standard_B2s", "Standard_D2as_v5"};
            String ds = d.optString("size", "Standard_B1s");
            if (!Arrays.asList(sizes).contains(ds)) { sizes = Arrays.copyOf(sizes, sizes.length + 1); sizes[sizes.length - 1] = ds; }
            f.add(Field.select("size", getString(R.string.s0143), ds, sizes, null));
            f.add(Field.select("os", getString(R.string.s0059), d.optString("os", "debian-12"), new String[]{"debian-12", "ubuntu-24.04", "ubuntu-22.04"}, null));
            f.add(Field.num("disk_gb", getString(R.string.s0144), d.optString("disk_gb", "30")));
            f.add(Field.select("disk_type", getString(R.string.s0145), "StandardSSD_LRS", new String[]{"StandardSSD_LRS", "Standard_LRS", "Premium_LRS"}, null));
            f.add(Field.text("resource_group", getString(R.string.s0146), ""));
            f.add(Field.text("ports", getString(R.string.s0138), ""));
            f.add(Field.check("ipv6", getString(R.string.s0147), false));
            f.add(Field.multi("ssh_key", getString(R.string.s0148), d.optString("ssh_key", "")));
            f.add(Field.check("password_login", getString(R.string.s0149), true));
            f.add(scriptField());
            f.add(Field.multi("script", getString(R.string.s0140), ""));
            form(getString(R.string.s0150), getString(R.string.s0151), f, getString(R.string.s0142), v -> {
                Api.setPref("azloc_" + id, v.optString("location"));
                Api.post(this, "/accounts/" + id + "/azure/create", v, x -> taskOrToast(x, getString(R.string.s0152)));
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
            f.add(Field.text("name", getString(R.string.s0135), "ls-" + Long.toString(System.currentTimeMillis() / 1000, 36)));
            f.add(regionSel("zone", getString(R.string.s0153), d.optString("zone"), o.optJSONArray("zones")));
            f.add(sel("blueprint", getString(R.string.s0154), d.optString("blueprint"), o.optJSONArray("blueprints"), true));
            f.add(sel("bundle", getString(R.string.s0155), d.optString("bundle"), o.optJSONArray("bundles"), true));
            f.add(Field.select("ip_type", getString(R.string.s0156), "dualstack", new String[]{"dualstack", "ipv6"}, new String[]{"IPv4 + IPv6", getString(R.string.s0157)}));
            f.add(Field.check("password_login", getString(R.string.s0158), true));
            f.add(scriptField());
            f.add(Field.multi("user_data", getString(R.string.s0159), ""));
            form(getString(R.string.s0160), null, f, getString(R.string.s0142), v -> {
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
    /** A1 免费额度按账号类型（与后端 core.oci_a1_free 一致）：plan_type 为 FREE_TIER → free，其他非空 → paid，未知 → unknown。 */
    String a1Basis() {
        JSONObject a = acc;
        if (Api.accounts != null)
            for (int i = 0; i < Api.accounts.length(); i++) if (Api.accounts.optJSONObject(i).optInt("id") == id) a = Api.accounts.optJSONObject(i);
        try {
            String raw = str(a, "acct_type", "");
            String plan = raw.isEmpty() ? "" : str(new JSONObject(raw), "plan_type", "");
            return plan.isEmpty() ? "unknown" : "FREE_TIER".equals(plan) ? "free" : "paid";
        } catch (Exception e) { return "unknown"; }
    }

    String[] shapeLabels() {
        String[] l = SHAPE_LABELS.clone();
        String b = a1Basis();
        if ("free".equals(b)) l[0] = getString(R.string.s0161);
        else if ("paid".equals(b)) l[0] = getString(R.string.s0162);
        return l;
    }

    private void ociCreate(boolean snatch) {
        JSONObject d = defaults.optJSONObject("oci");
        if (d == null) d = new JSONObject();
        boolean freeA1 = !"paid".equals(a1Basis());   // 免费号 / 未知按 2 OCPU / 12 GB 给默认值
        LinearLayout c = card(snatch ? getString(R.string.s0003) : getString(R.string.s0002));
        muted(c, snatch ? getString(R.string.s0163) : getString(R.string.s0164));
        String b0 = a1Basis();
        muted(c, getString(R.string.s0168, ("paid".equals(b0) ? getString(R.string.s0165) : "free".equals(b0) ? getString(R.string.s0166)
                : getString(R.string.s0167))));
        String[] shapes = SHAPES;
        List<Field> f = new ArrayList<>(Arrays.asList(
                Field.text("name", getString(R.string.s0169), "oci-" + Long.toString(System.currentTimeMillis() / 1000, 36)),
                Field.select("shape", getString(R.string.s0170), d.optString("shape", shapes[0]), shapes, shapeLabels()),
                Field.num("ocpus", "OCPU", d.optString("ocpus", freeA1 ? "2" : "4")),
                Field.num("memory_gb", getString(R.string.s0126), d.optString("memory_gb", freeA1 ? "12" : "24")),
                Field.num("disk_gb", getString(R.string.s0171), d.optString("disk_gb", "50")),
                osImageField(d.optString("os", "Canonical Ubuntu"), str(d, "os_version", "")),
                Field.text("ad", getString(R.string.s0172), str(d, "ad", "")),
                Field.text("subnet_id", getString(R.string.s0173), str(d, "subnet_id", "")),
                Field.multi("ssh_key", getString(R.string.s0174), str(d, "ssh_key", "")),
                Field.check("ipv6", getString(R.string.s0175), d.optBoolean("ipv6", false)),
                Field.check("password_login", getString(R.string.s0139), true),
                scriptField(),
                Field.multi("script", getString(R.string.s0140), "")));
        if (snatch) {
            f.add(Field.num("interval", getString(R.string.s0176), "60"));
            f.add(Field.num("max_attempts", getString(R.string.s0177), "0"));
        }
        LinearLayout r = row(c);
        button(r, snatch ? getString(R.string.s0178) : getString(R.string.s0179), v -> form(snatch ? getString(R.string.s0180) : getString(R.string.s0181), null, f, snatch ? getString(R.string.s0182) : getString(R.string.s0142), vals -> {
            try {
                JSONObject create = splitOsImage(new JSONObject(vals.toString()));
                Object interval = create.remove("interval"), maxa = create.remove("max_attempts");
                JSONObject b = new JSONObject().put("region", region()).put("create", create);
                if (snatch) {
                    b.put("interval", interval).put("max_attempts", maxa);
                    Api.post(this, "/accounts/" + id + "/oci/snatch", b, x -> taskOrToast(x, getString(R.string.s0183)));
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
            for (int i = 2; i < o.length; i++) { opts.add(o[0] + "|" + o[i]); labels.add(o[1] + " " + (o[i].isEmpty() ? getString(R.string.s0061) : o[i])); }
        String def = os + "|" + (ver == null ? "" : ver);
        if (!opts.contains(def)) {
            boolean known = false;
            for (String[] o : OCI_OS) if (o[0].equals(os)) known = true;
            if (known) { opts.add(def); labels.add(os + " " + ver); }   // 默认值里的版本不在列表里：临时加一个选项
            else def = opts.get(0);                                       // 已移除的系统（如 CentOS）回落到 Ubuntu 最新
        }
        return Field.select("os_image", getString(R.string.s0184), def, opts.toArray(new String[0]), labels.toArray(new String[0]));
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
        if (pw.isEmpty() || "null".equals(pw)) { toast(getString(R.string.s0185, o.optString("name"))); return; }
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s0186, o.optString("name")))
                .setMessage(getString(R.string.s0187, o.optString("username"), pw))
                .setPositiveButton(getString(R.string.s0188), (dd, w) -> {
                    android.content.ClipboardManager cm = (android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                    cm.setPrimaryClip(android.content.ClipData.newPlainText("pw", pw));
                    toast(getString(R.string.s0098));
                }).setNegativeButton(getString(R.string.s0074), null).show();
    }

    // ---------------- CloudFront（v1.5：缓存刷新 / 编辑 / 启停 / 套餐 / 删除前自动停用） ----------------
    static final String[] CF_TIERS = {"PAYGO", "FREE", "PRO", "BUSINESS", "PREMIUM"};
    static final String[] CF_TIER_NAMES = {"按量付费", "Free $0/月", "Pro $15/月", "Business $200/月", "Premium $1000/月起"};

    static String cfPlanName(JSONObject d) {
        if (d.isNull("plan") || !d.has("plan")) return getString(R.string.s0189);
        int i = Arrays.asList(CF_TIERS).indexOf(d.optString("plan"));
        return i >= 0 ? CF_TIER_NAMES[i] : d.optString("plan");
    }

    private void cloudfront() {
        bigButton(getString(R.string.s0190), v -> form(getString(R.string.s0191), getString(R.string.s0192), Arrays.asList(
                Field.text("origin", getString(R.string.s0193), ""),
                Field.select("origin_protocol", getString(R.string.s0194), "http-only", new String[]{"http-only", "https-only", "match-viewer"}, new String[]{"HTTP", "HTTPS", getString(R.string.s0195)}),
                Field.select("price_class", getString(R.string.s0196), "all", new String[]{"all", "200", "100"}, new String[]{getString(R.string.s0197), getString(R.string.s0198), getString(R.string.s0199)}),
                Field.select("cache_mode", getString(R.string.s0200), "disabled", new String[]{"disabled", "optimized"}, new String[]{getString(R.string.s0201), getString(R.string.s0202)}),
                Field.check("compress", getString(R.string.s0203), true),
                Field.text("comment", getString(R.string.s0204), "")), getString(R.string.s0142), vals -> {
            try { Api.post(this, "/accounts/" + id + "/cloudfront", vals.put("op", "create"), x -> { toast(getString(R.string.s0205, Api.obj(x).optString("domain"))); refresh(); }); }
            catch (Exception ignored) { }
        }));
        Api.get(this, "/accounts/" + id + "/cloudfront", r -> {
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card(getString(R.string.s0206)), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject d = a.optJSONObject(i);
                String did = d.optString("id");
                boolean en = d.optBoolean("enabled");
                LinearLayout c = card(did + "  [" + d.optString("status") + "]");
                text(c, getString(R.string.s0209, d.optString("domain"), join(d.optJSONArray("origins")), (en ? getString(R.string.s0207) : getString(R.string.s0208)), cfPlanName(d), str(d, "price_class", "-"), (d.optString("comment").isEmpty() ? "" : "\n" + d.optString("comment"))), 13, false);
                LinearLayout row = row(c);
                button(row, getString(R.string.s0210), v -> cfInvalidate(did));
                button(row, getString(R.string.s0211), v -> cfEdit(did));
                button(row, en ? getString(R.string.s0212) : getString(R.string.s0213), v -> confirm(en ? getString(R.string.s0214) : getString(R.string.s0215), en ? getString(R.string.s0216) : getString(R.string.s0217, did), () -> {
                    try { Api.post(this, "/accounts/" + id + "/cloudfront/toggle", new JSONObject().put("distribution_id", did).put("enabled", !en), x -> { toast(Api.obj(x).optString("message")); refresh(); }); }
                    catch (Exception ignored) { }
                }));
                button(row, getString(R.string.s0155), v -> cfPlan(d));
                button(row, getString(R.string.s0057), v -> confirm(getString(R.string.s0218), (en || !"Deployed".equals(d.optString("status")))
                        ? getString(R.string.s0221, did, (en ? getString(R.string.s0219) : getString(R.string.s0220)))
                        : getString(R.string.s0222, did), () -> Api.del(this, "/accounts/" + id + "/cloudfront/" + Api.enc(did) + "?confirm=true", x -> {
                    JSONObject o = Api.obj(x);
                    if (o.optBoolean("deleted")) toast(getString(R.string.s0223)); else taskOrToast(x, getString(R.string.s0224));
                    refresh();
                })));
            }
        });
    }

    private void cfInvalidate(String did) {
        form(getString(R.string.s0225, did), getString(R.string.s0226), Arrays.asList(Field.multi("paths", getString(R.string.s0227), "/*")), getString(R.string.s0228), v -> {
            try {
                Api.post(this, "/accounts/" + id + "/cloudfront/invalidate", new JSONObject().put("distribution_id", did).put("paths", v.optString("paths")), x -> {
                    JSONObject o = Api.obj(x);
                    toast(getString(R.string.s0229, o.optString("invalidation_id"), join(o.optJSONArray("paths"))));
                });
            } catch (Exception ignored) { }
        });
    }

    private void cfEdit(String did) {
        Api.get(this, "/accounts/" + id + "/cloudfront/" + Api.enc(did) + "/config", r -> {
            JSONObject c = Api.obj(r);
            List<Field> f = new ArrayList<>(Arrays.asList(
                    Field.text("comment", getString(R.string.s0204), c.optString("comment")),
                    Field.text("origin_domain", getString(R.string.s0230), c.optString("origin_domain")),
                    Field.select("price_class", getString(R.string.s0196), c.optString("price_class"), new String[]{"100", "200", "All"}, null),
                    Field.text("default_root_object", getString(R.string.s0231), c.optString("default_root_object"))));
            if (!c.optString("origin_protocol").isEmpty())
                f.add(Field.select("origin_protocol", getString(R.string.s0194), c.optString("origin_protocol"), new String[]{"http-only", "https-only", "match-viewer"}, null));
            form(getString(R.string.s0232, did), getString(R.string.s0233), f, getString(R.string.s0089), v ->
                    Api.async(this, "PUT", "/accounts/" + id + "/cloudfront/" + Api.enc(did), v, x -> { toast(Api.obj(x).optString("message")); refresh(); }));
        });
    }

    private void cfPlan(JSONObject d) {
        String did = d.optString("id");
        choose(getString(R.string.s0234, cfPlanName(d)), CF_TIER_NAMES, i -> {
            String tier = CF_TIERS[i];
            boolean paid = i >= 2;
            Runnable go = () -> {
                try { Api.post(this, "/accounts/" + id + "/cloudfront/plan", new JSONObject().put("distribution_id", did).put("plan_tier", tier).put("confirm", paid),
                        x -> { toast(Api.obj(x).optString("message")); refresh(); }); }
                catch (Exception ignored) { }
            };
            if (paid) confirm(getString(R.string.s0235), getString(R.string.s0236, did, CF_TIER_NAMES[i]), go);
            else go.run();
        });
    }

    // ---------------- OCI 安全组：按子网选择（build 19，安全列表挂在子网上，同子网实例共享） ----------------
    private String sgSub;

    /** 「VCN / 子网 CIDR · 实例1、实例2」，实例多于 4 台时「… 等 N 台」，与 Web subnetLabel 一致。 */
    static String subnetLabel(JSONObject s) {
        JSONArray ins = s.optJSONArray("instances");
        int n = ins == null ? 0 : ins.length();
        StringBuilder names = new StringBuilder();
        for (int i = 0; i < Math.min(n, 4); i++) { if (i > 0) names.append("、"); names.append(str(ins.optJSONObject(i), "name", "?")); }
        String tail = n == 0 ? getString(R.string.s0237) : names + (n > 4 ? getString(R.string.s0238, n) : "");
        String vcn = str(s, "vcn_name", "");
        return (vcn.isEmpty() ? "" : vcn + " / ") + str(s, "name", getString(R.string.s0239)) + " " + str(s, "cidr", "") + " · " + tail;
    }

    private void secgroup() {
        Api.get(this, "/accounts/" + id + "/oci/security-subnets?" + rq(), r -> {
            if (!"secgroup".equals(tab)) return;
            JSONArray a = Api.obj(r).optJSONArray("subnets");
            if (a == null || a.length() == 0) { muted(card(getString(R.string.s0240)), Regions.label(region())); return; }
            String[] ids = new String[a.length()], labels = new String[a.length()];
            for (int i = 0; i < a.length(); i++) { ids[i] = a.optJSONObject(i).optString("id"); labels[i] = subnetLabel(a.optJSONObject(i)); }
            List<String> idl = Arrays.asList(ids);
            if (sgSub == null || !idl.contains(sgSub)) sgSub = Api.pref("sgsub_" + id, "");
            if (!idl.contains(sgSub)) {   // 旧版记的是实例：换成该实例所在的子网
                String li = Api.pref("sg_" + id, "");
                sgSub = ids[0];
                for (int i = 0; i < a.length(); i++) {
                    JSONArray ins = a.optJSONObject(i).optJSONArray("instances");
                    for (int j = 0; ins != null && j < ins.length(); j++) if (li.equals(ins.optJSONObject(j).optString("id"))) sgSub = ids[i];
                }
            }
            Api.setPref("sgsub_" + id, sgSub);
            int si = idl.indexOf(sgSub);
            JSONObject sub = a.optJSONObject(si);
            LinearLayout sc = card(getString(R.string.s0239));
            text(sc, labels[si], 14, true);
            muted(sc, getString(R.string.s0241));
            LinearLayout top = row(sc);
            button(top, getString(R.string.s0242), v -> choose(getString(R.string.s0243), labels, i -> { sgSub = ids[i]; Api.setPref("sgsub_" + id, sgSub); refresh(); }));
            button(top, getString(R.string.s0048), v -> renameSubnet(sub));
            button(top, getString(R.string.s0244), v -> sgAdd());
            // 实例另挂的 NSG：只读提示
            StringBuilder ns = new StringBuilder();
            JSONArray ins = sub.optJSONArray("instances");
            for (int i = 0; ins != null && i < ins.length(); i++) {
                JSONObject in = ins.optJSONObject(i);
                JSONArray g = in.optJSONArray("nsgs");
                if (g == null || g.length() == 0) continue;
                StringBuilder gn = new StringBuilder();
                for (int j = 0; j < g.length(); j++) { if (j > 0) gn.append("、"); gn.append(str(g.optJSONObject(j), "name", "?")); }
                ns.append(str(in, "name", "?")).append(getString(R.string.s0245)).append(gn).append("\n");
            }
            if (ns.length() > 0) {
                LinearLayout nc = card(getString(R.string.s0246));
                text(nc, ns.toString().trim(), 13, false);
                muted(nc, getString(R.string.s0247));
            }
            Api.get(this, "/accounts/" + id + "/security-rules?subnet_id=" + Api.enc(sgSub) + "&" + rq(), x -> {
                if (!"secgroup".equals(tab)) return;
                JSONArray rules = Api.obj(x).optJSONArray("rules");
                sgRules = rules == null ? new JSONArray() : rules;
                sgFilterBar();
            });
        });
    }

    /** 子网 / VCN 改名：只改显示名称（display_name），不影响实例、IP、安全规则；保存后刷新并保持选中。 */
    private void renameSubnet(JSONObject s) {
        String sid = s.optString("id"), vid = str(s, "vcn_id", "");
        String oldS = str(s, "name", ""), oldV = str(s, "vcn_name", "");
        List<Field> f = new ArrayList<>();
        f.add(Field.text("subnet", getString(R.string.s0248), oldS));
        if (!vid.isEmpty()) f.add(Field.text("vcn", getString(R.string.s0249), oldV));
        form(getString(R.string.s0250), getString(R.string.s0251, str(s, "cidr", "")), f, getString(R.string.s0089), v -> {
            String nsub = v.optString("subnet").trim(), nvcn = v.optString("vcn").trim();
            if (nsub.isEmpty() || (!vid.isEmpty() && nvcn.isEmpty())) { toast(getString(R.string.s0090)); return; }
            if (nsub.length() > 255 || nvcn.length() > 255) { toast(getString(R.string.s0252)); return; }
            boolean chS = !nsub.equals(oldS), chV = !vid.isEmpty() && !nvcn.equals(oldV);
            if (!chS && !chV) { toast(getString(R.string.s0253)); return; }
            Runnable done = () -> { toast(getString(R.string.s0091)); sgSub = sid; Api.setPref("sgsub_" + id, sid); refresh(); };
            Runnable vcnStep = () -> { if (chV) patchName("/oci/vcns/" + Api.enc(vid), nvcn, done); else done.run(); };
            if (chS) patchName("/oci/subnets/" + Api.enc(sid), nsub, vcnStep); else vcnStep.run();
        });
    }

    private void patchName(String path, String name, Runnable then) {
        try { Api.async(this, "PATCH", "/accounts/" + id + path, new JSONObject().put("display_name", name).put("region", region()), x -> then.run()); }
        catch (Exception ignored) { }
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
        String[][] opts = {{"all", getString(R.string.s0254)}, {"ingress", getString(R.string.s0255)}, {"egress", getString(R.string.s0256)}};
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
            com.google.android.material.textfield.TextInputLayout til = inputLayout(getString(R.string.s0257), getString(R.string.s0258), android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
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
            LinearLayout c = card(getString(R.string.s0262, (in ? getString(R.string.s0259) : getString(R.string.s0260)), ru.optString("protocol"), ru.optString("port"), (pub ? getString(R.string.s0261) : "")));
            sgCards.add((android.view.View) c.getParent());
            muted(c, ru.optString("cidr") + (ru.optString("desc").isEmpty() ? "" : " · " + ru.optString("desc")) + " · " + ru.optString("sl_name"));
            button(row(c), getString(R.string.s0057), v -> confirm(getString(R.string.s0263), getString(R.string.s0265, (in && "22".equals(ru.optString("port")) ? getString(R.string.s0264) : "")), () -> {
                try {
                    String p = ru.optString("protocol");
                    String proto = "全部".equals(p) ? "all" : p.toLowerCase(Locale.ROOT);
                    JSONObject b = new JSONObject().put("subnet_id", sgSub).put("region", region()).put("sl_id", ru.optString("sl_id"))
                            .put("direction", ru.optString("direction")).put("protocol", proto).put("cidr", ru.optString("cidr"))
                            .put("port_min", ru.opt("port_min")).put("port_max", ru.opt("port_max"));
                    Api.async(this, "DELETE", "/accounts/" + id + "/security-rules", b, y -> { toast(getString(R.string.s0223)); refresh(); });
                } catch (Exception ignored) { }
            }));
        }
        if (shown == 0) {
            LinearLayout c = card(sgRules.length() == 0 ? getString(R.string.s0266) : getString(R.string.s0267));
            sgCards.add((android.view.View) c.getParent());
        }
        if (sgCount != null) sgCount.setText(shown == sgRules.length() ? getString(R.string.s0268, shown) : getString(R.string.s0269, shown, sgRules.length()));
    }

    private void sgAdd() {
        form(getString(R.string.s0270), getString(R.string.s0271), Arrays.asList(
                Field.select("direction", getString(R.string.s0272), "ingress", new String[]{"ingress", "egress"}, new String[]{getString(R.string.s0255), getString(R.string.s0256)}),
                Field.select("protocol", getString(R.string.s0104), "tcp", new String[]{"tcp", "udp", "icmp", "icmpv6", "all"}, new String[]{"TCP", "UDP", "ICMP", "ICMPv6", getString(R.string.s0273)}),
                Field.text("cidr", getString(R.string.s0274), ""),
                Field.multi("ports", getString(R.string.s0275), ""),
                Field.text("description", getString(R.string.s0276), "")), getString(R.string.s0277), v -> {
            try {
                JSONObject b = new JSONObject(v.toString()).put("subnet_id", sgSub).put("region", region());
                String cidr = v.optString("cidr").replace(" ", "");
                Runnable send = () -> Api.post(this, "/accounts/" + id + "/security-rules", b, x -> {
                    JSONObject o = Api.obj(x);
                    toast(getString(R.string.s0279, o.optInt("added"), (o.optInt("skipped") > 0 ? getString(R.string.s0278, o.optInt("skipped")) : "")));
                    refresh();
                });
                if ("ingress".equals(v.optString("direction")) && ("0.0.0.0/0".equals(cidr) || "::/0".equals(cidr))) {
                    b.put("confirm_public", true);
                    confirm(getString(R.string.s0107), getString(R.string.s0280, cidr), send);
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
        muted(card(getString(R.string.s0281)), getString(R.string.s0282));
        Api.get(this, "/accounts/" + id + "/oci/traffic-summary?" + rq(), r -> {
            header();
            JSONObject d = Api.obj(r);
            double free = d.optDouble("free_out_gb", 10240), out = d.optDouble("out_gb", 0);
            LinearLayout c = card(getString(R.string.s0283));
            text(c, gb(d, "out_gb") + " / " + gb(d, "free_out_gb"), 24, true);
            muted(c, String.format(java.util.Locale.US, "已用 %.2f%% · 入站 %s（不计费）· %s UTC", free > 0 ? out / free * 100 : 0, gb(d, "in_gb"), d.optString("period")));
            muted(c, getString(R.string.s0284));
            JSONArray items = d.optJSONArray("items");
            if (items == null || items.length() == 0) { muted(card(getString(R.string.s0285)), Regions.label(region())); return; }
            java.util.Map<String, android.widget.TextView> gtv = new java.util.HashMap<>();
            java.util.Map<String, LinearLayout> grow = new java.util.HashMap<>();
            for (int i = 0; i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i);
                LinearLayout ic = card(it.optString("name") + " · " + it.optString("state"));
                if (it.has("error")) muted(ic, getString(R.string.s0286, it.optString("error")));
                else text(ic, getString(R.string.s0287, gb(it, "out_gb"), gb(it, "in_gb")), 16, true);
                muted(ic, str(it, "public_ip", "-") + " · " + it.optString("shape"));
                gtv.put(it.optString("id"), muted(ic, getString(R.string.s0288)));
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
                    if (g == null) { tv.setText(getString(R.string.s0289)); button(rr, getString(R.string.s0290), v -> traffic(it, "vm")); continue; }
                    tv.setText(getString(R.string.s0297, (g.optInt("enabled", 1) == 1 ? str(g, "status_text", getString(R.string.s0291)) : getString(R.string.s0292)), str(g, "last_gb", "-"), str(g, "limit_gb", "-"), ("stop".equals(g.optString("action")) ? getString(R.string.s0293) : "throttle".equals(g.optString("action")) ? getString(R.string.s0294, str(g, "throttle_mbps", "1")) : getString(R.string.s0295)), (g.optInt("acct_enabled") == 1 ? getString(R.string.s0296) : "")));
                    int gid = g.optInt("id");
                    button(rr, getString(R.string.s0298), v -> traffic(it, "vm"));
                    button(rr, getString(R.string.s0299), v -> startActivity(new android.content.Intent(this, GuardAgentActivity.class).putExtra("gid", gid).putExtra("name", it.optString("name"))));
                    button(rr, getString(R.string.s0300), v -> Api.post(this, "/traffic-guards/" + gid + "/check", null, x -> { toast(getString(R.string.s0301)); refresh(); }));
                    button(rr, getString(R.string.s0302), v -> confirm(getString(R.string.s0263), getString(R.string.s0303), () -> Api.del(this, "/traffic-guards/" + gid, x -> { toast(getString(R.string.s0223)); refresh(); })));
                }
            });
        });
    }

    private void quota(boolean force) {
        muted(card(getString(R.string.s0304)), getString(R.string.s0305));
        Api.get(this, "/accounts/" + id + "/quotas" + (force ? "?refresh=true" : ""), r -> {
            header();
            JSONObject q = Api.obj(r);
            JSONObject v = q.optJSONObject("standard_vcpu"), cf = q.optJSONObject("cloudfront_distributions");
            LinearLayout c1 = card(getString(R.string.s0306));
            text(c1, v == null ? "-" : v.optString("value") + " " + v.optString("unit"), 26, true);
            muted(c1, getString(R.string.s0307, (v == null ? "-" : Regions.label(v.optString("region")))));
            LinearLayout c2 = card(getString(R.string.s0308));
            text(c2, cf == null ? "-" : str(cf, "value", "-") + " " + cf.optString("unit"), 26, true);
            muted(c2, getString(R.string.s0309, q.optString("updated_at")));
            bigButton(getString(R.string.s0310), x -> { header(); quota(true); });
        });
    }

    // ---------------- build 20：新号 Credit（AWS 新免费计划 Free Tier credit + 5 个活动一键完成） ----------------
    private int crGen = 0;

    private static String crMoney(JSONObject o, String k) {
        if (o == null || o.isNull(k) || !o.has(k)) return "-";
        String u = o.optString("unit", "USD");
        String v = new java.math.BigDecimal(String.valueOf(o.optDouble(k))).setScale(2, java.math.RoundingMode.HALF_UP).stripTrailingZeros().toPlainString();
        return ("USD".equals(u) || u.isEmpty() ? "$" : u + " ") + v;
    }

    private static String crDate(String s) {
        if (s == null || s.isEmpty() || "null".equals(s)) return "-";
        s = s.replace("T", " ");
        return s.length() > 16 ? s.substring(0, 16) : s;
    }

    private static String crStep(String st) {
        switch (st) {
            case "executed": return getString(R.string.s0311);
            case "failed": return getString(R.string.s0312);
            case "stopped": return getString(R.string.s0313);
            case "skipped": return getString(R.string.s0314);
            case "running": return getString(R.string.s0315);
            default: return getString(R.string.s0316);
        }
    }

    private void credit(boolean refresh) {
        final int g = ++crGen;
        LinearLayout wait = card(getString(R.string.s0317));
        muted(wait, getString(R.string.s0318));
        Api.get(this, "/accounts/" + id + "/aws/credits" + (refresh ? "?refresh=true" : ""), r -> {
            if (!"credit".equals(tab) || g != crGen) return;
            header();
            crRender(Api.obj(r), g);
        });
    }

    private void crRender(JSONObject d, int g) {
        JSONObject p = d.optJSONObject("plan"), rt = d.optJSONObject("running_task");
        boolean running = rt != null;
        if ("ok".equals(d.optString("state")) && p != null) {
            LinearLayout pc = card(getString(R.string.s0319));
            text(pc, crMoney(p, "remaining"), 26, true);
            muted(pc, getString(R.string.s0320, str(p, "type", "-"), str(p, "status", "-"), crDate(p.optString("expires"))));
        } else {
            LinearLayout sc = card(getString(R.string.s0321));
            text(sc, "⚠️ " + str(d, "message", getString(R.string.s0322)), 13, false);
            JSONArray perms = d.optJSONArray("permissions");
            if (perms != null) muted(sc, getString(R.string.s0323, join(perms)));
            if ("not_applicable".equals(d.optString("state"))) muted(sc, getString(R.string.s0324));
        }
        if (running) {
            LinearLayout rc = card(getString(R.string.s0325, rt.optInt("id")));
            JSONArray ks = rt.optJSONArray("activities");
            JSONObject steps = rt.optJSONObject("steps");
            int n = ks == null ? 0 : ks.length(), done = 0;
            for (int i = 0; i < n; i++) {
                JSONObject st = steps == null ? null : steps.optJSONObject(ks.optString(i));
                if (st != null && !Arrays.asList("running", "pending").contains(st.optString("status"))) done++;
            }
            com.google.android.material.progressindicator.LinearProgressIndicator pi = new com.google.android.material.progressindicator.LinearProgressIndicator(this);
            pi.setMax(Math.max(1, n));
            pi.setProgressCompat(done, false);
            rc.addView(pi, new LinearLayout.LayoutParams(-1, -2));
            text(rc, "（" + done + "/" + n + "）" + str(rt, "message", ""), 13, false);
            int tid = rt.optInt("id");
            button(row(rc), getString(R.string.s0326, tid), v -> openTask(tid));
            body.postDelayed(() -> { if (!isFinishing() && "credit".equals(tab) && g == crGen) { clear(); header(); credit(false); } }, 4000);
        }
        LinearLayout ac = card(getString(R.string.s0327));
        muted(ac, str(d, "updated_at", "") + (d.optBoolean("cached") ? getString(R.string.s0328, Math.round(d.optInt("age") / 60.0)) : ""));
        LinearLayout ar = row(ac);
        button(ar, getString(R.string.s0329), v -> { clear(); header(); credit(true); });
        JSONArray pend = d.optJSONArray("pending");
        android.widget.Button allB = button(ar, getString(R.string.s0330), v -> crRunAll(d));
        allB.setEnabled(!running && pend != null && pend.length() > 0);
        android.widget.Button clB = button(ar, getString(R.string.s0331), v -> crCleanup());
        clB.setEnabled(!running);
        JSONArray acts = d.optJSONArray("activities");
        for (int i = 0; acts != null && i < acts.length(); i++) {
            JSONObject a = acts.optJSONObject(i);
            String key = a.optString("key");
            LinearLayout c = card(a.optString("label") + " · " + a.optString("status_text"));
            if (!a.isNull("title") && !a.optString("title").isEmpty()) muted(c, a.optString("title"));
            String when = !a.isNull("completed_at") && !a.optString("completed_at").isEmpty() ? getString(R.string.s0332, crDate(a.optString("completed_at")))
                    : !a.isNull("started_at") && !a.optString("started_at").isEmpty() ? getString(R.string.s0333, crDate(a.optString("started_at"))) : "";
            text(c, getString(R.string.s0334, crMoney(a, "reward"), (when.isEmpty() ? "" : " · " + when)), 13, false);
            muted(c, a.optString("plan"));
            if (!a.isNull("note") && !a.optString("note").isEmpty()) muted(c, "ℹ️ " + a.optString("note"));
            JSONObject lr = a.optJSONObject("last_run");
            if (lr != null) {
                String st = lr.optString("status");
                text(c, getString(R.string.s0335, lr.optInt("task_id"), crStep(st), ("failed".equals(st) && !lr.optString("message").isEmpty() ? "：" + lr.optString("message") : "")), 12, false);
            }
            if (a.optBoolean("runnable")) {
                android.widget.Button rb = button(row(c), getString(R.string.s0336), v -> crRun(a));
                rb.setEnabled(!running);
            } else if (a.optBoolean("completed")) muted(c, getString(R.string.s0337));
        }
        JSONArray notes = d.optJSONArray("notes");
        if (notes != null && notes.length() > 0) {
            LinearLayout nc = card(getString(R.string.s0338));
            for (int i = 0; i < notes.length(); i++) muted(nc, "• " + notes.optString(i));
        }
    }

    private void crRun(JSONObject a) {
        String key = a.optString("key");
        confirm(getString(R.string.s0339, a.optString("label")), getString(R.string.s0340, a.optString("plan"), (a.isNull("note") ? "" : a.optString("note") + "\n\n")), () -> {
            try {
                Api.post(this, "/accounts/" + id + "/aws/credits/activities/" + key + "/run", new JSONObject().put("confirm", true), x -> {
                    toast(Api.obj(x).optString("message"));
                    if ("credit".equals(tab)) { clear(); header(); credit(false); }
                });
            } catch (Exception ignored) { }
        });
    }

    private void crRunAll(JSONObject d) {
        JSONArray acts = d.optJSONArray("activities"), pend = d.optJSONArray("pending");
        List<String> names = new ArrayList<>();
        List<String> pl = new ArrayList<>();
        for (int i = 0; pend != null && i < pend.length(); i++) pl.add(pend.optString(i));
        for (int i = 0; acts != null && i < acts.length(); i++) if (pl.contains(acts.optJSONObject(i).optString("key"))) names.add(acts.optJSONObject(i).optString("label"));
        confirm(getString(R.string.s0330), getString(R.string.s0341, android.text.TextUtils.join("、", names)),
                () -> dangerConfirm(getString(R.string.s0342), getString(R.string.s0343), getString(R.string.s0344), () -> {
                    try {
                        Api.post(this, "/accounts/" + id + "/aws/credits/run-all", new JSONObject().put("confirm", true), x -> {
                            JSONObject o = Api.obj(x);
                            JSONArray sk = o.optJSONArray("skipped");
                            StringBuilder sb = new StringBuilder(o.optString("message"));
                            for (int i = 0; sk != null && i < sk.length(); i++) sb.append(i == 0 ? "：" : "；").append(sk.optJSONObject(i).optString("reason"));
                            toast(sb.toString());
                            if ("credit".equals(tab)) { clear(); header(); credit(false); }
                        });
                    } catch (Exception ignored) { }
                }));
    }

    private void crCleanup() {
        form(getString(R.string.s0345), getString(R.string.s0346),
                Arrays.asList(Field.check("include_budget", getString(R.string.s0347), false)), getString(R.string.s0348), v -> {
                    boolean ib = v.optBoolean("include_budget") || "1".equals(v.optString("include_budget")) || "true".equals(v.optString("include_budget"));
                    try {
                        Api.post(this, "/accounts/" + id + "/aws/credits/cleanup", new JSONObject().put("confirm", true).put("include_budget", ib), x -> {
                            JSONObject o = Api.obj(x);
                            JSONArray del = o.optJSONArray("deleted"), er = o.optJSONArray("errors");
                            int n = del == null ? 0 : del.length(), e = er == null ? 0 : er.length();
                            StringBuilder sb = new StringBuilder();
                            if (n > 0) {
                                sb.append(getString(R.string.s0349)).append(n).append(getString(R.string.s0350));
                                for (int i = 0; i < n; i++) sb.append(i == 0 ? "" : "、").append(del.optJSONObject(i).optString("id"));
                            } else if (e == 0) sb.append(getString(R.string.s0351));
                            for (int i = 0; i < e; i++) sb.append(i == 0 ? (n > 0 ? getString(R.string.s0352) : getString(R.string.s0353)) : "；").append(er.optJSONObject(i).optString("error"));
                            toast(sb.toString());
                        });
                    } catch (Exception ignored) { }
                });
    }

    // ---------------- 回收站估算 ----------------
    private void recycle() {
        LinearLayout wait = card(getString(R.string.s0354));
        muted(wait, getString(R.string.s0355));
        Api.get(this, "/accounts/" + id + "/recycle?" + rq(), r -> {
            header();
            JSONObject d = Api.obj(r);
            JSONArray items = d.optJSONArray("items");
            int n = items == null ? 0 : items.length();
            LinearLayout c = card(getString(R.string.s0356));
            text(c, "$" + d.optString("monthly_total"), 26, true);
            muted(c, getString(R.string.s0357, Regions.label(d.optString("region")), n));
            LinearLayout b = card(getString(R.string.s0358));
            text(b, d.isNull("month_to_date") ? "—" : "$" + d.optString("month_to_date"), 22, true);
            muted(b, getString(R.string.s0359, d.optString("billing_updated_at")));
            if (!d.isNull("credit_remaining")) {
                String m = d.isNull("credit_months_for_idle") ? "" : getString(R.string.s0360, d.optString("credit_months_for_idle"));
                muted(b, getString(R.string.s0361, d.optString("credit_remaining"), m));
            }
            if (n == 0) { muted(card(getString(R.string.s0362)), getString(R.string.s0363)); return; }
            for (int i = 0; i < n; i++) {
                JSONObject it = items.optJSONObject(i);
                LinearLayout ic = card(getString(R.string.s0364, it.optString("name"), it.optString("monthly")));
                muted(ic, it.optString("detail"));
                muted(ic, it.optString("tip"));
            }
        });
    }

    // ---------------- 账单 ----------------
    private void billing(boolean force) {
        Api.get(this, "/accounts/" + id + "/billing" + (force ? "?force=true" : ""), r -> {
            JSONObject b = Api.obj(r);
            LinearLayout c = card(getString(R.string.s0365));
            boolean noCache = b.optBoolean("no_cache");
            text(c, (noCache ? "—" : b.optString("total")) + " " + b.optString("currency"), 26, true);
            muted(c, getString(R.string.s0366, b.optString("period"), b.optString("updated_at")));
            if (noCache) muted(c, getString(R.string.s0367, b.optString("next_refresh")));
            boolean aws = "aws".equals(prov);
            if (aws) {
                muted(c, getString(R.string.s0368, b.optString("next_refresh"), b.optInt("ce_calls_this_month")));
                LinearLayout rr = row(c);
                button(rr, getString(R.string.s0369), v -> confirm(getString(R.string.s0370), getString(R.string.s0371), () -> { header(); billing(true); }));
            }
            LinearLayout s = card(getString(R.string.s0372));
            JSONArray sv = b.optJSONArray("services");
            StringBuilder sb = new StringBuilder();
            for (int i = 0; sv != null && i < sv.length(); i++)
                sb.append(sv.optJSONObject(i).optString("service")).append("：").append(sv.optJSONObject(i).optString("amount")).append("\n");
            text(s, sb.length() == 0 ? getString(R.string.s0373) : sb.toString().trim(), 13, false);
            credits();
        });
    }

    // ================= v1.4：Credit 与教育优惠 / Azure 订阅 =================
    static String money(JSONObject o, String k) { return o == null || !o.has(k) || o.isNull(k) ? "—" : "$" + String.format(Locale.US, "%.2f", o.optDouble(k)); }

    private void credits() {
        Api.get(this, "/accounts/" + id + "/credit-summary", r -> {
            JSONObject s = Api.obj(r);
            LinearLayout c = card(getString(R.string.s0374));
            JSONArray al = s.optJSONArray("alerts");
            for (int i = 0; al != null && i < al.length(); i++) {
                JSONObject a = al.optJSONObject(i);
                text(c, "⏰ " + a.optString("name") + " " + (a.optInt("days_left") == 0 ? getString(R.string.s0375) : getString(R.string.s0376, a.optInt("days_left")))
                        + "（" + a.optString("date") + (a.optBoolean("estimated") ? getString(R.string.s0377) : "") + "）", 13, true);
            }
            String src = "manual".equals(s.optString("used_source")) ? getString(R.string.s0378) : "billing".equals(s.optString("used_source")) ? getString(R.string.s0379) : getString(R.string.s0380);
            text(c, getString(R.string.s0382, money(s, "credit_total"), (s.optBoolean("credit_total_manual") ? getString(R.string.s0381) : ""), money(s, "used"), src, money(s, "remaining")), 15, false);
            muted(c, getString(R.string.s0385, str(s, "estimate_note", "-"), ("aws".equals(prov) ? getString(R.string.s0383) : getString(R.string.s0384))));
            JSONArray items = s.optJSONArray("items");
            for (int i = 0; items != null && i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i);
                LinearLayout ic = card(it.optString("name"));
                text(ic, getString(R.string.s0389, money(it, "amount"), money(it, "used"), ("manual".equals(it.optString("used_source")) ? getString(R.string.s0386) : ""), money(it, "remaining"), str(it, "expire_date", "-"), (it.has("days_left") && !it.isNull("days_left") ? (it.optBoolean("expired") ? getString(R.string.s0387) : getString(R.string.s0388, it.optInt("days_left"))) : "")), 13, false);
                LinearLayout ir = row(ic);
                int cid = it.optInt("id");
                button(ir, getString(R.string.s0211), v -> creditForm(it));
                button(ir, getString(R.string.s0057), v -> confirm(getString(R.string.s0390), it.optString("name"), () -> Api.del(this, "/accounts/" + id + "/credits-manual/" + cid, x -> refresh())));
            }
            LinearLayout info = card(getString(R.string.s0391));
            text(info, getString(R.string.s0394, (s.isNull("cloud_created_at") ? getString(R.string.s0392) : getString(R.string.s0393, s.optString("cloud_created_at"), s.optInt("age_days")))), 13, false);
            JSONObject edu = s.optJSONObject("edu");
            if (edu != null) text(info, getString(R.string.s0398, (edu.isNull("expires_at") ? getString(R.string.s0395) : getString(R.string.s0397, edu.optString("expires_at"), (edu.optBoolean("estimated") ? getString(R.string.s0396) : ""), edu.optInt("days_left"))), edu.optString("basis")), 13, false);
            LinearLayout br = row(c);
            button(br, getString(R.string.s0399), v -> creditForm(null));
            button(br, getString(R.string.s0400), v -> form(getString(R.string.s0401), getString(R.string.s0402), Arrays.asList(
                    Field.num("credit_total", getString(R.string.s0403), s.optBoolean("credit_total_manual") ? s.optString("credit_total") : "")), getString(R.string.s0089),
                    vals -> Api.async(this, "PUT", "/accounts/" + id + "/credit-total", vals, x -> refresh())));
            button(row(info), getString(R.string.s0404), v -> datesForm(s));
        });
    }

    private void creditForm(JSONObject it) {
        boolean edit = it != null;
        form(edit ? getString(R.string.s0405) : getString(R.string.s0406), getString(R.string.s0407), Arrays.asList(
                Field.text("name", getString(R.string.s0135), edit ? it.optString("name") : "Credit"),
                Field.num("amount", getString(R.string.s0408), edit ? it.optString("amount") : ""),
                Field.num("used_manual", getString(R.string.s0409), edit && !it.isNull("used_manual") ? it.optString("used_manual") : ""),
                Field.text("start_date", getString(R.string.s0410), edit ? str(it, "start_date", "") : ""),
                Field.text("expire_date", getString(R.string.s0411), edit ? str(it, "expire_date", "") : "")), getString(R.string.s0089), vals -> {
            if (edit) Api.async(this, "PUT", "/accounts/" + id + "/credits-manual/" + it.optInt("id"), vals, x -> refresh());
            else Api.post(this, "/accounts/" + id + "/credits-manual", vals, x -> refresh());
        });
    }

    private void datesForm(JSONObject s) {
        List<Field> f = new ArrayList<>();
        f.add(Field.text("cloud_created_at", getString(R.string.s0412), str(s, "cloud_created_at", "")));
        if ("azure".equals(prov)) f.add(Field.text("edu_expires_at", getString(R.string.s0413), str(acc, "edu_expires_at", "")));
        form(getString(R.string.s0414), getString(R.string.s0415), f, getString(R.string.s0089), vals -> Api.async(this, "PATCH", "/accounts/" + id, vals, x -> {
            try { acc.put("cloud_created_at", vals.optString("cloud_created_at")); if (vals.has("edu_expires_at")) acc.put("edu_expires_at", vals.optString("edu_expires_at")); } catch (Exception ignored) { }
            refresh();
        }));
    }

    private void subscription() {
        Api.get(this, "/accounts/" + id + "/azure/subscription", r -> {
            JSONObject s = Api.obj(r);
            LinearLayout c = card(getString(R.string.s0416));
            if (s.has("error")) text(c, "❌ " + s.optString("error"), 13, false);
            else text(c, getString(R.string.s0417, str(s, "display_name", "-"), str(s, "state", "-"), str(s, "offer", "-"), str(s, "spending_limit", "-"), str(s, "quota_id", "-"), str(s, "subscription_id", "-")), 13, false);
            JSONObject edu = s.optJSONObject("edu");
            LinearLayout e = card(getString(R.string.s0418));
            if (edu != null) text(e, edu.isNull("expires_at") ? getString(R.string.s0395) : getString(R.string.s0397, edu.optString("expires_at"), (edu.optBoolean("estimated") ? getString(R.string.s0396) : ""), edu.optInt("days_left")), 15, true);
            if (edu != null) muted(e, edu.optString("basis"));
            if (!s.isNull("age_days") && s.has("age_days")) muted(e, getString(R.string.s0419, s.optInt("age_days")));
        });
    }

    // ================= Foundry（Azure AI Services） =================
    private String fdRegion = "swedencentral";

    private void foundry() {
        Api.get(this, "/accounts/" + id + "/azure/foundry?region=" + fdRegion, r -> {
            JSONObject d = Api.obj(r);
            LinearLayout top = card("Foundry（Azure AI）");
            muted(top, getString(R.string.s0420, Regions.label(fdRegion)));
            LinearLayout tr = row(top);
            JSONArray regs = d.optJSONArray("regions");
            button(tr, getString(R.string.s0421), v -> {
                if (regs == null) return;
                String[] l = new String[regs.length()];
                for (int i = 0; i < l.length; i++) l[i] = regs.optString(i);
                choose(getString(R.string.s0010), Regions.labels(l), idx -> { fdRegion = l[idx]; refresh(); });
            });
            button(tr, getString(R.string.s0422), v -> fdDeploy(null, d.optJSONArray("models")));
            JSONArray res = d.optJSONArray("resources");
            if (res == null || res.length() == 0) muted(card(getString(R.string.s0423)), getString(R.string.s0424));
            for (int i = 0; res != null && i < res.length(); i++) {
                JSONObject x = res.optJSONObject(i);
                LinearLayout c = card(x.optString("name") + "  [" + x.optString("kind") + "]");
                StringBuilder sb = new StringBuilder(Regions.label(x.optString("region")) + " · " + x.optString("resource_group") + "\n" + str(x, "endpoint", "-"));
                JSONArray deps = x.optJSONArray("deployments");
                for (int j = 0; deps != null && j < deps.length(); j++) {
                    JSONObject dp = deps.optJSONObject(j);
                    sb.append("\n• ").append(dp.optString("name")).append("：").append(dp.optString("model")).append(" ").append(dp.optString("version"))
                            .append(" · ").append(dp.optString("sku")).append(" ").append(dp.optInt("capacity")).append("K TPM");
                }
                text(c, sb.toString(), 13, false);
                LinearLayout rr = row(c);
                String rid = x.optString("id");
                button(rr, "Endpoint / Key", v -> confirm(getString(R.string.s0425), getString(R.string.s0426), () -> {
                    try { Api.post(this, "/accounts/" + id + "/azure/foundry", new JSONObject().put("op", "keys").put("resource_id", rid).put("confirm", true), k -> {
                        JSONObject o = Api.obj(k);
                        String txt = "base_url：" + o.optString("openai_base_url") + "\nKey：" + o.optString("key1");
                        new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle("Endpoint / Key").setMessage(getString(R.string.s0427, txt))
                                .setPositiveButton(getString(R.string.s0428), (dd, w) -> {
                                    android.content.ClipboardManager cm = (android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                                    if (cm != null) cm.setPrimaryClip(android.content.ClipData.newPlainText("key", o.optString("key1")));
                                    toast(getString(R.string.s0098));
                                }).setNegativeButton(getString(R.string.s0074), null).show();
                    }); } catch (Exception ignored) { }
                }));
                button(rr, getString(R.string.s0429), v -> fdDeploy(rid, d.optJSONArray("models")));
                if (deps != null && deps.length() > 0) button(rr, getString(R.string.s0430), v -> {
                    String[] l = new String[deps.length()];
                    for (int j = 0; j < l.length; j++) l[j] = deps.optJSONObject(j).optString("name");
                    choose(getString(R.string.s0431), l, idx -> confirm(getString(R.string.s0430), getString(R.string.s0432, l[idx]), () -> {
                        try { Api.post(this, "/accounts/" + id + "/azure/foundry", new JSONObject().put("op", "delete_deployment").put("resource_id", rid).put("deployment", l[idx]).put("confirm", true), k -> { toast(getString(R.string.s0223)); refresh(); }); }
                        catch (Exception ignored) { }
                    }));
                });
                button(rr, getString(R.string.s0433), v -> confirm(getString(R.string.s0434), getString(R.string.s0435, x.optString("name")), () -> {
                    try { Api.post(this, "/accounts/" + id + "/azure/foundry", new JSONObject().put("op", "delete_resource").put("resource_id", rid).put("confirm", true), k -> { toast(getString(R.string.s0223)); refresh(); }); }
                    catch (Exception ignored) { }
                }));
            }
            LinearLayout qc = card(getString(R.string.s0436, Regions.label(fdRegion)));
            JSONArray q = d.optJSONArray("quotas");
            StringBuilder qs = new StringBuilder();
            for (int i = 0; q != null && i < q.length(); i++) qs.append(q.optJSONObject(i).optString("name")).append("：").append(q.optJSONObject(i).optInt("used")).append(" / ").append(q.optJSONObject(i).optInt("limit")).append("\n");
            text(qc, qs.length() == 0 ? getString(R.string.s0437) : qs.toString().trim(), 12, false);
        });
    }

    private void fdDeploy(String rid, JSONArray models) {
        List<Field> f = new ArrayList<>();
        if (rid == null) {
            f.add(Field.text("name", getString(R.string.s0438), ""));
            f.add(Field.text("resource_group", getString(R.string.s0439), ""));
        }
        int n = models == null ? 0 : models.length();
        String[] mv = new String[Math.max(n, 1)], ml = new String[Math.max(n, 1)];
        if (n == 0) { mv[0] = "gpt-4o-mini|"; ml[0] = "gpt-4o-mini"; }
        for (int i = 0; i < n; i++) { JSONObject m = models.optJSONObject(i); mv[i] = m.optString("name") + "|" + m.optString("version"); ml[i] = m.optString("name") + " " + m.optString("version"); }
        f.add(Field.select("model", getString(R.string.s0440), mv[0], mv, ml));
        f.add(Field.select("sku", getString(R.string.s0441), "GlobalStandard", new String[]{"GlobalStandard", "Standard"}, new String[]{"Global Standard", getString(R.string.s0442)}));
        f.add(Field.num("capacity", getString(R.string.s0443), "10"));
        f.add(Field.text("deployment", getString(R.string.s0444), ""));
        form(rid == null ? getString(R.string.s0445, Regions.label(fdRegion)) : getString(R.string.s0429), getString(R.string.s0446), f, getString(R.string.s0447), v -> {
            try {
                String[] mm = v.optString("model").split("\\|", -1);
                JSONObject b = new JSONObject().put("op", "deploy").put("model", mm[0]).put("sku", v.optString("sku")).put("capacity", v.optString("capacity", "10"));
                if (mm.length > 1 && !mm[1].isEmpty()) b.put("version", mm[1]);
                if (!v.optString("deployment").isEmpty()) b.put("deployment", v.optString("deployment"));
                if (rid != null) b.put("resource_id", rid);
                else {
                    if (!v.optString("name").matches("[a-zA-Z0-9][a-zA-Z0-9-]{1,62}")) { toast(getString(R.string.s0448)); return; }
                    b.put("name", v.optString("name")).put("region", fdRegion);
                    if (!v.optString("resource_group").isEmpty()) b.put("resource_group", v.optString("resource_group"));
                }
                Api.post(this, "/accounts/" + id + "/azure/foundry", b, x -> taskOrToast(x, getString(R.string.s0037)));
            } catch (Exception ignored) { }
        });
    }

    // ================= v1.2 / v1.3 =================
    private void migrate(JSONObject inst) {
        Api.get(this, "/accounts", r -> {
            JSONArray a = Api.arr(r);
            List<JSONObject> ts = new ArrayList<>();
            for (int i = 0; i < a.length(); i++) if (a.optJSONObject(i).optInt("id") != id) ts.add(a.optJSONObject(i));
            if (ts.isEmpty()) { toast(getString(R.string.s0449)); return; }
            String[] labels = new String[ts.size()];
            for (int i = 0; i < labels.length; i++) labels[i] = MainActivity.pname(ts.get(i).optString("provider")) + " · " + ts.get(i).optString("name");
            choose(getString(R.string.s0450), labels, idx -> {
                JSONObject to = ts.get(idx);
                String tp = to.optString("provider");
                List<Field> f = new ArrayList<>();
                f.add(Field.text("name", getString(R.string.s0451), inst.optString("name") + "-new"));
                if ("oci".equals(tp)) {
                    f.add(Field.select("shape", getString(R.string.s0170), "VM.Standard.A1.Flex", new String[]{"VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"}, new String[]{SHAPE_LABELS[0], SHAPE_LABELS[1]}));
                    f.add(Field.num("ocpus", "OCPU", "1"));
                    f.add(Field.num("memory_gb", getString(R.string.s0126), "6"));
                    f.add(Field.num("disk_gb", getString(R.string.s0144), "50"));
                    f.add(osImageField("Canonical Ubuntu", ""));
                } else if ("aws".equals(tp)) {
                    f.add(Field.text("type", getString(R.string.s0136), "t3.micro"));
                    f.add(Field.select("os", getString(R.string.s0059), "debian-12", new String[]{"debian-12", "ubuntu-24.04"}, new String[]{"Debian 12", "Ubuntu 24.04"}));
                    f.add(Field.num("disk_gb", getString(R.string.s0144), "10"));
                } else {
                    f.add(Field.text("location", getString(R.string.s0010), "eastasia"));
                    f.add(Field.text("size", getString(R.string.s0143), "Standard_B1s"));
                    f.add(Field.select("disk_type", getString(R.string.s0046), "Premium_LRS", new String[]{"Premium_LRS", "StandardSSD_LRS"}, new String[]{getString(R.string.s0452), "Standard SSD"}));
                    f.add(Field.num("disk_gb", getString(R.string.s0144), "64"));
                }
                f.add(Field.check("switch_dns", getString(R.string.s0453), true));
                f.add(Field.check("copy_monitor", getString(R.string.s0454), true));
                f.add(Field.check("stop_source", getString(R.string.s0455), false));
                form(getString(R.string.s0456, to.optString("name")), getString(R.string.s0457), f, getString(R.string.s0458), v -> {
                    try {
                        JSONObject create = splitOsImage(new JSONObject(v.toString()));
                        for (String k : new String[]{"switch_dns", "copy_monitor", "stop_source"}) create.remove(k);
                        JSONObject b = new JSONObject().put("from_account_id", id).put("from_region", region()).put("instance_id", inst.optString("id"))
                                .put("name", inst.optString("name")).put("to_account_id", to.optInt("id")).put("create", create)
                                .put("switch_dns", v.optBoolean("switch_dns")).put("copy_monitor", v.optBoolean("copy_monitor")).put("stop_source", v.optBoolean("stop_source"));
                        if (!"azure".equals(tp)) b.put("region", Regions.current(to));
                        Api.post(this, "/migrate", b, x -> taskOrToast(x, getString(R.string.s0037)));
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
        toast(getString(R.string.s0459));
        Api.get(this, "/accounts/" + id + "/oci/boot-volume?instance_id=" + Api.enc(inst.optString("id")) + "&" + rq(), r -> {
            JSONObject bv = Api.obj(r);
            String[] vp = {"10", "20", "30", "40", "50", "60", "70", "80", "90", "100", "110", "120"};
            form(getString(R.string.s0460, inst.optString("name")), getString(R.string.s0461, bv.optString("name"), bv.optString("size_gb"), bv.optString("vpus_per_gb"), bv.optString("state")), Arrays.asList(
                    Field.num("size_gb", getString(R.string.s0462), ""),
                    Field.select("vpus_per_gb", getString(R.string.s0463), bv.optString("vpus_per_gb", "10"), vp, null),
                    Field.check("grow", getString(R.string.s0464), true)), getString(R.string.s0127), v -> {
                try {
                    JSONObject b = base(inst, kind).put("vpus_per_gb", v.optString("vpus_per_gb")).put("grow", v.optBoolean("grow"));
                    if (!v.optString("size_gb").isEmpty()) b.put("size_gb", v.optString("size_gb"));
                    Api.post(this, "/accounts/" + id + "/oci/boot-volume", b, x -> {
                        JSONObject o = Api.obj(x);
                        JSONObject g = o.optJSONObject("grow");
                        toast(g != null ? getString(R.string.s0466, ("ok".equals(g.optString("status")) ? getString(R.string.s0465) : g.optString("message"))) : str(o, "hint", getString(R.string.s0037)));
                    });
                } catch (Exception ignored) { }
            });
        });
    }

    /** OCI 附加 IP：辅助私网 IP、辅助网卡、预留公网 IP。 */
    private void ociIps(JSONObject inst) {
        toast(getString(R.string.s0467));
        Api.get(this, "/accounts/" + id + "/oci/ips?instance_id=" + Api.enc(inst.optString("id")) + "&" + rq(), r -> {
            JSONObject d = Api.obj(r);
            List<String> labels = new ArrayList<>();
            List<Runnable> acts = new ArrayList<>();
            StringBuilder sb = new StringBuilder();
            JSONArray vnics = d.optJSONArray("vnics");
            for (int i = 0; vnics != null && i < vnics.length(); i++) {
                JSONObject v = vnics.optJSONObject(i);
                boolean pri = v.optBoolean("primary");
                sb.append(pri ? getString(R.string.s0468) : getString(R.string.s0469)).append(" · ").append(v.optString("name")).append("\n");
                JSONArray ips = v.optJSONArray("ips");
                for (int j = 0; ips != null && j < ips.length(); j++) {
                    JSONObject ip = ips.optJSONObject(j);
                    JSONObject pub = ip.optJSONObject("public");
                    sb.append("  ").append(ip.optString("ip")).append(ip.optBoolean("primary") ? getString(R.string.s0470) : "").append(" → ")
                            .append(pub == null ? "-" : pub.optString("ip") + ("RESERVED".equals(pub.optString("lifetime")) ? getString(R.string.s0471) : getString(R.string.s0472))).append("\n");
                    if (!ip.optBoolean("primary")) {
                        String pid = ip.optString("id");
                        labels.add(getString(R.string.s0473, ip.optString("ip")));
                        acts.add(() -> confirm(getString(R.string.s0474), getString(R.string.s0475), () -> ipOp(inst, "delete_private", "private_ip_id", pid)));
                    }
                }
                if (pri) { String vid = v.optString("vnic_id"); labels.add(getString(R.string.s0476)); acts.add(() -> ipOp(inst, "add_secondary", "vnic_id", vid)); }
                else { String aid = v.optString("attachment_id"); labels.add(getString(R.string.s0477, v.optString("name"))); acts.add(() -> confirm(getString(R.string.s0478), getString(R.string.s0479), () -> ipOp(inst, "detach_vnic", "attachment_id", aid))); }
            }
            labels.add(getString(R.string.s0480)); acts.add(() -> ipOp(inst, "attach_vnic", null, null));
            sb.append(getString(R.string.s0481));
            JSONArray res = d.optJSONArray("reserved");
            if (res == null || res.length() == 0) sb.append(getString(R.string.s0482));
            for (int i = 0; res != null && i < res.length(); i++) {
                JSONObject x = res.optJSONObject(i);
                String rid = x.optString("id"), ip = x.optString("ip");
                sb.append("  ").append(ip).append(x.optBoolean("assigned") ? getString(R.string.s0483) : getString(R.string.s0484)).append("\n");
                if (x.optBoolean("assigned")) { labels.add(getString(R.string.s0485, ip)); acts.add(() -> confirm(getString(R.string.s0486), getString(R.string.s0487), () -> ipOp(inst, "unassign_reserved", "public_ip_id", rid))); }
                else {
                    labels.add(getString(R.string.s0488, ip));
                    acts.add(() -> confirm(getString(R.string.s0489), getString(R.string.s0490, ip, inst.optString("name")), () -> {
                        try { Api.post(this, "/accounts/" + id + "/oci/ips", rb().put("instance_id", inst.optString("id")).put("op", "assign_reserved").put("public_ip_id", rid).put("ip", ip), y -> ipDone(y, inst)); }
                        catch (Exception ignored) { }
                    }));
                    labels.add(getString(R.string.s0491, ip)); acts.add(() -> confirm(getString(R.string.s0492), getString(R.string.s0493), () -> ipOp(inst, "delete_reserved", "public_ip_id", rid)));
                }
            }
            labels.add(getString(R.string.s0494)); acts.add(() -> ipOp(inst, "create_reserved", null, null));
            sb.append(getString(R.string.s0495));
            new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s0496, inst.optString("name"))).setMessage(sb.toString())
                    .setPositiveButton(getString(R.string.s0497), (dd, w) -> choose(getString(R.string.s0498), labels.toArray(new String[0]), k -> acts.get(k).run()))
                    .setNegativeButton(getString(R.string.s0074), null).show();
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
        if (!hint.isEmpty()) new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s0499)).setMessage(hint)
                .setPositiveButton(getString(R.string.s0500), (d, w) -> copy("hint", hint)).setNegativeButton(getString(R.string.s0501), (d, w) -> ociIps(inst)).show();
        else { toast(getString(R.string.s0499)); ociIps(inst); }
    }

    /** Azure 磁盘：系统盘 / 数据盘扩容、换类型、调性能层。 */
    private void azDisks(JSONObject inst) {
        toast(getString(R.string.s0502));
        Api.get(this, "/accounts/" + id + "/azure/disks?instance_id=" + Api.enc(inst.optString("id")), r -> {
            JSONObject d = Api.obj(r);
            JSONArray ks = d.optJSONArray("disks");
            int n = ks == null ? 0 : ks.length();
            String[] labels = new String[n];
            for (int i = 0; i < n; i++) {
                JSONObject k = ks.optJSONObject(i);
                labels[i] = ("os".equals(k.optString("role")) ? getString(R.string.s0503) : getString(R.string.s0504, k.optString("lun"))) + " · " + k.optString("size_gb") + " GB · " + str(k, "sku", "-") + " · " + str(k, "tier", "-");
            }
            if (n == 0) { info(getString(R.string.s0505, inst.optString("name")), getString(R.string.s0506, d.optString("hint"))); return; }
            new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s0507, inst.optString("name")))
                    .setItems(labels, (dd, w) -> azDiskEdit(inst, d, ks.optJSONObject(w))).setNegativeButton(getString(R.string.s0074), null).show();
            if (!d.optString("hint").isEmpty()) toast(d.optString("hint"));
        });
    }

    private void azDiskEdit(JSONObject inst, JSONObject d, JSONObject k) {
        JSONArray sk = d.optJSONArray("skus"), tr = d.optJSONArray("tiers");
        String[] skus = new String[sk == null ? 0 : sk.length()];
        for (int i = 0; i < skus.length; i++) skus[i] = sk.optString(i);
        String[] tiers = new String[(tr == null ? 0 : tr.length()) + 1], tl = new String[tiers.length];
        tiers[0] = ""; tl[0] = getString(R.string.s0508);
        for (int i = 1; i < tiers.length; i++) tiers[i] = tl[i] = tr.optString(i - 1);
        List<Field> f = new ArrayList<>();
        f.add(Field.num("size_gb", getString(R.string.s0509, k.optString("size_gb")), ""));
        if (skus.length > 0) f.add(Field.select("sku", getString(R.string.s0510), k.optString("sku"), skus, null));
        f.add(Field.select("tier", getString(R.string.s0511), "", tiers, tl));
        form(getString(R.string.s0512, k.optString("name")), null, f, getString(R.string.s0127), v -> {
            try {
                JSONObject b = new JSONObject().put("instance_id", inst.optString("id")).put("disk_id", k.optString("id"));
                if (!v.optString("size_gb").isEmpty()) b.put("size_gb", v.optString("size_gb"));
                if (v.has("sku") && !v.optString("sku").equals(k.optString("sku"))) b.put("sku", v.optString("sku"));
                if (!v.optString("tier").isEmpty()) b.put("tier", v.optString("tier"));
                Api.post(this, "/accounts/" + id + "/azure/disks", b, x -> { toast(str(Api.obj(x), "hint", getString(R.string.s0513))); azDisks(inst); });
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
                labels[i] = getString(R.string.s0514, p.optString("protocol"), port, (c.isEmpty() ? "-" : String.join(", ", c)));
            }
            com.google.android.material.dialog.MaterialAlertDialogBuilder db = new com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
                    .setTitle(getString(R.string.s0515, inst.optString("name")))
                    .setPositiveButton(getString(R.string.s0049), (dd, w) -> lsOpen(inst)).setNegativeButton(getString(R.string.s0074), null);
            if (labels.length == 0) db.setMessage(getString(R.string.s0516));
            else db.setItems(labels, (dd, w) -> {
                JSONObject p = ps.optJSONObject(w);
                confirm(getString(R.string.s0517), getString(R.string.s0518, p.optString("protocol"), p.optString("from"), p.optString("to")), () -> {
                    try {
                        Api.post(this, "/accounts/" + id + "/lightsail/ports", rb().put("op", "close").put("instance", inst.optString("id")).put("protocol", p.optString("protocol"))
                                .put("from_port", p.optInt("from")).put("to_port", p.optInt("to")), x -> { toast(getString(R.string.s0292)); lsPorts(inst); });
                    } catch (Exception ignored) { }
                });
            });
            db.show();
        });
    }

    private void lsOpen(JSONObject inst) {
        form(getString(R.string.s0049), getString(R.string.s0519), Arrays.asList(
                Field.select("protocol", getString(R.string.s0104), "tcp", new String[]{"tcp", "udp", "icmp"}, new String[]{"TCP", "UDP", "ICMP"}),
                Field.text("port", getString(R.string.s0520), ""),
                Field.text("cidrs", getString(R.string.s0521), "0.0.0.0/0")), getString(R.string.s0522), v -> {
            try {
                String proto = v.optString("protocol");
                java.util.regex.Matcher m = java.util.regex.Pattern.compile("^(\\d+)(?:\\s*-\\s*(\\d+))?$").matcher(v.optString("port"));
                boolean ok = m.matches();
                if (!"icmp".equals(proto) && !ok) { toast(getString(R.string.s0523)); return; }
                int a = "icmp".equals(proto) ? 0 : Integer.parseInt(m.group(1));
                int b = "icmp".equals(proto) ? 0 : Integer.parseInt(m.group(2) != null ? m.group(2) : m.group(1));
                JSONObject body = rb().put("op", "open").put("instance", inst.optString("id")).put("protocol", proto).put("from_port", a).put("to_port", b).put("cidrs", v.optString("cidrs"));
                Runnable send = () -> Api.post(this, "/accounts/" + id + "/lightsail/ports", body, x -> { toast(getString(R.string.s0524)); lsPorts(inst); });
                if (v.optString("cidrs").contains("0.0.0.0/0") || v.optString("cidrs").contains("::/0")) {
                    body.put("confirm_public", true);
                    confirm(getString(R.string.s0107), getString(R.string.s0525, ("icmp".equals(proto) ? "ICMP" : v.optString("port"))), send);
                } else send.run();
            } catch (Exception ignored) { }
        });
    }

    /** Lightsail 静态 IP（Lightsail 标签页下方）。 */
    private void lsStaticIps(JSONArray insts) {
        LinearLayout c = card(getString(R.string.s0526));
        android.widget.TextView t = muted(c, getString(R.string.s0527));
        String[] names = new String[insts.length()];
        for (int i = 0; i < names.length; i++) names[i] = insts.optJSONObject(i).optString("name");
        Api.job(this, () -> {
            try { return Api.call("GET", "/accounts/" + id + "/lightsail/static-ips?" + rq(), null); }
            catch (Exception e) { return new JSONObject().put("error", e.getMessage()); }
        }, r -> {
            if (r instanceof JSONObject) { t.setText("❌ " + ((JSONObject) r).optString("error")); return; }
            JSONArray ips = Api.arr(r);
            t.setText(getString(R.string.s0528));
            LinearLayout row = row(c);
            button(row, getString(R.string.s0529), v -> {
                String[] opts = new String[names.length + 1], labs = new String[names.length + 1];
                opts[0] = ""; labs[0] = getString(R.string.s0530);
                for (int i = 0; i < names.length; i++) opts[i + 1] = labs[i + 1] = names[i];
                form(getString(R.string.s0531), null, Arrays.asList(Field.text("name", getString(R.string.s0135), "ip-" + Long.toString(System.currentTimeMillis() / 1000, 36)),
                        Field.select("instance", getString(R.string.s0532), "", opts, labs)), getString(R.string.s0533), f -> lsIpOp(f, "allocate", getString(R.string.s0534)));
            });
            for (int i = 0; i < ips.length(); i++) {
                JSONObject s = ips.optJSONObject(i);
                String nm = s.optString("name");
                boolean att = s.optBoolean("attached");
                text(c, nm + " · " + s.optString("ip") + " · " + (att ? getString(R.string.s0535, s.optString("attached_to")) : getString(R.string.s0536)), 13, false);
                LinearLayout rr = row(c);
                if (att) button(rr, getString(R.string.s0537, nm), v -> confirm(getString(R.string.s0538), getString(R.string.s0539), () -> lsIpOp(new JSONObject(), "detach", getString(R.string.s0540), "name", nm)));
                else {
                    button(rr, getString(R.string.s0541, nm), v -> {
                        if (names.length == 0) { toast(getString(R.string.s0542)); return; }
                        choose(getString(R.string.s0543), names, k -> lsIpOp(new JSONObject(), "attach", getString(R.string.s0544), "name", nm, "instance", names[k]));
                    });
                    button(rr, getString(R.string.s0545, nm), v -> confirm(getString(R.string.s0546), getString(R.string.s0547), () -> lsIpOp(new JSONObject(), "release", getString(R.string.s0548), "name", nm)));
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
            if (z.length() == 0) { toast(getString(R.string.s0549)); return; }
            String[] ids = new String[z.length()], names = new String[z.length()];
            for (int i = 0; i < ids.length; i++) { ids[i] = z.optJSONObject(i).optString("id") + "|" + z.optJSONObject(i).optString("name"); names[i] = z.optJSONObject(i).optString("name"); }
            form(getString(R.string.s0550, inst.optString("name")), getString(R.string.s0551), Arrays.asList(
                    Field.select("zone", getString(R.string.s0552), ids[0], ids, names),
                    Field.text("record", getString(R.string.s0553), ""),
                    Field.check("v4", getString(R.string.s0554), true),
                    Field.check("v6", getString(R.string.s0555), false),
                    Field.check("proxied", getString(R.string.s0556), false),
                    Field.check("sync_now", getString(R.string.s0557), true)), getString(R.string.s0558), v -> {
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
                        toast(sb.length() > 0 ? sb.toString() : getString(R.string.s0544));
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
            LinearLayout top = card(getString(R.string.s0559));
            muted(top, getString(R.string.s0560, d.optString("used_gb"), d.optString("free_gb")));
            button(row(top), getString(R.string.s0561), v -> {
                String[] opts = new String[iids.length + 1], labs = new String[iids.length + 1];
                opts[0] = ""; labs[0] = getString(R.string.s0562);
                for (int i = 0; i < iids.length; i++) { opts[i + 1] = iids[i]; labs[i + 1] = inames[i]; }
                form(getString(R.string.s0563), getString(R.string.s0564, d.optString("used_gb"), d.optString("free_gb")), Arrays.asList(
                        Field.text("name", getString(R.string.s0135), "data-1"),
                        Field.num("size_gb", getString(R.string.s0565), "50"),
                        Field.select("vpus_per_gb", getString(R.string.s0463), "10", new String[]{"0", "10", "20", "30", "60", "90", "120"},
                                new String[]{getString(R.string.s0566), getString(R.string.s0567), "20", "30", "60", "90", "120"}),
                        Field.select("instance_id", getString(R.string.s0568), "", opts, labs)), getString(R.string.s0142), f -> {
                    try {
                        Api.post(this, "/accounts/" + id + "/oci/volumes", f.put("op", "create").put("region", region()), x -> {
                            JSONObject at = Api.obj(x).optJSONObject("attach");
                            toast(at != null && !str(at, "hint", "").isEmpty() ? at.optString("hint") : getString(R.string.s0569));
                            refresh();
                        });
                    } catch (Exception ignored) { }
                });
            });
            JSONArray vs = d.optJSONArray("volumes");
            if (vs == null || vs.length() == 0) muted(card(getString(R.string.s0570)), "");
            for (int i = 0; vs != null && i < vs.length(); i++) {
                JSONObject v = vs.optJSONObject(i);
                String att = str(v, "attached_to", "");
                int ix = Arrays.asList(iids).indexOf(att);
                LinearLayout c = card(v.optString("name") + "  [" + v.optString("state") + "]");
                text(c, getString(R.string.s0572, v.optString("size_gb"), v.optString("vpus_per_gb"), (att.isEmpty() ? getString(R.string.s0571)
                        : (ix >= 0 ? inames[ix] : att.substring(Math.max(0, att.length() - 10))) + (str(v, "device", "").isEmpty() ? "" : " " + v.optString("device")))), 13, false);
                LinearLayout rr = row(c);
                String vid = v.optString("id");
                button(rr, getString(R.string.s0573), x -> volUpdate(v));
                if (!att.isEmpty()) button(rr, getString(R.string.s0574), x -> confirm(getString(R.string.s0575), getString(R.string.s0576),
                        () -> volOp("detach", "attachment_id", v.optString("attachment_id"), getString(R.string.s0577))));
                else {
                    button(rr, getString(R.string.s0578), x -> {
                        if (iids.length == 0) { toast(getString(R.string.s0029)); return; }
                        choose(getString(R.string.s0579), inames, k -> volOp("attach", "volume_id", vid, "instance_id", iids[k], getString(R.string.s0580)));
                    });
                    button(rr, getString(R.string.s0057), x -> confirm(getString(R.string.s0581), getString(R.string.s0582), () -> volOp("delete", "volume_id", vid, "confirm", "1", getString(R.string.s0223))));
                }
            }
            LinearLayout bc = card(getString(R.string.s0583));
            JSONArray bs = d.optJSONArray("boot_volumes");
            StringBuilder sb = new StringBuilder();
            for (int i = 0; bs != null && i < bs.length(); i++) {
                JSONObject b = bs.optJSONObject(i);
                sb.append(b.optString("name")).append(" · ").append(b.optString("size_gb")).append(" GB · ").append(b.optString("vpus_per_gb")).append(" VPU/GB · ").append(b.optString("state")).append("\n");
            }
            text(bc, sb.length() == 0 ? getString(R.string.s0584) : sb.toString().trim(), 13, false);
            muted(bc, getString(R.string.s0585));
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
        List<Field> f = new ArrayList<>(Arrays.asList(Field.num("size_gb", getString(R.string.s0586, v.optString("size_gb")), ""),
                Field.select("vpus_per_gb", getString(R.string.s0463), v.optString("vpus_per_gb"), vp, null)));
        boolean att = !str(v, "attached_to", "").isEmpty();
        if (att) f.add(Field.check("grow", getString(R.string.s0587), true));
        form(getString(R.string.s0512, v.optString("name")), null, f, getString(R.string.s0127), x -> {
            try {
                JSONObject b = rb().put("op", "update").put("volume_id", v.optString("id")).put("vpus_per_gb", x.optString("vpus_per_gb"));
                if (!x.optString("size_gb").isEmpty()) b.put("size_gb", x.optString("size_gb"));
                if (att) b.put("instance_id", v.optString("attached_to")).put("grow", x.optBoolean("grow"));
                Api.post(this, "/accounts/" + id + "/oci/volumes", b, y -> {
                    JSONObject g = Api.obj(y).optJSONObject("grow");
                    toast(g != null ? getString(R.string.s0589, ("ok".equals(g.optString("status")) ? getString(R.string.s0588) : g.optString("message"))) : getString(R.string.s0037));
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
            LinearLayout bk = card(BK_TITLE);
            muted(bk, getString(R.string.s0590));
            billingKeep(bk, false, false);
            Api.get(this, "/accounts/" + id + "/oci/buckets?" + rq(), r -> {
                JSONObject d = Api.obj(r);
                LinearLayout top = card(getString(R.string.s0006));
                muted(top, getString(R.string.s0591, d.optString("namespace"), d.optString("free_gb")));
                button(row(top), getString(R.string.s0592), v -> form(getString(R.string.s0593), null, Arrays.asList(Field.text("name", getString(R.string.s0594), ""),
                        Field.check("public", getString(R.string.s0595), false)), getString(R.string.s0142), f -> {
                    try { Api.post(this, "/accounts/" + id + "/oci/buckets", f.put("op", "create").put("region", region()), x -> { toast(getString(R.string.s0569)); refresh(); }); }
                    catch (Exception ignored) { }
                }));
                JSONArray bs = d.optJSONArray("buckets");
                if (bs == null || bs.length() == 0) muted(card(getString(R.string.s0596)), "");
                else muted(top, getString(R.string.s0597));
                for (int i = 0; bs != null && i < bs.length(); i++) {
                    JSONObject b = bs.optJSONObject(i);
                    String nm = b.optString("name");
                    LinearLayout c = card("📁 " + nm);
                    muted(c, getString(R.string.s0598, (b.isNull("size") || !b.has("size") ? "—" : fmtBytes(b.optLong("size"))), str(b, "count", "—"), tierLabel(b), b.optString("created")));
                    LinearLayout rr = row(c);
                    button(rr, getString(R.string.s0599), v -> { objBucket = nm; objPrefix = ""; refresh(); });
                    button(rr, getString(R.string.s0057), v -> confirm(getString(R.string.s0600), getString(R.string.s0601, nm), () -> {
                        try { Api.post(this, "/accounts/" + id + "/oci/buckets", rb().put("op", "delete").put("name", nm).put("confirm", true), x -> { toast(getString(R.string.s0223)); refresh(); }); }
                        catch (Exception ignored) { }
                    }));
                }
            });
            return;
        }
        LinearLayout top = card(objBucket + "/" + objPrefix);
        LinearLayout tr = row(top);
        button(tr, getString(R.string.s0602), v -> {
            if (objPrefix.isEmpty()) objBucket = null;
            else objPrefix = objPrefix.replaceAll("[^/]+/$", "");
            refresh();
        });
        button(tr, getString(R.string.s0603), v -> pickFiles.launch(new String[]{"*/*"}));
        Api.get(this, "/accounts/" + id + "/oci/objects?bucket=" + Api.enc(objBucket) + "&prefix=" + Api.enc(objPrefix) + "&" + rq(), r -> {
            JSONObject d = Api.obj(r);
            JSONArray ps = d.optJSONArray("prefixes"), os = d.optJSONArray("objects");
            int shown = 0;
            for (int i = 0; ps != null && i < ps.length(); i++) {
                String p = ps.optString(i);
                LinearLayout c = card("📁 " + p.substring(Math.min(objPrefix.length(), p.length())));
                button(row(c), getString(R.string.s0599), v -> { objPrefix = p; refresh(); });
                shown++;
            }
            for (int i = 0; os != null && i < os.length(); i++) {
                JSONObject o = os.optJSONObject(i);
                String nm = o.optString("name");
                if (nm.equals(objPrefix)) continue;
                LinearLayout c = card(nm.substring(Math.min(objPrefix.length(), nm.length())));
                muted(c, fmtBytes(o.optLong("size")) + " · " + o.optString("created"));
                LinearLayout rr = row(c);
                button(rr, getString(R.string.s0604), v -> {
                    try {
                        Api.post(this, "/accounts/" + id + "/oci/objects", rb().put("op", "url").put("bucket", objBucket).put("name", nm).put("minutes", 60), x -> {
                            JSONObject u = Api.obj(x);
                            String url = u.optString("url");
                            new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s0604))
                                    .setMessage(getString(R.string.s0605, u.optString("expires")))
                                    .setPositiveButton(getString(R.string.s0599), (dd, w) -> { try { startActivity(new android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url))); } catch (Exception e) { toast(getString(R.string.s0606)); } })
                                    .setNeutralButton(getString(R.string.s0500), (dd, w) -> copy("url", url)).setNegativeButton(getString(R.string.s0074), null).show();
                        });
                    } catch (Exception ignored) { }
                });
                button(rr, getString(R.string.s0057), v -> confirm(getString(R.string.s0607), getString(R.string.s0608, nm), () -> {
                    try { Api.post(this, "/accounts/" + id + "/oci/objects", rb().put("op", "delete").put("bucket", objBucket).put("name", nm), x -> { toast(getString(R.string.s0223)); refresh(); }); }
                    catch (Exception ignored) { }
                }));
                shown++;
            }
            if (shown == 0) muted(card(getString(R.string.s0609)), "");
            if (!d.isNull("next") && d.has("next") && !d.optString("next").isEmpty()) muted(card(null), getString(R.string.s0610));
        });
    }

    // ---------------- 保号账单（仅 PAYG，build 19 补到 App）：先检测已有存储，标准层补足到约 11 GB ----------------
    static final String BK_TITLE = "一键生成保号账单";

    static String tierLabel(JSONObject b) {
        String t = str(b, "tier", "");
        if (t.isEmpty()) {
            String st = str(b, "storage_tier", ""), at = str(b, "auto_tiering", "Disabled");
            t = "Archive".equals(st) ? "archive" : "Standard".equals(st) ? (!"Disabled".equals(at) ? "autotier" : "standard") : "unknown";
        }
        switch (t) {
            case "standard": return getString(R.string.s0611);
            case "autotier": return getString(R.string.s0612);
            case "archive": return getString(R.string.s0613);
            default: return "—";
        }
    }

    private static String gib(long n) { return String.format(Locale.US, "%.2f GiB", n / 1073741824.0); }
    private static String gb2(double v) { return String.format(Locale.US, "%.2f GB", v); }
    private static String numStr(double v) { return new java.math.BigDecimal(String.valueOf(v)).stripTrailingZeros().toPlainString(); }

    /** 卡片仍在当前页面上（切换标签 / 打开 Bucket 后丢弃过期回调）。 */
    private boolean bkAlive(LinearLayout el) {
        return "objects".equals(tab) && objBucket == null && el.getParent() != null && el.getParent().getParent() == body;
    }

    private static JSONObject errObj(Exception e) {
        try { return new JSONObject().put("__error", e.getMessage() == null ? e.toString() : e.getMessage()); } catch (Exception x) { return new JSONObject(); }
    }

    /** 红色确认（危险操作）：确认按钮用 colorError。 */
    private void dangerConfirm(String title, String msg, String okText, Runnable ok) {
        androidx.appcompat.app.AlertDialog dlg = new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(title).setMessage(msg)
                .setNegativeButton(getString(R.string.s0614), null).setPositiveButton(okText, (d, w) -> ok.run()).show();
        android.widget.Button pb = dlg.getButton(android.content.DialogInterface.BUTTON_POSITIVE);
        if (pb != null) pb.setTextColor(attr(com.google.android.material.R.attr.colorError));
    }

    private void billingKeep(LinearLayout el, boolean wasRunning, boolean rescan) {
        Api.job(this, () -> {
            try { return Api.call("GET", "/accounts/" + id + "/oci/billing-keep", null); }
            catch (Api.ApiError e) { if (e.code == 401) throw e; return errObj(e); }
        }, r -> {
            if (!bkAlive(el)) return;
            JSONObject d = Api.obj(r);
            el.removeAllViews();
            if (d.has("__error")) { text(el, BK_TITLE, 16, true); muted(el, "❌ " + d.optString("__error")); return; }
            String plan = d.optString("plan");
            text(el, BK_TITLE + " · " + ("paid".equals(plan) ? "PAYG" : "free".equals(plan) ? getString(R.string.s0615) : getString(R.string.s0616)), 16, true);
            if (!d.optBoolean("eligible")) { muted(el, str(d, "hint", "")); return; }   // 免费号：「免费号 20GB 内不收费，无需操作」
            muted(el, d.optString("note"));
            JSONObject t = d.optJSONObject("task");
            if (t != null && "running".equals(t.optString("status"))) {
                long up = t.optLong("uploaded"), tot = t.optLong("total");
                int pct = tot > 0 ? (int) (up * 100 / tot) : 0;
                com.google.android.material.progressindicator.LinearProgressIndicator pi = new com.google.android.material.progressindicator.LinearProgressIndicator(this);
                pi.setMax(100);
                pi.setProgressCompat(pct, false);
                el.addView(pi, new LinearLayout.LayoutParams(-1, -2));
                text(el, getString(R.string.s0617, gib(up), gib(tot), pct), 13, false);
                int tid = t.optInt("id");
                button(row(el), getString(R.string.s0618, tid), v -> openTask(tid));
                body.postDelayed(() -> { if (!isFinishing() && bkAlive(el)) billingKeep(el, true, false); }, 3000);
                return;
            }
            android.widget.TextView wait = muted(el, getString(R.string.s0619));
            boolean fresh = rescan || wasRunning;
            Api.job(this, () -> {
                try { return Api.call("GET", "/accounts/" + id + "/oci/billing-keep/scan" + (fresh ? "?refresh=true" : ""), null); }
                catch (Api.ApiError e) { if (e.code == 401) throw e; return errObj(e); }
            }, sr -> {
                if (!bkAlive(el)) return;
                el.removeView(wait);
                JSONObject sj = Api.obj(sr);
                JSONObject sc = sj.has("__error") ? null : sj;
                bkRender(el, d, sc, sc == null ? sj.optString("__error") : "");
            });
        });
    }

    private void bkRender(LinearLayout el, JSONObject d, JSONObject s, String scanErr) {
        boolean over = s != null && s.optBoolean("over_free");
        double used = s != null ? s.optDouble("standard_gb", 0) : 0;
        double defGb = s != null ? s.optDouble("fill_gb", d.optDouble("default_gb", 11)) : d.optDouble("default_gb", 11);
        if (s != null) {
            JSONArray regs = s.optJSONArray("regions"), bks = s.optJSONArray("buckets");
            int nb = bks == null ? 0 : bks.length();
            text(el, getString(R.string.s0620, gb2(used), numStr(s.optDouble("free_gb", 10))), 14, true);
            muted(el, getString(R.string.s0622, (regs == null ? 0 : regs.length()), nb, (s.optBoolean("cached") ? getString(R.string.s0621, Math.round(s.optInt("age") / 60.0)) : "")));
            text(el, over ? getString(R.string.s0623)
                    : getString(R.string.s0624, numStr(s.optDouble("short_gb")), numStr(defGb), gb2(used + defGb)), 13, false);
            List<String> extra = new ArrayList<>();
            if (s.optDouble("autotier_gb", 0) > 0) extra.add(getString(R.string.s0625, gb2(s.optDouble("autotier_gb"))));
            if (s.optDouble("archive_gb", 0) > 0) extra.add(getString(R.string.s0626, gb2(s.optDouble("archive_gb"))));
            if (s.optInt("unknown_count") > 0) extra.add(getString(R.string.s0627, s.optInt("unknown_count")));
            JSONArray errs = s.optJSONArray("errors");
            if (errs != null && errs.length() > 0) {
                StringBuilder eb = new StringBuilder();
                for (int i = 0; i < errs.length(); i++) { if (i > 0) eb.append("、"); eb.append(Regions.label(errs.optJSONObject(i) == null ? errs.optString(i) : errs.optJSONObject(i).optString("region"))); }
                extra.add(getString(R.string.s0628, eb));
            }
            if (s.optBoolean("compartments_truncated")) extra.add(getString(R.string.s0629, s.optInt("compartments")));
            if (!extra.isEmpty()) muted(el, android.text.TextUtils.join("；", extra) + "。");
            if (nb > 0) {
                StringBuilder lb = new StringBuilder();
                for (int i = 0; i < nb; i++) {
                    JSONObject b = bks.optJSONObject(i);
                    lb.append("• ").append(b.optString("name")).append(b.optBoolean("billing_keep") ? getString(R.string.s0630) : "").append(" · ").append(Regions.label(b.optString("region")))
                            .append(" · ").append(tierLabel(b)).append(" · ").append(b.isNull("size") || !b.has("size") ? "—" : fmtBytes(b.optLong("size")))
                            .append(" · ").append(str(b, "count", "—")).append(getString(R.string.s0631));
                }
                android.widget.TextView lt = text(el, lb.toString().trim(), 12, false);
                lt.setVisibility(android.view.View.GONE);
                android.widget.Button tg = button(row(el), getString(R.string.s0632, nb), null);
                tg.setOnClickListener(v -> lt.setVisibility(lt.getVisibility() == android.view.View.VISIBLE ? android.view.View.GONE : android.view.View.VISIBLE));
            } else muted(el, getString(R.string.s0633));
            muted(el, getString(R.string.s0634));
        } else {
            text(el, getString(R.string.s0635, scanErr, numStr(defGb)), 13, false);
        }
        JSONObject t = d.optJSONObject("task");
        if (d.optBoolean("exists")) {
            text(el, getString(R.string.s0636, d.optString("bucket"), d.optString("object"), gib(d.optLong("size")), Regions.label(d.optString("region")), str(d, "storage_tier", "Standard")), 13, false);
            LinearLayout rr = row(el);
            button(rr, getString(R.string.s0637), v -> billingKeep(el, false, true));
            button(rr, getString(R.string.s0057), v -> bkDelete(el));
            return;
        }
        JSONArray pend = d.optJSONArray("pending_uploads");
        int np = pend == null ? 0 : pend.length();
        boolean resumable = np > 0 && t != null && Arrays.asList("failed", "stopped", "interrupted").contains(t.optString("status")) && t.optLong("uploaded") > 0;
        if (t != null && !"done".equals(t.optString("status"))) muted(el, getString(R.string.s0638, t.optInt("id"), t.optString("status"), str(t, "message", "")));
        double minGb = d.optDouble("min_gb", 0.5), maxGb = d.optDouble("max_gb", 20);
        com.google.android.material.textfield.TextInputLayout til = inputLayout(getString(R.string.s0639, numStr(minGb), numStr(maxGb)), null,
                android.text.InputType.TYPE_CLASS_NUMBER | android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL);
        android.widget.EditText sz = til.getEditText();
        sz.setText(numStr(defGb));
        el.addView(til);
        android.widget.TextView after = muted(el, "");
        Runnable upd = () -> {
            if (s == null) { after.setVisibility(android.view.View.GONE); return; }
            double v;
            try { v = Double.parseDouble(sz.getText().toString().trim()); } catch (Exception e) { v = 0; }
            after.setText(getString(R.string.s0640, gb2(used + v)));
        };
        sz.addTextChangedListener(new android.text.TextWatcher() {
            @Override public void beforeTextChanged(CharSequence q, int x, int y, int z) { }
            @Override public void onTextChanged(CharSequence q, int x, int y, int z) { }
            @Override public void afterTextChanged(android.text.Editable q) { upd.run(); }
        });
        upd.run();
        String goText = resumable ? getString(R.string.s0641, gib(t.optLong("uploaded"))) : over ? getString(R.string.s0642) : getString(R.string.s0643);
        android.view.View.OnClickListener go = v -> {
            double size;
            try { size = Double.parseDouble(sz.getText().toString().trim()); } catch (Exception e) { size = defGb; }
            if (!(size >= minGb && size <= maxGb)) { toast(getString(R.string.s0644, numStr(minGb), numStr(maxGb))); return; }
            double fs = size;
            Runnable start = () -> confirm(BK_TITLE, getString(R.string.s0646, d.optString("note"), numStr(fs), (s != null ? getString(R.string.s0645, gb2(used + fs)) : "")), () -> {
                try {
                    Api.post(this, "/accounts/" + id + "/oci/billing-keep", new JSONObject().put("size_gb", fs).put("confirm", true), x -> {
                        JSONObject o = Api.obj(x);
                        if (o.optBoolean("existed")) toast(getString(R.string.s0647, gib(o.optLong("size"))));
                        else toast(o.optBoolean("resumed") ? getString(R.string.s0648) : getString(R.string.s0649));
                        if (bkAlive(el)) billingKeep(el, false, false);
                    });
                } catch (Exception ignored) { }
            });
            if (over) dangerConfirm(getString(R.string.s0650), getString(R.string.s0651, gb2(used)), getString(R.string.s0652), start);
            else start.run();
        };
        if (over) {
            LinearLayout rr = row(el);
            button(rr, goText, go);
            button(rr, getString(R.string.s0637), v -> billingKeep(el, false, true));
            if (np > 0) button(rr, getString(R.string.s0653), v -> bkDelete(el));
        } else {
            com.google.android.material.button.MaterialButton gb = new com.google.android.material.button.MaterialButton(this);   // Filled：主操作
            gb.setText(goText);
            gb.setAllCaps(false);
            gb.setOnClickListener(go);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.setMargins(0, dp(6), 0, dp(2));
            el.addView(gb, lp);
            LinearLayout rr = row(el);
            button(rr, getString(R.string.s0637), v -> billingKeep(el, false, true));
            if (np > 0) button(rr, getString(R.string.s0653), v -> bkDelete(el));
        }
    }

    private void bkDelete(LinearLayout el) {
        dangerConfirm(getString(R.string.s0654), getString(R.string.s0655), getString(R.string.s0057),
                () -> Api.del(this, "/accounts/" + id + "/oci/billing-keep?confirm=true", x -> { toast(getString(R.string.s0223)); if (bkAlive(el)) billingKeep(el, false, true); }));
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
                if (size > 100L * 1024 * 1024) { sb.append(name).append(getString(R.string.s0656)); continue; }
                byte[] data;
                try (java.io.InputStream in = getContentResolver().openInputStream(u); java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream()) {
                    byte[] buf = new byte[65536];
                    int n;
                    while ((n = in.read(buf)) > 0) { bo.write(buf, 0, n); if (bo.size() > 100 * 1024 * 1024) break; }
                    data = bo.toByteArray();
                }
                if (data.length > 100 * 1024 * 1024) { sb.append(name).append(getString(R.string.s0656)); continue; }
                try {
                    Api.putBytes("/accounts/" + id + "/oci/objects?bucket=" + Api.enc(bucket) + "&name=" + Api.enc(prefix + name) + "&" + rq(), data);
                    sb.append(name).append(getString(R.string.s0657));
                } catch (Exception e) { sb.append(name).append("：").append(e.getMessage()).append("\n"); }
            }
            return sb.toString().trim();
        }, r -> { info(getString(R.string.s0658), String.valueOf(r)); refresh(); });
    }

    // ---------- 配额 / 网络 ----------
    private void ociLimits() {
        LinearLayout nc = card(getString(R.string.s0156));
        muted(nc, getString(R.string.s0659));
        button(row(nc), getString(R.string.s0660), v -> confirm(getString(R.string.s0660), getString(R.string.s0661), () -> {
            try { Api.post(this, "/accounts/" + id + "/oci/network", rb(), x -> taskOrToast(x, getString(R.string.s0037))); } catch (Exception ignored) { }
        }));
        LinearLayout c = card(getString(R.string.s0662, Regions.label(region())));
        android.widget.TextView cLoading = muted(c, getString(R.string.s0590));
        ociRegionSubSection();   // 页面最底部：默认折叠的「高级 · 区域订阅」
        Api.get(this, "/accounts/" + id + "/oci/limits?" + rq(), r -> {
            JSONObject d = Api.obj(r);
            JSONArray items = d.optJSONArray("items");
            c.removeView(cLoading);
            ((android.widget.TextView) c.getChildAt(0)).setText(getString(R.string.s0662, Regions.label(d.optString("region"))));
            if (items == null || items.length() == 0) muted(c, getString(R.string.s0663));
            for (int i = 0; items != null && i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i);
                String free = it.isNull("free") || !it.has("free") ? "-" : str(it, "free_left", "?") + " / " + it.optString("free");
                text(c, it.optString("name"), 14, true);
                muted(c, getString(R.string.s0664, it.optString("limit"), str(it, "used", "-"), str(it, "available", "-"), free));
            }
            String basis = d.optString("a1_basis");
            muted(c, getString(R.string.s0668, ("paid".equals(basis) ? getString(R.string.s0665) : "free".equals(basis) ? getString(R.string.s0666) : getString(R.string.s0667))));
        });
    }

    static final String REGION_SUB_TITLE = "高级 · 区域订阅（不可撤销）";

    /** v1.6 build 18：区域订阅不再单独占标签，收在「配额/网络」页底部，默认折叠，展开才加载。 */
    private void ociRegionSubSection() {
        LinearLayout adv = card(REGION_SUB_TITLE);
        muted(adv, getString(R.string.s0669));
        LinearLayout list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        list.setVisibility(android.view.View.GONE);
        boolean[] loaded = {false};
        android.widget.Button tg = button(row(adv), getString(R.string.s0670), null);
        adv.addView(list);
        tg.setOnClickListener(v -> {
            boolean show = list.getVisibility() != android.view.View.VISIBLE;
            list.setVisibility(show ? android.view.View.VISIBLE : android.view.View.GONE);
            tg.setText(show ? getString(R.string.s0671) : getString(R.string.s0670));
            if (show && !loaded[0]) { loaded[0] = true; ociRegionSub(list); }
        });
    }

    private void ociRegionSub(LinearLayout box) {
        box.removeAllViews();
        muted(box, getString(R.string.s0590));
        Api.get(this, "/accounts/" + id + "/oci/region-subscriptions", r -> {
            box.removeAllViews();
            JSONObject d = Api.obj(r);
            JSONArray rs = d.optJSONArray("regions");
            int sub = 0;
            for (int i = 0; rs != null && i < rs.length(); i++) if (rs.optJSONObject(i).optBoolean("subscribed")) sub++;
            text(box, getString(R.string.s0672, sub, Regions.label(str(d, "home", "-"))), 14, true);
            muted(box, getString(R.string.s0673, str(d, "limit_hint", "")));
            for (int i = 0; rs != null && i < rs.length(); i++) {
                JSONObject x = rs.optJSONObject(i);
                boolean s = x.optBoolean("subscribed");
                text(box, Regions.label(x.optString("name")) + (x.optBoolean("home") ? getString(R.string.s0674) : ""), 14, true);
                muted(box, x.optString("key") + " · " + (s ? str(x, "status", getString(R.string.s0675)) : getString(R.string.s0676)));
                if (!s) button(row(box), getString(R.string.s0017), v -> confirm(getString(R.string.s0677), getString(R.string.s0678, x.optString("name"), x.optString("key")),
                        () -> typeKeyConfirm(x.optString("name"), x.optString("key"), () -> {
                    try {
                        Api.post(this, "/accounts/" + id + "/oci/region-subscriptions", new JSONObject().put("region_key", x.optString("key")).put("confirm", true), y -> {
                            JSONObject o = Api.obj(y);
                            toast(getString(R.string.s0679, o.optString("region"), o.optString("status")));
                            ociRegionSub(box);
                        });
                    } catch (Exception ignored) { }
                })));
            }
        });
    }

    /** 二次确认：手动输入完整区域标识（如 ap-osaka-1）一致后「确认订阅」才可点。 */
    private void typeKeyConfirm(String name, String key, Runnable ok) {
        com.google.android.material.textfield.TextInputLayout til = inputLayout(getString(R.string.s0680), name, android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        LinearLayout wrap = new LinearLayout(this);
        wrap.setOrientation(LinearLayout.VERTICAL);
        wrap.setPadding(dp(24), dp(8), dp(24), 0);
        wrap.addView(til);
        androidx.appcompat.app.AlertDialog dlg = new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s0681))
                .setMessage(getString(R.string.s0682, name, key, name))
                .setView(wrap).setPositiveButton(getString(R.string.s0683), (d, w) -> ok.run()).setNegativeButton(getString(R.string.s0614), null).show();
        android.widget.Button pos = dlg.getButton(android.content.DialogInterface.BUTTON_POSITIVE);
        pos.setEnabled(false);
        android.widget.EditText et = til.getEditText();
        if (et != null) et.addTextChangedListener(new android.text.TextWatcher() {
            @Override public void beforeTextChanged(CharSequence c, int a, int b, int n) { }
            @Override public void onTextChanged(CharSequence c, int a, int b, int n) { }
            @Override public void afterTextChanged(android.text.Editable e) { pos.setEnabled(name.equals(e.toString().trim())); }
        });
    }

    // ======================= AWS 区域 =======================
    private void awsRegions(boolean rescan) {
        LinearLayout st = card(getString(R.string.s0684));
        android.widget.TextView stT = muted(st, getString(R.string.s0685));
        LinearLayout sc = card(getString(R.string.s0686));
        android.widget.TextView scT = muted(sc, getString(R.string.s0687));
        Api.job(this, () -> {
            try { return Api.call("GET", "/accounts/" + id + "/aws/regions-status", null); } catch (Exception e) { return new JSONObject().put("error", e.getMessage()); }
        }, r -> {
            if (r instanceof JSONObject) { stT.setText(getString(R.string.s0688, ((JSONObject) r).optString("error"))); return; }
            JSONArray rs = Api.arr(r);
            stT.setText(getString(R.string.s0689));
            StringBuilder sb = new StringBuilder();
            LinearLayout rr = row(st);
            for (int i = 0; i < rs.length(); i++) {
                JSONObject x = rs.optJSONObject(i);
                String status = x.optString("status");
                boolean on = "ENABLED_BY_DEFAULT".equals(status) || "ENABLED".equals(status);
                sb.append(on ? "✅ " : "DISABLED".equals(status) ? "⛔ " : "⏳ ").append(Regions.label(x.optString("region"))).append("  ").append(status).append("\n");
                if ("DISABLED".equals(status)) button(rr, getString(R.string.s0690, x.optString("region")), v -> {
                    try { Api.post(this, "/accounts/" + id + "/aws/enable-region", new JSONObject().put("region", x.optString("region")), y -> { toast(str(Api.obj(y), "hint", getString(R.string.s0037))); refresh(); }); }
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
            scT.setText(getString(R.string.s0691, d.optString("updated_at")));
            JSONArray rs = d.optJSONArray("regions");
            LinearLayout rr = row(sc);
            button(rr, getString(R.string.s0692), v -> { header(); awsRegions(true); });
            int n = 0;
            for (int i = 0; rs != null && i < rs.length(); i++) {
                JSONObject x = rs.optJSONObject(i);
                if (x.optInt("ec2") == 0 && x.optInt("lightsail") == 0) continue;
                n++;
                String reg = x.optString("region");
                text(sc, getString(R.string.s0693, Regions.label(reg), x.optInt("ec2"), x.optInt("ec2_running"), str(x, "lightsail", "-")), 13, false);
                button(row(sc), getString(R.string.s0694, reg), v -> { Api.setPref("region_" + id, reg); selectTab("ec2"); });
            }
            if (n == 0) muted(sc, getString(R.string.s0695));
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
        LinearLayout c = card(getString(R.string.s0150));
        muted(c, getString(R.string.s0696));
        button(row(c), getString(R.string.s0179), v -> azureCreate());
    }

    private void azRgs() {
        bigButton(getString(R.string.s0697), v -> withLocs(l -> form(getString(R.string.s0698), null, Arrays.asList(Field.text("name", getString(R.string.s0135), ""),
                regionSel("location", getString(R.string.s0010), Api.pref("azloc_" + id, "eastasia"), Api.arr(l))), getString(R.string.s0142),
                f -> Api.post(this, "/accounts/" + id + "/azure/rgs", f, x -> { toast(getString(R.string.s0569)); refresh(); }))));
        Api.get(this, "/accounts/" + id + "/azure/rgs", r -> {
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card(getString(R.string.s0699)), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject g = a.optJSONObject(i);
                String nm = g.optString("name");
                LinearLayout c = card(nm);
                muted(c, g.optString("location") + " · " + g.optString("state"));
                button(row(c), getString(R.string.s0057), v -> form(getString(R.string.s0700), getString(R.string.s0701, nm),
                        Arrays.asList(Field.text("confirm", getString(R.string.s0702), "")), getString(R.string.s0057), f -> {
                    if (!nm.equals(f.optString("confirm"))) { toast(getString(R.string.s0703)); return; }
                    try { Api.post(this, "/accounts/" + id + "/azure/rgs", f.put("op", "delete").put("name", nm), x -> { toast(getString(R.string.s0704)); body.postDelayed(this::refresh, 3000); }); }
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
            button(top, getString(R.string.s0022, cur), v -> {
                String[] ls = new String[locs.length()];
                for (int i = 0; i < ls.length; i++) ls[i] = locs.optString(i);
                choose(getString(R.string.s0705), ls, i -> { Api.setPref("azloc_" + id, ls[i]); refresh(); });
            });
            Api.get(this, "/accounts/" + id + "/azure/quotas?location=" + Api.enc(cur), r -> {
                JSONArray items = Api.obj(r).optJSONArray("items");
                LinearLayout c = card(getString(R.string.s0706, cur));
                StringBuilder sb = new StringBuilder();
                for (int i = 0; items != null && i < items.length(); i++) {
                    JSONObject it = items.optJSONObject(i);
                    sb.append(it.optString("name")).append("：").append(it.optString("used")).append(" / ").append(it.optString("limit")).append("\n");
                }
                text(c, sb.length() == 0 ? getString(R.string.s0663) : sb.toString().trim(), 13, false);
            });
        });
    }
}
