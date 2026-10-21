// TriCloud 前端 v1.6.0 · OCI：创建 / 抢机、配额、安全组、存储、对象存储、流量、区域订阅、免费额度体检
import { $, ACCOUNTS, act, api, confirmBox, del, esc, fmtBytes, form, loading, modal, post, regionLabel, regionOf, regionSelect, rq, SETTINGS, toast, view } from "./core.js";
import { guardAgentDialog, guardPortsDialog } from "./guard.js";
import { loginFields, portModeFields, portsOf, publicWarn, showCreated, trafficDialog } from "./instances.js";
import { GST } from "./monitors.js";
import { t } from "./i18n.js";
import { saveDefaultBtn } from "./settings.js";

// ---------------- OCI 创建 / 抢机 ----------------
// OCI 规格：标明是否 Always Free（免费额度只在主区域有效）
export const OCI_SHAPES = [
  ["VM.Standard.A1.Flex", "oci.shapeA1"],
  ["VM.Standard.E2.1.Micro", "oci.shapeE2"],
  ["VM.Standard.E4.Flex", "oci.shapeE4"],
  ["VM.Standard3.Flex", "oci.shape3"],
];
export const ociShapeOpts = (cur, only) => OCI_SHAPES.filter(([v]) => !only || only.includes(v))
  .map(([v, d]) => `<option value="${v}" ${v === cur ? "selected" : ""}>${v} — ${t(d)}</option>`).join("");
// v1.5：OCI「系统 / 系统版本」联动下拉。内置列表先显示，再按规格异步拉 /oci/os-versions 替换；"" = 最新（_pick_image 取最新镜像）
export const OCI_OS_VERSIONS = { "Canonical Ubuntu": ["24.04", "22.04", "20.04"], "Oracle Linux": ["9", "8"] };
export function ociOsOpts(cur) {
  const os = OCI_OS_VERSIONS[cur] ? cur : "Canonical Ubuntu";
  return Object.keys(OCI_OS_VERSIONS).map((s) => `<option ${s === os ? "selected" : ""}>${s}</option>`).join("");
}
export function ociVerOpts(os, cur, map) {
  const vs = ["", ...((map && map[os]) || OCI_OS_VERSIONS[os] || []).filter(Boolean)];
  if (cur && !vs.includes(cur)) vs.push(cur);   // 默认值里保存的版本不在列表里：临时加成一个选项
  return vs.map((v) => `<option value="${esc(v)}" ${v === (cur || "") ? "selected" : ""}>${v ? esc(v) : t("oci.latest")}</option>`).join("");
}
export const ociOsFields = (d) => `<div><label>${t("inst.os")}</label><select name="os">${ociOsOpts(d.os)}</select></div>
    <div><label>${t("oci.osVer")}</label><select name="os_version">${ociVerOpts(OCI_OS_VERSIONS[d.os] ? d.os : "Canonical Ubuntu", d.os_version || "")}</select></div>`;
// keep: "always" 保留当前值（不在列表里就临时加）；"present" 只在新列表里有时保留；其他 = 回到「最新」
export function refillOciVer(box, keep) {
  const os = box.querySelector("[name=os]"), sel = box.querySelector("[name=os_version]");
  if (!os || !sel) return;
  let cur = keep ? sel.value : "";
  const list = (box._osv && box._osv[os.value]) || OCI_OS_VERSIONS[os.value] || [];
  if (keep === "present" && cur && !list.includes(cur)) cur = "";
  sel.innerHTML = ociVerOpts(os.value, cur, box._osv);
}
export async function loadOciVersions(box, keep = "present") {
  const acc = box._ociAcc, shape = box.querySelector("[name=shape]");
  if (!acc || !shape) return;
  const req = (box._osvReq = (box._osvReq || 0) + 1);
  try {
    const m = await api(`/accounts/${acc.id}/oci/os-versions?shape=${encodeURIComponent(shape.value)}&${rq(acc)}`);
    if (req !== box._osvReq || !m || !Object.keys(m).length) return;
    box._osv = m; refillOciVer(box, keep);
  } catch (_) { /* 失败继续用内置列表 */ }
}
export function wireOciOs(box, acc) { if (!box) return; box._ociAcc = acc; loadOciVersions(box, "always"); }
document.addEventListener("change", (e) => {
  const box = e.target.closest && e.target.closest("[data-oci-os]");
  if (!box) return;
  if (e.target.name === "os") refillOciVer(box);
  else if (e.target.name === "shape") { box._osv = null; refillOciVer(box, "present"); loadOciVersions(box); }   // 换规格（A1=aarch64 / E2=x86）重新拉
});
export function ociCreateFields(d) {
  d = d || {};
  return `<div class="row2" data-oci-os>
    <div><label>${t("oci.instName")}</label><input name="name" value="${esc(d.name || "oci-" + Date.now().toString(36))}"></div>
    <div><label>${t("inst.spec")}</label><select name="shape">
      ${ociShapeOpts(d.shape)}</select></div>
    <div><label>${t("oci.ocpuFlex")}</label><input name="ocpus" type="number" min="1" value="${esc(d.ocpus || 4)}"></div>
    <div><label>${t("oci.memFlex")}</label><input name="memory_gb" type="number" min="1" value="${esc(d.memory_gb || 24)}"></div>
    <div><label>${t("oci.bootGb")}</label><input name="disk_gb" type="number" min="47" value="${esc(d.disk_gb || 50)}"></div>
    ${ociOsFields(d)}
    <div><label>${t("oci.ad")}</label><input name="ad" value="${esc(d.ad || "")}"></div></div>
    <label>${t("oci.subnetId")}</label><input name="subnet_id" value="${esc(d.subnet_id || "")}">
    <label>${t("oci.sshKey")}</label><textarea name="ssh_key" placeholder="ssh-ed25519 AAAA...">${esc(d.ssh_key || "")}</textarea>
    <label><input type="checkbox" name="ipv6" style="width:auto" ${d.ipv6 ? "checked" : ""}> ${t("oci.ipv6")}</label>
    <p class="muted">${t("oci.createNote")}</p>`;
}
export async function tabOciCreate(acc, box) {
  box.innerHTML = `<div class="bar">${await regionSelect(acc, () => tabOciCreate(acc, box))}<span class="muted">${t("oci.defHint")}</span></div>
    <div class="card" id="f">${ociCreateFields(SETTINGS.default_create?.oci)}${await loginFields()}<div class="bar" style="margin-top:14px"><button class="btn primary" id="go">${t("common.createNow")}</button>${saveDefaultBtn("oci")}</div></div>`;
  wireOciOs($("[data-oci-os]", box), acc);
  $("#go", box).onclick = async (e) => { const r = await act(e.target, () => post(`/accounts/${acc.id}/oci/create`, { region: regionOf(acc), create: form($("#f", box)) })); if (r) showCreated(r); };
}
export async function tabOciSnatch(acc, box) {
  box.innerHTML = `<div class="bar">${await regionSelect(acc, () => tabOciSnatch(acc, box))}</div>
    <div class="card" id="f"><h3>${t("oci.snatchTitle")}</h3><p class="muted">${t("oci.snatchNote")}</p>
    ${ociCreateFields(SETTINGS.default_create?.oci)}${await loginFields()}
    <label>${t("oci.snatchBatch")}</label>
    <div class="chips">${ACCOUNTS.filter((a) => a.provider === "oci").map((a) => `<label class="chip"><input type="checkbox" data-acc="${a.id}" ${a.id === acc.id ? "checked" : ""} style="width:auto"> ${esc(a.name)}</label>`).join("")}</div>
    <div class="row2"><div><label>${t("oci.interval")}</label><input name="interval" type="number" min="30" value="60"></div>
    <div><label>${t("oci.maxAttempts")}</label><input name="max_attempts" type="number" min="0" value="0"></div></div>
    <div class="bar" style="margin-top:14px"><button class="btn primary" id="go">${t("oci.snatchGo")}</button><a class="btn" href="#/tasks">${t("oci.viewTasks")}</a>${saveDefaultBtn("oci")}</div></div>`;
  wireOciOs($("[data-oci-os]", box), acc);
  $("#go", box).onclick = (e) => {
    const f = form($("#f", box));
    const { interval, max_attempts, ...create } = f;
    const account_ids = [...box.querySelectorAll("[data-acc]:checked")].map((x) => +x.dataset.acc);
    if (!account_ids.length) return toast(t("oci.pickOne"), true);
    act(e.target, () => post(`/accounts/${acc.id}/oci/snatch`, { region: regionOf(acc), interval, max_attempts, create, account_ids }),
      (r) => t("oci.snatchStarted", { n: r.task_ids.length, ids: r.task_ids.join(", #") }));
  };
}

