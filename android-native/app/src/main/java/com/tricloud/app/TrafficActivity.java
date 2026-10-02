package com.tricloud.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.tricloud.app.api.Models;
import com.tricloud.app.api.TriCloudApi;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Azure 流量控制：超限自动关机。 */
public class TrafficActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    private int accountId;
    private List<Models.Instance> instances = new ArrayList<>();

    private static class Rule {
        int id;
        String name;
        String instanceName;
        String metric;
        int windowHours;
        double limitGb;
        int durationHours;
        boolean enabled;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_traffic);

        accountId = getIntent().getIntExtra("account_id", 0);
        String accountName = getIntent().getStringExtra("account_name");
        ((TextView) findViewById(R.id.tvTitle)).setText(
                (accountName != null ? accountName : "") + " · 流量控制");

        findViewById(R.id.btnAdd).setOnClickListener(v -> showAddDialog());
        loadInstances();
        loadRules();
    }

    private void loadInstances() {
        bg.execute(() -> {
            try {
                List<Models.Instance> list = ApiHolder.api.instances(accountId);
                ui.post(() -> instances = list);
            } catch (Exception ignored) {}
        });
    }

    private void loadRules() {
        ListView lv = findViewById(R.id.lvRules);
        List<Rule> list = new ArrayList<>();
        RuleAdapter adapter = new RuleAdapter(list);
        lv.setAdapter(adapter);
        bg.execute(() -> {
            try {
                String raw = ApiHolder.api.trafficRules(accountId);
                JsonArray arr = JsonParser.parseString(raw).getAsJsonArray();
                List<Rule> loaded = new ArrayList<>();
                for (JsonElement e : arr) {
                    JsonObject o = e.getAsJsonObject();
                    Rule r = new Rule();
                    r.id = o.get("id").getAsInt();
                    r.name = str(o, "name");
                    r.instanceName = str(o, "instance_name");
                    r.metric = str(o, "metric");
                    r.windowHours = o.has("window_hours")
                            ? o.get("window_hours").getAsInt() : 24;
                    r.limitGb = o.has("limit_gb")
                            ? o.get("limit_gb").getAsDouble() : 0;
                    r.durationHours = o.has("duration_hours")
                            ? o.get("duration_hours").getAsInt() : 24;
                    r.enabled = !o.has("enabled") || o.get("enabled").getAsBoolean();
                    loaded.add(r);
                }
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

    private String str(JsonObject o, String k) {
        return o.has(k) && !o.get(k).isJsonNull() ? o.get(k).getAsString() : "";
    }

    private void showAddDialog() {
        if (instances.isEmpty()) {
            Toast.makeText(this, "实例列表加载中，请稍候", Toast.LENGTH_SHORT).show();
            return;
        }
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(48, 24, 48, 0);

        // 实例选择
        TextView lbInst = new TextView(this);
        lbInst.setText("实例");
        lbInst.setTextColor(0xFFE6E9F0);
        layout.addView(lbInst);
        Spinner spInst = new Spinner(this);
        List<String> names = new ArrayList<>();
        for (Models.Instance i : instances) names.add(i.name);
        ArrayAdapter<String> ad = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item, names);
        ad.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spInst.setAdapter(ad);
        layout.addView(spInst);

        EditText etName = addField(layout, "规则名称", false);
        // 方向
        TextView lbMetric = new TextView(this);
        lbMetric.setText("统计方向");
        lbMetric.setTextColor(0xFFE6E9F0);
        layout.addView(lbMetric);
        Spinner spMetric = new Spinner(this);
        ArrayAdapter<String> adM = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item,
                new String[]{"出向 (out)", "入向 (in)", "双向 (both)"});
        adM.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spMetric.setAdapter(adM);
        layout.addView(spMetric);

        EditText etWindow = addField(layout, "统计窗口 (小时)", true, "24");
        EditText etLimit = addField(layout, "流量阈值 (GB)", true, "100");
        EditText etDuration = addField(layout, "关机时长 (小时)", true, "24");

        final String[] metricVals = {"out", "in", "both"};
        new AlertDialog.Builder(this)
                .setTitle("新建流量规则")
                .setView(layout)
                .setPositiveButton("保存", (d, w) -> {
                    int pos = spInst.getSelectedItemPosition();
                    Models.Instance inst = instances.get(pos);
                    String name = etName.getText().toString().trim();
                    if (name.isEmpty()) name = inst.name + " 流量控制";
                    Map<String, Object> rule = new HashMap<>();
                    rule.put("account_id", accountId);
                    rule.put("instance_key", inst.id);
                    rule.put("instance_name", inst.name);
                    rule.put("name", name);
                    rule.put("metric", metricVals[spMetric.getSelectedItemPosition()]);
                    rule.put("window_hours",
                            parseInt(etWindow.getText().toString(), 24));
                    rule.put("limit_gb",
                            parseDouble(etLimit.getText().toString(), 100));
                    rule.put("duration_hours",
                            parseInt(etDuration.getText().toString(), 24));
                    rule.put("enabled", true);
                    rule.put("notify_trigger", true);
                    bg.execute(() -> {
                        try {
                            ApiHolder.api.trafficRuleAdd(rule);
                            ui.post(() -> {
                                Toast.makeText(this, "规则已创建",
                                        Toast.LENGTH_SHORT).show();
                                loadRules();
                            });
                        } catch (Exception e) {
                            String msg = e.getMessage() != null
                                    ? e.getMessage() : "创建失败";
                            ui.post(() -> Toast.makeText(this, msg,
                                    Toast.LENGTH_LONG).show());
                        }
                    });
                })
                .setNegativeButton("取消", null)
                .show();
    }

    private int parseInt(String s, int def) {
        try {
            return Integer.parseInt(s.trim());
        } catch (Exception e) {
            return def;
        }
    }

    private double parseDouble(String s, double def) {
        try {
            return Double.parseDouble(s.trim());
        } catch (Exception e) {
            return def;
        }
    }

    private EditText addField(LinearLayout layout, String label,
                              boolean number, String def) {
        TextView tv = new TextView(this);
        tv.setText(label);
        tv.setTextColor(0xFFE6E9F0);
        tv.setPadding(0, 12, 0, 4);
        layout.addView(tv);
        EditText et = new EditText(this);
        et.setHint(label);
        et.setTextColor(0xFFE6E9F0);
        et.setHintTextColor(0xFF5A6480);
        if (number) et.setInputType(InputType.TYPE_CLASS_NUMBER
                | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        if (def != null) et.setText(def);
        layout.addView(et);
        return et;
    }

    private EditText addField(LinearLayout layout, String label, boolean number) {
        return addField(layout, label, number, null);
    }

    private void deleteRule(Rule r) {
        new AlertDialog.Builder(this)
                .setTitle("删除规则")
                .setMessage("删除「" + r.name + "」？")
                .setPositiveButton("删除", (d, w) -> bg.execute(() -> {
                    try {
                        ApiHolder.api.trafficRuleDelete(r.id);
                        ui.post(() -> {
                            Toast.makeText(this, "已删除", Toast.LENGTH_SHORT).show();
                            loadRules();
                        });
                    } catch (Exception e) {
                        String msg = e.getMessage() != null
                                ? e.getMessage() : "删除失败";
                        ui.post(() -> Toast.makeText(this, msg,
                                Toast.LENGTH_SHORT).show());
                    }
                }))
                .setNegativeButton("取消", null)
                .show();
    }

    private class RuleAdapter extends BaseAdapter {
        private final List<Rule> items;
        private final LayoutInflater inflater;

        RuleAdapter(List<Rule> items) {
            this.items = items;
            this.inflater = LayoutInflater.from(TrafficActivity.this);
        }

        @Override public int getCount() { return items.size(); }
        @Override public Object getItem(int p) { return items.get(p); }
        @Override public long getItemId(int p) { return p; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            View v = convertView;
            if (v == null) v = inflater.inflate(R.layout.item_traffic, parent, false);
            Rule r = items.get(position);
            ((TextView) v.findViewById(R.id.tvName)).setText(r.name
                    + (r.enabled ? "" : " (已禁用)"));
            String metricLabel = "out".equals(r.metric) ? "出向"
                    : "in".equals(r.metric) ? "入向" : "双向";
            ((TextView) v.findViewById(R.id.tvInfo)).setText(
                    r.instanceName + " · " + metricLabel
                            + " · " + r.windowHours + "h 内 " + r.limitGb + "GB"
                            + " → 关机 " + r.durationHours + "h");
            v.findViewById(R.id.btnDelete).setOnClickListener(b -> deleteRule(r));
            return v;
        }
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
