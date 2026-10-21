package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** 脚本模板（同 Web pageScripts）：创建实例时可选用，以 root 在首次开机执行。 */
public class ScriptsActivity extends BaseActivity {
    static final String[][] PRESETS = {
            {L10n.s(R.string.s1086), "#!/bin/bash\necho 'net.core.default_qdisc=fq' >> /etc/sysctl.conf\necho 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.conf\nsysctl -p"},
            {"2GB Swap", "#!/bin/bash\nfallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile\necho '/swapfile none swap sw 0 0' >> /etc/fstab"},
            {"关闭 OCI 系统防火墙", "#!/bin/bash\niptables -P INPUT ACCEPT; iptables -P FORWARD ACCEPT; iptables -P OUTPUT ACCEPT; iptables -F\nnetfilter-persistent save 2>/dev/null || true\nsystemctl disable --now firewalld 2>/dev/null || true"},
            {"时区上海 + 常用工具", "#!/bin/bash\ntimedatectl set-timezone Asia/Shanghai\n(apt-get update && apt-get install -y curl wget unzip htop) || (dnf install -y curl wget unzip htop)"}};

    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s1087)); refresh(); }

    @Override
    protected String navKey() { return "scripts"; }

    @Override
    protected void refresh() {
        Api.get(this, "/scripts", r -> {
            clear();
            muted(card(getString(R.string.s0338)), getString(R.string.s1088));
            bigButton(getString(R.string.s1089), v -> {
                String[] labels = new String[PRESETS.length + 1];
                labels[0] = getString(R.string.s1090);
                for (int i = 0; i < PRESETS.length; i++) labels[i + 1] = PRESETS[i][0];
                choose(getString(R.string.s1091), labels, i -> edit(null, i == 0 ? "" : PRESETS[i - 1][0], i == 0 ? "#!/bin/bash\n" : PRESETS[i - 1][1]));
            });
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card(getString(R.string.s1092)), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject x = a.optJSONObject(i);
                LinearLayout c = card(x.optString("name"));
                String ct = x.optString("content");
                TextView t = text(c, ct.length() > 300 ? ct.substring(0, 300) + "…" : ct, 12, false);
                t.setTypeface(android.graphics.Typeface.MONOSPACE);
                LinearLayout row = row(c);
                button(row, getString(R.string.s0211), v -> edit(x, x.optString("name"), ct));
                button(row, getString(R.string.s0057), v -> confirm(getString(R.string.s1093), getString(R.string.s1094, x.optString("name")), () -> Api.del(this, "/scripts/" + x.optInt("id"), y -> { toast(getString(R.string.s0223)); refresh(); })));
            }
        });
    }

    private void edit(JSONObject x, String name, String content) {
        List<Field> f = new ArrayList<>(Arrays.asList(Field.text("name", getString(R.string.s0135), name), Field.multi("content", getString(R.string.s1095), content)));
        form(x == null ? getString(R.string.s1096) : getString(R.string.s1097), null, f, getString(R.string.s0089), v -> {
            try {
                if (x != null) v.put("id", x.optInt("id"));
                Api.post(this, "/scripts", v, y -> { toast(getString(R.string.s0777)); refresh(); });
            } catch (Exception ignored) { }
        });
    }
}