// OCI 配额 / 网络
export async function tabOciLimits(acc, box) {
  const reload = () => tabOciLimits(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">${t("common.refresh")}</button><button class="btn" id="net">${t("oci.netBtn")}</button></div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
  $("#rf", box).onclick = reload;
  $("#net", box).onclick = async (e) => {
    if (!(await confirmBox(t("oci.netBtn"), t("oci.netConfirm")))) return;
    act(e.target, () => post(`/accounts/${acc.id}/oci/network`, { region: regionOf(acc) }), (r) => t("inst.taskCreatedShort", { id: r.task_id }));
  };
  box.appendChild(regionSubSection(acc));   // 页面最底部，默认折叠
  let r;
  try { r = await api(`/accounts/${acc.id}/oci/limits?${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#lb", box).innerHTML = `<div class="card"><h3>${t("oci.limitsTitle", { region: esc(regionLabel(r.region)) })}</h3><table><tr><th>${t("oci.colItem")}</th><th>${t("oci.colLimit")}</th><th>${t("oci.colUsed")}</th><th>${t("oci.colAvail")}</th><th>${t("oci.colFree")}</th></tr>
    ${r.items.map((i) => `<tr><td>${esc(i.name)}</td><td>${i.limit}</td><td>${i.used ?? "-"}</td><td>${i.available ?? "-"}</td><td>${i.free == null ? "-" : `${i.free_left ?? "?"} / ${i.free}`}</td></tr>`).join("") || `<tr><td colspan=5 class="muted">${t("oci.noData")}</td></tr>`}</table>
    <p class="muted">${t("oci.limitsNote", { basis: r.a1_basis === "paid" ? t("oci.basisPaid") : r.a1_basis === "free" ? t("oci.basisFree") : t("oci.basisUnknown") })}</p></div>`;
}

// ---- OCI 安全组（独立标签页）：按子网选择（安全列表跟着子网走，同子网实例共享）、按规则内容删除、批量端口、对公网放行二次确认 ----
export const PUBLIC_CIDR = (c) => ["0.0.0.0/0", "::/0"].includes(String(c || "").replace(/\s/g, ""));
// 子网下拉文字：「VCN / 子网 CIDR · 实例1、实例2」，实例多于 4 台时「… 等 N 台」
export const subnetLabel = (s) => {
  const names = (s.instances || []).map((i) => i.name || "?");
  const tail = names.length ? names.slice(0, 4).join("、") + (names.length > 4 ? t("oci.subnetEtc", { n: names.length }) : "") : t("oci.subnetNone");
  return `${s.vcn_name ? s.vcn_name + " / " : ""}${s.name || t("oci.subnet")} ${s.cidr || ""} · ${tail}`;
};
export async function tabOciSecGroup(acc, box) {
  const reload = () => tabOciSecGroup(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<select id="sgSub" title="${t("oci.subnet")}"><option value="">${t("oci.sgLoading")}</option></select>
    <button class="btn" id="sgRen" disabled title="${t("oci.sgRenameTitle")}">${t("oci.rename")}</button><button class="btn" id="sgRf">${t("common.refresh")}</button><button class="btn primary" id="sgAdd" disabled>${t("inst.addRule")}</button><span class="grow"></span>
    <span class="muted">${t("oci.sgNote")}</span></div><div class="card" id="sgBox"><div class="empty">${t("oci.sgEmpty")}</div></div><div id="sgNsg"></div>`;
  $("#sgRf", box).onclick = reload;
  let subs = [];
  try { subs = (await api(`/accounts/${acc.id}/oci/security-subnets?${rq(acc)}`)).subnets || []; } catch (e) { $("#sgBox", box).innerHTML = `❌ ${esc(e.message)}`; return; }
  const key = "tc_sgsub_" + acc.id;
  let last = localStorage.getItem(key);
  if (!subs.some((s) => s.id === last)) {   // 旧版记的是实例：换成该实例所在的子网
    const li = localStorage.getItem("tc_sg_" + acc.id);
    last = (subs.find((s) => (s.instances || []).some((i) => i.id === li)) || subs[0] || {}).id || "";
  }
  $("#sgSub", box).innerHTML = subs.length ? subs.map((s) => `<option value="${esc(s.id)}"${s.id === last ? " selected" : ""}>${esc(subnetLabel(s))}</option>`).join("")
    : `<option value="">${t("oci.sgNoSubnet")}</option>`;
  if (subs.length) $("#sgSub", box).value = last;
  const load = async () => {
    const sid = $("#sgSub", box).value;
    $("#sgAdd", box).disabled = !sid;
    $("#sgRen", box).disabled = !sid;
    $("#sgNsg", box).innerHTML = "";
    if (!sid) return;
    localStorage.setItem(key, sid);
    const sub = subs.find((s) => s.id === sid) || {};
    const nsgRows = (sub.instances || []).filter((i) => (i.nsgs || []).length);
    $("#sgNsg", box).innerHTML = nsgRows.length ? `<div class="card"><h3>${t("oci.nsgTitle")}</h3>${nsgRows.map((i) => `<div><b>${esc(i.name)}</b>${t("oci.nsgSuffix", { list: i.nsgs.map((n) => esc(n.name)).join("、") })}</div>`).join("")}
      <p class="muted">${t("oci.nsgNote")}</p></div>` : "";
    $("#sgBox", box).innerHTML = `<span class="spin"></span>`;
    let d;
    try { d = await api(`/accounts/${acc.id}/security-rules?subnet_id=${encodeURIComponent(sid)}&${rq(acc)}`); }
    catch (e) { $("#sgBox", box).innerHTML = `❌ ${esc(e.message)}`; return; }
    const multi = d.lists.length > 1;
    const st = { dir: "all", q: "" };
    const many = d.rules.length > 10;
    $("#sgBox", box).innerHTML = `<div class="bar sgf"><span class="seg">${[["all", t("oci.dirAll")], ["ingress", t("inst.ingress")], ["egress", t("inst.egress")]].map(([k, l]) => `<button class="btn sm${k === "all" ? " primary" : ""}" data-sgdir="${k}">${l}</button>`).join("")}</span>
      ${many ? `<input id="sgQ" class="sm" placeholder="${t("oci.sgFilterPh")}" style="max-width:240px">` : ""}<span class="grow"></span><span class="muted" id="sgCnt"></span></div><div id="sgTbl"></div>`;
    const draw = () => {
      const q = st.q.trim().toLowerCase();
      const shown = d.rules.map((r, i) => [r, i]).filter(([r]) => (st.dir === "all" || r.direction === st.dir)
        && (!q || [r.port, r.cidr, r.protocol, r.desc, r.sl_name].some((x) => String(x ?? "").toLowerCase().includes(q))));
      $("#sgCnt", box).textContent = shown.length === d.rules.length ? t("oci.countTotal", { n: d.rules.length }) : t("oci.countShown", { a: shown.length, n: d.rules.length });
      $("#sgTbl", box).innerHTML = `<table><tr><th>${t("inst.direction")}</th><th>${t("inst.protocol")}</th><th>${t("oci.srcDst")}</th><th>${t("inst.port")}</th><th>${t("oci.colDesc")}</th>${multi ? `<th>${t("oci.colSecList")}</th>` : ""}<th></th></tr>
      ${shown.map(([r, i]) => `<tr><td>${r.direction === "ingress" ? t("inst.ingress") : t("inst.egress")}</td><td>${esc(r.protocol)}</td>
      <td class="mono">${esc(r.cidr)}${PUBLIC_CIDR(r.cidr) && r.direction === "ingress" ? ` <span class="badge failed">${t("oci.publicBadge")}</span>` : ""}</td><td class="mono">${esc(r.port)}</td>
      <td>${esc(r.desc)}</td>${multi ? `<td>${esc(r.sl_name)}</td>` : ""}<td><button class="btn sm danger" data-sgdel="${i}">${t("common.delete")}</button></td></tr>`).join("")
      || `<tr><td colspan="7" class="muted">${d.rules.length ? t("oci.noMatch") : t("oci.noRules")}</td></tr>`}</table>`;
    $("#sgTbl", box).querySelectorAll("[data-sgdel]").forEach((b) => (b.onclick = async () => {
      const r = d.rules[+b.dataset.sgdel];
      if (!(await confirmBox(t("traf.delTitle"), t("oci.sgDelConfirm", { dir: r.direction === "ingress" ? t("inst.ingress") : t("inst.egress"), proto: esc(r.protocol), cidr: esc(r.cidr), port: esc(r.port) }) + (r.direction === "ingress" && r.port === "22" ? t("oci.sgDel22") : ""), true))) return;
      const proto = { TCP: "tcp", UDP: "udp", ICMP: "icmp", ICMPv6: "icmpv6", "全部": "all" }[r.protocol] || String(r.protocol).toLowerCase();
      if (await act(b, () => api(`/accounts/${acc.id}/security-rules`, { method: "DELETE", body: { subnet_id: sid, region: regionOf(acc) || undefined, sl_id: r.sl_id,
        direction: r.direction, protocol: proto, cidr: r.cidr, port_min: r.port_min, port_max: r.port_max } }), t("common.deleted"))) load();
    }));
    };
    box.querySelectorAll("[data-sgdir]").forEach((b) => (b.onclick = () => {
      st.dir = b.dataset.sgdir;
      box.querySelectorAll("[data-sgdir]").forEach((x) => x.classList.toggle("primary", x === b));
      draw();
    }));
    if (many) $("#sgQ", box).oninput = (e) => { st.q = e.target.value; draw(); };
    draw();
    $("#sgAdd", box).onclick = () => addRule(sid, d.lists);
  };
  const addRule = async (sid, lists) => {
    const v = await modal(t("oci.addSecRule"), `<div class="row2"><div><label>${t("inst.direction")}</label><select name="direction"><option value="ingress">${t("inst.ingress")}</option><option value="egress">${t("inst.egress")}</option></select></div>
      <div><label>${t("inst.protocol")}</label><select name="protocol"><option value="tcp">TCP</option><option value="udp">UDP</option><option value="icmp">ICMP</option><option value="icmpv6">ICMPv6</option><option value="all">${t("oci.protoAll")}</option></select></div></div>
      <label>${t("oci.cidrLabel2")}</label><input name="cidr" placeholder="${t("inst.cidrPh")}">
      ${portModeFields()}
      ${lists.length > 1 ? `<label>${t("oci.colSecList")}</label><select name="sl_id">${lists.map((l) => `<option value="${esc(l.id)}">${esc(l.name)}</option>`).join("")}</select>` : ""}
      <label>${t("oci.descOpt")}</label><input name="description">
      <p class="muted">${t("oci.sgNote2")}</p>`, (bg) => form(bg), t("inst.next"));
    if (!v) return;
    const { port_mode, port_min, port_max, ...rest } = v;   // eslint-disable-line no-unused-vars
    const body = { subnet_id: sid, region: regionOf(acc) || undefined, ...rest, ports: portsOf(v) };
    if (!body.ports) delete body.ports;
    if (PUBLIC_CIDR(v.cidr) && v.direction === "ingress") {
      const go = await publicWarn(v.cidr, body.ports ? t("inst.whatPorts", { p: `<code>${esc(body.ports)}</code>` }) : t("inst.whatProto"), t("oci.pubOkAdd"));
      if (!go) return;
      body.confirm_public = true;
    }
    const r = await act(null, () => post(`/accounts/${acc.id}/security-rules`, body));
    if (r) { toast(t("inst.addedToast", { a: r.added, skip: r.skipped ? t("inst.skippedPart", { n: r.skipped }) : "" })); load(); }
  };
  $("#sgSub", box).onchange = load;
  $("#sgRen", box).onclick = () => { const s = subs.find((x) => x.id === $("#sgSub", box).value); if (s) renameSubnet(acc, s, reload); };
  load();
}

// 子网 / VCN 改名：只改显示名称（display_name），实例、IP、安全规则都不受影响；保存后刷新下拉并保持选中
export async function renameSubnet(acc, s, done) {
  const v = await modal(t("oci.subnetRename"), `<label>${t("oci.subnetName")}</label><input name="subnet" maxlength="255" value="${esc(s.name || "")}">
    ${s.vcn_id ? `<label>${t("oci.vcnName")}</label><input name="vcn" maxlength="255" value="${esc(s.vcn_name || "")}">` : ""}
    <p class="muted">${t("oci.renameNote")}${esc(s.cidr || "")}</p>`, (bg) => {
    const f = form(bg), sub = (f.subnet || "").trim(), vcn = (f.vcn || "").trim();
    if (!sub || (s.vcn_id && !vcn)) { toast(t("oci.nameEmpty"), true); return false; }
    if (sub.length > 255 || vcn.length > 255) { toast(t("oci.nameTooLong"), true); return false; }
    return { sub, vcn };
  }, t("common.save"));
  if (!v) return;
  const body = { region: regionOf(acc) || undefined };
  let changed = 0;
  if (v.sub !== (s.name || "")) {
    if (!(await act(null, () => api(`/accounts/${acc.id}/oci/subnets/${encodeURIComponent(s.id)}`, { method: "PATCH", body: { ...body, display_name: v.sub } })))) return;
    changed++;
  }
  if (s.vcn_id && v.vcn !== (s.vcn_name || "")) {
    if (!(await act(null, () => api(`/accounts/${acc.id}/oci/vcns/${encodeURIComponent(s.vcn_id)}`, { method: "PATCH", body: { ...body, display_name: v.vcn } })))) return;
    changed++;
  }
  if (!changed) { toast(t("oci.nameSame")); return; }
  toast(t("inst.renamed"));
  localStorage.setItem("tc_sgsub_" + acc.id, s.id);
  done();
}

// ---------- 6. OCI 存储（块存储卷 + 引导卷） ----------
export async function tabOciStorage(acc, box) {
  const reload = () => tabOciStorage(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">${t("common.refresh")}</button><button class="btn primary" id="newVol">${t("oci.newVol")}</button><span class="grow"></span><span class="muted" id="used"></span></div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
  $("#rf", box).onclick = reload;
  let d, insts = [];
  try { [d, insts] = await Promise.all([api(`/accounts/${acc.id}/oci/volumes?${rq(acc)}`), api(`/accounts/${acc.id}/instances?kind=vm&${rq(acc)}`).catch(() => [])]); }
  catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const iname = (id) => (insts.find((i) => i.id === id) || {}).name || (id ? id.slice(-10) : "-");
  $("#used", box).textContent = t("oci.usedLine", { u: d.used_gb, f: d.free_gb });
  $("#lb", box).innerHTML = `<div class="card"><h3>${t("oci.volTitle")}</h3><table><tr><th>${t("acc.colName")}</th><th>${t("inst.size")}</th><th>${t("inst.perf")}</th><th>${t("oci.colAttached")}</th><th>${t("common.status")}</th><th></th></tr>
    ${d.volumes.map((v) => `<tr data-v="${esc(v.id)}"><td>${esc(v.name)}</td><td>${v.size_gb} GB</td><td>${v.vpus_per_gb} VPU/GB</td><td>${v.attached_to ? esc(iname(v.attached_to)) + (v.device ? ` <span class="muted mono">${esc(v.device)}</span>` : "") : t("oci.unattached")}</td><td>${esc(v.state)}</td>
    <td><button class="btn sm" data-upd="${esc(v.id)}">${t("inst.adjust")}</button> ${v.attached_to ? `<button class="btn sm" data-det="${esc(v.attachment_id)}">${t("oci.detach")}</button>` : `<button class="btn sm" data-att="${esc(v.id)}">${t("oci.attach")}</button> <button class="btn sm danger" data-del="${esc(v.id)}">${t("common.delete")}</button>`}</td></tr>`).join("") || `<tr><td colspan=6 class="muted">${t("oci.noVols")}</td></tr>`}</table>
    <p class="muted">${t("oci.volNote")}</p></div>
    <div class="card"><h3>${t("oci.bootTitle")}</h3><table><tr><th>${t("acc.colName")}</th><th>${t("inst.size")}</th><th>${t("inst.perf")}</th><th>${t("common.status")}</th></tr>${d.boot_volumes.map((b) => `<tr><td>${esc(b.name)}</td><td>${b.size_gb} GB</td><td>${b.vpus_per_gb} VPU/GB</td><td>${esc(b.state)}</td></tr>`).join("") || `<tr><td colspan=4 class="muted">${t("common.none")}</td></tr>`}</table>
    <p class="muted">${t("oci.bootNote")}</p></div>`;
  const op = (b, body, msg) => act(b, () => post(`/accounts/${acc.id}/oci/volumes`, { region: regionOf(acc) || undefined, ...body }), msg).then((r) => { if (r) { if (r.hint) toast(r.hint); reload(); } return r; });
  const instOpts = insts.map((i) => `<option value="${esc(i.id)}">${esc(i.name)}</option>`).join("");
  $("#newVol", box).onclick = async () => {
    const r = await modal(t("oci.newVol"), `<label>${t("acc.colName")}</label><input name="name" placeholder="data-1">
      <div class="row2"><div><label>${t("oci.volSize")}</label><input name="size_gb" type="number" min="50" value="50"></div>
      <div><label>${t("inst.vpuLabel")}</label><select name="vpus_per_gb">${[0, 10, 20, 30, 60, 90, 120].map((v) => `<option ${v === 10 ? "selected" : ""} value="${v}">${v}${v === 0 ? t("oci.vpuLow") : v === 10 ? t("oci.vpuBal") : ""}</option>`).join("")}</select></div></div>
      <label>${t("oci.attachToOpt")}</label><select name="instance_id"><option value="">${t("oci.noAttach")}</option>${instOpts}</select>
      <p class="muted">${esc(t("oci.volUsedNote", { u: d.used_gb, f: d.free_gb }))}</p>`, (bg) => post(`/accounts/${acc.id}/oci/volumes`, { op: "create", region: regionOf(acc) || undefined, ...form(bg) }), t("oci.create"));
    if (r) { toast(r.attach && r.attach.hint ? r.attach.hint : t("oci.created")); reload(); }
  };
  box.querySelectorAll("[data-att]").forEach((b) => (b.onclick = async () => {
    const r = await modal(t("oci.attachVol"), `<label>${t("oci.attachTo")}</label><select name="instance_id">${instOpts}</select>`, (bg) => post(`/accounts/${acc.id}/oci/volumes`, { op: "attach", region: regionOf(acc) || undefined, volume_id: b.dataset.att, ...form(bg) }), t("oci.attach"));
    if (r) { toast(r.hint || t("oci.attached")); reload(); }
  }));
  box.querySelectorAll("[data-det]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("oci.detachVol"), t("oci.detachConfirm"), true)) op(b, { op: "detach", attachment_id: b.dataset.det }); }));
  box.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("oci.delVol"), t("oci.delVolConfirm"), true)) op(b, { op: "delete", volume_id: b.dataset.del, confirm: true }, t("common.deleted")); }));
  box.querySelectorAll("[data-upd]").forEach((b) => (b.onclick = async () => {
    const v = d.volumes.find((x) => x.id === b.dataset.upd);
    const r = await modal(t("inst.adjustTitle", { name: v.name }), `<div class="row2"><div><label>${t("oci.growToGb")}</label><input name="size_gb" type="number" min="${v.size_gb}" placeholder="${v.size_gb}"></div>
      <div><label>${t("inst.vpuLabel")}</label><select name="vpus_per_gb">${[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120].map((x) => `<option ${x === v.vpus_per_gb ? "selected" : ""}>${x}</option>`).join("")}</select></div></div>
      ${v.attached_to ? `<label><input type="checkbox" name="grow" style="width:auto" checked> ${t("oci.growRescan")}</label>` : ""}`,
      (bg) => post(`/accounts/${acc.id}/oci/volumes`, { op: "update", region: regionOf(acc) || undefined, volume_id: v.id, instance_id: v.attached_to, ...form(bg) }), t("inst.submit"));
    if (r) { toast(r.grow ? t("oci.growSubmitted", { s: r.grow.status === "ok" ? t("oci.rescanned") : r.grow.message }) : t("inst.submitted")); reload(); }
  }));
}

