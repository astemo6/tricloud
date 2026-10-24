// TriCloud 前端 v1.6.0 · Hash 路由（#/aws/3/billing）、侧栏、顶栏账号快速切换器
import { $, accountRegionText, ACCOUNTS, esc, isDesktop, loadAccounts, PLOGO, PNAME, post, PROVS, TAB_ALIAS, TABS, view } from "./core.js";
import { t } from "./i18n.js";
import { pageHome } from "./home.js";
import { pageAccounts, pageDeletedAccounts } from "./accounts.js";
import { closeOpsMenu, pageAccount } from "./instances.js";
import { pageFreeCheck } from "./oci.js";
import { pageTasks } from "./tasks.js";
import { pageHealth, pageMonitors, pageTraffic } from "./monitors.js";
import { pageDns, pageScripts, pageSecrets, pageSecurity, pageSettings } from "./settings.js";
import { pageOneDrive } from "./onedrive.js";

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
    if (p[0] === "onedrive") return pageOneDrive();
    if (p[0] === "health") return pageHealth();
    if (p[0] === "traffic") return pageTraffic();
    if (p[0] === "deleted") return pageDeletedAccounts();
    if (p[0] === "freecheck") return pageFreeCheck();
    if (TABS[p[0]]) {
      const acc = ACCOUNTS.find((a) => a.id == p[1] && a.provider === p[0]);
      if (!acc) return (view.innerHTML = `<div class="empty">${t("route.noAccount")}</div>`);
      const want = (TAB_ALIAS[p[0]] || {})[p[2]] || p[2];
      const tab = TABS[p[0]].some((tb) => tb[0] === want) ? want : TABS[p[0]][0][0];
      if (p[2] !== tab) return history.replaceState(null, "", `#/${p[0]}/${p[1]}/${tab}`), route();
      return pageAccount(acc, tab);
    }
    go("#/");
  } catch (e) { view.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; }
}

export function renderSide(p) {
  const cur = "#/" + (p[0] === "deleted" ? "accounts" : p.slice(0, 2).join("/"));
  const link = (h, label, cls = "") => `<a href="${h}" class="${(cur === h || (h === "#/" && !p.length)) ? "on" : ""}">${cls}${label}</a>`;
  let html = `<div class="logo">Tri<span>Cloud</span></div>` + link("#/", `🏠 ${t("nav.home")}`);
  for (const prov of PROVS) {
    const list = ACCOUNTS.filter((a) => a.provider === prov);
    if (!list.length) continue;
    html += `<div class="grp prov">${PLOGO[prov]}${PNAME[prov]}</div>`;
    for (const a of list) html += `<a href="#/${prov}/${a.id}" data-acc="${a.id}" draggable="true" class="${cur === `#/${prov}/${a.id}` ? "on" : ""}"><span class="dot ${prov}"></span>${esc(a.name)}</a>`;
  }
  html += `<div class="grp">${t("nav.manage")}</div>` + link("#/accounts", `🔑 ${t("nav.accounts")}`) + link("#/health", `🩺 ${t("nav.health")}`) + link("#/freecheck", `🆓 ${t("nav.freecheck")}`) + link("#/traffic", `📈 ${t("nav.traffic")}`) + link("#/tasks", `⏱ ${t("nav.tasks")}`) +
    link("#/monitors", `📡 ${t("nav.monitors")}`) + link("#/secrets", `🔐 ${t("nav.secrets")}`) + link("#/scripts", `📜 ${t("nav.scripts")}`) +
    link("#/dns", `🌐 ${t("nav.dns")}`) + link("#/security", `🛡 ${t("nav.security")}`) + link("#/onedrive", `☁️ ${t("nav.onedrive")}`) + link("#/settings", `⚙️ ${t("nav.settings")}`);
  $("#side").innerHTML = html;
  wireSideDrag();
  const acc = TABS[p[0]] && ACCOUNTS.find((a) => a.id == p[1]);
  renderAccSwitch(acc);
  $("#title").textContent = acc ? `${PNAME[acc.provider]} · ${acc.name}` :
    ({ accounts: t("nav.accounts"), tasks: t("nav.tasks"), monitors: t("nav.monitors"), settings: t("nav.settings"), secrets: t("nav.secrets"), scripts: t("nav.scripts"),
      dns: t("title.dns"), security: t("nav.security"), onedrive: t("nav.onedrive"), health: t("nav.health"), traffic: t("nav.traffic"), deleted: t("nav.deleted"), freecheck: t("nav.freecheck") }[p[0]] || t("nav.home"));
}

