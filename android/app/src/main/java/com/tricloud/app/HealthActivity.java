package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** 账号健康度：0–100 分，每天 07:30 自动检测，掉分推送 Telegram。 */
public class HealthActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("账号健康度"); refresh(); }

    static String level(int sc) { return sc >= 80 ? "健康" : sc >= 50 ? "注意" : "危险"; }

    @Override
    protected String navKey() { return "health"; }

    @Override
    protected void refresh() {
        Api.get(this, "/account-health", r -> {
            clear();
            muted(card("说明"), "每天 07:30 自动检测；分数下降 ≥15 或进入「危险」会推送 Telegram。检查凭证/封禁、被动停机、实例消失、非容量类任务失败、OCI A1 配额、AWS Credit、Azure 订阅状态。只用免费只读接口。");
            bigButton("全部重新检测", v -> Api.post(this, "/account-health/refresh", new JSONObject(), x -> { toast("检测完成"); refresh(); }));
            JSONArray a = Api.arr(r);
            for (int i = 0; i < a.length(); i++) {
                JSONObject h = a.optJSONObject(i);
                boolean has = !h.isNull("score");
                LinearLayout c = card(h.optString("name") + "  " + (has ? h.optInt("score") + " 分 · " + level(h.optInt("score")) : "未检测"));
                muted(c, MainActivity.pname(h.optString("provider")) + " · 检测于 " + (h.optLong("checked_at") > 0 ? fmtTime(h.optLong("checked_at")) : "从未"));
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
                button(row(c), "检测", v -> {
                    try { Api.post(this, "/account-health/refresh", new JSONObject().put("account_id", aid), x -> { toast("检测完成"); refresh(); }); } catch (Exception ignored) { }
                });
            }
        });
    }
}
