// TriCloud 前端 v1.6.0 build 23 · OneDrive 定期备份（设备码绑定、计划与保留、备份密码、立即备份、备份列表与恢复、解绑）
// build 23：计划支持 每 N 小时 / 每天多个时间点 / 每周多选 / 每月日期（含月末）/ Cron，保存前预览接下来 3 次
import { t } from "./i18n.js";
import { $, act, api, applyShowWhen, confirmBox, esc, fmtBytes, fmtDT, form, loading, modal, post, toast, view } from "./core.js";

const OD_WD = ["od.wd1", "od.wd2", "od.wd3", "od.wd4", "od.wd5", "od.wd6", "od.wd7"];
export const OD_LOGIN_URL = "https://microsoft.com/devicelogin";
let odTimer = null;

const OD_MODES = [["hourly", "od.modeHourly"], ["daily", "od.modeDaily"], ["weekly", "od.modeWeekly"], ["monthly", "od.modeMonthly"], ["cron", "od.modeCron"]];
let odPrevTimer = null, odPrevSeq = 0;
// build 23：计划描述由后端给（s.desc）；旧后端没有 desc 时退回 freq/time
export const odPlan = (c, desc) => esc(desc || ((c.freq === "weekly" ? t("od.planWeekly", { wd: t(OD_WD[+c.weekday || 0]) }) : t("od.planDaily")) + c.time)) + t("od.planKeep", { n: esc(c.keep) });

// 设置页里的小卡片：状态一行 + 进入按钮
export function odSettingsCard() {
  return `<div class="card" id="odCard"><h3>${t("od.cardTitle")}</h3><p class="muted">${t("od.cardNote")}</p>
    <div id="odSum" class="muted">${t("od.reading")}</div><div class="bar" style="margin-top:12px"><a class="btn primary" href="#/onedrive">${t("od.open")}</a></div></div>`;
}
export async function odSettingsBind() {
  const el = document.getElementById("odSum"); if (!el) return;
  try {
    const s = await api("/onedrive");
    el.innerHTML = !s.bound ? `<span class="badge">${t("od.unbound")}</span>` : `<span class="badge done">${t("od.bound")}</span> ${s.ready ? t("od.nextLine", { plan: odPlan(s.cfg, s.desc), next: esc(s.next_run || "-") }) : s.password_set ? t("od.schedOff") : t("od.noPwYet")}`
      + (s.state.last_ok ? `<br>${t("od.lastOk", { t: esc(fmtDT(s.state.last_ok)) })}` : "") + (s.state.last_result === "failed" ? `<br><span class="err-text">${t("od.lastFail", { e: esc(s.state.last_error || "") })}</span>` : "");
  } catch (e) { el.textContent = e.message; }
}

function stopPoll() { if (odTimer) { clearTimeout(odTimer); odTimer = null; } }

