// TriCloud 前端 v1.6.0 · 账号页框架与实例：列表 / 卡片 / 表格、实例操作、开放端口与安全组弹窗、迁移、流量守护弹窗、v1.6 实例弹窗（重装 / 附加 IP / IP 质量 / 500M / 磁盘 / Lightsail 防火墙）
import { agentLine, guardAgentDialog, guardPortsDialog } from "./guard.js";
import { $, ACCOUNTS, act, api, confirmBox, ensureLsRegion, ensureMachineRegion, esc, form, instView, isDesktop, lastModal, modal, NO_CHANGE_IP, NO_CREATE, NOREG, OP_NAMES, PNAME, post, regionLabel, regionOf, regionSelect, rq, TAB_FNS_EXTRA, TABS, toast, TRAFFIC_DIALOG, view } from "./core.js";
import { t } from "./i18n.js";
import { ociOsFields, ociShapeOpts, PUBLIC_CIDR, tabOciCreate, tabOciLimits, tabOciObjects, tabOciSecGroup, tabOciSnatch, tabOciStorage, tabOciTraffic, wireOciOs } from "./oci.js";
import { ec2Create, lightsailCreate, tabAwsCredit, tabAwsRegions, tabCloudFront, tabLightsailV16, tabQuota, tabRecycle } from "./aws.js";
import { tabAzCreate, tabAzFoundry, tabAzQuota, tabAzRgs, tabAzSubscription } from "./azure.js";
import { tabBilling } from "./billing.js";
import { bindDns } from "./settings.js";

// ---------------- 账号页 ----------------
// 标签栏横向滚动：切换标签重绘后，恢复原来的滚动位置，并保证选中的标签可见（手机上标签较多时会横向滚动）
export const TAB_SCROLL = {};
export function keepTabVisible(bar, key, prev) {
  if (!bar) return;
  bar.scrollLeft = prev;
  const on = bar.querySelector("a.on");
  if (on) {
    const l = on.offsetLeft - bar.offsetLeft, r = l + on.offsetWidth;
    if (l < bar.scrollLeft) bar.scrollLeft = Math.max(0, l - 24);
    else if (r > bar.scrollLeft + bar.clientWidth) bar.scrollLeft = r - bar.clientWidth + 24;
  }
  TAB_SCROLL[key] = bar.scrollLeft;
  bar.addEventListener("scroll", () => { TAB_SCROLL[key] = bar.scrollLeft; }, { passive: true });
}
// 不按区域显示的标签（与 App 顶部区域按钮的排除列表一致）
export const NO_REGION_TABS = ["cloudfront", "quota", "billing", "subscription", "regions", "credit"];
export async function pageAccount(acc, tab) {
  const tabs = `<div class="tabs">${TABS[acc.provider].map(([k, l]) =>
    `<a href="#/${acc.provider}/${acc.id}/${k}" class="${k === tab ? "on" : ""}">${t(l)}</a>`).join("")}</div>`;
  const prevScroll = TAB_SCROLL[acc.provider] || 0;
  view.innerHTML = tabs + `<div id="tab"></div>`;
  keepTabVisible(view.querySelector(".tabs"), acc.provider, prevScroll);
  const box = $("#tab");
  // build 25：默认选中有机器的区域 —— 还没有区域记录时先查一次总览（有缓存，最多等 8 秒）
  if (!NOREG(acc) && !NO_REGION_TABS.includes(tab) && !acc.machine_regions && !localStorage.getItem("tc_region_" + acc.id) && !acc.disabled) {
    box.innerHTML = `<div class="empty"><span class="spin"></span> ${t("inst.locating")}</div>`;
    await ensureMachineRegion(acc);
    if (!box.isConnected) return;
  }
  const fn = {
    instances: tabInstances, ec2: tabInstances, vms: tabInstances, lightsail: tabLightsailV16,
    storage: tabOciStorage, objects: (a, b) => tabOciObjects(a, b), traffic: tabOciTraffic,
    create: tabOciCreate, snatch: tabOciSnatch, cloudfront: tabCloudFront, quota: tabQuota, recycle: tabRecycle, billing: tabBilling,
    limits: tabOciLimits, regions: tabAwsRegions, azcreate: tabAzCreate, rgs: tabAzRgs, azquota: tabAzQuota,
    subscription: tabAzSubscription, secgroup: tabOciSecGroup, foundry: tabAzFoundry, credit: tabAwsCredit,
  }[tab] || TAB_FNS_EXTRA[tab];
  await fn(acc, box);
}

export function instOps(acc, kind) {
  const ops = [["start", t("op.start")], ["stop", acc.provider === "azure" ? t("op.stopRelease") : t("op.stop")], ["reboot", t("op.reboot")], ["changeip", t("op.changeip")]];
  if (acc.provider === "oci") ops.push(["ipv6", t("op.ipv6")], ["delipv6", t("op.delipv6")], ["resize", t("op.resize")], ["rename", t("op.rename")], ["bootvol", t("op.bootvol")],
    ["security", t("op.security")]);
  else if (kind !== "lightsail") ops.push(["rename", t("op.rename")]);   // v1.5：Azure / AWS EC2 也可改名（Lightsail 不支持改名）
  if (kind !== "lightsail") ops.push(["openport", t("op.openport")]);   // v1.5：三家云都有（来源 0.0.0.0/0，二次确认）
  if (acc.provider !== "oci") ops.push(["traffic", t("op.traffic")]);   // OCI 的流量守护统一在「流量」标签里管理
  if (acc.provider === "azure") ops.push(["resize", t("op.resizeAz")]);
  if (kind !== "lightsail") ops.push(["migrate", t("op.migrate")]);
  ops.push(["dns", t("op.dns")], ["monitor", t("op.monitor")], ["terminate", acc.provider === "azure" || kind === "lightsail" ? t("op.delete") : t("op.terminate")]);
  return v16Ops(acc, kind, ops);   // v1.6：附加 IP / 500M / 磁盘 / 防火墙 / IP 质量 / 重装系统
}
// v1.5：改名同步主机名 —— 只通过云厂商 Run Command 执行固定命令，不走 SSH
export const RENAME_HOSTNAME_TIP = "inst.renameTip";
export function renameResult(r) {
  const h = r && r.hostname;
  if (!h || h.status === "ok") return toast(h ? t("inst.renamedSynced") : t("inst.renamed"));
  if (h.status === "pending") return toast(t("inst.renamedMsg", { msg: h.message || t("inst.hostnameDispatched") }));
  if (!h.manual_cmd) return toast(t("inst.renamedNotSynced", { msg: h.message || "" }), h.status === "failed");
  modal(h.status === "failed" ? t("inst.renameFailTitle") : t("inst.renameManualTitle"),
    `<p>${esc(h.message || "")}</p><p class="muted">${t("inst.renameManualNote")}</p>
    <textarea id="hnCmd" readonly rows="4" class="mono" onclick="this.select()">${esc(h.manual_cmd)}</textarea>
    <button class="btn sm" id="hnCopy">${t("inst.copyCmd")}</button>`, null, t("common.understood"));
  const b = document.getElementById("hnCopy");
  if (b) b.onclick = async () => {
    const ta = document.getElementById("hnCmd");
    try { await navigator.clipboard.writeText(ta.value); toast(t("guard.copied")); } catch (_) { ta.select(); document.execCommand("copy"); toast(t("guard.copied")); }
  };
}
export function instCard(acc, i, kind) {
  const ip6 = (i.ipv6 || []).join("<br>") || "-";
  const extra = [];
  if (acc.provider === "oci") extra.push([t("inst.shape"), `${esc(i.shape)} ${i.ocpus ?? ""}C/${i.memory_gb ?? ""}G`]);
  else extra.push([t("inst.spec"), esc(i.shape)]);
  if (kind === "lightsail") extra.push([t("inst.blueprint"), esc(i.blueprint)], [t("inst.staticIp"), i.static_ip ? t("common.yes") : t("common.no")]);
  if (acc.provider === "azure") extra.push([t("inst.rg"), esc(i.resource_group)]);
  const ops = instOps(acc, kind);
  const inl = ops.filter(([o]) => INLINE_OPS.includes(o));
  const more = ops.length > inl.length;
  return `<div class="card inst" data-id="${esc(i.id)}"><div class="hd"><b title="${esc(i.id)}">${esc(i.name)}</b>
    <span class="badge ${esc(i.state)}">${esc(i.state)}</span></div>
    <div class="kv kv2"><span>${t("inst.public")}</span><span class="mono">${esc(i.public_ip || "-")}</span>
    <span>${t("inst.private")}</span><span class="mono">${esc(i.private_ip || "-")}</span>
    ${extra.map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join("")}
    <span>${t("inst.zone")}</span><span>${esc(i.zone ? regionLabel(i.zone) : "-")}</span>
    ${ip6 !== "-" ? `<span>IPv6</span><span class="mono wide">${ip6}</span>` : ""}</div>
    <div class="ops">${inl.map(([o, l]) => opBtn(o, l, i)).join("")}${more ? `<button class="btn sm" data-more aria-label="${t("inst.moreOps")}">${t("inst.more")} ▾</button>` : ""}</div></div>`;
}

