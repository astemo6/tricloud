package com.tricloud.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;

import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import org.json.JSONArray;
import org.json.JSONObject;
import org.json.JSONTokener;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/** 直连 TriCloud 面板 API（Bearer token）。服务器地址由用户在登录页填写，代码中不含任何域名。 */
public final class Api {
    public interface Cb { void ok(Object data); }

    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private static final ExecutorService POOL = Executors.newFixedThreadPool(4);
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static OkHttpClient http;
    private static SharedPreferences prefs;

    public static void init(Context ctx) {
        if (prefs != null) return;
        try {
            MasterKey mk = new MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build();
            prefs = EncryptedSharedPreferences.create(ctx, "tricloud_secure", mk,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM);
        } catch (Exception e) {
            prefs = ctx.getSharedPreferences("tricloud", Context.MODE_PRIVATE);
        }
        http = new OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(120, TimeUnit.SECONDS).writeTimeout(30, TimeUnit.SECONDS).build();
    }

    public static String server() { return prefs.getString("server", ""); }
    public static String token() { return prefs.getString("token", ""); }
    public static void save(String server, String token) {
        prefs.edit().putString("server", server).putString("token", token).apply();
    }
    public static void logout() { prefs.edit().remove("token").apply(); }
    public static String pref(String k, String d) { return prefs.getString(k, d); }
    public static void setPref(String k, String v) { prefs.edit().putString(k, v).apply(); }

    public static class ApiError extends Exception {
        public final int code;
        public JSONArray guard;   // v1.2 免费额度护栏：409 时的警告列表
        ApiError(int code, String msg) { super(msg); this.code = code; }
    }

    /** 同步调用（在后台线程中使用）。返回 JSONObject / JSONArray。 */
    public static Object call(String method, String path, JSONObject body) throws Exception {
        Request.Builder rb = new Request.Builder().url(server() + "/api" + path)
                .header("Authorization", "Bearer " + token());
        RequestBody rbody = body == null ? (method.equals("GET") || method.equals("DELETE") ? null : RequestBody.create("{}", JSON))
                : RequestBody.create(body.toString(), JSON);
        rb.method(method, rbody);
        try (Response r = http.newCall(rb.build()).execute()) {
            String s = r.body() != null ? r.body().string() : "";
            Object j = s.isEmpty() ? new JSONObject() : new JSONTokener(s).nextValue();
            if (!r.isSuccessful()) {
                String msg = "HTTP " + r.code();
                JSONArray guard = null;
                if (j instanceof JSONObject) {
                    Object d = ((JSONObject) j).opt("detail");
                    if (d instanceof JSONObject) { msg = ((JSONObject) d).optString("msg", msg); guard = ((JSONObject) d).optJSONArray("guard"); }
                    else if (d != null) msg = d.toString();
                }
                ApiError e = new ApiError(r.code(), msg);
                e.guard = guard;
                throw e;
            }
            return j;
        }
    }

    /** 异步调用：成功回调在主线程，失败 Toast。 */
    public static void async(BaseActivity act, String method, String path, JSONObject body, Cb cb) {
        act.setBusy(true);
        POOL.execute(() -> {
            try {
                Object r = call(method, path, body);
                MAIN.post(() -> { act.setBusy(false); if (cb != null) cb.ok(r); });
            } catch (ApiError e) {
                MAIN.post(() -> {
                    act.setBusy(false);
                    if (e.code == 401) act.toLogin();
                    else if (e.code == 409 && e.guard != null && body != null) {
                        StringBuilder sb = new StringBuilder();
                        for (int i = 0; i < e.guard.length(); i++) sb.append("• ").append(e.guard.optString(i)).append("\n\n");
                        sb.append("免费额度以云厂商公示和账号类型为准。可在设置里关闭护栏。");
                        new com.google.android.material.dialog.MaterialAlertDialogBuilder(act).setTitle("⚠️ 可能超出免费额度").setMessage(sb.toString())
                                .setNegativeButton("取消", null)
                                .setPositiveButton("仍然继续", (d, w) -> {
                                    try { async(act, method, path, new JSONObject(body.toString()).put("confirm_overage", true), cb); }
                                    catch (Exception ignored) { }
                                }).show();
                    } else act.toast("❌ " + e.getMessage());
                });
            } catch (Exception e) {
                MAIN.post(() -> { act.setBusy(false); act.toast("❌ " + e.getMessage()); });
            }
        });
    }

    /** 抽屉导航用的账号缓存（打开抽屉时静默刷新）。 */
    public static JSONArray accounts;

    public interface Job { Object run() throws Exception; }

