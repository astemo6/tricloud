// TriCloud 前端 v1.6.0 build 22 · 流量守护 agent：「推送并限速」安装 / 卸载命令、在线状态与最后心跳、重置 token、流量明细开关，
// 以及按端口 / 服务的流量明细（今日 / 本月 Top，入站 / 出站 / 合计 + 占比条）。面板不会远程执行任何命令，agent 由用户自己在机器上安装。
import { $, act, api, confirmBox, esc, modal, toast } from "./core.js";

export async function copyText(text, input) {
  try { await navigator.clipboard.writeText(text); toast("已复制"); }
  catch (_) { if (input) { input.select(); document.execCommand("copy"); toast("已复制"); } else toast("请手动复制", true); }
}

const cmdRow = (label, id, v) => `<label>${esc(label)}</label><div class="bar"><input class="mono grow" id="${id}" readonly value="${esc(v)}" onclick="this.select()">
  <button class="btn sm" data-copy="${id}">复制</button></div>`;

// agent 状态一行（守护列表 / 弹窗共用）
export function agentLine(a, g) {
  if (!a) return "";
  const st = !a.installed ? `<span class="badge">agent 未安装</span>` : a.online ? `<span class="badge done">agent 在线</span>` : `<span class="badge failed">agent 离线</span>`;
  const seen = a.last_seen_text ? `最后心跳 ${esc(a.last_seen_text)}` : "";
  const thr = g && g.action === "throttle" ? (a.applied ? " · 🐢 当前已限速" : g.throttled ? " · 应限速（等 agent 生效）" : " · 当前未限速") : "";
  return `${st} <span class="muted">${seen}${thr}</span>`;
}

export async function guardAgentDialog(g, onChange) {
  let d;
  try { d = await api(`/traffic-guards/${g.id}/agent?base=${encodeURIComponent(location.origin)}`); } catch (e) { toast(e.message, true); return; }
  const a = d.agent || {};
  const be = a.acct_backend ? `${esc(a.acct_backend_text || a.acct_backend)}${a.acct_ports != null ? `，${a.acct_ports} 个端口` : ""}` : "等待 agent 上报";
  const body = `<p>${agentLine(a, g)}</p>
    <ul class="guard">
      <li>动作：${g.action === "throttle" ? `超限后出站限速到 <b>${esc(d.throttle_mbps)} Mbps</b>（SSH 端口不限），回落 / 下月自动解除` : g.action === "stop" ? "超限自动停机（agent 只做流量明细）" : "只推送（agent 只做流量明细）"}</li>
      <li>当前：${d.throttled ? "<b>已触发限速</b>" : "未触发限速"}${a.applied ? "（agent 已生效）" : ""}${a.iface ? ` · 网卡 ${esc(a.iface)}` : ""}${a.ssh_ports ? ` · SSH 端口 ${esc(a.ssh_ports)}` : ""}</li>
      <li>流量明细：${a.acct_enabled ? `已开启（${be}）` : "未开启"}</li>
    </ul>
    <label class="row-check"><input type="checkbox" id="gaAcct" style="width:auto" ${a.acct_enabled ? "checked" : ""}> 流量明细：按端口 / 服务统计入站、出站（nftables 独立 table，只计数不拦截；没有 nft 时用 iptables 计数链）</label>
    ${d.commands ? `<p class="muted">在<b>这台实例</b>上用 root 运行安装命令（面板不会远程执行任何命令）。agent 是 bash 脚本 + systemd timer，每 ${Math.round(d.poll_secs / 60)} 分钟用这条守护的专属 token 拉取状态并上报流量明细；超过 ${Math.round(d.offline_secs / 60)} 分钟没心跳算离线。</p>
    ${cmdRow("安装命令", "gaIns", d.commands.install)}${cmdRow("卸载命令（面板）", "gaUn", d.commands.uninstall)}${cmdRow("卸载命令（本机）", "gaUnL", d.commands.uninstall_local)}${cmdRow("查看状态", "gaSt", d.commands.status)}
    <p class="muted">安装命令里含这条守护的 token，只能读写这条守护的状态和流量明细；泄露了点「重置 token」，旧 agent 会自动解除限速、删除计数规则。</p>`
      : `<p class="muted">API Token 只能查看状态，不显示安装命令。</p>`}
    <div class="bar" style="margin-top:8px">${d.commands ? `<button class="btn danger" id="gaReset">重置 token</button>` : ""}<button class="btn" id="gaPorts">端口流量明细</button></div>`;
  let changed = false;
  await modal(`流量守护 agent · ${g.name || g.instance_id.slice(-12)}`, body, null, "关闭", false, (bg) => {
    bg.querySelectorAll("[data-copy]").forEach((b) => (b.onclick = () => { const i = bg.querySelector("#" + b.dataset.copy); copyText(i.value, i); }));
    $("#gaAcct", bg).onchange = (e) => act(null, () => api(`/traffic-guards/${g.id}`, { method: "PATCH", body: { acct_enabled: e.target.checked } }),
      e.target.checked ? "已开启流量明细，agent 下次心跳（≤5 分钟）建立计数规则" : "已关闭流量明细，agent 下次心跳删除计数规则").then(() => { changed = true; });
    if ($("#gaReset", bg)) $("#gaReset", bg).onclick = async () => {
      if (!(await confirmBox("重置 agent token", "重置后旧的安装命令立即失效，实例上的旧 agent 会解除限速并删除计数规则，需要在实例上重新运行新的安装命令。确定重置？", true))) return;
      const r = await act($("#gaReset", bg), () => api(`/traffic-guards/${g.id}/agent/reset?base=${encodeURIComponent(location.origin)}`, { method: "POST", body: {} }), "已重置，请重新安装");
      if (r) { $("#gaIns", bg).value = r.commands.install; changed = true; }
    };
    $("#gaPorts", bg).onclick = () => { bg.remove(); guardPortsDialog(g); };
  });
  if (changed && onChange) onChange();
}

