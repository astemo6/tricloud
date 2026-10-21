// TriCloud 前端 v1.6.0 · 监控、流量守护、账号健康度
import { t } from "./i18n.js";
import { $, ACCOUNTS, act, api, confirmBox, del, esc, loading, post, view } from "./core.js";
import { agentLine, guardAgentDialog, guardPortsDialog } from "./guard.js";
import { trafficDialog } from "./instances.js";

// ---------------- 监控 ----------------
export async function pageMonitors() {
  loading();
  const [list, usage] = await Promise.all([api("/monitors"), api("/ip-change-usage").catch(() => [])]);
  const used = usage.filter((u) => u.auto_used || u.manual_used || list.some((m) => m.account_id === u.account_id && m.auto_change_ip));
  view.innerHTML = `${used.length ? `<div class="card"><h3>${t("mon.todayTitle")}</h3><div class="chips">${used.map((u) => `<span class="chip"><span class="dot ${u.provider}"></span>${esc(u.name)}
    · ${t("mon.auto")} <b>${u.auto_used}/${u.limit}</b> · ${t("mon.manual")} ${u.manual_used}</span>`).join("")}</div>
    <p class="muted">${t("mon.note", { n: used[0].limit })}</p></div>` : ""}
  <div class="card"><p class="muted">${t("mon.hint")}</p>
    <table><tr><th>${t("mon.col.instance")}</th><th>${t("common.account")}</th><th>${t("mon.col.lastState")}</th><th>${t("mon.col.autoStart")}</th><th>${t("mon.col.check")}</th><th></th></tr>
    ${list.map((m) => `<tr><td>${esc(m.name)}<div class="muted mono">${esc(m.instance_id).slice(-24)}</div></td><td>${esc(m.account_name)}</td>
    <td>${esc(m.last_state || "-")}</td><td>${m.auto_start ? "✅" : "—"}</td>
    <td>${m.check_port ? `${esc(m.public_ip || "-")}:${m.check_port}${m.auto_change_ip ? t("mon.autoChange") : ""}${m.fail_count ? t("mon.failCount", { n: m.fail_count }) : ""}` : "—"}</td>
    <td><button class="btn sm danger" data-del="${m.id}">${t("common.remove")}</button></td></tr>`).join("") || `<tr><td colspan=6 class="muted">${t("common.none")}</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (!(await confirmBox(t("mon.removeTitle"), t("mon.removeConfirm"), true))) return; if (await act(b, () => del(`/monitors/${b.dataset.del}`), t("common.removed"))) pageMonitors(); }));
}

// ================= v1.2 新增 =================
export const HL = { good: "health.lv.good", warn: "health.lv.warn", bad: "health.lv.bad" };
export async function pageHealth() {
  loading();
  const list = await api("/account-health");
  const fmt = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : t("health.never"));
  view.innerHTML = `<div class="bar"><button class="btn primary" id="all">${t("health.refreshAll")}</button>
    <span class="muted">${t("health.note")}</span></div>
    <div class="grid">${list.map((h) => `<div class="card"><div class="inst"><div class="hd"><span class="dot ${h.provider}"></span><b>${esc(h.name)}</b>
      ${h.score == null ? `<span class="badge">${t("common.unchecked")}</span>` : `<span class="hs big2 ${h.level}">${h.score}</span>`}</div>
      ${h.items.length ? `<div class="hitems">${h.items.map((i) => `<div class="hi ${i.ok ? "ok" : "bad"}"><span>${i.ok ? "✓" : "!"}</span>
        <div><b>${esc(i.name)}</b>${i.penalty ? ` <span class="muted">-${i.penalty}</span>` : ""}<div class="muted">${esc(i.detail)}</div></div></div>`).join("")}</div>`
        : `<p class="muted">${t("health.noRecord")}</p>`}
      <div class="ops"><span class="muted grow">${h.level ? t(HL[h.level]) + " · " : ""}${t("health.checkedAt", { t: fmt(h.checked_at) })}</span>
      <button class="btn sm" data-chk="${h.account_id}">${t("health.checkBtn")}</button></div></div></div>`).join("")}</div>`;
  $("#all").onclick = (e) => act(e.target, () => post("/account-health/refresh", {}), t("health.done")).then(pageHealth);
  view.querySelectorAll("[data-chk]").forEach((b) => (b.onclick = () =>
    act(b, () => post("/account-health/refresh", { account_id: +b.dataset.chk }), t("health.done")).then(pageHealth)));
}

