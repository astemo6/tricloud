package com.tricloud.app;

import android.os.Bundle;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** 任务列表：抢机 / 换 IP / 改配置等，可查看实时日志、停止运行中的任务。 */
public class TasksActivity extends BaseActivity {
    private final Runnable tick = this::refresh;

    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("任务"); refresh(); }

    @Override
    protected void onPause() { super.onPause(); body.removeCallbacks(tick); }

    static String tn(String t) {
        switch (t) {
            case "snatch": return "抢机"; case "change_ip": return "换 IP"; case "resize": return "改配置"; case "ipv6": return "IPv6";
            case "azure_create": return "创建 VM"; case "ensure_network": return "自动建网"; case "snapshot": return "快照（已移除）"; case "migrate": return "迁移"; case "cf_delete": return "删除 CDN 分发";
            default: return t;
        }
    }

    static String st(String s) {
        switch (s) {
            case "running": return "运行中"; case "done": return "完成"; case "failed": return "失败"; case "stopped": return "已停止"; case "interrupted": return "已中断";
            default: return s;
        }
    }

    @Override
    protected String navKey() { return "tasks"; }

    @Override
    protected void refresh() {
        body.removeCallbacks(tick);
        Api.get(this, "/tasks", r -> {
            clear();
            JSONArray a = Api.arr(r);
            muted(card(null), "任务完成 / 失败 / 停止会自动推送 Telegram；本页每 10 秒自动刷新。");
            if (a.length() == 0) muted(card("暂无任务"), "");
            SimpleDateFormat f = new SimpleDateFormat("MM-dd HH:mm:ss", Locale.getDefault());
            for (int i = 0; i < a.length(); i++) {
                JSONObject t = a.optJSONObject(i);
                LinearLayout c = card("#" + t.optInt("id") + " " + tn(t.optString("type")) + "  [" + st(t.optString("status")) + "]");
                text(c, str(t, "account_name", "-") + " · 尝试 " + t.optInt("attempts") + " 次\n" + str(t, "message", ""), 13, false);
                muted(c, "更新于 " + f.format(new Date(t.optLong("updated") * 1000)));
                LinearLayout row = row(c);
                int tid = t.optInt("id");
                button(row, "日志", v -> openTask(tid));
                if ("running".equals(t.optString("status")))
                    button(row, "停止", v -> confirm("停止任务", "#" + tid, () -> Api.post(this, "/tasks/" + tid + "/stop", null, x -> refresh())));
                else button(row, "删除", v -> Api.del(this, "/tasks/" + tid, x -> refresh()));
            }
            body.postDelayed(tick, 10000);
        });
    }
}