export async function pageOneDrive(hint) {
  stopPoll();
  loading();
  const s = await api("/onedrive");
  const c = s.cfg, st = s.state || {};
  const failed = st.last_result === "failed";
  view.innerHTML = `<div class="grid">
  <div class="card" id="odStat"><h3>${t("od.status")}</h3>
    <p>${s.bound ? `<span class="badge done">${t("od.bound")}</span> ${esc((s.account && s.account.folder) ? t("od.folderLine", { folder: s.account.folder }) : t("od.personal"))}` : `<span class="badge">${t("od.unbound")}</span>`}
      ${s.password_set ? `<span class="badge done">${t("od.pwSet")}</span>` : `<span class="badge">${t("od.pwUnset")}</span>`}</p>
    <p>${s.ready ? `${t("od.schedLine", { plan: odPlan(c, s.desc), tz: esc(s.timezone) })}<br>${t("od.nextBackup", { t: esc((s.next_runs_label || [])[0] || s.next_run || "-") })}${(s.next_runs_label || []).length > 1 ? `<br><span class="muted">${t("od.afterThat", { list: s.next_runs_label.slice(1).map(esc).join("、") })}</span>` : ""}` : `<span class="muted">${!s.bound ? t("od.hintBind") : !s.password_set ? t("od.hintPw") : t("od.schedOff")}</span>`}</p>
    ${st.last_ok ? `<p>${t("od.lastOk2", { t: esc(fmtDT(st.last_ok)) })} · ${esc(st.last_file || "")}${st.last_size ? ` · ${esc(fmtBytes(st.last_size))}` : ""}</p>` : ""}
    ${failed ? `<p class="err-text">${t("od.lastFail2", { t: esc(fmtDT(st.last_try)), e: esc(st.last_error || "") })}</p>` : ""}
    ${st.auth_error ? `<p class="err-text">${esc(st.auth_error)}</p>` : ""}
    ${s.running_task_id ? `<p><span class="spin"></span> ${t("od.running", { id: s.running_task_id })}</p>` : ""}
    <div class="bar" style="margin-top:8px"><button class="btn primary" id="odNow" ${s.bound && s.password_set && !s.running_task_id ? "" : "disabled"}>${t("od.now")}</button>
      ${s.bound ? `<button class="btn danger" id="odUnbind">${t("od.unbind")}</button>` : ""}</div></div>
  <div class="card" id="odApp"><h3>${t("od.appTitle")}</h3>
    <p class="muted">${t("od.appNote")}</p>
    <label>${t("od.clientId")}</label><input name="client_id" class="mono" value="${esc(s.client_id || "")}" placeholder="00000000-0000-0000-0000-000000000000" autocomplete="off">
    <label>${t("od.tenant")}</label><select name="tenant"><option value="consumers" ${s.tenant === "consumers" ? "selected" : ""}>${t("od.tenantConsumers")}</option><option value="common" ${s.tenant === "common" ? "selected" : ""}>${t("od.tenantCommon")}</option></select>
    <div class="bar" style="margin-top:12px">${s.bound
      ? `<button class="btn" id="odSaveApp">${t("common.save")}</button><button class="btn" id="odBind">${t("od.rebind")}</button>`
      : `<button class="btn sm" id="odSaveApp">${t("common.save")}</button><button class="btn primary" id="odBind" style="font-weight:600;padding:10px 22px" ${s.client_id ? "" : "disabled"}>${t("od.bind")}</button>`}</div>
    ${!s.bound && s.client_id ? `<p class="muted" id="odBindHint">${hint ? t("od.hintSaved") : ""}${t("od.hintBindCode")}</p>` : !s.bound ? `<p class="muted" id="odBindHint">${t("od.hintFill")}</p>` : ""}
    <div id="odPendBox"></div></div>
  <div class="card" id="odPlan"><h3>${t("od.planTitle")}</h3>
    <label><input type="checkbox" name="enabled" style="width:auto" ${c.enabled ? "checked" : ""}> ${t("od.enableSched")}</label>
    ${odSchedForm(c, s.timezone)}
    <label>${t("od.keep")}</label><input name="keep" type="number" min="1" max="365" value="${esc(c.keep)}">
    <label>${t("od.pwLabel")}${s.password_set ? ` <span class="badge done">${t("set.isSet")}</span>` : ""}</label><input name="password" type="password" autocomplete="new-password" placeholder="${s.password_set ? t("set.keepPh") : t("od.pwPh")}">
    <label>${t("od.pw2")}</label><input name="password2" type="password" autocomplete="new-password">
    <p class="muted">${t("od.pwNote")}</p>
    <div class="bar" style="margin-top:8px"><button class="btn primary" id="odSavePlan">${t("common.save")}</button></div></div>
  <div class="card" id="odHelp"><h3>${t("od.helpTitle")}</h3>
    <ol class="muted"><li>${t("od.help1")}</li><li>${t("od.help2")}</li><li>${t("od.help3")}</li><li>${t("od.help4")}</li></ol>
    <p class="muted">${t("od.helpOffline")}</p><input class="mono" readonly onclick="this.select()" value="python -m tools.decrypt_backup tricloud-backup-xxxx.tcod 输出目录">
    <p class="muted">${t("od.helpNote2")}</p></div></div>
  <div class="card" id="odList"><div class="bar"><h3 class="grow" style="margin:0">${t("od.listTitle")}</h3>${s.bound ? `<button class="btn sm" id="odRefresh">${t("common.refresh")}</button>` : ""}</div>
    <div id="odItems" class="muted">${s.bound ? `<span class="spin"></span> ${t("od.reading")}` : t("od.listUnbound")}</div></div>`;
  odSchedBind($("#odPlan"));
  $("#odSaveApp").onclick = (e) => act(e.target, () => post("/onedrive/config", form($("#odApp"))),
    (r) => (r.changed.includes("unbound") ? t("od.savedUnbound") : !r.bound && r.client_id ? t("od.savedBind") : t("common.saved")))
    .then((r) => r && pageOneDrive(!r.bound && !!r.client_id));
  $("#odSavePlan").onclick = (e) => {
    const pf = form($("#odPlan"));
    if (!pf.password && pf.password2) return toast(t("od.pwEmpty"), true);
    if (pf.password && pf.password !== pf.password2) return toast(t("od.pwMismatch"), true);
    const f = Object.assign(odSchedBody($("#odPlan")), { enabled: pf.enabled, keep: pf.keep });
    if (pf.password) Object.assign(f, { password: pf.password, password2: pf.password2 });
    act(e.target, () => post("/onedrive/config", f), t("common.saved")).then((r) => r && pageOneDrive());
  };
  $("#odBind").onclick = (e) => act(e.target, async () => {
    if ($("#odApp [name=client_id]").value.trim() !== (s.client_id || "")) await post("/onedrive/config", form($("#odApp")));
    return post("/onedrive/bind");
  }).then((p) => p && showPending(p));
  if (s.pending) showPending(s.pending);
  $("#odNow").onclick = (e) => act(e.target, () => post("/onedrive/backup"), (r) => r.message).then((r) => r && setTimeout(pageOneDrive, 800));
  if ($("#odUnbind")) $("#odUnbind").onclick = async () => {
    if (!(await confirmBox(t("od.unbindTitle"), t("od.unbindMsg"), true))) return;
    const r = await act($("#odUnbind"), () => api("/onedrive/bind?confirm=true", { method: "DELETE" }), t("set.unbound"));
    if (r) pageOneDrive();
  };
  if (s.bound) { loadList(); $("#odRefresh").onclick = loadList; }
}

