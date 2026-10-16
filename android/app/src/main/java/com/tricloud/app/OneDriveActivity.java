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
    protected void onCreate(Bundle s) { super.onCreate(s); setTitle("OneDrive 备份"); refresh(); }

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
        if (d.isEmpty()) d = ("weekly".equals(c.optString("freq")) ? "每" + WD[Math.max(0, Math.min(6, c.optInt("weekday")))] + " " : "每天 ") + c.optString("time", "03:30");
        return d + "，保留 " + c.optInt("keep", 30) + " 份";
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

        LinearLayout a = card("状态");
        StringBuilder sb = new StringBuilder();
        sb.append(bound ? "✅ 已绑定" + (str(acc, "folder", "").isEmpty() ? "" : "（OneDrive / 应用 / " + str(acc, "folder", "") + "）") : "未绑定");
        sb.append("\n备份密码：").append(pwSet ? "已设置" : "未设置");
        if (s.optBoolean("ready")) {
            JSONArray nl = s.optJSONArray("next_runs_label");
            sb.append("\n定时：").append(plan(s, c)).append("（").append(s.optString("timezone")).append("）\n下次备份：")
                    .append(nl != null && nl.length() > 0 ? nl.optString(0) : str(s, "next_run", "-"));
            if (nl != null && nl.length() > 1) {
                sb.append("\n之后：");
                for (int i = 1; i < nl.length(); i++) sb.append(i > 1 ? "、" : "").append(nl.optString(i));
            }
        }
        else sb.append("\n").append(!bound ? "绑定 OneDrive 并设置备份密码后开始定时备份" : !pwSet ? "设置备份密码后开始定时备份" : "定时备份已停用");
        if (st.optLong("last_ok") > 0) sb.append("\n上次成功：").append(fmtTime(st.optLong("last_ok"))).append(" · ").append(str(st, "last_file", ""))
                .append(st.optLong("last_size") > 0 ? " · " + (st.optLong("last_size") / 1024) + " KB" : "");
        if ("failed".equals(str(st, "last_result", ""))) sb.append("\n❌ 上次失败：").append(str(st, "last_error", ""));
        if (!str(st, "auth_error", "").isEmpty()) sb.append("\n⚠️ ").append(str(st, "auth_error", ""));
        if (running > 0) sb.append("\n⏳ 备份进行中（任务 #").append(running).append("）");
        text(a, sb.toString(), 14, false);
        LinearLayout ar = row(a);
        if (bound && pwSet && running == 0) button(ar, "立即备份", v -> Api.post(this, "/onedrive/backup", null, x -> { taskOrToast(x, "已开始备份"); body.postDelayed(this::refresh, 1500); }));
        if (running > 0) button(ar, "查看进度", v -> openTask(running));
        if (bound) button(ar, "解绑 OneDrive", v -> new MaterialAlertDialogBuilder(this).setTitle("解绑 OneDrive")
                .setMessage("将删除本机保存的 OneDrive 授权，定时备份停止。\nOneDrive 上已有的备份文件不会删除，以后重新绑定还能恢复。确定解绑？")
                .setNegativeButton("取消", null)
                .setPositiveButton("解绑", (d, w) -> Api.del(this, "/onedrive/bind?confirm=true", y -> { toast("已解绑"); refresh(); })).show());

        LinearLayout ap = card("1. Azure 应用与绑定");
        muted(ap, "在 Azure 门户注册你自己的应用（公共客户端、允许个人 Microsoft 帐户、启用「允许公共客户端流」），把「应用程序(客户端) ID」填到这里。只申请 Files.ReadWrite.AppFolder + offline_access，看不到网盘里的其他文件。教程见 docs/api-credentials.md「OneDrive 备份」。");
        String cid = str(s, "client_id", "");
        text(ap, "client_id：" + (cid.isEmpty() ? "未填写" : cid) + "\n登录端点：" + s.optString("tenant", "consumers"), 13, false);
        if (!bound && !cid.isEmpty()) {   // build 22：未绑定时「绑定 OneDrive」做成醒目的主按钮放在最前面，代码点它才出现
            muted(ap, (justSaved ? "✅ 已保存。" : "") + "点下面蓝色「绑定 OneDrive」获取代码，代码会显示在下方。");
            filledButton(ap, "绑定 OneDrive", v -> Api.post(this, "/onedrive/bind", null, x -> showPending(Api.obj(x))));
        } else if (!bound) muted(ap, "先点「填写 client_id」保存，然后点蓝色「绑定 OneDrive」获取代码。");
        justSaved = false;
        LinearLayout apr = row(ap);
        button(apr, cid.isEmpty() ? "填写 client_id" : "修改 client_id", v -> form("Azure 应用", "client_id 为「应用程序(客户端) ID」；换应用会解除当前绑定。", Arrays.asList(
                Field.text("client_id", "client_id", cid),
                Field.select("tenant", "登录端点", s.optString("tenant", "consumers"), new String[]{"consumers", "common"},
                        new String[]{"consumers（个人 Microsoft 帐户，推荐）", "common（个人 + 工作/学校帐户）"})), "保存",
                f -> Api.post(this, "/onedrive/config", f, x -> {
                    JSONObject o = Api.obj(x);
                    boolean unb = o.optJSONArray("changed") != null && o.optJSONArray("changed").toString().contains("unbound");
                    boolean need = !o.optBoolean("bound") && !str(o, "client_id", "").isEmpty();
                    toast(unb ? "已保存；换了应用，原绑定已解除。点「绑定 OneDrive」获取代码" : need ? "已保存，点「绑定 OneDrive」获取代码" : "已保存");
                    justSaved = need;
                    refresh();
                })));
        if (!cid.isEmpty() && bound) button(apr, "重新绑定", v -> Api.post(this, "/onedrive/bind", null, x -> showPending(Api.obj(x))));

        LinearLayout pl = card("2. 计划、保留与备份密码");
        muted(pl, "启用：" + (c.optBoolean("enabled", true) ? "是" : "否") + " · " + plan(s, c) + "\n备份文件用备份密码加密（scrypt + AES-256-GCM）；为了无人值守定时运行，密码用面板 Fernet 密钥加密后保存在面板数据库里。");
        LinearLayout plr = row(pl);
        button(plr, "修改计划", v -> startActivity(new Intent(this, OneDriveScheduleActivity.class)
                .putExtra("cfg", c.toString()).putExtra("tz", s.optString("timezone"))));
        button(plr, pwSet ? "修改备份密码" : "设置备份密码", v -> form("备份密码", "不能为空，长度不限；恢复时需要，丢失无法恢复，请另外记下来。",
                Arrays.asList(Field.pass("password", "备份密码"), Field.pass("password2", "再输一次")), "保存", f -> {
                    if (f.optString("password").trim().isEmpty()) { toast("备份密码不能为空"); return; }
                    if (!f.optString("password").equals(f.optString("password2"))) { toast("两次输入的备份密码不一致"); return; }
                    Api.post(this, "/onedrive/config", f, x -> { toast("备份密码已保存"); refresh(); });
                }));

        LinearLayout hp = card("新装机恢复 / 离线解密");
        muted(hp, "1）装好面板并登录 2）这里填 client_id 并绑定同一个 Microsoft 帐户 3）下方列表选一份 → 恢复 → 输入备份密码 4）面板自动重启，用备份时的面板密码重新登录。\n恢复前面板会在 data/ 下自动保存一份当前数据。\n离线解密：python -m tools.decrypt_backup 文件 输出目录");

        LinearLayout ls = card("OneDrive 上的备份");
        if (!bound) { muted(ls, "绑定后显示"); return; }
        muted(ls, "读取中…");
        Api.get(this, "/onedrive/backups", x -> {
            ls.removeViews(1, ls.getChildCount() - 1);
            JSONObject o = Api.obj(x);
            JSONArray items = o.optJSONArray("items") != null ? o.optJSONArray("items") : new JSONArray();
            if (items.length() == 0) { muted(ls, "还没有备份，点「立即备份」试一次"); return; }
            muted(ls, "共 " + items.length() + " 份，保留最近 " + o.optInt("keep") + " 份。");
            for (int i = 0; i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i);
                String when = it.optString("time").isEmpty() ? it.optString("created") : it.optString("time");
                text(ls, when + " · " + Math.max(1, it.optLong("size") / 1024) + " KB\n" + it.optString("name"), 13, false);
                String iid = it.optString("id"), nm = it.optString("name");
                button(row(ls), "恢复这份", v -> restore(iid, nm));
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
        androidx.appcompat.app.AlertDialog dlg = new MaterialAlertDialogBuilder(this).setTitle("绑定 OneDrive")
                .setMessage("1）打开 " + url.replace("https://", "") + "（" + LOGIN_URL.replace("https://", "") + "）\n2）输入代码：" + code
                        + "\n3）用要存备份的 Microsoft 帐户登录并同意授权\n\n授权后这里会自动显示已绑定（" + Math.max(1, p.optInt("expires_in", 900) / 60) + " 分钟内有效）。")
                .setPositiveButton("复制代码并打开", null)
                .setNegativeButton("取消", (d, w) -> { pollGen++; Api.del(this, "/onedrive/bind?pending_only=true", null); })
                .setCancelable(false).show();
        dlg.getButton(androidx.appcompat.app.AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            copy("code", code);
            try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); } catch (Exception e) { toast("请手动打开 " + url); }
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
                if ("ok".equals(stt)) { pollGen++; dlg.dismiss(); toast("OneDrive 已绑定"); refresh(); }
                else if ("pending".equals(stt) || "slow_down".equals(stt)) poll(gen, Math.max(interval, o.optInt("interval", interval)), dlg);
                else { pollGen++; dlg.dismiss(); toast("❌ " + o.optString("message", "绑定失败")); refresh(); }
            });
        }, interval * 1000L);
    }

    private void restore(String iid, String name) {
        form("从 OneDrive 恢复", "备份：" + name + "\n⚠️ 当前全部数据（云账号、设置、任务、审计）将被这份备份覆盖。恢复前会自动在 data/ 下保存一份当前数据。",
                Arrays.asList(Field.pass("password", "这份备份的备份密码")), "下一步", f -> {
                    String pw = f.optString("password");
                    if (pw.isEmpty()) { toast("请输入备份密码"); return; }
                    new MaterialAlertDialogBuilder(this).setTitle("确认恢复")
                            .setMessage("确定用 " + name + " 覆盖当前全部数据？\n所有设备需要重新登录，面板会自动重启。")
                            .setNegativeButton("取消", null)
                            .setPositiveButton("恢复并覆盖", (d, w) -> {
                                try {
                                    Api.post(this, "/onedrive/restore", new JSONObject().put("item_id", iid).put("password", pw).put("confirm", true), x -> {
                                        JSONObject o = Api.obj(x);
                                        toast(o.optString("message", "已恢复，请重新登录"));
                                        body.postDelayed(this::toLogin, o.optBoolean("restart") ? 10000 : 1500);
                                    });
                                } catch (Exception ignored) { }
                            }).show();
                });
    }
}