export const GST = { ok: "running", warn: "pending", over: "failed", tripped: "stopped", resume_failed: "failed", disabled: "", throttled: "pending" };
export async function pageTraffic() {
  loading();
  const list = await api("/traffic-guards");
  const fmt = (t) => (t ? new Date(t * 1000).toLocaleString() : "-");
  const actText = (g) => g.action === "throttle" ? t("traf.throttle", { n: g.throttle_mbps }) : g.action !== "stop" ? t("traf.notifyOnly") : g.shutdown_hours > 0 ? t("traf.stopHours", { n: g.shutdown_hours }) : t("traf.stopAuto");
  view.innerHTML = `<div class="card"><p class="muted">${t("traf.intro")}</p>
    ${list.length ? `<table><tr><th>${t("mon.col.instance")}</th><th>${t("common.account")}</th><th>${t("traf.col.stats")}</th><th>${t("traf.col.usage")}</th><th>${t("traf.col.limit")}</th><th>${t("traf.col.onLimit")}</th><th>${t("common.status")}</th><th>${t("traf.col.enabled")}</th><th>${t("traf.col.checkedAt")}</th><th></th></tr>
    ${list.map((g) => `<tr data-g="${g.id}"><td>${esc(g.name || g.instance_id.slice(-12))}</td><td><span class="dot ${g.provider}"></span>${esc(g.account_name || "-")}</td>
      <td>${esc(g.scope || t("traf.scopeDefault"))}</td>
      <td><div class="meter"><i style="width:${Math.min(100, g.last_pct || 0)}%" class="${(g.last_pct || 0) >= 100 ? "bad" : (g.last_pct || 0) >= g.warn_pct ? "warn" : ""}"></i></div>
        ${g.last_gb ?? "-"} GB · ${g.last_pct ?? "-"}%</td><td>${g.limit_gb} GB</td><td>${actText(g)}${g.agent ? `<div>${agentLine(g.agent, g)}</div>` : ""}</td>
      <td><span class="badge ${GST[g.status] || ""}">${esc(g.status_text || t("traf.normal"))}</span>${g.resume_at_text ? `<div class="muted">${t("traf.resumeAt", { t: esc(g.resume_at_text) })}</div>` : g.state_msg && g.status !== "ok" ? `<div class="muted">${esc(g.state_msg)}</div>` : ""}</td>
      <td><label class="switch"><input type="checkbox" data-en="${g.id}" ${g.enabled ? "checked" : ""}><span></span></label></td>
      <td>${fmt(g.checked_at)}</td><td><button class="btn sm" data-chk="${g.id}">${t("traf.checkNow")}</button> <button class="btn sm" data-ed="${g.id}">${t("common.edit")}</button>
      <button class="btn sm" data-ag="${g.id}">agent</button> <button class="btn sm" data-pt="${g.id}">${t("traf.ports")}</button>${g.throttled ? ` <button class="btn sm" data-rt="${g.id}">${t("traf.release")}</button>` : ""}
      ${g.resume_at ? `<button class="btn sm" data-cr="${g.id}">${t("traf.cancelResume")}</button>` : ""}${["tripped", "resume_failed"].includes(g.status) ? ` <button class="btn sm" data-rs="${g.id}">${t("traf.clearState")}</button>` : ""}
      <button class="btn sm danger" data-del="${g.id}">${t("common.delete")}</button></td></tr>`).join("")}</table>`
    : `<div class="empty">${t("traf.empty")}</div>`}</div>`;
  view.querySelectorAll("[data-chk]").forEach((b) => (b.onclick = () => act(b, () => post(`/traffic-guards/${b.dataset.chk}/check`), t("traf.checked")).then(pageTraffic)));
  view.querySelectorAll("[data-en]").forEach((b) => (b.onchange = () => act(null, () => api(`/traffic-guards/${b.dataset.en}`, { method: "PATCH", body: { enabled: b.checked } }), b.checked ? t("common.enabled") : t("common.disabled")).then(pageTraffic)));
  view.querySelectorAll("[data-cr]").forEach((b) => (b.onclick = () => act(b, () => api(`/traffic-guards/${b.dataset.cr}`, { method: "PATCH", body: { cancel_resume: true } }), t("traf.resumeCancelled")).then(pageTraffic)));
  view.querySelectorAll("[data-ag]").forEach((b) => (b.onclick = () => guardAgentDialog(list.find((x) => x.id == b.dataset.ag), pageTraffic)));
  view.querySelectorAll("[data-pt]").forEach((b) => (b.onclick = () => guardPortsDialog(list.find((x) => x.id == b.dataset.pt))));
  view.querySelectorAll("[data-rt]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox(t("traf.release"), t("traf.releaseConfirm"))) act(b, () => api(`/traffic-guards/${b.dataset.rt}`, { method: "PATCH", body: { release_throttle: true } }), t("traf.released")).then(pageTraffic);
  }));
  view.querySelectorAll("[data-rs]").forEach((b) => (b.onclick = () => act(b, () => api(`/traffic-guards/${b.dataset.rs}`, { method: "PATCH", body: { reset_state: true } }), t("traf.cleared")).then(pageTraffic)));
  view.querySelectorAll("[data-ed]").forEach((b) => (b.onclick = () => {
    const g = list.find((x) => x.id == b.dataset.ed); const acc = ACCOUNTS.find((a) => a.id === g.account_id);
    if (acc) trafficDialog(acc, { id: g.instance_id, name: g.name || g.instance_id.slice(-12), region: g.region || undefined }, g.kind || "vm", pageTraffic);
  }));
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox(t("traf.delTitle"), t("traf.delConfirm"), true)) act(b, () => api(`/traffic-guards/${b.dataset.del}`, { method: "DELETE" }), t("common.deleted")).then(pageTraffic);
  }));
}
