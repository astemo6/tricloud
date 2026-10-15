// TriCloud 前端 v1.6.0 · 账单与 Credit / 教育优惠
import { $, ACCOUNTS, act, api, confirmBox, del, esc, form, modal, post } from "./core.js";
import { accountInfoDialog } from "./accounts.js";

// ---------------- 账单 ----------------
export async function tabBilling(acc, box, force = false) {
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let b;
  try { b = await api(`/accounts/${acc.id}/billing${force ? "?force=true" : ""}`); }
  catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div><div id="credbox"></div>`; creditCard(acc, $("#credbox", box)); return; }
  const isAws = acc.provider === "aws";
  let html = `<div class="grid"><div class="card"><h3>本月费用</h3><div class="big">${b.no_cache ? "—" : esc(b.total)} <span style="font-size:14px">${esc(b.currency)}</span></div>
    <div class="muted">${esc(b.period)} · 数据更新于 ${esc(b.updated_at)}</div>
    ${b.no_cache ? `<div class="muted">尚无缓存：将在 ${esc(b.next_refresh)} 自动查询，或点手动刷新（收费）</div>` : ""}
    ${isAws ? `<div class="muted">AWS 账单每月仅在 15 号与月末自动查询（Cost Explorer $0.01/次），下次：${esc(b.next_refresh)}；本月已调用 ${esc(b.ce_calls_this_month)} 次</div>
    <div class="bar" style="margin-top:8px"><button class="btn sm" id="force">手动刷新（约 $0.02）</button></div>` : ""}</div>`;
  if (isAws) {
    const c = b.credits;
    html += `<div class="card"><h3>Credit 余额</h3><div class="big">${b.no_cache ? "—" : "$" + esc(c.remaining)}</div>
      <div class="muted">总额 $${esc(c.total)} − 已抵扣 $${esc(c.used)}（CE 自最早 Credit 起始日累计）</div></div>`;
  }
  html += `</div><div class="card"><h3>按服务</h3>${b.services.length ? `<table><tr><th>服务</th><th style="text-align:right">金额</th></tr>
    ${b.services.map((s) => `<tr><td>${esc(s.service)}</td><td style="text-align:right">${esc(s.amount)}</td></tr>`).join("")}</table>` : `<div class="muted">本月暂无费用</div>`}</div>`;
  html += `<div id="credbox"><div class="card"><span class="spin"></span> 读取 Credit…</div></div>`;
  box.innerHTML = html;
  creditCard(acc, $("#credbox", box));   // v1.4：Credit 与教育优惠（三家云通用）
  if (!isAws) return;
  $("#force", box).onclick = async () => {
    if (await confirmBox("手动刷新 AWS 账单", "这会调用 Cost Explorer API（每次 $0.01，本次约 1–2 次）。确定？")) tabBilling(acc, box, true);
  };
}

// ---------- 账单页：Credit 与教育优惠 ----------
export async function creditCard(acc, box) {
  if (!box) return;
  let s;
  try { s = await api(`/accounts/${acc.id}/credit-summary`); } catch (e) { box.innerHTML = `<div class="card">❌ Credit：${esc(e.message)}</div>`; return; }
  const money = (v) => (v == null ? "—" : "$" + (+v).toFixed(2));
  const src = { billing: "按账单估算", manual: "手动填写" };
  const edu = s.edu;
  box.innerHTML = `<div class="card" id="credit"><div class="bar"><h3 class="grow" style="margin:0">Credit 与优惠</h3>
    <button class="btn sm" id="ctot">设置总额</button><button class="btn sm primary" id="cadd">添加 Credit</button></div>
    ${s.alerts.length ? s.alerts.map((a) => `<div class="al ${a.days_left <= 7 ? "bad" : "warn"}">⏰ ${esc(a.name)} ${a.days_left === 0 ? "今天到期" : `还剩 ${a.days_left} 天`}（${esc(a.date)}${a.estimated ? "，估算" : ""}）</div>`).join("") : ""}
    <div class="grid3"><div><div class="muted">Credit 总额${s.credit_total_manual ? "（手动设置）" : "（各条合计）"}</div><div class="big">${money(s.credit_total)}</div></div>
      <div><div class="muted">已用${s.used_source ? `（${src[s.used_source]}）` : ""}</div><div class="big">${money(s.used)}</div></div>
      <div><div class="muted">剩余</div><div class="big">${money(s.remaining)}</div></div></div>
    <p class="muted">${s.used == null && s.items.length ? "已用额度暂时估不出，可在每条 Credit 里手动填写。" : ""}估算依据：${esc(s.estimate_note || "-")}${s.billing_updated_at ? `（账单数据更新于 ${esc(s.billing_updated_at)}）` : ""}。
      ${acc.provider === "aws" ? "AWS 只读账单缓存，不会额外调用 Cost Explorer。" : "先到期的 Credit 先抵扣。"}</p>
    <table><tr><th>名称</th><th>初始额度</th><th>已用</th><th>剩余</th><th>起始</th><th>到期</th><th></th></tr>
    ${s.items.map((c) => `<tr><td>${esc(c.name)}</td><td>${money(c.amount)}</td><td>${money(c.used)}${c.used_source ? `<div class="muted">${src[c.used_source]}</div>` : `<div class="muted">估不出</div>`}</td>
      <td>${money(c.remaining)}</td><td>${esc(c.start_date || "-")}</td>
      <td>${esc(c.expire_date || "-")}${c.days_left != null ? `<div class="muted">${c.expired ? "已过期" : `剩 ${c.days_left} 天`}</div>` : ""}</td>
      <td><button class="btn sm" data-ced="${c.id}">编辑</button> <button class="btn sm danger" data-cdel="${c.id}">删除</button></td></tr>`).join("") || `<tr><td colspan=7 class="muted">还没有录入 Credit</td></tr>`}</table>
    <div class="kv" style="margin-top:14px"><span>云上创建</span><span>${s.cloud_created_at ? `${esc(s.cloud_created_at)}（已存活 ${s.age_days} 天）` : `<span class="muted">未填写</span>`}</span>
    ${edu ? `<span>教育优惠</span><span>${edu.expires_at ? `${esc(edu.expires_at)}${edu.estimated ? ` <span class="badge pending">估算</span>` : ""} · ${edu.days_left >= 0 ? `剩 ${edu.days_left} 天` : "已过期"}` : "未知"}
      <div class="muted">${esc(edu.basis)}</div></span>` : ""}</div>
    <div class="bar"><button class="btn sm" id="cinfo">${edu ? "设置创建日期 / 教育优惠到期日" : "设置云账号创建日期"}</button></div></div>`;
  const again = () => creditCard(acc, box);
  const credForm = (c = {}) => `<label>名称</label><input name="name" value="${esc(c.name || (acc.provider === "azure" ? "Azure 学生 Credit" : acc.provider === "oci" ? "OCI 试用 Credit" : "AWS Credit"))}">
    <div class="row2"><div><label>初始额度（USD）</label><input name="amount" type="number" step="0.01" min="0" value="${c.amount ?? ""}"></div>
    <div><label>已用额度（留空 = 按账单估算）</label><input name="used_manual" type="number" step="0.01" min="0" value="${c.used_manual ?? ""}"></div>
    <div><label>起始日期${acc.provider === "aws" ? "（AWS 用于统计累计抵扣）" : "（可选）"}</label><input name="start_date" type="date" value="${esc(c.start_date || "")}"></div>
    <div><label>到期日期</label><input name="expire_date" type="date" value="${esc(c.expire_date || "")}"></div></div>
    <p class="muted">30 天内到期会在总览提醒，并在 30 / 7 / 1 天各推送一次 Telegram。</p>`;
  $("#cadd", box).onclick = async () => {
    const r = await modal("添加 Credit", credForm(), (bg) => { const f = form(bg); if (!f.amount) throw new Error("初始额度必填"); return post(`/accounts/${acc.id}/credits-manual`, f); }, "保存");
    if (r) again();
  };
  $("#ctot", box).onclick = async () => {
    const r = await modal("Credit 总额", `<label>总额（USD，留空 = 各条 Credit 之和）</label><input name="credit_total" type="number" step="0.01" min="0" value="${s.credit_total_manual ? s.credit_total : ""}">`,
      (bg) => api(`/accounts/${acc.id}/credit-total`, { method: "PUT", body: form(bg) }), "保存");
    if (r) again();
  };
  $("#cinfo", box).onclick = () => accountInfoDialog(ACCOUNTS.find((a) => a.id === acc.id) || acc);
  box.querySelectorAll("[data-ced]").forEach((b) => (b.onclick = async () => {
    const c = s.items.find((x) => x.id == b.dataset.ced);
    const r = await modal("编辑 Credit", credForm(c), (bg) => api(`/accounts/${acc.id}/credits-manual/${c.id}`, { method: "PUT", body: form(bg) }), "保存");
    if (r) again();
  }));
  box.querySelectorAll("[data-cdel]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("删除 Credit", "确定删除这条 Credit？", true)) { await act(b, () => del(`/accounts/${acc.id}/credits-manual/${b.dataset.cdel}`), "已删除"); again(); }
  }));
}
