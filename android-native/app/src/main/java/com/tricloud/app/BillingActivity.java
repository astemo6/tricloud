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
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.tricloud.app.api.Models;
import com.tricloud.app.api.TriCloudApi;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class BillingActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final SimpleDateFormat dateFmt =
            new SimpleDateFormat("yyyy-MM-dd", Locale.getDefault());

    private int accountId;
    private String provider;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_billing);

        accountId = getIntent().getIntExtra("account_id", 0);
        String accountName = getIntent().getStringExtra("account_name");
        provider = getIntent().getStringExtra("provider");
        ((TextView) findViewById(R.id.tvTitle)).setText(
                (accountName != null ? accountName : "") + " 账单");

        TriCloudApi api = ApiHolder.api;
        if (api == null) {
            finish();
            return;
        }

        loadBilling();
        if ("aws".equals(provider)) {
            findViewById(R.id.llCredit).setVisibility(View.VISIBLE);
            findViewById(R.id.btnCreditAdd).setOnClickListener(v ->
                    showCreditDialog(null));
            loadCredits();
        }
    }

    private void loadBilling() {
        bg.execute(() -> {
            try {
                Models.Billing b = ApiHolder.api.billing(accountId);
                ui.post(() -> {
                    String currency = b.currency != null ? b.currency : "USD";
                    ((TextView) findViewById(R.id.tvTotal)).setText(
                            String.format("%.2f %s", b.total, currency));
                    ((TextView) findViewById(R.id.tvPeriod)).setText(
                            b.period != null ? b.period : "");
                    LinearLayout ll = findViewById(R.id.llServices);
                    ll.removeAllViews();
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

    // ---------- 手动 Credit ----------

    private static class Credit {
        int id;
        String name;
        double amount;
        Double startAt;
        Double expiresAt;
    }

    private void loadCredits() {
        ListView lv = findViewById(R.id.lvCredits);
        List<Credit> list = new ArrayList<>();
        CreditAdapter adapter = new CreditAdapter(list);
        lv.setAdapter(adapter);
        bg.execute(() -> {
            try {
                String raw = ApiHolder.api.creditsManual(accountId);
                JsonArray arr = JsonParser.parseString(raw).getAsJsonArray();
                List<Credit> loaded = new ArrayList<>();
                for (JsonElement e : arr) {
                    JsonObject o = e.getAsJsonObject();
                    Credit c = new Credit();
                    c.id = o.get("id").getAsInt();
                    c.name = o.get("name").getAsString();
                    c.amount = o.get("amount").getAsDouble();
                    c.startAt = o.has("start_at") && !o.get("start_at").isJsonNull()
                            ? o.get("start_at").getAsDouble() : null;
                    c.expiresAt = o.has("expires_at") && !o.get("expires_at").isJsonNull()
                            ? o.get("expires_at").getAsDouble() : null;
                    loaded.add(c);
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

    private void showCreditDialog(Credit edit) {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(48, 24, 48, 0);

        EditText etName = addField(layout, "名称", false,
                edit != null ? edit.name : null);
        EditText etAmount = addField(layout, "金额", true,
                edit != null ? String.valueOf(edit.amount) : null);
        EditText etStart = addField(layout, "生效日期 (yyyy-MM-dd，可空)", false,
                edit != null && edit.startAt != null
                        ? dateFmt.format(new Date((long)(edit.startAt * 1000))) : null);
        EditText etExpire = addField(layout, "到期日期 (yyyy-MM-dd，可空)", false,
                edit != null && edit.expiresAt != null
                        ? dateFmt.format(new Date((long)(edit.expiresAt * 1000))) : null);

        new AlertDialog.Builder(this)
                .setTitle(edit == null ? "添加 Credit" : "编辑 Credit")
                .setView(layout)
                .setPositiveButton("保存", (d, w) -> {
                    String name = etName.getText().toString().trim();
                    String amtStr = etAmount.getText().toString().trim();
                    if (name.isEmpty() || amtStr.isEmpty()) {
                        Toast.makeText(this, "名称和金额不能为空",
                                Toast.LENGTH_SHORT).show();
                        return;
                    }
                    double amount;
                    try {
                        amount = Double.parseDouble(amtStr);
                    } catch (NumberFormatException e) {
                        Toast.makeText(this, "金额格式错误",
                                Toast.LENGTH_SHORT).show();
                        return;
                    }
                    Double startAt = parseDate(etStart.getText().toString().trim());
                    Double expiresAt = parseDate(etExpire.getText().toString().trim());
                    bg.execute(() -> {
                        try {
                            if (edit == null) {
                                ApiHolder.api.creditAdd(accountId, name, amount,
                                        startAt, expiresAt);
                            } else {
                                ApiHolder.api.creditUpdate(edit.id, accountId, name,
                                        amount, startAt, expiresAt);
                            }
                            ui.post(() -> {
                                Toast.makeText(this, "已保存", Toast.LENGTH_SHORT).show();
                                loadCredits();
                                loadBilling();
                            });
                        } catch (Exception e) {
                            String msg = e.getMessage() != null
                                    ? e.getMessage() : "保存失败";
                            ui.post(() -> Toast.makeText(this, msg,
                                    Toast.LENGTH_LONG).show());
                        }
                    });
                })
                .setNegativeButton("取消", null)
                .show();
    }

    private Double parseDate(String s) {
        if (s.isEmpty()) return null;
        try {
            return dateFmt.parse(s).getTime() / 1000.0;
        } catch (Exception e) {
            return null;
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

    private void deleteCredit(Credit c) {
        new AlertDialog.Builder(this)
                .setTitle("删除 Credit")
                .setMessage("删除「" + c.name + "」？")
                .setPositiveButton("删除", (d, w) -> bg.execute(() -> {
                    try {
                        ApiHolder.api.creditDelete(accountId, c.id);
                        ui.post(() -> {
                            Toast.makeText(this, "已删除", Toast.LENGTH_SHORT).show();
                            loadCredits();
                            loadBilling();
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

    private class CreditAdapter extends BaseAdapter {
        private final List<Credit> items;
        private final LayoutInflater inflater;

        CreditAdapter(List<Credit> items) {
            this.items = items;
            this.inflater = LayoutInflater.from(BillingActivity.this);
        }

        @Override public int getCount() { return items.size(); }
        @Override public Object getItem(int p) { return items.get(p); }
        @Override public long getItemId(int p) { return p; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            View v = convertView;
            if (v == null) v = inflater.inflate(R.layout.item_credit, parent, false);
            Credit c = items.get(position);
            ((TextView) v.findViewById(R.id.tvName)).setText(c.name);
            StringBuilder sb = new StringBuilder();
            sb.append(String.format("%.2f", c.amount));
            if (c.startAt != null) {
                sb.append(" · ").append(dateFmt.format(
                        new Date((long)(c.startAt * 1000)))).append(" 生效");
            }
            if (c.expiresAt != null) {
                sb.append(" · ").append(dateFmt.format(
                        new Date((long)(c.expiresAt * 1000)))).append(" 到期");
            }
            ((TextView) v.findViewById(R.id.tvInfo)).setText(sb.toString());
            v.findViewById(R.id.btnEdit).setOnClickListener(
                    b -> showCreditDialog(c));
            v.findViewById(R.id.btnDelete).setOnClickListener(
                    b -> deleteCredit(c));
            return v;
        }
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
