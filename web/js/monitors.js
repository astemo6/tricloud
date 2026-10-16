// TriCloud 前端 v1.6.0 · 监控、流量守护、账号健康度
import { $, ACCOUNTS, act, api, confirmBox, del, esc, loading, post, view } from "./core.js";
import { agentLine, guardAgentDialog, guardPortsDialog } from "./guard.js";
import { trafficDialog } from "./instances.js";

// ---------------- 监控 ----------------
export async function pageMonitors() {
  loading();
  const [list, usage] = await Promise.all([api("/monitors"), api("/ip-change-usage").catch(() => [])]);
  const used = usage.filter((u) => u.auto_used || u.manual_used || list.some((m) => m.account_id === u.account_id && m.auto_change_ip));
  view.innerHTML = `${used.length ? `<div class="card"><h3>今日换 IP 次数</h3><div class="chips">${used.map((u) => `<span class="chip"><span class="dot ${u.provider}"></span>${esc(u.name)}
    · 自动 <b>${u.auto_used}/${u.limit}</b> · 手动 ${u.manual_used}</span>`).join("")}</div>
    <p class="muted">自动换 IP 每账号每天最多 ${used[0].limit} 次（设置里修改），达到上限或失败时只推送 Telegram 告警。</p></div>` : ""}
  <div class="card"><p class="muted">在实例卡片上点「监控」添加。检测间隔见设置页。非面板操作导致的停止/终止会推送告警，可选自动启动。</p>
    <table><tr><th>实例</th><th>账号</th><th>上次状态</th><th>自动启动</th><th>连通检测</th><th></th></tr>
    ${list.map((m) => `<tr><td>${esc(m.name)}<div class="muted mono">${esc(m.instance_id).slice(-24)}</div></td><td>${esc(m.account_name)}</td>
    <td>${esc(m.last_state || "-")}</td><td>${m.auto_start ? "✅" : "—"}</td>
    <td>${m.check_port ? `${esc(m.public_ip || "-")}:${m.check_port}${m.auto_change_ip ? " · 不通自动换 IP" : ""}${m.fail_count ? ` · 失败 ${m.fail_count}` : ""}` : "—"}</td>
    <td><button class="btn sm danger" data-del="${m.id}">移除</button></td></tr>`).join("") || `<tr><td colspan=6 class="muted">暂无</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (!(await confirmBox("移除监控", "确定移除这台实例的监控？", true))) return; if (await act(b, () => del(`/monitors/${b.dataset.del}`), "已移除")) pageMonitors(); }));
}

// ================= v1.2 新增 =================
export const HL = { good: "健康", warn: "注意", bad: "危险" };
export async function pageHealth() {
  loading();
  const list = await api("/account-health");
  const fmt = (t) => (t ? new Date(t * 1000).toLocaleString() : "从未");
  view.innerHTML = `<div class="bar"><button class="btn primary" id="all">全部重新检测</button>
    <span class="muted">每天 07:30 自动检测；分数下降 ≥15 或进入「危险」会推送 Telegram。只用免费只读接口，不调用 Cost Explorer。</span></div>
    <div class="grid">${list.map((h) => `<div class="card"><div class="inst"><div class="hd"><span class="dot ${h.provider}"></span><b>${esc(h.name)}</b>
      ${h.score == null ? `<span class="badge">未检测</span>` : `<span class="hs big2 ${h.level}">${h.score}</span>`}</div>
      ${h.items.length ? `<div class="hitems">${h.items.map((i) => `<div class="hi ${i.ok ? "ok" : "bad"}"><span>${i.ok ? "✓" : "!"}</span>
        <div><b>${esc(i.name)}</b>${i.penalty ? ` <span class="muted">-${i.penalty}</span>` : ""}<div class="muted">${esc(i.detail)}</div></div></div>`).join("")}</div>`
        : `<p class="muted">还没有检测记录</p>`}
      <div class="ops"><span class="muted grow">${h.level ? HL[h.level] + " · " : ""}检测于 ${fmt(h.checked_at)}</span>
      <button class="btn sm" data-chk="${h.account_id}">检测</button></div></div></div>`).join("")}</div>`;
  $("#all").onclick = (e) => act(e.target, () => post("/account-health/refresh", {}), "检测完成").then(pageHealth);
  view.querySelectorAll("[data-chk]").forEach((b) => (b.onclick = () =>
    act(b, () => post("/account-health/refresh", { account_id: +b.dataset.chk }), "检测完成").then(pageHealth)));
}

