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

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class JobActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final SimpleDateFormat fmt =
            new SimpleDateFormat("MM-dd HH:mm", Locale.getDefault());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_job);

        findViewById(R.id.btnRefresh).setOnClickListener(v -> load());
        load();
    }

    private void load() {
        TriCloudApi api = ApiHolder.api;
        if (api == null) return;
        ListView lv = findViewById(R.id.lvJobs);
        List<Models.Job> list = new ArrayList<>();
        JobAdapter adapter = new JobAdapter(list);
        lv.setAdapter(adapter);

        bg.execute(() -> {
            try {
                List<Models.Job> loaded = api.jobs();
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

    private void showLog(Models.Job job) {
        String log = job.log != null && !job.log.isEmpty() ? job.log : "(无日志)";
        if (job.result != null && !job.result.isEmpty()) {
            log += "\n\n--- 结果 ---\n" + job.result;
        }
        new AlertDialog.Builder(this)
                .setTitle(job.title)
                .setMessage(log)
                .setPositiveButton("关闭", null)
                .show();
    }

    private void deleteJob(Models.Job job) {
        new AlertDialog.Builder(this)
                .setTitle("删除任务记录")
                .setMessage("删除「" + job.title + "」的历史记录？")
                .setPositiveButton("删除", (d, w) -> bg.execute(() -> {
                    try {
                        ApiHolder.api.jobDelete(job.id);
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

    private void stopJob(Models.Job job) {
        new AlertDialog.Builder(this)
                .setTitle("停止任务")
                .setMessage("停止「" + job.title + "」？")
                .setPositiveButton("确认", (d, w) -> bg.execute(() -> {
                    try {
                        ApiHolder.api.jobStop(job.id);
                        ui.post(() -> {
                            Toast.makeText(this, "已发送停止请求",
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

    private class JobAdapter extends BaseAdapter {
        private final List<Models.Job> items;
        private final LayoutInflater inflater;

        JobAdapter(List<Models.Job> items) {
            this.items = items;
            this.inflater = LayoutInflater.from(JobActivity.this);
        }

        @Override public int getCount() { return items.size(); }
        @Override public Object getItem(int p) { return items.get(p); }
        @Override public long getItemId(int p) { return p; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            View v = convertView;
            if (v == null) v = inflater.inflate(R.layout.item_job, parent, false);
            Models.Job job = items.get(position);

            ((TextView) v.findViewById(R.id.tvTitle)).setText(job.title);
            String time = fmt.format(new Date((long) (job.created_at * 1000)));
            ((TextView) v.findViewById(R.id.tvMeta)).setText(
                    time + " · " + job.provider);

            TextView tvStatus = v.findViewById(R.id.tvStatus);
            tvStatus.setText(statusLabel(job.status));
            tvStatus.setTextColor(statusColor(job.status));

            v.findViewById(R.id.btnLog).setOnClickListener(b -> showLog(job));
            Button btnStop = v.findViewById(R.id.btnStop);
            boolean canStop = "queued".equals(job.status) || "running".equals(job.status);
            btnStop.setVisibility(canStop ? View.VISIBLE : View.GONE);
            btnStop.setOnClickListener(b -> stopJob(job));
            v.findViewById(R.id.btnDelete).setOnClickListener(b -> deleteJob(job));
            return v;
        }

        private String statusLabel(String s) {
            switch (s) {
                case "queued": return "排队中";
                case "running": return "运行中";
                case "success": return "成功";
                case "failed": return "失败";
                case "stopped": return "已停止";
                case "interrupted": return "已中断";
                default: return s;
            }
        }

        private int statusColor(String s) {
            switch (s) {
                case "success": return 0xFF4CAF50;
                case "failed": return 0xFFF44336;
                case "running":
                case "queued": return 0xFF2196F3;
                default: return 0xFFFF9800;
            }
        }
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
