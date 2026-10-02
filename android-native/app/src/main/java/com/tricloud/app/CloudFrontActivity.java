package com.tricloud.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import com.tricloud.app.api.Models;
import com.tricloud.app.api.TriCloudApi;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class CloudFrontActivity extends Activity {

    private int accountId;
    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_cloudfront);

        accountId = getIntent().getIntExtra("account_id", 0);
        String accountName = getIntent().getStringExtra("account_name");
        ((TextView) findViewById(R.id.tvTitle)).setText(
                (accountName != null ? accountName : "") + " · CloudFront");

        findViewById(R.id.btnRefresh).setOnClickListener(v -> load());
        load();
    }

    private void load() {
        TriCloudApi api = ApiHolder.api;
        if (api == null) return;
        ListView lv = findViewById(R.id.lvDist);
        List<Models.Distribution> list = new ArrayList<>();
        CfAdapter adapter = new CfAdapter(list);
        lv.setAdapter(adapter);

        bg.execute(() -> {
            try {
                List<Models.Distribution> loaded = api.cloudfront(accountId);
                ui.post(() -> {
                    list.clear();
                    list.addAll(loaded);
                    adapter.notifyDataSetChanged();
                });
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "加载失败";
                ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show());
            }
        });
    }

    private void doInvalidate(Models.Distribution d) {
        new AlertDialog.Builder(this)
                .setTitle("刷新缓存")
                .setMessage("对分发 " + d.id + " 执行全站缓存刷新（/*）？")
                .setPositiveButton("确认", (x, y) -> bg.execute(() -> {
                    try {
                        ApiHolder.api.cloudfrontInvalidate(accountId, d.id);
                        ui.post(() -> Toast.makeText(this, "刷新任务已提交",
                                Toast.LENGTH_SHORT).show());
                    } catch (Exception e) {
                        String msg = e.getMessage() != null ? e.getMessage() : "操作失败";
                        ui.post(() -> Toast.makeText(this, msg,
                                Toast.LENGTH_SHORT).show());
                    }
                }))
                .setNegativeButton("取消", null)
                .show();
    }

    private void doToggle(Models.Distribution d) {
        String label = d.enabled ? "停用" : "启用";
        new AlertDialog.Builder(this)
                .setTitle("确认" + label)
                .setMessage("对分发 " + d.id + " 执行" + label + "？")
                .setPositiveButton("确认", (x, y) -> bg.execute(() -> {
                    try {
                        ApiHolder.api.cloudfrontToggle(accountId, d.id, !d.enabled);
                        ui.post(() -> {
                            Toast.makeText(this, "已提交", Toast.LENGTH_SHORT).show();
                            load();
                        });
                    } catch (Exception e) {
                        String msg = e.getMessage() != null ? e.getMessage() : "操作失败";
                        ui.post(() -> Toast.makeText(this, msg,
                                Toast.LENGTH_SHORT).show());
                    }
                }))
                .setNegativeButton("取消", null)
                .show();
    }

    private class CfAdapter extends BaseAdapter {
        private final List<Models.Distribution> items;
        private final LayoutInflater inflater;

        CfAdapter(List<Models.Distribution> items) {
            this.items = items;
            this.inflater = LayoutInflater.from(CloudFrontActivity.this);
        }

        @Override public int getCount() { return items.size(); }
        @Override public Object getItem(int p) { return items.get(p); }
        @Override public long getItemId(int p) { return p; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            View v = convertView;
            if (v == null) v = inflater.inflate(R.layout.item_cloudfront, parent, false);
            Models.Distribution d = items.get(position);

            ((TextView) v.findViewById(R.id.tvId)).setText(d.id);
            String comment = d.comment != null && !d.comment.isEmpty()
                    ? d.comment : d.domain;
            ((TextView) v.findViewById(R.id.tvComment)).setText(comment);

            TextView tvStatus = v.findViewById(R.id.tvStatus);
            String st = (d.enabled ? "已启用" : "已停用") + " · " + d.status
                    + " · " + (d.plan != null ? d.plan : "paygo");
            tvStatus.setText(st);
            tvStatus.setTextColor(d.enabled ? 0xFF4CAF50 : 0xFFFF9800);

            v.findViewById(R.id.btnInvalidate).setOnClickListener(
                    b -> doInvalidate(d));
            Button btnToggle = v.findViewById(R.id.btnToggle);
            btnToggle.setText(d.enabled ? "停用" : "启用");
            btnToggle.setOnClickListener(b -> doToggle(d));
            return v;
        }
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
