package com.tricloud.app;

import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Iterator;
import java.util.Locale;

/** v1.4 任务实时日志：GET /api/tasks/{id}?after=N 轮询，运行中每 2 秒刷新并滚到最底部；可停止 / 删除。 */
public class TaskLogActivity extends BaseActivity {
    private int tid;
    private long last = 0;
    private TextView status, msg, logView, result;
    private ScrollView logScroll;
    private LinearLayout acts;
    private final SpannableStringBuilder logs = new SpannableStringBuilder();
    private final SimpleDateFormat fmt = new SimpleDateFormat("HH:mm:ss", Locale.getDefault());
    private final Runnable tick = this::poll;
    private boolean running = true, built = false;

    @Override
    protected boolean useDrawer() { return false; }

    @Override
    protected void onCreate(Bundle s) {
        super.onCreate(s);
        tid = getIntent().getIntExtra("tid", 0);
        setTitle("任务 #" + tid);
        refresh();
    }

    @Override
    protected void onResume() { super.onResume(); if (built && running) { body.removeCallbacks(tick); poll(); } }

    @Override
    protected void onPause() { super.onPause(); body.removeCallbacks(tick); }

    private void build() {
        clear();
        LinearLayout c = card(null);
        status = text(c, "读取中…", 16, true);
        msg = text(c, "", 13, false);
        logScroll = new ScrollView(this);
        logView = new TextView(this);
        logView.setTypeface(Typeface.MONOSPACE);
        logView.setTextSize(11);
        logView.setTextColor(Color.rgb(0xd7, 0xd9, 0xe0));
        logView.setBackgroundColor(Color.rgb(0x11, 0x13, 0x18));
        logView.setPadding(dp(10), dp(8), dp(10), dp(8));
        logView.setTextIsSelectable(true);
        logScroll.addView(logView);
        c.addView(logScroll, new LinearLayout.LayoutParams(-1, dp(360)));
        result = text(c, "", 12, false);
        acts = row(c);
        built = true;
    }

    @Override
    protected void refresh() {
        body.removeCallbacks(tick);
        last = 0;
        logs.clear();
        build();
        poll();
    }

    private void poll() {
        body.removeCallbacks(tick);
        Api.get(this, "/tasks/" + tid + "?after=" + last, r -> {
            JSONObject t = Api.obj(r);
            running = "running".equals(t.optString("status"));
            String head = str(t, "type_name", t.optString("type")) + " · " + stName(t.optString("status")) + "\n"
                    + str(t, "account_name", "-") + (t.optInt("attempts") > 1 ? " · 已尝试 " + t.optInt("attempts") + " 次" : "");
            status.setText(head);
            msg.setText(str(t, "message", ""));
            JSONArray a = t.optJSONArray("logs");
            for (int i = 0; a != null && i < a.length(); i++) {
                JSONObject l = a.optJSONObject(i);
                int start = logs.length();
                logs.append(fmt.format(new Date(l.optLong("ts") * 1000))).append("  ").append(l.optString("msg")).append("\n");
                int color = colorOf(l.optString("level"));
                if (color != 0) logs.setSpan(new ForegroundColorSpan(color), start, logs.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            }
            if (logs.length() > 60000) logs.delete(0, logs.length() - 50000);
            last = t.optLong("last_log_id", last);
            logView.setText(logs.length() == 0 ? "暂无日志" : logs);
            logScroll.post(() -> logScroll.fullScroll(android.view.View.FOCUS_DOWN));   // 自动滚到最底部
            JSONObject res = t.optJSONObject("result");
            StringBuilder sb = new StringBuilder();
            if (res != null) for (Iterator<String> it = res.keys(); it.hasNext(); ) { String k = it.next(); sb.append(k).append("：").append(res.opt(k)).append("\n"); }
            result.setText(sb.toString().trim());
            acts.removeAllViews();
            if (running) button(acts, "停止任务", v -> confirm("停止任务", "停止任务 #" + tid + "？", () -> Api.post(this, "/tasks/" + tid + "/stop", null, x -> poll())));
            else button(acts, "删除记录", v -> confirm("删除记录", "删除任务 #" + tid + " 及其日志？", () -> Api.del(this, "/tasks/" + tid, x -> finish())));
            button(acts, "刷新", v -> refresh());
            if (running) body.postDelayed(tick, 2000);
        });
    }

    static String stName(String s) {
        switch (s) { case "running": return "运行中"; case "done": return "完成"; case "failed": return "失败"; case "stopped": return "已停止"; case "interrupted": return "已中断（服务重启）"; default: return s; }
    }

    static int colorOf(String level) {
        switch (level) { case "ok": return Color.rgb(0x7e, 0xe2, 0xa0); case "warn": return Color.rgb(0xff, 0xcf, 0x7a); case "error": return Color.rgb(0xff, 0x9e, 0x98); default: return 0; }
    }
}
