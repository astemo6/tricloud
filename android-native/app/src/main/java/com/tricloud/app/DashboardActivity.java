package com.tricloud.app;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.ListView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

/** 账号功能菜单：根据云厂商显示可用功能入口。 */
public class DashboardActivity extends Activity {

    private static class MenuItem {
        final String title;
        final String desc;
        final Class<?> cls;
        MenuItem(String title, String desc, Class<?> cls) {
            this.title = title;
            this.desc = desc;
            this.cls = cls;
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_dashboard);

        int accountId = getIntent().getIntExtra("account_id", 0);
        String accountName = getIntent().getStringExtra("account_name");
        String provider = getIntent().getStringExtra("provider");

        ((TextView) findViewById(R.id.tvTitle)).setText(
                accountName != null ? accountName : "");
        ((TextView) findViewById(R.id.tvProvider)).setText(
                provider != null ? provider.toUpperCase() : "");

        List<MenuItem> menu = new ArrayList<>();
        menu.add(new MenuItem("实例", "EC2 / 虚拟机 / Droplet", InstanceActivity.class));
        menu.add(new MenuItem("创建实例", "新建云服务器", CreateInstanceActivity.class));
        if ("aws".equals(provider)) {
            menu.add(new MenuItem("Lightsail", "轻量实例管理", LightsailActivity.class));
            menu.add(new MenuItem("CloudFront", "CDN 分发管理", CloudFrontActivity.class));
        }
        if ("azure".equals(provider)) {
            menu.add(new MenuItem("流量控制", "超限自动关机", TrafficActivity.class));
        }
        if ("oci".equals(provider)) {
            menu.add(new MenuItem("订阅信息", "租户订阅详情", SubscriptionActivity.class));
        }
        menu.add(new MenuItem("配额", "查询云资源配额余量", QuotaActivity.class));
        menu.add(new MenuItem("账单", "本月费用明细", BillingActivity.class));

        ListView lv = findViewById(R.id.lvMenu);
        ArrayAdapter<MenuItem> adapter = new ArrayAdapter<MenuItem>(this,
                android.R.layout.simple_list_item_2, android.R.id.text1, menu) {
            @Override
            public View getView(int position, View convertView, ViewGroup parent) {
                View v = super.getView(position, convertView, parent);
                MenuItem m = getItem(position);
                TextView t1 = v.findViewById(android.R.id.text1);
                TextView t2 = v.findViewById(android.R.id.text2);
                t1.setText(m.title);
                t1.setTextColor(0xFFE6E9F0);
                t1.setTextSize(16);
                t2.setText(m.desc);
                t2.setTextColor(0xFF8B93AD);
                return v;
            }
        };
        lv.setAdapter(adapter);
        lv.setOnItemClickListener((AdapterView<?> p, View v, int pos, long id) -> {
            MenuItem m = menu.get(pos);
            Intent i = new Intent(this, m.cls);
            i.putExtra("account_id", accountId);
            i.putExtra("account_name", accountName);
            i.putExtra("provider", provider);
            startActivity(i);
        });
    }
}