// ---------------- build 23 计划编辑 ----------------
const odTimeRow = (tv) => `<span class="od-time"><input type="time" value="${esc(tv)}" data-odt><button type="button" class="btn sm" data-odrm title="${t("od.delTime")}">✕</button></span>`;
const odChip = (attr, v, label, on) => `<label class="od-chip"><input type="checkbox" ${attr}="${v}" ${on ? "checked" : ""}><span>${label}</span></label>`;

export function odSchedForm(c, tz) {
  const days = new Set(c.days || []), wds = new Set(c.weekdays || []);
  return `<label>${t("od.freqLabel", { tz: esc(tz || "") })}</label><select name="mode">${OD_MODES.map(([k, v]) => `<option value="${k}" ${c.mode === k ? "selected" : ""}>${t(v)}</option>`).join("")}</select>
    <div data-show-when="mode=hourly"><div class="row2"><div><label>${t("od.everyHours")}</label><input name="every_hours" type="number" min="1" max="24" value="${esc(c.every_hours ?? 6)}"></div>
      <div><label>${t("od.minute")}</label><input name="minute" type="number" min="0" max="59" value="${esc(c.minute ?? 0)}"></div></div>
      <label>${t("od.startHour")}</label><input name="start_hour" type="number" min="0" max="23" value="${esc(c.start_hour ?? 0)}">
      <p class="muted">${t("od.hourlyNote")}</p></div>
    <div data-show-when="mode=daily|weekly|monthly"><label>${t("od.times")}</label><div class="od-times" id="odTimes">${(c.times && c.times.length ? c.times : ["03:30"]).map(odTimeRow).join("")}</div>
      <button type="button" class="btn sm" id="odAddTime">${t("od.addTime")}</button></div>
    <div data-show-when="mode=weekly"><label>${t("od.weekdays")}</label><div class="od-chips">${OD_WD.map((w, i) => odChip("data-odwd", i, t(w), wds.has(i))).join("")}</div></div>
    <div data-show-when="mode=monthly"><label>${t("od.days")}</label>
      <div class="od-chips od-days">${Array.from({ length: 31 }, (_, i) => odChip("data-odday", i + 1, i + 1, days.has(i + 1))).join("")}${odChip("data-odlast", 1, t("od.lastDay"), !!c.last_day)}</div></div>
    <div data-show-when="mode=cron"><label>${t("od.cronLabel")}</label><input name="cron" class="mono" value="${esc(c.cron || "30 3 * * *")}" placeholder="30 3 * * 1-5" autocomplete="off" spellcheck="false">
      <p class="muted">${t("od.cronNote")}</p></div>
    <div class="od-prev" id="odPrev"><span class="muted">${t("od.prevLoading")}</span></div>`;
}