// ---------- 18. OCI 对象存储 ----------
export async function tabOciObjects(acc, box, bucket, prefix = "") {
  const reload = () => tabOciObjects(acc, box, bucket, prefix);
  if (!bucket) {
    box.innerHTML = `<div class="bar">${await regionSelect(acc, () => tabOciObjects(acc, box))}<button class="btn" id="rf">${t("common.refresh")}</button><button class="btn primary" id="nb">${t("oci.newBucket")}</button><span class="grow"></span><span class="muted" id="ns"></span></div><div id="bkCard" class="card"><span class="spin"></span> ${t("oci.bkLoading")}</div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
    billingKeepCard(acc, $("#bkCard", box));
    $("#rf", box).onclick = reload;
    let d;
    try { d = await api(`/accounts/${acc.id}/oci/buckets?${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
    $("#ns", box).textContent = t("oci.nsLine", { ns: d.namespace, n: d.free_gb });
    $("#lb", box).innerHTML = `<div class="card"><table id="bkList"><tr><th>Bucket</th><th>${t("inst.size")}</th><th>${t("oci.colCount")}</th><th>${t("oci.colTier")}</th><th>${t("inst.colCreated")}</th><th></th></tr>${d.buckets.map((b) => `<tr><td><a href="javascript:void 0" data-open="${esc(b.name)}">📁 ${esc(b.name)}</a></td>
      <td${b.error ? ` title="${esc(b.error)}"` : ""}>${b.size == null ? "—" : fmtBytes(b.size)}</td><td>${b.count == null ? "—" : esc(b.count)}</td><td>${tierLabel(b)}</td><td class="mono">${esc(b.created)}</td>
      <td><button class="btn sm" data-open="${esc(b.name)}">${t("oci.open")}</button> <button class="btn sm danger" data-delb="${esc(b.name)}">${t("common.delete")}</button></td></tr>`).join("") || `<tr><td colspan=6 class="muted">${t("oci.noBuckets")}</td></tr>`}</table>
      ${d.buckets.length ? `<p class="muted">${t("oci.bucketNote")}</p>` : ""}</div>`;
    $("#nb", box).onclick = async () => {
      const r = await modal(t("oci.newBucket"), `<label>${t("oci.bucketName")}</label><input name="name" placeholder="backup">
        <label><input type="checkbox" name="public" style="width:auto"> ${t("oci.bucketPublic")}</label>`, (bg) => post(`/accounts/${acc.id}/oci/buckets`, { op: "create", region: regionOf(acc) || undefined, ...form(bg) }), t("oci.create"));
      if (r) { toast(t("oci.created")); reload(); }
    };
    box.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => tabOciObjects(acc, box, b.dataset.open)));
    box.querySelectorAll("[data-delb]").forEach((b) => (b.onclick = async () => {
      if (await confirmBox(t("oci.delBucket"), t("oci.delBucketConfirm", { name: esc(b.dataset.delb) }), true) && await act(b, () => post(`/accounts/${acc.id}/oci/buckets`, { op: "delete", region: regionOf(acc) || undefined, name: b.dataset.delb, confirm: true }), t("common.deleted"))) reload();
    }));
    return;
  }
  box.innerHTML = `<div class="bar"><button class="btn" id="back">${t("oci.bucketList")}</button><b class="mono">${esc(bucket)}/${esc(prefix)}</b><span class="grow"></span>
    <label class="btn primary" style="margin:0">${t("oci.upload")}<input type="file" id="up" multiple style="display:none"></label><button class="btn" id="rf">${t("common.refresh")}</button></div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
  $("#back", box).onclick = () => (prefix ? tabOciObjects(acc, box, bucket, prefix.replace(/[^/]+\/$/, "")) : tabOciObjects(acc, box));
  $("#rf", box).onclick = reload;
  $("#up", box).onchange = async (e) => {
    for (const f of e.target.files) {
      if (f.size > 100 * 1024 * 1024) { toast(t("oci.tooBig", { name: f.name }), true); continue; }
      toast(t("oci.uploading", { name: f.name }));
      const r = await fetch(`/api/accounts/${acc.id}/oci/objects?bucket=${encodeURIComponent(bucket)}&name=${encodeURIComponent(prefix + f.name)}&${rq(acc)}`, { method: "PUT", body: f, credentials: "same-origin" });
      if (!r.ok) { const j = await r.json().catch(() => ({})); toast(`${f.name}：${j.detail || r.statusText}`, true); } else toast(t("oci.uploaded", { name: f.name }));
    }
    reload();
  };
  let d;
  try { d = await api(`/accounts/${acc.id}/oci/objects?bucket=${encodeURIComponent(bucket)}&prefix=${encodeURIComponent(prefix)}&${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#lb", box).innerHTML = `<div class="card"><table><tr><th>${t("acc.colName")}</th><th>${t("inst.size")}</th><th>${t("oci.colUploaded")}</th><th></th></tr>
    ${d.prefixes.map((p) => `<tr><td><a href="javascript:void 0" data-dir="${esc(p)}">📁 ${esc(p.slice(prefix.length))}</a></td><td>-</td><td>-</td><td></td></tr>`).join("")}
    ${d.objects.filter((o) => o.name !== prefix).map((o) => `<tr><td class="mono">${esc(o.name.slice(prefix.length))}</td><td>${fmtBytes(o.size)}</td><td class="mono">${esc(o.created)}</td>
      <td><button class="btn sm" data-dl="${esc(o.name)}">${t("oci.dlLink")}</button> <button class="btn sm danger" data-delo="${esc(o.name)}">${t("common.delete")}</button></td></tr>`).join("")}
    ${!d.prefixes.length && !d.objects.length ? `<tr><td colspan=4 class="muted">${t("oci.empty")}</td></tr>` : ""}</table>${d.next ? `<p class="muted">${t("oci.only200")}</p>` : ""}</div>`;
  box.querySelectorAll("[data-dir]").forEach((b) => (b.onclick = () => tabOciObjects(acc, box, bucket, b.dataset.dir)));
  box.querySelectorAll("[data-dl]").forEach((b) => (b.onclick = async () => {
    const r = await act(b, () => post(`/accounts/${acc.id}/oci/objects`, { op: "url", region: regionOf(acc) || undefined, bucket, name: b.dataset.dl, minutes: 60 }));
    if (r) modal(t("oci.dlLink"), `<p class="muted">${t("oci.dlNote", { exp: esc(r.expires) })}</p><input readonly value="${esc(r.url)}" onclick="this.select()"><div class="bar"><a class="btn primary" href="${esc(r.url)}" target="_blank" rel="noopener">${t("oci.open")}</a></div>`, null, t("common.close"));
  }));
  box.querySelectorAll("[data-delo]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox(t("oci.delObject"), t("oci.delObjConfirm", { name: esc(b.dataset.delo) }), true) && await act(b, () => post(`/accounts/${acc.id}/oci/objects`, { op: "delete", region: regionOf(acc) || undefined, bucket, name: b.dataset.delo }), t("common.deleted"))) reload();
  }));
}

// ---------- 18b. 保号账单（仅 PAYG 升级号）：先检测已有存储（所有已订阅区域的 Bucket），标准层补足到约 11 GB，超出 10 GB 免费额度，每月约 $0.02–0.03 ----------
export const BK_TITLE = "oci.bkTitle";
const gib = (n) => `${((+n || 0) / 1024 ** 3).toFixed(2)} GiB`;
const gb1 = (v) => `${(+v || 0).toFixed(2)} GB`;
export function tierLabel(b) {
  const tv = b.tier || (b.storage_tier === "Archive" ? "archive" : b.storage_tier === "Standard" ? (b.auto_tiering && b.auto_tiering !== "Disabled" ? "autotier" : "standard") : "unknown");
  return { standard: t("oci.tierStd"), autotier: `${t("oci.tierStd")} <span class="badge pending" title="${t("oci.tierAutoTitle")}">${t("oci.tierAuto")}</span>`, archive: t("oci.tierArchive"), unknown: "—" }[tv] || "—";
}
// 补足大小：11 − 已用，向上取 0.1，最小 0.5（与后端 fill_size_gb 一致）
export function bkFill(used, target = 11) { return Math.max(0.5, Math.ceil(Math.round((target - (+used || 0)) * 1e6) / 1e5) / 10); }
function bkScanHtml(s) {
  const head = `<div>${t("oci.bkHead", { used: `<span id="bkStd">${gb1(s.standard_gb)}</span>`, free: s.free_gb })} <span class="muted">${t("oci.bkHeadMeta", { r: s.regions.length, b: s.buckets.length, cached: s.cached ? t("oci.bkCached", { m: Math.round(s.age / 60) }) : "" })}</span>
    <button class="btn sm" id="bkRescan">${t("oci.bkRescan")}</button></div>`;
  const verdict = s.over_free
    ? `<p id="bkVerdict" class="al warn">${t("oci.bkOver")}</p>`
    : `<p id="bkVerdict" class="al">${t("oci.bkUnder", { short: s.short_gb, fill: s.fill_gb, total: (s.standard_gb + s.fill_gb).toFixed(2) })}</p>`;
  const extra = [s.autotier_gb > 0 ? t("oci.bkExtraAuto", { x: gb1(s.autotier_gb) }) : "",
    s.archive_gb > 0 ? t("oci.bkExtraArch", { x: gb1(s.archive_gb) }) : "",
    s.unknown_count ? t("oci.bkExtraUnknown", { n: s.unknown_count }) : "",
    (s.errors || []).length ? t("oci.bkExtraErr", { regions: s.errors.map((e) => esc(e.region)).join("、") }) : "",
    s.compartments_truncated ? t("oci.bkExtraTrunc", { n: s.compartments }) : ""].filter(Boolean);
  const rows = s.buckets.map((b) => `<tr><td class="mono">${esc(b.name)}${b.billing_keep ? ` <span class="badge">${t("oci.bkBadge")}</span>` : ""}</td><td class="mono">${esc(regionLabel(b.region))}</td><td>${tierLabel(b)}</td>
    <td>${b.size == null ? "—" : fmtBytes(b.size)}</td><td>${b.count == null ? "—" : esc(b.count)}</td></tr>`).join("");
  return head + verdict + (extra.length ? `<p class="muted">${extra.join("；")}。</p>` : "")
    + (rows ? `<details id="bkBuckets"><summary>${t("oci.bkExisting", { n: s.buckets.length })}</summary><table><tr><th>Bucket</th><th>${t("core.region.title")}</th><th>${t("oci.colTier")}</th><th>${t("inst.size")}</th><th>${t("oci.colCount")}</th></tr>${rows}</table></details>` : `<p class="muted">${t("oci.bkNone")}</p>`)
    + `<p class="muted">${t("oci.bkApprox")}</p>`;
}
export async function billingKeepCard(acc, el, again, rescan) {
  if (!el || !el.isConnected) return;
  const reload = (rs) => billingKeepCard(acc, el, true, rs);
  let d;
  try { d = await api(`/accounts/${acc.id}/oci/billing-keep`); } catch (e) { el.innerHTML = `<h3>${t(BK_TITLE)}</h3><div>❌ ${esc(e.message)}</div>`; return; }
  if (!el.isConnected) return;
  const tk = d.task, running = tk && tk.status === "running";
  const head = `<h3>${t(BK_TITLE)} <span class="badge">${d.plan === "paid" ? "PAYG" : d.plan === "free" ? t("oci.planFree") : t("oci.planUnknown")}</span></h3>`;
  if (!d.eligible) { el.innerHTML = `${head}<p class="muted" id="bkHint">${esc(d.hint || "")}</p>`; return; }
  let body = `<p class="muted" id="bkNote">${esc(d.note)}</p>`;
  if (running) {
    const pct = tk.total ? Math.floor((tk.uploaded * 100) / tk.total) : 0;
    body += `<div id="bkProg"><progress max="100" value="${pct}" style="width:100%"></progress>
      <div>${t("oci.bkUploading", { up: gib(tk.uploaded), tot: gib(tk.total), pct })} · <a href="javascript:void 0" id="bkTask">${t("oci.bkTaskLink", { id: tk.id })}</a></div></div>`;
    el.innerHTML = head + body;
    const tl = $("#bkTask", el); if (tl) tl.onclick = () => window.TaskDrawer && window.TaskDrawer.open(tk.id);
    el.dataset.wasRunning = "1";
    setTimeout(() => billingKeepCard(acc, el, true), again ? 3000 : 2000);
    return;
  }
  // 先检测已有存储（上传刚结束或点了「重新检测」时跳过 5 分钟缓存）
  const fresh = rescan || el.dataset.wasRunning === "1";
  delete el.dataset.wasRunning;
  el.innerHTML = head + body + `<div id="bkScan"><span class="spin"></span> ${t("oci.bkScanning")}</div>`;
  let s = null, scanErr = "";
  try { s = await api(`/accounts/${acc.id}/oci/billing-keep/scan${fresh ? "?refresh=true" : ""}`); } catch (e) { scanErr = e.message; }
  if (!el.isConnected) return;
  const scanHtml = s ? bkScanHtml(s) : `<p class="al warn">${t("oci.bkScanFail", { msg: esc(scanErr), n: d.default_gb })}</p><button class="btn sm" id="bkRescan">${t("oci.bkRescan")}</button>`;
  const over = !!(s && s.over_free), used = s ? +s.standard_gb : 0, defGb = s ? s.fill_gb : d.default_gb;
  if (d.exists) {
    body += `<div id="bkDone">${t("oci.bkExists", { path: `${esc(d.bucket)}/${esc(d.object)}`, size: gib(d.size), region: esc(regionLabel(d.region)), tier: esc(d.storage_tier || "Standard") })}</div>
      <div id="bkScan">${scanHtml}</div><div class="bar"><button class="btn danger" id="bkDel">${t("common.delete")}</button></div>`;
  } else {
    const pend = (d.pending_uploads || []).length, resumable = pend && t && ["failed", "stopped", "interrupted"].includes(tk.status) && tk.uploaded;
    body += `<div id="bkScan">${scanHtml}</div>` + (tk && tk.status !== "done" ? `<p class="muted">${t("oci.bkLastTask", { id: tk.id, status: esc(tk.status), msg: esc(tk.message || "") })}</p>` : "")
      + `<div class="bar"><label style="margin:0">${t("oci.bkSize")}</label><input id="bkSize" type="number" step="0.1" min="${d.min_gb}" max="${d.max_gb}" value="${defGb}" style="width:6em">
      <button class="btn ${over ? "" : "primary"}" id="bkGo">${resumable ? t("oci.bkResume", { x: gib(tk.uploaded) }) : over ? t("oci.bkGoOver") : t("oci.bkGo")}</button>
      ${pend ? `<button class="btn danger" id="bkDel">${t("oci.bkDelPend")}</button>` : ""}<span class="muted" id="bkAfter"></span></div>`;
  }
  el.innerHTML = head + body;
  const rs = $("#bkRescan", el); if (rs) rs.onclick = () => reload(true);
  const sz = $("#bkSize", el), after = $("#bkAfter", el);
  const upd = () => { if (after && s) after.textContent = t("oci.bkAfter", { x: (used + (+sz.value || 0)).toFixed(2) }); };
  if (sz) { sz.addEventListener("input", upd); upd(); }
  const go = $("#bkGo", el);
  if (go) go.onclick = async () => {
    const size = +sz.value || defGb;
    if (!(size >= d.min_gb && size <= d.max_gb)) { toast(t("oci.bkRange", { min: d.min_gb, max: d.max_gb }), true); return; }
    if (over && !(await confirmBox(t("oci.bkNoNeed"), t("oci.bkNoNeedMsg", { used: gb1(used) }), true))) return;
    const tot = s ? t("oci.bkConfirmTot", { x: (used + size).toFixed(2) }) : "";
    if (!(await confirmBox(t(BK_TITLE), `${esc(d.note)}<br><br>${t("oci.bkConfirm", { size, tot })}`))) return;
    const r = await act(go, () => post(`/accounts/${acc.id}/oci/billing-keep`, { size_gb: size, confirm: true }));
    if (r) { if (r.existed) toast(t("oci.bkExistedToast", { size: gib(r.size) })); reload(); }
  };
  const dl = $("#bkDel", el);
  if (dl) dl.onclick = async () => {
    if (!(await confirmBox(t("oci.bkDelTitle"), t("oci.bkDelConfirm"), true))) return;
    if (await act(dl, () => del(`/accounts/${acc.id}/oci/billing-keep?confirm=true`), t("common.deleted"))) reload(true);
  };
}

// ---------- OCI 流量：本区域实例本月出站 / 入站（OCI Monitoring，免费） ----------
export async function tabOciTraffic(acc, box) {
  const reload = () => tabOciTraffic(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">${t("common.refresh")}</button><span class="grow"></span><span class="muted" id="pd"></span></div><div id="lb"><div class="card"><span class="spin"></span> ${t("oci.trafLoading")}</div></div>`;
  $("#rf", box).onclick = reload;
  let d, gs = [];
  try { gs = (await api("/traffic-guards")).filter((g) => g.account_id === acc.id); } catch (_) { /* ignore */ }
  try { d = await api(`/accounts/${acc.id}/oci/traffic-summary?${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#pd", box).textContent = t("oci.trafPeriod", { period: d.period });
  const pct = d.free_out_gb ? Math.min(100, (d.out_gb / d.free_out_gb) * 100) : 0;
  const gb = (v) => (v == null ? "-" : v >= 1024 ? `${(v / 1024).toFixed(2)} TB` : `${(+v).toFixed(2)} GB`);
  $("#lb", box).innerHTML = `<div class="card"><p>${t("oci.trafSummary", { out: gb(d.out_gb), free: gb(d.free_out_gb), pct: pct.toFixed(pct < 1 ? 2 : 1), inn: gb(d.in_gb) })}</p>
      <div class="meter"><i style="width:${pct}%" class="${pct >= 100 ? "bad" : pct >= 80 ? "warn" : ""}"></i></div>
      <p class="muted">${t("oci.trafNote2")}</p></div>
    <div class="card"><table><tr><th>${t("oci.colInst")}</th><th>${t("common.status")}</th><th>${t("inst.colPublic")}</th><th>${t("oci.colOut")}</th><th>${t("oci.colIn")}</th><th>${t("oci.colGuard")}</th><th></th></tr>
    ${d.items.map((r, i) => `<tr><td>${esc(r.name)}<div class="muted mono" style="font-size:11px">${esc(r.shape || "")}</div></td><td>${esc(r.state || "")}</td><td class="mono">${esc(r.public_ip || "-")}</td>
      <td>${r.error ? `<span class="muted" title="${esc(r.error)}">${t("oci.readFail")}</span>` : `<b>${gb(r.out_gb)}</b>`}</td><td>${r.error ? "-" : gb(r.in_gb)}</td>
      <td>${guardCell(gs.find((g) => g.instance_id === r.id))}</td>
      <td>${(() => { const g = gs.find((x) => x.instance_id === r.id); return g ? `<button class="btn sm" data-tg="${i}">${t("common.edit")}</button> <button class="btn sm" data-tgag="${g.id}">agent</button> <button class="btn sm" data-tgpt="${g.id}">${t("traf.ports")}</button> <button class="btn sm" data-tgchk="${g.id}">${t("oci.checkNow")}</button> <button class="btn sm danger" data-tgdel="${g.id}">${t("common.delete")}</button>` : `<button class="btn sm" data-tg="${i}">${t("oci.setGuard")}</button>`; })()}</td></tr>`).join("") || `<tr><td colspan=7 class="muted">${t("oci.noInst")}</td></tr>`}</table></div>`;
  box.querySelectorAll("[data-tg]").forEach((b) => (b.onclick = () => trafficDialog(acc, d.items[+b.dataset.tg], "vm", reload)));
  box.querySelectorAll("[data-tgchk]").forEach((b) => (b.onclick = () => act(b, () => post(`/traffic-guards/${b.dataset.tgchk}/check`), t("oci.checked")).then(reload)));
  box.querySelectorAll("[data-tgag]").forEach((b) => (b.onclick = () => guardAgentDialog(gs.find((g) => g.id == b.dataset.tgag), reload)));
  box.querySelectorAll("[data-tgpt]").forEach((b) => (b.onclick = () => guardPortsDialog(gs.find((g) => g.id == b.dataset.tgpt))));
  box.querySelectorAll("[data-tgdel]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox(t("traf.delTitle"), t("oci.tgDelConfirm"), true)) act(b, () => api(`/traffic-guards/${b.dataset.tgdel}`, { method: "DELETE" }), t("common.deleted")).then(reload);
  }));
}
export function guardCell(g) {
  if (!g) return `<span class="muted">${t("oci.notSet")}</span>`;
  const st = `<span class="badge ${GST[g.status] || ""}">${esc(g.enabled ? g.status_text || t("oci.normal") : t("oci.closed"))}</span>`;
  return `${st} <span class="muted">${g.last_gb ?? "-"} / ${g.limit_gb} GB${g.action === "stop" ? t("oci.gcStop") : g.action === "throttle" ? t("oci.gcThrottle", { n: g.throttle_mbps }) : t("oci.gcNotify")}${g.acct_enabled ? t("oci.gcAcct") : ""}</span>`;
}

// ---------- 7. OCI 区域订阅（v1.6 build 18：不再单独占标签，收在「配额/网络」页底部默认折叠的「高级」区，展开才加载） ----------
// 订阅不可撤销：确认框之后还要手动输入区域标识（如 ap-osaka-1）才能提交，防止误点
export const REGION_SUB_TITLE = "oci.rsTitle";
export function regionSubSection(acc) {
  const el = document.createElement("details");
  el.className = "card rsadv"; el.id = "rsAdv";
  el.innerHTML = `<summary>${t(REGION_SUB_TITLE)}</summary><div id="rsBody"><p class="muted">${t("oci.rsHint")}</p></div>`;
  let loaded = false;
  el.addEventListener("toggle", () => { if (el.open && !loaded) { loaded = true; tabOciRegionSub(acc, el.querySelector("#rsBody")); } });
  return el;
}
export function typeKeyConfirm(name, key) {
  // 必须手动输入完整的区域标识（如 ap-osaka-1，即列表里的「区域」列），一致后「确认订阅」才可点
  return modal(t("oci.rsConfirmTitle"), `<p>${t("oci.rsConfirmBody", { name: esc(name), key: esc(key) })}</p>
    <input name="rskey" id="rsKey" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${esc(name)}">`,
  (bg) => {
    if (bg.querySelector("#rsKey").value.trim() !== name) { toast(t("oci.rsMismatch"), true); return false; }
    return true;
  }, t("oci.rsGo"), true, (bg) => {
    const ok = bg.querySelector("[data-ok]"), inp = bg.querySelector("#rsKey");
    ok.disabled = true;
    inp.addEventListener("input", () => { ok.disabled = inp.value.trim() !== name; });
    setTimeout(() => inp.focus());
  });
}
export async function tabOciRegionSub(acc, box) {
  const reload = () => tabOciRegionSub(acc, box);
  box.innerHTML = `<div><span class="spin"></span></div>`;
  let d;
  try { d = await api(`/accounts/${acc.id}/oci/region-subscriptions`); } catch (e) { box.innerHTML = `<div>❌ ${esc(e.message)}</div>`; return; }
  const subd = d.regions.filter((r) => r.subscribed);
  box.innerHTML = `<h3>${t("oci.rsHead", { n: subd.length, home: esc(d.home || "-") })}</h3>
    <p class="muted">${t("oci.rsNote", { hint: esc(d.limit_hint) })}</p>
    <table><tr><th>${t("core.region.title")}</th><th>Key</th><th>${t("common.status")}</th><th></th></tr>${d.regions.map((r) => `<tr><td>${esc(regionLabel(r.name))}${r.home ? ` <span class="badge done">${t("oci.homeBadge")}</span>` : ""}</td><td class="mono">${esc(r.key)}</td>
      <td>${r.subscribed ? esc(r.status || t("oci.subscribed")) : `<span class="muted">${t("oci.notSub")}</span>`}</td><td>${r.subscribed ? "" : `<button class="btn sm danger" data-sub="${esc(r.key)}" data-n="${esc(r.name)}">${t("oci.subscribe")}</button>`}</td></tr>`).join("")}</table>`;
  box.querySelectorAll("[data-sub]").forEach((b) => (b.onclick = async () => {
    if (!(await confirmBox(t("oci.subTitle"), t("oci.subConfirm", { name: esc(b.dataset.n), key: esc(b.dataset.sub) }), true))) return;
    if (!(await typeKeyConfirm(b.dataset.n, b.dataset.sub))) return;
    if (await act(b, () => post(`/accounts/${acc.id}/oci/region-subscriptions`, { region_key: b.dataset.sub, confirm: true }), (r) => t("oci.subSubmitted", { region: r.region, status: r.status }))) reload();
  }));
}

// ---------- 20. 免费额度体检 ----------
export async function pageFreeCheck() {
  loading();
  const list = await api("/oci/free-check");
  const bar = (v, max) => `<span class="${v > max ? "bad" : ""}">${v ?? "-"} / ${max}</span>`;
  view.innerHTML = `<div class="card"><p class="muted">${t("oci.fcIntro")}</p>
    <table><tr><th>${t("oci.colAccount")}</th><th>A1 OCPU</th><th>${t("oci.fcMem")}</th><th>${t("oci.fcMicro")}</th><th>${t("oci.fcStorage")}</th><th>${t("oci.fcVerdict")}</th></tr>
    ${list.map((r) => r.error ? `<tr><td>${esc(r.name)}</td><td colspan=5 class="muted">❌ ${esc(r.error)}</td></tr>` : `<tr><td><a href="#/oci/${r.account_id}">${esc(r.name)}</a></td>
      <td>${bar(r.a1.ocpus, r.a1.limit_ocpus)}</td><td>${bar(r.a1.memory_gb, r.a1.limit_mem)}</td><td>${bar(r.micro.count, r.micro.limit)}</td><td>${bar(r.storage.used_gb, r.storage.limit)}</td>
      <td>${r.ok ? `<span class="badge done">${t("oci.fcOk")}</span>` : r.issues.map((x) => `<div class="bad">${esc(x)}</div>`).join("")}
      ${r.suggestions.map((s) => `<div class="muted">${t("oci.fcSugg", { name: esc(s.name), o: s.ocpus, m: s.memory_gb, tail: s.delete ? t("oci.fcDel") : `${s.to_ocpus}C/${s.to_memory_gb}G` })}
        ${s.delete ? "" : `<button class="btn sm" data-down='${esc(JSON.stringify({ acc: r.account_id, ...s }))}'>${t("oci.fcDown")}</button>`}</div>`).join("")}</td></tr>`).join("") || `<tr><td colspan=6 class="muted">${t("oci.fcNone")}</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-down]").forEach((b) => (b.onclick = async () => {
    const s = JSON.parse(b.dataset.down);
    if (!(await confirmBox(t("oci.fcDown"), t("oci.fcDownConfirm", { name: esc(s.name), o: s.ocpus, m: s.memory_gb, to_o: s.to_ocpus, to_m: s.to_memory_gb })))) return;
    act(b, () => post(`/accounts/${s.acc}/instances/resize`, { instance_id: s.id, name: s.name, ocpus: s.to_ocpus, memory_gb: s.to_memory_gb, confirm_overage: true }), (r) => t("inst.taskCreatedShort", { id: r.task_id }));
  }));
}
