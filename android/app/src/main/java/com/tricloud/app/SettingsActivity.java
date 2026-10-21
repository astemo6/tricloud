package com.tricloud.app;

import android.content.Intent;
import android.os.Bundle;
import android.widget.EditText;
import android.widget.LinearLayout;

import org.json.JSONObject;

import java.util.Arrays;

/** 设置：Telegram、每日报告、监控间隔、默认创建参数、面板密码、App 配色。 */
public class SettingsActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s1062)); refresh(); }

    @Override
    protected String navKey() { return "settings"; }

    private void setLang(String v) {
        getSharedPreferences("tricloud", MODE_PRIVATE).edit().putString("app_lang", v).apply();
        Intent i = new Intent(this, LoginActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(i);
    }

    @Override
    protected void refresh() {
        Api.get(this, "/settings", r -> {
            clear();
            JSONObject s = Api.obj(r);
            LinearLayout lg = card(getString(R.string.set_lang_card));
            String curLang = getSharedPreferences("tricloud", MODE_PRIVATE).getString("app_lang", "system");
            muted(lg, getString(R.string.set_lang_cur, "zh".equals(curLang) ? getString(R.string.set_lang_zh) : "en".equals(curLang) ? getString(R.string.set_lang_en) : getString(R.string.set_lang_system)));
            LinearLayout lr = row(lg);
            button(lr, getString(R.string.set_lang_system), v -> setLang("system"));
            button(lr, getString(R.string.set_lang_zh), v -> setLang("zh"));
            button(lr, getString(R.string.set_lang_en), v -> setLang("en"));
            LinearLayout tg = card("Telegram");
            muted(tg, getString(R.string.s1153, (s.optBoolean("tg_token_set") ? getString(R.string.s1150, s.optString("tg_token_hint")) : getString(R.string.s0995)), str(s, "tg_chat_id", "-"), (s.optBoolean("daily_report") ? getString(R.string.s1151, str(s, "report_time", "09:00")) : getString(R.string.s1152)), str(s, "monitor_interval", "5")));
            LinearLayout r1 = row(tg);
            button(r1, getString(R.string.s1154), v -> form(getString(R.string.s1155), getString(R.string.s1156), Arrays.asList(
                    Field.pass("tg_token", "Bot Token"),
                    Field.text("tg_chat_id", "Chat ID", str(s, "tg_chat_id", "")),
                    Field.check("daily_report", getString(R.string.s1157), s.optBoolean("daily_report")),
                    Field.text("report_time", getString(R.string.s1158), str(s, "report_time", "09:00")),
                    Field.num("monitor_interval", getString(R.string.s1159), str(s, "monitor_interval", "5")),
                    Field.text("timezone", getString(R.string.s1160), str(s, "timezone", "Asia/Shanghai"))), getString(R.string.s0089), vals -> {
                if (vals.optString("tg_token").isEmpty()) vals.remove("tg_token");
                Api.post(this, "/settings", vals, x -> { toast(getString(R.string.s0777)); refresh(); });
            }));
            button(r1, getString(R.string.s1161), v -> Api.post(this, "/settings/tg-test", null, x -> toast(getString(R.string.s1162))));

            LinearLayout cf = card("Cloudflare");
            muted(cf, getString(R.string.s1163, (s.optBoolean("cf_token_set") ? getString(R.string.s0994) : getString(R.string.s0995))));
            LinearLayout rcf = row(cf);
            button(rcf, s.optBoolean("cf_token_set") ? getString(R.string.s1164) : getString(R.string.s1165), v -> form("Cloudflare API Token", null, Arrays.asList(Field.pass("cf_token", "API Token")), getString(R.string.s0089), vals -> {
                if (vals.optString("cf_token").isEmpty()) { toast(getString(R.string.s1166)); return; }
                Api.post(this, "/settings", vals, x -> { toast(getString(R.string.s0777)); refresh(); });
            }));
            if (s.optBoolean("cf_token_set")) button(rcf, getString(R.string.s1167), v -> confirm(getString(R.string.s1168), getString(R.string.s1169), () -> {
                try { Api.post(this, "/settings", new JSONObject().put("cf_token_clear", true), x -> { toast(getString(R.string.s1170)); refresh(); }); } catch (Exception ignored) { }
            }));

            LinearLayout pc = card(getString(R.string.s1171));
            muted(pc, getString(R.string.s1172, (s.optBoolean("proxycheck_key_set") ? getString(R.string.s0994) : getString(R.string.s0995))));
            LinearLayout rpc = row(pc);
            button(rpc, s.optBoolean("proxycheck_key_set") ? getString(R.string.s1173) : getString(R.string.s1174), v -> form("proxycheck.io Key", null, Arrays.asList(Field.pass("proxycheck_key", "Key")), getString(R.string.s0089), vals -> {
                if (vals.optString("proxycheck_key").isEmpty()) { toast(getString(R.string.s1175)); return; }
                Api.post(this, "/settings", vals, x -> { toast(getString(R.string.s0777)); refresh(); });
            }));
            if (s.optBoolean("proxycheck_key_set")) button(rpc, getString(R.string.s1167), v -> {
                try { Api.post(this, "/settings", new JSONObject().put("proxycheck_key_clear", true), x -> { toast(getString(R.string.s1170)); refresh(); }); } catch (Exception ignored) { }
            });

            LinearLayout dc = card(getString(R.string.s1176));
            EditText e = new EditText(this);
            JSONObject d = s.optJSONObject("default_create");
            try { e.setText(d == null ? "{\n  \"oci\": {\"shape\": \"VM.Standard.A1.Flex\", \"ocpus\": 4, \"memory_gb\": 24, \"disk_gb\": 50, \"os\": \"Canonical Ubuntu\", \"os_version\": \"22.04\", \"ssh_key\": \"\"},\n  \"lightsail\": {\"blueprint\": \"debian_12\", \"bundle\": \"nano_3_0\"}\n}" : d.toString(2)); }
            catch (Exception ignored) { }
            e.setTextSize(12);
            e.setTypeface(android.graphics.Typeface.MONOSPACE);
            muted(dc, getString(R.string.s1177));
            dc.addView(e);
            LinearLayout r2 = row(dc);
            button(r2, getString(R.string.s0089), v -> {
                try { Api.post(this, "/settings", new JSONObject().put("default_create", new JSONObject(e.getText().toString())), x -> toast(getString(R.string.s0777))); }
                catch (Exception ex) { toast(getString(R.string.s1178)); }
            });

            LinearLayout fg = card(getString(R.string.s1179));
            boolean on = !s.has("free_guard") || s.isNull("free_guard") || s.optBoolean("free_guard", true);
            muted(fg, getString(R.string.s1181, (on ? getString(R.string.s1180) : getString(R.string.s1152))));
            button(row(fg), on ? getString(R.string.s1182) : getString(R.string.s1183), v -> {
                try { Api.post(this, "/settings", new JSONObject().put("free_guard", !on), x -> refresh()); } catch (Exception ignored) { }
            });

            LinearLayout ai = card(getString(R.string.s1184));
            muted(ai, getString(R.string.s1185, s.optInt("auto_ip_daily_limit", 3)));
            button(row(ai), getString(R.string.s1154), v -> form(getString(R.string.s1184), getString(R.string.s1186), Arrays.asList(
                    Field.num("auto_ip_daily_limit", getString(R.string.s1187), String.valueOf(s.optInt("auto_ip_daily_limit", 3)))), getString(R.string.s0089), vals -> {
                try { Api.post(this, "/settings", new JSONObject().put("auto_ip_daily_limit", Integer.parseInt(vals.optString("auto_ip_daily_limit", "3"))), x -> refresh()); }
                catch (Exception ex) { toast(getString(R.string.s1188)); }
            }));

            LinearLayout od = card(getString(R.string.s0985));
            muted(od, getString(R.string.s1189));
            button(row(od), getString(R.string.s1190), v -> startActivity(new android.content.Intent(this, OneDriveActivity.class)));

            LinearLayout pw = card(getString(R.string.s0946));
            muted(pw, getString(R.string.s1191));
            LinearLayout r3 = row(pw);
            button(r3, getString(R.string.s1192), v -> form(getString(R.string.s1193), getString(R.string.s1194), Arrays.asList(
                    Field.pass("old", getString(R.string.s1195)), Field.pass("new", getString(R.string.s1196))), getString(R.string.s1154),
                    vals -> Api.post(this, "/password", vals, x -> { toast(getString(R.string.s1197)); toLogin(); })));

            LinearLayout th = card(getString(R.string.s1198));
            LinearLayout r4 = row(th);
            String cur = Api.pref("theme", "system");
            for (String[] m : new String[][]{{"system", getString(R.string.s1199)}, {"light", getString(R.string.s1200)}, {"dark", getString(R.string.s1201)}})
                button(r4, (m[0].equals(cur) ? "● " : "") + m[1], v -> { Api.setPref("theme", m[0]); applyTheme(); recreate(); });
            muted(card(getString(R.string.s1202)), Api.server());
        });
    }
}
