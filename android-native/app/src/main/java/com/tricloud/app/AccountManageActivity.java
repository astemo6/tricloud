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

public class AccountManageActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_account_manage);

        findViewById(R.id.btnAdd).setOnClickListener(v ->
                startActivity(new Intent(this, AddAccountActivity.class)));
        findViewById(R.id.btnBatch).setOnClickListener(v ->
                startActivity(new Intent(this, BatchAddActivity.class)));
        findViewById(R.id.btnRecycle).setOnClickListener(v ->
                startActivity(new Intent(this, RecycleActivity.class)));
        findViewById(R.id.btnTestAll).setOnClickListener(v -> testAll());
    }

    @Override
    protected void onResume() {
        super.onResume();
        load();
    }

    private void load() {
        TriCloudApi api = ApiHolder.api;
        if (api == null) return;
        ListView lv = findViewById(R.id.lvAccounts);
        List<Models.CloudAccount> list = new ArrayList<>();
        AccountAdapter adapter = new AccountAdapter(list);
        lv.setAdapter(adapter);

        bg.execute(() -> {
            List<Models.CloudAccount> loaded = new ArrayList<>();
            for (String p : new String[]{"oci", "aws", "azure"}) {
                try {
                    loaded.addAll(api.accounts(p));
                } catch (Exception ignored) {}
            }
            ui.post(() -> {
                list.clear();
                list.addAll(loaded);
                adapter.notifyDataSetChanged();
            });
        });
    }

    private void testAll() {
        bg.execute(() -> {
            try {
                ApiHolder.api.testAll();
                ui.post(() -> Toast.makeText(this, "测活任务已提交",
                        Toast.LENGTH_SHORT).show());
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "操作失败";
                ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show());
            }
        });
    }

    private void confirmDelete(Models.CloudAccount acc) {
        new AlertDialog.Builder(this)
                .setTitle("删除账号")
                .setMessage("删除「" + acc.name + "」？将记入回收站。")
                .setPositiveButton("删除", (d, w) -> bg.execute(() -> {
                    try {
                        ApiHolder.api.deleteAccount(acc.id);
                        ui.post(() -> {
                            Toast.makeText(this, "已删除", Toast.LENGTH_SHORT).show();
                            load();
                        });
                    } catch (Exception e) {
                        String msg = e.getMessage() != null ? e.getMessage() : "删除失败";
                        ui.post(() -> Toast.makeText(this, msg,
                                Toast.LENGTH_SHORT).show());
                    }
                }))
                .setNegativeButton("取消", null)
                .show();
    }

    private void testAccount(Models.CloudAccount acc) {
        bg.execute(() -> {
            try {
                ApiHolder.api.testAccount(acc.id);
                ui.post(() -> Toast.makeText(this, acc.name + " 连接正常",
                        Toast.LENGTH_SHORT).show());
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "测试失败";
                ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
            }
        });
    }

    private class AccountAdapter extends BaseAdapter {
        private final List<Models.CloudAccount> items;
        private final LayoutInflater inflater;

        AccountAdapter(List<Models.CloudAccount> items) {
            this.items = items;
            this.inflater = LayoutInflater.from(AccountManageActivity.this);
        }

        @Override public int getCount() { return items.size(); }
        @Override public Object getItem(int p) { return items.get(p); }
        @Override public long getItemId(int p) { return p; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            View v = convertView;
            if (v == null) v = inflater.inflate(R.layout.item_account_manage, parent, false);
            Models.CloudAccount acc = items.get(position);
            ((TextView) v.findViewById(R.id.tvName)).setText(acc.name);
            ((TextView) v.findViewById(R.id.tvProvider)).setText(
                    acc.provider.toUpperCase() + " · #" + acc.id);
            v.findViewById(R.id.btnTest).setOnClickListener(b -> testAccount(acc));
            v.findViewById(R.id.btnDelete).setOnClickListener(b -> confirmDelete(acc));
            return v;
        }
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
