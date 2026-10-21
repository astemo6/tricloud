package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** build 22 流量守护 agent 与端口流量明细（同 Web guardAgentDialog / guardPortsDialog）：
 *  agent 在线状态与最后心跳、当前是否限速、可复制的安装 / 卸载命令、重置 token、流量明细开关；
 *  今日 / 本月按端口和按服务的 Top（入站、出站、合计 + 占比条）。面板不会远程执行任何命令。 */
public class GuardAgentActivity extends BaseActivity {
    private int gid;
    private String name;
    private String range = "today";
    private boolean byService = false;

    @Override
    protected boolean useDrawer() { return false; }

    @Override
    protected void onCreate(Bundle s) {
        super.onCreate(s);
        gid = getIntent().getIntExtra("gid", 0);
        name = getIntent().getStringExtra("name");
        setTitle(getString(R.string.s0840, (name == null ? "#" + gid : name)));
        refresh();
    }

    private String base() { return Api.enc(Api.server()); }

    @Override
    protected void refresh() {
        Api.get(this, "/traffic-guards/" + gid + "/agent?base=" + base(), r -> {
            clear();
            JSONObject d = Api.obj(r);
            renderAgent(d);
            loadPorts();
        });
    }

    static String agentLine(JSONObject a, boolean throttleAction, boolean throttled) {
        if (a == null) return "";
        String st = !a.optBoolean("installed") ? L10n.s(R.string.s0881) : a.optBoolean("online") ? L10n.s(R.string.s0882) : L10n.s(R.string.s0883);
        String seen = a.isNull("last_seen_text") ? "" : L10n.s(R.string.s0884, a.optString("last_seen_text"));
        String thr = !throttleAction ? "" : a.optBoolean("applied") ? L10n.s(R.string.s0885) : throttled ? L10n.s(R.string.s0886) : L10n.s(R.string.s0887);
        return st + seen + thr;
    }

    private void renderAgent(JSONObject d) {
        JSONObject a = d.optJSONObject("agent") != null ? d.optJSONObject("agent") : new JSONObject();
        boolean throttled = d.optBoolean("throttled");
        LinearLayout c = card(getString(R.string.s0888));
        StringBuilder sb = new StringBuilder(agentLine(a, true, throttled));
        sb.append(getString(R.string.s0889)).append(str(d, "throttle_mbps", "1")).append(getString(R.string.s0890));
        sb.append(getString(R.string.s0891)).append(throttled ? getString(R.string.s0892) : getString(R.string.s0893)).append(a.optBoolean("applied") ? getString(R.string.s0894) : "");
        if (!a.isNull("iface") && a.has("iface")) sb.append(getString(R.string.s0895)).append(a.optString("iface"));
        if (!a.isNull("ssh_ports") && a.has("ssh_ports")) sb.append(getString(R.string.s0896)).append(a.optString("ssh_ports"));
        String be = a.isNull("acct_backend_text") || !a.has("acct_backend_text") ? getString(R.string.s0897) : a.optString("acct_backend_text")
                + (a.isNull("acct_ports") || !a.has("acct_ports") ? "" : getString(R.string.s0898, a.optInt("acct_ports")));
        sb.append(getString(R.string.s0899)).append(a.optBoolean("acct_enabled") ? getString(R.string.s0900, be) : getString(R.string.s0901));
        text(c, sb.toString(), 14, false);
        boolean acct = a.optBoolean("acct_enabled");
        LinearLayout cr = row(c);
        button(cr, acct ? getString(R.string.s0902) : getString(R.string.s0903), v -> {
            try {
                Api.async(this, "PATCH", "/traffic-guards/" + gid, new JSONObject().put("acct_enabled", !acct), x -> {
                    toast(!acct ? getString(R.string.s0904) : getString(R.string.s0905));
                    refresh();
                });
            } catch (Exception ignored) { }
        });
        muted(c, getString(R.string.s0906));

        JSONObject cm = d.optJSONObject("commands");
        LinearLayout k = card(getString(R.string.s0907));
        if (cm == null) { muted(k, getString(R.string.s0908)); return; }
        muted(k, getString(R.string.s0909, (d.optInt("poll_secs", 300) / 60), (d.optInt("offline_secs", 900) / 60)));
        String[][] items = {{getString(R.string.s0910), "install"}, {getString(R.string.s0911), "uninstall"}, {getString(R.string.s0912), "uninstall_local"}, {getString(R.string.s0913), "status"}};
        for (String[] it : items) {
            String v = cm.optString(it[1]);
            text(k, it[0] + "：\n" + v, 12, false).setTextIsSelectable(true);
            button(row(k), getString(R.string.s0914, it[0]), x -> copy(it[1], v));
        }
        muted(k, getString(R.string.s0915));
        button(row(k), getString(R.string.s0916), v -> dangerConfirm(getString(R.string.s0917),
                getString(R.string.s0918),
                () -> Api.post(this, "/traffic-guards/" + gid + "/agent/reset?base=" + base(), new JSONObject(), x -> { toast(getString(R.string.s0919)); refresh(); })));
    }

