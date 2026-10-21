// TriCloud 前端 v1.6.0 · AWS：EC2 创建、Lightsail、区域、配额、闲置资源、CloudFront
import { $, act, api, confirmBox, del, esc, form, modal, post, regionLabel, regionOf, regionOpt, regionSelect, rq, SETTINGS, toast } from "./core.js";
import { go } from "./router.js";
import { loginFields, showCreated, tabInstances } from "./instances.js";
import { saveDefaultBtn } from "./settings.js";
import { getLang, t, tr } from "./i18n.js";

// ---------------- Lightsail ----------------
export const tabLightsail = (acc, box) => tabInstances(acc, box, "lightsail");
export async function lightsailCreate(acc, reload) {
  let o;
  try { toast(t("aws.readingLs")); o = await api(`/accounts/${acc.id}/lightsail/options?${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  const d = SETTINGS.default_create?.lightsail || {};
  const r = await modal(t("aws.createLs"), `<label>${t("acc.colName")}</label><input name="name" value="ls-${Date.now().toString(36)}">
    <label>${t("inst.zone")}</label><select name="zone">${o.zones.map((z) => regionOpt(z, z === d.zone)).join("")}</select>
    <label>${t("aws.blueprint")}</label><select name="blueprint">${o.blueprints.map((b) => `<option value="${esc(b.id)}" ${b.id === d.blueprint ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select>
    <label>${t("aws.bundle")}</label><select name="bundle">${o.bundles.map((b) => `<option value="${esc(b.id)}" ${b.id === d.bundle ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select>
    <label>${t("aws.network")}</label><select name="ip_type"><option value="dualstack">IPv4 + IPv6</option><option value="ipv6" ${d.ip_type === "ipv6" ? "selected" : ""}>${t("aws.ipv6Only")}</option></select>
    ${await loginFields()}<div class="bar">${saveDefaultBtn("lightsail")}</div>`,
    (bg) => post(`/accounts/${acc.id}/lightsail/create`, { ...form(bg), region: regionOf(acc) }), t("oci.create"));
  if (r) { showCreated(r); setTimeout(reload, 3000); }
}

// ---------------- 配额 ----------------
export async function tabQuota(acc, box, refresh = false) {
  box.innerHTML = `<div class="card"><span class="spin"></span> ${t("aws.quotaLoading")}</div>`;
  let q;
  try { q = await api(`/accounts/${acc.id}/quotas${refresh ? "?refresh=true" : ""}`); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const v = q.standard_vcpu, cf = q.cloudfront_distributions || {};
  box.innerHTML = `<div class="grid">
    <div class="card"><h3>${t("aws.quotaVcpu")}</h3><div class="big">${v ? esc(v.value) : "-"} ${esc(v?.unit || "")}</div>
      <div class="muted">${t("aws.quotaVcpuFrom", { region: esc(v?.region ? regionLabel(v.region) : "-") })}</div></div>
    <div class="card"><h3>${t("aws.quotaCf")}</h3><div class="big">${cf.value ?? "-"} ${esc(cf.unit || "")}</div>
      <div class="muted">${t("aws.quotaCfNote")}${cf.default ? t("aws.cfDefault") : ""}${cf.error ? " · " + esc(cf.error) : ""}</div></div></div>
    <div class="card"><div class="bar"><h3 class="grow" style="margin:0">${t("aws.perRegion")}</h3><span class="muted">${t("aws.updatedCache", { t: esc(q.updated_at) })}</span>
    <button class="btn sm" id="rf">${t("aws.requery")}</button></div>
    <table><tr><th>${t("core.region.title")}</th><th>vCPU</th></tr>${q.per_region.map((r) => `<tr><td>${esc(regionLabel(r.region))}</td><td>${r.value ?? `<span class="muted">${esc(r.error || "-")}</span>`}</td></tr>`).join("")}</table></div>`;
  $("#rf", box).onclick = () => tabQuota(acc, box, true);
}

// ---------------- 回收站估算（AWS 闲置仍计费资源） ----------------
export async function tabRecycle(acc, box) {
  const reload = () => tabRecycle(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">${t("aws.rescan")}</button></div>
    <div id="rb"><div class="card"><span class="spin"></span> ${t("aws.scanLoading")}</div></div>`;
  $("#rf", box).onclick = reload;
  const out = $("#rb", box);
  let r;
  try { r = await api(`/accounts/${acc.id}/recycle?${rq(acc)}`); } catch (e) { out.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  out.innerHTML = `<div class="grid">
    <div class="card"><h3>${t("aws.idleTitle")}</h3><div class="big">$${esc(r.monthly_total)}</div>
      <div class="muted">${t("aws.idleMeta", { r: esc(regionLabel(r.region)), n: r.items.length })}</div></div>
    <div class="card"><h3>${t("aws.billRef")}</h3><div class="big">${r.month_to_date == null ? "—" : "$" + esc(r.month_to_date)}</div>
      <div class="muted">${t("aws.billMeta", { t: esc(r.billing_updated_at) })}</div>
      ${r.credit_remaining != null ? `<div class="muted">${t("aws.creditLeft", { x: esc(r.credit_remaining), months: r.credit_months_for_idle ? t("aws.creditMonths", { m: esc(r.credit_months_for_idle) }) : "" })}</div>` : ""}</div></div>
    <div class="card"><h3>${t("aws.colDetail")}</h3>
    ${r.items.length ? `<table><tr><th>${t("aws.colResource")}</th><th>${t("aws.colDesc")}</th><th style="text-align:right">${t("aws.colMonthly")}</th><th>${t("aws.colTip")}</th></tr>
    ${r.items.map((i) => `<tr><td><b>${esc(i.name)}</b><div class="muted mono">${esc(i.id)}</div></td><td>${esc(i.detail)}</td>
    <td style="text-align:right">$${esc(i.monthly)}</td><td class="muted">${esc(i.tip)}</td></tr>`).join("")}</table>` : `<div class="empty">${t("aws.noIdle")}</div>`}</div>`;
}
export async function ec2Create(acc, reload) {
  let o;
  try { o = await api(`/accounts/${acc.id}/aws/ec2-options`); } catch (e) { return toast(e.message, true); }
  const d = SETTINGS.default_create?.aws || {};
  const r = await modal(t("inst.createEc2"), `<div class="row2">
    <div><label>${t("acc.colName")}</label><input name="name" value="ec2-${Date.now().toString(36)}"></div>
    <div><label>${t("inst.instType")}</label><input name="type" list="ec2types" value="${esc(d.type || "t3.micro")}"><datalist id="ec2types">${o.types.map((x) => `<option>${x}</option>`).join("")}</datalist></div>
    <div><label>${t("inst.os")}</label><select name="os">${o.os.map((x) => `<option ${x === d.os ? "selected" : ""}>${x}</option>`).join("")}</select></div>
    <div><label>${t("aws.ec2Disk")}</label><input name="disk_gb" type="number" min="8" value="${esc(d.disk_gb || 10)}"></div></div>
    <label>${t("aws.ec2Ports")}</label><input name="ports" placeholder="80,443" value="${esc(d.ports || "")}">
    ${await loginFields()}<div class="bar">${saveDefaultBtn("aws")}</div>`, (bg) => post(`/accounts/${acc.id}/aws/ec2-create`, { ...form(bg), region: regionOf(acc) }), t("oci.create"));
  if (r) { showCreated(r); setTimeout(reload, 4000); }
}

// AWS 区域
export async function tabAwsRegions(acc, box, refresh = false) {
  box.innerHTML = `<div class="grid"><div class="card" id="st"><span class="spin"></span> ${t("aws.regLoading")}</div><div class="card" id="sc"><span class="spin"></span> ${t("aws.scanAllLoading")}</div></div>`;
  api(`/accounts/${acc.id}/aws/regions-status`).then((rs) => {
    $("#st", box).innerHTML = `<h3>${t("aws.regAct")}</h3><p class="muted">${t("aws.regActNote")}</p><table><tr><th>${t("core.region.title")}</th><th>${t("common.status")}</th><th></th></tr>
      ${rs.map((r) => `<tr><td>${esc(regionLabel(r.region))}</td><td><span class="badge ${r.status === "ENABLED_BY_DEFAULT" || r.status === "ENABLED" ? "running" : ""}">${esc(r.status)}</span></td>
      <td>${r.status === "DISABLED" ? `<button class="btn sm" data-en="${esc(r.region)}">${t("aws.activate")}</button>` : ""}</td></tr>`).join("")}</table>`;
    box.querySelectorAll("[data-en]").forEach((b) => (b.onclick = async () => {
      const r = await act(b, () => post(`/accounts/${acc.id}/aws/enable-region`, { region: b.dataset.en }));
      if (r) { toast(r.hint); b.remove(); }
    }));
  }).catch((e) => ($("#st", box).innerHTML = `❌ ${esc(e.message)}<p class="muted">${t("aws.regPerm")}</p>`));
  api(`/accounts/${acc.id}/aws/scan${refresh ? "?refresh=true" : ""}`).then((d) => {
    const rows = d.regions.filter((r) => r.ec2 || r.lightsail);
    $("#sc", box).innerHTML = `<div class="bar"><h3 class="grow" style="margin:0">${t("aws.allInst")}</h3><span class="muted">${esc(d.updated_at)}</span><button class="btn sm" id="rs">${t("aws.rescan")}</button></div>
      ${rows.length ? `<table><tr><th>${t("core.region.title")}</th><th>${t("aws.colEc2Run")}</th><th>Lightsail</th><th></th></tr>${rows.map((r) => `<tr><td>${esc(regionLabel(r.region))}</td><td>${r.ec2}（${r.ec2_running}）</td><td>${r.lightsail ?? "-"}</td>
      <td><button class="btn sm" data-go="${esc(r.region)}">${t("aws.view")}</button></td></tr>`).join("")}</table>` : `<div class="empty">${t("aws.noInstAny")}</div>`}`;
    $("#rs", box).onclick = () => tabAwsRegions(acc, box, true);
    box.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => { localStorage.setItem("tc_region_" + acc.id, b.dataset.go); go(`#/aws/${acc.id}/ec2`); }));
  }).catch((e) => ($("#sc", box).innerHTML = `❌ ${esc(e.message)}`));
}

// ---- CloudFront：新建 / 缓存刷新 / 编辑配置 / 启停 / 套餐 / 删除（启用中先停用再删） ----
export const CF_PLAN = { PAYGO: "aws.cfPaygo", FREE: "aws.cfFree", PRO: "aws.cfPro", BUSINESS: "aws.cfBusiness", PREMIUM: "aws.cfPremium" };
export const cfPlanLabel = (p) => (CF_PLAN[p] ? t(CF_PLAN[p]) : p);
export async function tabCloudFront(acc, box) {
  const reload = () => tabCloudFront(acc, box);
  box.innerHTML = `<div class="bar"><button class="btn" id="rf">${t("common.refresh")}</button><button class="btn primary" id="new">${t("aws.cfNew")}</button>
    <span class="grow"></span><span class="muted">${t("aws.cfNote")}</span></div><div class="card" id="t"><span class="spin"></span></div>`;
  $("#rf", box).onclick = reload;
  $("#new", box).onclick = async () => {
    const r = await modal(t("aws.cfNewTitle"), `<label>${t("aws.cfOrigin")}</label><input name="origin" placeholder="${t("aws.cfOriginPh")}">
      <div class="row2"><div><label>${t("aws.cfProto")}</label><select name="origin_protocol"><option value="http-only">HTTP</option><option value="https-only">HTTPS</option><option value="match-viewer">${t("aws.cfMatch")}</option></select></div>
      <div><label>${t("aws.cfPrice")}</label><select name="price_class"><option value="all">${t("aws.cfPriceAll")}</option><option value="200">${t("aws.cfPrice200")}</option><option value="100">${t("aws.cfPrice100")}</option></select></div>
      <div><label>${t("aws.cfCache")}</label><select name="cache_mode"><option value="disabled">${t("aws.cfCacheOff")}</option><option value="optimized">${t("aws.cfCacheOpt")}</option></select></div>
      <div><label>&nbsp;</label><label><input type="checkbox" name="compress" style="width:auto" checked> ${t("aws.cfCompress")}</label></div></div>
      <label>${t("inst.desc")}</label><input name="comment"><p class="muted">${t("aws.cfNewNote")}</p>`,
      (bg) => post(`/accounts/${acc.id}/cloudfront`, { op: "create", ...form(bg) }), t("oci.create"));
    if (r) { toast(t("aws.cfCreated", { domain: r.domain })); reload(); }
  };
  let list;
  try { list = await api(`/accounts/${acc.id}/cloudfront`); } catch (e) { $("#t", box).textContent = "❌ " + e.message; return; }
  $("#t", box).innerHTML = list.length ? `<table><tr><th>${t("aws.cfColId")}</th><th>${t("aws.cfOriginCol")}</th><th>${t("common.status")}</th><th>${t("aws.cfColPlan")}</th><th>${t("inst.colOps")}</th></tr>
    ${list.map((d) => `<tr><td><b>${esc(d.id)}</b><br><code>${esc(d.domain)}</code>${d.aliases.length ? "<br>" + d.aliases.map(esc).join(", ") : ""}
    <div class="muted">${esc(d.comment)}</div></td><td class="mono">${d.origins.map(esc).join("<br>")}</td>
    <td><span class="badge ${esc(d.status)}">${esc(d.status)}</span><br>${d.enabled ? t("aws.cfOn") : t("aws.cfOff")}</td>
    <td>${d.plan == null ? t("aws.cfUnknown") : esc(cfPlanLabel(d.plan))}<div class="muted">${esc(d.price_class || "-")}</div></td>
    <td><button class="btn sm" data-cf="inv" data-id="${esc(d.id)}">${t("aws.cfInv")}</button> <button class="btn sm" data-cf="edit" data-id="${esc(d.id)}">${t("common.edit")}</button>
    <button class="btn sm" data-cf="toggle" data-id="${esc(d.id)}">${d.enabled ? t("aws.cfDisable") : t("aws.cfEnable")}</button> <button class="btn sm" data-cf="plan" data-id="${esc(d.id)}">${t("aws.cfPlan")}</button>
    <button class="btn sm danger" data-cf="delete" data-id="${esc(d.id)}">${t("common.delete")}</button></td></tr>`).join("")}</table>` : `<div class="empty">${t("aws.cfNone")}</div>`;
  box.querySelectorAll("[data-cf]").forEach((b) => (b.onclick = () => cfOp(acc, list.find((x) => x.id === b.dataset.id), b.dataset.cf, b, reload)));
}
export async function cfOp(acc, d, op, btn, reload) {
  const base = `/accounts/${acc.id}/cloudfront`;
  if (op === "inv") {
    const r = await modal(t("aws.cfInvTitle", { id: d.id }), `<label>${t("aws.cfPaths")}</label><textarea name="paths" placeholder="/*&#10;/index.html&#10;/static/*"></textarea>
      <p class="muted">${t("aws.cfInvNote")}</p>`, (bg) => post(`${base}/invalidate`, { distribution_id: d.id, paths: form(bg).paths }), t("aws.cfInvGo"));
    if (r) toast(t("aws.cfInvDone", { id: r.invalidation_id, paths: r.paths.join(", ") }));
  } else if (op === "edit") {
    let c;
    try { c = await api(`${base}/${encodeURIComponent(d.id)}/config`); } catch (e) { return toast(e.message, true); }
    const r = await modal(t("aws.cfEditTitle", { id: d.id }), `<label>${t("inst.desc")}</label><input name="comment" value="${esc(c.comment)}">
      <label>${t("aws.cfOrigin")}</label><input name="origin_domain" value="${esc(c.origin_domain)}">
      <div class="row2"><div><label>${t("aws.cfProto")}</label><select name="origin_protocol">${["http-only", "https-only", "match-viewer"].map((x) => `<option ${x === c.origin_protocol ? "selected" : ""}>${x}</option>`).join("")}</select></div>
      <div><label>${t("aws.cfPrice")}</label><select name="price_class">${["100", "200", "All"].map((x) => `<option ${x === c.price_class ? "selected" : ""}>${x}</option>`).join("")}</select></div></div>
      <label>${t("aws.cfRoot")}</label><input name="default_root_object" value="${esc(c.default_root_object)}" placeholder="index.html">
      <p class="muted">${t("aws.cfEditNote")}</p>`, (bg) => {
      const f = form(bg);
      if (!c.origin_protocol) delete f.origin_protocol;
      return api(`${base}/${encodeURIComponent(d.id)}`, { method: "PUT", body: f });
    }, t("common.save"));
    if (r) { toast(r.message); reload(); }
  } else if (op === "toggle") {
    if (!(await confirmBox(d.enabled ? t("aws.cfDisableTitle") : t("aws.cfEnableTitle"), d.enabled ? t("aws.cfDisableMsg", { domain: esc(d.domain) }) : t("aws.cfEnableMsg", { id: esc(d.id) }), d.enabled))) return;
    if (await act(btn, () => post(`${base}/toggle`, { distribution_id: d.id, enabled: !d.enabled }), (x) => x.message)) setTimeout(reload, 1500);
  } else if (op === "plan") {
    const cur = d.plan || "PAYGO";
    const tier = await modal(t("aws.cfPlanTitle", { id: d.id }), `<p class="muted">${t("aws.cfPlanBody", { cur: d.plan == null ? t("aws.cfPlanUnknown") : esc(cfPlanLabel(cur)) })}</p>
      ${Object.entries(CF_PLAN).map(([k, l]) => `<label class="chip" style="display:flex"><input type="radio" name="tier" value="${k}" style="width:auto" ${k === cur ? "checked" : ""}> ${t(l)}</label>`).join("")}`,
      (bg) => { const v = bg.querySelector("input[name=tier]:checked"); return v ? v.value : false; }, t("inst.next"));
    if (!tier || tier === cur) return tier === cur && toast(t("aws.cfSamePlan"));
    const paid = ["PRO", "BUSINESS", "PREMIUM"].includes(tier);
    if (paid && !(await confirmBox(t("aws.cfPaidTitle"), t("aws.cfPaidMsg", { id: esc(d.id), plan: esc(t(CF_PLAN[tier])) }), true))) return;
    if (await act(btn, () => post(`${base}/plan`, { distribution_id: d.id, plan_tier: tier, confirm: paid }), (x) => x.message)) reload();
  } else if (op === "delete") {
    const msg = d.enabled || d.status !== "Deployed"
      ? t("aws.cfDelMsg1", { id: esc(d.id), domain: esc(d.domain), state: d.enabled ? t("aws.cfStateOn") : t("aws.cfStateDep") })
      : t("aws.cfDelMsg2", { id: esc(d.id), domain: esc(d.domain) });
    if (!(await confirmBox(t("aws.cfDelTitle"), msg, true))) return;
    const r = await act(btn, () => del(`${base}/${encodeURIComponent(d.id)}?confirm=true`));
    if (r) { toast(r.deleted ? t("common.deleted") : t("aws.cfDelTask", { id: r.task_id })); reload(); }
  }
}

// ---------- 19. Lightsail 静态 IP（Lightsail 标签页下方） ----------
export async function tabLightsailV16(acc, box) {
  await tabInstances(acc, box, "lightsail");
  const card = document.createElement("div");
  card.className = "card"; card.id = "lsips";
  card.innerHTML = `<h3>${t("aws.lsIpTitle")}</h3><span class="spin"></span>`;
  box.appendChild(card);
  const reload = () => { card.remove(); tabLightsailV16(acc, box); };
  let ips, insts = [];
  try { [ips, insts] = await Promise.all([api(`/accounts/${acc.id}/lightsail/static-ips?${rq(acc)}`), api(`/accounts/${acc.id}/instances?kind=lightsail&${rq(acc)}`).catch(() => [])]); }
  catch (e) { card.innerHTML = `<h3>${t("aws.lsIpTitle")}</h3>❌ ${esc(e.message)}`; return; }
  const opts = insts.map((i) => `<option>${esc(i.name)}</option>`).join("");
  card.innerHTML = `<h3>${t("aws.lsIpTitle")} <button class="btn sm" id="lsAlloc">${t("aws.lsAlloc")}</button></h3><table><tr><th>${t("acc.colName")}</th><th>IP</th><th>${t("aws.lsBoundTo")}</th><th></th></tr>
    ${ips.map((s) => `<tr><td>${esc(s.name)}</td><td class="mono">${esc(s.ip)}</td><td>${s.attached ? esc(s.attached_to) : `<span class="badge running">${t("aws.lsUnbound")}</span>`}</td>
      <td>${s.attached ? `<button class="btn sm" data-lsdet="${esc(s.name)}">${t("inst.unbind")}</button>` : `<button class="btn sm" data-lsatt="${esc(s.name)}">${t("aws.lsBind")}</button> <button class="btn sm danger" data-lsrel="${esc(s.name)}">${t("aws.lsRelease")}</button>`}</td></tr>`).join("") || `<tr><td colspan=4 class="muted">${t("aws.lsNone")}</td></tr>`}</table>
    <p class="muted">${t("aws.lsNote")}</p>`;
  const op = (b, body, msg) => act(b, () => post(`/accounts/${acc.id}/lightsail/static-ips`, { region: regionOf(acc), ...body }), msg).then((r) => { if (r) { if (r.hint) toast(r.hint); reload(); } });
  card.querySelector("#lsAlloc").onclick = async () => {
    const r = await modal(t("aws.lsAllocTitle"), `<label>${t("acc.colName")}</label><input name="name" placeholder="ip-1"><label>${t("aws.lsBindNow")}</label><select name="instance"><option value="">${t("aws.lsNoBind")}</option>${opts}</select>`,
      (bg) => post(`/accounts/${acc.id}/lightsail/static-ips`, { op: "allocate", region: regionOf(acc), ...form(bg) }), t("aws.lsAllocGo"));
    if (r) { toast(t("aws.lsAllocated", { ip: r.ip })); reload(); }
  };
  card.querySelectorAll("[data-lsatt]").forEach((b) => (b.onclick = async () => {
    const r = await modal(t("aws.lsBindTitle"), `<label>${t("oci.colInst")}</label><select name="instance">${opts}</select><p class="muted">${t("aws.lsBindNote")}</p>`,
      (bg) => post(`/accounts/${acc.id}/lightsail/static-ips`, { op: "attach", region: regionOf(acc), name: b.dataset.lsatt, ...form(bg) }), t("aws.lsBind"));
    if (r) { toast(t("inst.bound")); reload(); }
  }));
  card.querySelectorAll("[data-lsdet]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("aws.lsDetTitle"), t("aws.lsDetConfirm"), true)) op(b, { op: "detach", name: b.dataset.lsdet }); }));
  card.querySelectorAll("[data-lsrel]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("aws.lsRelTitle"), t("aws.lsRelConfirm"), true)) op(b, { op: "release", name: b.dataset.lsrel }, t("aws.lsReleased")); }));
}

// ---------------- build 20：新号 Credit（AWS 新免费计划 Free Tier credit + 5 个活动一键完成） ----------------
const CR_BADGE = { COMPLETED: "done", IN_PROGRESS: "pending", EXPIRING: "interrupted", NOT_STARTED: "" };
const CR_STEP = { executed: "aws.crsExecuted", failed: "aws.crsFailed", stopped: "aws.crsStopped", skipped: "aws.crsSkipped", running: "aws.crsRunning", pending: "aws.crsPending" };
export const crMoney = (v, u) => (v == null || v === "" ? "-" : `${u && u !== "USD" ? u + " " : "$"}${(+v).toFixed(2).replace(/\.00$/, "")}`);
export const crDate = (s) => (s ? String(s).replace("T", " ").slice(0, 16) : "-");
function crLastRun(a) {
  const l = a.last_run;
  if (!l) return "";
  const cls = l.status === "executed" ? "ok" : l.status === "failed" ? "bad" : "";
  return `<div class="muted cr-last ${cls}">${t("aws.crLastRun", { id: l.task_id, step: esc(CR_STEP[l.status] ? t(CR_STEP[l.status]) : l.status), extra: l.status === "failed" && l.message ? (getLang() === "en" ? ": " : "：") + esc(l.message) : "" })}</div>`;
}
export async function tabAwsCredit(acc, box, refresh = false) {
  const reload = (rf) => tabAwsCredit(acc, box, rf);
  box.innerHTML = `<div class="card"><span class="spin"></span> ${t("aws.crLoading")}</div>`;
  let d;
  try { d = await api(`/accounts/${acc.id}/aws/credits${refresh ? "?refresh=true" : ""}`); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  if (!box.isConnected) return;
  const p = d.plan || {}, rt = d.running_task;
  const head = d.state === "ok" ? `<div class="grid" id="crPlan">
      <div class="card"><h3>${t("aws.crRemain")}</h3><div class="big">${crMoney(p.remaining, p.unit)}</div><div class="muted">${t("aws.crPlanMeta", { type: esc(p.type || "-"), status: esc(p.status || "-") })}</div></div>
      <div class="card"><h3>${t("aws.crExpires")}</h3><div class="big" style="font-size:20px">${esc(crDate(p.expires))}</div><div class="muted">${t("aws.crExpiresNote")}</div></div></div>`
    : `<div class="card al warn" id="crState">⚠️ ${esc(d.message || t("aws.crUnreadable"))}${d.permissions ? `<div class="muted">${t("aws.crPerms", { list: d.permissions.map(esc).join(" / ") })}</div>` : ""}
      ${d.state === "not_applicable" ? `<div class="muted">${t("aws.crNaNote")}</div>` : ""}</div>`;
  const rows = d.activities.map((a) => `<tr data-k="${a.key}"><td><b>${esc(a.label)}</b>${a.title ? `<div class="muted">${esc(a.title)}</div>` : ""}
      <div class="muted cr-plan">${esc(a.plan)}</div>${a.note ? `<div class="al warn cr-note">ℹ️ ${esc(a.note)}</div>` : ""}${crLastRun(a)}</td>
      <td><span class="badge ${CR_BADGE[a.status] || ""}">${esc(a.status_text)}</span></td><td>${crMoney(a.reward, a.unit)}</td>
      <td>${a.completed_at ? esc(crDate(a.completed_at)) : a.started_at ? t("aws.crStartedAt", { t: esc(crDate(a.started_at)) }) : "-"}</td>
      <td>${a.runnable ? `<button class="btn sm primary" data-run="${a.key}" ${rt ? "disabled" : ""}>${t("aws.crRun")}</button>` : `<span class="muted">✅</span>`}</td></tr>`).join("");
  const extra = (d.extra_activities || []).length ? `<p class="muted">${t("aws.crExtra", { list: d.extra_activities.map((a) => `${esc(a.title)}（${esc(a.status_text)}）`).join("、") })}</p>` : "";
  box.innerHTML = `${head}
    <div class="card"><div class="bar"><h3 class="grow" style="margin:0">${t("aws.crTitle")}</h3>
      <span class="muted">${esc(d.updated_at || "")}${d.cached ? t("aws.crCached", { m: Math.round(d.age / 60) }) : ""}</span>
      <button class="btn sm" id="crRf">${t("common.refresh")}</button><button class="btn sm" id="crAll" ${rt || !d.pending.length ? "disabled" : ""}>${t("aws.crAll")}</button>
      <button class="btn sm danger" id="crClean" ${rt ? "disabled" : ""}>${t("aws.crClean")}</button></div>
      <div id="crRun"></div>
      <table id="crTable"><tr><th>${t("aws.colActivity")}</th><th>${t("common.status")}</th><th>${t("aws.colReward")}</th><th>${t("aws.colDoneAt")}</th><th></th></tr>${rows}</table>${extra}
      <ul class="muted" id="crNotes">${(d.notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>`;
  $("#crRf", box).onclick = () => reload(true);
  if (rt) crProgress(acc, box, rt);
  box.querySelectorAll("[data-run]").forEach((b) => (b.onclick = async () => {
    const a = d.activities.find((x) => x.key === b.dataset.run);
    const ok = await confirmBox(t("aws.crRunTitle", { label: a.label }), `${esc(a.plan)}<br><br>${a.note ? esc(a.note) + "<br><br>" : ""}${t("aws.crRunBody")}`);
    if (!ok) return;
    const r = await act(b, () => post(`/accounts/${acc.id}/aws/credits/activities/${a.key}/run`, { confirm: true }));
    if (r) { toast(r.message); reload(false); }
  }));
  $("#crAll", box).onclick = async () => {
    const names = d.activities.filter((a) => d.pending.includes(a.key)).map((a) => a.label).join("、");
    if (!(await confirmBox(t("aws.crAll"), t("aws.crAllMsg", { names: esc(names) })))) return;
    if (!(await confirmBox(t("aws.crCostTitle"), t("aws.crCostMsg"), true))) return;
    const r = await act($("#crAll", box), () => post(`/accounts/${acc.id}/aws/credits/run-all`, { confirm: true }));
    if (r) { toast(r.message + (r.skipped?.length ? (getLang() === "en" ? ": " : "：") + r.skipped.map((s) => s.reason).join(getLang() === "en" ? "; " : "；") : "")); reload(false); }
  };
  $("#crClean", box).onclick = async () => {
    const r0 = await modal(t("aws.crCleanTitle"), `<p>${t("aws.crCleanBody")}</p>
      <label><input type="checkbox" name="include_budget" style="width:auto"> ${t("aws.crCleanBudget")}</label>`,
      (bg) => post(`/accounts/${acc.id}/aws/credits/cleanup`, { confirm: true, ...form(bg) }), t("aws.crCleanGo"), true);
    if (!r0) return;
    const n = r0.deleted.length, e = r0.errors.length;
    toast(n ? t("aws.crCleaned", { n, list: r0.deleted.map((x) => x.id).join("、") }) + (e ? t("aws.crCleanFailPart", { e, errs: r0.errors.map((x) => x.error).join(getLang() === "en" ? "; " : "；") }) : "") : e ? t("aws.crCleanFail", { errs: r0.errors.map((x) => x.error).join(getLang() === "en" ? "; " : "；") }) : t("aws.crCleanNone"), e > 0);
  };
}
async function crProgress(acc, box, rt) {
  const el = $("#crRun", box);
  let after = 0, lines = [];
  const tick = async () => {
    if (!el.isConnected) return;
    let t;
    try { t = await api(`/tasks/${rt.id}?after=${after}`); } catch (_) { setTimeout(tick, 5000); return; }
    after = t.last_log_id || after;
    lines = lines.concat((t.logs || []).map((l) => l.msg)).slice(-8);
    const steps = (t.result && t.result.steps) || {};
    const keys = rt.activities || [];
    const done = keys.filter((k) => steps[k] && !["running", "pending"].includes(steps[k].status)).length;
    el.innerHTML = `<div class="al" id="crProg"><b>${tr("aws.crProg", { id: rt.id, done, total: keys.length, msg: esc(t.message || "") })}</b>
      <progress max="${keys.length || 1}" value="${done}" style="width:100%"></progress>
      <pre class="mono" style="white-space:pre-wrap;margin:4px 0 0;font-size:12px">${lines.map(esc).join("\n")}</pre>
      <a href="javascript:void 0" id="crTask">${tr("aws.crFullLog")}</a></div>`;
    $("#crTask", el).onclick = () => window.TaskDrawer && window.TaskDrawer.open(rt.id);
    if (t.status === "running") setTimeout(tick, 3000);
    else { toast(t.message || tr("aws.crTaskEnd"), t.status === "failed"); tabAwsCredit(acc, box, false); }
  };
  tick();
}