export const GST = { ok: "running", warn: "pending", over: "failed", tripped: "stopped", resume_failed: "failed", disabled: "", throttled: "pending" };
export async function pageTraffic() {
  loading();
  const list = await api("/traffic-guards");
  const fmt = (t) => (t ? new Date(t * 1000).toLocaleString() : "-");
  const actText = (g) => g.action === "throttle" ? `限速 ${g.throttle_mbps} Mbps` : g.action !== "stop" ? "只推送" : g.shutdown_hours > 0 ? `停机 ${g.shutdown_hours} 小时后自动开机` : "自动停机";
  view.innerHTML = `<div class="card"><p class="muted">在实例卡片上点「流量守护」添加规则（OCI 在账号的「流量」标签里设置）：本月累计或滚动窗口（最近 N 小时，出站 / 入站 / 双向）。超限可自动停机，并可在 M 小时后自动开机（失败只告警、不重试）；或「推送并限速」（实例上装 agent，默认 1 Mbps，SSH 不限）。同一个 agent 还能按端口 / 服务统计流量明细。Telegram：/traffic、/ports 实例名。</p>
    ${list.length ? `<table><tr><th>实例</th><th>账号</th><th>统计</th><th>用量</th><th>上限</th><th>到上限</th><th>状态</th><th>启用</th><th>检查于</th><th></th></tr>
    ${list.map((g) => `<tr data-g="${g.id}"><td>${esc(g.name || g.instance_id.slice(-12))}</td><td><span class="dot ${g.provider}"></span>${esc(g.account_name || "-")}</td>
      <td>${esc(g.scope || "本月出站")}</td>
      <td><div class="meter"><i style="width:${Math.min(100, g.last_pct || 0)}%" class="${(g.last_pct || 0) >= 100 ? "bad" : (g.last_pct || 0) >= g.warn_pct ? "warn" : ""}"></i></div>
        ${g.last_gb ?? "-"} GB · ${g.last_pct ?? "-"}%</td><td>${g.limit_gb} GB</td><td>${actText(g)}${g.agent ? `<div>${agentLine(g.agent, g)}</div>` : ""}</td>
      <td><span class="badge ${GST[g.status] || ""}">${esc(g.status_text || "正常")}</span>${g.resume_at_text ? `<div class="muted">预计 ${esc(g.resume_at_text)} 开机</div>` : g.state_msg && g.status !== "ok" ? `<div class="muted">${esc(g.state_msg)}</div>` : ""}</td>
      <td><label class="switch"><input type="checkbox" data-en="${g.id}" ${g.enabled ? "checked" : ""}><span></span></label></td>
      <td>${fmt(g.checked_at)}</td><td><button class="btn sm" data-chk="${g.id}">立即检查</button> <button class="btn sm" data-ed="${g.id}">编辑</button>
      <button class="btn sm" data-ag="${g.id}">agent</button> <button class="btn sm" data-pt="${g.id}">端口明细</button>${g.throttled ? ` <button class="btn sm" data-rt="${g.id}">解除限速</button>` : ""}
      ${g.resume_at ? `<button class="btn sm" data-cr="${g.id}">取消自动开机</button>` : ""}${["tripped", "resume_failed"].includes(g.status) ? ` <button class="btn sm" data-rs="${g.id}">清除状态</button>` : ""}
      <button class="btn sm danger" data-del="${g.id}">删除</button></td></tr>`).join("")}</table>`
    : `<div class="empty">还没有流量守护规则</div>`}</div>`;
  view.querySelectorAll("[data-chk]").forEach((b) => (b.onclick = () => act(b, () => post(`/traffic-guards/${b.dataset.chk}/check`), "已检查").then(pageTraffic)));
  view.querySelectorAll("[data-en]").forEach((b) => (b.onchange = () => act(null, () => api(`/traffic-guards/${b.dataset.en}`, { method: "PATCH", body: { enabled: b.checked } }), b.checked ? "已启用" : "已停用").then(pageTraffic)));
  view.querySelectorAll("[data-cr]").forEach((b) => (b.onclick = () => act(b, () => api(`/traffic-guards/${b.dataset.cr}`, { method: "PATCH", body: { cancel_resume: true } }), "已取消自动开机").then(pageTraffic)));
  view.querySelectorAll("[data-ag]").forEach((b) => (b.onclick = () => guardAgentDialog(list.find((x) => x.id == b.dataset.ag), pageTraffic)));
  view.querySelectorAll("[data-pt]").forEach((b) => (b.onclick = () => guardPortsDialog(list.find((x) => x.id == b.dataset.pt))));
  view.querySelectorAll("[data-rt]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("解除限速", "手动解除这条守护的限速？本期内不会再自动限速（回落 / 下个月后恢复正常判断）。")) act(b, () => api(`/traffic-guards/${b.dataset.rt}`, { method: "PATCH", body: { release_throttle: true } }), "已解除，agent 下次心跳生效").then(pageTraffic);
  }));
  view.querySelectorAll("[data-rs]").forEach((b) => (b.onclick = () => act(b, () => api(`/traffic-guards/${b.dataset.rs}`, { method: "PATCH", body: { reset_state: true } }), "已清除").then(pageTraffic)));
  view.querySelectorAll("[data-ed]").forEach((b) => (b.onclick = () => {
    const g = list.find((x) => x.id == b.dataset.ed); const acc = ACCOUNTS.find((a) => a.id === g.account_id);
    if (acc) trafficDialog(acc, { id: g.instance_id, name: g.name || g.instance_id.slice(-12), region: g.region || undefined }, g.kind || "vm", pageTraffic);
  }));
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("删除规则", "删除这条流量守护？", true)) act(b, () => api(`/traffic-guards/${b.dataset.del}`, { method: "DELETE" }), "已删除").then(pageTraffic);
  }));
}