export async function tabInstances(acc, box, kind = "vm") {
  const reload = () => tabInstances(acc, box, kind);
  if (kind === "lightsail") await ensureLsRegion(acc);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload, kind === "lightsail" ? "lightsail" : undefined)}<button class="btn" id="rf">${t("common.refresh")}</button>
    ${kind === "lightsail" ? `<button class="btn primary" id="lsNew">${t("inst.createLs")}</button>` : ""}
    ${acc.provider === "aws" && kind === "vm" ? `<button class="btn primary" id="ec2New">${t("inst.createEc2")}</button>` : ""}
    <span class="grow"></span><span class="muted" id="info"></span>
    <div class="seg desk-only" id="ivw" title="${t("inst.viewTitle")}"><button class="${instView() === "card" ? "on" : ""}" data-v="card">${t("inst.viewCard")}</button><button class="${instView() === "table" ? "on" : ""}" data-v="table">${t("inst.viewTable")}</button></div></div>
    <div class="grid" id="list"><div class="empty"><span class="spin"></span></div></div>`;
  $("#rf", box).onclick = reload;
  box.querySelectorAll("#ivw [data-v]").forEach((b) => (b.onclick = () => { localStorage.setItem("tc_inst_view", b.dataset.v); reload(); }));
  if (kind === "lightsail") $("#lsNew", box).onclick = () => lightsailCreate(acc, reload);
  if (acc.provider === "aws" && kind === "vm") $("#ec2New", box).onclick = () => ec2Create(acc, reload);
  let list;
  try { list = await api(`/accounts/${acc.id}/instances?kind=${kind}&${rq(acc)}`); }
  catch (e) { $("#list", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#info", box).textContent = t("inst.count", { n: list.length });
  const useTable = instView() === "table" && isDesktop() && list.length;
  const lb = $("#list", box);
  lb.className = useTable ? "card itable" : "grid";
  lb.innerHTML = !list.length ? `<div class="empty">${t("inst.emptyRegion")}</div>` : useTable ? instTable(acc, list, kind) : list.map((i) => instCard(acc, i, kind)).join("");
  box.querySelectorAll("[data-op]").forEach((b) => {
    const card = b.closest("[data-id]");
    const inst = list.find((x) => x.id === card.dataset.id);
    b.onclick = () => instOp(acc, inst, b.dataset.op, kind, b, reload);
  });
  box.querySelectorAll("[data-more]").forEach((b) => {
    const inst = list.find((x) => x.id === b.closest("[data-id]").dataset.id);
    b.onclick = (e) => { e.stopPropagation(); opsMenu(b, instOps(acc, kind).filter(([o]) => !INLINE_OPS.includes(o)), (op) => instOp(acc, inst, op, kind, b, reload)); };
  });
}

export async function instOp(acc, inst, op, kind, btn, reload) {
  const base = { instance_id: inst.id, region: regionOf(acc) || undefined, kind, name: inst.name };
  const names = OP_NAMES[acc.provider] || { start: t("op.start"), stop: t("op.stop"), reboot: t("op.reboot"), terminate: t("op.terminate") };
  if (V16_OPS[op]) return V16_OPS[op](acc, inst, base, kind, btn, reload);
  if (names[op]) {
    const danger = op === "terminate";
    const msg = danger ? t("inst.termConfirm", { verb: acc.provider === "azure" || kind === "lightsail" ? t("op.delete") : t("op.terminate"), name: esc(inst.name) })
      : t("inst.opConfirm", { op: names[op], name: esc(inst.name) }) + (op === "stop" && acc.provider === "azure" ? `<br><span class='muted'>${t("inst.azureStopNote")}</span>` : "");
    const keep = danger && acc.provider === "oci";
    const ok = await modal(names[op], `<p>${msg}</p>${keep ? `<label><input type="checkbox" name="preserve_boot_volume" style="width:auto"> ${t("inst.preserveBoot")}</label>` : ""}`,
      (bg) => form(bg), t("common.confirm"), danger);
    if (!ok) return;
    await act(btn, () => post(`/accounts/${acc.id}/instances/action`, { ...base, action: op, confirm: danger, preserve_boot_volume: !!ok.preserve_boot_volume }), t("inst.cmdSent", { op: names[op] }));
    setTimeout(reload, 2500);
  } else if (op === "changeip") {
    let body = `<p>${t("inst.chipBody", { name: esc(inst.name), ip: esc(inst.public_ip || "-") })}</p>`;
    if (acc.provider === "aws" && kind === "vm") body += `<label>${t("inst.chipMode")}</label><select name="mode"><option value="auto">${t("inst.chipModeAuto")}</option>
      <option value="eip">${t("inst.chipModeEip")}</option><option value="stopstart">${t("inst.chipModeStop")}</option></select>`;
    if (acc.provider === "azure") body += `<p class="muted">${t("inst.chipAzureNote")}</p>`;
    if (kind === "lightsail") body += `<p class="muted">${t("inst.chipLsNote")}</p>`;
    const oci = acc.provider === "oci";
    body += `<label>${t("inst.chipCidrs")}</label>
      <input name="cidrs" placeholder="${oci ? t("inst.chipCidrPhOci") : t("inst.chipCidrPh")}">
      <label>${oci ? t("inst.chipTriesOci") : t("inst.chipTriesOther")}</label><input name="max_tries" type="number" min="1" max="${oci ? 100 : 20}" value="${oci ? 20 : 5}">` + qualityFields();
    try { const u = await api(`/accounts/${acc.id}/ip-change-usage`); body += `<p class="muted">${t("inst.chipUsage", { m: u.manual_used, a: u.auto_used, limit: u.limit })}</p>`; } catch (_) { /* ignore */ }
    body += `<p class="muted">${t("inst.chipDnsNote")}</p>`;
    const r = await modal(t("inst.changeIpTitle"), body, (bg) => post(`/accounts/${acc.id}/instances/change-ip`, { ...base, ...form(bg) }), t("inst.changeIpGo"));
    if (r) {
      if (r.task_id) toast(t("inst.taskCreated", { id: r.task_id }));
      else toast(t("inst.newIp", { ip: r.new_ip }));
      setTimeout(reload, 1500);
    }
  } else if (op === "migrate") {
    migrateDialog(acc, inst);
  } else if (op === "ipv6") {
    if (!(await confirmBox(t("inst.ipv6Title"), t("inst.ipv6Confirm")))) return;
    await act(btn, () => post(`/accounts/${acc.id}/oci/ipv6`, base), (r) => t("inst.taskCreatedAlt", { id: r.task_id }));
  } else if (op === "delipv6") {
    if (!(await confirmBox(t("inst.delIpv6Title"), t("inst.delIpv6Confirm", { name: esc(inst.name) }), true))) return;
    if (await act(btn, () => post(`/accounts/${acc.id}/oci/ipv6/delete`, { ...base, confirm: true }), (r) => t("inst.deletedList", { list: r.deleted.join(", ") }))) setTimeout(reload, 1500);
  } else if (op === "rename") {
    const r = await modal(t("inst.renameTitle"), `<input name="new_name" value="${esc(inst.name)}">
      <label><input type="checkbox" name="sync_hostname" style="width:auto" checked> ${t("inst.syncHostname")}</label>
      <p class="muted">${t(RENAME_HOSTNAME_TIP)}</p>`, (bg) => post(`/accounts/${acc.id}/instances/rename`, { ...base, ...form(bg) }), t("common.save"));
    if (r) { renameResult(r); reload(); }
  } else if (op === "bootvol") {
    let bv;
    try { toast(t("inst.readingBoot")); bv = await api(`/accounts/${acc.id}/oci/boot-volume?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
    const r = await modal(t("op.bootvol"), `<div class="kv"><span>${t("acc.colName")}</span><span>${esc(bv.name)}</span><span>${t("inst.size")}</span><span>${bv.size_gb} GB</span>
      <span>${t("inst.perf")}</span><span>${bv.vpus_per_gb} VPU/GB</span><span>${t("common.status")}</span><span>${esc(bv.state)}</span></div>
      <div class="row2"><div><label>${t("inst.growTo")}</label><input name="size_gb" type="number" min="${bv.size_gb}" placeholder="${bv.size_gb}"></div>
      <div><label>${t("inst.vpuLabel")}</label><select name="vpus_per_gb">${[10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120].map((v) => `<option ${v === bv.vpus_per_gb ? "selected" : ""}>${v}</option>`).join("")}</select></div></div>
      <label><input type="checkbox" name="grow" style="width:auto" checked> ${t("inst.growRoot")}</label>
      <p class="muted">${t("inst.vpuNote")}</p>`,
      (bg) => post(`/accounts/${acc.id}/oci/boot-volume`, { ...base, ...form(bg) }), t("inst.submit"));
    if (r) toast(r.grow ? t("inst.grownOk", { s: r.grow.status === "ok" ? t("task.st.done") : r.grow.message }) : (r.hint || t("inst.submitted")));
  } else if (op === "openport") {
    openPortDialog(acc, inst, base, btn);
  } else if (op === "security") {
    openSecurity(acc, inst, base);
  } else if (op === "traffic") {
    trafficDialog(acc, inst, kind);
  } else if (op === "dns") {
    bindDns(acc, inst);
  } else if (op === "resize") {
    if (acc.provider === "oci") {
      const r = await modal(t("op.resize"), `<p class="muted">${t("inst.resizeNote")}</p><div class="row2">
        <div><label>OCPU</label><input name="ocpus" type="number" step="1" min="1" value="${inst.ocpus || 1}"></div>
        <div><label>${t("inst.memLabel")}</label><input name="memory_gb" type="number" min="1" value="${inst.memory_gb || 6}"></div></div>`,
        (bg) => post(`/accounts/${acc.id}/instances/resize`, { ...base, ...form(bg) }), t("inst.submit"));
      if (r) toast(t("inst.taskCreatedShort", { id: r.task_id }));
    } else {
      let sizes = [];
      try { sizes = await api(`/accounts/${acc.id}/azure/sizes?instance_id=${encodeURIComponent(inst.id)}`); } catch (e) { return toast(e.message, true); }
      const r = await modal(t("inst.azResizeTitle"), `<p class="muted">${t("inst.azResizeNote", { shape: esc(inst.shape) })}</p><label>${t("inst.azResizeLabel")}</label><select name="size">
        ${sizes.map((s) => `<option value="${esc(s.name)}" ${s.name === inst.shape ? "selected" : ""}>${esc(s.name)} · ${s.cores}C/${(s.memory_mb / 1024).toFixed(1)}G</option>`).join("")}</select>`,
        (bg) => post(`/accounts/${acc.id}/instances/resize`, { ...base, ...form(bg) }), t("inst.submit"));
      if (r) toast(t("inst.taskCreatedShort", { id: r.task_id }));
    }
  } else if (op === "monitor") {
    const r = await modal(t("inst.monTitle"), `<p>${t("inst.monBody", { name: esc(inst.name) })}</p>
      <label><input type="checkbox" name="auto_start" style="width:auto"> ${t("inst.monAutoStart")}</label>
      <label>${t("inst.monPort")}</label><input name="check_port" type="number" min="0" max="65535" value="0">
      ${NO_CHANGE_IP.has(acc.provider) ? `<p class="muted">${t("inst.monNoIp")}</p>` : `<label><input type="checkbox" name="auto_change_ip" style="width:auto"> ${t("inst.monAutoIp")}</label>`}
      <p class="muted">${t("inst.monNote")}</p>`,
      (bg) => post(`/monitors`, { account_id: acc.id, instance_id: inst.id, region: regionOf(acc) || null, kind, name: inst.name, state: inst.state, public_ip: inst.public_ip, ...form(bg) }), t("common.save"));
    if (r) toast(t("inst.monAdded"));
  }
}

