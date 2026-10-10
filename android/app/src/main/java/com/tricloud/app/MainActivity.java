package com.tricloud.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.Toast;

public class MainActivity extends Activity {

    private static final String KEY_URL = "server_url";
    private static final String DEFAULT_URL = "https://your-panel.example.com";

    private WebView webView;
    private ProgressBar progress;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("tricloud", Context.MODE_PRIVATE);

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        progress.setMax(100);

        webView = new WebView(this);
        webView.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.addView(progress);
        root.addView(webView);
        setContentView(root);

        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        cm.setAcceptThirdPartyCookies(webView, true);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                progress.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progress.setVisibility(View.GONE);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (request.isForMainFrame()) {
                    Toast.makeText(MainActivity.this,
                            "加载失败，可点右上角菜单修改服务器地址后刷新",
                            Toast.LENGTH_LONG).show();
                }
            }
        });
        // 长按菜单：输入框内允许（可粘贴），其他区域禁用
        webView.setOnLongClickListener(v -> {
            android.webkit.WebView.HitTestResult hit =
                ((android.webkit.WebView) v).getHitTestResult();
            return hit.getType() !=
                android.webkit.WebView.HitTestResult.EDIT_TEXT_TYPE;
        });

        String saved = prefs.getString(KEY_URL, null);
        if (saved == null || saved.isEmpty()) {
            showServerDialog(true);
        } else {
            webView.loadUrl(saved);
        }
    }

    private void showServerDialog(boolean firstRun) {
        final EditText input = new EditText(this);
        input.setText(prefs.getString(KEY_URL, DEFAULT_URL));
        input.setHint(DEFAULT_URL);
        input.setSingleLine();
        new AlertDialog.Builder(this)
                .setTitle("服务器地址")
                .setMessage("填写 TriCloud 面板的公网地址（Cloudflare Tunnel hostname）")
                .setView(input)
                .setCancelable(!firstRun)
                .setPositiveButton("保存并连接", (d, w) -> {
                    String url = input.getText().toString().trim();
                    while (url.endsWith("/")) url = url.substring(0, url.length() - 1);
                    if (url.isEmpty()) {
                        Toast.makeText(this, "地址不能为空", Toast.LENGTH_SHORT).show();
                        return;
                    }
                    prefs.edit().putString(KEY_URL, url).apply();
                    webView.loadUrl(url);
                })
                .setNegativeButton(firstRun ? "稍后" : "取消", null)
                .show();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, "刷新");
        menu.add(0, 2, 0, "服务器设置");
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == 1) { webView.reload(); return true; }
        if (item.getItemId() == 2) { showServerDialog(false); return true; }
        return super.onOptionsItemSelected(item);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}
