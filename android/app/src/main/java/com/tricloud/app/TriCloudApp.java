package com.tricloud.app;

import android.app.Application;

import com.google.android.material.color.DynamicColors;

/** Android 12+ 跟随壁纸动态取色（Material You）；更早的系统用品牌蓝配色。 */
public class TriCloudApp extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        L10n.init(this);
        DynamicColors.applyToActivitiesIfAvailable(this);
    }
}
