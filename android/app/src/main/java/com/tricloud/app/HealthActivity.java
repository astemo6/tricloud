package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** 账号健康度：0–100 分，每天 07:30 自动检测，掉分推送 Telegram。 */
public class HealthActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s0931)); refresh(); }

    String level(int sc) { return sc >= 80 ? getString(R.string.s0932) : sc >= 50 ? getString(R.string.s0933) : getString(R.string.s0934); }

    @Override
    protected String navKey() { return "health"; }

    @Override
    protected void refresh() {
        Api.get(this, "/account-health", r -> {
            clear();
            muted(card(getString(R.string.s0338)), getString(R.string.s0935));
            bigButton(getString(R.string.s0936), v -> Api.post(this, "/account-health/refresh", new JSONObject(), x -> { toast(getString(R.string.s0937)); refresh(); }));
            JSONArray a = Api.arr(r);
            for (int i = 0; i < a.length(); i++) {
                JSONObject h = a.optJSONObject(i);
                boolean has = !h.isNull("score");
                LinearLayout c = card(h.optString("name") + "  " + (has ? getString(R.string.s0938, h.optInt("score"), level(h.optInt("score"))) : getString(R.string.s0939)));
                muted(c, getString(R.string.s0941, MainActivity.pname(h.optString("provider")), (h.optLong("checked_at") > 0 ? fmtTime(h.optLong("checked_at")) : getString(R.string.s0940))));
                JSONArray items = h.optJSONArray("items");
                StringBuilder sb = new StringBuilder();
                for (int j = 0; items != null && j < items.length(); j++) {
                    JSONObject it = items.optJSONObject(j);
                    sb.append(it.optBoolean("ok") ? "✓ " : "! ").append(it.optString("name"));
                    if (it.optInt("penalty") > 0) sb.append("  -").append(it.optInt("penalty"));
                    sb.append("\n   ").append(it.optString("detail")).append("\n");
                }
                if (sb.length() > 0) text(c, sb.toString().trim(), 13, false);
                int aid = h.optInt("account_id");
                button(row(c), getString(R.string.s0942), v -> {
                    try { Api.post(this, "/account-health/refresh", new JSONObject().put("account_id", aid), x -> { toast(getString(R.string.s0937)); refresh(); }); } catch (Exception ignored) { }
                });
            }
        });
    }
}
