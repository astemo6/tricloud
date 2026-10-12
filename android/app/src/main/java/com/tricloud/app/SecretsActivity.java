package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Arrays;

/** 开机密码（同 Web pageSecrets）：面板创建 / 抢机生成的随机密码，查看需验证面板密码。 */
public class SecretsActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("开机密码"); refresh(); }

    @Override
    protected String navKey() { return "secrets"; }

    @Override
    protected void refresh() {
        Api.get(this, "/secrets", r -> {
            clear();
            muted(card("说明"), "面板创建 / 抢机 / 重装生成的随机密码，经 Fernet 加密保存。查看需要输入面板密码。");
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card("暂无"), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject x = a.optJSONObject(i);
                int sid = x.optInt("id");
                LinearLayout c = card(x.optString("name"));
                muted(c, "账号：" + str(x, "account_name", "-") + "\n用户：" + str(x, "username", "-") + "\n创建于 " + fmtTime(x.optLong("created")));
                LinearLayout row = row(c);
                button(row, "查看", v -> form("验证面板密码", null, Arrays.asList(Field.pass("password", "面板密码")), "查看",
                        f -> Api.post(this, "/secrets/" + sid + "/reveal", f, y -> {
                            JSONObject o = Api.obj(y);
                            secretDialog("开机密码", "实例：" + x.optString("name") + "\n用户：" + o.optString("username"), o.optString("password"));
                        })));
                button(row, "删除", v -> confirm("删除", "删除后无法再找回此密码。确定？", () -> Api.del(this, "/secrets/" + sid, y -> refresh())));
            }
        });
    }
}
