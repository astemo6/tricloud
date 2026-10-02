package com.tricloud.app

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.graphics.Bitmap
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.webkit.CookieManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.Toast

class MainActivity : Activity() {

    private lateinit var webView: WebView
    private lateinit var progress: ProgressBar
    private val prefs by lazy { getSharedPreferences("tricloud", Context.MODE_PRIVATE) }

    companion object {
        const val KEY_URL = "server_url"
        const val DEFAULT_URL = "https://panel.6668800.xyz"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
            max = 100
        }
        webView = WebView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0, 1f
            )
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(progress)
            addView(webView)
        }
        setContentView(root)

        val cm = CookieManager.getInstance()
        cm.setAcceptCookie(true)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = false
            displayZoomControls = false
        }
        // 允许跨域 Cookie（面板登录态需要）
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                progress.visibility = android.view.View.VISIBLE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                progress.visibility = android.view.View.GONE
            }

            override fun onReceivedError(
                view: WebView?, request: WebResourceRequest?, error: WebResourceError?
            ) {
                if (request?.isForMainFrame == true) {
                    Toast.makeText(
                        this@MainActivity,
                        "加载失败：${error?.description}，可点右上角菜单修改服务器地址后刷新",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
        webView.setOnLongClickListener { true } // 禁用长按菜单

        val saved = prefs.getString(KEY_URL, null)
        if (saved.isNullOrBlank()) {
            showServerDialog(firstRun = true)
        } else {
            webView.loadUrl(saved)
        }
    }

    private fun showServerDialog(firstRun: Boolean) {
        val input = EditText(this).apply {
            setText(prefs.getString(KEY_URL, DEFAULT_URL))
            hint = DEFAULT_URL
            setSingleLine()
        }
        AlertDialog.Builder(this)
            .setTitle("服务器地址")
            .setMessage("填写 TriCloud 面板的公网地址（Cloudflare Tunnel hostname）")
            .setView(input)
            .setCancelable(!firstRun)
            .setPositiveButton("保存并连接") { _, _ ->
                val url = input.text.toString().trim().trimEnd('/')
                if (url.isBlank()) {
                    Toast.makeText(this, "地址不能为空", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                prefs.edit().putString(KEY_URL, url).apply()
                webView.loadUrl(url)
            }
            .setNegativeButton(if (firstRun) "稍后" else "取消", null)
            .show()
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "刷新")
        menu.add(0, 2, 0, "服务器设置")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            1 -> { webView.reload(); true }
            2 -> { showServerDialog(firstRun = false); true }
            else -> super.onOptionsItemSelected(item)
        }
    }

    @Deprecated("back handling")
    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) webView.goBack()
        else super.onBackPressed()
    }

    override fun onDestroy() {
        if (::webView.isInitialized) webView.destroy()
        super.onDestroy()
    }
}
