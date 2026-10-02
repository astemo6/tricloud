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

public class LightsailActivity extends Activity {

    private int accountId;
    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_lightsail);

        accountId = getIntent().getIntExtra("account_id", 0);
        String accountName = getIntent().getStringExtra("account_name");
        ((TextView) findViewById(R.id.tvTitle)).setText(
                (accountName != null ? accountName : "") + " · Lightsail");

        findViewById(R.id.btnRefresh).setOnClickListener(v -> load());
        load();
    }

    private void load() {
        TriCloudApi api = ApiHolder.api;
        if (api == null) return;
        ListView lv = findViewById(R.id.lvLightsail);
        List<Models.LightsailInstance> list = new ArrayList<>();
        LsAdapter adapter = new LsAdapter(list);
        lv.setAdapter(adapter);
        Toast.makeText(this, "正在扫描各区域…", Toast.LENGTH_SHORT).show();

        bg.execute(() -> {
            try {
                List<Models.LightsailInstance> loaded = api.lightsail(accountId);
                ui.post(() -> {
                    list.clear();
                    list.addAll(loaded);
                    adapter.notifyDataSetChanged();
                    if (loaded.isEmpty()) {
                        Toast.makeText(this, "没有 Lightsail 实例",
                                Toast.LENGTH_SHORT).show();
                    }
                });
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "加载失败";
                ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show());
            }
        });
    }

    private void confirmAction(Models.LightsailInstance inst, String action, String label) {
        new AlertDialog.Builder(this)
                .setTitle("确认" + label)
                .setMessage("对「" + inst.name + "」执行" + label + "？")
                .setPositiveButton("确认", (d, w) -> doAction(inst, action))
                .setNegativeButton("取消", null)
                .show();
    }

    private void doAction(Models.LightsailInstance inst, String action) {
        TriCloudApi api = ApiHolder.api;
        if (api == null) return;
        bg.execute(() -> {
            try {
                api.lightsailAction(accountId, inst.name, action,
                        inst.region != null ? inst.region : "");
                ui.post(() -> Toast.makeText(this, "任务已提交",
                        Toast.LENGTH_SHORT).show());
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "操作失败";
                ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show());
            }
        });
    }

    private void doChangeIp(Models.LightsailInstance inst) {
        new AlertDialog.Builder(this)
                .setTitle("更换 IP")
                .setMessage("更换「" + inst.name + "」的公网 IP？")
                .setPositiveButton("确认", (d, w) -> bg.execute(() -> {
                    try {
                        ApiHolder.api.lightsailChangeIp(accountId, inst.name,
                                inst.region != null ? inst.region : "");
                        ui.post(() -> {
                            Toast.makeText(this, "换 IP 任务已提交",
                                    Toast.LENGTH_SHORT).show();
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

    private class LsAdapter extends BaseAdapter {
        private final List<Models.LightsailInstance> items;
        private final LayoutInflater inflater;

        LsAdapter(List<Models.LightsailInstance> items) {
            this.items = items;
            this.inflater = LayoutInflater.from(LightsailActivity.this);
        }

        @Override public int getCount() { return items.size(); }
        @Override public Object getItem(int p) { return items.get(p); }
        @Override public long getItemId(int p) { return p; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            View v = convertView;
            if (v == null) v = inflater.inflate(R.layout.item_lightsail, parent, false);
            Models.LightsailInstance inst = items.get(position);

            ((TextView) v.findViewById(R.id.tvName)).setText(inst.name);
            String ip = inst.public_ip != null && !inst.public_ip.isEmpty()
                    ? inst.public_ip : "无公网 IP";
            ((TextView) v.findViewById(R.id.tvInfo)).setText(
                    ip + " · " + (inst.region != null ? inst.region : ""));

            TextView tvState = v.findViewById(R.id.tvState);
            tvState.setText("状态：" + inst.state);
            tvState.setTextColor("running".equalsIgnoreCase(inst.state)
                    ? 0xFF4CAF50 : 0xFFFF9800);

            v.findViewById(R.id.btnStart).setOnClickListener(
                    b -> confirmAction(inst, "start", "开机"));
            v.findViewById(R.id.btnStop).setOnClickListener(
                    b -> confirmAction(inst, "stop", "关机"));
            v.findViewById(R.id.btnReboot).setOnClickListener(
                    b -> confirmAction(inst, "reboot", "重启"));
            v.findViewById(R.id.btnChangeIp).setOnClickListener(
                    b -> doChangeIp(inst));
            return v;
        }
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
