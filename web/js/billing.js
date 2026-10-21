// TriCloud 前端 v1.6.0 · 账单与 Credit / 教育优惠
import { t } from "./i18n.js";
import { $, ACCOUNTS, act, api, confirmBox, del, esc, form, modal, post } from "./core.js";
import { accountInfoDialog } from "./accounts.js";

// ---------------- 账单 ----------------
export async function tabBilling(acc, box, force = false) {
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let b;
  try { b = await api(`/accounts/${acc.id}/billing${force ? "?force=true" : ""}`); }
  catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div><div id="credbox"></div>`; creditCard(acc, $("#credbox", box)); return; }
  const isAws = acc.provider === "aws";
  let html = `<div class="grid"><div class="card"><h3>${t("bill.thisMonth")}</h3><div class="big">${b.no_cache ? "—" : esc(b.total)} <span style="font-size:14px">${esc(b.currency)}</span></div>
    <div class="muted">${esc(b.period)} · ${t("bill.updatedAt", { t: esc(b.updated_at) })}</div>
    ${b.no_cache ? `<div class="muted">${t("bill.noCache", { t: esc(b.next_refresh) })}</div>` : ""}
    ${isAws ? `<div class="muted">${t("bill.awsNote", { next: esc(b.next_refresh), n: esc(b.ce_calls_this_month) })}</div>
    <div class="bar" style="margin-top:8px"><button class="btn sm" id="force">${t("bill.forceBtn")}</button></div>` : ""}</div>`;
  if (isAws) {
    const c = b.credits;
    html += `<div class="card"><h3>${t("bill.creditBalance")}</h3><div class="big">${b.no_cache ? "—" : "$" + esc(c.remaining)}</div>
      <div class="muted">${t("bill.creditTotalLine", { total: esc(c.total), used: esc(c.used) })}</div></div>`;
  }
  html += `</div><div class="card"><h3>${t("bill.byService")}</h3>${b.services.length ? `<table><tr><th>${t("bill.colService")}</th><th style="text-align:right">${t("bill.colAmount")}</th></tr>
    ${b.services.map((s) => `<tr><td>${esc(s.service)}</td><td style="text-align:right">${esc(s.amount)}</td></tr>`).join("")}</table>` : `<div class="muted">${t("bill.noCost")}</div>`}</div>`;
  html += `<div id="credbox"><div class="card"><span class="spin"></span> ${t("bill.readingCredit")}</div></div>`;
  box.innerHTML = html;
  creditCard(acc, $("#credbox", box));   // v1.4：Credit 与教育优惠（三家云通用）
  if (!isAws) return;
  $("#force", box).onclick = async () => {
    if (await confirmBox(t("bill.forceTitle"), t("bill.forceConfirm"))) tabBilling(acc, box, true);
  };
}

// ---------- 账单页：Credit 与教育优惠 ----------
export async function creditCard(acc, box) {
  if (!box) return;
  let s;
  try { s = await api(`/accounts/${acc.id}/credit-summary`); } catch (e) { box.innerHTML = `<div class="card">❌ ${t("bill.creditErr", { msg: esc(e.message) })}</div>`; return; }
  const money = (v) => (v == null ? "—" : "$" + (+v).toFixed(2));
  const src = { billing: t("bill.srcBilling"), manual: t("bill.srcManual") };
  const edu = s.edu;
  box.innerHTML = `<div class="card" id="credit"><div class="bar"><h3 class="grow" style="margin:0">${t("bill.creditTitle")}</h3>
    <button class="btn sm" id="ctot">${t("bill.setTotal")}</button><button class="btn sm primary" id="cadd">${t("bill.addCredit")}</button></div>
    ${s.alerts.length ? s.alerts.map((a) => `<div class="al ${a.days_left <= 7 ? "bad" : "warn"}">⏰ ${esc(a.name)} ${a.days_left === 0 ? t("common.expiresToday") : t("common.daysLeft", { n: a.days_left })}（${esc(a.date)}${a.estimated ? t("bill.estimatedComma") : ""}）</div>`).join("") : ""}
    <div class="grid3"><div><div class="muted">${s.credit_total_manual ? t("bill.totalManual") : t("bill.totalSum")}</div><div class="big">${money(s.credit_total)}</div></div>
      <div><div class="muted">${t("bill.used")}${s.used_source ? ` (${src[s.used_source]})` : ""}</div><div class="big">${money(s.used)}</div></div>
      <div><div class="muted">${t("bill.remaining")}</div><div class="big">${money(s.remaining)}</div></div></div>
    <p class="muted">${s.used == null && s.items.length ? t("bill.usedUnknown") : ""}${t("bill.estLine", { note: esc(s.estimate_note || "-"), upd: s.billing_updated_at ? t("bill.billingUpdated", { t: esc(s.billing_updated_at) }) : "" })}
      ${acc.provider === "aws" ? t("bill.awsCacheNote") : t("bill.fifoNote")}</p>
    <table><tr><th>${t("bill.colName")}</th><th>${t("bill.colInitial")}</th><th>${t("bill.used")}</th><th>${t("bill.remaining")}</th><th>${t("bill.colStart")}</th><th>${t("bill.colExpire")}</th><th></th></tr>
    ${s.items.map((c) => `<tr><td>${esc(c.name)}</td><td>${money(c.amount)}</td><td>${money(c.used)}${c.used_source ? `<div class="muted">${src[c.used_source]}</div>` : `<div class="muted">${t("bill.usedUnknownShort")}</div>`}</td>
      <td>${money(c.remaining)}</td><td>${esc(c.start_date || "-")}</td>
      <td>${esc(c.expire_date || "-")}${c.days_left != null ? `<div class="muted">${c.expired ? t("common.expired") : t("common.daysLeft", { n: c.days_left })}</div>` : ""}</td>
      <td><button class="btn sm" data-ced="${c.id}">${t("common.edit")}</button> <button class="btn sm danger" data-cdel="${c.id}">${t("common.delete")}</button></td></tr>`).join("") || `<tr><td colspan=7 class="muted">${t("bill.noCredits")}</td></tr>`}</table>
    <div class="kv" style="margin-top:14px"><span>${t("bill.cloudCreated")}</span><span>${s.cloud_created_at ? `${esc(s.cloud_created_at)}${t("bill.aliveDays", { n: s.age_days })}` : `<span class="muted">${t("common.notFilled")}</span>`}</span>
    ${edu ? `<span>${t("bill.edu")}</span><span>${edu.expires_at ? `${esc(edu.expires_at)}${edu.estimated ? ` <span class="badge pending">${t("bill.estimated")}</span>` : ""} · ${edu.days_left >= 0 ? t("common.daysLeft", { n: edu.days_left }) : t("common.expired")}` : t("bill.eduUnknown")}
      <div class="muted">${esc(edu.basis)}</div></span>` : ""}</div>
    <div class="bar"><button class="btn sm" id="cinfo">${edu ? t("bill.setDatesEdu") : t("bill.setCreated")}</button></div></div>`;
  const again = () => creditCard(acc, box);
  const credForm = (c = {}) => `<label>${t("bill.colName")}</label><input name="name" value="${esc(c.name || (acc.provider === "azure" ? t("bill.defAzure") : acc.provider === "oci" ? t("bill.defOci") : t("bill.defAws")))}">
    <div class="row2"><div><label>${t("bill.fAmount")}</label><input name="amount" type="number" step="0.01" min="0" value="${c.amount ?? ""}"></div>
    <div><label>${t("bill.fUsed")}</label><input name="used_manual" type="number" step="0.01" min="0" value="${c.used_manual ?? ""}"></div>
    <div><label>${acc.provider === "aws" ? t("bill.fStartAws") : t("bill.fStartOpt")}</label><input name="start_date" type="date" value="${esc(c.start_date || "")}"></div>
    <div><label>${t("bill.fExpire")}</label><input name="expire_date" type="date" value="${esc(c.expire_date || "")}"></div></div>
    <p class="muted">${t("bill.fNote")}</p>`;
  $("#cadd", box).onclick = async () => {
    const r = await modal(t("bill.addCredit"), credForm(), (bg) => { const f = form(bg); if (!f.amount) throw new Error(t("bill.amountRequired")); return post(`/accounts/${acc.id}/credits-manual`, f); }, t("common.save"));
    if (r) again();
  };
  $("#ctot", box).onclick = async () => {
    const r = await modal(t("bill.totalTitle"), `<label>${t("bill.totalLabel")}</label><input name="credit_total" type="number" step="0.01" min="0" value="${s.credit_total_manual ? s.credit_total : ""}">`,
      (bg) => api(`/accounts/${acc.id}/credit-total`, { method: "PUT", body: form(bg) }), t("common.save"));
    if (r) again();
  };
  $("#cinfo", box).onclick = () => accountInfoDialog(ACCOUNTS.find((a) => a.id === acc.id) || acc);
  box.querySelectorAll("[data-ced]").forEach((b) => (b.onclick = async () => {
    const c = s.items.find((x) => x.id == b.dataset.ced);
    const r = await modal(t("bill.editCredit"), credForm(c), (bg) => api(`/accounts/${acc.id}/credits-manual/${c.id}`, { method: "PUT", body: form(bg) }), t("common.save"));
    if (r) again();
  }));
  box.querySelectorAll("[data-cdel]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox(t("bill.delTitle"), t("bill.delConfirm"), true)) { await act(b, () => del(`/accounts/${acc.id}/credits-manual/${b.dataset.cdel}`), t("common.deleted")); again(); }
  }));
}
