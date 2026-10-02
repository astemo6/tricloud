package com.tricloud.app;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.TextView;
import android.widget.Toast;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonElement;
import com.google.gson.JsonParser;
import com.tricloud.app.api.TriCloudApi;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class SubscriptionActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_subscription);

        int accountId = getIntent().getIntExtra("account_id", 0);
        String accountName = getIntent().getStringExtra("account_name");
        ((TextView) findViewById(R.id.tvTitle)).setText(
                (accountName != null ? accountName : "") + " · 订阅信息");

        TextView tvSub = findViewById(R.id.tvSub);
        tvSub.setText("加载中…");

        TriCloudApi api = ApiHolder.api;
        if (api == null) {
            finish();
            return;
        }

        bg.execute(() -> {
            try {
                String raw = api.subscription(accountId);
                String pretty;
                try {
                    JsonElement el = JsonParser.parseString(raw);
                    Gson gson = new GsonBuilder().setPrettyPrinting().create();
                    pretty = gson.toJson(el);
                } catch (Exception e) {
                    pretty = raw;
                }
                String out = pretty;
                ui.post(() -> tvSub.setText(out));
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "加载失败";
                ui.post(() -> {
                    tvSub.setText("");
                    Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
                });
            }
        });
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
