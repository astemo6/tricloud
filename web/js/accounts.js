// TriCloud 前端 v1.6.0 · 云账号管理：添加 / 批量添加 / 编辑 / 粘贴识别、测活、账号类型与停用、已删账号
import { t } from "./i18n.js";
import { $, accountRegionText, ACCOUNTS, act, ADD_BODY, api, confirmBox, del, esc, fmtDT, form, loadAccounts, loading, modal, PNAME, post, PROV_HINT, provOpts, PROVS, refreshMachineRegions, regionLabel, TEXTAREA_FIELDS, toast, view } from "./core.js";
import { go, route } from "./router.js";

// ---------------- 云账号管理 ----------------
export const CRED_FIELDS = {
  oci: [["user", "cred.user"], ["tenancy", "cred.tenancy"], ["fingerprint", "cred.fingerprint"], ["region", "cred.region", "ap-tokyo-1"],
    ["key_content", "cred.keyContent", "", "textarea"], ["pass_phrase", "cred.passPhraseOpt"], ["compartment", "cred.compartment"], ["home_region", "cred.homeRegion"],
    ["proxy", "cred.proxy", "http://host:port"], ["proxy_user", "cred.proxyUser"], ["proxy_pass", "cred.proxyPass", "", "password"]],
  aws: [["access_key", "cred.accessKey"], ["secret_key", "cred.secretKey", "", "password"], ["region", "cred.defRegion", "us-east-1"], ["proxy", "cred.proxy", "socks5://host:port"],
    ["proxy_user", "cred.proxyUser"], ["proxy_pass", "cred.proxyPass", "", "password"]],
  azure: [["tenant_id", "cred.tenantId"], ["client_id", "cred.clientId"], ["client_secret", "cred.clientSecret", "", "password"], ["subscription_id", "cred.subscriptionId"],
    ["proxy", "cred.proxy", "http://host:port"], ["proxy_user", "cred.proxyUser"], ["proxy_pass", "cred.proxyPass", "", "password"]],
};
// build 25：区域列显示有机器的区域；与默认区域不同时下面小字注明默认区域
export function accRegionCell(a) {
  const l = a.machine_regions || [];
  const sub = l.length > 1 ? l.map((r) => t("acc.regionCount", { label: regionLabel(r.region), n: r.count })).join("\n") : "";
  const def = a.provider !== "azure" && l.length && a.region && a.region !== l[0].region ? `<div class="muted">${t("acc.defaultPrefix", { d: esc(regionLabel(a.region)) })}</div>` : "";
  return `<span${sub ? ` title="${esc(sub)}"` : ""}>${esc(accountRegionText(a) || "-")}</span>${def}`;
}
export async function pageAccounts() {
  const prov = (p) => ACCOUNTS.filter((a) => a.provider === p).length;
  view.innerHTML = `<div class="bar"><button class="btn primary" id="add">${t("acc.addBtn")}</button><button class="btn" id="batch">${t("acc.batchBtn")}</button>
    <select id="tprov" title="${t("acc.testScope")}"><option value="">${t("acc.allAccounts")}</option>${PROVS.filter(prov).map((p) => `<option value="${p}">${PNAME[p]}</option>`).join("")}</select>
    <button class="btn" id="testAll">${t("acc.testAll")}</button><a class="btn" href="#/deleted">${t("acc.deletedLink")}</a><span class="grow"></span><span class="muted" id="tsum">${t("acc.encNote")}</span></div>
    <div class="card"><table><tr><th>${t("acc.colName")}</th><th>${t("acc.colCloud")}</th><th>${t("core.region.title")}</th><th>${t("acc.colCreated")}</th><th>${t("acc.colConn")}</th><th>${t("acc.colProxy")}</th><th>${t("acc.colAdded")}</th><th></th></tr>
    ${ACCOUNTS.map((a) => `<tr data-acc="${a.id}" class="${a.disabled ? "acc-off" : ""}"><td><a href="#/${a.provider}/${a.id}">${esc(a.name)}</a>${a.disabled ? ` <span class="badge failed" title="${esc(a.disabled_reason || "")}">${t("acc.disabledBadge")}</span>` : ""}${acctTypeTag(a)}</td><td><span class="dot ${a.provider}"></span> ${PNAME[a.provider]}</td>
    <td id="mr${a.id}">${accRegionCell(a)}</td><td>${ageText(a)}</td><td class="tcell">${testCell(a)}</td><td class="mono">${esc(a.proxy || t("acc.direct"))}${a.proxy_user ? `<div class="muted">${esc(a.proxy_user)}${a.proxy_pass_set ? " · ●●●" : ""}</div>` : ""}</td><td>${new Date(a.created * 1000).toLocaleString()}</td>
    <td><button class="btn sm" data-test="${a.id}">${t("acc.test")}</button> <button class="btn sm" data-info="${a.id}">${t("acc.info")}</button> <button class="btn sm" data-type="${a.id}">${t("acc.typeBtn")}</button>${a.disabled ? ` <button class="btn sm" data-off="${a.id}">${t("common.enable")}</button>` : ""} <button class="btn sm" data-edit="${a.id}">${t("common.edit")}</button> <button class="btn sm" data-px="${a.id}">${t("acc.proxyBtn")}</button> <button class="btn sm danger" data-del="${a.id}">${t("common.delete")}</button></td></tr>`).join("") || `<tr><td colspan=8 class="muted">${t("common.none")}</td></tr>`}</table></div>`;
  $("#add").onclick = addAccount;
  $("#batch").onclick = batchAddAccounts;
  refreshMachineRegions(ACCOUNTS, (a) => { const td = document.getElementById("mr" + a.id); if (td) td.innerHTML = accRegionCell(a); });
  $("#testAll").onclick = async (e) => {
    const p = $("#tprov").value;
    view.querySelectorAll("tr[data-acc]").forEach((tr) => { const a = ACCOUNTS.find((x) => x.id == tr.dataset.acc); if (!p || a.provider === p) tr.querySelector(".tcell").innerHTML = `<span class="spin"></span>`; });
    const r = await act(e.target, () => post("/accounts/test-all", { provider: p || undefined }));
    if (!r) return;
    $("#tsum").textContent = t("acc.testDone", { ok: r.ok, total: r.total, s: (r.ms / 1000).toFixed(1) });
    await loadAccounts();
    r.results.forEach((x) => { const tr = view.querySelector(`tr[data-acc="${x.account_id}"]`); if (tr) tr.querySelector(".tcell").innerHTML = testCell(ACCOUNTS.find((a) => a.id === x.account_id) || {}, x); });
  };
  view.querySelectorAll("[data-test]").forEach((b) => (b.onclick = async () => {
    const tr = b.closest("tr"); tr.querySelector(".tcell").innerHTML = `<span class="spin"></span>`;
    const r = await act(b, () => post(`/accounts/${b.dataset.test}/test`));
    await loadAccounts();
    tr.querySelector(".tcell").innerHTML = testCell(ACCOUNTS.find((a) => a.id == b.dataset.test) || {}, r || undefined);
  }));
  view.querySelectorAll("[data-info]").forEach((b) => (b.onclick = () => accountInfoDialog(ACCOUNTS.find((x) => x.id == b.dataset.info))));
  view.querySelectorAll("[data-type]").forEach((b) => (b.onclick = () => accountTypeDialog(ACCOUNTS.find((x) => x.id == b.dataset.type))));
  view.querySelectorAll("[data-off]").forEach((b) => (b.onclick = () => toggleDisable(ACCOUNTS.find((x) => x.id == b.dataset.off))));
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (!(await confirmBox(t("acc.delTitle"), t("acc.delConfirm"), true))) return;
    await act(b, () => del(`/accounts/${b.dataset.del}`), t("common.deleted")); await loadAccounts(); route();
  }));
  view.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => editAccount(ACCOUNTS.find((x) => x.id == b.dataset.edit))));
  view.querySelectorAll("[data-px]").forEach((b) => (b.onclick = async () => {
    const a = ACCOUNTS.find((x) => x.id == b.dataset.px);
    const r = await modal(t("acc.proxyTitle"), `<p class="muted">${t("acc.proxyIntro")}</p>
      <p class="muted">${t("acc.proxyCurrent", { v: esc(a.proxy || t("acc.direct")) })}${a.proxy_user ? t("acc.proxyUserPart", { u: esc(a.proxy_user) }) : ""}${a.proxy_pass_set ? t("acc.proxyPassSet") : ""}</p>
      ${proxyFields({ proxy_user: a.proxy_user, proxy_pass_set: a.proxy_pass_set })}
      ${a.proxy ? `<label><input type="checkbox" name="clear_all" style="width:auto"> ${t("acc.proxyClear")}</label>` : ""}`, (bg) => {
      const f = form(bg); const body = {};
      if (f.clear_all) body.proxy = "";
      else {
        if (f.proxy) body.proxy = f.proxy;
        else if (!a.proxy && (f.proxy_user || f.proxy_pass)) throw new Error(t("acc.proxyAddrFirst"));
        if (f.proxy_user !== (a.proxy_user || "")) body.proxy_user = f.proxy_user;
        if (f.proxy_pass) body.proxy_pass = f.proxy_pass;
        if (f.proxy_pass_clear) body.proxy_pass_clear = true;
      }
      if (!Object.keys(body).length) return true;
      return api(`/accounts/${a.id}`, { method: "PATCH", body });
    }, t("common.save"));
    if (r) { toast(t("common.saved")); await loadAccounts(); route(); }
  }));
}
export const credInput = ([k, l, ph, ty]) => `<label>${t(l)}</label>` + (ty === "textarea" ? `<textarea name="c_${k}" placeholder="${esc(ph || (k === "key_content" ? "-----BEGIN PRIVATE KEY-----" : ""))}"></textarea>`
  : `<input name="c_${k}" type="${ty || "text"}" placeholder="${esc(ph || "")}" autocomplete="off">`);
