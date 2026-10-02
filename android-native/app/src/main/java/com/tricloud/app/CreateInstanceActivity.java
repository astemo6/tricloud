package com.tricloud.app;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.tricloud.app.api.TriCloudApi;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** 创建实例：根据后端 create-options 动态生成表单。 */
public class CreateInstanceActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    private int accountId;
    private String provider;
    private final Map<String, View> inputs = new HashMap<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_create);

        accountId = getIntent().getIntExtra("account_id", 0);
        provider = getIntent().getStringExtra("provider");
        String accountName = getIntent().getStringExtra("account_name");
        ((TextView) findViewById(R.id.tvTitle)).setText(
                "创建实例 · " + (accountName != null ? accountName : ""));

        loadOptions();
    }

    private void loadOptions() {
        LinearLayout form = findViewById(R.id.llForm);
        TextView tvLoading = findViewById(R.id.tvLoading);
        bg.execute(() -> {
            try {
                String raw = ApiHolder.api.createOptions(accountId);
                JsonObject opts = JsonParser.parseString(raw).getAsJsonObject();
                ui.post(() -> {
                    tvLoading.setVisibility(View.GONE);
                    buildForm(form, opts);
                });
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "加载失败";
                ui.post(() -> {
                    tvLoading.setText(msg);
                    Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
                });
            }
        });
    }

    private void buildForm(LinearLayout form, JsonObject opts) {
        form.removeAllViews();
        inputs.clear();

        if ("oci".equals(provider)) {
            addText(form, "name", "实例名（可选，留空自动生成）", false);
            addSpinner(form, "availability_domain", "可用域",
                    strList(opts, "availability_domains"), null);
            addSpinner(form, "shape", "规格", strList(opts, "shapes"), "E2.1.Micro");
            addText(form, "ocpus", "OCPU（仅 Flex）", true, "1");
            addText(form, "memory_gbs", "内存 GB（仅 Flex）", true, "6");
            addSpinner(form, "os", "操作系统", strList(opts, "os_options"), null);
            addText(form, "boot_volume_gb", "引导卷 GB", true, "50");
            addText(form, "ssh_key", "SSH 公钥（可选）", false);
            addText(form, "login_user", "登录用户", false, "ubuntu");
            addText(form, "password", "密码（可选，留空自动生成）", false);
            addCheck(form, "assign_public_ip", "分配公网 IP", true);
        } else if ("aws".equals(provider)) {
            addText(form, "name", "实例名（Name 标签，可选）", false);
            addSpinner(form, "region", "区域", strList(opts, "regions"),
                    getStr(opts, "default_region"));
            addSpinner(form, "instance_type", "实例类型",
                    strList(opts, "instance_types"), "t2.micro");
            List<String> keys = new ArrayList<>();
            keys.add("（自动创建新密钥对）");
            keys.addAll(strList(opts, "key_pairs"));
            addSpinner(form, "key_name", "密钥对", keys, null);
            addText(form, "ami", "AMI（可选，留空自动用 Ubuntu 22.04）", false);
        } else if ("azure".equals(provider)) {
            addText(form, "name", "虚拟机名（可选）", false);
            addText(form, "resource_group", "资源组（可选，留空自动创建）", false);
            addSpinner(form, "location", "区域", strList(opts, "locations"), "japaneast");
            addSpinner(form, "vm_size", "规格", strList(opts, "vm_sizes"), "Standard_B1s");
            addSpinner(form, "image", "镜像", strList(opts, "images"), null);
            addText(form, "disk_gb", "系统盘 GB", true, "30");
            addText(form, "admin_username", "管理员用户", false, "azureuser");
            addText(form, "password", "密码（可选，留空自动生成）", false);
            addText(form, "ssh_key", "SSH 公钥（可选）", false);
        }

        Button btn = new Button(this);
        btn.setText("提交创建（后台执行）");
        btn.setOnClickListener(v -> submit());
        form.addView(btn);
    }

    private void submit() {
        Map<String, Object> params = new HashMap<>();
        for (Map.Entry<String, View> e : inputs.entrySet()) {
            View v = e.getValue();
            if (v instanceof EditText) {
                String val = ((EditText) v).getText().toString().trim();
                if (!val.isEmpty()) params.put(e.getKey(), val);
            } else if (v instanceof Spinner) {
                Object sel = ((Spinner) v).getSelectedItem();
                if (sel != null) {
                    String val = sel.toString();
                    if (val.startsWith("（自动")) continue;
                    params.put(e.getKey(), val);
                }
            } else if (v instanceof CheckBox) {
                params.put(e.getKey(), ((CheckBox) v).isChecked());
            }
        }
        bg.execute(() -> {
            try {
                ApiHolder.api.createInstance(accountId, params);
                ui.post(() -> {
                    Toast.makeText(this, "创建任务已提交，可在任务历史查看",
                            Toast.LENGTH_SHORT).show();
                    finish();
                });
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "提交失败";
                ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
            }
        });
    }

    // ---------- 表单组件 ----------

    private void addLabel(LinearLayout form, String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextColor(0xFF8B93AD);
        tv.setTextSize(13);
        tv.setPadding(0, 12, 0, 4);
        form.addView(tv);
    }

    private void addText(LinearLayout form, String key, String label,
                         boolean number) {
        addText(form, key, label, number, null);
    }

    private void addText(LinearLayout form, String key, String label,
                         boolean number, String def) {
        addLabel(form, label);
        EditText et = new EditText(this);
        et.setHint(label);
        et.setTextColor(0xFFE6E9F0);
        et.setHintTextColor(0xFF5A6480);
        if (number) et.setInputType(InputType.TYPE_CLASS_NUMBER);
        if (def != null) et.setText(def);
        form.addView(et);
        inputs.put(key, et);
    }

    private void addSpinner(LinearLayout form, String key, String label,
                            List<String> options, String def) {
        addLabel(form, label);
        Spinner sp = new Spinner(this);
        ArrayAdapter<String> ad = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item, options);
        ad.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        sp.setAdapter(ad);
        if (def != null) {
            int idx = -1;
            for (int i = 0; i < options.size(); i++) {
                if (options.get(i).contains(def)) { idx = i; break; }
            }
            if (idx >= 0) sp.setSelection(idx);
        }
        form.addView(sp);
        inputs.put(key, sp);
    }

    private void addCheck(LinearLayout form, String key, String label, boolean def) {
        CheckBox cb = new CheckBox(this);
        cb.setText(label);
        cb.setTextColor(0xFFE6E9F0);
        cb.setChecked(def);
        cb.setPadding(0, 12, 0, 4);
        form.addView(cb);
        inputs.put(key, cb);
    }

    private List<String> strList(JsonObject o, String key) {
        List<String> out = new ArrayList<>();
        if (o.has(key) && o.get(key).isJsonArray()) {
            for (JsonElement e : o.getAsJsonArray(key)) {
                out.add(e.getAsString());
            }
        }
        return out;
    }

    private String getStr(JsonObject o, String key) {
        return o.has(key) && !o.get(key).isJsonNull()
                ? o.get(key).getAsString() : null;
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
