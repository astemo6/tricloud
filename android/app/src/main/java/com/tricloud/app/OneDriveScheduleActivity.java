package com.tricloud.app;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.View;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipDrawable;
import com.google.android.material.chip.ChipGroup;
import com.google.android.material.materialswitch.MaterialSwitch;
import com.google.android.material.textfield.TextInputLayout;
import com.google.android.material.timepicker.MaterialTimePicker;
import com.google.android.material.timepicker.TimeFormat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/** build 23 OneDrive 备份计划编辑（同 Web odSchedForm）：每 N 小时 / 每天多个时间点 / 每周多选 / 每月日期（含月末）/ Cron，
 *  修改时实时调用 POST /onedrive/schedule/preview 显示「接下来 3 次」，非法配置在预览卡片里直接显示后端的友好错误。Material 3 Chip / TimePicker。 */
public class OneDriveScheduleActivity extends BaseActivity {
    static final String[] MODES = {"hourly", "daily", "weekly", "monthly", "cron"};
    static final String[] MODE_LABELS = {"每 N 小时", "每天", "每周", "每月", "Cron"};
    private JSONObject cfg = new JSONObject();
    private String tz = "";
    private String mode = "daily";
    private final List<String> times = new ArrayList<>();
    private MaterialSwitch enabled;
    private EditText everyHours, minute, startHour, cron, keep;
    private ChipGroup timeGroup, wdGroup, dayGroup;
    private Chip lastDay;
    private LinearLayout secHourly, secTimes, secWeekly, secMonthly, secCron;
    private TextView preview;
    private final Handler h = new Handler(Looper.getMainLooper());
    private int seq = 0;
    private boolean built = false;

    @Override
    protected boolean useDrawer() { return false; }

    @Override
    protected void onCreate(Bundle s) {
        super.onCreate(s);
        setTitle("备份计划");
        try { cfg = new JSONObject(getIntent().getStringExtra("cfg")); } catch (Exception ignored) { }
        tz = getIntent().getStringExtra("tz") == null ? "" : getIntent().getStringExtra("tz");
        refresh();
    }

    @Override
    protected void onDestroy() { seq++; h.removeCallbacksAndMessages(null); super.onDestroy(); }

    private Chip chip(String label, boolean checkable) {
        Chip c = new Chip(this);
        c.setChipDrawable(ChipDrawable.createFromAttributes(this, null, 0,
                checkable ? com.google.android.material.R.style.Widget_Material3_Chip_Filter : com.google.android.material.R.style.Widget_Material3_Chip_Input));
        c.setText(label);
        c.setCheckable(checkable);
        return c;
    }

    private ChipGroup chipGroup(LinearLayout parent, boolean single) {
        ChipGroup g = new ChipGroup(this);
        g.setSingleSelection(single);
        g.setSelectionRequired(single);
        g.setChipSpacingHorizontal(dp(6));
        parent.addView(g, new LinearLayout.LayoutParams(-1, -2));
        return g;
    }

    private EditText num(LinearLayout parent, String label, String value, String helper) {
        TextInputLayout til = inputLayout(label, null, InputType.TYPE_CLASS_NUMBER);
        if (helper != null) til.setHelperText(helper);
        EditText e = til.getEditText();
        e.setText(value);
        e.addTextChangedListener(watcher());
        parent.addView(til);
        return e;
    }

