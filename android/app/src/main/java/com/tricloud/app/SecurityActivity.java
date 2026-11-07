package com.tricloud.app;

import android.net.Uri;
import android.os.Bundle;
import android.util.Base64;
import android.widget.LinearLayout;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Arrays;

/** 安全与备份（同 Web pageSecurity）：二次验证（TOTP）、加密备份 / 恢复、API Token、审计日志。 */
public class SecurityActivity extends BaseActivity {
    private byte[] pendingBackup;

    private final ActivityResultLauncher<String> saveDoc = registerForActivityResult(
            new ActivityResultContracts.CreateDocument("application/octet-stream"), this::onSaveUri);
    private final ActivityResultLauncher<String[]> openDoc = registerForActivityResult(
            new ActivityResultContracts.OpenDocument(), this::onOpenUri);

    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s1105)); refresh(); }

    @Override
    protected String navKey() { return "security"; }

    @Override
    protected void refresh() {
        Api.get(this, "/settings", sr -> {
            JSONObject s = Api.obj(sr);
            Api.get(this, "/tokens", tr -> Api.get(this, "/audit?limit=100", lr ->
                    Api.get(this, "/audit/logins", gr -> Api.get(this, "/sessions", dr ->
                            render(s, Api.arr(tr), Api.arr(lr), Api.arr(gr), Api.arr(dr))))));
        });
    }

    private void render(JSONObject s, JSONArray toks, JSONArray logs, JSONArray logins, JSONArray devs) {
        clear();
        boolean totp = s.optBoolean("totp_enabled");
        LinearLayout t = card(getString(R.string.s1106));
        muted(t, totp ? getString(R.string.s1107)
                : getString(R.string.s1108));
        button(row(t), totp ? getString(R.string.s1109) : getString(R.string.s1110), v -> { if (totp) totpOff(); else totpOn(); });

        LinearLayout b = card(getString(R.string.s1111));
        muted(b, getString(R.string.s1112));
        LinearLayout br = row(b);
        button(br, getString(R.string.s1113), v -> backup());
        button(br, getString(R.string.s1114), v -> openDoc.launch(new String[]{"*/*"}));

        LinearLayout k = card("API Token");
        muted(k, getString(R.string.s1115));
        button(row(k), getString(R.string.s1116), v -> form(getString(R.string.s1117), null, Arrays.asList(Field.text("name", getString(R.string.s0135), "bot"),
                Field.select("scope", getString(R.string.s1118), "read", new String[]{"read", "full"}, new String[]{getString(R.string.s1119), getString(R.string.s1120)})), getString(R.string.s1121),
                f -> Api.post(this, "/tokens", f, x -> {
                    secretDialog(getString(R.string.s1122), getString(R.string.s1123), Api.obj(x).optString("token"));
                    refresh();
                })));
        for (int i = 0; i < toks.length(); i++) {
            JSONObject x = toks.optJSONObject(i);
            LinearLayout c = card(x.optString("name") + " · " + ("read".equals(x.optString("scope")) ? getString(R.string.s1119) : getString(R.string.s1124)));
            muted(c, getString(R.string.s1125, x.optString("prefix"), (x.optLong("last_used") > 0 ? fmtTime(x.optLong("last_used")) : getString(R.string.s0940))));
            int tid = x.optInt("id");
            button(row(c), getString(R.string.s1126), v -> confirm(getString(R.string.s1127), getString(R.string.s1128), () -> Api.del(this, "/tokens/" + tid, y -> refresh())));
        }

        // build 38：已登录设备（同 Web 安全页：设备名 / IP / 登录与活跃时间 / 可踢下线）
        LinearLayout dv = card(getString(R.string.s1280));
        button(row(dv), getString(R.string.s1287), v -> confirm(getString(R.string.s1287), getString(R.string.s1299), () ->
                Api.post(this, "/sessions/kick-others", null, y -> { toast(getString(R.string.s1288, Api.obj(y).optInt("kicked"))); refresh(); })));
        if (devs.length() == 0) muted(dv, getString(R.string.s0584));
        for (int i = 0; i < devs.length(); i++) {
            JSONObject x = devs.optJSONObject(i);
            boolean cur = x.optBoolean("current");
            LinearLayout c = card((x.optString("device").isEmpty() ? getString(R.string.s1282) : x.optString("device")) + (cur ? " · " + getString(R.string.s1281) : ""));
            muted(c, "IP " + (x.optString("ip").isEmpty() ? "—" : x.optString("ip"))
                    + "\n" + getString(R.string.s1296) + " " + (x.optLong("created") > 0 ? fmtTime(x.optLong("created")) : "—")
                    + " · " + getString(R.string.s1297) + " " + (x.optLong("last_seen") > 0 ? fmtTime(x.optLong("last_seen")) : "—"));
            String sid = x.optString("id");
            button(row(c), getString(R.string.s1295), v -> confirm(getString(R.string.s1283), cur ? getString(R.string.s1285) : getString(R.string.s1284), () ->
                    Api.del(this, "/sessions/" + sid, y -> {
                        if (Api.obj(y).optBoolean("self")) { toLogin(); return; }
                        toast(getString(R.string.s1286)); refresh();
                    })));
        }

        // build 38：登录记录（同 Web 安全页）
        LinearLayout ln = card(getString(R.string.s1279));
        StringBuilder lb = new StringBuilder();
        for (int i = 0; i < logins.length(); i++) {
            JSONObject l = logins.optJSONObject(i);
            boolean okLogin = l.optString("detail").contains("200");
            lb.append(fmtTime(l.optLong("ts"))).append("  ").append(l.optString("ip")).append("  ")
                    .append(okLogin ? "✅ " + getString(R.string.s1293) : "❌ " + getString(R.string.s1294)).append("\n");
        }
        text(ln, lb.length() == 0 ? getString(R.string.s0584) : lb.toString().trim(), 12, false);

        LinearLayout lg = card(getString(R.string.s1129));
        // build 19：一键清空（红色按钮 + 确认；清空后服务端自动留一条 audit-clear 记录）
        button(row(lg), getString(R.string.s1130), v -> new com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
                .setTitle(getString(R.string.s1131))
                .setMessage(getString(R.string.s1132))
                .setNegativeButton(getString(R.string.s0614), null)
                .setPositiveButton(getString(R.string.s1133), (d, w) -> Api.del(this, "/audit?confirm=true", y -> {
                    toast(getString(R.string.s1134, Api.obj(y).optInt("deleted")));
                    refresh();
                })).show());
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < logs.length(); i++) {
            JSONObject l = logs.optJSONObject(i);
            String act = str(l, "action", "");
            if ("POST /api/login".equals(act)) act = "🔐 " + getString(R.string.s0949);
            sb.append(fmtTime(l.optLong("ts"))).append("  ").append(str(l, "actor", "-")).append("  ").append(str(l, "ip", "")).append("\n  ")
                    .append(act).append(str(l, "detail", "").isEmpty() ? "" : " · " + l.optString("detail")).append("\n");
        }
        text(lg, sb.length() == 0 ? getString(R.string.s0584) : sb.toString().trim(), 12, false);
    }

    private void totpOn() {
        Api.post(this, "/2fa/setup", null, r -> {
            JSONObject o = Api.obj(r);
            String sec = o.optString("secret");
            String png = o.optString("qr_png");
            if (png.isEmpty()) { totpCodeForm(sec); return; }
            try {
                byte[] raw = Base64.decode(png, Base64.DEFAULT);
                android.graphics.Bitmap bmp = android.graphics.BitmapFactory.decodeByteArray(raw, 0, raw.length);
                LinearLayout box = new LinearLayout(this);
                box.setOrientation(LinearLayout.VERTICAL);
                box.setPadding(dp(24), dp(8), dp(24), 0);
                android.widget.ImageView iv = new android.widget.ImageView(this);
                iv.setImageBitmap(bmp);
                iv.setAdjustViewBounds(true);
                box.addView(iv);
                android.widget.TextView tv = new android.widget.TextView(this);
                tv.setText(getString(R.string.s1289) + "\n" + sec);
                box.addView(tv);
                new com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
                        .setTitle(getString(R.string.s1110))
                        .setView(box)
                        .setNegativeButton(getString(R.string.s0614), null)
                        .setNeutralButton(getString(R.string.s1139), (d, w) -> { copy("totp", sec); totpCodeForm(sec); })
                        .setPositiveButton(getString(R.string.s1290), (d, w) -> totpCodeForm(sec))
                        .show();
            } catch (Exception e) { totpCodeForm(sec); }
        });
    }

    private void totpCodeForm(String sec) {
        form(getString(R.string.s1110), getString(R.string.s1135, sec),
                Arrays.asList(Field.num("code", getString(R.string.s1136), "")), getString(R.string.s1137),
                f -> Api.post(this, "/2fa/enable", f, x -> { toast(getString(R.string.s1138)); refresh(); }),
                getString(R.string.s1139), () -> { copy("totp", sec); body.postDelayed(this::totpOn, 300); });
    }

    private void totpOff() {
        form(getString(R.string.s1109), null, Arrays.asList(Field.pass("password", getString(R.string.s0946)), Field.num("code", getString(R.string.s1140), "")), getString(R.string.s0074),
                f -> Api.post(this, "/2fa/disable", f, x -> { toast(getString(R.string.s0292)); refresh(); }));
    }

    private void backup() {
        form(getString(R.string.s1141), getString(R.string.s1142), Arrays.asList(Field.pass("password", getString(R.string.s0946)), Field.pass("passphrase", getString(R.string.s1143))), getString(R.string.s1144), f -> {
            String[] name = {"tricloud.tcbk"};
            Api.job(this, () -> Api.rawPost("/backup", f, name), r -> {
                pendingBackup = (byte[]) r;
                saveDoc.launch(name[0]);
            });
        });
    }

    private void onSaveUri(Uri uri) {
        if (uri == null || pendingBackup == null) { pendingBackup = null; return; }
        byte[] data = pendingBackup;
        pendingBackup = null;
        Api.job(this, () -> {
            try (OutputStream os = getContentResolver().openOutputStream(uri)) { os.write(data); }
            return new JSONObject();
        }, r -> toast(getString(R.string.s1145, data.length / 1024)));
    }

    private void onOpenUri(Uri uri) {
        if (uri == null) return;
        Api.job(this, () -> {
            try (InputStream in = getContentResolver().openInputStream(uri); ByteArrayOutputStream bo = new ByteArrayOutputStream()) {
                byte[] buf = new byte[32768];
                int n;
                while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
                return Base64.encodeToString(bo.toByteArray(), Base64.NO_WRAP);
            }
        }, r -> form(getString(R.string.s1114), getString(R.string.s1146), Arrays.asList(Field.pass("passphrase", getString(R.string.s1147)), Field.pass("password", getString(R.string.s1148))), getString(R.string.s1149), f -> {
            try {
                Api.post(this, "/restore", f.put("file_b64", (String) r), x -> { toast(getString(R.string.s1057)); body.postDelayed(this::toLogin, 1200); });
            } catch (Exception ignored) { }
        }));
    }
}
