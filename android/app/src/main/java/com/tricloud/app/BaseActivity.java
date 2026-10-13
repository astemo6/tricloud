package com.tricloud.app;

import android.content.Intent;
import android.graphics.Typeface;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.PathInterpolator;
import android.view.ContextThemeWrapper;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.ActionBarDrawerToggle;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.view.GravityCompat;
import androidx.drawerlayout.widget.DrawerLayout;
import com.google.android.material.navigation.NavigationView;
import androidx.appcompat.app.AppCompatDelegate;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.card.MaterialCardView;
import com.google.android.material.color.MaterialColors;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.materialswitch.MaterialSwitch;
import com.google.android.material.progressindicator.LinearProgressIndicator;
import com.google.android.material.snackbar.Snackbar;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.textfield.TextInputLayout;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** 纯代码构建 UI 的基础类：列表、卡片、确认框、表单弹窗。 */
public abstract class BaseActivity extends AppCompatActivity {
    protected LinearLayout body;
    protected SwipeRefreshLayout swipe;
    protected LinearProgressIndicator busy;
    /** 首屏卡片依次浮入；之后的刷新只做轻微淡入，避免下拉刷新时整页跳动。 */
    private boolean settled = false;
    private static final PathInterpolator EMPHASIZED = new PathInterpolator(0.05f, 0.7f, 0.1f, 1f);
    private int busyCount = 0;

    public static void applyTheme() {
        String m = Api.pref("theme", "system");
        AppCompatDelegate.setDefaultNightMode("dark".equals(m) ? AppCompatDelegate.MODE_NIGHT_YES
                : "light".equals(m) ? AppCompatDelegate.MODE_NIGHT_NO : AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM);
    }

