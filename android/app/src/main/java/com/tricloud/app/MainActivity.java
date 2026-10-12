package com.tricloud.app;

import android.content.Intent;
import android.os.Bundle;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Arrays;

/** 总览（同 Web pageHome）：到期提醒、账号健康度、各账号实例数，抽屉导航到各账号与管理页。 */
public class MainActivity extends BaseActivity {
    static final String[] PROVS = {"oci", "aws", "azure"};
    static final String[] PNAMES = {"Oracle Cloud", "AWS", "Azure"};
    private boolean first = true;

    @Override
    protected void onCreate(Bundle s) {
        super.onCreate(s);
        setTitle("总览");
        refresh();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (!first) refresh();
        first = false;
    }

    @Override
    protected String navKey() { return "home"; }

    static String pname(String p) {
        int i = Arrays.asList(PROVS).indexOf(p);
        return i >= 0 ? PNAMES[i] : p;
    }

    static String regionOf(JSONObject a) { return Api.pref("region_" + a.optInt("id"), str(a, "region", "")); }

    @Override
    protected void refresh() {
        Api.get(this, "/accounts", r -> {
            clear();
            JSONArray a = Api.arr(r);
            Api.accounts = a;
            buildNav();
            if (a.length() == 0) {
                muted(card("还没有云账号"), "添加 OCI / AWS / Azure 账号后，这里会显示各账号的实例数、健康度和到期提醒。");
                bigButton("＋ 添加云账号", v -> startActivity(new Intent(this, AccountsActivity.class).putExtra("add", true)));
                return;
            }
            LinearLayout exp = card("⏰ 30 天内到期");
            TextView expT = muted(exp, "读取中…");
            Api.quiet("/expiry-alerts", x -> {
                JSONArray al = Api.arr(x);
                if (al.length() == 0) { ((android.view.ViewGroup) exp.getParent()).setVisibility(android.view.View.GONE); return; }
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < al.length(); i++) {
                    JSONObject e = al.optJSONObject(i);
                    sb.append(e.optInt("days_left") <= 7 ? "🔴 " : "🟡 ").append(e.optString("account_name")).append(" · ").append(e.optString("name"))
                            .append("  ").append(e.optInt("days_left") == 0 ? "今天到期" : "剩 " + e.optInt("days_left") + " 天")
                            .append("（").append(e.optString("date")).append(e.optBoolean("estimated") ? "，估算" : "").append("）\n");
                }
                expT.setText(sb.toString().trim());
                expT.setTextColor(attr(com.google.android.material.R.attr.colorOnSurface));
            });
            LinearLayout hh = card("🩺 账号健康度");
            TextView hT = muted(hh, "读取中…");
            button(row(hh), "详情", v -> openPage("health", null));
            Api.quiet("/account-health", x -> {
                JSONArray l = Api.arr(x);
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < l.length(); i++) {
                    JSONObject h = l.optJSONObject(i);
                    boolean has = h.has("score") && !h.isNull("score");
                    int sc = h.optInt("score");
                    sb.append(!has ? "⚪ " : sc >= 80 ? "🟢 " : sc >= 50 ? "🟡 " : "🔴 ").append(h.optString("name")).append("  ")
                            .append(has ? sc + " 分 · " + HealthActivity.level(sc) : "未检测").append("\n");
                }
                hT.setText(sb.length() == 0 ? "暂无" : sb.toString().trim());
                hT.setTextColor(attr(com.google.android.material.R.attr.colorOnSurface));
            });
            for (int i = 0; i < a.length(); i++) {
                JSONObject acc = a.optJSONObject(i);
                LinearLayout c = card(acc.optString("name") + (acc.optInt("disabled") == 1 ? "  [已停用]" : ""));
                String reg = "azure".equals(acc.optString("provider")) ? "" : regionOf(acc);
                muted(c, pname(acc.optString("provider")) + (reg.isEmpty() ? "" : " · " + reg) + ageOf(acc));
                TextView cnt = text(c, "实例：查询中…", 13, false);
                String rq = "azure".equals(acc.optString("provider")) ? "" : "?region=" + Api.enc(reg);
                if (acc.optInt("disabled") == 1) cnt.setText("实例：账号已停用");
                else Api.job(this, () -> {
                    try { return Api.call("GET", "/accounts/" + acc.optInt("id") + "/instances" + rq, null); }
                    catch (Exception e) { return new JSONObject().put("error", e.getMessage()); }
                }, x -> {
                    if (x instanceof JSONObject) { String e = ((JSONObject) x).optString("error"); cnt.setText("实例：查询失败 " + (e.length() > 60 ? e.substring(0, 60) : e)); return; }
                    JSONArray l = Api.arr(x);
                    int run = 0;
                    for (int j = 0; j < l.length(); j++) if ("running".equalsIgnoreCase(l.optJSONObject(j).optString("state"))) run++;
                    cnt.setText("实例：" + l.length() + " 台（运行 " + run + "）");
                });
                button(row(c), "进入管理", v -> openPage("acc_" + acc.optInt("id"), acc));
            }
        });
    }

    static String ageOf(JSONObject acc) {
        String d = str(acc, "cloud_created_at", "");
        if (d.isEmpty()) return "";
        try {
            long days = (System.currentTimeMillis() - new java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US).parse(d).getTime()) / 86400000L;
            return "\n云上创建 " + d + " · 已存活 " + days + " 天";
        } catch (Exception e) { return ""; }
    }

    static String testOf(JSONObject acc) {
        if (!acc.has("last_test_ok") || acc.isNull("last_test_ok")) return "";
        return acc.optInt("last_test_ok") == 1 ? "\n连通 · " + acc.optInt("last_test_ms") + " ms" : "\n测活失败：" + str(acc, "last_test_error", "");
    }
}
