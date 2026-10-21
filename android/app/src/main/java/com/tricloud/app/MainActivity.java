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

    /** 没有区域概念的云厂商（Azure 用资源组位置）。 */
    static boolean noRegion(String p) { return "azure".equals(p); }
    private boolean first = true;
    private boolean rescan = false;   // 「重新扫描区域」：下一次刷新带 refresh=true

    @Override
    protected void onCreate(Bundle s) {
        super.onCreate(s);
        setTitle(getString(R.string.s0952));
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

    /** 手动选过的区域 > 机器最多的区域（build 25）> 账号默认区域。 */
    static String regionOf(JSONObject a) { return Regions.current(a); }

    @Override
    protected void refresh() {
        Api.meta(null);
        Api.get(this, "/accounts", r -> {
            clear();
            JSONArray a = Api.arr(r);
            Api.accounts = a;
            Regions.HINTS.clear();   // build 25：/accounts 带的 machine_regions 是后端最新记录
            buildNav();
            if (a.length() == 0) {
                muted(card(getString(R.string.s0717)), getString(R.string.s0953));
                bigButton(getString(R.string.s0954), v -> startActivity(new Intent(this, AccountsActivity.class).putExtra("add", true)));
                return;
            }
            LinearLayout exp = card(getString(R.string.s0955));
            TextView expT = muted(exp, getString(R.string.s0527));
            Api.quiet("/expiry-alerts", x -> {
                JSONArray al = Api.arr(x);
                if (al.length() == 0) { ((android.view.ViewGroup) exp.getParent()).setVisibility(android.view.View.GONE); return; }
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < al.length(); i++) {
                    JSONObject e = al.optJSONObject(i);
                    sb.append(e.optInt("days_left") <= 7 ? "🔴 " : "🟡 ").append(e.optString("account_name")).append(" · ").append(e.optString("name"))
                            .append("  ").append(e.optInt("days_left") == 0 ? getString(R.string.s0375) : getString(R.string.s0769, e.optInt("days_left")))
                            .append("（").append(e.optString("date")).append(e.optBoolean("estimated") ? getString(R.string.s0377) : "").append("）\n");
                }
                expT.setText(sb.toString().trim());
                expT.setTextColor(attr(com.google.android.material.R.attr.colorOnSurface));
            });
            LinearLayout hh = card(getString(R.string.s0956));
            TextView hT = muted(hh, getString(R.string.s0527));
            button(row(hh), getString(R.string.s0957), v -> openPage("health", null));
            Api.quiet("/account-health", x -> {
                JSONArray l = Api.arr(x);
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < l.length(); i++) {
                    JSONObject h = l.optJSONObject(i);
                    boolean has = h.has("score") && !h.isNull("score");
                    int sc = h.optInt("score");
                    sb.append(!has ? "⚪ " : sc >= 80 ? "🟢 " : sc >= 50 ? "🟡 " : "🔴 ").append(h.optString("name")).append("  ")
                            .append(has ? getString(R.string.s0938, sc, (sc >= 80 ? getString(R.string.s0932) : sc >= 50 ? getString(R.string.s0933) : getString(R.string.s0934))) : getString(R.string.s0939)).append("\n");
                }
                hT.setText(sb.length() == 0 ? getString(R.string.s0584) : sb.toString().trim());
                hT.setTextColor(attr(com.google.android.material.R.attr.colorOnSurface));
            });
            LinearLayout ov = card(getString(R.string.s0958));
            muted(ov, getString(R.string.s0959));
            button(row(ov), getString(R.string.s0960), v -> { rescan = true; refresh(); });
            boolean force = rescan;
            rescan = false;
            for (int i = 0; i < a.length(); i++) {
                JSONObject acc = a.optJSONObject(i);
                LinearLayout c = card(acc.optString("name") + (acc.optInt("disabled") == 1 ? getString(R.string.s0724) : ""));
                String prov = acc.optString("provider");
                String reg = noRegion(prov) ? "" : regionOf(acc);
                TextView head = muted(c, pname(prov) + (reg.isEmpty() ? "" : " · " + Regions.label(reg)) + ageOf(acc));
                TextView cnt = text(c, getString(R.string.s0961), 13, false);
                if (acc.optInt("disabled") == 1) cnt.setText(getString(R.string.s0962));
                // 后端 /overview 统计所有有机器的区域（AWS EC2+Lightsail 全区域、OCI 订阅区域、Azure 整个订阅），带缓存
                else Api.job(this, () -> {
                    try { return Api.call("GET", "/accounts/" + acc.optInt("id") + "/overview" + (force ? "?refresh=true" : ""), null); }
                    catch (Exception e) { return new JSONObject().put("error", e.getMessage()); }
                }, x -> {
                    JSONObject o = (JSONObject) x;
                    if (o.has("error") && !o.has("total")) { String e = o.optString("error"); cnt.setText(getString(R.string.s0963, (e.length() > 60 ? e.substring(0, 60) : e))); return; }
                    Regions.apply(acc.optInt("id"), o);   // build 25：账号列表 / 打开账号的默认区域同步更新
                    JSONArray rs = o.optJSONArray("regions");
                    String brief = Regions.brief(rs);
                    String dr = o.optString("default_region", "");
                    if (o.isNull("default_region")) dr = reg;
                    String where = !brief.isEmpty() ? brief : (dr.isEmpty() ? "" : Regions.label(dr));
                    head.setText(pname(prov) + (where.isEmpty() ? "" : " · " + where) + ageOf(acc));
                    cnt.setText(getString(R.string.s0965, Regions.count(o), (rs != null && rs.length() > 1 ? getString(R.string.s0964, Regions.dist(rs)) : "")));
                });
                button(row(c), getString(R.string.s0966), v -> openPage("acc_" + acc.optInt("id"), acc));
            }
        });
    }

    static String ageOf(JSONObject acc) {
        String d = str(acc, "cloud_created_at", "");
        if (d.isEmpty()) return "";
        try {
            long days = (System.currentTimeMillis() - new java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US).parse(d).getTime()) / 86400000L;
            return L10n.s(R.string.s0967, d, days);
        } catch (Exception e) { return ""; }
    }

    static String testOf(JSONObject acc) {
        if (!acc.has("last_test_ok") || acc.isNull("last_test_ok")) return "";
        return acc.optInt("last_test_ok") == 1 ? L10n.s(R.string.s0968, acc.optInt("last_test_ms")) : L10n.s(R.string.s0969, str(acc, "last_test_error", ""));
    }
}
