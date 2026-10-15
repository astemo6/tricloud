// TriCloud 前端 v1.6.0 · Hash 路由（#/aws/3/billing）、侧栏、顶栏账号快速切换器
import { $, ACCOUNTS, esc, isDesktop, PLOGO, PNAME, PROVS, TABS, view } from "./core.js";
import { pageHome } from "./home.js";
import { pageAccounts, pageDeletedAccounts } from "./accounts.js";
import { closeOpsMenu, pageAccount } from "./instances.js";
import { pageFreeCheck } from "./oci.js";
import { pageTasks } from "./tasks.js";
import { pageHealth, pageMonitors, pageTraffic } from "./monitors.js";
import { pageDns, pageScripts, pageSecrets, pageSecurity, pageSettings } from "./settings.js";

export function parseHash() {
  const p = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  return p;
}
export function go(h) { if (location.hash !== h) location.hash = h; else route(); }
window.addEventListener("hashchange", route);

export async function route() {
  $("#side").classList.remove("open");
  const p = parseHash();
  renderSide(p);
  try {
    if (!p.length) return pageHome();
    if (p[0] === "accounts") return pageAccounts();
    if (p[0] === "tasks") return pageTasks();
    if (p[0] === "monitors") return pageMonitors();
    if (p[0] === "settings") return pageSettings();
    if (p[0] === "secrets") return pageSecrets();
    if (p[0] === "scripts") return pageScripts();
    if (p[0] === "dns") return pageDns();
    if (p[0] === "security") return pageSecurity();
    if (p[0] === "health") return pageHealth();
    if (p[0] === "traffic") return pageTraffic();
    if (p[0] === "deleted") return pageDeletedAccounts();
    if (p[0] === "freecheck") return pageFreeCheck();
    if (TABS[p[0]]) {
      const acc = ACCOUNTS.find((a) => a.id == p[1] && a.provider === p[0]);
      if (!acc) return (view.innerHTML = `<div class="empty">账号不存在</div>`);
      const tab = TABS[p[0]].some((t) => t[0] === p[2]) ? p[2] : TABS[p[0]][0][0];
      if (p[2] !== tab) return history.replaceState(null, "", `#/${p[0]}/${p[1]}/${tab}`), route();
      return pageAccount(acc, tab);
    }
    go("#/");
  } catch (e) { view.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; }
}

export function renderSide(p) {
  const cur = "#/" + (p[0] === "deleted" ? "accounts" : p.slice(0, 2).join("/"));
  const link = (h, label, cls = "") => `<a href="${h}" class="${(cur === h || (h === "#/" && !p.length)) ? "on" : ""}">${cls}${label}</a>`;
  let html = `<div class="logo">Tri<span>Cloud</span></div>` + link("#/", "🏠 总览");
  for (const prov of PROVS) {
    const list = ACCOUNTS.filter((a) => a.provider === prov);
    if (!list.length) continue;
    html += `<div class="grp prov">${PLOGO[prov]}${PNAME[prov]}</div>`;
    for (const a of list) html += link(`#/${prov}/${a.id}`, esc(a.name), `<span class="dot ${prov}"></span>`);
  }
  html += `<div class="grp">管理</div>` + link("#/accounts", "🔑 云账号") + link("#/health", "🩺 账号健康度") + link("#/freecheck", "🆓 免费额度体检") + link("#/traffic", "📈 流量守护") + link("#/tasks", "⏱ 任务") +
    link("#/monitors", "📡 监控") + link("#/secrets", "🔐 开机密码") + link("#/scripts", "📜 脚本模板") +
    link("#/dns", "🌐 DNS 联动") + link("#/security", "🛡 安全与备份") + link("#/settings", "⚙️ 设置");
  $("#side").innerHTML = html;
  const acc = TABS[p[0]] && ACCOUNTS.find((a) => a.id == p[1]);
  renderAccSwitch(acc);
  $("#title").textContent = acc ? `${PNAME[acc.provider]} · ${acc.name}` :
    ({ accounts: "云账号", tasks: "任务", monitors: "监控", settings: "设置", secrets: "开机密码", scripts: "脚本模板",
      dns: "Cloudflare DNS 联动", security: "安全与备份", health: "账号健康度", traffic: "流量守护", deleted: "已删账号", freecheck: "免费额度体检" }[p[0]] || "总览");
}

