package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** 监控（同 Web pageMonitors）：今日换 IP 次数、监控列表（连通检测 / 自动换 IP）与移除；在实例卡片上点「监控」添加。 */
public class MonitorsActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("监控"); refresh(); }

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
            us.append(u.optString("name")).append(" · 自动 ").append(u.optInt("auto_used")).append("/").append(u.optInt("limit")).append(" · 手动 ").append(u.optInt("manual_used")).append("\n");
        }
        if (us.length() > 0) {
            LinearLayout uc = card("今日换 IP 次数");
            text(uc, us.toString().trim(), 13, false);
            muted(uc, "自动换 IP 每账号每天最多 " + limit + " 次（设置里修改），达到上限或失败时只推送 Telegram 告警。");
        }
        muted(card("说明"), "在实例卡片上点「监控」添加。检测间隔见设置页。非面板操作导致的停止 / 终止会推送告警，可选自动启动；可选端口连通检测，连续 3 次不通自动换 IP。");
        if (a.length() == 0) muted(card("暂无监控"), "");
        for (int i = 0; i < a.length(); i++) {
            JSONObject m = a.optJSONObject(i);
            LinearLayout c = card(str(m, "name", "-"));
            int port = m.optInt("check_port");
            text(c, str(m, "account_name", "-") + "\n上次状态：" + str(m, "last_state", "-") + "\n自动启动：" + (m.optInt("auto_start") == 1 ? "是" : "否")
                    + "\n连通检测：" + (port > 0 ? str(m, "public_ip", "-") + ":" + port + (m.optInt("auto_change_ip") == 1 ? " · 不通自动换 IP" : "")
                    + (m.optInt("fail_count") > 0 ? " · 失败 " + m.optInt("fail_count") : "") : "—"), 13, false);
            int mid = m.optInt("id");
            button(row(c), "移除", v -> confirm("移除监控", "确定移除这台实例的监控？", () -> Api.del(this, "/monitors/" + mid, x -> { toast("已移除"); refresh(); })));
        }
    }
}