export async function addAccount() {
  const fields = (p) => CRED_FIELDS[p].map(credInput).join("");
  const r = await modal(t("acc.addBtn"), `<label>${t("acc.provider")}</label><select name="provider" id="np">${provOpts()}</select>
    <label>${t("acc.nameLabel")}</label><input name="name" placeholder="${t("acc.namePh")}">
    <details id="smartpaste" open><summary class="muted">${t("acc.smartSummary")}</summary>
    <textarea id="smarttext" placeholder="${esc(t("acc.smartPh"))}"></textarea>
    <select id="smartpick" style="display:none" title="${t("acc.smartPickTitle")}"></select><p class="muted" id="smarthint"></p></details>
    <div id="cf">${fields("oci")}</div>
    <p class="muted" id="hint"></p>`, async (bg) => {
    const f = form(bg); const cred = {};
    for (const k in f) if (k.startsWith("c_")) cred[k.slice(2)] = f[k];
    toast(t("acc.verifying"));
    return post("/accounts", ADD_BODY[f.provider] ? ADD_BODY[f.provider](f, cred, bg) : { provider: f.provider, name: f.name, cred });
  }, t("acc.verifySave"));
  if (r) { toast(t("acc.added")); await loadAccounts(); go("#/accounts"); }
}
document.addEventListener("change", (e) => {
  if (e.target.id !== "np") return;
  const p = e.target.value;
  const hint = { oci: t("acc.hintOci"), aws: t("acc.hintAws"), azure: t("acc.hintAzure"), ...PROV_HINT }[p];
  $("#cf").innerHTML = CRED_FIELDS[p].map(credInput).join("");
  $("#hint").textContent = hint;
});

