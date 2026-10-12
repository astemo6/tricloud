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
        setTitle("已删账号");
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
            LinearLayout head = card("共 " + st.optInt("count") + " 个");
            muted(head, by.toString().trim() + "\n平均存活 " + str(st, "avg_lifecycle_days", "—") + " 天 · 最长 " + str(st, "max_lifecycle_days", "—") + " 天"
                    + "\n预估费用合计 $" + String.format(Locale.US, "%.2f", st.optDouble("total_est_cost_usd", 0))
                    + " · 单个最高 $" + String.format(Locale.US, "%.2f", st.optDouble("max_est_cost_usd", 0))
                    + "\n删除账号时自动留档（取自本地账单缓存，不调用云 API），只是记录。");
            if (st.optInt("count") > 0) button(row(head), "清空记录", v -> confirm("清空已删账号记录", "只清空记录，不影响任何账号或云资源。确定？",
                    () -> Api.del(this, "/recycle-bin?confirm=true", y -> { toast("已清空"); refresh(); })));
            JSONArray a = o.optJSONArray("items");
            for (int i = 0; a != null && i < a.length(); i++) {
                JSONObject x = a.optJSONObject(i);
                LinearLayout c = card(x.optString("name") + ("legacy".equals(x.optString("source")) ? "  [旧版迁移]" : ""));
                String cost = x.isNull("est_cost") ? "—" : String.format(Locale.US, "%.2f %s", x.optDouble("est_cost"), str(x, "currency", "USD"));
                String when = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US).format(new java.util.Date(x.optLong("deleted_at") * 1000));
                muted(c, MainActivity.pname(x.optString("provider")) + " · 存活 " + (x.isNull("lifecycle_days") ? "—" : x.optString("lifecycle_days") + " 天")
                        + "（" + str(x, "age_basis", "-") + "）\n预估费用 " + cost + "（" + str(x, "cost_basis", "-") + "）\n删除于 " + when);
                int rid = x.optInt("id");
                button(row(c), "移除记录", v -> Api.del(this, "/recycle-bin/" + rid, y -> refresh()));
            }
            if (a == null || a.length() == 0) muted(card("还没有删除过账号"), "");
        });
    }
}
