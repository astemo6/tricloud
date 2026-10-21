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
    static String[] modeLabels() {
        return new String[]{L10n.s(R.string.lx_mode_hourly), L10n.s(R.string.lx_mode_daily), L10n.s(R.string.lx_mode_weekly), L10n.s(R.string.lx_mode_monthly), "Cron"};
    }
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
        setTitle(getString(R.string.s1058));
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

        LinearLayout a = card(getString(R.string.s1059));
        muted(a, getString(R.string.s1060, tz));
        enabled = new MaterialSwitch(this);
        enabled.setText(getString(R.string.s1061));
        enabled.setChecked(cfg.optBoolean("enabled", true));
        a.addView(enabled);
        ChipGroup mg = chipGroup(a, true);
        for (int i = 0; i < MODES.length; i++) {
            Chip c = chip(modeLabels()[i], true);
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

        LinearLayout b = card(getString(R.string.s1062));
        secHourly = section(b);
        everyHours = num(secHourly, getString(R.string.s1063), String.valueOf(cfg.optInt("every_hours", 6)), null);
        minute = num(secHourly, getString(R.string.s1064), String.valueOf(cfg.optInt("minute", 0)), getString(R.string.s1065));
        startHour = num(secHourly, getString(R.string.s1066), String.valueOf(cfg.optInt("start_hour", 0)), getString(R.string.s1067));

        secTimes = section(b);
        text(secTimes, getString(R.string.s1068), 14, true);
        timeGroup = chipGroup(secTimes, false);
        MaterialButton add = new MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle);
        add.setText(getString(R.string.s1069));
        add.setAllCaps(false);
        add.setOnClickListener(v -> pickTime());
        secTimes.addView(add, new LinearLayout.LayoutParams(-2, -2));
        renderTimes();

        secWeekly = section(b);
        text(secWeekly, getString(R.string.s1070), 14, true);
        wdGroup = chipGroup(secWeekly, false);
        JSONArray wds = cfg.optJSONArray("weekdays");
        for (int i = 0; i < 7; i++) {
            Chip c = chip(OneDriveActivity.wd()[i], true);
            c.setTag(i);
            c.setChecked(contains(wds, i) || (wds == null && cfg.optInt("weekday", 0) == i));
            c.setOnCheckedChangeListener((v, on) -> schedulePreview());
            wdGroup.addView(c);
        }

        secMonthly = section(b);
        text(secMonthly, getString(R.string.s1071), 14, true);
        muted(secMonthly, getString(R.string.s1072));
        dayGroup = chipGroup(secMonthly, false);
        JSONArray days = cfg.optJSONArray("days");
        for (int d = 1; d <= 31; d++) {
            Chip c = chip(String.valueOf(d), true);
            c.setTag(d);
            c.setChecked(days == null ? d == 1 : contains(days, d));
            c.setOnCheckedChangeListener((v, on) -> schedulePreview());
            dayGroup.addView(c);
        }
        lastDay = chip(getString(R.string.s1073), true);
        lastDay.setChecked(cfg.optBoolean("last_day"));
        lastDay.setOnCheckedChangeListener((v, on) -> schedulePreview());
        dayGroup.addView(lastDay);

        secCron = section(b);
        TextInputLayout ct = inputLayout(getString(R.string.s1074), "30 3 * * 1-5", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        ct.setHelperText(getString(R.string.s1075));
        cron = ct.getEditText();
        cron.setText(cfg.optString("cron", "30 3 * * *"));
        cron.setTypeface(android.graphics.Typeface.MONOSPACE);
        cron.addTextChangedListener(watcher());
        secCron.addView(ct);

        LinearLayout k = card(getString(R.string.s1076));
        keep = num(k, getString(R.string.s1077), String.valueOf(cfg.optInt("keep", 30)), getString(R.string.s1078));

        LinearLayout p = card(getString(R.string.s1079));
        preview = text(p, getString(R.string.s1080), 14, false);

        bigButton(getString(R.string.s1081), v -> save());
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
                if (times.size() <= 1) { toast(getString(R.string.s1082)); return; }
                times.remove(t);
                renderTimes();
                schedulePreview();
            });
            c.setOnClickListener(v -> pickTime());
            timeGroup.addView(c);
        }
    }

    private void pickTime() {
        if (times.size() >= 24) { toast(getString(R.string.s1083)); return; }
        MaterialTimePicker tp = new MaterialTimePicker.Builder().setTimeFormat(TimeFormat.CLOCK_24H).setHour(12).setMinute(0)
                .setTitleText(getString(R.string.s1069)).setInputMode(MaterialTimePicker.INPUT_MODE_KEYBOARD).build();
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
            toast(getString(R.string.s1085, o.optString("desc", ""), (o.isNull("next_run") ? "" : getString(R.string.s1084, o.optString("next_run")))));
            setResult(RESULT_OK);
            finish();
        });
    }
}