// ================= v1.1 新增 =================
// 登录方式 + 开机脚本（创建表单通用）
export async function loginFields() {
  let scripts = [];
  try { scripts = await api("/scripts"); } catch (_) { /* ignore */ }
  return `<label><input type="checkbox" name="password_login" style="width:auto" checked> ${t("inst.loginPw")}</label>
    <label>${t("inst.bootScript")}</label><select name="script_id"><option value="">${t("inst.noTemplate")}</option>${scripts.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select>
    <textarea name="script" placeholder="${t("inst.scriptPh")}"></textarea>
`;
}
export async function showCreated(r) {
  if (!r) return;
  const pw = r.password ? `<label>${t("inst.username")}</label><code>${esc(r.username)}</code><label>${t("inst.pwOnce")}</label>
    <input value="${esc(r.password)}" readonly onclick="this.select()">` : `<p class="muted">${t("inst.noPw")}</p>`;
  await modal(t("inst.createdTitle"), `<p>${esc(r.name || "")} · ${esc(r.state || "")}${r.public_ip ? " · " + esc(r.public_ip) : ""}</p>${pw}`, null, t("inst.savedIt"));
}

// v1.5 公网放行警告（实例「开放端口」/ 安全列表 / 安全组页共用）
export const publicWarn = (cidr, what, okText) => modal(t("inst.pubTitle"), `<p>${t("inst.pubBody", { cidr: esc(cidr), what })}</p>
  <ul class="guard"><li>${t("inst.pubLi1")}</li><li>${t("inst.pubLi2")}</li></ul>`, null, okText || t("inst.pubOk"), true);