// ---------- 账号：存活天数、测活、信息、批量添加 ----------
export function acctTypeTag(a) {   // v1.6：缓存的账号类型（点「类型」查询后显示）
  try { const ty = a.acct_type ? JSON.parse(a.acct_type) : null; return ty && ty.label ? ` <span class="badge" title="${esc(ty.plan_type || "")}">${esc(ty.label)}${ty.age_days != null ? t("acc.ageDaysSuffix", { n: ty.age_days }) : ""}</span>` : ""; } catch (_) { return ""; }
}
export function ageText(a) {
  if (!a.cloud_created_at) return `<span class="muted">${t("common.notFilled")}</span>`;
  const days = Math.floor((Date.now() - new Date(a.cloud_created_at + "T00:00:00").getTime()) / 86400000);
  return `${esc(a.cloud_created_at)}<div class="muted">${t("acc.aliveDays", { n: days })}</div>`;
}
export function testCell(a, r) {
  const ok = r ? r.ok : a.last_test_ok, ms = r ? r.ms : a.last_test_ms, err = r ? r.error : a.last_test_error;
  if (ok == null) return `<span class="muted">${t("acc.untested")}</span>`;
  return ok ? `<span class="badge running">${t("acc.reachable")}</span> <span class="muted">${ms} ms</span>`
    : `<span class="badge failed">${t("acc.failed")}</span> <span class="muted" title="${esc(err || "")}">${esc((err || "").slice(0, 40))}</span>`;
}
export async function accountInfoDialog(a) {
  const r = await modal(t("acc.infoTitle", { name: a.name }), `<label>${a.provider === "azure" ? t("acc.createdLabelAzure") : t("acc.createdLabel")}</label>
    <input name="cloud_created_at" type="date" value="${esc(a.cloud_created_at || "")}">
    <p class="muted">${a.provider === "oci" ? `${t("acc.ociCreatedNote")} <button type="button" class="btn sm" id="ccDetect">${t("acc.detectBtn")}</button> <span id="ccMsg"></span>` : t("acc.createdManual")}</p>
    ${a.provider === "azure" ? `<label>${t("acc.eduLabel")}</label><input name="edu_expires_at" type="date" value="${esc(a.edu_expires_at || "")}">` : ""}`,
    (bg) => api(`/accounts/${a.id}`, { method: "PATCH", body: form(bg) }), t("common.save"), false, (bg) => {
      const b = bg.querySelector("#ccDetect");
      if (!b) return;
      const go = async () => {
        const m = bg.querySelector("#ccMsg"); b.disabled = true; m.innerHTML = `<span class="spin"></span>`;
        try { const r = await post(`/accounts/${a.id}/detect-created`, {}); bg.querySelector('[name="cloud_created_at"]').value = r.cloud_created_at; a.cloud_created_at = r.cloud_created_at; m.textContent = t("acc.detected"); }
        catch (e) { m.textContent = `❌ ${e.message}`; } finally { b.disabled = false; }
      };
      b.onclick = go;
      if (!a.cloud_created_at) go();
    });
  if (r) { toast(t("common.saved")); await loadAccounts(); route(); }
}
export async function batchAddAccounts(prefill) {
  const sample = t("acc.batchSample");
  const r = await modal(t("acc.batchTitle"), `<p class="muted">${t("acc.batchIntro")}</p>
    <textarea name="text" style="min-height:260px" placeholder="${esc(sample)}">${esc(prefill || "")}</textarea>
    <div class="row2"><div><label>${t("acc.batchProviderLabel")}</label><select name="provider">${provOpts(t("acc.batchNoGuess"))}</select></div>
    <div><label>&nbsp;</label><label><input type="checkbox" name="dry_run"> ${t("acc.batchDry")}</label></div></div>`, (bg) => {
    const f = form(bg); if (!f.text) throw new Error(t("acc.batchEmpty"));
    toast(t("acc.batchVerifying"));
    return post("/accounts/batch", { text: bg.querySelector("[name=text]").value, provider: f.provider || undefined, dry_run: f.dry_run });
  }, t("acc.batchGo"));
  if (!r) return;
  await modal(t("acc.batchResult", { ok: r.ok, total: r.total }), `<table><tr><th>#</th><th>${t("acc.colName")}</th><th>${t("acc.colCloud")}</th><th>${t("acc.colResult")}</th></tr>
    ${r.results.map((x) => `<tr><td>${x.index}</td><td>${esc(x.name || "-")}</td><td>${x.provider ? `<span class="dot ${x.provider}"></span> ${PNAME[x.provider] || esc(x.provider)}` : "-"}</td>
    <td>${x.ok ? `<span class="badge running">${x.dry_run ? t("acc.formatOk") : t("acc.addedShort")}</span>${x.ms ? ` <span class="muted">${x.ms} ms</span>` : ""}` : `<span class="badge failed">${t("acc.failed")}</span> <span class="muted">${esc(x.error)}</span>`}</td></tr>`).join("")}</table>`, null, t("common.gotIt"));
  await loadAccounts(); route();
}

