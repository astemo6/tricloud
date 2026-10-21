package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Iterator;
import java.util.Locale;

/** v1.5 已删账号：删除账号时留档的名称、云、存活天数、预估费用。与 AWS「闲置资源」估算无关。 */
public class DeletedActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) {
        super.onCreate(s);
        setTitle(getString(R.string.s0844));
        refresh();
    }

    @Override
    protected String navKey() { return "accounts"; }

    @Override
    protected void refresh() {
        Api.get(this, "/recycle-bin", r -> {
            clear();
            JSONObject o = Api.obj(r);
            JSONObject st = o.optJSONObject("stats");
            if (st == null) st = new JSONObject();
            StringBuilder by = new StringBuilder();
            JSONObject bp = st.optJSONObject("by_provider");
            if (bp != null) for (Iterator<String> it = bp.keys(); it.hasNext(); ) { String k = it.next(); by.append(MainActivity.pname(k)).append(" ").append(bp.optInt(k)).append("  "); }
            LinearLayout head = card(getString(R.string.s0845, st.optInt("count")));
            muted(head, getString(R.string.s0846, by.toString().trim(), str(st, "avg_lifecycle_days", "—"), str(st, "max_lifecycle_days", "—"), String.format(Locale.US, "%.2f", st.optDouble("total_est_cost_usd", 0)), String.format(Locale.US, "%.2f", st.optDouble("max_est_cost_usd", 0))));
            if (st.optInt("count") > 0) button(row(head), getString(R.string.s0847), v -> confirm(getString(R.string.s0848), getString(R.string.s0849),
                    () -> Api.del(this, "/recycle-bin?confirm=true", y -> { toast(getString(R.string.s0850)); refresh(); })));
            JSONArray a = o.optJSONArray("items");
            for (int i = 0; a != null && i < a.length(); i++) {
                JSONObject x = a.optJSONObject(i);
                LinearLayout c = card(x.optString("name") + ("legacy".equals(x.optString("source")) ? getString(R.string.s0851) : ""));
                String cost = x.isNull("est_cost") ? "—" : String.format(Locale.US, "%.2f %s", x.optDouble("est_cost"), str(x, "currency", "USD"));
                String when = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US).format(new java.util.Date(x.optLong("deleted_at") * 1000));
                muted(c, getString(R.string.s0853, MainActivity.pname(x.optString("provider")), (x.isNull("lifecycle_days") ? "—" : getString(R.string.s0852, x.optString("lifecycle_days"))), str(x, "age_basis", "-"), cost, str(x, "cost_basis", "-"), when));
                int rid = x.optInt("id");
                button(row(c), getString(R.string.s0854), v -> Api.del(this, "/recycle-bin/" + rid, y -> refresh()));
            }
            if (a == null || a.length() == 0) muted(card(getString(R.string.s0855)), "");
        });
    }
}
