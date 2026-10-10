package com.tricloud.app;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import com.tricloud.app.api.TriCloudApi;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {

    private final ExecutorService bg = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        SharedPreferences prefs = getSharedPreferences("tricloud", Context.MODE_PRIVATE);
        EditText etServer = findViewById(R.id.etServer);
        EditText etPassword = findViewById(R.id.etPassword);
        Button btnLogin = findViewById(R.id.btnLogin);
        TextView tvError = findViewById(R.id.tvError);

        etServer.setText(prefs.getString("server_url", "https://your-panel.example.com"));

        btnLogin.setOnClickListener(v -> {
            String server = etServer.getText().toString().trim().replaceAll("/+$", "");
            String password = etPassword.getText().toString();
            if (server.isEmpty() || password.isEmpty()) {
                tvError.setText("请填写服务器地址和密码");
                return;
            }
            tvError.setText("");
            btnLogin.setEnabled(false);
            bg.execute(() -> {
                try {
                    TriCloudApi api = new TriCloudApi(server);
                    api.login(password);
                    prefs.edit()
                            .putString("server_url", server)
                            .apply();
                    ApiHolder.api = api;
                    ApiHolder.serverUrl = server;
                    ui.post(() -> {
                        startActivity(new Intent(this, AccountActivity.class));
                        finish();
                    });
                } catch (Exception e) {
                    String msg = e.getMessage() != null ? e.getMessage() : "登录失败";
                    ui.post(() -> {
                        tvError.setText(msg);
                        btnLogin.setEnabled(true);
                    });
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