    private TextWatcher watcher() {
        return new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int a, int b, int c) { }
            @Override public void onTextChanged(CharSequence s, int a, int b, int c) { }
            @Override public void afterTextChanged(Editable s) { schedulePreview(); }
        };
    }

    private LinearLayout section(LinearLayout parent) {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        parent.addView(l, new LinearLayout.LayoutParams(-1, -2));
        return l;
    }

    @Override
    protected void refresh() {
        if (built) { schedulePreview(); return; }
        built = true;
        clear();
        mode = cfg.optString("mode", "weekly".equals(cfg.optString("freq")) ? "weekly" : "daily");
        times.clear();
        JSONArray ts = cfg.optJSONArray("times");
        if (ts != null) for (int i = 0; i < ts.length(); i++) times.add(ts.optString(i));
        if (times.isEmpty()) times.add(cfg.optString("time", "03:30"));

        LinearLayout a = card("频率");
        muted(a, "时间按面板时区（" + tz + "）。两次备份至少间隔 30 分钟。");
        enabled = new MaterialSwitch(this);
        enabled.setText("启用定时备份");
        enabled.setChecked(cfg.optBoolean("enabled", true));
        a.addView(enabled);
        ChipGroup mg = chipGroup(a, true);
        for (int i = 0; i < MODES.length; i++) {
            Chip c = chip(MODE_LABELS[i], true);
            c.setId(View.generateViewId());
            c.setTag(MODES[i]);
            c.setChecked(MODES[i].equals(mode));
            mg.addView(c);
        }
        mg.setOnCheckedStateChangeListener((g, ids) -> {
            if (ids.isEmpty()) return;
            Object t = g.findViewById(ids.get(0)).getTag();
            mode = String.valueOf(t);
            showSections();
            schedulePreview();
        });

        LinearLayout b = card("设置");
        secHourly = section(b);
        everyHours = num(secHourly, "每隔几小时（1–24）", String.valueOf(cfg.optInt("every_hours", 6)), null);
        minute = num(secHourly, "第几分钟（0–59）", String.valueOf(cfg.optInt("minute", 0)), "0 = 整点");
        startHour = num(secHourly, "起始小时（0–23）", String.valueOf(cfg.optInt("start_hour", 0)), "每天从这个小时起按间隔对齐");

        secTimes = section(b);
        text(secTimes, "时间点（可多个）", 14, true);
        timeGroup = chipGroup(secTimes, false);
        MaterialButton add = new MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle);
        add.setText("添加时间");
        add.setAllCaps(false);
        add.setOnClickListener(v -> pickTime());
        secTimes.addView(add, new LinearLayout.LayoutParams(-2, -2));
        renderTimes();

        secWeekly = section(b);
        text(secWeekly, "星期（可多选）", 14, true);
        wdGroup = chipGroup(secWeekly, false);
        JSONArray wds = cfg.optJSONArray("weekdays");
        for (int i = 0; i < 7; i++) {
            Chip c = chip(OneDriveActivity.WD[i], true);
            c.setTag(i);
            c.setChecked(contains(wds, i) || (wds == null && cfg.optInt("weekday", 0) == i));
            c.setOnCheckedChangeListener((v, on) -> schedulePreview());
            wdGroup.addView(c);
        }

        secMonthly = section(b);
        text(secMonthly, "日期（可多选）", 14, true);
        muted(secMonthly, "没有这一天的月份会跳过（如 31 日），每月最后一天请选「月末」。");
        dayGroup = chipGroup(secMonthly, false);
        JSONArray days = cfg.optJSONArray("days");
        for (int d = 1; d <= 31; d++) {
            Chip c = chip(String.valueOf(d), true);
            c.setTag(d);
            c.setChecked(days == null ? d == 1 : contains(days, d));
            c.setOnCheckedChangeListener((v, on) -> schedulePreview());
            dayGroup.addView(c);
        }
        lastDay = chip("月末", true);
        lastDay.setChecked(cfg.optBoolean("last_day"));
        lastDay.setOnCheckedChangeListener((v, on) -> schedulePreview());
        dayGroup.addView(lastDay);

        secCron = section(b);
        TextInputLayout ct = inputLayout("Cron 表达式（分 时 日 月 周）", "30 3 * * 1-5", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        ct.setHelperText("支持 * , - / 和数字、mon/jan 等缩写、@daily。\n例：30 3 * * 1-5 工作日 03:30；0 */6 * * * 每 6 小时；0 4 1,15 * * 每月 1、15 日。日和周都指定时满足任一即可。");
        cron = ct.getEditText();
        cron.setText(cfg.optString("cron", "30 3 * * *"));
        cron.setTypeface(android.graphics.Typeface.MONOSPACE);
        cron.addTextChangedListener(watcher());
        secCron.addView(ct);

        LinearLayout k = card("保留");
        keep = num(k, "保留最近几份（1–365）", String.valueOf(cfg.optInt("keep", 30)), "多余的自动删除");

        LinearLayout p = card("接下来 3 次");
        preview = text(p, "计算中…", 14, false);

        bigButton("保存计划", v -> save());
        showSections();
        schedulePreview();
    }

    private static boolean contains(JSONArray a, int v) {
        if (a == null) return false;
        for (int i = 0; i < a.length(); i++) if (a.optInt(i, -1) == v) return true;
        return false;
    }

    private void showSections() {
        secHourly.setVisibility("hourly".equals(mode) ? View.VISIBLE : View.GONE);
        secTimes.setVisibility("daily".equals(mode) || "weekly".equals(mode) || "monthly".equals(mode) ? View.VISIBLE : View.GONE);
        secWeekly.setVisibility("weekly".equals(mode) ? View.VISIBLE : View.GONE);
        secMonthly.setVisibility("monthly".equals(mode) ? View.VISIBLE : View.GONE);
        secCron.setVisibility("cron".equals(mode) ? View.VISIBLE : View.GONE);
    }

    private void renderTimes() {
        Collections.sort(times);
        timeGroup.removeAllViews();
        for (String t : new ArrayList<>(times)) {
            Chip c = chip(t, false);
            c.setCloseIconVisible(true);
            c.setOnCloseIconClickListener(v -> {
                if (times.size() <= 1) { toast("至少保留一个时间点"); return; }
                times.remove(t);
                renderTimes();
                schedulePreview();
            });
            c.setOnClickListener(v -> pickTime());
            timeGroup.addView(c);
        }
    }

    private void pickTime() {
        if (times.size() >= 24) { toast("最多 24 个时间点"); return; }
        MaterialTimePicker tp = new MaterialTimePicker.Builder().setTimeFormat(TimeFormat.CLOCK_24H).setHour(12).setMinute(0)
                .setTitleText("添加时间").setInputMode(MaterialTimePicker.INPUT_MODE_KEYBOARD).build();
        tp.addOnPositiveButtonClickListener(v -> {
            String t = String.format(Locale.US, "%02d:%02d", tp.getHour(), tp.getMinute());
            if (!times.contains(t)) times.add(t);
            renderTimes();
            schedulePreview();
        });
        tp.show(getSupportFragmentManager(), "odtime");
    }

    private JSONObject body() {
        JSONObject b = new JSONObject();
        try {
            b.put("mode", mode);
            if ("hourly".equals(mode)) {
                b.put("every_hours", everyHours.getText().toString().trim());
                b.put("minute", minute.getText().toString().trim());
                b.put("start_hour", startHour.getText().toString().trim());
            }
            if ("daily".equals(mode) || "weekly".equals(mode) || "monthly".equals(mode)) b.put("times", new JSONArray(times));
            if ("weekly".equals(mode)) {
                JSONArray a = new JSONArray();
                for (int i = 0; i < wdGroup.getChildCount(); i++) { Chip c = (Chip) wdGroup.getChildAt(i); if (c.isChecked()) a.put(c.getTag()); }
                b.put("weekdays", a);
            }
            if ("monthly".equals(mode)) {
                JSONArray a = new JSONArray();
                for (int i = 0; i < dayGroup.getChildCount(); i++) { Chip c = (Chip) dayGroup.getChildAt(i); if (c != lastDay && c.isChecked()) a.put(c.getTag()); }
                b.put("days", a);
                b.put("last_day", lastDay.isChecked());
            }
            if ("cron".equals(mode)) b.put("cron", cron.getText().toString().trim());
        } catch (Exception ignored) { }
        return b;
    }

    private void schedulePreview() {
        if (preview == null) return;
        h.removeCallbacksAndMessages(null);
        h.postDelayed(this::loadPreview, 400);
    }

    private void loadPreview() {
        int my = ++seq;
        JSONObject b = body();
        Api.job(this, () -> {
            try { return Api.call("POST", "/onedrive/schedule/preview", b); }
            catch (Api.ApiError e) {
                if (e.code == 401) throw e;
                return new JSONObject().put("__error", e.getMessage());
            }
        }, r -> {
            if (my != seq || isFinishing()) return;
            JSONObject o = Api.obj(r);
            if (o.has("__error")) { preview.setText("⚠️ " + o.optString("__error")); return; }
            StringBuilder sb = new StringBuilder(o.optString("desc"));
            sb.append("\n（").append(o.optString("timezone")).append("）");
            JSONArray l = o.optJSONArray("next_runs_label");
            if (l != null) for (int i = 0; i < l.length(); i++) sb.append("\n· ").append(l.optString(i));
            preview.setText(sb.toString());
        });
    }

    private void save() {
        JSONObject b = body();
        try {
            b.put("enabled", enabled.isChecked());
            b.put("keep", keep.getText().toString().trim());
        } catch (Exception ignored) { }
        Api.post(this, "/onedrive/config", b, x -> {
            JSONObject o = Api.obj(x);
            toast("已保存：" + o.optString("desc", "") + (o.isNull("next_run") ? "" : "，下次 " + o.optString("next_run")));
            setResult(RESULT_OK);
            finish();
        });
    }
}
