package com.tricloud.app.api;

import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import okhttp3.Cookie;
import okhttp3.CookieJar;
import okhttp3.HttpUrl;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;

import java.io.IOException;
import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * TriCloud 面板 API 客户端（Cookie 会话）。
 * 所有网络调用为同步阻塞，调用方需在子线程执行。
 */
public class TriCloudApi {

    public static class ApiException extends Exception {
        public ApiException(String message) { super(message); }
    }

    public interface Callback<T> {
        void onSuccess(T result);
        void onError(String message);
    }

    private final Gson gson = new Gson();
    private final String base;
    private final OkHttpClient client;
    private static final MediaType JSON = MediaType.get("application/json");

    public TriCloudApi(String serverUrl) {
        this.base = serverUrl.trim().replaceAll("/+$", "");
        CookieJar jar = new CookieJar() {
            private final Map<String, List<Cookie>> store = new HashMap<>();
            @Override public void saveFromResponse(HttpUrl url, List<Cookie> cookies) {
                store.put(url.host(), cookies);
            }
            @Override public List<Cookie> loadForRequest(HttpUrl url) {
                List<Cookie> c = store.get(url.host());
                return c != null ? c : new ArrayList<>();
            }
        };
        this.client = new OkHttpClient.Builder().cookieJar(jar).build();
    }

    private String get(String path) throws IOException, ApiException {
        Request req = new Request.Builder().url(base + path).get().build();
        return exec(req);
    }

    private String post(String path, String json) throws IOException, ApiException {
        Request req = new Request.Builder()
                .url(base + path)
                .post(RequestBody.create(json, JSON))
                .build();
        return exec(req);
    }

    private String exec(Request req) throws IOException, ApiException {
        try (okhttp3.Response resp = client.newCall(req).execute()) {
            String body = resp.body() != null ? resp.body().string() : "";
            if (!resp.isSuccessful()) throw new ApiException(parseDetail(body, resp.code()));
            return body;
        }
    }

    private String parseDetail(String body, int code) {
        try {
            Type t = new TypeToken<Map<String, Object>>() {}.getType();
            Map<String, Object> map = gson.fromJson(body, t);
            Object d = map.get("detail");
            if (d instanceof String) return (String) d;
        } catch (Exception ignored) {}
        return "请求失败 (" + code + ")";
    }

    public void login(String password) throws IOException, ApiException {
        Map<String, String> p = new HashMap<>();
        p.put("password", password);
        post("/api/login", gson.toJson(p));
    }

    public List<Models.Provider> providers() throws IOException, ApiException {
        Type t = new TypeToken<List<Models.Provider>>() {}.getType();
        return gson.fromJson(get("/api/providers"), t);
    }

    public List<Models.CloudAccount> accounts(String provider)
            throws IOException, ApiException {
        Type t = new TypeToken<List<Models.CloudAccount>>() {}.getType();
        return gson.fromJson(get("/api/accounts?provider=" + provider), t);
    }

    public List<Models.Instance> instances(int accountId)
            throws IOException, ApiException {
        Type t = new TypeToken<List<Models.Instance>>() {}.getType();
        return gson.fromJson(get("/api/accounts/" + accountId + "/instances"), t);
    }

    public String instanceAction(int accountId, Models.Instance inst, String action)
            throws IOException, ApiException {
        Map<String, Object> instMap = new HashMap<>();
        instMap.put("id", inst.id);
        instMap.put("name", inst.name);
        instMap.put("extra", inst.extra != null ? inst.extra : new HashMap<>());
        Map<String, Object> payload = new HashMap<>();
        payload.put("instance", instMap);
        payload.put("action", action);
        payload.put("params", new HashMap<>());
        String body = post("/api/accounts/" + accountId + "/action",
                gson.toJson(payload));
        Type t = new TypeToken<Map<String, Object>>() {}.getType();
        Map<String, Object> map = gson.fromJson(body, t);
        Object jid = map.get("job_id");
        return jid instanceof String ? (String) jid : "";
    }

    public Models.Billing billing(int accountId) throws IOException, ApiException {
        return gson.fromJson(get("/api/accounts/" + accountId + "/billing"),
                Models.Billing.class);
    }
}
