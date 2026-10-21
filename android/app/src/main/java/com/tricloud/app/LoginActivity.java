package com.tricloud.app;

import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.widget.EditText;
import android.widget.LinearLayout;

import org.json.JSONObject;

/** 登录：填写面板地址（如 https://panel.example.com）与面板密码，换取 Bearer token。 */
public class LoginActivity extends BaseActivity {
    private EditText server, pw, otp;

    @Override
    protected boolean useDrawer() { return false; }

    @Override
    protected void onCreate(Bundle s) {
        super.onCreate(s);
        setTitle(getString(R.string.s0943));
        if (!Api.token().isEmpty() && !Api.server().isEmpty()) {
            startActivity(new Intent(this, MainActivity.class));
            finish();
            return;
        }
        refresh();
    }

    @Override
    protected void refresh() {
        clear();
        LinearLayout c = card("☁️ TriCloud");
        muted(c, getString(R.string.s0944));
        com.google.android.material.textfield.TextInputLayout t1 = inputLayout(getString(R.string.s0945), "https://panel.example.com",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        server = t1.getEditText();
        server.setText(Api.server());
        c.addView(t1);
        com.google.android.material.textfield.TextInputLayout t2 = inputLayout(getString(R.string.s0946), null,
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        pw = t2.getEditText();
        c.addView(t2);
        com.google.android.material.textfield.TextInputLayout t3 = inputLayout(getString(R.string.s0947), getString(R.string.s0948),
                InputType.TYPE_CLASS_NUMBER);
        otp = t3.getEditText();
        c.addView(t3);
        bigButton(getString(R.string.s0949), v -> login());
    }

    private void login() {
        String url = server.getText().toString().trim().replaceAll("/+$", "");
        if (!url.startsWith("http")) { toast(getString(R.string.s0950)); return; }
        Api.save(url, "");
        try {
            JSONObject b = new JSONObject().put("password", pw.getText().toString()).put("client", "app")
                    .put("otp", otp.getText().toString().trim());
            Api.post(this, "/login", b, r -> {
                Api.save(url, Api.obj(r).optString("token"));
                startActivity(new Intent(this, MainActivity.class));
                finish();
            });
        } catch (Exception e) { toast(e.getMessage()); }
    }

    @Override
    public void toLogin() { toast(getString(R.string.s0951)); }
}
