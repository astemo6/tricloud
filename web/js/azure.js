// TriCloud 前端 v1.6.0 · Azure：创建 VM、资源组、配额、订阅、Foundry
import { t } from "./i18n.js";
import { $, ACCOUNTS, act, api, confirmBox, esc, form, modal, post, regionLabel, regionOpt, SETTINGS, toast } from "./core.js";
import { accountInfoDialog } from "./accounts.js";
import { loginFields } from "./instances.js";
import { saveDefaultBtn } from "./settings.js";

// Azure 创建 / 资源组 / 配额
export let AZ_LOC = {};
export async function azLocations(acc) {
  if (!AZ_LOC[acc.id]) AZ_LOC[acc.id] = await api(`/accounts/${acc.id}/azure/locations`);
  return AZ_LOC[acc.id];
}
export async function tabAzCreate(acc, box) {
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let locs = [];
  try { locs = await azLocations(acc); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const dz = SETTINGS.default_create?.azure || {};
  const last = localStorage.getItem("tc_azloc_" + acc.id) || dz.location || "eastasia";
  box.innerHTML = `<div class="card" id="f"><h3>${t("az.createTitle")}</h3><div class="row2">
    <div><label>${t("acc.colName")}</label><input name="name" value="vm-${Date.now().toString(36)}"></div>
    <div><label>${t("core.region.title")}</label><select name="location">${locs.map((l) => regionOpt(l, l === last)).join("")}</select></div>
    <div><label>${t("inst.size")}</label><input name="size" value="${esc(dz.size || "Standard_B1s")}" list="azs"><datalist id="azs">${["Standard_B1s", "Standard_B1ms", "Standard_B2ats_v2", "Standard_B2pts_v2", "Standard_B2s", "Standard_D2as_v5"].map((x) => `<option>${x}</option>`).join("")}</datalist></div>
    <div><label>${t("inst.os")}</label><select name="os">${["debian-12", "ubuntu-24.04", "ubuntu-22.04"].map((x) => `<option ${x === dz.os ? "selected" : ""}>${x}</option>`).join("")}</select></div>
    <div><label>${t("az.diskGb")}</label><input name="disk_gb" type="number" min="30" value="${esc(dz.disk_gb || 30)}"></div>
    <div><label>${t("inst.diskType")}</label><select name="disk_type"><option>StandardSSD_LRS</option><option>Standard_LRS</option><option>Premium_LRS</option></select></div>
    <div><label>${t("az.rgLabel")}</label><input name="resource_group"></div>
    <div><label>${t("az.ports")}</label><input name="ports" placeholder="80,443"></div></div>
    <label><input type="checkbox" name="ipv6" style="width:auto"> ${t("az.ipv6")}</label>
    <label>${t("oci.sshKey")}</label><textarea name="ssh_key">${esc(dz.ssh_key || "")}</textarea>
    ${await loginFields()}
    <p class="muted">${t("az.createNote")}</p>
    <div class="bar" style="margin-top:14px"><button class="btn primary" id="go">${t("oci.create")}</button>${saveDefaultBtn("azure")}</div></div>`;
  $("#go", box).onclick = (e) => {
    const f = form($("#f", box));
    localStorage.setItem("tc_azloc_" + acc.id, f.location);
    act(e.target, () => post(`/accounts/${acc.id}/azure/create`, f), (r) => t("az.createdTask", { id: r.task_id }));
  };
}
export async function tabAzRgs(acc, box) {
  const reload = () => tabAzRgs(acc, box);
  box.innerHTML = `<div class="bar"><button class="btn" id="rf">${t("common.refresh")}</button><button class="btn primary" id="new">${t("az.newRg")}</button></div><div class="card" id="t"><span class="spin"></span></div>`;
  $("#rf", box).onclick = reload;
  $("#new", box).onclick = async () => {
    const locs = await azLocations(acc).catch(() => []);
    const r = await modal(t("az.newRg"), `<label>${t("acc.colName")}</label><input name="name"><label>${t("core.region.title")}</label><select name="location">${locs.map((l) => `<option>${l}</option>`).join("")}</select>`,
      (bg) => post(`/accounts/${acc.id}/azure/rgs`, form(bg)), t("oci.create"));
    if (r) reload();
  };
  let list;
  try { list = await api(`/accounts/${acc.id}/azure/rgs`); } catch (e) { $("#t", box).textContent = "❌ " + e.message; return; }
  $("#t", box).innerHTML = `<table><tr><th>${t("acc.colName")}</th><th>${t("core.region.title")}</th><th>${t("common.status")}</th><th></th></tr>${list.map((g) => `<tr><td>${esc(g.name)}</td><td>${esc(g.location)}</td><td>${esc(g.state)}</td>
    <td><button class="btn sm danger" data-del="${esc(g.name)}">${t("common.delete")}</button></td></tr>`).join("") || `<tr><td colspan=4 class="muted">${t("common.none")}</td></tr>`}</table>`;
  box.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    const r = await modal(t("az.delRg"), `<p>${t("az.delRgBody", { name: esc(b.dataset.del) })}</p><label>${t("az.delRgLabel")}</label><input name="confirm">`,
      (bg) => post(`/accounts/${acc.id}/azure/rgs`, { op: "delete", name: b.dataset.del, ...form(bg) }), t("common.delete"), true);
    if (r) { toast(t("az.delRgToast")); setTimeout(reload, 3000); }
  }));
}
export async function tabAzQuota(acc, box) {
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let locs = [];
  try { locs = await azLocations(acc); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const cur = localStorage.getItem("tc_azloc_" + acc.id) || "eastasia";
  box.innerHTML = `<div class="bar"><select id="loc">${locs.map((l) => `<option ${l === cur ? "selected" : ""}>${l}</option>`).join("")}</select></div><div class="card" id="q"><span class="spin"></span></div>`;
  const load = async () => {
    const loc = $("#loc", box).value; localStorage.setItem("tc_azloc_" + acc.id, loc);
    $("#q", box).innerHTML = `<span class="spin"></span>`;
    try {
      const r = await api(`/accounts/${acc.id}/azure/quotas?location=${encodeURIComponent(loc)}`);
      $("#q", box).innerHTML = `<table><tr><th>${t("oci.colItem")}</th><th>${t("oci.colUsed")}</th><th>${t("oci.colLimit")}</th></tr>${r.items.map((i) => `<tr><td>${esc(i.name)}</td><td>${i.used}</td><td>${i.limit}</td></tr>`).join("")}</table>`;
    } catch (e) { $("#q", box).textContent = "❌ " + e.message; }
  };
  $("#loc", box).onchange = load;
  load();
}

// ---------- Azure 订阅（只读） ----------
export async function tabAzSubscription(acc, box) {
  box.innerHTML = `<div class="card"><span class="spin"></span> ${t("az.subLoading")}</div>`;
  let s;
  try { s = await api(`/accounts/${acc.id}/azure/subscription`); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const stCls = { Enabled: "running", Warned: "pending", PastDue: "pending", Disabled: "failed", Deleted: "failed" }[s.state] || "";
  const edu = s.edu || {};
  box.innerHTML = `<div class="grid"><div class="card"><h3>${t("az.sub")}</h3>
    ${s.error ? `<p>❌ ${esc(s.error)}</p><p class="muted">${t("az.subPerm")}</p>` : `<div class="kv">
      <span>${t("acc.colName")}</span><span>${esc(s.display_name || "-")}</span><span>${t("az.subId")}</span><span class="mono">${esc(s.subscription_id || "-")}</span>
      <span>${t("common.status")}</span><span><span class="badge ${stCls}">${esc(s.state || "-")}</span></span>
      <span>${t("common.type")}</span><span>${esc(s.offer || "-")}${s.quota_id ? `<div class="muted mono">${esc(s.quota_id)}</div>` : ""}</span>
      <span>${t("az.spendLimit")}</span><span>${esc({ On: t("az.spendOn"), Off: t("common.close"), CurrentPeriodOff: t("az.spendCurOff") }[s.spending_limit] || s.spending_limit || "-")}</span>
      <span>${t("az.locPolicy")}</span><span class="mono">${esc(s.location_placement_id || "-")}</span>
      <span>${t("az.authSrc")}</span><span>${esc(s.authorization_source || "-")}</span><span>${t("az.tenant")}</span><span class="mono">${esc(s.tenant_id || "-")}</span></div>`}</div>
    <div class="card"><h3>${t("az.edu")}</h3><div class="big">${edu.expires_at ? esc(edu.expires_at) : "—"}</div>
      <div class="muted">${edu.expires_at ? `${edu.estimated ? t("az.eduEst") : ""}${edu.days_left >= 0 ? t("az.eduDays", { n: edu.days_left }) : t("common.expired")}` : ""}</div>
      <p class="muted">${esc(edu.basis || "")}${s.age_days != null ? t("az.ageDays", { n: s.age_days }) : ""}</p>
      <div class="bar"><button class="btn sm" id="ainfo">${t("az.setDates")}</button><a class="btn sm" href="#/azure/${acc.id}/billing">${t("az.creditBilling")}</a></div></div></div>
    <p class="muted">${t("az.subNote")}</p>`;
  $("#ainfo", box).onclick = () => accountInfoDialog(ACCOUNTS.find((a) => a.id === acc.id) || acc);
}

// ---------- Azure Foundry（AI Services）：配额、AI 资源与模型部署、Endpoint / Key ----------
export const FOUNDRY_REGION = {};
export async function tabAzFoundry(acc, box) {
  const region = FOUNDRY_REGION[acc.id] || "swedencentral";
  const reload = () => tabAzFoundry(acc, box);
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let d;
  try { d = await api(`/accounts/${acc.id}/azure/foundry?region=${encodeURIComponent(region)}`); }
  catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}<p class="muted">${t("az.fPerm")}</p></div>`; return; }
  const res = d.resources || [], models = d.models || [];
  const regs = (d.regions || [region]).map((r) => regionOpt(r, r === region)).join("");
  const resHtml = res.length ? res.map((r) => `<div class="card"><h3>${esc(r.name)} <span class="badge">${esc(r.kind)}</span> <span class="muted">${esc(regionLabel(r.region))} · ${esc(r.resource_group)} · ${esc(r.state || "")}</span></h3>
      <p class="mono" style="word-break:break-all">${esc(r.endpoint || "-")}</p>
      <div class="acts" style="justify-content:flex-start;flex-wrap:wrap"><button class="btn sm" data-key="${esc(r.id)}">${t("az.fViewKey")}</button>
        <button class="btn sm primary" data-dep="${esc(r.id)}" data-reg="${esc(r.region)}">${t("az.fDeploy")}</button>
        <button class="btn sm danger" data-delr="${esc(r.id)}" data-n="${esc(r.name)}">${t("az.fDelRes")}</button></div>
      ${r.deployments.length ? `<table><tr><th>${t("az.fDepName")}</th><th>${t("az.fModel")}</th><th>${t("common.type")}</th><th>${t("az.fCapacity")}</th><th>${t("common.status")}</th><th></th></tr>${r.deployments.map((x) => `<tr><td class="mono">${esc(x.name)}</td>
        <td>${esc(x.model || "-")} <span class="muted">${esc(x.version || "")}</span></td><td>${esc(x.sku || "-")}</td><td>${x.capacity != null ? esc(x.capacity) + "K TPM" : "-"}</td><td>${esc(x.state || "-")}</td>
        <td><button class="btn sm danger" data-deld="${esc(x.name)}" data-rid="${esc(r.id)}">${t("common.delete")}</button></td></tr>`).join("")}</table>` : `<p class="muted">${t("az.fNoDep")}</p>`}</div>`).join("")
    : `<div class="card"><p class="muted">${t("az.fNone")}</p></div>`;
  const q = d.quotas || [];
  box.innerHTML = `<div class="card"><h3>Foundry（Azure AI）</h3>
      <p class="muted">${t("az.fIntro")}</p>
      <div class="acts" style="justify-content:flex-start;flex-wrap:wrap"><label style="margin:0">${t("core.region.title")}</label><select id="fdReg" style="width:auto">${regs}</select>
        <button class="btn primary" id="fdNew">${t("az.fNew")}</button></div></div>
    ${resHtml}
    <div class="card"><h3>${t("az.fQuota", { region: esc(regionLabel(region)) })}</h3>${q.length ? `<table><tr><th>${t("az.fQuotaItem")}</th><th>${t("az.fUsedLimit")}</th></tr>${q.map((x) => `<tr><td>${esc(x.name)}</td><td>${esc(x.used)} / ${esc(x.limit)}</td></tr>`).join("")}</table>`
      : `<p class="muted">${t("az.fNoQuota")}</p>`}</div>`;
  $("#fdReg", box).onchange = (e) => { FOUNDRY_REGION[acc.id] = e.target.value; reload(); };
  const modelOpts = (list) => list.length ? list.map((m) => `<option value="${esc(m.name)}|${esc(m.version)}" data-skus="${esc(m.skus.join(","))}">${esc(m.name)} ${esc(m.version)}${m.default ? t("az.fDefault") : ""}</option>`).join("")
    : ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini", "text-embedding-3-small"].map((n) => `<option value="${n}|">${n}</option>`).join("");
  const depForm = async (rid, reg) => {
    let list = models;
    if (reg !== region) { try { list = (await api(`/accounts/${acc.id}/azure/foundry?region=${encodeURIComponent(reg)}&part=models`)).models || []; } catch (_) { list = []; } }
    const newRes = !rid;
    const v = await modal(newRes ? t("az.fNewTitle") : t("az.fDepTitle"), `${newRes ? `<label>${t("az.fResName")}</label><input name="name" placeholder="${t("az.fResNamePh")}">
        <label>${t("az.fRg")}</label><input name="resource_group" placeholder="${t("az.fOptional")}">
        <p class="muted">${t("az.fRegionLine", { reg: esc(reg) })}</p>` : ""}
      <label>${t("az.fModel")}</label><select name="model">${modelOpts(list)}</select>
      <div class="row2"><div><label>${t("az.fSku")}</label><select name="sku"><option value="GlobalStandard">${t("az.fSkuGlobal")}</option><option value="Standard">${t("az.fSkuStd")}</option><option value="DataZoneStandard">DataZone Standard</option></select></div>
        <div><label>${t("az.fCapLabel")}</label><input name="capacity" type="number" min="1" max="1000" value="10"></div></div>
      <label>${t("az.fDepNameLabel")}</label><input name="deployment" placeholder="${t("az.fDepPh")}">
      <p class="muted">${t("az.fNote")}</p>`, (bg) => {
      const f = Object.fromEntries([...bg.querySelectorAll("[name]")].map((x) => [x.name, x.value.trim()]));
      if (newRes && !/^[a-zA-Z0-9][a-zA-Z0-9-]{1,62}$/.test(f.name)) { toast(t("az.fNameInvalid"), true); return false; }
      if (f.deployment && !/^[a-zA-Z0-9][a-zA-Z0-9-]{1,62}$/.test(f.deployment)) { toast(t("az.fDepInvalid"), true); return false; }
      return f;
    }, t("az.fGo"));
    if (!v) return;
    const [model, version] = v.model.split("|");
    const body = { op: "deploy", model, version: version || undefined, sku: v.sku, capacity: Number(v.capacity) || 10, deployment: v.deployment || undefined };
    if (rid) body.resource_id = rid; else Object.assign(body, { name: v.name, region: reg, resource_group: v.resource_group || undefined });
    const r = await act(null, () => post(`/accounts/${acc.id}/azure/foundry`, body), (x) => t("inst.taskCreatedAlt", { id: x.task_id }));
    if (r) setTimeout(reload, 1500);
  };
  $("#fdNew", box).onclick = () => depForm(null, region);
  box.querySelectorAll("[data-dep]").forEach((b) => (b.onclick = () => depForm(b.dataset.dep, b.dataset.reg)));
  box.querySelectorAll("[data-key]").forEach((b) => (b.onclick = async () => {
    if (!(await confirmBox(t("az.fKeyTitle"), t("az.fKeyConfirm"), false))) return;
    const k = await act(b, () => post(`/accounts/${acc.id}/azure/foundry`, { op: "keys", resource_id: b.dataset.key, confirm: true }));
    if (!k) return;
    modal("Endpoint / Key", `<label>Endpoint</label><input readonly class="mono" value="${esc(k.endpoint || "")}" onclick="this.select()">
      <label>Key 1</label><input readonly class="mono" id="fdK1" value="${esc(k.key1 || "")}" onclick="this.select()"> <button class="btn sm" id="fdCopy">${t("az.fCopyKey")}</button>
      <label>${t("az.fBaseUrl")}</label><input readonly class="mono" value="${esc(k.openai_base_url || "")}" onclick="this.select()">
      <p class="muted">${t("az.fSdkNote")}</p>`, null, t("common.close"));
    const c = document.getElementById("fdCopy");
    if (c) c.onclick = async () => { const ta = document.getElementById("fdK1"); try { await navigator.clipboard.writeText(ta.value); toast(t("guard.copied")); } catch (_) { ta.select(); document.execCommand("copy"); toast(t("guard.copied")); } };
  }));
  box.querySelectorAll("[data-deld]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox(t("az.fDelDep"), t("az.fDelDepMsg", { name: esc(b.dataset.deld) }), true)
      && await act(b, () => post(`/accounts/${acc.id}/azure/foundry`, { op: "delete_deployment", resource_id: b.dataset.rid, deployment: b.dataset.deld, confirm: true }), t("az.fDelDepOk"))) reload();
  }));
  box.querySelectorAll("[data-delr]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox(t("az.fDelResTitle"), t("az.fDelResMsg", { name: esc(b.dataset.n) }), true)
      && await act(b, () => post(`/accounts/${acc.id}/azure/foundry`, { op: "delete_resource", resource_id: b.dataset.delr, confirm: true }), (x) => x.hint || t("common.deleted"))) reload();
  }));
}
