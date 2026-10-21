package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** 免费额度体检（同 Web pageFreeCheck）：逐个 OCI 账号检查 A1 / E2.1.Micro / 块存储是否超出 Always Free，给出降配建议。 */
public class FreeCheckActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s0864)); refresh(); }

    @Override
    protected String navKey() { return "freecheck"; }

    private static String bar(JSONObject o, String k, String lim) {
        if (o == null) return "-";
        String v = o.isNull(k) ? "-" : o.optString(k);
        double dv = o.optDouble(k, 0), dl = o.optDouble(lim, 0);
        return v + " / " + o.optString(lim) + (dv > dl ? L10n.s(R.string.s0865) : "");
    }

    @Override
    protected void refresh() {
        clear();
        muted(card(getString(R.string.s0866)), getString(R.string.s0867));
        Api.get(this, "/oci/free-check", r -> {
            clear();
            muted(card(getString(R.string.s0338)), getString(R.string.s0868));
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card(getString(R.string.s0869)), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject x = a.optJSONObject(i);
                if (!str(x, "error", "").isEmpty()) { muted(card(x.optString("name")), "❌ " + x.optString("error")); continue; }
                boolean ok = x.optBoolean("ok");
                LinearLayout c = card(x.optString("name") + (ok ? "  ✅" : "  ⚠"));
                String basis = x.optString("a1_basis");
                text(c, getString(R.string.s0870, bar(x.optJSONObject("a1"), "ocpus", "limit_ocpus"), bar(x.optJSONObject("a1"), "memory_gb", "limit_mem"), bar(x.optJSONObject("micro"), "count", "limit"), bar(x.optJSONObject("storage"), "used_gb", "limit")), 13, false);
                if (!basis.isEmpty()) muted(c, getString(R.string.s0874, ("paid".equals(basis) ? getString(R.string.s0871) : "free".equals(basis) ? getString(R.string.s0872) : getString(R.string.s0873))));
                if (ok) muted(c, getString(R.string.s0875));
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
                            + (s.optBoolean("delete") ? getString(R.string.s0876) : s.optString("to_ocpus") + "C/" + s.optString("to_memory_gb") + "G");
                    muted(c, line);
                    if (!s.optBoolean("delete")) button(row, getString(R.string.s0877, s.optString("name")), v -> confirm(getString(R.string.s0878),
                            getString(R.string.s0879, s.optString("name"), s.optString("ocpus"), s.optString("memory_gb"), s.optString("to_ocpus"), s.optString("to_memory_gb")), () -> {
                        try {
                            JSONObject b = new JSONObject().put("instance_id", s.optString("id")).put("name", s.optString("name"))
                                    .put("ocpus", s.opt("to_ocpus")).put("memory_gb", s.opt("to_memory_gb")).put("confirm_overage", true);
                            Api.post(this, "/accounts/" + aid + "/instances/resize", b, y -> taskOrToast(y, getString(R.string.s0037)));
                        } catch (Exception ignored) { }
                    }));
                }
                JSONObject acc = findAcc(aid);
                if (acc != null) button(row, getString(R.string.s0880), v -> openPage("acc_" + aid, acc));
            }
        });
    }

    static JSONObject findAcc(int id) {
        JSONArray a = Api.accounts;
        for (int i = 0; a != null && i < a.length(); i++) if (a.optJSONObject(i).optInt("id") == id) return a.optJSONObject(i);
        return null;
    }
}