export function portsTable(t, kind) {
  const rows = kind === "services" ? t.services : t.ports;
  if (!rows.length) return `<div class="empty">${esc(t.title)}还没有数据</div>`;
  return `<table class="ptable"><tr><th>${kind === "services" ? "服务" : "端口 · 进程"}</th><th>入站</th><th>出站</th><th>合计</th><th style="min-width:120px">占比</th></tr>
    ${rows.map((r) => `<tr><td>${esc(kind === "services" ? r.service : r.label)}${kind === "services" && r.ports.length ? `<div class="muted">${esc(r.ports.join(", "))}</div>` : ""}</td>
      <td>${esc(r.in_text)}</td><td>${esc(r.out_text)}</td><td><b>${esc(r.total_text)}</b></td>
      <td><div class="meter pbar" title="${r.pct}%"><i style="width:${Math.min(100, r.pct)}%"></i></div><span class="muted">${r.pct}%</span></td></tr>`).join("")}</table>`;
}

export async function guardPortsDialog(g) {
  let rng = "today", kind = "ports";
  const load = async (bg) => {
    const box = $("#gpBody", bg);
    box.innerHTML = `<span class="spin"></span> 读取中…`;
    let t;
    try { t = await api(`/traffic-guards/${g.id}/ports?range=${rng}&limit=20`); } catch (e) { box.innerHTML = `<span class="err-text">${esc(e.message)}</span>`; return; }
    const a = t.agent || {};
    box.innerHTML = `<p>${esc(t.title)}（${esc(t.start === t.end ? t.start : t.start + " ~ " + t.end)}）合计 <b>${esc(t.total_text)}</b>：入站 ${esc(t.in_text)} / 出站 ${esc(t.out_text)}
      ${t.updated_at ? `<span class="muted">· 更新于 ${esc(new Date(t.updated_at * 1000).toLocaleString())}</span>` : ""}</p>
      ${!t.acct_enabled ? `<p class="muted">流量明细未开启：在「agent」里打开流量明细并在实例上安装 agent。</p>` : !a.installed ? `<p class="muted">agent 尚未安装 / 尚未上报。</p>` : ""}
      ${portsTable(t, kind)}
      <p class="muted">非监听端口的流量（比如本机主动访问外网、代理的出站连接）归为「其他/出站连接」。数据由实例上的 agent 每 5 分钟上报，按天保存 ${t.retain_days} 天。</p>`;
  };
  await modal(`端口流量明细 · ${g.name || g.instance_id.slice(-12)}`, `<div class="bar"><div class="seg" id="gpRng"><button data-r="today" class="on">今日</button><button data-r="month">本月</button></div>
      <div class="seg" id="gpKind"><button data-k="ports" class="on">按端口</button><button data-k="services">按服务</button></div></div><div id="gpBody" style="margin-top:12px"></div>`,
  null, "关闭", false, (bg) => {
    bg.querySelector(".modal").classList.add("wide");
    bg.querySelectorAll("#gpRng button").forEach((b) => (b.onclick = () => { rng = b.dataset.r; bg.querySelectorAll("#gpRng button").forEach((x) => x.classList.toggle("on", x === b)); load(bg); }));
    bg.querySelectorAll("#gpKind button").forEach((b) => (b.onclick = () => { kind = b.dataset.k; bg.querySelectorAll("#gpKind button").forEach((x) => x.classList.toggle("on", x === b)); load(bg); }));
    load(bg);
  });
}
