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
        setTitle("流量守护 · " + (name == null ? "#" + gid : name));
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
        String st = !a.optBoolean("installed") ? "⚪ agent 未安装" : a.optBoolean("online") ? "🟢 agent 在线" : "🔴 agent 离线";
        String seen = a.isNull("last_seen_text") ? "" : "，最后心跳 " + a.optString("last_seen_text");
        String thr = !throttleAction ? "" : a.optBoolean("applied") ? " · 🐢 当前已限速" : throttled ? " · 应限速（等 agent 生效）" : " · 当前未限速";
        return st + seen + thr;
    }

    private void renderAgent(JSONObject d) {
        JSONObject a = d.optJSONObject("agent") != null ? d.optJSONObject("agent") : new JSONObject();
        boolean throttled = d.optBoolean("throttled");
        LinearLayout c = card("agent 状态");
        StringBuilder sb = new StringBuilder(agentLine(a, true, throttled));
        sb.append("\n超限后出站限速：").append(str(d, "throttle_mbps", "1")).append(" Mbps（SSH 端口不限，仅「推送并限速」规则生效）");
        sb.append("\n当前：").append(throttled ? "已触发限速" : "未触发限速").append(a.optBoolean("applied") ? "（agent 已生效）" : "");
        if (!a.isNull("iface") && a.has("iface")) sb.append("\n网卡：").append(a.optString("iface"));
        if (!a.isNull("ssh_ports") && a.has("ssh_ports")) sb.append("  SSH 端口：").append(a.optString("ssh_ports"));
        String be = a.isNull("acct_backend_text") || !a.has("acct_backend_text") ? "等待 agent 上报" : a.optString("acct_backend_text")
                + (a.isNull("acct_ports") || !a.has("acct_ports") ? "" : "，" + a.optInt("acct_ports") + " 个端口");
        sb.append("\n流量明细：").append(a.optBoolean("acct_enabled") ? "已开启（" + be + "）" : "未开启");
        text(c, sb.toString(), 14, false);
        boolean acct = a.optBoolean("acct_enabled");
        LinearLayout cr = row(c);
        button(cr, acct ? "关闭流量明细" : "开启流量明细", v -> {
            try {
                Api.async(this, "PATCH", "/traffic-guards/" + gid, new JSONObject().put("acct_enabled", !acct), x -> {
                    toast(!acct ? "已开启流量明细，agent 下次心跳（≤5 分钟）建立计数规则" : "已关闭流量明细，agent 下次心跳删除计数规则");
                    refresh();
                });
            } catch (Exception ignored) { }
        });
        muted(c, "流量明细：按端口 / 服务统计入站、出站（nftables 独立 table，只计数不拦截；没有 nft 时用 iptables 计数链）。");

        JSONObject cm = d.optJSONObject("commands");
        LinearLayout k = card("安装 / 卸载命令");
        if (cm == null) { muted(k, "API Token 只能查看状态，不显示安装命令。"); return; }
        muted(k, "在这台实例上用 root 运行（面板不会远程执行任何命令）。agent 是 bash 脚本 + systemd timer，每 "
                + (d.optInt("poll_secs", 300) / 60) + " 分钟用这条守护的专属 token 拉取状态并上报流量明细；超过 "
                + (d.optInt("offline_secs", 900) / 60) + " 分钟没心跳算离线。");
        String[][] items = {{"安装命令", "install"}, {"卸载命令（面板）", "uninstall"}, {"卸载命令（本机）", "uninstall_local"}, {"查看状态", "status"}};
        for (String[] it : items) {
            String v = cm.optString(it[1]);
            text(k, it[0] + "：\n" + v, 12, false).setTextIsSelectable(true);
            button(row(k), "复制" + it[0], x -> copy(it[1], v));
        }
        muted(k, "安装命令里含这条守护的 token，只能读写这条守护的状态和流量明细；泄露了点「重置 token」，旧 agent 会自动解除限速并删除计数规则。");
        button(row(k), "重置 token", v -> dangerConfirm("重置 agent token",
                "重置后旧的安装命令立即失效，实例上的旧 agent 会解除限速并删除计数规则，需要在实例上重新运行新的安装命令。确定重置？",
                () -> Api.post(this, "/traffic-guards/" + gid + "/agent/reset?base=" + base(), new JSONObject(), x -> { toast("已重置，请重新安装"); refresh(); })));
    }

    private void dangerConfirm(String title, String msg, Runnable ok) {
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(this).setTitle(title).setMessage(msg)
                .setNegativeButton("取消", null).setPositiveButton("重置", (d, w) -> ok.run()).show();
    }

    private void loadPorts() {
        LinearLayout p = card("端口流量明细");
        LinearLayout sw = row(p);
        button(sw, ("today".equals(range) ? "● " : "") + "今日", v -> { range = "today"; refresh(); });
        button(sw, ("month".equals(range) ? "● " : "") + "本月", v -> { range = "month"; refresh(); });
        button(sw, byService ? "按端口" : "按服务", v -> { byService = !byService; refresh(); });
        muted(p, "读取中…");
        Api.get(this, "/traffic-guards/" + gid + "/ports?range=" + range + "&limit=20", r -> {
            p.removeViews(2, p.getChildCount() - 2);
            JSONObject t = Api.obj(r);
            JSONObject a = t.optJSONObject("agent") != null ? t.optJSONObject("agent") : new JSONObject();
            String span = t.optString("start").equals(t.optString("end")) ? t.optString("start") : t.optString("start") + " ~ " + t.optString("end");
            text(p, t.optString("title") + "（" + span + "）合计 " + t.optString("total_text") + "：入站 " + t.optString("in_text") + " / 出站 " + t.optString("out_text"), 14, true);
            if (!t.optBoolean("acct_enabled")) muted(p, "流量明细未开启：点上面「开启流量明细」并在实例上安装 agent。");
            else if (!a.optBoolean("installed")) muted(p, "agent 尚未安装 / 尚未上报。");
            JSONArray rows = byService ? t.optJSONArray("services") : t.optJSONArray("ports");
            if (rows == null || rows.length() == 0) { muted(p, t.optString("title") + "还没有数据"); return; }
            for (int i = 0; i < rows.length(); i++) {
                JSONObject x = rows.optJSONObject(i);
                String label = byService ? x.optString("service") : x.optString("label");
                String ports = byService && x.optJSONArray("ports") != null && x.optJSONArray("ports").length() > 0 ? "\n" + join(x.optJSONArray("ports")) : "";
                text(p, (i + 1) + ". " + label + "：" + x.optString("total_text") + "（" + x.optDouble("pct") + "%）" + ports
                        + "\n入 " + x.optString("in_text") + " · 出 " + x.optString("out_text"), 13, false);
                bar(p, x.optDouble("pct"));
            }
            muted(p, "非监听端口的流量（比如本机主动访问外网、代理的出站连接）归为「其他/出站连接」。agent 每 5 分钟上报，按天保存 " + t.optInt("retain_days", 90) + " 天。");
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
