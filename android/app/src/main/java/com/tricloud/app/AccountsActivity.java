package com.tricloud.app;

import android.content.DialogInterface;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import androidx.appcompat.app.AlertDialog;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.button.MaterialButtonToggleGroup;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.textfield.TextInputLayout;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 云账号管理（同 Web pageAccounts）：列表、测活、信息、类型、编辑、代理、停用、删除；添加（粘贴自动识别）与批量添加。 */
public class AccountsActivity extends BaseActivity {
    /** {key, 标签, 占位提示, 类型(text/password/multi)}，与 Web CRED_FIELDS 一致。 */
    static final Map<String, String[][]> CRED = new LinkedHashMap<>();
    static {
        CRED.put("oci", new String[][]{{"user", "用户 OCID", "", "text"}, {"tenancy", "租户 OCID", "", "text"}, {"fingerprint", "API Key 指纹", "", "text"},
                {"region", "区域", "ap-tokyo-1", "text"}, {"key_content", "私钥 (PEM)", "-----BEGIN PRIVATE KEY-----", "multi"}, {"pass_phrase", "私钥密码（可选）", "", "password"},
                {"compartment", "区间 OCID（可选，默认根区间）", "", "text"}, {"home_region", "主区域（账单用，可选）", "", "text"},
                {"proxy", "出口代理（可选）", "http://host:port", "text"}, {"proxy_user", "代理用户名（可选）", "", "text"}, {"proxy_pass", "代理密码（可选）", "", "password"}});
        CRED.put("aws", new String[][]{{"access_key", "Access Key ID", "", "text"}, {"secret_key", "Secret Access Key", "", "password"}, {"region", "默认区域", "us-east-1", "text"},
                {"proxy", "出口代理（可选）", "socks5://host:port", "text"}, {"proxy_user", "代理用户名（可选）", "", "text"}, {"proxy_pass", "代理密码（可选）", "", "password"}});
        CRED.put("azure", new String[][]{{"tenant_id", "Tenant ID", "", "text"}, {"client_id", "Client (App) ID", "", "text"}, {"client_secret", "Client Secret", "", "password"},
                {"subscription_id", "Subscription ID", "", "text"},
                {"proxy", "出口代理（可选）", "http://host:port", "text"}, {"proxy_user", "代理用户名（可选）", "", "text"}, {"proxy_pass", "代理密码（可选）", "", "password"}});
    }
    /** 添加账号页切换按钮用的短名。 */
    static final String[] PSHORT = {"OCI", "AWS", "Azure"};
    static final Map<String, String> PROV_HINT = new LinkedHashMap<>();
    static {
        PROV_HINT.put("oci", "OCI 控制台右上角头像 → User settings（进入 My profile）→ Tokens and keys 标签 → Add API key 生成。");
        PROV_HINT.put("aws", "建议使用仅含 EC2/Lightsail/CloudFront/Service Quotas/CE 权限的 IAM 用户。");
        PROV_HINT.put("azure", "用 az ad sp create-for-rbac --role Contributor --scopes /subscriptions/<订阅 ID> 生成。");
    }

    static String credLabel(String k) {
        for (String[][] fs : CRED.values()) for (String[] f : fs) if (f[0].equals(k)) return f[1].replace("（可选）", "").replaceAll("（可选，.*）", "");
        return k;
    }

    @Override
    protected void onCreate(Bundle s) {
        super.onCreate(s);
        setTitle("云账号");
        refresh();
        if (s == null && getIntent().getBooleanExtra("add", false)) body.post(() -> addAccount(""));
    }

    @Override
    protected String navKey() { return "accounts"; }

