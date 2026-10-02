package com.tricloud.app;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.tricloud.app.api.TriCloudApi;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class SettingsActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_settings);

        EditText etOld = findViewById(R.id.etOldPwd);
        EditText etNew = findViewById(R.id.etNewPwd);
        EditText etTgToken = findViewById(R.id.etTgToken);
        EditText etTgChat = findViewById(R.id.etTgChat);
        TextView tvTgStatus = findViewById(R.id.tvTgStatus);
        Button btnPwd = findViewById(R.id.btnChangePwd);
        Button btnTgSave = findViewById(R.id.btnTgSave);
        Button btnTgTest = findViewById(R.id.btnTgTest);

        // 加载当前 TG 配置
        bg.execute(() -> {
            try {
                String raw = ApiHolder.api.getSettings();
                JsonObject obj = JsonParser.parseString(raw).getAsJsonObject();
                String chatId = obj.has("tg_chat_id") && !obj.get("tg_chat_id").isJsonNull()
                        ? obj.get("tg_chat_id").getAsString() : "";
                boolean tokenSet = obj.has("tg_bot_token_set")
                        && obj.get("tg_bot_token_set").getAsBoolean();
                boolean running = obj.has("tg_bot_running")
                        && obj.get("tg_bot_running").getAsBoolean();
                ui.post(() -> {
                    etTgChat.setText(chatId);
                    etTgToken.setHint(tokenSet ? "已保存，留空不修改" : "Bot Token");
                    tvTgStatus.setText(running ? "Bot 运行中" : "Bot 未运行");
                    tvTgStatus.setTextColor(running ? 0xFF4CAF50 : 0xFFFF9800);
                });
            } catch (Exception ignored) {}
        });

        btnPwd.setOnClickListener(v -> {
            String oldPwd = etOld.getText().toString();
            String newPwd = etNew.getText().toString();
            if (oldPwd.isEmpty() || newPwd.isEmpty()) {
                Toast.makeText(this, "请填写原密码和新密码", Toast.LENGTH_SHORT).show();
                return;
            }
            bg.execute(() -> {
                try {
                    ApiHolder.api.changePassword(oldPwd, newPwd);
                    ui.post(() -> {
                        Toast.makeText(this, "密码已修改", Toast.LENGTH_SHORT).show();
                        etOld.setText("");
                        etNew.setText("");
                    });
                } catch (Exception e) {
                    String msg = e.getMessage() != null ? e.getMessage() : "修改失败";
                    ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show());
                }
            });
        });

        btnTgSave.setOnClickListener(v -> {
            Map<String, String> s = new HashMap<>();
            String token = etTgToken.getText().toString().trim();
            if (!token.isEmpty()) s.put("tg_bot_token", token);
            s.put("tg_chat_id", etTgChat.getText().toString().trim());
            bg.execute(() -> {
                try {
                    ApiHolder.api.updateSettings(s);
                    ui.post(() -> Toast.makeText(this, "TG 配置已保存",
                            Toast.LENGTH_SHORT).show());
                } catch (Exception e) {
                    String msg = e.getMessage() != null ? e.getMessage() : "保存失败";
                    ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show());
                }
            });
        });

        btnTgTest.setOnClickListener(v -> bg.execute(() -> {
            try {
                ApiHolder.api.tgTest();
                ui.post(() -> Toast.makeText(this, "测试消息已发送",
                        Toast.LENGTH_SHORT).show());
            } catch (Exception e) {
                String msg = e.getMessage() != null ? e.getMessage() : "发送失败";
                ui.post(() -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show());
            }
        }));
    }

    @Override
    protected void onDestroy() {
        bg.shutdownNow();
        super.onDestroy();
    }
}
