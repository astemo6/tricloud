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
            {"开启 BBR", "#!/bin/bash\necho 'net.core.default_qdisc=fq' >> /etc/sysctl.conf\necho 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.conf\nsysctl -p"},
            {"2GB Swap", "#!/bin/bash\nfallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile\necho '/swapfile none swap sw 0 0' >> /etc/fstab"},
            {"关闭 OCI 系统防火墙", "#!/bin/bash\niptables -P INPUT ACCEPT; iptables -P FORWARD ACCEPT; iptables -P OUTPUT ACCEPT; iptables -F\nnetfilter-persistent save 2>/dev/null || true\nsystemctl disable --now firewalld 2>/dev/null || true"},
            {"时区上海 + 常用工具", "#!/bin/bash\ntimedatectl set-timezone Asia/Shanghai\n(apt-get update && apt-get install -y curl wget unzip htop) || (dnf install -y curl wget unzip htop)"}};

    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("脚本模板"); refresh(); }

    @Override
    protected String navKey() { return "scripts"; }

    @Override
    protected void refresh() {
        Api.get(this, "/scripts", r -> {
            clear();
            muted(card("说明"), "创建 EC2 / Lightsail / OCI / Azure 实例时可选用，以 root 在首次开机执行（日志在 /root/tricloud-init.log）。不建议在脚本中 curl | bash 来源不明的远程脚本。");
            bigButton("＋ 新建模板", v -> {
                String[] labels = new String[PRESETS.length + 1];
                labels[0] = "空白";
                for (int i = 0; i < PRESETS.length; i++) labels[i + 1] = PRESETS[i][0];
                choose("从预设开始", labels, i -> edit(null, i == 0 ? "" : PRESETS[i - 1][0], i == 0 ? "#!/bin/bash\n" : PRESETS[i - 1][1]));
            });
            JSONArray a = Api.arr(r);
            if (a.length() == 0) muted(card("暂无模板"), "");
            for (int i = 0; i < a.length(); i++) {
                JSONObject x = a.optJSONObject(i);
                LinearLayout c = card(x.optString("name"));
                String ct = x.optString("content");
                TextView t = text(c, ct.length() > 300 ? ct.substring(0, 300) + "…" : ct, 12, false);
                t.setTypeface(android.graphics.Typeface.MONOSPACE);
                LinearLayout row = row(c);
                button(row, "编辑", v -> edit(x, x.optString("name"), ct));
                button(row, "删除", v -> confirm("删除模板", "确定删除「" + x.optString("name") + "」？", () -> Api.del(this, "/scripts/" + x.optInt("id"), y -> { toast("已删除"); refresh(); })));
            }
        });
    }

    private void edit(JSONObject x, String name, String content) {
        List<Field> f = new ArrayList<>(Arrays.asList(Field.text("name", "名称", name), Field.multi("content", "脚本", content)));
        form(x == null ? "新建模板" : "编辑模板", null, f, "保存", v -> {
            try {
                if (x != null) v.put("id", x.optInt("id"));
                Api.post(this, "/scripts", v, y -> { toast("已保存"); refresh(); });
            } catch (Exception ignored) { }
        });
    }
}
