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
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("安全与备份"); refresh(); }

    @Override
    protected String navKey() { return "security"; }

    @Override
    protected void refresh() {
        Api.get(this, "/settings", sr -> {
            JSONObject s = Api.obj(sr);
            Api.get(this, "/tokens", tr -> Api.get(this, "/audit?limit=100", lr -> render(s, Api.arr(tr), Api.arr(lr))));
        });
    }

    private void render(JSONObject s, JSONArray toks, JSONArray logs) {
        clear();
        boolean totp = s.optBoolean("totp_enabled");
        LinearLayout t = card("二次验证（TOTP）");
        muted(t, totp ? "✅ 已开启：登录需要身份验证器 App 上的 6 位验证码。"
                : "支持 Google Authenticator、1Password、Authy 等。开启后即使面板密码泄露也无法登录。");
        button(row(t), totp ? "关闭二次验证" : "开启二次验证", v -> { if (totp) totpOff(); else totpOn(); });

        LinearLayout b = card("加密备份 / 恢复");
        muted(b, "备份包含全部账号凭证、设置和加密密钥，整包再用你设置的口令加密（scrypt + Fernet）。口令丢失则无法恢复。");
        LinearLayout br = row(b);
        button(br, "下载备份", v -> backup());
        button(br, "从备份恢复", v -> openDoc.launch(new String[]{"*/*"}));

        LinearLayout k = card("API Token");
        muted(k, "给脚本、自建 Bot 调用面板 API 用（Header：Authorization: Bearer <Token>）。只读 Token 只能 GET；任何 Token 都不能改密码、2FA、备份。");
        button(row(k), "＋ 新建 Token", v -> form("新建 API Token", null, Arrays.asList(Field.text("name", "名称", "bot"),
                Field.select("scope", "权限", "read", new String[]{"read", "full"}, new String[]{"只读", "完全（可开关机、换 IP）"})), "生成",
                f -> Api.post(this, "/tokens", f, x -> {
                    secretDialog("Token 已生成", "只显示这一次，请立即保存：", Api.obj(x).optString("token"));
                    refresh();
                })));
        for (int i = 0; i < toks.length(); i++) {
            JSONObject x = toks.optJSONObject(i);
            LinearLayout c = card(x.optString("name") + " · " + ("read".equals(x.optString("scope")) ? "只读" : "完全"));
            muted(c, "前缀 " + x.optString("prefix") + "…\n最近使用：" + (x.optLong("last_used") > 0 ? fmtTime(x.optLong("last_used")) : "从未"));
            int tid = x.optInt("id");
            button(row(c), "吊销", v -> confirm("吊销 Token", "使用此 Token 的程序将立即失效。确定？", () -> Api.del(this, "/tokens/" + tid, y -> refresh())));
        }

        LinearLayout lg = card("审计日志（最近 100 条写操作，保留 180 天）");
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < logs.length(); i++) {
            JSONObject l = logs.optJSONObject(i);
            sb.append(fmtTime(l.optLong("ts"))).append("  ").append(str(l, "actor", "-")).append("  ").append(str(l, "ip", "")).append("\n  ")
                    .append(str(l, "action", "")).append(str(l, "detail", "").isEmpty() ? "" : " · " + l.optString("detail")).append("\n");
        }
        text(lg, sb.length() == 0 ? "暂无" : sb.toString().trim(), 12, false);
    }

    private void totpOn() {
        Api.post(this, "/2fa/setup", null, r -> {
            JSONObject o = Api.obj(r);
            String sec = o.optString("secret");
            form("开启二次验证", "在身份验证器 App 中「手动输入密钥」：\n" + sec + "\n\n输入 App 显示的 6 位验证码完成绑定。",
                    Arrays.asList(Field.num("code", "6 位验证码", "")), "开启",
                    f -> Api.post(this, "/2fa/enable", f, x -> { toast("二次验证已开启"); refresh(); }),
                    "复制密钥", () -> { copy("totp", sec); body.postDelayed(this::totpOn, 300); });
        });
    }

    private void totpOff() {
        form("关闭二次验证", null, Arrays.asList(Field.pass("password", "面板密码"), Field.num("code", "当前验证码", "")), "关闭",
                f -> Api.post(this, "/2fa/disable", f, x -> { toast("已关闭"); refresh(); }));
    }

    private void backup() {
        form("下载加密备份", "备份文件需用备份口令才能恢复，请妥善保存。", Arrays.asList(Field.pass("password", "面板密码"), Field.pass("passphrase", "备份口令（≥10 位，恢复时需要）")), "下载", f -> {
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
        }, r -> toast("备份已保存（" + data.length / 1024 + " KB）"));
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
        }, r -> form("从备份恢复", "⚠️ 当前所有数据将被备份内容覆盖，所有设备需重新登录。", Arrays.asList(Field.pass("passphrase", "备份口令"), Field.pass("password", "当前面板密码")), "恢复", f -> {
            try {
                Api.post(this, "/restore", f.put("file_b64", (String) r), x -> { toast("已恢复，请重新登录"); body.postDelayed(this::toLogin, 1200); });
            } catch (Exception ignored) { }
        }));
    }
}
