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
        return instanceAction(accountId, inst, action, new HashMap<String, Object>());
    }

    public String instanceAction(int accountId, Models.Instance inst,
                                 String action, Map<String, Object> params)
            throws IOException, ApiException {
        Map<String, Object> instMap = new HashMap<>();
        instMap.put("id", inst.id);
        instMap.put("name", inst.name);
        instMap.put("extra", inst.extra != null ? inst.extra : new HashMap<>());
        Map<String, Object> payload = new HashMap<>();
        payload.put("instance", instMap);
        payload.put("action", action);
        payload.put("params", params);
        String body = post("/api/accounts/" + accountId + "/action",
                gson.toJson(payload));
        Type t = new TypeToken<Map<String, Object>>() {}.getType();
        Map<String, Object> map = gson.fromJson(body, t);
        Object jid = map.get("job_id");
        return jid instanceof String ? (String) jid : "";
    }

    public List<Models.InstanceAction> actions(int accountId)
            throws IOException, ApiException {
        Type t = new TypeToken<List<Models.InstanceAction>>() {}.getType();
        return gson.fromJson(get("/api/accounts/" + accountId + "/actions"), t);
    }

    public Models.Billing billing(int accountId) throws IOException, ApiException {
        return gson.fromJson(get("/api/accounts/" + accountId + "/billing"),
                Models.Billing.class);
    }

    public List<Models.LightsailInstance> lightsail(int accountId)
            throws IOException, ApiException {
        Type t = new TypeToken<List<Models.LightsailInstance>>() {}.getType();
        return gson.fromJson(get("/api/accounts/" + accountId + "/lightsail"), t);
    }

    public void lightsailAction(int accountId, String name, String action, String region)
            throws IOException, ApiException {
        Map<String, String> p = new HashMap<>();
        p.put("name", name);
        p.put("action", action);
        p.put("region", region);
        post("/api/accounts/" + accountId + "/lightsail/action", gson.toJson(p));
    }

    public List<Models.Distribution> cloudfront(int accountId)
            throws IOException, ApiException {
        Type t = new TypeToken<List<Models.Distribution>>() {}.getType();
        return gson.fromJson(get("/api/accounts/" + accountId + "/cloudfront"), t);
    }

    public void cloudfrontInvalidate(int accountId, String distId)
            throws IOException, ApiException {
        Map<String, Object> p = new HashMap<>();
        p.put("distribution_id", distId);
        p.put("paths", new ArrayList<String>());
        post("/api/accounts/" + accountId + "/cloudfront/invalidate", gson.toJson(p));
    }

    public void cloudfrontToggle(int accountId, String distId, boolean enable)
            throws IOException, ApiException {
        Map<String, Object> p = new HashMap<>();
        p.put("distribution_id", distId);
        p.put("enabled", enable);
        post("/api/accounts/" + accountId + "/cloudfront/toggle", gson.toJson(p));
    }

    public String quotas(int accountId) throws IOException, ApiException {
        // 配额结构各云不同，直接返回原始 JSON 由 UI 展示
        return get("/api/accounts/" + accountId + "/quotas");
    }

    public List<Models.Job> jobs() throws IOException, ApiException {
        Type t = new TypeToken<List<Models.Job>>() {}.getType();
        return gson.fromJson(get("/api/jobs?limit=50"), t);
    }

    public void jobStop(String jobId) throws IOException, ApiException {
        post("/api/jobs/" + jobId + "/stop", "{}");
    }

    public void jobDelete(String jobId) throws IOException, ApiException {
        delete("/api/jobs/" + jobId);
    }

    private String delete(String path) throws IOException, ApiException {
        Request req = new Request.Builder().url(base + path).delete().build();
        return exec(req);
    }

    private String put(String path, String json) throws IOException, ApiException {
        Request req = new Request.Builder()
                .url(base + path)
                .put(RequestBody.create(json, JSON))
                .build();
        return exec(req);
    }

    // ---------- 账号管理 ----------

    public int createAccount(String provider, String name, Map<String, String> creds)
            throws IOException, ApiException {
        Map<String, Object> p = new HashMap<>();
        p.put("provider", provider);
        p.put("name", name);
        p.put("creds", creds);
        String body = post("/api/accounts", gson.toJson(p));
        Type t = new TypeToken<Map<String, Object>>() {}.getType();
        Map<String, Object> map = gson.fromJson(body, t);
        Object id = map.get("id");
        return id instanceof Number ? ((Number) id).intValue() : 0;
    }

    public void deleteAccount(int accountId) throws IOException, ApiException {
        delete("/api/accounts/" + accountId);
    }

    public void testAccount(int accountId) throws IOException, ApiException {
        post("/api/accounts/" + accountId + "/test", "{}");
    }

    public String recycleBin() throws IOException, ApiException {
        return get("/api/recycle-bin");
    }

    public void testAll() throws IOException, ApiException {
        post("/api/accounts/test-all", "{}");
    }

    public String batchAddAccounts(String provider, List<Map<String, Object>> accounts)
            throws IOException, ApiException {
        Map<String, Object> p = new HashMap<>();
        p.put("provider", provider);
        p.put("accounts", accounts);
        return post("/api/accounts/batch", gson.toJson(p));
    }

    public String subscription(int accountId) throws IOException, ApiException {
        return get("/api/accounts/" + accountId + "/subscription");
    }

    // ---------- 设置 ----------

    public void changePassword(String oldPwd, String newPwd)
            throws IOException, ApiException {
        Map<String, String> p = new HashMap<>();
        p.put("old_password", oldPwd);
        p.put("new_password", newPwd);
        post("/api/change-password", gson.toJson(p));
    }

    public String getSettings() throws IOException, ApiException {
        return get("/api/settings");
    }

    public void updateSettings(Map<String, String> settings)
            throws IOException, ApiException {
        put("/api/settings", gson.toJson(settings));
    }

    public void tgTest() throws IOException, ApiException {
        post("/api/settings/tg-test", "{}");
    }

    // ---------- 创建实例 ----------

    public String createOptions(int accountId) throws IOException, ApiException {
        return get("/api/accounts/" + accountId + "/create-options");
    }

    public String createInstance(int accountId, Map<String, Object> params)
            throws IOException, ApiException {
        String body = post("/api/accounts/" + accountId + "/create",
                gson.toJson(params));
        Type t = new TypeToken<Map<String, Object>>() {}.getType();
        Map<String, Object> map = gson.fromJson(body, t);
        Object jid = map.get("job_id");
        return jid instanceof String ? (String) jid : "";
    }

    // ---------- Lightsail 增强 ----------

    public void lightsailChangeIp(int accountId, String name, String region)
            throws IOException, ApiException {
        Map<String, String> p = new HashMap<>();
        p.put("name", name);
        p.put("region", region);
        post("/api/accounts/" + accountId + "/lightsail/change-ip", gson.toJson(p));
    }

    // ---------- CloudFront 增强 ----------

    public void cloudfrontDelete(int accountId, String distId)
            throws IOException, ApiException {
        delete("/api/accounts/" + accountId + "/cloudfront/" + distId);
    }

    public void cloudfrontPlan(int accountId, String distId, String plan)
            throws IOException, ApiException {
        Map<String, String> p = new HashMap<>();
        p.put("distribution_id", distId);
        p.put("plan_tier", plan);
        post("/api/accounts/" + accountId + "/cloudfront/plan", gson.toJson(p));
    }

    public void cloudfrontUpdate(int accountId, String distId,
                                 Map<String, Object> fields)
            throws IOException, ApiException {
        put("/api/accounts/" + accountId + "/cloudfront/" + distId,
                gson.toJson(fields));
    }

    // ---------- 账单 Credit ----------

    public String creditsManual(int accountId) throws IOException, ApiException {
        return get("/api/accounts/" + accountId + "/credits-manual");
    }

    public void creditAdd(int accountId, String name, double amount,
                          Double startAt, Double expiresAt)
            throws IOException, ApiException {
        Map<String, Object> p = new HashMap<>();
        p.put("name", name);
        p.put("amount", amount);
        if (startAt != null) p.put("start_at", startAt);
        if (expiresAt != null) p.put("expires_at", expiresAt);
        post("/api/accounts/" + accountId + "/credits-manual", gson.toJson(p));
    }

    public void creditUpdate(int creditId, int accountId, String name, double amount,
                             Double startAt, Double expiresAt)
            throws IOException, ApiException {
        Map<String, Object> p = new HashMap<>();
        p.put("name", name);
        p.put("amount", amount);
        if (startAt != null) p.put("start_at", startAt);
        if (expiresAt != null) p.put("expires_at", expiresAt);
        put("/api/accounts/" + accountId + "/credits-manual/" + creditId,
                gson.toJson(p));
    }

    public void creditDelete(int accountId, int creditId)
            throws IOException, ApiException {
        delete("/api/accounts/" + accountId + "/credits-manual/" + creditId);
    }

    // ---------- 流量控制 ----------

    public String trafficRules(Integer accountId) throws IOException, ApiException {
        String path = "/api/traffic-rules";
        if (accountId != null) path += "?account_id=" + accountId;
        return get(path);
    }

    public void trafficRuleAdd(Map<String, Object> rule)
            throws IOException, ApiException {
        post("/api/traffic-rules", gson.toJson(rule));
    }

    public void trafficRuleDelete(int ruleId) throws IOException, ApiException {
        delete("/api/traffic-rules/" + ruleId);
    }
}