    /** 任意后台任务（原始字节下载 / 上传等），错误处理与 async 一致（不含护栏重试）。 */
    public static void job(BaseActivity act, Job j, Cb cb) {
        act.setBusy(true);
        POOL.execute(() -> {
            try {
                Object r = j.run();
                MAIN.post(() -> { act.setBusy(false); if (cb != null) cb.ok(r); });
            } catch (ApiError e) {
                MAIN.post(() -> { act.setBusy(false); if (e.code == 401) act.toLogin(); else act.toast("❌ " + e.getMessage()); });
            } catch (Exception e) {
                MAIN.post(() -> { act.setBusy(false); act.toast("❌ " + e.getMessage()); });
            }
        });
    }

    /** 后端已启用的云厂商（GET /api/meta 的 providers）；null 表示未知 / 请求失败 → 全部显示。 */
    public static java.util.List<String> providers;

    /** 拉取 /api/meta；无论成功失败都会在主线程回调 done（失败时 providers 置 null，回退为全部厂商）。 */
    public static void meta(Runnable done) {
        POOL.execute(() -> {
            java.util.List<String> l = null;
            try {
                Object r = call("GET", "/meta", null);
                JSONArray a = r instanceof JSONObject ? ((JSONObject) r).optJSONArray("providers") : null;
                if (a != null) {
                    l = new java.util.ArrayList<>();
                    for (int i = 0; i < a.length(); i++) l.add(a.optString(i));
                    if (l.isEmpty()) l = null;
                }
            } catch (Exception ignored) { }
            java.util.List<String> fin = l;
            MAIN.post(() -> { providers = fin; if (done != null) done.run(); });
        });
    }

    /** 某厂商是否在后端启用列表里（列表未知时视为启用）。 */
    public static boolean provEnabled(String p) { return providers == null || providers.contains(p); }

    /** 静默 GET：不显示进度、不提示错误（抽屉刷新账号列表用）。 */
    public static void quiet(String path, Cb cb) {
        POOL.execute(() -> {
            try { Object r = call("GET", path, null); MAIN.post(() -> cb.ok(r)); } catch (Exception ignored) { }
        });
    }

    private static ApiError errOf(Response r, String s) {
        String msg = "HTTP " + r.code();
        try {
            Object j = new JSONTokener(s).nextValue();
            if (j instanceof JSONObject) {
                Object d = ((JSONObject) j).opt("detail");
                if (d instanceof JSONObject) msg = ((JSONObject) d).optString("msg", msg);
                else if (d != null) msg = d.toString();
            }
        } catch (Exception ignored) { }
        return new ApiError(r.code(), msg);
    }

    /** POST 并取回原始字节（加密备份下载）。name[0] 回填服务器给的文件名。 */
    public static byte[] rawPost(String path, JSONObject body, String[] name) throws Exception {
        Request rq = new Request.Builder().url(server() + "/api" + path).header("Authorization", "Bearer " + token())
                .post(RequestBody.create(body == null ? "{}" : body.toString(), JSON)).build();
        try (Response r = http.newCall(rq).execute()) {
            if (!r.isSuccessful()) throw errOf(r, r.body() != null ? r.body().string() : "");
            String cd = r.header("Content-Disposition", "");
            int i = cd == null ? -1 : cd.indexOf("filename=\"");
            if (name != null && name.length > 0) name[0] = i < 0 ? "tricloud.tcbk" : cd.substring(i + 10).replace("\"", "");
            return r.body() != null ? r.body().bytes() : new byte[0];
        }
    }

    /** PUT 原始字节（对象存储上传）。 */
    public static Object putBytes(String path, byte[] data) throws Exception {
        Request rq = new Request.Builder().url(server() + "/api" + path).header("Authorization", "Bearer " + token())
                .put(RequestBody.create(data, MediaType.get("application/octet-stream"))).build();
        try (Response r = http.newCall(rq).execute()) {
            String s = r.body() != null ? r.body().string() : "";
            if (!r.isSuccessful()) throw errOf(r, s);
            return s.isEmpty() ? new JSONObject() : new JSONTokener(s).nextValue();
        }
    }

    public static void get(BaseActivity a, String p, Cb cb) { async(a, "GET", p, null, cb); }
    public static void post(BaseActivity a, String p, JSONObject b, Cb cb) { async(a, "POST", p, b, cb); }
    public static void del(BaseActivity a, String p, Cb cb) { async(a, "DELETE", p, null, cb); }

    public static JSONArray arr(Object o) { return o instanceof JSONArray ? (JSONArray) o : new JSONArray(); }
    public static JSONObject obj(Object o) { return o instanceof JSONObject ? (JSONObject) o : new JSONObject(); }

    public static String enc(String s) {
        try { return java.net.URLEncoder.encode(s == null ? "" : s, "UTF-8"); } catch (Exception e) { return s; }
    }
}
