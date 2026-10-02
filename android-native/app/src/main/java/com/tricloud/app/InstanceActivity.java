package com.tricloud.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import com.tricloud.app.api.Models;
import com.tricloud.app.api.TriCloudApi;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class InstanceActivity extends Activity {

    private int accountId;
    private List<Models.InstanceAction> allActions = new ArrayList<>();
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

        loadActions();
        loadInstances();
    }

    private void loadActions() {
        TriCloudApi api = ApiHolder.api;
        if (api == null) return;
        bg.execute(() -> {
            try {
                List<Models.InstanceAction> list = api.actions(accountId);
                ui.post(() -> allActions = list);
            } catch (Exception ignored) {}
        });
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

    /** 点击"更多操作"：弹出该云所有可用操作。 */
    private void showActionPicker(Models.Instance inst) {
        if (allActions.isEmpty()) {
            Toast.makeText(this, "操作列表加载中，请稍候", Toast.LENGTH_SHORT).show();
            return;
        }
        String[] labels = new String[allActions.size()];
        for (int i = 0; i < allActions.size(); i++) {
            Models.InstanceAction a = allActions.get(i);
            labels[i] = a.label + (a.danger ? " ⚠" : "");
        }
        new AlertDialog.Builder(this)
                .setTitle("选择操作 · " + inst.name)
                .setItems(labels, (d, which) -> {
                    Models.InstanceAction a = allActions.get(which);
                    startAction(inst, a);
                })
                .show();
    }

    private void startAction(Models.Instance inst, Models.InstanceAction action) {
        if (action.params != null && !action.params.isEmpty()) {
            showParamDialog(inst, action);
        } else {
            confirmAndRun(inst, action, new HashMap<>());
        }
    }

    /** 需要输入参数的操作：动态生成输入框。 */
    private void showParamDialog(Models.Instance inst, Models.InstanceAction action) {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(48, 24, 48, 0);
        List<EditText> inputs = new ArrayList<>();
        for (Models.ActionParam p : action.params) {
            TextView label = new TextView(this);
            label.setText(p.label);
            label.setTextColor(0xFFE6E9F0);
            layout.addView(label);
            EditText et = new EditText(this);
            et.setHint(p.label);
            et.setTextColor(0xFFE6E9F0);
            et.setHintTextColor(0xFF5A6480);
            if ("number".equals(p.type)) {
                et.setInputType(InputType.TYPE_CLASS_NUMBER);
            }
            layout.addView(et);
            inputs.add(et);
        }
        new AlertDialog.Builder(this)
                .setTitle(action.label + " · " + inst.name)
                .setView(layout)
                .setPositiveButton("确认", (d, w) -> {
                    Map<String, Object> params = new HashMap<>();
                    for (int i = 0; i < action.params.size(); i++) {
                        String v = inputs.get(i).getText().toString().trim();
                        if (!v.isEmpty()) {
                            params.put(action.params.get(i).name, v);
                        }
                    }
                    confirmAndRun(inst, action, params);
                })
                .setNegativeButton("取消", null)
                .show();
    }

    private void confirmAndRun(Models.Instance inst, Models.InstanceAction action,
                               Map<String, Object> params) {
        String msg = "对实例「" + inst.name + "」执行「" + action.label + "」？";
        if (action.danger) {
            msg += "\n\n⚠ 这是危险操作，请再次确认！";
        }
        new AlertDialog.Builder(this)
                .setTitle("确认" + action.label)
                .setMessage(msg)
                .setPositiveButton("确认", (d, w) -> doAction(inst, action.key, params))
                .setNegativeButton("取消", null)
                .show();
    }

    private void doAction(Models.Instance inst, String action,
                          Map<String, Object> params) {
        TriCloudApi api = ApiHolder.api;
        if (api == null) return;
        bg.execute(() -> {
            try {
                api.instanceAction(accountId, inst, action, params);
                ui.post(() -> Toast.makeText(this, "任务已提交，可在任务历史查看",
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

            // 快捷按钮：开机/关机/重启（兼容各云的 key 差异）
            v.findViewById(R.id.btnStart).setOnClickListener(
                    b -> quickAction(inst, "start"));
            v.findViewById(R.id.btnStop).setOnClickListener(
                    b -> quickAction(inst, "stop"));
            v.findViewById(R.id.btnReboot).setOnClickListener(
                    b -> quickAction(inst, "reboot", "restart"));
            v.findViewById(R.id.btnMore).setOnClickListener(
                    b -> showActionPicker(inst));
            return v;
        }

        private void quickAction(Models.Instance inst, String... keys) {
            for (String k : keys) {
                for (Models.InstanceAction a : allActions) {
                    if (a.key.equals(k)) {
                        startAction(inst, a);
                        return;
                    }
                }
            }
            Toast.makeText(InstanceActivity.this, "该云不支持此操作",
                    Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