    @Override
    protected void refresh() {
        Api.get(this, "/accounts", r -> {
            clear();
            JSONArray a = Api.arr(r);
            Api.accounts = a;
            Regions.HINTS.clear();   // build 25：/accounts 带的 machine_regions 是后端最新记录
            buildNav();
            heads.clear();
            LinearLayout top = card(null);
            muted(top, "凭证经 Fernet 加密保存在你的面板服务器，不经过任何第三方。");
            LinearLayout tr = row(top);
            button(tr, "＋ 添加", v -> addAccount(""));
            button(tr, "批量添加", v -> batchAdd(""));
            button(tr, "⚡ 一键测活", v -> testAll(a));
            button(tr, "到期提醒", v -> expiry());
            button(tr, "🗑 已删账号", v -> startActivity(new Intent(this, DeletedActivity.class)));
            if (a.length() == 0) muted(card("还没有云账号"), "点击「添加」，把控制台里复制的内容直接粘贴进去即可自动识别。");
            for (int i = 0; i < a.length(); i++) accCard(a.optJSONObject(i));
            // build 25：还没有区域记录 / 记录过期的账号，逐个（一次一个）查总览后更新这张卡片
            Regions.refreshHints(this, a, id -> {
                TextView tv = heads.get(id);
                JSONObject acc = null;
                for (int i = 0; i < a.length(); i++) if (a.optJSONObject(i).optInt("id") == id) acc = a.optJSONObject(i);
                if (tv != null && acc != null) tv.setText(headText(acc));
            });
        });
    }

    private final java.util.Map<Integer, TextView> heads = new java.util.HashMap<>();

    /** 卡片说明：云 · 有机器的区域（与默认区域不同时注明默认区域）· 类型 · 存活 · 连通 · 代理 · 停用原因 · 添加时间。 */
    private String headText(JSONObject acc) {
        boolean off = acc.optInt("disabled") == 1;
        String type = "";
        try {
            JSONObject t = str(acc, "acct_type", "").isEmpty() ? null : new JSONObject(acc.optString("acct_type"));
            if (t != null && !str(t, "label", "").isEmpty()) type = t.optString("label") + (t.has("age_days") && !t.isNull("age_days") ? " · " + t.optInt("age_days") + " 天" : "");
        } catch (Exception ignored) { }
        String rt = Regions.accountText(acc), m = Regions.machineRegion(acc), def = str(acc, "region", "");
        String note = !m.isEmpty() && !def.isEmpty() && !m.equals(def) ? "（默认 " + Regions.label(def) + "）" : "";
        return MainActivity.pname(acc.optString("provider")) + (rt.isEmpty() ? "" : " · " + rt + note) + (type.isEmpty() ? "" : " · " + type)
                + MainActivity.ageOf(acc) + MainActivity.testOf(acc)
                + "\n出口代理：" + str(acc, "proxy", "直连") + (str(acc, "proxy_user", "").isEmpty() ? "" : " · " + acc.optString("proxy_user") + (acc.optBoolean("proxy_pass_set") ? " · ●●●" : ""))
                + (off && !str(acc, "disabled_reason", "").isEmpty() ? "\n停用原因：" + acc.optString("disabled_reason") : "")
                + "\n添加于 " + fmtTime(acc.optLong("created"));
    }

    private void accCard(JSONObject acc) {
        int aid = acc.optInt("id");
        boolean off = acc.optInt("disabled") == 1;
        LinearLayout c = card(acc.optString("name") + (off ? "  [已停用]" : ""));
        heads.put(aid, muted(c, headText(acc)));
        LinearLayout row = row(c);
        button(row, "管理", v -> openPage("acc_" + aid, acc));
        button(row, "测活", v -> Api.post(this, "/accounts/" + aid + "/test", null, x -> {
            JSONObject o = Api.obj(x);
            toast(o.optBoolean("ok") ? "✅ 连通 · " + o.optInt("ms") + " ms" : "❌ " + str(o, "error", "失败"));
            refresh();
        }));
        button(row, "信息", v -> infoDialog(acc));
        button(row, "类型", v -> typeDialog(acc, false));
        button(row, "编辑", v -> editAccount(acc));
        button(row, "代理", v -> proxyDialog(acc));
        button(row, off ? "启用" : "停用", v -> toggleDisable(acc));
        button(row, "删除", v -> confirm("删除账号", "仅从面板删除凭证，不影响云上资源。删除记录会留在「已删账号」里。", () ->
                Api.del(this, "/accounts/" + aid, x -> { toast("已删除"); refresh(); })));
    }

