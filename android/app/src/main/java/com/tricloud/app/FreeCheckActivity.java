package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** 免费额度体检（同 Web pageFreeCheck）：逐个 OCI 账号检查 A1 / E2.1.Micro / 块存储是否超出 Always Free，给出降配建议。 */
public class FreeCheckActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("免费额度体检"); refresh(); }

    @Override
    protected String navKey() { return "freecheck"; }

    private static String bar(JSONObject o, String k, String lim) {
        if (o == null) return "-";
        String v = o.isNull(k) ? "-" : o.optString(k);
        double dv = o.optDouble(k, 0), dl = o.optDouble(lim, 0);
        return v + " / " + o.optString(lim) + (dv > dl ? "  ⚠ 超出" : "");
    }

    @Override
    protected void refresh() {
        clear();
        muted(card("正在检查…"), "逐个读取 OCI 账号主区域 / 默认区域的用量");
        Api.get(this, "/oci/free-check", r -> {
            clear();
            muted(card("说明"), "逐个检查 OCI 账号（主区域 / 默认区域）的 A1、E2.1.Micro、块存储用量是否超出 Always Free。只给建议，降配需要你确认后才执行（只降不升，不会删实例）。"
                    + "\nA1 免费额度：免费号 2 OCPU / 12 GB（2026-06 起），付费号仍为 4 OCPU / 24 GB。");
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card("没有启用中的 OCI 账号"), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject x = a.optJSONObject(i);
                if (!str(x, "error", "").isEmpty()) { muted(card(x.optString("name")), "❌ " + x.optString("error")); continue; }
                boolean ok = x.optBoolean("ok");
                LinearLayout c = card(x.optString("name") + (ok ? "  ✅" : "  ⚠"));
                String basis = x.optString("a1_basis");
                text(c, "A1 OCPU：" + bar(x.optJSONObject("a1"), "ocpus", "limit_ocpus")
                        + "\nA1 内存 GB：" + bar(x.optJSONObject("a1"), "memory_gb", "limit_mem")
                        + "\nMicro 台数：" + bar(x.optJSONObject("micro"), "count", "limit")
                        + "\n块存储 GB：" + bar(x.optJSONObject("storage"), "used_gb", "limit"), 13, false);
                if (!basis.isEmpty()) muted(c, "A1 额度按" + ("paid".equals(basis) ? "付费号 4 OCPU / 24 GB" : "free".equals(basis) ? "免费号 2 OCPU / 12 GB" : "免费号 2 OCPU / 12 GB（未识别账号类型）") + "计算");
                if (ok) muted(c, "都在免费额度内");
                JSONArray is = x.optJSONArray("issues");
                StringBuilder sb = new StringBuilder();
                for (int j = 0; is != null && j < is.length(); j++) sb.append("• ").append(is.optString(j)).append("\n");
                if (sb.length() > 0) text(c, sb.toString().trim(), 13, false).setTextColor(attr(androidx.appcompat.R.attr.colorError));
                LinearLayout row = row(c);
                JSONArray sg = x.optJSONArray("suggestions");
                int aid = x.optInt("account_id");
                for (int j = 0; sg != null && j < sg.length(); j++) {
                    JSONObject s = sg.optJSONObject(j);
                    String line = s.optString("name") + "：" + s.optString("ocpus") + "C/" + s.optString("memory_gb") + "G → "
                            + (s.optBoolean("delete") ? "额度已用完，建议停用或删除" : s.optString("to_ocpus") + "C/" + s.optString("to_memory_gb") + "G");
                    muted(c, line);
                    if (!s.optBoolean("delete")) button(row, "降配 " + s.optString("name"), v -> confirm("降配",
                            "把「" + s.optString("name") + "」从 " + s.optString("ocpus") + "C/" + s.optString("memory_gb") + "G 降到 " + s.optString("to_ocpus") + "C/" + s.optString("to_memory_gb") + "G？实例可能会重启。", () -> {
                        try {
                            JSONObject b = new JSONObject().put("instance_id", s.optString("id")).put("name", s.optString("name"))
                                    .put("ocpus", s.opt("to_ocpus")).put("memory_gb", s.opt("to_memory_gb")).put("confirm_overage", true);
                            Api.post(this, "/accounts/" + aid + "/instances/resize", b, y -> taskOrToast(y, "已提交"));
                        } catch (Exception ignored) { }
                    }));
                }
                JSONObject acc = findAcc(aid);
                if (acc != null) button(row, "打开账号", v -> openPage("acc_" + aid, acc));
            }
        });
    }

    static JSONObject findAcc(int id) {
        JSONArray a = Api.accounts;
        for (int i = 0; a != null && i < a.length(); i++) if (a.optJSONObject(i).optInt("id") == id) return a.optJSONObject(i);
        return null;
    }
}