export function odSchedBody(root) {
  const mode = root.querySelector("[name=mode]").value, b = { mode };
  if (mode === "hourly") ["every_hours", "minute", "start_hour"].forEach((k) => (b[k] = root.querySelector(`[name=${k}]`).value));
  if (mode === "daily" || mode === "weekly" || mode === "monthly") b.times = [...root.querySelectorAll("[data-odt]")].map((i) => i.value).filter(Boolean);
  if (mode === "weekly") b.weekdays = [...root.querySelectorAll("[data-odwd]:checked")].map((i) => +i.dataset.odwd);
  if (mode === "monthly") { b.days = [...root.querySelectorAll("[data-odday]:checked")].map((i) => +i.dataset.odday); b.last_day = !!root.querySelector("[data-odlast]:checked"); }
  if (mode === "cron") b.cron = root.querySelector("[name=cron]").value.trim();
  return b;
}

async function odPreview(root) {
  const box = root.querySelector("#odPrev"); if (!box) return;
  const seq = ++odPrevSeq;
  let r;
  try { r = await post("/onedrive/schedule/preview", odSchedBody(root)); } catch (e) { r = { error: e.message }; }
  if (seq !== odPrevSeq || !document.body.contains(box)) return;
  box.innerHTML = r.error ? `<span class="err-text">⚠️ ${esc(r.error)}</span>`
    : `<b>${esc(r.desc)}</b><br><span class="muted">${t("od.prevLine", { tz: esc(r.timezone) })}</span>${r.next_runs_label.map((x) => `<br>· ${esc(x)}`).join("")}`;
}

export function odSchedBind(root) {
  const refresh = () => { applyShowWhen(root); clearTimeout(odPrevTimer); odPrevTimer = setTimeout(() => odPreview(root), 350); };
  root.addEventListener("change", refresh);
  root.addEventListener("input", (e) => { if (!e.target.matches("[name=password],[name=password2],[name=keep]")) refresh(); });
  root.addEventListener("click", (e) => {
    const rm = e.target.closest("[data-odrm]");
    if (rm) { const rows = root.querySelectorAll(".od-time"); if (rows.length <= 1) return toast(t("od.keepOneTime"), true); rm.parentElement.remove(); refresh(); }
  });
  root.querySelector("#odAddTime").onclick = () => {
    const box = root.querySelector("#odTimes");
    if (box.querySelectorAll(".od-time").length >= 24) return toast(t("od.maxTimes"), true);
    box.insertAdjacentHTML("beforeend", odTimeRow("12:00")); refresh();
  };
  applyShowWhen(root); odPreview(root);
}

