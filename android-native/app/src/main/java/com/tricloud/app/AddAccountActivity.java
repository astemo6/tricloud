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
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import com.tricloud.app.api.TriCloudApi;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class AddAccountActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    /** provider -> [(field, label, multiline)] */
    private static final Map<String, List<String[]>> CRED_FIELDS = new LinkedHashMap<>();
    static {
        List<String[]> aws = new ArrayList<>();
        aws.add(new String[]{"access_key", "Access Key ID", "0"});
        aws.add(new String[]{"secret_key", "Secret Access Key", "0"});
        aws.add(new String[]{"region", "默认区域 (如 ap-northeast-1)", "0"});
        CRED_FIELDS.put("aws", aws);

        List<String[]> azure = new ArrayList<>();
        azure.add(new String[]{"tenant_id", "Tenant ID", "0"});
        azure.add(new String[]{"client_id", "Client ID", "0"});
        azure.add(new String[]{"client_secret", "Client Secret", "0"});
        azure.add(new String[]{"subscription_id", "Subscription ID", "0"});
        CRED_FIELDS.put("azure", azure);

        List<String[]> oci = new ArrayList<>();
        oci.add(new String[]{"user_ocid", "User OCID", "0"});
        oci.add(new String[]{"tenancy_ocid", "Tenancy OCID", "0"});
        oci.add(new String[]{"fingerprint", "Fingerprint", "0"});
        oci.add(new String[]{"private_key", "Private Key (PEM)", "1"});
        oci.add(new String[]{"region", "区域 (如 ap-tokyo-1)", "0"});
        CRED_FIELDS.put("oci", oci);
    }

    private String currentProvider = "aws";
    private final List<EditText> credInputs = new ArrayList<>();
    private final List<String> credNames = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_add_account);

        Spinner spProvider = findViewById(R.id.spProvider);
        LinearLayout llCreds = findViewById(R.id.llCreds);
        EditText etName = findViewById(R.id.etName);
        Button btnSave = findViewById(R.id.btnSave);

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
                buildCredForm(llCreds);
            }
            @Override public void onNothingSelected(AdapterView<?> p) {}
        });
        buildCredForm(llCreds);

        btnSave.setOnClickListener(v -> {
            String name = etName.getText().toString().trim();
            if (name.isEmpty()) {
                Toast.makeText(this, "别名不能为空", Toast.LENGTH_SHORT).show();
                return;
            }
            Map<String, String> creds = new HashMap<>();
            for (int i = 0; i < credNames.size(); i++) {
                String val = credInputs.get(i).getText().toString().trim();
                if (val.isEmpty()) {
                    Toast.makeText(this, "请填写完整凭证", Toast.LENGTH_SHORT).show();
                    return;
                }
                creds.put(credNames.get(i), val);
            }
            btnSave.setEnabled(false);
            bg.execute(() -> {
                try {
                    ApiHolder.api.createAccount(currentProvider, name, creds);
                    ui.post(() -> {
                        Toast.makeText(this, "账号已添加", Toast.LENGTH_SHORT).show();
                        finish();
                    });
                } catch (Exception e) {
                    String msg = e.getMessage() != null ? e.getMessage() : "添加失败";
                    ui.post(() -> {
                        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
                        btnSave.setEnabled(true);
                    });
                }
            });
        });
    }

    private void buildCredForm(LinearLayout ll) {
        ll.removeAllViews();
        credInputs.clear();
        credNames.clear();
        List<String[]> fields = CRED_FIELDS.get(currentProvider);
        if (fields == null) return;
        for (String[] f : fields) {
            TextView label = new TextView(this);
            label.setText(f[1]);
            label.setTextColor(0xFFE6E9F0);
            label.setPadding(0, 12, 0, 4);
            ll.addView(label);
            EditText et = new EditText(this);
            et.setHint(f[1]);
            et.setTextColor(0xFFE6E9F0);
            et.setHintTextColor(0xFF5A6480);
            if ("1".equals(f[2])) {
                et.setInputType(InputType.TYPE_CLASS_TEXT
                        | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
                et.setMinLines(4);
            }
            ll.addView(et);
            credInputs.add(et);
            credNames.add(f[0]);
        }
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
