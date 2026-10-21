package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** 流量守护规则：在实例卡片上点「流量守护」添加。 */
public class TrafficActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s0050)); refresh(); }

    @Override
    protected String navKey() { return "traffic"; }

    @Override
    protected void refresh() {
        Api.get(this, "/traffic-guards", r -> {
            clear();
            muted(card(getString(R.string.s0338)), getString(R.string.s1226));
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card(getString(R.string.s1227)), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject g = a.optJSONObject(i);
                LinearLayout c = card(str(g, "name", "-"));
                boolean stop = "stop".equals(g.optString("action"));
                boolean thr = "throttle".equals(g.optString("action"));
                double sh = g.optDouble("shutdown_hours", 0);
                text(c, getString(R.string.s1233, str(g, "account_name", "-"), str(g, "scope", getString(R.string.s1228)), str(g, "last_gb", "-"), str(g, "limit_gb", "-"), str(g, "last_pct", "-"), (thr ? getString(R.string.s1229, str(g, "throttle_mbps", "1")) : !stop ? getString(R.string.s0833) : sh > 0 ? getString(R.string.s1230, (sh == Math.floor(sh) ? String.valueOf((long) sh) : String.valueOf(sh))) : getString(R.string.s1231)), str(g, "status_text", getString(R.string.s0291)), (g.isNull("resume_at_text") || !g.has("resume_at_text") ? "" : getString(R.string.s1232, g.optString("resume_at_text"))), (g.optInt("enabled", 1) == 1 ? "" : getString(R.string.s0819)), fmtTime(g.optLong("checked_at"))), 13, false);
                if (!g.isNull("state_msg") && g.has("state_msg") && !"ok".equals(g.optString("status"))) muted(c, g.optString("state_msg"));
                if (g.optJSONObject("agent") != null) muted(c, GuardAgentActivity.agentLine(g.optJSONObject("agent"), thr, g.optInt("throttled") == 1)
                        + (g.optInt("acct_enabled") == 1 ? getString(R.string.s1234) : ""));
                LinearLayout row = row(c);
                int gid = g.optInt("id");
                boolean en = g.optInt("enabled", 1) == 1;
                button(row, en ? getString(R.string.s0212) : getString(R.string.s0213), v -> patch(gid, "enabled", !en));
                if (g.has("resume_at") && !g.isNull("resume_at")) button(row, getString(R.string.s1235), v -> patch(gid, "cancel_resume", true));
                if ("tripped".equals(g.optString("status")) || "resume_failed".equals(g.optString("status"))) button(row, getString(R.string.s1236), v -> patch(gid, "reset_state", true));
                button(row, getString(R.string.s0211), v -> trafficDialog(g.optInt("account_id"), g.optString("provider"), str(g, "region", ""), g.optString("instance_id"),
                        str(g, "name", g.optString("instance_id")), str(g, "kind", "vm"), this::refresh));
                button(row, getString(R.string.s0300), v -> Api.post(this, "/traffic-guards/" + gid + "/check", null, x -> { toast(getString(R.string.s0301)); refresh(); }));
                button(row, getString(R.string.s0299), v -> startActivity(new android.content.Intent(this, GuardAgentActivity.class).putExtra("gid", gid).putExtra("name", str(g, "name", ""))));
                if (g.optInt("throttled") == 1) button(row, getString(R.string.s1237), v -> confirm(getString(R.string.s1237), getString(R.string.s1238), () -> patch(gid, "release_throttle", true)));
                button(row, getString(R.string.s0057), v -> confirm(getString(R.string.s0263), getString(R.string.s1239), () -> Api.del(this, "/traffic-guards/" + gid, x -> refresh())));
            }
        });
    }

    private void patch(int gid, String k, boolean v) {
        try { Api.async(this, "PATCH", "/traffic-guards/" + gid, new JSONObject().put(k, v), x -> refresh()); } catch (Exception ignored) { }
    }
}
