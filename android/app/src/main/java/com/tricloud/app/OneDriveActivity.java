package com.tricloud.app;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.widget.LinearLayout;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Arrays;

/** build 21 OneDrive 定期备份（同 Web pageOneDrive；build 23 计划编辑见 OneDriveScheduleActivity）：状态、设备码绑定（microsoft.com/devicelogin + 轮询）、
 *  计划 / 保留 / 备份密码、立即备份、备份列表与恢复（密码 + 二次确认）、解绑。 */
public class OneDriveActivity extends BaseActivity {
    static final String LOGIN_URL = "https://microsoft.com/devicelogin";
    static final String[] WD = {"周一", "周二", "周三", "周四", "周五", "周六", "周日"};
    private boolean justSaved = false;   // build 22：刚保存 client_id 且未绑定 → 卡片里提示「点绑定 OneDrive 获取代码」
    private int pollGen = 0;          // 每次开始绑定 / 离开页面 +1，旧的轮询自动作废
    private boolean visible = false;

    @Override
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle(getString(R.string.s0985)); refresh(); }

    @Override
    protected String navKey() { return "onedrive"; }

    @Override
    protected void onResume() { super.onResume(); visible = true; }

    @Override
    protected void onPause() { super.onPause(); visible = false; }   // 去浏览器授权时暂停轮询，回来继续

    @Override
    protected void onDestroy() { pollGen++; super.onDestroy(); }

    /** build 23：计划描述用后端的 desc（每 N 小时 / 多时间点 / 每周多选 / 每月 / Cron）；旧后端没有 desc 时退回 freq/time。 */
    static String plan(JSONObject s, JSONObject c) {
        String d = s.optString("desc", "");
        if (d.isEmpty()) d = ("weekly".equals(c.optString("freq")) ? L10n.s(R.string.s0986, WD[Math.max(0, Math.min(6, c.optInt("weekday")))]) : L10n.s(R.string.s0987)) + c.optString("time", "03:30");
        return L10n.s(R.string.s0988, d, c.optInt("keep", 30));
    }

    @Override
    protected void onRestart() { super.onRestart(); refresh(); }   // 从计划编辑页返回后刷新

    @Override
    protected void refresh() {
        Api.get(this, "/onedrive", r -> render(Api.obj(r)));
    }

    private void render(JSONObject s) {
        clear();
        JSONObject c = s.optJSONObject("cfg") != null ? s.optJSONObject("cfg") : new JSONObject();
        JSONObject st = s.optJSONObject("state") != null ? s.optJSONObject("state") : new JSONObject();
        JSONObject acc = s.optJSONObject("account") != null ? s.optJSONObject("account") : new JSONObject();
        boolean bound = s.optBoolean("bound"), pwSet = s.optBoolean("password_set");
        int running = s.optInt("running_task_id");

        LinearLayout a = card(getString(R.string.s0989));
        StringBuilder sb = new StringBuilder();
        sb.append(bound ? getString(R.string.s0991, (str(acc, "folder", "").isEmpty() ? "" : getString(R.string.s0990, str(acc, "folder", "")))) : getString(R.string.s0992));
        sb.append(getString(R.string.s0993)).append(pwSet ? getString(R.string.s0994) : getString(R.string.s0995));
        if (s.optBoolean("ready")) {
            JSONArray nl = s.optJSONArray("next_runs_label");
            sb.append(getString(R.string.s0996)).append(plan(s, c)).append("（").append(s.optString("timezone")).append(getString(R.string.s0997))
                    .append(nl != null && nl.length() > 0 ? nl.optString(0) : str(s, "next_run", "-"));
            if (nl != null && nl.length() > 1) {
                sb.append(getString(R.string.s0998));
                for (int i = 1; i < nl.length(); i++) sb.append(i > 1 ? "、" : "").append(nl.optString(i));
            }
        }
        else sb.append("\n").append(!bound ? getString(R.string.s0999) : !pwSet ? getString(R.string.s1000) : getString(R.string.s1001));
        if (st.optLong("last_ok") > 0) sb.append(getString(R.string.s1002)).append(fmtTime(st.optLong("last_ok"))).append(" · ").append(str(st, "last_file", ""))
                .append(st.optLong("last_size") > 0 ? " · " + (st.optLong("last_size") / 1024) + " KB" : "");
        if ("failed".equals(str(st, "last_result", ""))) sb.append(getString(R.string.s1003)).append(str(st, "last_error", ""));
        if (!str(st, "auth_error", "").isEmpty()) sb.append("\n⚠️ ").append(str(st, "auth_error", ""));
        if (running > 0) sb.append(getString(R.string.s1004)).append(running).append("）");
        text(a, sb.toString(), 14, false);
        LinearLayout ar = row(a);
        if (bound && pwSet && running == 0) button(ar, getString(R.string.s1005), v -> Api.post(this, "/onedrive/backup", null, x -> { taskOrToast(x, getString(R.string.s1006)); body.postDelayed(this::refresh, 1500); }));
        if (running > 0) button(ar, getString(R.string.s1007), v -> openTask(running));
        if (bound) button(ar, getString(R.string.s1008), v -> new MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s1008))
                .setMessage(getString(R.string.s1009))
                .setNegativeButton(getString(R.string.s0614), null)
                .setPositiveButton(getString(R.string.s0861), (d, w) -> Api.del(this, "/onedrive/bind?confirm=true", y -> { toast(getString(R.string.s0540)); refresh(); })).show());

        LinearLayout ap = card(getString(R.string.s1010));
        muted(ap, getString(R.string.s1011));
        String cid = str(s, "client_id", "");
        text(ap, getString(R.string.s1012, (cid.isEmpty() ? getString(R.string.s0392) : cid), s.optString("tenant", "consumers")), 13, false);
        if (!bound && !cid.isEmpty()) {   // build 22：未绑定时「绑定 OneDrive」做成醒目的主按钮放在最前面，代码点它才出现
            muted(ap, getString(R.string.s1014, (justSaved ? getString(R.string.s1013) : "")));
            filledButton(ap, getString(R.string.s1015), v -> Api.post(this, "/onedrive/bind", null, x -> showPending(Api.obj(x))));
        } else if (!bound) muted(ap, getString(R.string.s1016));
        justSaved = false;
        LinearLayout apr = row(ap);
        button(apr, cid.isEmpty() ? getString(R.string.s1017) : getString(R.string.s1018), v -> form(getString(R.string.s1019), getString(R.string.s1020), Arrays.asList(
                Field.text("client_id", "client_id", cid),
                Field.select("tenant", getString(R.string.s1021), s.optString("tenant", "consumers"), new String[]{"consumers", "common"},
                        new String[]{getString(R.string.s1022), getString(R.string.s1023)})), getString(R.string.s0089),
                f -> Api.post(this, "/onedrive/config", f, x -> {
                    JSONObject o = Api.obj(x);
                    boolean unb = o.optJSONArray("changed") != null && o.optJSONArray("changed").toString().contains("unbound");
                    boolean need = !o.optBoolean("bound") && !str(o, "client_id", "").isEmpty();
                    toast(unb ? getString(R.string.s1024) : need ? getString(R.string.s1025) : getString(R.string.s0777));
                    justSaved = need;
                    refresh();
                })));
        if (!cid.isEmpty() && bound) button(apr, getString(R.string.s1026), v -> Api.post(this, "/onedrive/bind", null, x -> showPending(Api.obj(x))));

        LinearLayout pl = card(getString(R.string.s1027));
        muted(pl, getString(R.string.s1028, (c.optBoolean("enabled", true) ? getString(R.string.s0976) : getString(R.string.s0977)), plan(s, c)));
        LinearLayout plr = row(pl);
        button(plr, getString(R.string.s1029), v -> startActivity(new Intent(this, OneDriveScheduleActivity.class)
                .putExtra("cfg", c.toString()).putExtra("tz", s.optString("timezone"))));
        button(plr, pwSet ? getString(R.string.s1030) : getString(R.string.s1031), v -> form(getString(R.string.s1032), getString(R.string.s1033),
                Arrays.asList(Field.pass("password", getString(R.string.s1032)), Field.pass("password2", getString(R.string.s1034))), getString(R.string.s0089), f -> {
                    if (f.optString("password").trim().isEmpty()) { toast(getString(R.string.s1035)); return; }
                    if (!f.optString("password").equals(f.optString("password2"))) { toast(getString(R.string.s1036)); return; }
                    Api.post(this, "/onedrive/config", f, x -> { toast(getString(R.string.s1037)); refresh(); });
                }));

        LinearLayout hp = card(getString(R.string.s1038));
        muted(hp, getString(R.string.s1039));

        LinearLayout ls = card(getString(R.string.s1040));
        if (!bound) { muted(ls, getString(R.string.s1041)); return; }
        muted(ls, getString(R.string.s0527));
        Api.get(this, "/onedrive/backups", x -> {
            ls.removeViews(1, ls.getChildCount() - 1);
            JSONObject o = Api.obj(x);
            JSONArray items = o.optJSONArray("items") != null ? o.optJSONArray("items") : new JSONArray();
            if (items.length() == 0) { muted(ls, getString(R.string.s1042)); return; }
            muted(ls, getString(R.string.s1043, items.length(), o.optInt("keep")));
            for (int i = 0; i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i);
                String when = it.optString("time").isEmpty() ? it.optString("created") : it.optString("time");
                text(ls, when + " · " + Math.max(1, it.optLong("size") / 1024) + " KB\n" + it.optString("name"), 13, false);
                String iid = it.optString("id"), nm = it.optString("name");
                button(row(ls), getString(R.string.s1044), v -> restore(iid, nm));
            }
        });
    }

    /** Material 3 Filled button（主操作），整行宽度，放在卡片里。 */
    private void filledButton(LinearLayout card, String label, View.OnClickListener l) {
        com.google.android.material.button.MaterialButton b = new com.google.android.material.button.MaterialButton(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setMinHeight(dp(52));
        b.setOnClickListener(l);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(6), 0, dp(6));
        card.addView(b, lp);
    }

    private void showPending(JSONObject p) {
        int gen = ++pollGen;
        String code = p.optString("user_code");
        String url = p.optString("verification_uri", LOGIN_URL);
        androidx.appcompat.app.AlertDialog dlg = new MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s1015))
                .setMessage(getString(R.string.s1045, url.replace("https://", ""), LOGIN_URL.replace("https://", ""), code, Math.max(1, p.optInt("expires_in", 900) / 60)))
                .setPositiveButton(getString(R.string.s1046), null)
                .setNegativeButton(getString(R.string.s0614), (d, w) -> { pollGen++; Api.del(this, "/onedrive/bind?pending_only=true", null); })
                .setCancelable(false).show();
        dlg.getButton(androidx.appcompat.app.AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            copy("code", code);
            try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); } catch (Exception e) { toast(getString(R.string.s1047, url)); }
        });
        poll(gen, Math.max(2, p.optInt("interval", 5)), dlg);
    }

    private void poll(int gen, int interval, androidx.appcompat.app.AlertDialog dlg) {
        body.postDelayed(() -> {
            if (gen != pollGen || isFinishing() || !visible) { if (gen == pollGen && !isFinishing()) poll(gen, interval, dlg); return; }
            Api.job(this, () -> Api.call("POST", "/onedrive/bind/poll", null), r -> {
                if (gen != pollGen) return;
                JSONObject o = Api.obj(r);
                String stt = o.optString("status");
                if ("ok".equals(stt)) { pollGen++; dlg.dismiss(); toast(getString(R.string.s1048)); refresh(); }
                else if ("pending".equals(stt) || "slow_down".equals(stt)) poll(gen, Math.max(interval, o.optInt("interval", interval)), dlg);
                else { pollGen++; dlg.dismiss(); toast("❌ " + o.optString("message", getString(R.string.s1049))); refresh(); }
            });
        }, interval * 1000L);
    }

    private void restore(String iid, String name) {
        form(getString(R.string.s1050), getString(R.string.s1051, name),
                Arrays.asList(Field.pass("password", getString(R.string.s1052))), getString(R.string.s0105), f -> {
                    String pw = f.optString("password");
                    if (pw.isEmpty()) { toast(getString(R.string.s1053)); return; }
                    new MaterialAlertDialogBuilder(this).setTitle(getString(R.string.s1054))
                            .setMessage(getString(R.string.s1055, name))
                            .setNegativeButton(getString(R.string.s0614), null)
                            .setPositiveButton(getString(R.string.s1056), (d, w) -> {
                                try {
                                    Api.post(this, "/onedrive/restore", new JSONObject().put("item_id", iid).put("password", pw).put("confirm", true), x -> {
                                        JSONObject o = Api.obj(x);
                                        toast(o.optString("message", getString(R.string.s1057)));
                                        body.postDelayed(this::toLogin, o.optBoolean("restart") ? 10000 : 1500);
                                    });
                                } catch (Exception ignored) { }
                            }).show();
                });
    }
}