    // ---------------- 添加账号：粘贴自动识别 ----------------
    private List<JSONObject> smartItems = new ArrayList<>();

    private void addAccount(String prefill) {
        setBusy(true);
        Api.meta(() -> { setBusy(false); if (!isFinishing()) showAddAccount(prefill); });
    }

    private void showAddAccount(String prefill) {
        ScrollView sv = new ScrollView(this);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(24), dp(4), dp(24), 0);
        sv.addView(box);

        TextInputLayout smartL = inputLayout("粘贴内容自动识别", "控制台复制、环境变量、AWS CSV、Azure 门户、OCI config 都行",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        EditText smart = smartL.getEditText();
        smart.setMinLines(3);
        smart.setMaxLines(8);
        smart.setGravity(android.view.Gravity.TOP);
        smartL.setHelperText("把复制来的一堆内容直接贴进来，自动识别云厂商并填好下面的字段");
        box.addView(smartL);
        Spinner pick = new Spinner(this);
        pick.setVisibility(View.GONE);
        box.addView(pick);
        TextView hint = muted(box, "");
        hint.setVisibility(View.GONE);
        LinearLayout batchRow = new LinearLayout(this);
        batchRow.setOrientation(LinearLayout.VERTICAL);
        box.addView(batchRow);
        batchRow.setVisibility(View.GONE);

        muted(box, "云厂商");
        MaterialButtonToggleGroup grp = new MaterialButtonToggleGroup(this);
        grp.setSingleSelection(true);
        grp.setSelectionRequired(true);
        int np = MainActivity.PROVS.length;
        int[] ids = new int[np];
        for (int i = 0; i < np; i++) {
            MaterialButton b = new MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle);
            b.setText(PSHORT[i]);
            b.setAllCaps(false);
            // 按钮平分宽度时，默认左右 24dp 内边距会把文字挤成「…」
            b.setPadding(dp(2), b.getPaddingTop(), dp(2), b.getPaddingBottom());
            b.setMinWidth(0);
            b.setMinimumWidth(0);
            b.setMaxLines(1);
            b.setEllipsize(null);
            b.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 13);
            ids[i] = View.generateViewId();
            b.setId(ids[i]);
            if (!Api.provEnabled(MainActivity.PROVS[i])) b.setVisibility(View.GONE);
            grp.addView(b, new LinearLayout.LayoutParams(0, -2, 1));
        }
        int first = 0;
        while (first < np - 1 && !Api.provEnabled(MainActivity.PROVS[first])) first++;
        box.addView(grp, new LinearLayout.LayoutParams(-1, -2));
        TextInputLayout nameL = inputLayout("备注名称", "例如 东京主号", InputType.TYPE_CLASS_TEXT);
        box.addView(nameL);
        EditText name = nameL.getEditText();
        LinearLayout credBox = new LinearLayout(this);
        credBox.setOrientation(LinearLayout.VERTICAL);
        box.addView(credBox);
        TextView provHint = muted(box, "");

        Map<String, EditText> inputs = new LinkedHashMap<>();
        String[] prov = {MainActivity.PROVS[first]};
        boolean[] filling = {false};
        String[] autoName = {""};

        Runnable rebuild = () -> {
            credBox.removeAllViews();
            inputs.clear();
            for (String[] f : CRED.get(prov[0])) {
                int it = "password".equals(f[3]) ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
                        : "multi".equals(f[3]) ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
                        : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS;
                TextInputLayout til = inputLayout(f[1], f[2].isEmpty() ? null : f[2], it);
                if ("multi".equals(f[3])) { til.getEditText().setMinLines(3); til.getEditText().setGravity(android.view.Gravity.TOP); }
                credBox.addView(til);
                inputs.put(f[0], til.getEditText());
            }
            provHint.setText(PROV_HINT.get(prov[0]));
        };
        grp.addOnButtonCheckedListener((g, id, checked) -> {
            if (!checked || filling[0]) return;
            for (int i = 0; i < np; i++) if (ids[i] == id) prov[0] = MainActivity.PROVS[i];
            rebuild.run();
        });
        grp.check(ids[first]);
        rebuild.run();

        AlertDialog dlg = new MaterialAlertDialogBuilder(this).setTitle("添加云账号").setView(sv)
                .setNegativeButton("取消", null).setPositiveButton("校验并保存", null).create();

        Runnable fill = () -> {
            int idx = Math.max(0, pick.getSelectedItemPosition());
            if (idx >= smartItems.size()) return;
            JSONObject it = smartItems.get(idx);
            String p = it.optString("provider");
            int pi = Arrays.asList(MainActivity.PROVS).indexOf(p);
            if (pi >= 0 && Api.provEnabled(p) && !p.equals(prov[0])) {
                filling[0] = true;
                prov[0] = p;
                grp.check(ids[pi]);
                filling[0] = false;
                rebuild.run();
            }
            JSONObject cred = it.optJSONObject("cred");
            if (cred != null) for (Iterator<String> k = cred.keys(); k.hasNext(); ) {
                String key = k.next();
                String val = cred.optString(key);
                EditText e = inputs.get(key);
                if (e != null && !val.isEmpty() && !"null".equals(val)) e.setText(val);
            }
            String nm = str(it, "name", "");
            String cur = name.getText().toString();
            if (!nm.isEmpty() && (cur.isEmpty() || cur.equals(autoName[0]))) { name.setText(nm); autoName[0] = nm; }
            JSONArray miss = it.optJSONArray("missing");
            StringBuilder sb = new StringBuilder("已识别为 " + MainActivity.pname(p));
            if (miss != null && miss.length() > 0) {
                sb.append("，还缺：");
                for (int i = 0; i < miss.length(); i++) sb.append(i > 0 ? "、" : "").append(credLabel(miss.optString(i)));
            } else sb.append("，字段齐全");
            if (!str(it, "error", "").isEmpty()) sb.append("；").append(it.optString("error"));
            if (smartItems.size() > 1) sb.append("。共识别到 ").append(smartItems.size()).append(" 个账号，可在上面切换，或点「全部批量添加」");
            hint.setText(sb.toString());
            hint.setVisibility(View.VISIBLE);
        };
        pick.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> p, View v, int pos, long id) { fill.run(); }
            @Override public void onNothingSelected(AdapterView<?> p) { }
        });

        Handler h = new Handler(Looper.getMainLooper());
        int[] seq = {0};
        Runnable parse = () -> {
            String t = smart.getText().toString();
            int my = ++seq[0];
            if (t.trim().isEmpty()) {
                smartItems = new ArrayList<>();
                pick.setVisibility(View.GONE);
                hint.setVisibility(View.GONE);
                batchRow.setVisibility(View.GONE);
                return;
            }
            Api.job(this, () -> {
                try { return Api.call("POST", "/accounts/parse", new JSONObject().put("text", t)); }
                catch (Exception e) { return new JSONObject().put("_error", e.getMessage()); }
            }, r -> {
                if (my != seq[0] || !dlg.isShowing()) return;   // 已有更新的输入
                JSONObject o = Api.obj(r);
                if (o.has("_error")) { hint.setText("❌ " + o.optString("_error")); hint.setVisibility(View.VISIBLE); return; }
                JSONArray items = o.optJSONArray("items");
                List<JSONObject> l = new ArrayList<>();
                for (int i = 0; items != null && i < items.length(); i++) if (!str(items.optJSONObject(i), "provider", "").isEmpty()) l.add(items.optJSONObject(i));
                smartItems = l;
                if (l.isEmpty()) {
                    pick.setVisibility(View.GONE);
                    batchRow.setVisibility(View.GONE);
                    hint.setText("没有识别到云账号凭证");
                    hint.setVisibility(View.VISIBLE);
                    return;
                }
                String[] labels = new String[l.size()];
                for (int i = 0; i < labels.length; i++) labels[i] = (i + 1) + ". " + MainActivity.pname(l.get(i).optString("provider")) + " · " + str(l.get(i), "name", "未命名");
                pick.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels));
                pick.setVisibility(l.size() > 1 ? View.VISIBLE : View.GONE);
                batchRow.setVisibility(l.size() > 1 ? View.VISIBLE : View.GONE);
                fill.run();
            });
        };
        smart.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int a, int b, int c) { }
            @Override public void onTextChanged(CharSequence s, int a, int b, int c) { }
            @Override public void afterTextChanged(Editable s) { h.removeCallbacks(parse); h.postDelayed(parse, 400); }
        });
        button(batchRow, "全部批量添加", v -> { String t = smart.getText().toString(); dlg.dismiss(); batchAdd(t); });

        dlg.show();
        if (prefill != null && !prefill.isEmpty()) smart.setText(prefill);
        dlg.getButton(DialogInterface.BUTTON_POSITIVE).setOnClickListener(v -> {
            try {
                JSONObject cred = new JSONObject();
                for (Map.Entry<String, EditText> e : inputs.entrySet()) cred.put(e.getKey(), e.getValue().getText().toString().trim());
                JSONObject b = new JSONObject().put("provider", prov[0]).put("name", name.getText().toString().trim());
                b.put("cred", cred);
                toast("正在校验凭证…");
                Api.post(this, "/accounts", b, r -> { dlg.dismiss(); toast("账号已添加"); refresh(); });
            } catch (Exception e) { toast(e.getMessage()); }
        });
    }

    // ---------------- 批量添加 ----------------
    private void batchAdd(String prefill) {
        form("批量添加云账号", "直接粘贴复制来的一堆内容：控制台页面、环境变量、AWS accessKeys.csv、Azure 应用注册页、OCI config + 私钥，或 JSON，"
                        + "混在一起也能自动识别、自动拆分成多个账号（最多 50 个）。每条都会在线校验凭证，结果逐条显示。",
                Arrays.asList(Field.multi("text", "粘贴内容", prefill),
                        Field.select("provider", "无法判断云厂商时按", "", new String[]{"", "oci", "aws", "azure"}, new String[]{"不猜测（报错）", "Oracle Cloud", "AWS", "Azure"}),
                        Field.check("dry_run", "只检查格式，不校验、不保存", false)), "校验并添加", v -> {
            if (v.optString("text").isEmpty()) { toast("请粘贴内容"); return; }
            try {
                JSONObject b = new JSONObject().put("text", v.optString("text")).put("dry_run", v.optBoolean("dry_run"));
                if (!v.optString("provider").isEmpty()) b.put("provider", v.optString("provider"));
                toast("正在逐条校验…");
                Api.post(this, "/accounts/batch", b, r -> {
                    JSONObject o = Api.obj(r);
                    JSONArray rs = o.optJSONArray("results");
                    StringBuilder sb = new StringBuilder();
                    for (int i = 0; rs != null && i < rs.length(); i++) {
                        JSONObject x = rs.optJSONObject(i);
                        sb.append(x.optBoolean("ok") ? "✅ " : "❌ ").append(x.optInt("index")).append(". ")
                                .append(x.isNull("provider") ? "-" : MainActivity.pname(x.optString("provider"))).append(" · ").append(str(x, "name", "-"));
                        if (x.optBoolean("ok")) sb.append(x.optBoolean("dry_run") ? "  格式正确" : "  已添加").append(x.optInt("ms") > 0 ? "  " + x.optInt("ms") + " ms" : "");
                        else sb.append("\n    ").append(str(x, "error", ""));
                        sb.append("\n");
                    }
                    boolean dry = v.optBoolean("dry_run");
                    MaterialAlertDialogBuilder d = new MaterialAlertDialogBuilder(this)
                            .setTitle("批量添加结果：成功 " + o.optInt("ok") + " / 共 " + o.optInt("total")).setMessage(sb.toString().trim());
                    if (dry && o.optInt("ok") > 0) d.setPositiveButton("正式添加", (dd, w) -> {
                        try {
                            JSONObject b2 = new JSONObject(b.toString()).put("dry_run", false);
                            Api.post(this, "/accounts/batch", b2, y -> { toast("已添加 " + Api.obj(y).optInt("ok") + " 个"); refresh(); });
                        } catch (Exception ignored) { }
                    }).setNegativeButton("取消", null);
                    else d.setPositiveButton("好的", (dd, w) -> refresh());
                    d.show();
                });
            } catch (Exception e) { toast(e.getMessage()); }
        });
    }

    // ---------------- 一键测活 / 到期 ----------------
    private void testAll(JSONArray a) {
        List<String> ps = new ArrayList<>();
        for (int i = 0; i < a.length(); i++) if (!ps.contains(a.optJSONObject(i).optString("provider"))) ps.add(a.optJSONObject(i).optString("provider"));
        if (ps.size() <= 1) { runTestAll(""); return; }
        String[] labels = new String[ps.size() + 1];
        labels[0] = "全部账号";
        for (int i = 0; i < ps.size(); i++) labels[i + 1] = MainActivity.pname(ps.get(i));
        choose("测活范围", labels, i -> runTestAll(i == 0 ? "" : ps.get(i - 1)));
    }

    private void runTestAll(String prov) {
        toast("正在并发测活…");
        JSONObject b = new JSONObject();
        try { if (!prov.isEmpty()) b.put("provider", prov); } catch (Exception ignored) { }
        Api.post(this, "/accounts/test-all", b, r -> {
            JSONObject o = Api.obj(r);
            JSONArray rs = o.optJSONArray("results");
            StringBuilder sb = new StringBuilder();
            for (int i = 0; rs != null && i < rs.length(); i++) {
                JSONObject x = rs.optJSONObject(i);
                sb.append(x.optBoolean("ok") ? "✅ " : "❌ ").append(x.optString("name")).append("  ").append(x.optInt("ms")).append(" ms");
                if (!x.optBoolean("ok")) sb.append("\n    ").append(str(x, "error", ""));
                sb.append("\n");
            }
            new MaterialAlertDialogBuilder(this).setTitle("测活：" + o.optInt("ok") + "/" + o.optInt("total") + " 连通，用时 "
                            + String.format(java.util.Locale.US, "%.1f", o.optInt("ms") / 1000.0) + " 秒")
                    .setMessage(sb.toString().trim()).setPositiveButton("好的", (d, w) -> refresh()).show();
        });
    }

    private void expiry() {
        Api.get(this, "/expiry-alerts", r -> {
            JSONArray a = Api.arr(r);
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < a.length(); i++) {
                JSONObject x = a.optJSONObject(i);
                sb.append("⏰ ").append(x.optString("account_name")).append(" · ").append(x.optString("name")).append("\n    ").append(x.optString("date"))
                        .append(x.optBoolean("estimated") ? "（估算）" : "").append("，").append(x.optInt("days_left") == 0 ? "今天到期" : "剩 " + x.optInt("days_left") + " 天").append("\n");
            }
            info("30 天内到期", sb.length() == 0 ? "没有即将到期的 Credit 或优惠" : sb.toString().trim());
        });
    }

    // ---------------- 信息 / 类型 / 停用 / 代理 / 编辑 ----------------
    private void infoDialog(JSONObject a) { infoDialog(a, str(a, "cloud_created_at", "")); }

    private void infoDialog(JSONObject a, String created) {
        int aid = a.optInt("id");
        boolean oci = "oci".equals(a.optString("provider")), az = "azure".equals(a.optString("provider"));
        List<Field> f = new ArrayList<>();
        f.add(Field.text("cloud_created_at", "云账号创建日期 YYYY-MM-DD", created));
        if (az) f.add(Field.text("edu_expires_at", "教育优惠到期日（留空 = 创建日期 + 12 个月估算）", str(a, "edu_expires_at", "")));
        String note = "用于计算存活天数" + (az ? "、估算教育优惠到期日" : "") + "。"
                + (oci ? "OCI 可自动读取租户创建时间。" : "AWS / Azure 没有免费接口能读到账号创建日期，请按控制台或注册邮件填写。");
        form("账号信息 · " + a.optString("name"), note, f, "保存",
                v -> Api.async(this, "PATCH", "/accounts/" + aid, v, x -> { toast("已保存"); refresh(); }),
                oci ? "从 OCI 读取" : null,
                () -> Api.post(this, "/accounts/" + aid + "/detect-created", new JSONObject(), x -> {
                    String d = Api.obj(x).optString("cloud_created_at");
                    toast("已读取：" + d);
                    infoDialog(a, d);
                }));
    }

    private void typeDialog(JSONObject a, boolean force) {
        toast("查询账号类型…");
        Api.get(this, "/accounts/" + a.optInt("id") + "/account-type" + (force ? "?refresh=1" : ""), x -> {
            JSONObject r = Api.obj(x);
            StringBuilder sb = new StringBuilder("类型：" + str(r, "label", "-"));
            String[][] kv = {{"plan_type", "计划"}, {"account_type", "账户"}, {"upgrade_state", "升级状态"}, {"time_start", "开户日期"}, {"home_region", "主区域"}, {"state", "订阅状态"}};
            for (String[] k : kv) if (!str(r, k[0], "").isEmpty()) sb.append("\n").append(k[1]).append("：").append("home_region".equals(k[0]) ? Regions.label(r.optString(k[0])) : r.optString(k[0]));
            if (r.has("age_days") && !r.isNull("age_days")) sb.append("\n开户天数：").append(r.optInt("age_days")).append(" 天");
            String extra = str(r, "error", str(r, "hint", ""));
            if (!extra.isEmpty()) sb.append("\n\n").append(extra);
            sb.append("\n\n查询于 ").append(fmtTime(r.optLong("checked_at")));
            new MaterialAlertDialogBuilder(this).setTitle("账号类型 · " + a.optString("name")).setMessage(sb.toString())
                    .setPositiveButton("重新查询", (d, w) -> typeDialog(a, true)).setNegativeButton("关闭", (d, w) -> refresh()).show();
        });
    }

    private void toggleDisable(JSONObject a) {
        int aid = a.optInt("id");
        try {
            if (a.optInt("disabled") == 1) {
                Api.post(this, "/accounts/" + aid + "/disable", new JSONObject().put("disabled", false), x -> { toast("已启用"); refresh(); });
                return;
            }
        } catch (Exception ignored) { }
        form("停用账号", "停用「" + a.optString("name") + "」（比如被封号）：\n• 不再测活、不监控、不跑流量守护；\n• 该账号运行中的任务（抢机等）全部停止；\n• 凭证和云上资源都不动，随时可以重新启用。",
                Arrays.asList(Field.text("reason", "原因（可选，如 被封号 / 欠费）", "")), "停用", v -> {
            try {
                Api.post(this, "/accounts/" + aid + "/disable", v.put("disabled", true), x -> {
                    JSONArray st = Api.obj(x).optJSONArray("stopped_tasks");
                    toast("已停用" + (st != null && st.length() > 0 ? "，停止了 " + st.length() + " 个任务" : ""));
                    refresh();
                });
            } catch (Exception ignored) { }
        });
    }

    private void proxyDialog(JSONObject a) {
        boolean has = !str(a, "proxy", "").isEmpty();
        boolean passSet = a.optBoolean("proxy_pass_set");
        List<Field> f = new ArrayList<>();
        f.add(Field.text("proxy", "代理地址（留空 = 不改" + (has ? "" : "，直连") + "）", ""));
        f.add(Field.text("proxy_user", "代理用户名（可选）", str(a, "proxy_user", "")));
        f.add(Field.pass("proxy_pass", passSet ? "代理密码（已设置，留空不改）" : "代理密码（可选）"));
        if (passSet) f.add(Field.check("proxy_pass_clear", "清除代理密码", false));
        if (has) f.add(Field.check("clear_all", "改为直连（清除代理地址、用户名和密码）", false));
        form("出口代理", "该账号的所有云 API 请求经此代理发出（固定出口 IP、避免多号同 IP 关联）。\n当前：" + str(a, "proxy", "直连")
                + (str(a, "proxy_user", "").isEmpty() ? "" : " · 用户 " + a.optString("proxy_user")) + (passSet ? " · 已设密码" : "")
                + "\n支持 http://host:port 或 socks5://host:port，也兼容 http://user:pass@host:port。", f, "保存", v -> {
            try {
                JSONObject b = new JSONObject();
                if (v.optBoolean("clear_all")) b.put("proxy", "");
                else {
                    if (!v.optString("proxy").isEmpty()) b.put("proxy", v.optString("proxy"));
                    else if (!has && (!v.optString("proxy_user").isEmpty() || !v.optString("proxy_pass").isEmpty())) { toast("请先填写代理地址"); return; }
                    if (!v.optString("proxy_user").equals(str(a, "proxy_user", ""))) b.put("proxy_user", v.optString("proxy_user"));
                    if (!v.optString("proxy_pass").isEmpty()) b.put("proxy_pass", v.optString("proxy_pass"));
                    if (v.optBoolean("proxy_pass_clear")) b.put("proxy_pass_clear", true);
                }
                if (b.length() == 0) return;
                Api.async(this, "PATCH", "/accounts/" + a.optInt("id"), b, x -> { toast("已保存"); refresh(); });
            } catch (Exception ignored) { }
        });
    }

    /** 编辑账号：非敏感字段回显，密钥类留空不改；代理地址 / 用户名 / 密码分开填写。 */
    private void editAccount(JSONObject acc) {
        int aid = acc.optInt("id");
        Api.get(this, "/accounts/" + aid + "/detail", r -> {
            JSONObject d = Api.obj(r);
            JSONObject fields = d.optJSONObject("fields");
            List<Field> f = new ArrayList<>();
            f.add(Field.text("name", "备注名称", d.optString("name")));
            List<String> keys = new ArrayList<>();
            if (fields != null) for (Iterator<String> it = fields.keys(); it.hasNext(); ) {
                String k = it.next();
                keys.add(k);
                Object v = fields.opt(k);
                String lab = credLabel(k);
                if (v instanceof String) f.add("servers_text".equals(k) ? Field.multi("c_" + k, lab, (String) v) : Field.text("c_" + k, lab, (String) v));
                else {
                    JSONObject o = (JSONObject) v;
                    String l2 = lab + (o.optBoolean("set") ? "（已设置" + (o.optString("hint").isEmpty() ? "" : " " + o.optString("hint")) + "，留空不改）" : "（未设置）");
                    f.add("key_content".equals(k) || "servers_text".equals(k) ? Field.multi("c_" + k, l2, "") : (k.contains("secret") || k.contains("pass") ? Field.pass("c_" + k, l2) : Field.text("c_" + k, l2, "")));
                }
            }
            f.add(Field.text("proxy", "代理地址（当前 " + (d.optString("proxy").isEmpty() ? "直连" : d.optString("proxy")) + "；留空不改）", ""));
            f.add(Field.text("proxy_user", "代理用户名", d.optString("proxy_user")));
            f.add(Field.pass("proxy_pass", d.optBoolean("proxy_pass_set") ? "代理密码（已设置，留空不改）" : "代理密码（可选）"));
            if (d.optBoolean("proxy_pass_set")) f.add(Field.check("proxy_pass_clear", "清除代理密码", false));
            f.add(Field.check("direct", "改为直连（清除代理）", false));
            form("编辑 · " + d.optString("name"), "修改了凭证时会先测活，通过才保存。代理地址出于安全只回显主机，修改代理请重新填写完整地址。", f, "保存", v -> {
                try {
                    JSONObject b = new JSONObject().put("name", v.optString("name"));
                    JSONObject cred = new JSONObject();
                    for (String k : keys) cred.put(k, v.optString("c_" + k));
                    if (cred.length() > 0) b.put("cred", cred);
                    if (v.optBoolean("direct")) b.put("proxy", "");
                    else {
                        if (!v.optString("proxy").isEmpty()) b.put("proxy", v.optString("proxy"));
                        if (!v.optString("proxy_user").equals(d.optString("proxy_user"))) b.put("proxy_user", v.optString("proxy_user"));
                        if (!v.optString("proxy_pass").isEmpty()) b.put("proxy_pass", v.optString("proxy_pass"));
                        if (v.optBoolean("proxy_pass_clear")) b.put("proxy_pass_clear", true);
                    }
                    Api.async(this, "PATCH", "/accounts/" + aid, b, x -> { toast("已保存"); refresh(); });
                } catch (Exception e) { toast(e.getMessage()); }
            });
        });
    }
}