function showPending(p) {
  const box = $("#odPendBox"); if (!box) return;
  const url = p.verification_uri || OD_LOGIN_URL;
  box.innerHTML = `<div class="card" id="odPend" style="margin-top:12px"><p>${t("od.stepOpen")}<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url.replace(/^https:\/\//, ""))}</a>（${esc(OD_LOGIN_URL.replace(/^https:\/\//, ""))}）</p>
    <p>${t("od.stepCode")} <b class="mono" style="font-size:1.4em;letter-spacing:2px" id="odCode">${esc(p.user_code)}</b> <button class="btn sm" id="odCopy">${t("common.copy")}</button></p>
    <p>${t("od.stepLogin")}</p><p class="muted" id="odPollMsg"><span class="spin"></span> ${t("od.pollWait", { m: `<span id="odLeft">${Math.ceil((p.expires_in || 900) / 60)}</span>` })}</p>
    <div class="bar"><button class="btn sm" id="odCancel">${t("common.cancel")}</button></div></div>`;
  $("#odCopy").onclick = () => { try { navigator.clipboard.writeText(p.user_code); toast(t("guard.copied")); } catch (_) { toast(t("od.copyManual"), true); } };
  $("#odCancel").onclick = async () => { stopPoll(); await api("/onedrive/bind?pending_only=true", { method: "DELETE" }).catch(() => {}); box.innerHTML = ""; };
  let interval = Math.max(2, +p.interval || 5);
  const deadline = Date.now() + (p.expires_in || 900) * 1000;
  const tick = async () => {
    odTimer = null;
    if (!document.getElementById("odPend")) return;      // 离开页面就停止轮询
    let r;
    try { r = await post("/onedrive/bind/poll"); } catch (e) { r = { status: "error", message: e.message }; }
    if (!document.getElementById("odPend")) return;
    const left = $("#odLeft"); if (left) left.textContent = Math.max(0, Math.ceil((deadline - Date.now()) / 60000));
    if (r.status === "ok") { toast(t("od.boundToast")); return pageOneDrive(); }
    if (r.status === "pending" || r.status === "slow_down") { if (r.interval) interval = r.interval; odTimer = setTimeout(tick, interval * 1000); return; }
    $("#odPollMsg").innerHTML = `<span class="err-text">${esc(r.message || t("od.bindFail"))}</span>`;
  };
  odTimer = setTimeout(tick, interval * 1000);
}

async function loadList() {
  const box = $("#odItems"); if (!box) return;
  box.innerHTML = `<span class="spin"></span> ${t("od.reading")}`;
  let r;
  try { r = await api("/onedrive/backups"); } catch (e) { box.innerHTML = `<span class="err-text">${esc(e.message)}</span>`; return; }
  if (!document.getElementById("odItems")) return;
  box.classList.remove("muted");
  box.innerHTML = r.items.length ? `<table><tr><th>${t("set.colTime")}</th><th>${t("inst.size")}</th><th>${t("od.colFile")}</th><th></th></tr>${r.items.map((it) => `<tr><td>${esc(it.time || it.created)}</td><td>${esc(fmtBytes(it.size))}</td>
    <td class="mono">${esc(it.name)}</td><td><button class="btn sm danger" data-odrs="${esc(it.id)}" data-odn="${esc(it.name)}">${t("set.restore")}</button></td></tr>`).join("")}</table>
    <p class="muted">${t("od.listSummary", { n: r.items.length, k: esc(r.keep) })}</p>` : `<span class="muted">${t("od.listEmpty")}</span>`;
  box.querySelectorAll("[data-odrs]").forEach((b) => (b.onclick = () => restore(b.dataset.odrs, b.dataset.odn)));
}

async function restore(id, name) {
  const pw = await modal(t("od.rsTitle"), `<p>${t("od.rsBackup", { name: `<b class="mono">${esc(name)}</b>` })}</p><p>${t("od.rsWarn")}</p>
    <label>${t("od.rsPw")}</label><input name="password" type="password" autocomplete="off">`, (bg) => { const v = form(bg).password; if (!v) throw new Error(t("od.needPw")); return v; }, t("inst.next"), true);
  if (!pw) return;
  if (!(await confirmBox(t("od.rsConfirmTitle"), t("od.rsConfirmMsg", { name: `<b class="mono">${esc(name)}</b>` }), true))) return;
  const r = await act(null, () => post("/onedrive/restore", { item_id: id, password: pw, confirm: true }));
  if (!r) return;
  toast(r.message || t("set.restored"));
  setTimeout(() => (location.href = "/login"), r.restart ? 10000 : 1500);
}
