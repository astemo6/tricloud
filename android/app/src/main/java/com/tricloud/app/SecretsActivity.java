package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Arrays;

/** 开机密码（同 Web pageSecrets）：面板创建 / 抢机生成的随机密码，查看需验证面板密码。 */
public class SecretsActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s1098)); refresh(); }

    @Override
    protected String navKey() { return "secrets"; }

    @Override
    protected void refresh() {
        Api.get(this, "/secrets", r -> {
            clear();
            muted(card(getString(R.string.s0338)), getString(R.string.s1099));
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card(getString(R.string.s0584)), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject x = a.optJSONObject(i);
                int sid = x.optInt("id");
                LinearLayout c = card(x.optString("name"));
                muted(c, getString(R.string.s1100, str(x, "account_name", "-"), str(x, "username", "-"), fmtTime(x.optLong("created"))));
                LinearLayout row = row(c);
                button(row, getString(R.string.s1101), v -> form(getString(R.string.s1102), null, Arrays.asList(Field.pass("password", getString(R.string.s0946))), getString(R.string.s1101),
                        f -> Api.post(this, "/secrets/" + sid + "/reveal", f, y -> {
                            JSONObject o = Api.obj(y);
                            secretDialog(getString(R.string.s1098), getString(R.string.s1103, x.optString("name"), o.optString("username")), o.optString("password"));
                        })));
                button(row, getString(R.string.s0057), v -> confirm(getString(R.string.s0057), getString(R.string.s1104), () -> Api.del(this, "/secrets/" + sid, y -> refresh())));
            }
        });
    }
}