// ---------- 左侧账号手动排序（同云组内拖动，松手存后端 sort_order） ----------
function wireSideDrag() {
  const side = $("#side");
  let dragId = null;
  const items = () => [...side.querySelectorAll("a[data-acc]")];
  const provOf = (id) => (ACCOUNTS.find((a) => a.id == id) || {}).provider;
  items().forEach((el) => {
    el.addEventListener("dragstart", (e) => {
      dragId = el.dataset.acc; el.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", dragId); } catch {}
    });
    el.addEventListener("dragend", () => { dragId = null; items().forEach((x) => x.classList.remove("dragging", "drop-before", "drop-after")); });
    el.addEventListener("dragover", (e) => {
      if (dragId == null || el.dataset.acc === dragId || provOf(el.dataset.acc) !== provOf(dragId)) return;
      e.preventDefault(); e.dataTransfer.dropEffect = "move";
      const r = el.getBoundingClientRect(), after = e.clientY > r.top + r.height / 2;
      el.classList.toggle("drop-after", after); el.classList.toggle("drop-before", !after);
      el.dataset.after = after ? "1" : "";
    });
    el.addEventListener("dragleave", () => el.classList.remove("drop-before", "drop-after"));
    el.addEventListener("drop", async (e) => {
      e.preventDefault();
      if (dragId == null || el.dataset.acc === dragId) return;
      const dragEl = side.querySelector(`a[data-acc="${dragId}"]`);
      if (!dragEl || provOf(el.dataset.acc) !== provOf(dragId)) return;
      el.parentNode.insertBefore(dragEl, el.dataset.after ? el.nextSibling : el);
      await post("/accounts/reorder", { ids: items().map((x) => +x.dataset.acc) });
      await loadAccounts(); renderSide(parseHash());
    });
  });
}

// ---------- 顶栏账号快速切换器 ----------
export const TAB_EQUIV = [["instances", "ec2", "vms"], ["create", "azcreate"], ["limits", "quota", "azquota"], ["billing"]];
export function mapTab(tab, prov) {
  if (!tab) return TABS[prov][0][0];
  if (TABS[prov].some((tb) => tb[0] === tab)) return tab;
  const grp = TAB_EQUIV.find((g) => g.includes(tab));
  const hit = grp && TABS[prov].find((tb) => grp.includes(tb[0]));
  return hit ? hit[0] : TABS[prov][0][0];
}
export function renderAccSwitch(cur) {
  const el = document.getElementById("accsw"); if (!el) return;
  if (!ACCOUNTS.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<button class="btn accsw-btn" id="accswBtn" aria-haspopup="listbox" title="${t("accsw.switch")}">${cur ? `<span class="dot ${cur.provider}"></span><span class="accsw-name">${esc(cur.name)}</span>` : `<span class="accsw-name">${t("accsw.switch")}</span>`} ▾</button>`;
  $("#accswBtn").onclick = (e) => { e.stopPropagation(); openAccMenu(); };
}
export function openAccMenu() {
  closeAccMenu();
  const p = parseHash(); const curTab = TABS[p[0]] ? p[2] : null;
  const m = document.createElement("div"); m.className = "accmenu"; m.id = "accmenu";
  m.innerHTML = `<input id="accq" placeholder="${t("accsw.search")}" autocomplete="off"><div class="accl" id="accl"></div>`;
  document.body.appendChild(m);
  const btn = $("#accswBtn").getBoundingClientRect();
  if (isDesktop()) { m.style.top = `${btn.bottom + 6}px`; m.style.left = `${Math.max(8, Math.min(btn.left, window.innerWidth - 340))}px`; } else m.style.setProperty("top", `${btn.bottom + 6}px`, "important");
  const draw = () => {
    const q = $("#accq").value.trim().toLowerCase();
    let html = "";
    for (const prov of PROVS) {
      const l = ACCOUNTS.filter((a) => a.provider === prov && (!q || (a.name + " " + accountRegionText(a) + " " + (a.region || "") + " " + PNAME[prov]).toLowerCase().includes(q)));
      if (!l.length) continue;
      html += `<div class="accg">${PNAME[prov]}</div>` + l.map((a) => `<button class="acci ${a.id == p[1] && a.provider === p[0] ? "on" : ""}" data-go="#/${prov}/${a.id}/${mapTab(curTab, prov)}">
        <span class="dot ${prov}"></span><span class="grow">${esc(a.name)}</span><span class="muted">${esc(accountRegionText(a))}</span></button>`).join("");
    }
    $("#accl").innerHTML = html || `<div class="empty">${t("accsw.none")}</div>`;
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