export const OPEN_PORT_WHERE = { oci: "inst.whereOci", aws: "inst.whereAws", azure: "inst.whereAz" };
// v1.5 实例操作「开放端口」：POST /instances/{id}/open-port，来源固定 0.0.0.0/0；先填端口，再弹公网警告二次确认
export async function openPortDialog(acc, inst, base, btn) {
  const v = await modal(t("op.openport"), `<p>${t("inst.openPortBody", { name: esc(inst.name), where: t(OPEN_PORT_WHERE[acc.provider] || "inst.whereDefault") })}</p>
    <div class="row2"><div><label>${t("inst.portLabel")}</label><input name="port" placeholder="${t("inst.portPh")}"></div>
    <div><label>${t("inst.protocol")}</label><select name="protocol"><option value="tcp">TCP</option><option value="udp">UDP</option></select></div></div>
    <p class="muted">${t("inst.openPortNote")}</p>`, (f) => {
    const x = form(f);
    if (!x.port) throw new Error(t("inst.portRequired"));
    return x;
  }, t("inst.next"));
  if (!v) return;
  if (!(await publicWarn("0.0.0.0/0", `${v.protocol.toUpperCase()} ${t("inst.portWord")} <code>${esc(v.port)}</code>`, t("inst.pubConfirm")))) return;
  const r = await act(btn, () => post(`/accounts/${acc.id}/instances/${encodeURIComponent(inst.id)}/open-port`,
    { port: v.port, protocol: v.protocol, region: base.region, kind: base.kind, confirm_public: true }));
  if (r) {
    toast(t("inst.openedToast", { a: r.added, skip: r.skipped ? t("inst.skippedPart", { n: r.skipped }) : "" }));
    modal(t("inst.openPortResult"), `<ul>${(r.groups || []).map((g) => `<li>${t("inst.openPortGroup", { kind: esc(g.kind), name: esc(g.name), a: g.added, s: g.skipped })}</li>`).join("")}</ul>`, null, t("common.good"));
  }
}
// v1.5「添加规则」端口输入：单端口（起始 / 结束）或批量（仿线上版 openSecRuleModal）
export const portModeFields = () => `<div data-show-when="protocol=tcp|udp"><label>${t("inst.portMode")}</label><select name="port_mode">
  <option value="single">${t("inst.portModeSingle")}</option><option value="batch">${t("inst.portModeBatch")}</option></select>
  <div class="row2" data-show-when="port_mode=single"><div><label>${t("inst.portMin")}</label><input name="port_min" type="number" min="1" max="65535" placeholder="${t("inst.ph80")}"></div>
  <div><label>${t("inst.portMax")}</label><input name="port_max" type="number" min="1" max="65535" placeholder="${t("inst.ph80")}"></div></div>
  <div data-show-when="port_mode=batch"><label>${t("inst.portsLabel")}</label><textarea name="ports" placeholder="80&#10;443&#10;8000-8100"></textarea>
  <p class="muted">${t("inst.portsNote")}</p></div></div>`;
// 把弹窗的端口字段统一成 ports 字符串；返回 "" 表示未填
export function portsOf(v) {
  if (!["tcp", "udp"].includes(v.protocol)) return "";
  if (v.port_mode === "batch") return String(v.ports || "").trim();
  if (!v.port_min) return "";
  const a = +v.port_min, b = +(v.port_max || v.port_min);
  return a === b ? String(a) : `${a}-${b}`;
}

// OCI 安全列表
export async function openSecurity(acc, inst, base) {
  let lists;
  try { toast(t("inst.readingSec")); lists = await api(`/accounts/${acc.id}/oci/security?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  const body = lists.map((l) => `<h4>${esc(l.name)}</h4><table><tr><th>${t("inst.direction")}</th><th>${t("inst.protocol")}</th><th>CIDR</th><th>${t("inst.port")}</th><th></th></tr>
    ${l.rules.map((r) => `<tr><td>${r.direction === "ingress" ? t("inst.ingress") : t("inst.egress")}</td><td>${esc(r.protocol)}</td><td class="mono">${esc(r.cidr)}</td><td>${esc(r.port)}</td>
    <td><button class="btn sm danger" data-rm="${esc(l.id)}|${r.direction}|${r.idx}">${t("common.delete")}</button></td></tr>`).join("")}</table>
    <div class="bar"><button class="btn sm" data-add="${esc(l.id)}">${t("inst.addRule")}</button><button class="btn sm" data-ports="1">${t("inst.allowPorts")}</button></div>`).join("");
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal wide"><h3>${t("inst.secTitle", { name: esc(inst.name) })}</h3><div class="mb">${body}</div><div class="acts"><button class="btn" data-x>${t("common.close")}</button></div></div>`;
  document.body.appendChild(bg);
  const again = () => { bg.remove(); openSecurity(acc, inst, base); };
  bg.querySelector("[data-x]").onclick = () => bg.remove();
  bg.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = async () => {
    const [sl_id, direction, idx] = b.dataset.rm.split("|");
    if (!(await confirmBox(t("traf.delTitle"), t("inst.delRuleConfirm"), true))) return;
    if (await act(b, () => post(`/accounts/${acc.id}/oci/security`, { op: "remove", region: base.region, sl_id, direction, idx }), t("common.deleted"))) again();
  }));
  const pubOk = async (cidr, what) => !PUBLIC_CIDR(cidr) || !!(await publicWarn(cidr, esc(what)));
  // 「放行指定端口」：与实例操作「开放端口」同一个接口（来源 0.0.0.0/0）
  bg.querySelectorAll("[data-ports]").forEach((b) => (b.onclick = () => { bg.remove(); openPortDialog(acc, inst, base, null); }));
  bg.querySelectorAll("[data-add]").forEach((b) => (b.onclick = async () => {
    const r = await modal(t("inst.addRule"), `<div class="row2"><div><label>${t("inst.direction")}</label><select name="direction"><option value="ingress">${t("inst.ingress")}</option><option value="egress">${t("inst.egress")}</option></select></div>
      <div><label>${t("inst.protocol")}</label><select name="protocol"><option>tcp</option><option>udp</option><option>icmp</option><option>icmpv6</option><option>all</option></select></div></div>
      <label>CIDR</label><input name="cidr" placeholder="${t("inst.cidrPh")}">
      ${portModeFields()}<label>${t("inst.desc")}</label><input name="desc">
      <p class="muted">${t("inst.secNote")}</p>`, (f) => form(f), t("inst.next"));
    if (!r) return;
    const ports = portsOf(r);
    if (r.direction === "ingress" && !(await pubOk(r.cidr, ports ? t("inst.whatPorts", { p: ports }) : t("inst.whatProto")))) return;
    const res = await act(null, () => post(`/accounts/${acc.id}/security-rules`, { instance_id: inst.id, region: base.region, sl_id: b.dataset.add,
      direction: r.direction, protocol: r.protocol, cidr: r.cidr, ports, description: r.desc, confirm_public: PUBLIC_CIDR(r.cidr) }));
    if (res) { toast(t("inst.addedToast", { a: res.added, skip: res.skipped ? t("inst.skippedPart", { n: res.skipped }) : "" })); again(); }
  }));
}