// ---- 已删账号（账号管理入口）。注意与 AWS「闲置资源」估算不是一回事 ----
export async function pageDeletedAccounts() {
  loading();
  const d = await api("/recycle-bin");
  const s = d.stats;
  const money = (x) => (x == null ? "—" : `${x.currency === "USD" || !x.currency ? "$" : ""}${(+x.est_cost).toFixed(2)}${x.currency && x.currency !== "USD" ? " " + esc(x.currency) : ""}`);
  view.innerHTML = `<div class="bar"><a class="btn" href="#/accounts">${t("acc.backAccounts")}</a><span class="grow"></span>
    ${s.count ? `<button class="btn danger" id="clr">${t("acc.clearRecords")}</button>` : ""}</div>
  <div class="grid"><div class="card"><h3>${t("acc.deletedTitle")}</h3><div class="big">${s.count}</div><div class="muted">${Object.entries(s.by_provider).map(([k, v]) => `${PNAME[k] || esc(k)} ${v}`).join(" · ") || t("common.none")}</div></div>
    <div class="card"><h3>${t("acc.lifespan")}</h3><div class="big">${s.avg_lifecycle_days ?? "—"}</div><div class="muted">${t("acc.lifeAvg", { max: s.max_lifecycle_days ?? "—" })}</div></div>
    <div class="card"><h3>${t("acc.estCostTotal")}</h3><div class="big">$${(s.total_est_cost_usd || 0).toFixed(2)}</div><div class="muted">${t("acc.estCostMax", { max: (s.max_est_cost_usd || 0).toFixed(2) })}</div></div></div>
  <div class="card"><p class="muted">${t("acc.deletedIntro")}</p>
    <table><tr><th>${t("acc.colName")}</th><th>${t("acc.colCloud")}</th><th>${t("acc.colLife")}</th><th>${t("acc.colEstCost")}</th><th>${t("acc.colDeletedAt")}</th><th></th></tr>
    ${d.items.map((x) => `<tr><td>${esc(x.name)}${x.source === "legacy" ? ` <span class="badge">${t("acc.legacy")}</span>` : ""}</td><td><span class="dot ${esc(x.provider)}"></span> ${PNAME[x.provider] || esc(x.provider)}</td>
    <td>${x.lifecycle_days == null ? "—" : t("common.days", { n: x.lifecycle_days })}<div class="muted">${esc(x.age_basis || "")}</div></td>
    <td>${money(x)}<div class="muted">${esc(x.cost_basis || "")}</div></td><td>${fmtDT(x.deleted_at)}</td>
    <td><button class="btn sm" data-rdel="${x.id}">${t("acc.removeRecord")}</button></td></tr>`).join("") || `<tr><td colspan="6" class="muted">${t("acc.noDeleted")}</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-rdel]").forEach((b) => (b.onclick = async () => { await act(b, () => del(`/recycle-bin/${b.dataset.rdel}`)); pageDeletedAccounts(); }));
  if ($("#clr")) $("#clr").onclick = async () => { if (await confirmBox(t("acc.clearTitle"), t("acc.clearConfirm"), true)) { await act(null, () => del("/recycle-bin?confirm=true"), t("acc.cleared")); pageDeletedAccounts(); } };
}

