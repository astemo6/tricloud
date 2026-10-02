package com.tricloud.app;

import com.tricloud.app.api.TriCloudApi;

/** 全局持有已登录的 API 客户端。 */
public class ApiHolder {
    public static TriCloudApi api = null;
    public static String serverUrl = "";
}