export const migSpec = (p) => ({
    oci: `<div class="row2" data-oci-os><div><label>${t("inst.spec")}</label><select name="shape">${ociShapeOpts("VM.Standard.A1.Flex", ["VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"])}</select></div>
      ${ociOsFields({ os: "Canonical Ubuntu" })}
      <div><label>OCPU</label><input name="ocpus" type="number" min="1" value="1"></div><div><label>${t("inst.memGb")}</label><input name="memory_gb" type="number" min="1" value="6"></div>
      <div><label>${t("inst.diskGb")}</label><input name="disk_gb" type="number" min="47" value="50"></div></div>`,
    aws: `<div class="row2"><div><label>${t("inst.instType")}</label><input name="type" value="t3.micro"></div>
      <div><label>${t("inst.os")}</label><select name="os"><option>debian-12</option><option>ubuntu-24.04</option><option>ubuntu-22.04</option></select></div>
      <div><label>${t("inst.diskGb")}</label><input name="disk_gb" type="number" min="8" value="10"></div><div><label>${t("inst.extraPorts")}</label><input name="ports" placeholder="80,443"></div></div>`,
    azure: `<div class="row2"><div><label>${t("core.region.title")}</label><input name="location" value="eastasia"></div><div><label>${t("inst.size")}</label><input name="size" value="Standard_B1s"></div>
      <div><label>${t("inst.os")}</label><select name="os"><option>debian-12</option><option>ubuntu-24.04</option></select></div>
      <div><label>${t("inst.diskType")}</label><select name="disk_type"><option>Premium_LRS</option><option>StandardSSD_LRS</option></select></div>
      <div><label>${t("inst.diskGb")}</label><input name="disk_gb" type="number" min="30" value="64"></div><div><label>${t("inst.extraPorts")}</label><input name="ports" placeholder="80,443"></div></div>`,
  }[p]);
export async function migrateDialog(acc, inst) {
  const targets = ACCOUNTS.filter((a) => a.id !== acc.id && !NO_CREATE.has(a.provider));
  if (!targets.length) return toast(t("inst.migNeed2"), true);
  const lf = await loginFields();

  const r = await modal(t("inst.migTitle"), `<p>${t("inst.migBody", { name: esc(inst.name) })}</p>
    <p class="muted">${t("inst.migWarn")}</p>
    <label>${t("inst.migTarget")}</label><select name="to" id="mto">${targets.map((a) => `<option value="${a.id}">${PNAME[a.provider]} · ${esc(a.name)}</option>`).join("")}</select>
    <label>${t("inst.migName")}</label><input name="name" value="${esc(inst.name)}-new">
    <div id="mspec">${migSpec(targets[0].provider)}</div>${lf}
    <label><input type="checkbox" name="switch_dns" checked> ${t("inst.migDns")}</label>
    <label><input type="checkbox" name="copy_monitor" checked> ${t("inst.migMonitor")}</label>
    <label><input type="checkbox" name="stop_source"> ${t("inst.migStop")}</label>`, (bg) => {
    const f = form(bg); const to = ACCOUNTS.find((a) => a.id == f.to);
    const { to: _t, switch_dns, copy_monitor, stop_source, ...create } = f;
    return post("/migrate", { from_account_id: acc.id, from_region: regionOf(acc) || undefined, instance_id: inst.id, name: inst.name,
      to_account_id: to.id, region: to.provider === "azure" ? undefined : regionOf(to) || undefined, create, switch_dns, copy_monitor, stop_source });
  }, t("inst.migGo"));
  if (r) toast(t("inst.migCreated", { id: r.task_id }));
}
document.addEventListener("change", (e) => {
  if (e.target.id !== "mto") return;
  const a = ACCOUNTS.find((x) => x.id == e.target.value); const box = document.getElementById("mspec");
  if (a && box) box.innerHTML = migSpec(a.provider);
});

