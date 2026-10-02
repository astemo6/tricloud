package com.tricloud.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
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

public class InstanceActivity extends Activity {

    private int accountId;
    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_instance);

        accountId = getIntent().getIntExtra("account_id", 0);
        String accountName = getIntent().getStringExtra("account_name");

        ((TextView) findViewById(R.id.tvTitle)).setText(
                accountName != null ? accountName : "实例");
        findViewById(R.id.btnBilling).setOnClickListener(v -> {
            Intent i = new Intent(this, BillingActivity.class);
            i.putExtra("account_id", accountId);
            i.putExtra("account_name", accountName);
            startActivity(i);
        });

        loadInstances();
    }

    private void loadInstances() {
        TriCloudApi api = ApiHolder.api;
        if (api == null) return;
        ListView lv = findViewById(R.id.lvInstances);
        List<Models.Instance> list = new ArrayList<>();
        InstanceAdapter adapter = new InstanceAdapter(list);
        lv.setAdapter(adapter);

        bg.execute(() -> {
            try {
                List<Models.Instance> loaded = api.instances(accountId);
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

    private void confirmAction(Models.Instance inst, String action, String label) {
        new AlertDialog.Builder(this)
                .setTitle("确认" + label)
                .setMessage("对实例「" + inst.name + "」执行" + label + "？")
                .setPositiveButton("确认", (d, w) -> doAction(inst, action))
                .setNegativeButton("取消", null)
                .show();
    }

    private void doAction(Models.Instance inst, String action) {
        TriCloudApi api = ApiHolder.api;
        if (api == null) return;
        bg.execute(() -> {
            try {
                api.instanceAction(accountId, inst, action);
                ui.post(() -> Toast.makeText(this, "任务已提交",
                        Toast.LENGTH_SHORT).show());
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "操作失败";
                ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show());
            }
        });
    }

    private class InstanceAdapter extends BaseAdapter {
        private final List<Models.Instance> items;
        private final LayoutInflater inflater;

        InstanceAdapter(List<Models.Instance> items) {
            this.items = items;
            this.inflater = LayoutInflater.from(InstanceActivity.this);
        }

        @Override public int getCount() { return items.size(); }
        @Override public Object getItem(int p) { return items.get(p); }
        @Override public long getItemId(int p) { return p; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            View v = convertView;
            if (v == null) v = inflater.inflate(R.layout.item_instance, parent, false);
            Models.Instance inst = items.get(position);

            ((TextView) v.findViewById(R.id.tvName)).setText(inst.name);
            String ip = inst.public_ip != null ? inst.public_ip
                    : (inst.private_ip != null ? inst.private_ip : "无 IP");
            String info = ip;
            if (inst.region != null) info += " · " + inst.region;
            if (inst.shape != null) info += " " + inst.shape;
            ((TextView) v.findViewById(R.id.tvInfo)).setText(info);

            TextView tvStatus = v.findViewById(R.id.tvStatus);
            tvStatus.setText("状态：" + inst.status);
            tvStatus.setTextColor(inst.status != null
                    && inst.status.toUpperCase().contains("RUN")
                    ? 0xFF4CAF50 : 0xFFFF9800);

            v.findViewById(R.id.btnStart).setOnClickListener(
                    b -> confirmAction(inst, "start", "开机"));
            v.findViewById(R.id.btnStop).setOnClickListener(
                    b -> confirmAction(inst, "stop", "关机"));
            v.findViewById(R.id.btnReboot).setOnClickListener(
                    b -> confirmAction(inst, "reboot", "重启"));
            return v;
        }
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
