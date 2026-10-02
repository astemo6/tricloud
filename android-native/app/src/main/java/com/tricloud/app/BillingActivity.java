package com.tricloud.app;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import com.tricloud.app.api.Models;
import com.tricloud.app.api.TriCloudApi;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class BillingActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_billing);

        int accountId = getIntent().getIntExtra("account_id", 0);
        String accountName = getIntent().getStringExtra("account_name");
        ((TextView) findViewById(R.id.tvTitle)).setText(
                (accountName != null ? accountName : "") + " 账单");

        TriCloudApi api = ApiHolder.api;
        if (api == null) {
            finish();
            return;
        }

        bg.execute(() -> {
            try {
                Models.Billing b = api.billing(accountId);
                ui.post(() -> {
                    String currency = b.currency != null ? b.currency : "USD";
                    ((TextView) findViewById(R.id.tvTotal)).setText(
                            String.format("%.2f %s", b.total, currency));
                    ((TextView) findViewById(R.id.tvPeriod)).setText(
                            b.period != null ? b.period : "");
                    LinearLayout ll = findViewById(R.id.llServices);
                    if (b.services != null) {
                        for (Models.BillingService s : b.services) {
                            TextView row = new TextView(this);
                            row.setText(String.format("%-30s %.2f", s.name, s.cost));
                            row.setTextColor(0xFFE6E9F0);
                            row.setTextSize(14);
                            row.setPadding(0, 8, 0, 8);
                            ll.addView(row);
                        }
                    }
                });
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "加载失败";
                ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show());
            }
        });
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