// ================= v1.3 新增：流量守护 / 串口控制台 =================
export const FREE_OUT = { oci: 10240, aws: 100, azure: 100 };
export async function trafficDialog(acc, inst, kind, onSaved) {
  let gs = [];
  try { gs = await api("/traffic-guards"); } catch (_) { /* ignore */ }
  const g = gs.find((x) => x.account_id === acc.id && x.instance_id === inst.id) || {};
  if (TRAFFIC_DIALOG[acc.provider]) return TRAFFIC_DIALOG[acc.provider](acc, inst, g, onSaved);
  let use = "";
  try {
    const rgq = NOREG(acc) ? "" : `region=${encodeURIComponent(inst.region || regionOf(acc))}`;
    const td = await api(`/accounts/${acc.id}/traffic?instance_id=${encodeURIComponent(inst.id)}&kind=${kind}&${rgq}`);
    use = `<p>${t("inst.trafficUse", { period: esc(td.period), out: td.out_gb, in: td.in_gb })}</p>`;
  } catch (e) { use = `<p class="muted">${t("inst.trafficFail", { msg: esc(e.message) })}</p>`; }
  const mode = g.mode || "monthly", dir = g.direction || (g.count_in ? "both" : "out");
  const r = await modal(t("inst.trafTitle", { name: inst.name }), `${use}
    <p class="muted">${t("inst.trafNote")}</p>
    <div class="row2"><div><label>${t("inst.trafMode")}</label><select name="mode"><option value="monthly">${t("inst.trafMonthly")}</option><option value="rolling" ${mode === "rolling" ? "selected" : ""}>${t("inst.trafRolling")}</option></select></div>
    <div data-show-when="mode=rolling"><label>${t("inst.trafWindow")}</label><input name="window_hours" type="number" min="1" max="720" value="${g.window_hours || 24}"></div>
    <div><label>${t("inst.direction")}</label><select name="direction">${[["out", t("inst.dirOut")], ["in", t("inst.dirIn")], ["both", t("inst.dirBoth")]].map(([v, l]) => `<option value="${v}" ${dir === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    <div><label><span data-show-when="mode=monthly">${t("inst.trafMonthlyWord")}</span><span data-show-when="mode=rolling">${t("inst.trafWindowWord")}</span>${t("inst.trafLimit", { n: FREE_OUT[acc.provider] })}</label><input name="limit_gb" type="number" min="1" value="${g.limit_gb || FREE_OUT[acc.provider]}"></div>
    <div><label>${t("inst.trafWarn")}</label><input name="warn_pct" type="number" min="10" max="99" value="${g.warn_pct || 80}"></div>
    <div><label>${t("inst.trafAction")}</label><select name="action"><option value="notify">${t("traf.notifyOnly")}</option><option value="stop" ${g.action === "stop" ? "selected" : ""}>${t("inst.trafActStop")}</option><option value="throttle" ${g.action === "throttle" ? "selected" : ""}>${t("inst.trafActThrottle")}</option></select></div>
    <div data-show-when="action=stop"><label>${t("inst.trafShutdown")}</label><input name="shutdown_hours" type="number" min="0" max="720" step="0.5" value="${g.shutdown_hours || 0}"></div>
    <div data-show-when="action=throttle"><label>${t("inst.trafThrottle")}</label><input name="throttle_mbps" type="number" min="0.1" max="10000" step="0.1" value="${g.throttle_mbps || 1}"></div></div>
    <p class="muted" data-show-when="action=stop">${t("inst.trafStopNote")}</p>
    <p class="muted" data-show-when="action=throttle">${t("inst.trafThrottleNote")}</p>
    <label><input type="checkbox" name="acct_enabled" ${g.acct_enabled ? "checked" : ""}> ${t("inst.trafAcct")}</label>
    <label><input type="checkbox" name="enabled" ${g.enabled === 0 ? "" : "checked"}> ${t("inst.trafEnable")}</label>
    ${g.id ? `<div class="bar" style="margin-top:8px"><span class="grow">${agentLine(g.agent, g)}</span><button type="button" class="btn sm" id="tgAgent">agent</button><button type="button" class="btn sm" id="tgPorts">${t("traf.ports")}</button></div>` : ""}`,
    (bg) => post("/traffic-guards", { account_id: acc.id, instance_id: inst.id, region: inst.region || regionOf(acc) || undefined, kind, name: inst.name, ...form(bg) }), t("common.save"), false,
    (bg) => {
      if (bg.querySelector("#tgAgent")) bg.querySelector("#tgAgent").onclick = () => { bg.remove(); guardAgentDialog(g, onSaved); };
      if (bg.querySelector("#tgPorts")) bg.querySelector("#tgPorts").onclick = () => { bg.remove(); guardPortsDialog(g); };
    });
  if (r) {
    toast(r.warning || t("inst.trafSaved", { gb: r.last_gb ?? "-", pct: r.last_pct ?? "-" }), !!r.warning);
    if (onSaved) onSaved();
    const ng = (await api("/traffic-guards").catch(() => [])).find((x) => x.id === r.id);
    if (ng && (ng.action === "throttle" || ng.acct_enabled) && !(ng.agent && ng.agent.installed)) guardAgentDialog(ng, onSaved);   // 首次选限速 / 流量明细：直接给安装命令
  }
}

// ---------- 实例表格视图 ----------
export const INLINE_OPS = ["start", "stop", "reboot", "changeip"];
// 按实例状态禁用无意义的操作：运行中不能再启动，已停止不能停止/重启
export function opOff(op, i) {
  const st = String(i.state || "").toLowerCase();
  const up = ["running", "starting", "provisioning", "pending"].includes(st), down = ["stopped", "stopping", "deallocated", "deallocating", "stopped (deallocated)"].includes(st);
  if (op === "start" && up) return t("inst.offRunning");
  if ((op === "stop" || op === "reboot") && down) return t("inst.offStopped");
  return "";
}
export const opBtn = (o, l, i, cls = "") => { const off = opOff(o, i); return `<button class="btn sm ${cls}" data-op="${o}"${off ? ` disabled title="${off}"` : ""}>${l}</button>`; };
export function instTable(acc, list, kind) {
  // v1.5：参照线上版——默认表格视图，列：名称/状态/规格/公网 IP/内网 IP/地域/创建时间，行内操作全部平铺
  const spec = (i) => acc.provider === "oci" ? `${esc(i.shape)} ${i.ocpus ?? ""}C/${i.memory_gb ?? ""}G` : esc(i.shape || "-");
  const when = (c) => { if (!c || c === "None") return "-"; const t = String(c).replace("T", " "); return esc(t.slice(0, 16)); };
  const ops = instOps(acc, kind);
  return `<table class="inst-table"><tr><th>${t("acc.colName")}</th><th>${t("common.status")}</th><th>${t("inst.spec")}</th><th>${t("inst.colPublic")}</th><th>${t("inst.colPrivate")}</th><th>${t("inst.colRegion")}</th><th>${t("inst.colCreated")}</th><th>${t("inst.colOps")}</th></tr>
    ${list.map((i) => `<tr data-id="${esc(i.id)}"><td><b title="${esc(i.id)}">${esc(i.name)}</b>${(i.ipv6 || []).length ? `<div class="muted mono" title="${esc(i.ipv6.join("\n"))}">${esc(i.ipv6[i.ipv6.length - 1])}${i.ipv6.length > 1 ? ` +${i.ipv6.length - 1}` : ""}</div>` : ""}</td>
    <td><span class="badge ${esc(i.state)}">${esc(i.state)}</span></td><td>${spec(i)}</td><td class="mono nowrap">${esc(i.public_ip || "-")}</td><td class="mono nowrap">${esc(i.private_ip || "-")}</td>
    <td class="nowrap">${esc(i.zone || i.region ? regionLabel(i.zone || i.region) : "-")}</td><td class="mono nowrap">${when(i.created)}</td>
    <td class="row-ops"><div class="row-ops-in">${ops.map(([o, l]) => opBtn(o, l, i, o === "terminate" ? "danger" : "")).join("")}</div></td></tr>`).join("")}</table>`;
}
export function opsMenu(anchor, ops, pick) {
  closeOpsMenu();
  const m = document.createElement("div"); m.className = "opsmenu"; m.setAttribute("role", "menu");
  m.innerHTML = ops.map(([o, l]) => `<button role="menuitem" class="${o === "terminate" ? "danger" : ""}" data-o="${o}">${l}</button>`).join("");
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  m.style.top = `${Math.min(r.bottom + 4, window.innerHeight - m.offsetHeight - 8)}px`;
  m.style.left = `${Math.max(8, Math.min(r.right - 200, window.innerWidth - 216))}px`;
  m.querySelectorAll("[data-o]").forEach((b) => (b.onclick = () => { closeOpsMenu(); pick(b.dataset.o); }));
}
export function closeOpsMenu() { document.querySelectorAll(".opsmenu").forEach((m) => m.remove()); }

// ---------- 3. 重装系统 ----------
export const AWS_OS = [["debian-12", "Debian 12"], ["ubuntu-24.04", "Ubuntu 24.04"], ["ubuntu-22.04", "Ubuntu 22.04"], ["al2023", "Amazon Linux 2023"]];
export const AZ_OS = [["debian-12", "Debian 12"], ["ubuntu-24.04", "Ubuntu 24.04"], ["ubuntu-22.04", "Ubuntu 22.04"]];
export async function reinstallDialog(acc, inst, base) {
  const oci = acc.provider === "oci";
  const osField = oci ? `<div class="row2" data-oci-os><input type="hidden" name="shape" value="${esc(inst.shape || "")}">${ociOsFields({})}</div>
      <label>${t("inst.reinstallDisk")}</label><input name="disk_gb" type="number" min="47">`
    : `<label>${t("inst.os")}</label><select name="os">${(acc.provider === "aws" ? AWS_OS : AZ_OS).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>`;
  const how = oci ? t("inst.reinstallHowOci")
    : acc.provider === "aws" ? t("inst.reinstallHowAws")
      : t("inst.reinstallHowAz");
  const p = modal(t("op.reinstall"), `<p>${t("inst.reinstallWarn", { name: esc(inst.name) })}</p>
    <p class="muted">${how}${t("inst.reinstallDown")}</p>${osField}
    ${acc.provider === "aws" ? "" : `<label><input type="checkbox" name="password_login" style="width:auto" checked> ${t("inst.reinstallPw")}</label>
    <label>${t("inst.sshKey")}</label><textarea name="ssh_key" placeholder="ssh-ed25519 AAAA..."></textarea>`}
    <label><input type="checkbox" name="confirm" style="width:auto"> ${t("inst.reinstallConfirm")}</label>`, (bg) => {
    const f = form(bg);
    if (!f.confirm) throw new Error(t("inst.reinstallNeedConfirm"));
    delete f.shape;
    return post(`/accounts/${acc.id}/instances/reinstall`, { ...base, ...f, confirm: true });
  }, t("inst.reinstallGo"), true);
  if (oci) setTimeout(() => wireOciOs(lastModal() && lastModal().querySelector("[data-oci-os]"), acc), 0);
  const r = await p;
  if (r) toast(t("inst.taskCreatedAlt", { id: r.task_id }));
}

// ---------- 8. OCI 附加 IP / 辅助网卡 / 预留 IP ----------
export async function ociIpsDialog(acc, inst, base, reload) {
  let d;
  try { toast(t("inst.readingIps")); d = await api(`/accounts/${acc.id}/oci/ips?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  const ipRow = (v, ip) => `<tr><td class="mono">${esc(ip.ip)}${ip.primary ? ` <span class="badge">${t("inst.primary")}</span>` : ""}</td>
    <td class="mono">${ip.public ? `${esc(ip.public.ip)} <span class="muted">${ip.public.lifetime === "RESERVED" ? t("inst.ipReserved") : t("inst.ipTemp")}</span>` : "-"}</td>
    <td>${ip.primary ? "" : `<button class="btn sm danger" data-delip="${esc(ip.id)}">${t("common.delete")}</button>`}</td></tr>`;
  const html = d.vnics.map((v) => `<h4>${v.primary ? t("inst.vnicPrimary") : t("inst.vnicSecondary")} · ${esc(v.name || "")}
      ${v.primary ? `<button class="btn sm" data-addip="${esc(v.vnic_id)}">${t("inst.addIp")}</button>` : `<button class="btn sm danger" data-detach="${esc(v.attachment_id)}">${t("inst.detachVnic")}</button>`}</h4>
    <table><tr><th>${t("inst.colPrivIp")}</th><th>${t("inst.colPublic")}</th><th></th></tr>${v.ips.map((ip) => ipRow(v, ip)).join("")}</table>`).join("")
    + `<div class="bar" style="margin-top:10px"><button class="btn" id="addVnic">${t("inst.addVnic")}</button></div>
    <h4>${t("inst.reservedTitle")}<button class="btn sm" id="newRes">${t("inst.newReserved")}</button></h4>
    <table><tr><th>IP</th><th>${t("common.status")}</th><th></th></tr>${d.reserved.map((r) => `<tr><td class="mono">${esc(r.ip)}</td><td>${r.assigned ? t("inst.bound") : t("inst.unbound")}</td>
      <td>${r.assigned ? `<button class="btn sm" data-unres="${esc(r.id)}">${t("inst.unbind")}</button>` : `<button class="btn sm" data-res="${esc(r.id)}" data-ip="${esc(r.ip)}">${t("inst.bindHere")}</button> <button class="btn sm danger" data-delres="${esc(r.id)}">${t("common.delete")}</button>`}</td></tr>`).join("") || `<tr><td colspan=3 class="muted">${t("common.none")}</td></tr>`}</table>
    <p class="muted">${t("inst.ipsNote")}</p>`;
  const done = (r) => { if (r && r.hint) modal(t("inst.done"), `<p>${esc(r.hint)}</p>`, null, t("common.understood")); else toast(t("inst.done")); lastModal() && lastModal().remove(); ociIpsDialog(acc, inst, base, reload); };
  const opp = (b, body) => act(b, () => post(`/accounts/${acc.id}/oci/ips`, { region: regionOf(acc) || undefined, instance_id: inst.id, ...body })).then((r) => r && done(r));
  modal(t("inst.ipsTitle", { name: inst.name }), html, null, t("common.close"));
  const bg = lastModal();
  bg.querySelectorAll("[data-addip]").forEach((b) => (b.onclick = () => opp(b, { op: "add_secondary", vnic_id: b.dataset.addip })));
  bg.querySelectorAll("[data-delip]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("inst.delIpTitle"), t("inst.delIpConfirm"), true)) opp(b, { op: "delete_private", private_ip_id: b.dataset.delip }); }));
  bg.querySelectorAll("[data-detach]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("inst.detachTitle"), t("inst.detachConfirm"), true)) opp(b, { op: "detach_vnic", attachment_id: b.dataset.detach }); }));
  bg.querySelector("#addVnic").onclick = (e) => opp(e.target, { op: "attach_vnic" });
  bg.querySelector("#newRes").onclick = (e) => opp(e.target, { op: "create_reserved" });
  bg.querySelectorAll("[data-res]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("inst.bindTitle"), t("inst.bindConfirm", { ip: esc(b.dataset.ip), name: esc(inst.name) }))) opp(b, { op: "assign_reserved", public_ip_id: b.dataset.res, ip: b.dataset.ip }).then(() => setTimeout(reload, 1500)); }));
  bg.querySelectorAll("[data-unres]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("inst.unbindTitle"), t("inst.unbindConfirm"))) opp(b, { op: "unassign_reserved", public_ip_id: b.dataset.unres }).then(() => setTimeout(reload, 1500)); }));
  bg.querySelectorAll("[data-delres]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("inst.delResTitle"), t("inst.delResConfirm"), true)) opp(b, { op: "delete_reserved", public_ip_id: b.dataset.delres }); }));
}

// ---------- 9. IP 质量 ----------
export function qualityHtml(q) {
  const lv = q.risk == null ? "" : q.risk <= 33 ? "done" : q.risk <= 66 ? "running" : "failed";
  return `<div class="kv"><span>IP</span><span class="mono">${esc(q.ip)}</span>
    <span>${t("inst.risk")}</span><span>${q.risk == null ? t("inst.queryFail") : `<span class="badge ${lv}">${q.risk}</span> <span class="muted">${t("inst.riskNote")}</span>`}</span>
    <span>${t("common.type")}</span><span>${esc(q.type || "-")}${q.proxy ? t("inst.proxyFlag") : ""}</span>
    <span>${t("inst.country")}</span><span>${esc(q.country || "-")} ${esc(q.country_code || "")}</span>
    <span>ISP / ASN</span><span>${esc(q.isp || "-")} ${esc(q.asn || "")}</span>
    <span>${t("inst.hosting")}</span><span>${q.hosting == null ? "-" : q.hosting ? t("common.yes") : t("common.no")}</span></div>
    ${q.error ? `<p class="muted">${esc(q.error)}</p>` : ""}<p class="muted">${t("inst.qualityNote", { src: esc(q.source || "") })}</p>`;
}
export async function qualityDialog(inst) {
  if (!inst.public_ip) return toast(t("inst.noPublicIp"), true);
  let q;
  try { toast(t("inst.checking")); q = await api(`/ip-quality?ip=${encodeURIComponent(inst.public_ip)}`); } catch (e) { return toast(e.message, true); }
  modal(t("inst.qualityTitle", { name: inst.name }), qualityHtml(q), null, t("common.close"));
}
export const qualityFields = () => `<details><summary class="muted">${t("inst.qTitle")}</summary>
  <div class="row2"><div><label>${t("inst.qRisk")}</label><input name="quality_max_risk" type="number" min="0" max="100" placeholder="${t("inst.qRiskPh")}"></div>
  <div><label>${t("inst.qCountry")}</label><input name="quality_country" placeholder="${t("inst.qCountryPh")}"></div></div>
  <p class="muted">${t("inst.qNote")}</p></details>`;

// ---------- 15. 免费 AMD 下行 500Mbps ----------
export async function net500Dialog(acc, inst, base) {
  let st;
  try { st = await api(`/accounts/${acc.id}/oci/500m?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  if (st.enabled) {
    const r = await modal(t("inst.net500OffTitle"), `<p>${t("inst.net500Cur", { ip: esc(st.public_ip || "-") })}</p><p class="muted">${t("inst.net500OffNote")}</p>`,
      () => post(`/accounts/${acc.id}/oci/500m`, { ...base, enable: false }), t("common.close"), true);
    if (r) toast(t("inst.taskCreatedShort", { id: r.task_id }));
    return;
  }
  const r = await modal(t("inst.net500OnTitle"), `<p>${t("inst.net500Intro")}</p>
    <ul class="guard"><li>${t("inst.net500Li1")}</li>
    <li>${t("inst.net500Li2")}</li><li>${t("inst.net500Li3")}</li></ul>
    <label>${t("inst.net500Health")}</label><input name="ssh_port" type="number" value="22" min="1" max="65535">
    <p class="muted">${t("inst.net500Note")}</p>`, (bg) => post(`/accounts/${acc.id}/oci/500m`, { ...base, ...form(bg), enable: true, confirm: true }), t("inst.net500On"));
  if (r) toast(t("inst.net500Push", { id: r.task_id }));
}

// ---------- 14. Azure 磁盘 ----------
export async function azDiskDialog(acc, inst) {
  let d;
  try { toast(t("inst.readingDisks")); d = await api(`/accounts/${acc.id}/azure/disks?instance_id=${encodeURIComponent(inst.id)}`); } catch (e) { return toast(e.message, true); }
  const rows = d.disks.map((k) => `<tr><td>${k.role === "os" ? t("inst.diskOs") : t("inst.diskData", { n: k.lun })}<div class="muted mono">${esc(k.name)}</div></td><td>${k.size_gb} GB</td><td>${esc(k.sku || "-")}</td><td>${esc(k.tier || "-")}</td>
    <td><button class="btn sm" data-disk="${esc(k.id)}">${t("inst.adjust")}</button></td></tr>`).join("");
  modal(t("inst.diskTitle", { name: inst.name }), `<table><tr><th>${t("inst.disk")}</th><th>${t("inst.size")}</th><th>${t("common.type")}</th><th>${t("inst.diskTier")}</th><th></th></tr>${rows}</table><p class="muted">${esc(d.hint)}</p>`, null, t("common.close"));
  lastModal().querySelectorAll("[data-disk]").forEach((b) => (b.onclick = async () => {
    const k = d.disks.find((x) => x.id === b.dataset.disk);
    const r = await modal(t("inst.adjustTitle", { name: k.name }), `<div class="row2"><div><label>${t("inst.diskSize")}</label><input name="size_gb" type="number" min="${k.size_gb}" placeholder="${k.size_gb}"></div>
      <div><label>${t("common.type")}</label><select name="sku">${d.skus.map((s) => `<option ${s === k.sku ? "selected" : ""}>${s}</option>`).join("")}</select></div></div>
      <label>${t("inst.diskTierLabel")}</label><select name="tier"><option value="">${t("inst.diskTierSame")}</option>${d.tiers.map((t) => `<option ${t === k.tier ? "selected" : ""}>${t}</option>`).join("")}</select>`,
      (bg) => { const f = form(bg); if (f.sku === k.sku) delete f.sku; return post(`/accounts/${acc.id}/azure/disks`, { instance_id: inst.id, disk_id: k.id, ...f }); }, t("inst.submit"));
    if (r) { toast(r.hint || t("inst.adjusted")); lastModal() && lastModal().remove(); azDiskDialog(acc, inst); }
  }));
}

// ---------- 19. Lightsail 防火墙 ----------
export async function lsPortsDialog(acc, inst) {
  const load = () => api(`/accounts/${acc.id}/lightsail/ports?instance=${encodeURIComponent(inst.id)}&${rq(acc)}`);
  let ports;
  try { ports = await load(); } catch (e) { return toast(e.message, true); }
  modal(t("inst.fwTitle", { name: inst.name }), `<table><tr><th>${t("inst.protocol")}</th><th>${t("inst.port")}</th><th>${t("inst.source")}</th><th></th></tr>${ports.map((p, i) => `<tr><td>${esc(p.protocol)}</td><td>${p.from === p.to ? p.from : `${p.from}-${p.to}`}</td>
    <td class="mono">${esc([...p.cidrs, ...p.ipv6_cidrs].join(", ") || "-")}</td><td><button class="btn sm danger" data-close="${i}">${t("inst.closePort")}</button></td></tr>`).join("") || `<tr><td colspan=4 class="muted">${t("inst.noOpenPorts")}</td></tr>`}</table>
    <div class="row2"><div><label>${t("inst.protocol")}</label><select name="protocol"><option>tcp</option><option>udp</option><option>icmp</option></select></div>
    <div><label>${t("inst.portRangeLabel")}</label><input name="port" placeholder="${t("inst.portPh")}"></div></div>
    <label>${t("inst.cidrLabel")}</label><input name="cidrs" value="0.0.0.0/0">
    <div class="bar"><button class="btn primary" id="lsOpen">${t("op.openport")}</button></div>`, null, t("common.close"));
  const bg = lastModal();
  bg.querySelectorAll("[data-close]").forEach((b) => (b.onclick = async () => {
    const p = ports[+b.dataset.close];
    if (!(await confirmBox(t("inst.closePortTitle"), t("inst.closePortConfirm", { proto: esc(p.protocol), from: p.from, to: p.to }), true))) return;
    if (await act(b, () => post(`/accounts/${acc.id}/lightsail/ports`, { op: "close", instance: inst.id, region: regionOf(acc), protocol: p.protocol, from_port: p.from, to_port: p.to }), t("inst.closed"))) { bg.remove(); lsPortsDialog(acc, inst); }
  }));
  bg.querySelector("#lsOpen").onclick = async (e) => {
    const f = form(bg); const m = /^(\d+)(?:\s*-\s*(\d+))?$/.exec(f.port || "");
    if (f.protocol !== "icmp" && !m) return toast(t("inst.portFormat"), true);
    const body = { op: "open", instance: inst.id, region: regionOf(acc), protocol: f.protocol, from_port: m ? +m[1] : -1, to_port: m ? +(m[2] || m[1]) : -1, cidrs: f.cidrs };
    if (f.protocol === "icmp") { body.from_port = 0; body.to_port = 0; }
    try { await post(`/accounts/${acc.id}/lightsail/ports`, body); }
    catch (err) {
      if (!/0\.0\.0\.0|整个互联网/.test(err.message)) return toast(err.message, true);
      if (!(await confirmBox(t("inst.pubTitlePlain"), t("inst.pubConfirmMsg", { port: esc(f.port || "ICMP") }), true))) return;
      if (!(await act(e.target, () => post(`/accounts/${acc.id}/lightsail/ports`, { ...body, confirm_public: true })))) return;
    }
    toast(t("inst.opened")); bg.remove(); lsPortsDialog(acc, inst);
  };
}

// ---------- 实例操作入口 ----------
export const V16_OPS = {
  reinstall: (acc, inst, base) => reinstallDialog(acc, inst, base),
  ips: (acc, inst, base, kind, btn, reload) => ociIpsDialog(acc, inst, base, reload),
  quality: (acc, inst) => qualityDialog(inst),
  net500: (acc, inst, base) => net500Dialog(acc, inst, base),
  disks: (acc, inst) => azDiskDialog(acc, inst),
  lsports: (acc, inst) => lsPortsDialog(acc, inst),
};
export function v16Ops(acc, kind, ops) {
  const i = ops.findIndex(([o]) => o === "terminate");
  const add = [];
  if (acc.provider === "oci") add.push(["ips", t("op.ips")], ["net500", t("op.net500")]);
  if (acc.provider === "azure") add.push(["disks", t("op.disks")]);
  if (kind === "lightsail") add.push(["lsports", t("op.lsports")]);
  add.push(["quality", t("op.quality")]);
  if (kind !== "lightsail") add.push(["reinstall", t("op.reinstall")]);
  ops.splice(i < 0 ? ops.length : i, 0, ...add);
  return ops;
}
