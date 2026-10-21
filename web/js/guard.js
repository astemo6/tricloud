// TriCloud 前端 v1.6.0 build 22 · 流量守护 agent：「推送并限速」安装 / 卸载命令、在线状态与最后心跳、重置 token、流量明细开关，
// 以及按端口 / 服务的流量明细（今日 / 本月 Top，入站 / 出站 / 合计 + 占比条）。面板不会远程执行任何命令，agent 由用户自己在机器上安装。
import { tr } from "./i18n.js";
import { $, act, api, confirmBox, esc, modal, toast } from "./core.js";

export async function copyText(text, input) {
  try { await navigator.clipboard.writeText(text); toast(tr("guard.copied")); }
  catch (_) { if (input) { input.select(); document.execCommand("copy"); toast(tr("guard.copied")); } else toast(tr("guard.copyManual"), true); }
}

const cmdRow = (label, id, v) => `<label>${esc(label)}</label><div class="bar"><input class="mono grow" id="${id}" readonly value="${esc(v)}" onclick="this.select()">
  <button class="btn sm" data-copy="${id}">${tr("common.copy")}</button></div>`;

// agent 状态一行（守护列表 / 弹窗共用）
export function agentLine(a, g) {
  if (!a) return "";
  const st = !a.installed ? `<span class="badge">${tr("guard.notInstalled")}</span>` : a.online ? `<span class="badge done">${tr("guard.online")}</span>` : `<span class="badge failed">${tr("guard.offline")}</span>`;
  const seen = a.last_seen_text ? tr("guard.lastSeen", { t: esc(a.last_seen_text) }) : "";
  const thr = g && g.action === "throttle" ? (a.applied ? tr("guard.throttledNow") : g.throttled ? tr("guard.throttlePending") : tr("guard.notThrottled")) : "";
  return `${st} <span class="muted">${seen}${thr}</span>`;
}

export async function guardAgentDialog(g, onChange) {
  let d;
  try { d = await api(`/traffic-guards/${g.id}/agent?base=${encodeURIComponent(location.origin)}`); } catch (e) { toast(e.message, true); return; }
  const a = d.agent || {};
  const be = a.acct_backend ? `${esc(a.acct_backend_text || a.acct_backend)}${a.acct_ports != null ? tr("guard.portsCount", { n: a.acct_ports }) : ""}` : tr("guard.waitAgent");
  const body = `<p>${agentLine(a, g)}</p>
    <ul class="guard">
      <li>${tr("guard.action")}${g.action === "throttle" ? tr("guard.actThrottle", { n: esc(d.throttle_mbps) }) : g.action === "stop" ? tr("guard.actStop") : tr("guard.actNotify")}</li>
      <li>${tr("guard.current")}${d.throttled ? `<b>${tr("guard.curThrottled")}</b>` : tr("guard.curNot")}${a.applied ? tr("guard.applied") : ""}${a.iface ? tr("guard.iface", { v: esc(a.iface) }) : ""}${a.ssh_ports ? tr("guard.sshPorts", { v: esc(a.ssh_ports) }) : ""}</li>
      <li>${tr("guard.acctLabel")}${a.acct_enabled ? tr("guard.acctOn", { v: be }) : tr("guard.acctOff")}</li>
    </ul>
    <label class="row-check"><input type="checkbox" id="gaAcct" style="width:auto" ${a.acct_enabled ? "checked" : ""}> ${tr("guard.acctCheck")}</label>
    ${d.commands ? `<p class="muted">${tr("guard.installNote", { m: Math.round(d.poll_secs / 60), o: Math.round(d.offline_secs / 60) })}</p>
    ${cmdRow(tr("guard.cmdInstall"), "gaIns", d.commands.install)}${cmdRow(tr("guard.cmdUninstallPanel"), "gaUn", d.commands.uninstall)}${cmdRow(tr("guard.cmdUninstallLocal"), "gaUnL", d.commands.uninstall_local)}${cmdRow(tr("guard.cmdStatus"), "gaSt", d.commands.status)}
    <p class="muted">${tr("guard.tokenNote")}</p>`
      : `<p class="muted">${tr("guard.apiTokenNote")}</p>`}
    <div class="bar" style="margin-top:8px">${d.commands ? `<button class="btn danger" id="gaReset">${tr("guard.resetToken")}</button>` : ""}<button class="btn" id="gaPorts">${tr("guard.portsBtn")}</button></div>`;
  let changed = false;
  await modal(tr("guard.agentTitle", { name: g.name || g.instance_id.slice(-12) }), body, null, tr("common.close"), false, (bg) => {
    bg.querySelectorAll("[data-copy]").forEach((b) => (b.onclick = () => { const i = bg.querySelector("#" + b.dataset.copy); copyText(i.value, i); }));
    $("#gaAcct", bg).onchange = (e) => act(null, () => api(`/traffic-guards/${g.id}`, { method: "PATCH", body: { acct_enabled: e.target.checked } }),
      e.target.checked ? tr("guard.acctOnToast") : tr("guard.acctOffToast")).then(() => { changed = true; });
    if ($("#gaReset", bg)) $("#gaReset", bg).onclick = async () => {
      if (!(await confirmBox(tr("guard.resetTitle"), tr("guard.resetConfirm"), true))) return;
      const r = await act($("#gaReset", bg), () => api(`/traffic-guards/${g.id}/agent/reset?base=${encodeURIComponent(location.origin)}`, { method: "POST", body: {} }), tr("guard.resetDone"));
      if (r) { $("#gaIns", bg).value = r.commands.install; changed = true; }
    };
    $("#gaPorts", bg).onclick = () => { bg.remove(); guardPortsDialog(g); };
  });
  if (changed && onChange) onChange();
}

