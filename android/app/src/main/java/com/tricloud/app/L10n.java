package com.tricloud.app;

import android.content.Context;
import android.content.res.Configuration;
import android.content.res.Resources;

/** 静态方法里取字符串（没有 Activity 实例可调 getString 时用）：按偏好 app_lang（system/zh/en）取对应语言的资源。 */
final class L10n {
    private static Context app;
    private static String cachedLang;
    private static Resources cachedRes;

    private L10n() {}

    static void init(Context ctx) { app = ctx.getApplicationContext(); }

    private static synchronized Resources res() {
        String lang = app.getSharedPreferences("tricloud", Context.MODE_PRIVATE).getString("app_lang", "system");
        if ("system".equals(lang)) return app.getResources();
        if (!lang.equals(cachedLang) || cachedRes == null) {
            Configuration cfg = new Configuration(app.getResources().getConfiguration());
            cfg.setLocale(new java.util.Locale("zh".equals(lang) ? "zh" : "en"));
            cachedRes = app.createConfigurationContext(cfg).getResources();
            cachedLang = lang;
        }
        return cachedRes;
    }

    static String s(int id) { return res().getString(id); }

    static String s(int id, Object... args) { return res().getString(id, args); }
}
