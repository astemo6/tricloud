package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** 流量守护规则：在实例卡片上点「流量守护」添加。 */
public class TrafficActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("流量守护"); refresh(); }

    @Override
    protected String navKey() { return "traffic"; }

    @Override
    protected void refresh() {
        Api.get(this, "/traffic-guards", r -> {
            clear();
            muted(card("说明"), "本月累计或滚动窗口（最近 N 小时，出站 / 入站 / 双向）。到预警比例推送，到上限推送并可自动停机，可在 M 小时后自动开机（失败只告警、不重试）。在实例卡片上点「流量守护」添加（OCI 在账号的「流量」标签里设置）。也可以给 Telegram Bot 发 /traffic 查看。");
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card("还没有规则"), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject g = a.optJSONObject(i);
                LinearLayout c = card(str(g, "name", "-"));
                boolean stop = "stop".equals(g.optString("action"));
                double sh = g.optDouble("shutdown_hours", 0);
                text(c, str(g, "account_name", "-") + "\n" + str(g, "scope", "本月出站") + "：" + str(g, "last_gb", "-") + " / " + str(g, "limit_gb", "-") + " GB（" + str(g, "last_pct", "-") + "%）"
                        + "\n到上限：" + (!stop ? "只推送" : sh > 0 ? "停机 " + (sh == Math.floor(sh) ? String.valueOf((long) sh) : String.valueOf(sh)) + " 小时后自动开机" : "自动停机")
                        + "\n状态：" + str(g, "status_text", "正常") + (g.isNull("resume_at_text") || !g.has("resume_at_text") ? "" : "，预计 " + g.optString("resume_at_text") + " 开机")
                        + (g.optInt("enabled", 1) == 1 ? "" : "（已停用）") + "\n检查于 " + fmtTime(g.optLong("checked_at")), 13, false);
                if (!g.isNull("state_msg") && g.has("state_msg") && !"ok".equals(g.optString("status"))) muted(c, g.optString("state_msg"));
                LinearLayout row = row(c);
                int gid = g.optInt("id");
                boolean en = g.optInt("enabled", 1) == 1;
                button(row, en ? "停用" : "启用", v -> patch(gid, "enabled", !en));
                if (g.has("resume_at") && !g.isNull("resume_at")) button(row, "取消自动开机", v -> patch(gid, "cancel_resume", true));
                if ("tripped".equals(g.optString("status")) || "resume_failed".equals(g.optString("status"))) button(row, "清除状态", v -> patch(gid, "reset_state", true));
                button(row, "编辑", v -> trafficDialog(g.optInt("account_id"), g.optString("provider"), str(g, "region", ""), g.optString("instance_id"),
                        str(g, "name", g.optString("instance_id")), str(g, "kind", "vm"), this::refresh));
                button(row, "立即检查", v -> Api.post(this, "/traffic-guards/" + gid + "/check", null, x -> { toast("已检查"); refresh(); }));
                button(row, "删除", v -> confirm("删除规则", "删除这条流量守护？", () -> Api.del(this, "/traffic-guards/" + gid, x -> refresh())));
            }
        });
    }

    private void patch(int gid, String k, boolean v) {
        try { Api.async(this, "PATCH", "/traffic-guards/" + gid, new JSONObject().put(k, v), x -> refresh()); } catch (Exception ignored) { }
    }
}