// ---------- 顶栏账号快速切换器 ----------
export const TAB_EQUIV = [["instances", "ec2", "vms"], ["create", "azcreate"], ["limits", "quota", "azquota"], ["billing"]];
export function mapTab(tab, prov) {
  if (!tab) return TABS[prov][0][0];
  if (TABS[prov].some((t) => t[0] === tab)) return tab;
  const grp = TAB_EQUIV.find((g) => g.includes(tab));
  const hit = grp && TABS[prov].find((t) => grp.includes(t[0]));
  return hit ? hit[0] : TABS[prov][0][0];
}
export function renderAccSwitch(cur) {
  const el = document.getElementById("accsw"); if (!el) return;
  if (!ACCOUNTS.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<button class="btn accsw-btn" id="accswBtn" aria-haspopup="listbox" title="切换账号">${cur ? `<span class="dot ${cur.provider}"></span><span class="accsw-name">${esc(cur.name)}</span>` : `<span class="accsw-name">切换账号</span>`} ▾</button>`;
  $("#accswBtn").onclick = (e) => { e.stopPropagation(); openAccMenu(); };
}
export function openAccMenu() {
  closeAccMenu();
  const p = parseHash(); const curTab = TABS[p[0]] ? p[2] : null;
  const m = document.createElement("div"); m.className = "accmenu"; m.id = "accmenu";
  m.innerHTML = `<input id="accq" placeholder="搜索账号 / 区域…" autocomplete="off"><div class="accl" id="accl"></div>`;
  document.body.appendChild(m);
  const btn = $("#accswBtn").getBoundingClientRect();
  if (isDesktop()) { m.style.top = `${btn.bottom + 6}px`; m.style.left = `${Math.max(8, Math.min(btn.left, window.innerWidth - 340))}px`; } else m.style.setProperty("top", `${btn.bottom + 6}px`, "important");
  const draw = () => {
    const q = $("#accq").value.trim().toLowerCase();
    let html = "";
    for (const prov of PROVS) {
      const l = ACCOUNTS.filter((a) => a.provider === prov && (!q || (a.name + " " + (a.region || "") + " " + PNAME[prov]).toLowerCase().includes(q)));
      if (!l.length) continue;
      html += `<div class="accg">${PNAME[prov]}</div>` + l.map((a) => `<button class="acci ${a.id == p[1] && a.provider === p[0] ? "on" : ""}" data-go="#/${prov}/${a.id}/${mapTab(curTab, prov)}">
        <span class="dot ${prov}"></span><span class="grow">${esc(a.name)}</span><span class="muted">${esc(a.region || "")}</span></button>`).join("");
    }
    $("#accl").innerHTML = html || `<div class="empty">没有匹配的账号</div>`;
    $("#accl").querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => { closeAccMenu(); go(b.dataset.go); }));
  };
  $("#accq").oninput = draw;
  $("#accq").onkeydown = (e) => {
    if (e.key === "Escape") closeAccMenu();
    if (e.key === "Enter") { const f = $("#accl [data-go]"); if (f) f.click(); }
  };
  draw();
  setTimeout(() => $("#accq") && $("#accq").focus());
}
export function closeAccMenu() { const m = document.getElementById("accmenu"); if (m) m.remove(); }
document.addEventListener("click", (e) => { if (!e.target.closest("#accmenu") && !e.target.closest("#accswBtn")) closeAccMenu(); if (!e.target.closest(".opsmenu")) closeOpsMenu(); });
