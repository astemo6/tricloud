package com.tricloud.app;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ScrollView;
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

/** 批量添加账号：每行 "别名 | 字段1 | 字段2 | ..." */
public class BatchAddActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    private String currentProvider = "aws";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_batch_add);

        Spinner spProvider = findViewById(R.id.spProvider);
        EditText etInput = findViewById(R.id.etInput);
        TextView tvFormat = findViewById(R.id.tvFormat);
        TextView tvResult = findViewById(R.id.tvResult);
        Button btnSubmit = findViewById(R.id.btnSubmit);

        String[] providers = {"aws", "azure", "oci"};
        String[] labels = {"AWS", "Azure", "Oracle Cloud"};
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item, labels);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spProvider.setAdapter(adapter);
        spProvider.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> p, View v, int pos, long id) {
                currentProvider = providers[pos];
                tvFormat.setText(formatHint());
            }
            @Override public void onNothingSelected(AdapterView<?> p) {}
        });
        tvFormat.setText(formatHint());

        btnSubmit.setOnClickListener(v -> {
            String text = etInput.getText().toString().trim();
            if (text.isEmpty()) {
                Toast.makeText(this, "请输入账号信息", Toast.LENGTH_SHORT).show();
                return;
            }
            List<Map<String, Object>> accounts = parse(text);
            if (accounts.isEmpty()) {
                Toast.makeText(this, "格式错误，请检查", Toast.LENGTH_SHORT).show();
                return;
            }
            btnSubmit.setEnabled(false);
            tvResult.setText("提交中…");
            bg.execute(() -> {
                try {
                    String raw = ApiHolder.api.batchAddAccounts(
                            currentProvider, accounts);
                    JsonObject obj = JsonParser.parseString(raw).getAsJsonObject();
                    String summary = obj.has("summary")
                            ? obj.get("summary").getAsString() : "";
                    StringBuilder sb = new StringBuilder(summary).append("\n\n");
                    if (obj.has("results")) {
                        for (JsonElement e : obj.getAsJsonArray("results")) {
                            JsonObject r = e.getAsJsonObject();
                            String name = r.has("name")
                                    ? r.get("name").getAsString() : "?";
                            boolean ok = r.has("ok") && r.get("ok").getAsBoolean();
                            sb.append(ok ? "✓ " : "✗ ").append(name);
                            if (!ok && r.has("error")) {
                                sb.append(": ").append(r.get("error").getAsString());
                            }
                            sb.append("\n");
                        }
                    }
                    String out = sb.toString();
                    ui.post(() -> {
                        tvResult.setText(out);
                        btnSubmit.setEnabled(true);
                    });
                } catch (Exception e) {
                    String msg = e.getMessage() != null ? e.getMessage() : "提交失败";
                    ui.post(() -> {
                        tvResult.setText(msg);
                        btnSubmit.setEnabled(true);
                    });
                }
            });
        });
    }

    private String formatHint() {
        switch (currentProvider) {
            case "aws":
                return "每行格式：别名 | access_key | secret_key | region";
            case "azure":
                return "每行格式：别名 | tenant_id | client_id | client_secret | subscription_id";
            case "oci":
                return "每行格式：别名 | user_ocid | tenancy_ocid | fingerprint | region | private_key(单行，\\n 转义)";
            default:
                return "";
        }
    }

    private List<Map<String, Object>> parse(String text) {
        List<Map<String, Object>> out = new ArrayList<>();
        String[] fieldNames;
        switch (currentProvider) {
            case "aws":
                fieldNames = new String[]{"access_key", "secret_key", "region"};
                break;
            case "azure":
                fieldNames = new String[]{"tenant_id", "client_id",
                        "client_secret", "subscription_id"};
                break;
            case "oci":
                fieldNames = new String[]{"user_ocid", "tenancy_ocid",
                        "fingerprint", "region", "private_key"};
                break;
            default:
                return out;
        }
        for (String line : text.split("\n")) {
            line = line.trim();
            if (line.isEmpty()) continue;
            String[] parts = line.split("\\|");
            if (parts.length < fieldNames.length + 1) continue;
            String name = parts[0].trim();
            if (name.isEmpty()) continue;
            Map<String, String> creds = new HashMap<>();
            for (int i = 0; i < fieldNames.length; i++) {
                String val = parts[i + 1].trim();
                if ("private_key".equals(fieldNames[i])) {
                    val = val.replace("\\n", "\n");
                }
                creds.put(fieldNames[i], val);
            }
            Map<String, Object> acc = new HashMap<>();
            acc.put("name", name);
            acc.put("creds", creds);
            out.add(acc);
        }
        return out;
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