// ---- 账号编辑：非敏感字段回显，密钥类留空不改；代理 URL + 用户名 + 密码 ----
export const CRED_LABEL = { user: "cred.user", tenancy: "cred.tenancy", fingerprint: "cred.fingerprint", key_content: "cred.keyContent", pass_phrase: "cred.passPhrase", region: "cred.region",
  compartment: "cred.compartmentShort", home_region: "cred.homeRegionShort", access_key: "cred.accessKey", secret_key: "cred.secretKey", tenant_id: "cred.tenantId",
  client_id: "cred.clientId", client_secret: "cred.clientSecret", subscription_id: "cred.subscriptionId" };
export const proxyFields = (d = {}) => `<label>${t("acc.pfAddr")}</label><input name="proxy" value="${esc(d.proxyUrl || "")}" placeholder="${t("acc.pfPh")}" autocomplete="off">
  <div class="row2"><div><label>${t("acc.pfUser")}</label><input name="proxy_user" value="${esc(d.proxy_user || "")}" autocomplete="off"></div>
  <div><label>${d.proxy_pass_set ? t("acc.pfPassSet") : t("acc.pfPassOpt")}</label><input name="proxy_pass" type="password" placeholder="${d.proxy_pass_set ? t("acc.pfPassPh") : ""}" autocomplete="new-password"></div></div>
  ${d.proxy_pass_set ? `<label><input type="checkbox" name="proxy_pass_clear" style="width:auto"> ${t("acc.pfPassClear")}</label>` : ""}
  <p class="muted">${t("acc.pfNote")}</p>`;
