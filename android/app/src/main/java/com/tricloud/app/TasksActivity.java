package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** 任务列表：抢机 / 换 IP / 改配置等，可查看实时日志、停止运行中的任务。 */
public class TasksActivity extends BaseActivity {
    private final Runnable tick = this::refresh;

    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s1212)); refresh(); }

    @Override
    protected void onPause() { super.onPause(); body.removeCallbacks(tick); }

    static String tn(String t) {
        switch (t) {
            case "snatch": return L10n.s(R.string.s1213); case "change_ip": return L10n.s(R.string.s0035); case "resize": return L10n.s(R.string.s0042); case "ipv6": return "IPv6";
            case "azure_create": return L10n.s(R.string.s0015); case "ensure_network": return L10n.s(R.string.s1214); case "snapshot": return L10n.s(R.string.s1215); case "migrate": return L10n.s(R.string.s0051); case "cf_delete": return L10n.s(R.string.s1216);
            case "reinstall": return L10n.s(R.string.s0056); case "net500m": return L10n.s(R.string.s1217); case "foundry": return L10n.s(R.string.s1218); case "billing_keep": return L10n.s(R.string.s1219);
            case "aws_credit": return L10n.s(R.string.s0013); case "onedrive_backup": return L10n.s(R.string.s0985);
            default: return t;
        }
    }

    static String st(String s) {
        switch (s) {
            case "running": return L10n.s(R.string.s1210); case "done": return L10n.s(R.string.s0465); case "failed": return L10n.s(R.string.s0728); case "stopped": return L10n.s(R.string.s0313); case "interrupted": return L10n.s(R.string.s1220);
            default: return s;
        }
    }

    @Override
    protected String navKey() { return "tasks"; }

    @Override
    protected void refresh() {
        body.removeCallbacks(tick);
        Api.get(this, "/tasks", r -> {
            clear();
            JSONArray a = Api.arr(r);
            muted(card(null), getString(R.string.s1221));
            if (a.length() == 0) muted(card(getString(R.string.s1222)), "");
            SimpleDateFormat f = new SimpleDateFormat("MM-dd HH:mm:ss", Locale.getDefault());
            for (int i = 0; i < a.length(); i++) {
                JSONObject t = a.optJSONObject(i);
                LinearLayout c = card("#" + t.optInt("id") + " " + tn(t.optString("type")) + "  [" + st(t.optString("status")) + "]");
                text(c, getString(R.string.s1223, str(t, "account_name", "-"), t.optInt("attempts"), str(t, "message", "")), 13, false);
                muted(c, getString(R.string.s1224, f.format(new Date(t.optLong("updated") * 1000))));
                LinearLayout row = row(c);
                int tid = t.optInt("id");
                button(row, getString(R.string.s1225), v -> openTask(tid));
                if ("running".equals(t.optString("status")))
                    button(row, getString(R.string.s0033), v -> confirm(getString(R.string.s1206), "#" + tid, () -> Api.post(this, "/tasks/" + tid + "/stop", null, x -> refresh())));
                else button(row, getString(R.string.s0057), v -> Api.del(this, "/tasks/" + tid, x -> refresh()));
            }
            body.postDelayed(tick, 10000);
        });
    }
}
