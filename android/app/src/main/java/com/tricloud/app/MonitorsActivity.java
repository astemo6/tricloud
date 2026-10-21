package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** 监控（同 Web pageMonitors）：今日换 IP 次数、监控列表（连通检测 / 自动换 IP）与移除；在实例卡片上点「监控」添加。 */
public class MonitorsActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s0053)); refresh(); }

    @Override
    protected String navKey() { return "monitors"; }

    @Override
    protected void refresh() {
        Api.get(this, "/monitors", r -> Api.job(this, () -> {
            try { return Api.call("GET", "/ip-change-usage", null); } catch (Exception e) { return new JSONArray(); }
        }, u -> render(Api.arr(r), Api.arr(u))));
    }

    private void render(JSONArray a, JSONArray usage) {
        clear();
        StringBuilder us = new StringBuilder();
        int limit = 0;
        for (int i = 0; i < usage.length(); i++) {
            JSONObject u = usage.optJSONObject(i);
            boolean watched = false;
            for (int j = 0; j < a.length(); j++) if (a.optJSONObject(j).optInt("account_id") == u.optInt("account_id") && a.optJSONObject(j).optInt("auto_change_ip") == 1) watched = true;
            if (u.optInt("auto_used") == 0 && u.optInt("manual_used") == 0 && !watched) continue;
            limit = u.optInt("limit");
            us.append(u.optString("name")).append(getString(R.string.s0970)).append(u.optInt("auto_used")).append("/").append(u.optInt("limit")).append(getString(R.string.s0971)).append(u.optInt("manual_used")).append("\n");
        }
        if (us.length() > 0) {
            LinearLayout uc = card(getString(R.string.s0972));
            text(uc, us.toString().trim(), 13, false);
            muted(uc, getString(R.string.s0973, limit));
        }
        muted(card(getString(R.string.s0338)), getString(R.string.s0974));
        if (a.length() == 0) muted(card(getString(R.string.s0975)), "");
        for (int i = 0; i < a.length(); i++) {
            JSONObject m = a.optJSONObject(i);
            LinearLayout c = card(str(m, "name", "-"));
            int port = m.optInt("check_port");
            text(c, getString(R.string.s0980, str(m, "account_name", "-"), str(m, "last_state", "-"), (m.optInt("auto_start") == 1 ? getString(R.string.s0976) : getString(R.string.s0977)), (port > 0 ? str(m, "public_ip", "-") + ":" + port + (m.optInt("auto_change_ip") == 1 ? getString(R.string.s0978) : "")
                    + (m.optInt("fail_count") > 0 ? getString(R.string.s0979, m.optInt("fail_count")) : "") : "—")), 13, false);
            int mid = m.optInt("id");
            button(row(c), getString(R.string.s0981), v -> confirm(getString(R.string.s0982), getString(R.string.s0983), () -> Api.del(this, "/monitors/" + mid, x -> { toast(getString(R.string.s0984)); refresh(); })));
        }
    }
}