export async function editAccount(a) {
  let d;
  if (!a) return toast(t("acc.notFound"), true);
  toast(t("acc.reading"));
  try { d = await Promise.race([api(`/accounts/${a.id}/detail`), new Promise((_, rj) => setTimeout(() => rj(new Error(t("acc.readTimeout"))), 15000))]); }
  catch (e) { return toast(e.message, true); }
  const fld = Object.entries(d.fields).map(([k, v]) => {
    const label = CRED_LABEL[k] ? t(CRED_LABEL[k]) : k;
    if (typeof v === "string") return TEXTAREA_FIELDS.has(k) ? `<label>${label}</label><textarea name="c_${k}" rows="4" class="mono">${esc(v)}</textarea>`
      : `<label>${label}</label><input name="c_${k}" value="${esc(v)}" autocomplete="off">`;
    const ph = v.set ? t("acc.fieldSet", { hint: v.hint ? " " + v.hint : "" }) : t("acc.fieldUnset");
    return TEXTAREA_FIELDS.has(k) ? `<label>${label}</label><textarea name="c_${k}" placeholder="${esc(ph)}"></textarea>`
      : `<label>${label}</label><input name="c_${k}" type="${/secret|pass_phrase/.test(k) ? "password" : "text"}" placeholder="${esc(ph)}" autocomplete="new-password">`;
  }).join("");
  const r = await modal(t("acc.editTitle", { name: a.name }), `<label>${t("acc.nameLabel")}</label><input name="name" value="${esc(d.name)}">${fld}
    <h4 style="margin:14px 0 4px">${t("acc.proxyTitle")}</h4>${proxyFields(d)}
    <p class="muted">${t("acc.editNote")}</p>`, async (bg) => {
    const f = form(bg); const body = { name: f.name }; const cred = {};
    for (const k in f) if (k.startsWith("c_")) cred[k.slice(2)] = f[k];
    if (Object.keys(cred).length) body.cred = cred;
    if (f.proxy) body.proxy = f.proxy;
    if (f.proxy_user !== (d.proxy_user || "")) body.proxy_user = f.proxy_user;
    if (f.proxy_pass) body.proxy_pass = f.proxy_pass;
    if (f.proxy_pass_clear) body.proxy_pass_clear = true;
    return api(`/accounts/${a.id}`, { method: "PATCH", body });
  }, t("common.save"));
  if (r) { toast(t("common.saved")); await loadAccounts(); route(); }
}