export function portsTable(t, kind) {
  const rows = kind === "services" ? t.services : t.ports;
  if (!rows.length) return `<div class="empty">${tr("guard.noData", { title: esc(t.title) })}</div>`;
  return `<table class="ptable"><tr><th>${kind === "services" ? tr("guard.col.service") : tr("guard.col.portProc")}</th><th>${tr("guard.col.in")}</th><th>${tr("guard.col.out")}</th><th>${tr("guard.col.total")}</th><th style="min-width:120px">${tr("guard.col.share")}</th></tr>
    ${rows.map((r) => `<tr><td>${esc(kind === "services" ? r.service : r.label)}${kind === "services" && r.ports.length ? `<div class="muted">${esc(r.ports.join(", "))}</div>` : ""}</td>
      <td>${esc(r.in_text)}</td><td>${esc(r.out_text)}</td><td><b>${esc(r.total_text)}</b></td>
      <td><div class="meter pbar" title="${r.pct}%"><i style="width:${Math.min(100, r.pct)}%"></i></div><span class="muted">${r.pct}%</span></td></tr>`).join("")}</table>`;
}

export async function guardPortsDialog(g) {
  let rng = "today", kind = "ports";
  const load = async (bg) => {
    const box = $("#gpBody", bg);
    box.innerHTML = `<span class="spin"></span> ${tr("guard.reading")}`;
    let t;
    try { t = await api(`/traffic-guards/${g.id}/ports?range=${rng}&limit=20`); } catch (e) { box.innerHTML = `<span class="err-text">${esc(e.message)}</span>`; return; }
    const a = t.agent || {};
    box.innerHTML = `<p>${tr("guard.portsSummary", { title: esc(t.title), range: esc(t.start === t.end ? t.start : t.start + " ~ " + t.end), total: esc(t.total_text), in: esc(t.in_text), out: esc(t.out_text) })}
      ${t.updated_at ? `<span class="muted">${tr("guard.updatedAt", { t: esc(new Date(t.updated_at * 1000).toLocaleString()) })}</span>` : ""}</p>
      ${!t.acct_enabled ? `<p class="muted">${tr("guard.acctOffNote")}</p>` : !a.installed ? `<p class="muted">${tr("guard.agentPending")}</p>` : ""}
      ${portsTable(t, kind)}
      <p class="muted">${tr("guard.otherNote", { d: t.retain_days })}</p>`;
  };
  await modal(tr("guard.portsTitle", { name: g.name || g.instance_id.slice(-12) }), `<div class="bar"><div class="seg" id="gpRng"><button data-r="today" class="on">${tr("guard.rngToday")}</button><button data-r="month">${tr("guard.rngMonth")}</button></div>
      <div class="seg" id="gpKind"><button data-k="ports" class="on">${tr("guard.kindPorts")}</button><button data-k="services">${tr("guard.kindServices")}</button></div></div><div id="gpBody" style="margin-top:12px"></div>`,
  null, tr("common.close"), false, (bg) => {
    bg.querySelector(".modal").classList.add("wide");
    bg.querySelectorAll("#gpRng button").forEach((b) => (b.onclick = () => { rng = b.dataset.r; bg.querySelectorAll("#gpRng button").forEach((x) => x.classList.toggle("on", x === b)); load(bg); }));
    bg.querySelectorAll("#gpKind button").forEach((b) => (b.onclick = () => { kind = b.dataset.k; bg.querySelectorAll("#gpKind button").forEach((x) => x.classList.toggle("on", x === b)); load(bg); }));
    load(bg);
  });
}