    @Override
    protected void onCreate(Bundle s) {
        Api.init(this);
        applyTheme();
        super.onCreate(s);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        busy = new LinearProgressIndicator(this);
        busy.setIndeterminate(true);
        busy.setVisibility(View.INVISIBLE);
        root.addView(busy, new LinearLayout.LayoutParams(-1, -2));
        topBar = new LinearLayout(this);
        topBar.setOrientation(LinearLayout.VERTICAL);
        root.addView(topBar, new LinearLayout.LayoutParams(-1, -2));
        swipe = new SwipeRefreshLayout(this);
        ScrollView sv = new ScrollView(this);
        body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(16), dp(8), dp(16), dp(32));
        sv.setClipToPadding(false);
        sv.addView(body);
        swipe.addView(sv);
        swipe.setColorSchemeColors(MaterialColors.getColor(swipe, androidx.appcompat.R.attr.colorPrimary));
        swipe.setProgressBackgroundColorSchemeColor(MaterialColors.getColor(swipe, com.google.android.material.R.attr.colorSurfaceContainerHigh));
        swipe.setOnRefreshListener(() -> { swipe.setRefreshing(false); refresh(); });
        root.addView(swipe, new LinearLayout.LayoutParams(-1, -1));
        if (useDrawer()) setupDrawer(root); else setContentView(root);
        body.postDelayed(() -> settled = true, 900);
    }

    protected abstract void refresh();

    // ---------- Material 3 侧滑抽屉导航（分类与 Web 侧栏一致） ----------
    protected LinearLayout topBar;
    protected DrawerLayout drawer;
    protected NavigationView nav;
    private ActionBarDrawerToggle toggle;

    /** 登录页、任务日志页不显示抽屉。 */
    protected boolean useDrawer() { return true; }
    /** 当前页在抽屉里的键：home / accounts / health / … / acc_<id>。 */
    protected String navKey() { return ""; }

    static final String[][] NAV_PAGES = {
            {"accounts", "🔑 云账号"}, {"health", "🩺 账号健康度"}, {"freecheck", "🆓 免费额度体检"}, {"traffic", "📈 流量守护"},
            {"tasks", "⏱ 任务"}, {"monitors", "📡 监控"}, {"secrets", "🔐 开机密码"}, {"scripts", "📜 脚本模板"},
            {"dns", "🌐 DNS 联动"}, {"security", "🛡 安全与备份"}, {"settings", "⚙️ 设置"}};

    static Class<?> pageClass(String k) {
        switch (k) {
            case "accounts": return AccountsActivity.class;
            case "health": return HealthActivity.class;
            case "freecheck": return FreeCheckActivity.class;
            case "traffic": return TrafficActivity.class;
            case "tasks": return TasksActivity.class;
            case "monitors": return MonitorsActivity.class;
            case "secrets": return SecretsActivity.class;
            case "scripts": return ScriptsActivity.class;
            case "dns": return DnsActivity.class;
            case "security": return SecurityActivity.class;
            case "settings": return SettingsActivity.class;
            case "deleted": return DeletedActivity.class;
            default: return MainActivity.class;
        }
    }

    private void setupDrawer(View content) {
        drawer = new DrawerLayout(this);
        drawer.addView(content, new DrawerLayout.LayoutParams(-1, -1));
        nav = new NavigationView(this);
        DrawerLayout.LayoutParams lp = new DrawerLayout.LayoutParams(-2, -1);
        lp.gravity = GravityCompat.START;
        drawer.addView(nav, lp);
        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.VERTICAL);
        head.setPadding(dp(28), dp(28), dp(28), dp(12));
        TextView logo = new TextView(this);
        logo.setText("TriCloud");
        logo.setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_HeadlineSmall);
        head.addView(logo);
        TextView sub = new TextView(this);
        sub.setText("OCI · AWS · Azure · GreenCloud 多云面板");
        sub.setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_BodySmall);
        head.addView(sub);
        nav.addHeaderView(head);
        setContentView(drawer);
        if (getSupportActionBar() != null) {
            toggle = new ActionBarDrawerToggle(this, drawer, R.string.nav_open, R.string.nav_close);
            drawer.addDrawerListener(toggle);
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            toggle.syncState();
        }
        androidx.activity.OnBackPressedCallback back = new androidx.activity.OnBackPressedCallback(false) {
            @Override public void handleOnBackPressed() { drawer.closeDrawer(GravityCompat.START); }
        };
        getOnBackPressedDispatcher().addCallback(this, back);
        drawer.addDrawerListener(new DrawerLayout.SimpleDrawerListener() {
            @Override public void onDrawerOpened(View v) { back.setEnabled(true); Api.quiet("/accounts", r -> { Api.accounts = Api.arr(r); buildNav(); }); }
            @Override public void onDrawerClosed(View v) { back.setEnabled(false); }
        });
        nav.setNavigationItemSelectedListener(it -> { onNav(it); return true; });
        buildNav();
        if (Api.accounts == null) Api.quiet("/accounts", r -> { Api.accounts = Api.arr(r); buildNav(); });
    }

    private final java.util.Map<Integer, String> navIds = new java.util.HashMap<>();
    private final java.util.Map<Integer, JSONObject> navAccs = new java.util.HashMap<>();

    protected void buildNav() {
        if (nav == null) return;
        android.view.Menu m = nav.getMenu();
        m.clear();
        navIds.clear();
        navAccs.clear();
        int[] nid = {1};
        java.util.function.BiFunction<android.view.Menu, String[], android.view.MenuItem> add = (menu, kv) -> {
            int id = nid[0]++;
            android.view.MenuItem it = menu.add(0, id, id, kv[1]);
            it.setCheckable(true);
            navIds.put(id, kv[0]);
            if (kv[0].equals(navKey())) it.setChecked(true);
            return it;
        };
        add.apply(m, new String[]{"home", "🏠 总览"});
        JSONArray accs = Api.accounts == null ? new JSONArray() : Api.accounts;
        String[] dots = {"🟥", "🟧", "🟦", "🟩"};
        for (int p = 0; p < MainActivity.PROVS.length; p++) {
            android.view.SubMenu sm = null;
            for (int i = 0; i < accs.length(); i++) {
                JSONObject a = accs.optJSONObject(i);
                if (!MainActivity.PROVS[p].equals(a.optString("provider"))) continue;
                if (sm == null) sm = m.addSubMenu(0, nid[0]++, nid[0], provHeader(p));
                android.view.MenuItem it = add.apply(sm, new String[]{"acc_" + a.optInt("id"), dots[p] + "  " + a.optString("name") + (a.optInt("disabled") == 1 ? "（已停用）" : "")});
                navAccs.put(it.getItemId(), a);
            }
        }
        android.view.SubMenu mg = m.addSubMenu(0, nid[0]++, nid[0], "管理");
        for (String[] kv : NAV_PAGES) add.apply(mg, kv);
        android.view.SubMenu out = m.addSubMenu(0, nid[0]++, nid[0], "账户");
        add.apply(out, new String[]{"logout", "🚪 退出登录"}).setCheckable(false);
    }

    private static final int[] PROV_LOGOS = {R.drawable.logo_oci, R.drawable.logo_aws, R.drawable.logo_azure, R.drawable.logo_greencloud};

    /** 侧栏云厂商分组标题：官方 Logo + 名称（保持原大小写）。 */
    private CharSequence provHeader(int p) {
        android.text.SpannableString ss = new android.text.SpannableString("\u00A0 " + MainActivity.PNAMES[p]);
        android.graphics.drawable.Drawable d = androidx.core.content.ContextCompat.getDrawable(this, PROV_LOGOS[p]);
        if (d == null) return MainActivity.PNAMES[p];
        int h = Math.round(getResources().getDisplayMetrics().density * (p == 1 ? 18 : 13));
        int w = Math.round((float) d.getIntrinsicWidth() * h / Math.max(1, d.getIntrinsicHeight()));
        d.setBounds(0, 0, w, h);
        ss.setSpan(new CenterImageSpan(d, p == 1 ? Math.round(h * 0.23f) : 0), 0, 1, android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        return ss;
    }

    /** 图片与文字按垂直中线对齐（ALIGN_BASELINE 会让带下沿弧线的 AWS Logo 偏高）。 */
    static class CenterImageSpan extends android.text.style.ImageSpan {
        /** 额外下移量：AWS 的「aws」字母只占图的上半部（下面是笑脸弧线），按字母中线而不是整图中线对齐。 */
        final int shift;
        CenterImageSpan(android.graphics.drawable.Drawable d, int shift) { super(d); this.shift = shift; }
        @Override public int getSize(android.graphics.Paint paint, CharSequence text, int start, int end, android.graphics.Paint.FontMetricsInt fm) {
            android.graphics.Rect r = getDrawable().getBounds();
            if (fm != null) {
                android.graphics.Paint.FontMetricsInt pf = paint.getFontMetricsInt();
                int mid = (pf.ascent + pf.descent) / 2 + shift, half = r.height() / 2;
                fm.ascent = Math.min(pf.ascent, mid - half); fm.top = fm.ascent;
                fm.descent = Math.max(pf.descent, mid + half); fm.bottom = fm.descent;
            }
            return r.right;
        }
        @Override public void draw(android.graphics.Canvas c, CharSequence text, int start, int end, float x, int top, int y, int bottom, android.graphics.Paint paint) {
            android.graphics.drawable.Drawable d = getDrawable();
            android.graphics.Paint.FontMetricsInt pf = paint.getFontMetricsInt();
            int ty = y + (pf.ascent + pf.descent) / 2 + shift - d.getBounds().height() / 2;
            c.save(); c.translate(x, ty); d.draw(c); c.restore();
        }
    }

    private void onNav(android.view.MenuItem it) {
        String k = navIds.get(it.getItemId());
        if (k == null) return;
        drawer.closeDrawer(GravityCompat.START);
        if (k.equals(navKey())) return;
        if ("logout".equals(k)) {
            confirm("退出登录", "退出后需要重新输入面板地址和密码。", () -> Api.post(this, "/logout", null, r -> toLogin()));
            return;
        }
        JSONObject acc = navAccs.get(it.getItemId());
        drawer.postDelayed(() -> openPage(k, acc), 220);
    }

    /** 打开一级页面：总览常驻栈底，其余页面互相切换时替换当前页。 */
    public void openPage(String k, JSONObject acc) {
        Intent i;
        if (acc != null) i = new Intent(this, AccountActivity.class).putExtra("acc", acc.toString());
        else i = new Intent(this, pageClass(k));
        if ("home".equals(k)) i.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        startActivity(i);
        if (!(this instanceof MainActivity)) finish();
    }

    @Override
    public boolean onOptionsItemSelected(android.view.MenuItem item) {
        if (toggle != null && toggle.onOptionsItemSelected(item)) return true;
        return super.onOptionsItemSelected(item);
    }

    // ---------- 通用小工具 ----------
    public void copy(String label, String text) {
        android.content.ClipboardManager cm = (android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
        if (cm != null) cm.setPrimaryClip(android.content.ClipData.newPlainText(label, text));
        toast("已复制");
    }

    public void info(String title, String msg) {
        new MaterialAlertDialogBuilder(this).setTitle(title).setMessage(msg).setPositiveButton("好的", null).show();
    }

    /** 只显示一次的敏感内容（Token、开机密码）：可复制。 */
    public void secretDialog(String title, String msg, String value) {
        new MaterialAlertDialogBuilder(this).setTitle(title).setMessage(msg + "\n\n" + value)
                .setPositiveButton("复制", (d, w) -> copy(title, value)).setNegativeButton("关闭", null).show();
    }

    public static String fmtTime(long sec) {
        if (sec <= 0) return "-";
        return new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm", java.util.Locale.getDefault()).format(new java.util.Date(sec * 1000));
    }

    static final String[][] GUARD_FREE = {{"oci", "10240"}, {"aws", "100"}, {"azure", "100"}};

    /** 流量守护规则（新建 / 编辑，同 Web trafficDialog）：已有规则时回显。 */
    public void trafficDialog(int accId, String prov, String region, String instId, String name, String kind, Runnable onSaved) {
        String free = "oci".equals(prov) ? "10240" : "100";
        Api.get(this, "/traffic-guards", gr -> {
            JSONObject g = new JSONObject();
            JSONArray gs = Api.arr(gr);
            for (int i = 0; i < gs.length(); i++) {
                JSONObject x = gs.optJSONObject(i);
                if (x.optInt("account_id") == accId && instId.equals(x.optString("instance_id"))) g = x;
            }
            JSONObject gg = g;
            String rgq = MainActivity.noRegion(prov) ? "" : "&region=" + Api.enc(region);
            Api.job(this, () -> {
                try { return Api.call("GET", "/accounts/" + accId + "/traffic?instance_id=" + Api.enc(instId) + "&kind=" + kind + rgq, null); }
                catch (Exception e) { return new JSONObject().put("error", e.getMessage()); }
            }, tr -> {
                JSONObject t = Api.obj(tr);
                String use = t.has("error") ? "读取流量失败：" + t.optString("error") : "本月（" + str(t, "period", "-") + "）出站 " + t.optString("out_gb") + " GB，入站 " + t.optString("in_gb") + " GB。";
                String dir = str(gg, "direction", gg.optInt("count_in") == 1 ? "both" : "out");
                List<Field> f = new ArrayList<>();
                f.add(Field.select("mode", "统计方式", str(gg, "mode", "monthly"), new String[]{"monthly", "rolling"}, new String[]{"本月累计", "滚动窗口（最近 N 小时）"}));
                f.add(Field.num("window_hours", "窗口小时数 N（滚动窗口时生效）", str(gg, "window_hours", "24")));
                f.add(Field.select("direction", "方向", dir, new String[]{"out", "in", "both"}, new String[]{"出站", "入站", "双向（出+入）"}));
                f.add(Field.num("limit_gb", "上限 GB（免费出站 " + free + " GB/月）", str(gg, "limit_gb", free)));
                f.add(Field.num("warn_pct", "预警比例 %", str(gg, "warn_pct", "80")));
                f.add(Field.select("action", "到达上限后", str(gg, "action", "notify"), new String[]{"notify", "stop"}, new String[]{"只推送", "推送并自动停机"}));
                f.add(Field.num("shutdown_hours", "关机多少小时后自动开机（0 = 不自动开机，自动停机时生效）", str(gg, "shutdown_hours", "0")));
                f.add(Field.check("enabled", "启用这条规则", gg.optInt("enabled", 1) != 0));
                form("流量守护 · " + name, use + "\n月度模式每 30 分钟、滚动窗口每 10 分钟查一次平台指标（免费，有 5~15 分钟延迟）。到预警比例推送 Telegram；自动开机失败只告警、不重试。", f, "保存", v -> {
                    try {
                        v.put("account_id", accId).put("instance_id", instId).put("kind", kind).put("name", name);
                        if (region != null && !region.isEmpty() && !MainActivity.noRegion(prov)) v.put("region", region);
                        Api.post(this, "/traffic-guards", v, x -> {
                            JSONObject o = Api.obj(x);
                            toast(o.has("warning") && !o.isNull("warning") ? o.optString("warning") : "已保存，当前已用 " + str(o, "last_gb", "-") + " GB（" + str(o, "last_pct", "-") + "%）");
                            if (onSaved != null) onSaved.run();
                        });
                    } catch (Exception ignored) { }
                });
            });
        });
    }

    public int dp(int v) { return (int) (v * getResources().getDisplayMetrics().density + 0.5f); }

    public void setBusy(boolean b) {
        busyCount = Math.max(0, busyCount + (b ? 1 : -1));
        if (busyCount > 0) busy.show(); else busy.hide();
    }

    /** Android 的 optString 对 JSON null 返回 "null"，这里统一处理。 */
    public static String str(JSONObject o, String k, String def) {
        if (o == null || !o.has(k) || o.isNull(k)) return def;
        String v = o.optString(k, def);
        return v.isEmpty() ? def : v;
    }

    public static String join(org.json.JSONArray a) {
        if (a == null) return "";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < a.length(); i++) { if (i > 0) sb.append(", "); sb.append(a.optString(i)); }
        return sb.toString();
    }

    /** Material 3 Snackbar；页面正在关闭时退回系统 Toast。 */
    public void toast(String s) {
        View host = findViewById(android.R.id.content);
        if (isFinishing() || host == null) { Toast.makeText(getApplicationContext(), s, Toast.LENGTH_LONG).show(); return; }
        Snackbar sb = Snackbar.make(host, s, Snackbar.LENGTH_LONG);
        TextView tv = sb.getView().findViewById(com.google.android.material.R.id.snackbar_text);
        if (tv != null) tv.setMaxLines(6);
        sb.show();
    }

    public int attr(int a) { return MaterialColors.getColor(body, a); }

    /** v1.4：打开任务实时日志页（轮询）。 */
    public void openTask(int tid) {
        if (tid <= 0) return;
        startActivity(new Intent(this, TaskLogActivity.class).putExtra("tid", tid));
    }

    /** v1.4：接口返回 task_id 时自动打开任务日志，否则 Toast。 */
    public void taskOrToast(Object r, String fallback) {
        JSONObject o = Api.obj(r);
        if (o.optInt("task_id") > 0) openTask(o.optInt("task_id"));
        else toast(fallback);
    }

    public void toLogin() {
        Api.logout();
        Intent i = new Intent(this, LoginActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK | Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(i);
        finish();
    }

    // ---------- 视图构建 ----------
    protected void clear() { body.removeAllViews(); }

    protected TextView text(ViewGroup parent, String s, int sizeSp, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        // 映射到 Material 3 字体层级
        int ap = bold ? (sizeSp >= 16 ? com.google.android.material.R.style.TextAppearance_Material3_TitleMedium
                : com.google.android.material.R.style.TextAppearance_Material3_TitleSmall)
                : (sizeSp <= 12 ? com.google.android.material.R.style.TextAppearance_Material3_BodySmall
                : com.google.android.material.R.style.TextAppearance_Material3_BodyMedium);
        t.setTextAppearance(ap);
        if (sizeSp > 16) t.setTextSize(sizeSp);
        if (bold) t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        t.setTextColor(attr(com.google.android.material.R.attr.colorOnSurface));
        t.setTextIsSelectable(true);
        t.setLineSpacing(0, 1.1f);
        t.setPadding(0, dp(2), 0, dp(2));
        parent.addView(t);
        return t;
    }

    protected TextView muted(ViewGroup p, String s) {
        TextView t = text(p, s, 12, false);
        t.setTextColor(attr(com.google.android.material.R.attr.colorOnSurfaceVariant));
        return t;
    }

    protected LinearLayout card(String title) {
        // Material 3 Filled card：surfaceContainerHighest 底色、无描边、16dp 圆角
        MaterialCardView c = new MaterialCardView(this);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(6), 0, dp(6));
        c.setRadius(dp(16));
        c.setStrokeWidth(0);
        c.setCardElevation(0);
        c.setCardBackgroundColor(attr(com.google.android.material.R.attr.colorSurfaceContainerHigh));
        LinearLayout in = new LinearLayout(this);
        in.setOrientation(LinearLayout.VERTICAL);
        in.setPadding(dp(16), dp(14), dp(16), dp(14));
        c.addView(in);
        int idx = body.getChildCount();
        body.addView(c, lp);
        enter(c, idx);
        if (title != null) text(in, title, 16, true);
        return in;
    }

    /** 进入动画：首屏按顺序上浮淡入（emphasized decelerate），之后只淡入。 */
    protected void enter(View v, int idx) {
        if (!settled) {
            v.setAlpha(0f);
            v.setTranslationY(dp(16));
            v.animate().alpha(1f).translationY(0).setStartDelay(Math.min(idx, 8) * 40L)
                    .setDuration(400).setInterpolator(EMPHASIZED).start();
        } else {
            v.setAlpha(0f);
            v.animate().alpha(1f).setDuration(150).start();
        }
    }

    protected LinearLayout row(ViewGroup p) {
        // 自动换行的按钮区：用多行 LinearLayout 简单实现
        LinearLayout r = new LinearLayout(this);
        r.setOrientation(LinearLayout.VERTICAL);
        p.addView(r);
        return r;
    }

    protected Button button(ViewGroup p, String label, View.OnClickListener l) {
        LinearLayout line;
        if (p.getChildCount() == 0 || ((LinearLayout) p.getChildAt(p.getChildCount() - 1)).getChildCount() >= 3) {
            line = new LinearLayout(this);
            line.setOrientation(LinearLayout.HORIZONTAL);
            p.addView(line);
        } else line = (LinearLayout) p.getChildAt(p.getChildCount() - 1);
        boolean danger = label.contains("删除") || label.contains("终止") || label.contains("销毁");
        MaterialButton b = new MaterialButton(new ContextThemeWrapper(this,
                danger ? R.style.ThemeOverlay_TriCloud_Danger : R.style.ThemeOverlay_TriCloud_Tonal));
        b.setText(label);
        b.setAllCaps(false);
        b.setMaxLines(2);
        b.setInsetTop(dp(2));
        b.setInsetBottom(dp(2));
        b.setPadding(dp(8), b.getPaddingTop(), dp(8), b.getPaddingBottom());
        b.setOnClickListener(l);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, -2, 1);
        lp.setMargins(dp(3), 0, dp(3), 0);
        line.addView(b, lp);
        return b;
    }

    protected Button bigButton(String label, View.OnClickListener l) {
        MaterialButton b = new MaterialButton(this);   // Filled button（主操作）
        b.setText(label);
        b.setAllCaps(false);
        b.setMinHeight(dp(52));
        b.setOnClickListener(l);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(10), 0, dp(4));
        int idx = body.getChildCount();
        body.addView(b, lp);
        enter(b, idx);
        return b;
    }

    // ---------- 对话框 ----------
    public void confirm(String title, String msg, Runnable ok) {
        new MaterialAlertDialogBuilder(this).setTitle(title).setMessage(msg)
                .setPositiveButton("确认", (d, w) -> ok.run()).setNegativeButton("取消", null).show();
    }

    /** Material 3 Outlined 文本框（浮动标签）。 */
    public TextInputLayout inputLayout(String label, String hint, int inputType) {
        TextInputLayout til = new TextInputLayout(this, null, com.google.android.material.R.attr.textInputOutlinedStyle);
        til.setHint(label);
        if (hint != null) til.setPlaceholderText(hint);
        TextInputEditText e = new TextInputEditText(til.getContext());
        e.setInputType(inputType);
        til.addView(e, new LinearLayout.LayoutParams(-1, -2));
        if ((inputType & InputType.TYPE_TEXT_VARIATION_PASSWORD) == InputType.TYPE_TEXT_VARIATION_PASSWORD
                && (inputType & InputType.TYPE_CLASS_TEXT) != 0)
            til.setEndIconMode(TextInputLayout.END_ICON_PASSWORD_TOGGLE);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(6), 0, dp(2));
        til.setLayoutParams(lp);
        return til;
    }

    public static class Field {
        final String key, label, def, type;
        final String[] options, labels;
        public Field(String key, String label, String def, String type) { this(key, label, def, type, null, null); }
        public Field(String key, String label, String def, String type, String[] options, String[] labels) {
            this.key = key; this.label = label; this.def = def == null ? "" : def; this.type = type;
            this.options = options; this.labels = labels == null ? options : labels;
        }
        public static Field text(String k, String l, String d) { return new Field(k, l, d, "text"); }
        public static Field num(String k, String l, String d) { return new Field(k, l, d, "number"); }
        public static Field multi(String k, String l, String d) { return new Field(k, l, d, "multi"); }
        public static Field pass(String k, String l) { return new Field(k, l, "", "password"); }
        public static Field check(String k, String l, boolean d) { return new Field(k, l, d ? "1" : "", "check"); }
        public static Field select(String k, String l, String d, String[] opts, String[] labels) { return new Field(k, l, d, "select", opts, labels); }
    }

    public interface FormCb { void ok(JSONObject values); }

    @Override
    protected void onPostCreate(Bundle s) {
        super.onPostCreate(s);
        if (toggle != null) toggle.syncState();
    }

    public void form(String title, String note, List<Field> fields, String okText, FormCb cb) { form(title, note, fields, okText, cb, null, null); }

    /** neutral：可选的第三个按钮（如「从 OCI 读取」），点击后关闭对话框并执行。 */
    public void form(String title, String note, List<Field> fields, String okText, FormCb cb, String neutral, Runnable onNeutral) {
        ScrollView sv = new ScrollView(this);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(24), dp(4), dp(24), 0);
        sv.addView(box);
        if (note != null) muted(box, note);
        List<View> inputs = new ArrayList<>();
        for (Field f : fields) {
            if ("select".equals(f.type)) muted(box, f.label);
            View v;
            View shown = null;
            switch (f.type) {
                case "select": {
                    Spinner sp = new Spinner(this);
                    sp.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, f.labels));
                    for (int i = 0; i < f.options.length; i++) if (f.options[i].equals(f.def)) sp.setSelection(i);
                    v = sp; break;
                }
                case "check": {
                    MaterialSwitch cb2 = new MaterialSwitch(this);
                    cb2.setText(f.label);
                    cb2.setChecked(!f.def.isEmpty());
                    v = cb2; break;
                }
                default: {
                    int it = "number".equals(f.type) ? InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL
                            : "password".equals(f.type) ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
                            : "multi".equals(f.type) ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                            : InputType.TYPE_CLASS_TEXT;
                    TextInputLayout til = inputLayout(f.label, null, it);
                    EditText e = til.getEditText();
                    e.setText(f.def);
                    if ("multi".equals(f.type)) e.setMinLines(3);
                    shown = til;
                    v = e;
                }
            }
            box.addView(shown != null ? shown : v);
            inputs.add(v);
        }
        MaterialAlertDialogBuilder db = new MaterialAlertDialogBuilder(this).setTitle(title).setView(sv).setNegativeButton("取消", null);
        if (neutral != null) db.setNeutralButton(neutral, (d, w) -> onNeutral.run());
        db.setPositiveButton(okText, (d, w) -> {
                    JSONObject o = new JSONObject();
                    try {
                        for (int i = 0; i < fields.size(); i++) {
                            Field f = fields.get(i);
                            View v = inputs.get(i);
                            if (v instanceof Spinner) o.put(f.key, f.options[((Spinner) v).getSelectedItemPosition()]);
                            else if (v instanceof android.widget.CompoundButton) o.put(f.key, ((android.widget.CompoundButton) v).isChecked());
                            else o.put(f.key, ((EditText) v).getText().toString().trim());
                        }
                    } catch (Exception ignored) { }
                    cb.ok(o);
                }).show();
    }

    public void choose(String title, String[] labels, java.util.function.IntConsumer cb) {
        new MaterialAlertDialogBuilder(this).setTitle(title).setItems(labels, (d, w) -> cb.accept(w)).show();
    }
}