// ---- OCI config 粘贴识别：多 profile 段 + PEM 私钥 ----
// v1.6：添加账号弹窗的「粘贴自动识别」，由后端 /accounts/parse 统一解析
export let SMART_ITEMS = [], SMART_T = 0;
export function smartFill() {
  const sel = document.getElementById("smartpick"), hint = document.getElementById("smarthint");
  if (!sel || !hint) return;
  const it = SMART_ITEMS[+sel.value || 0];
  if (!it) return;
  const np = document.getElementById("np");
  if (np && np.value !== it.provider) { np.value = it.provider; np.dispatchEvent(new Event("change", { bubbles: true })); }
  for (const [k, v] of Object.entries(it.cred || {})) { const el = document.querySelector(`.modal [name="c_${k}"]`); if (el && v) el.value = v; }
  const nm = document.querySelector('.modal [name="name"]');
  if (nm && it.name && (!nm.value || nm.dataset.auto)) { nm.value = it.name; nm.dataset.auto = "1"; }
  hint.innerHTML = `${t("acc.smartOk", { p: PNAME[it.provider] || esc(it.provider) })}` + (it.missing.length ? t("acc.smartMissing", { list: it.missing.map(esc).join("、") }) : t("acc.smartComplete"))
    + (it.error ? `；${esc(it.error)}` : "")
    + (SMART_ITEMS.length > 1 ? `${t("acc.smartMulti", { n: SMART_ITEMS.length })}<a href="#" id="smartbatch">${t("acc.smartBatchAll")}</a>` : "");
  const bl = document.getElementById("smartbatch");
  if (bl) bl.onclick = (e) => { e.preventDefault(); const t = document.getElementById("smarttext").value; document.querySelector(".modal [data-x]")?.click(); batchAddAccounts(t); };
}
export async function smartParse() {
  const ta = document.getElementById("smarttext"), sel = document.getElementById("smartpick"), hint = document.getElementById("smarthint");
  if (!ta) return;
  if (!ta.value.trim()) { SMART_ITEMS = []; sel.style.display = "none"; hint.textContent = ""; return; }
  try {
    const r = await post("/accounts/parse", { text: ta.value });
    SMART_ITEMS = (r.items || []).filter((x) => x.provider);
    if (!SMART_ITEMS.length) { sel.style.display = "none"; hint.textContent = t("acc.smartNone"); return; }
    sel.innerHTML = SMART_ITEMS.map((x, i) => `<option value="${i}">${i + 1}. ${PNAME[x.provider]} · ${esc(x.name || t("acc.unnamed"))}</option>`).join("");
    sel.style.display = SMART_ITEMS.length > 1 ? "" : "none";
    smartFill();
  } catch (e) { hint.textContent = `❌ ${e.message}`; }
}
document.addEventListener("input", (e) => { if (e.target.id === "smarttext") { clearTimeout(SMART_T); SMART_T = setTimeout(smartParse, 350); } });
document.addEventListener("change", (e) => { if (e.target.id === "smartpick") smartFill(); });

// ---------- 11. 账号类型 / 停用 ----------
export async function accountTypeDialog(a, refresh) {
  let r;
  try { toast(t("acc.typeQuerying")); r = await api(`/accounts/${a.id}/account-type${refresh ? "?refresh=1" : ""}`); } catch (e) { return toast(e.message, true); }
  const ok = await modal(t("acc.typeTitle", { name: a.name }), `<div class="kv"><span>${t("common.type")}</span><span><b>${esc(r.label || "-")}</b></span>
    ${r.plan_type ? `<span>${t("acc.tPlan")}</span><span class="mono">${esc(r.plan_type)}</span>` : ""}${r.account_type ? `<span>${t("common.account")}</span><span>${esc(r.account_type)}</span>` : ""}
    ${r.upgrade_state ? `<span>${t("acc.tUpgrade")}</span><span>${esc(r.upgrade_state)}</span>` : ""}${r.time_start ? `<span>${t("acc.tStart")}</span><span>${esc(r.time_start)}</span>` : ""}
    ${r.age_days != null ? `<span>${t("acc.tAge")}</span><span>${t("common.days", { n: r.age_days })}</span>` : ""}${r.home_region ? `<span>${t("acc.tHome")}</span><span>${esc(regionLabel(r.home_region))}</span>` : ""}
    ${r.state ? `<span>${t("acc.tState")}</span><span>${esc(r.state)}</span>` : ""}</div>${r.error || r.hint ? `<p class="muted">${esc(r.error || r.hint)}</p>` : ""}
    <p class="muted">${t("acc.tCheckedAt", { t: new Date((r.checked_at || 0) * 1000).toLocaleString() })}</p>`, null, t("acc.tRequery"));
  if (ok) accountTypeDialog(a, true);
}
export async function toggleDisable(a) {
  if (a.disabled) {
    if (await act(null, () => post(`/accounts/${a.id}/disable`, { disabled: false }), t("common.enabled"))) { await loadAccounts(); route(); }
    return;
  }
  const r = await modal(t("acc.disableTitle"), `<p>${t("acc.disableIntro", { name: esc(a.name) })}</p><ul class="guard"><li>${t("acc.dis1")}</li><li>${t("acc.dis2")}</li><li>${t("acc.dis3")}</li></ul>
    <label>${t("acc.disReason")}</label><input name="reason" placeholder="${t("acc.disReasonPh")}">`, (bg) => post(`/accounts/${a.id}/disable`, { disabled: true, ...form(bg) }), t("acc.disable"), true);
  if (r) { toast(`${t("acc.disabledToast")}${r.stopped_tasks.length ? t("acc.disabledTasks", { n: r.stopped_tasks.length }) : ""}`); await loadAccounts(); route(); }
}
