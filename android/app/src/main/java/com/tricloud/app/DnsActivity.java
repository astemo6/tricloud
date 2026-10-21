package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** Cloudflare DNS 联动（同 Web pageDns）：绑定列表与解绑；在实例卡片上点「绑定域名」添加。 */
public class DnsActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s0856)); refresh(); }

    @Override
    protected String navKey() { return "dns"; }

    @Override
    protected void refresh() {
        Api.get(this, "/dns-bindings", r -> {
            clear();
            muted(card(getString(R.string.s0338)), getString(R.string.s0857));
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card(getString(R.string.s0858)), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject d = a.optJSONObject(i);
                LinearLayout c = card(d.optString("record"));
                muted(c, getString(R.string.s0860, str(d, "name", "-"), str(d, "account_name", "-"), (d.optInt("v4") == 1 || d.optBoolean("v4") ? "A " : ""), (d.optInt("v6") == 1 || d.optBoolean("v6") ? "AAAA " : ""), (d.optInt("proxied") == 1 || d.optBoolean("proxied") ? getString(R.string.s0859) : "")));
                int bid = d.optInt("id");
                button(row(c), getString(R.string.s0861), v -> confirm(getString(R.string.s0862), getString(R.string.s0863),
                        () -> Api.del(this, "/dns-bindings/" + bid, y -> { toast(getString(R.string.s0540)); refresh(); })));
            }
        });
    }
}
