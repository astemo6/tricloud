package com.tricloud.app;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.TextView;
import android.widget.Toast;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.tricloud.app.api.TriCloudApi;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class RecycleActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_recycle);

        TextView tvStats = findViewById(R.id.tvStats);
        TextView tvItems = findViewById(R.id.tvItems);
        tvItems.setText("加载中…");

        TriCloudApi api = ApiHolder.api;
        if (api == null) {
            finish();
            return;
        }

        bg.execute(() -> {
            try {
                String raw = api.recycleBin();
                JsonObject obj = JsonParser.parseString(raw).getAsJsonObject();
                JsonObject stats = obj.has("stats") ? obj.getAsJsonObject("stats") : null;
                JsonArray items = obj.has("items") ? obj.getAsJsonArray("items") : null;

                StringBuilder sbStats = new StringBuilder();
                if (stats != null) {
                    for (String k : new String[]{"total", "total_cost"}) {
                        if (stats.has(k)) {
                            sbStats.append(k).append(": ")
                                    .append(stats.get(k).getAsString()).append("  ");
                        }
                    }
                }

                StringBuilder sbItems = new StringBuilder();
                if (items != null) {
                    for (JsonElement e : items) {
                        JsonObject it = e.getAsJsonObject();
                        sbItems.append("· ")
                                .append(getStr(it, "name"))
                                .append(" (").append(getStr(it, "provider")).append(")")
                                .append("\n  删除时间: ").append(getStr(it, "deleted_at"))
                                .append("\n  存活: ").append(getStr(it, "days"))
                                .append(" 天 · 预估费用: ").append(getStr(it, "cost"))
                                .append("\n\n");
                    }
                }
                if (sbItems.length() == 0) sbItems.append("(空)");

                String sStats = sbStats.toString();
                String sItems = sbItems.toString();
                ui.post(() -> {
                    tvStats.setText(sStats);
                    tvItems.setText(sItems);
                });
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "加载失败";
                ui.post(() -> {
                    tvItems.setText("");
                    Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
                });
            }
        });
    }

    private String getStr(JsonObject o, String k) {
        return o.has(k) && !o.get(k).isJsonNull() ? o.get(k).getAsString() : "-";
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
