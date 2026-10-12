package com.tricloud.app;

import android.os.Bundle;
import android.widget.EditText;
import android.widget.LinearLayout;

import org.json.JSONObject;

import java.util.Arrays;

/** 设置：Telegram、每日报告、监控间隔、默认创建参数、面板密码、App 配色。 */
public class SettingsActivity extends BaseActivity {
    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("设置"); refresh(); }

    @Override
    protected String navKey() { return "settings"; }

    @Override
    protected void refresh() {
        Api.get(this, "/settings", r -> {
            clear();
            JSONObject s = Api.obj(r);
            LinearLayout tg = card("Telegram");
            muted(tg, "Bot Token：" + (s.optBoolean("tg_token_set") ? "已设置 " + s.optString("tg_token_hint") : "未设置")
                    + "\nChat ID：" + str(s, "tg_chat_id", "-") + "\n每日报告：" + (s.optBoolean("daily_report") ? "开 " + str(s, "report_time", "09:00") : "关")
                    + "\n监控间隔：" + str(s, "monitor_interval", "5") + " 分钟");
            LinearLayout r1 = row(tg);
            button(r1, "修改", v -> form("Telegram 设置", "Token 留空保持不变", Arrays.asList(
                    Field.pass("tg_token", "Bot Token"),
                    Field.text("tg_chat_id", "Chat ID", str(s, "tg_chat_id", "")),
                    Field.check("daily_report", "每日账单报告", s.optBoolean("daily_report")),
                    Field.text("report_time", "报告时间 HH:MM", str(s, "report_time", "09:00")),
                    Field.num("monitor_interval", "监控间隔（分钟）", str(s, "monitor_interval", "5")),
                    Field.text("timezone", "时区", str(s, "timezone", "Asia/Shanghai"))), "保存", vals -> {
                if (vals.optString("tg_token").isEmpty()) vals.remove("tg_token");
                Api.post(this, "/settings", vals, x -> { toast("已保存"); refresh(); });
            }));
            button(r1, "发送测试", v -> Api.post(this, "/settings/tg-test", null, x -> toast("测试消息已发送")));

            LinearLayout cf = card("Cloudflare");
            muted(cf, "用于换 IP 后自动更新 DNS（DNS 联动）。建议创建仅含「Zone.DNS 编辑」权限、限定域名的 API Token。\nAPI Token：" + (s.optBoolean("cf_token_set") ? "已设置" : "未设置"));
            LinearLayout rcf = row(cf);
            button(rcf, s.optBoolean("cf_token_set") ? "更换 Token" : "设置 Token", v -> form("Cloudflare API Token", null, Arrays.asList(Field.pass("cf_token", "API Token")), "保存", vals -> {
                if (vals.optString("cf_token").isEmpty()) { toast("请输入 Token"); return; }
                Api.post(this, "/settings", vals, x -> { toast("已保存"); refresh(); });
            }));
            if (s.optBoolean("cf_token_set")) button(rcf, "清除", v -> confirm("清除 Cloudflare Token", "清除后换 IP 不再自动更新 DNS。", () -> {
                try { Api.post(this, "/settings", new JSONObject().put("cf_token_clear", true), x -> { toast("已清除"); refresh(); }); } catch (Exception ignored) { }
            }));

            LinearLayout pc = card("IP 质量检测");
            muted(pc, "风险分来自 proxycheck.io：不填 Key 每天 100 次，免费注册的 Key 每天 1000 次。只发送要检测的公网 IP。\nKey：" + (s.optBoolean("proxycheck_key_set") ? "已设置" : "未设置"));
            LinearLayout rpc = row(pc);
            button(rpc, s.optBoolean("proxycheck_key_set") ? "更换 Key" : "设置 Key", v -> form("proxycheck.io Key", null, Arrays.asList(Field.pass("proxycheck_key", "Key")), "保存", vals -> {
                if (vals.optString("proxycheck_key").isEmpty()) { toast("请输入 Key"); return; }
                Api.post(this, "/settings", vals, x -> { toast("已保存"); refresh(); });
            }));
            if (s.optBoolean("proxycheck_key_set")) button(rpc, "清除", v -> {
                try { Api.post(this, "/settings", new JSONObject().put("proxycheck_key_clear", true), x -> { toast("已清除"); refresh(); }); } catch (Exception ignored) { }
            });

            LinearLayout dc = card("默认创建参数（JSON）");
            EditText e = new EditText(this);
            JSONObject d = s.optJSONObject("default_create");
            try { e.setText(d == null ? "{\n  \"oci\": {\"shape\": \"VM.Standard.A1.Flex\", \"ocpus\": 4, \"memory_gb\": 24, \"disk_gb\": 50, \"os\": \"Canonical Ubuntu\", \"os_version\": \"22.04\", \"ssh_key\": \"\"},\n  \"lightsail\": {\"blueprint\": \"debian_12\", \"bundle\": \"nano_3_0\"}\n}" : d.toString(2)); }
            catch (Exception ignored) { }
            e.setTextSize(12);
            e.setTypeface(android.graphics.Typeface.MONOSPACE);
            muted(dc, "OCI 创建 / 抢机、Lightsail、EC2、Azure 创建表单的默认值。");
            dc.addView(e);
            LinearLayout r2 = row(dc);
            button(r2, "保存", v -> {
                try { Api.post(this, "/settings", new JSONObject().put("default_create", new JSONObject(e.getText().toString())), x -> toast("已保存")); }
                catch (Exception ex) { toast("JSON 格式错误"); }
            });

            LinearLayout fg = card("免费额度护栏");
            boolean on = !s.has("free_guard") || s.isNull("free_guard") || s.optBoolean("free_guard", true);
            muted(fg, "创建、改配置、扩容前估算是否超出免费额度，超出时二次确认。当前：" + (on ? "开" : "关"));
            button(row(fg), on ? "关闭护栏" : "开启护栏", v -> {
                try { Api.post(this, "/settings", new JSONObject().put("free_guard", !on), x -> refresh()); } catch (Exception ignored) { }
            });

            LinearLayout ai = card("自动换 IP 每日上限");
            muted(ai, "IP 不通触发的自动换 IP，每账号每天最多 " + s.optInt("auto_ip_daily_limit", 3) + " 次；达到上限或失败只推送 Telegram 告警。");
            button(row(ai), "修改", v -> form("自动换 IP 每日上限", "0 = 不自动换（0~50）", Arrays.asList(
                    Field.num("auto_ip_daily_limit", "每账号每天次数", String.valueOf(s.optInt("auto_ip_daily_limit", 3)))), "保存", vals -> {
                try { Api.post(this, "/settings", new JSONObject().put("auto_ip_daily_limit", Integer.parseInt(vals.optString("auto_ip_daily_limit", "3"))), x -> refresh()); }
                catch (Exception ex) { toast("请输入整数"); }
            }));

            LinearLayout pw = card("面板密码");
            muted(pw, "修改后所有设备需要重新登录。登录连续失败 5 次将锁定该 IP 15 分钟。");
            LinearLayout r3 = row(pw);
            button(r3, "修改密码", v -> form("修改面板密码", "修改后所有设备需重新登录", Arrays.asList(
                    Field.pass("old", "原密码"), Field.pass("new", "新密码（≥10 位）")), "修改",
                    vals -> Api.post(this, "/password", vals, x -> { toast("已修改"); toLogin(); })));

            LinearLayout th = card("配色");
            LinearLayout r4 = row(th);
            String cur = Api.pref("theme", "system");
            for (String[] m : new String[][]{{"system", "跟随系统"}, {"light", "浅色"}, {"dark", "深色"}})
                button(r4, (m[0].equals(cur) ? "● " : "") + m[1], v -> { Api.setPref("theme", m[0]); applyTheme(); recreate(); });
            muted(card("服务器"), Api.server());
        });
    }
}
