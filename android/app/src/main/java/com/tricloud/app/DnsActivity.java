package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/** Cloudflare DNS 联动（同 Web pageDns）：绑定列表与解绑；在实例卡片上点「绑定域名」添加。 */
public class DnsActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("DNS 联动"); refresh(); }

    @Override
    protected String navKey() { return "dns"; }

    @Override
    protected void refresh() {
        Api.get(this, "/dns-bindings", r -> {
            clear();
            muted(card("说明"), "绑定后，换 IP / 分配 IPv6 会自动更新对应的 Cloudflare 记录。在实例卡片上点「绑定域名」添加；Token 在「设置 → Cloudflare」配置。");
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card("暂无绑定"), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject d = a.optJSONObject(i);
                LinearLayout c = card(d.optString("record"));
                muted(c, "实例：" + str(d, "name", "-") + "\n账号：" + str(d, "account_name", "-") + "\n类型：" + (d.optInt("v4") == 1 || d.optBoolean("v4") ? "A " : "")
                        + (d.optInt("v6") == 1 || d.optBoolean("v6") ? "AAAA " : "") + (d.optInt("proxied") == 1 || d.optBoolean("proxied") ? "· 代理（橙色云）" : ""));
                int bid = d.optInt("id");
                button(row(c), "解绑", v -> confirm("解绑域名", "解绑后换 IP 不再自动更新这条解析（Cloudflare 上的记录保留）。确定？",
                        () -> Api.del(this, "/dns-bindings/" + bid, y -> { toast("已解绑"); refresh(); })));
            }
        });
    }
}