    private void dangerConfirm(String title, String msg, Runnable ok) {
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(title).setMessage(msg)
                .setNegativeButton(getString(R.string.s0614), null).setPositiveButton(getString(R.string.s0920), (d, w) -> ok.run()).show();
    }

    private void loadPorts() {
        LinearLayout p = card(getString(R.string.s0921));
        LinearLayout sw = row(p);
        button(sw, getString(R.string.s0922, ("today".equals(range) ? "● " : "")), v -> { range = "today"; refresh(); });
        button(sw, getString(R.string.s0923, ("month".equals(range) ? "● " : "")), v -> { range = "month"; refresh(); });
        button(sw, byService ? getString(R.string.s0924) : getString(R.string.s0372), v -> { byService = !byService; refresh(); });
        muted(p, getString(R.string.s0527));
        Api.get(this, "/traffic-guards/" + gid + "/ports?range=" + range + "&limit=20", r -> {
            p.removeViews(2, p.getChildCount() - 2);
            JSONObject t = Api.obj(r);
            JSONObject a = t.optJSONObject("agent") != null ? t.optJSONObject("agent") : new JSONObject();
            String span = t.optString("start").equals(t.optString("end")) ? t.optString("start") : t.optString("start") + " ~ " + t.optString("end");
            text(p, getString(R.string.s0925, t.optString("title"), span, t.optString("total_text"), t.optString("in_text"), t.optString("out_text")), 14, true);
            if (!t.optBoolean("acct_enabled")) muted(p, getString(R.string.s0926));
            else if (!a.optBoolean("installed")) muted(p, getString(R.string.s0927));
            JSONArray rows = byService ? t.optJSONArray("services") : t.optJSONArray("ports");
            if (rows == null || rows.length() == 0) { muted(p, getString(R.string.s0928, t.optString("title"))); return; }
            for (int i = 0; i < rows.length(); i++) {
                JSONObject x = rows.optJSONObject(i);
                String label = byService ? x.optString("service") : x.optString("label");
                String ports = byService && x.optJSONArray("ports") != null && x.optJSONArray("ports").length() > 0 ? "\n" + join(x.optJSONArray("ports")) : "";
                text(p, getString(R.string.s0929, (i + 1), label, x.optString("total_text"), x.optDouble("pct"), ports, x.optString("in_text"), x.optString("out_text")), 13, false);
                bar(p, x.optDouble("pct"));
            }
            muted(p, getString(R.string.s0930, t.optInt("retain_days", 90)));
        });
    }

    /** Material 3 线性进度条当占比条。 */
    private void bar(LinearLayout p, double pct) {
        com.google.android.material.progressindicator.LinearProgressIndicator b = new com.google.android.material.progressindicator.LinearProgressIndicator(this);
        b.setMax(1000);
        b.setProgressCompat((int) Math.round(Math.min(100, Math.max(0, pct)) * 10), false);
        b.setTrackCornerRadius(dp(3));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(2), 0, dp(8));
        p.addView(b, lp);
    }
}
