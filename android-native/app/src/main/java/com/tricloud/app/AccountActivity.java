package com.tricloud.app;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import com.tricloud.app.api.Models;
import com.tricloud.app.api.TriCloudApi;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class AccountActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_account);

        TriCloudApi api = ApiHolder.api;
        if (api == null) {
            Toast.makeText(this, "未登录", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }

        ListView lv = findViewById(R.id.lvAccounts);
        findViewById(R.id.btnJobs).setOnClickListener(v ->
                startActivity(new Intent(this, JobActivity.class)));

        List<Models.CloudAccount> all = new ArrayList<>();        ArrayAdapter<Models.CloudAccount> adapter =
                new ArrayAdapter<Models.CloudAccount>(this,
                        android.R.layout.simple_list_item_2,
                        android.R.id.text1, all) {
                    @Override
                    public View getView(int position, View convertView, ViewGroup parent) {
                        View v = super.getView(position, convertView, parent);
                        Models.CloudAccount a = getItem(position);
                        TextView t1 = v.findViewById(android.R.id.text1);
                        TextView t2 = v.findViewById(android.R.id.text2);
                        t1.setText(a.name);
                        t1.setTextColor(0xFFE6E9F0);
                        t2.setText(a.provider.toUpperCase());
                        t2.setTextColor(0xFF8B93AD);
                        return v;
                    }
                };
        lv.setAdapter(adapter);

        lv.setOnItemClickListener((AdapterView<?> parent, View view, int position, long id) -> {
            Models.CloudAccount acc = all.get(position);
            Intent i = new Intent(this, DashboardActivity.class);
            i.putExtra("account_id", acc.id);
            i.putExtra("account_name", acc.name);
            i.putExtra("provider", acc.provider);
            startActivity(i);
        });

        bg.execute(() -> {
            List<Models.CloudAccount> loaded = new ArrayList<>();
            for (String p : new String[]{"oci", "aws", "azure"}) {
                try {
                    loaded.addAll(api.accounts(p));
                } catch (Exception ignored) {}
            }
            ui.post(() -> {
                all.clear();
                all.addAll(loaded);
                adapter.notifyDataSetChanged();
                if (loaded.isEmpty()) {
                    Toast.makeText(this, "暂无账号", Toast.LENGTH_SHORT).show();
                }
            });
        });
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
