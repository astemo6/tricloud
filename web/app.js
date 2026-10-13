// TriCloud 前端 v1.6.0：原生 JS，Hash 路由 #/aws/3/billing（FR-06）
"use strict";
// v1.4 紧凑模式（每台设备单独记忆）尽早生效，避免闪烁
try { if (localStorage.getItem("tc_compact") === "1") document.documentElement.classList.add("compact"); } catch (_) { /* ignore */ }
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const view = $("#view");
let ACCOUNTS = [];
let SETTINGS = {};

// ---------------- API ----------------
async function api(path, opt = {}) {
  const init = { method: opt.method || "GET", headers: {}, credentials: "same-origin" };
  if (opt.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opt.body); }
  const r = await fetch("/api" + path, init);
  if (r.status === 401) { sessionStorage.setItem("tc_back", location.hash); location.href = "/login"; throw new Error("未登录"); }
  const j = await r.json().catch(() => ({}));
  if (r.status === 409 && j.detail && j.detail.guard) {   // v1.2 免费额度护栏：二次确认后带 confirm_overage 重发
    const go = await modal("⚠️ 可能超出免费额度", `<ul class="guard">${j.detail.guard.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
      <p class="muted">免费额度以云厂商公示和你的账号类型为准。可在「设置 → 免费额度护栏」关闭此提醒。</p>`, null, "仍然继续", true);
    if (!go) throw new Error("已取消");
    return api(path, { ...opt, body: { ...(opt.body || {}), confirm_overage: true } });
  }
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : (j.detail && j.detail.msg) || r.statusText);
  // v1.4：提交了后台任务 → 自动打开右侧任务抽屉并跟踪
  if (init.method !== "GET" && j && (j.task_id || (j.task_ids && j.task_ids.length)) && window.TaskDrawer) TaskDrawer.open(j.task_id || j.task_ids[0]);
  return j;
}
const post = (p, b) => api(p, { method: "POST", body: b || {} });
const del = (p) => api(p, { method: "DELETE" });

// 页面脚本出错时直接提示，避免点了按钮没反应（例如 Windows 客户端里）
window.addEventListener("error", (e) => { try { toast("页面出错：" + (e.message || e.error), true); } catch (_) {} });
window.addEventListener("unhandledrejection", (e) => { try { toast("操作出错：" + ((e.reason && e.reason.message) || e.reason), true); } catch (_) {} });
function toast(msg, err) {
  const d = document.createElement("div");
  d.className = "toast" + (err ? " err" : "");
  d.textContent = msg;
  document.body.appendChild(d);
  setTimeout(() => d.remove(), err ? 6000 : 4500);
}
async function act(btn, fn, okMsg) {
  if (btn) btn.disabled = true;
  try { const r = await fn(); if (okMsg) toast(typeof okMsg === "function" ? okMsg(r) : okMsg); return r; }
  catch (e) { toast(e.message, true); }
  finally { if (btn) btn.disabled = false; }
}
function modal(title, bodyHtml, onOk, okText = "确定", danger = false, onOpen = null) {
  return new Promise((resolve) => {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `<div class="modal"><h3>${esc(title)}</h3><div class="mb">${bodyHtml}</div>
      <div class="acts"><button class="btn" data-x>取消</button><button class="btn ${danger ? "danger" : "primary"}" data-ok>${esc(okText)}</button></div></div>`;
    document.body.appendChild(bg);
    applyShowWhen(bg); bg.addEventListener("change", () => applyShowWhen(bg));
    if (onOpen) onOpen(bg);
    const close = (v) => { bg.remove(); resolve(v); };
    bg.querySelector("[data-x]").onclick = () => close(null);
    bg.onclick = (e) => { if (e.target === bg) close(null); };
    bg.querySelector("[data-ok]").onclick = async (e) => {
      const b = e.target; b.disabled = true;
      try { const v = onOk ? await onOk(bg) : true; if (v !== false) close(v ?? true); }
      catch (err) { toast(err.message, true); }
      finally { b.disabled = false; }
    };
  });
}
// v1.4：<div data-show-when="mode=rolling"> 按同一弹窗里字段的值显示 / 隐藏（多个条件用 & 连接，值可用 | 表示或）
function applyShowWhen(root) {
  root.querySelectorAll("[data-show-when]").forEach((el) => {
    const okAll = el.dataset.showWhen.split("&").every((cond) => {
      const [k, v] = cond.split("="); const f = root.querySelector(`[name="${k}"]`);
      if (!f) return true;
      const val = f.type === "checkbox" ? String(f.checked) : f.value;
      return v.split("|").includes(val);
    });
    el.style.display = okAll ? "" : "none";
  });
}
const confirmBox = (t, msg, danger) => modal(t, `<p>${msg}</p>`, null, "确认", danger);
const form = (root) => Object.fromEntries([...root.querySelectorAll("[name]")].map((i) => [i.name, i.type === "checkbox" ? i.checked : i.value.trim()]));
const loading = () => (view.innerHTML = `<div class="empty"><span class="spin"></span> 加载中…</div>`);

// ---------------- 路由 ----------------
const TABS = {
  oci: [["instances", "实例"], ["create", "创建实例"], ["snatch", "自动抢机"], ["secgroup", "安全组"], ["storage", "存储"], ["objects", "对象存储"], ["traffic", "流量"], ["limits", "配额/网络"], ["regionsub", "区域订阅"], ["billing", "账单"]],
  aws: [["ec2", "EC2"], ["lightsail", "Lightsail"], ["regions", "区域"], ["cloudfront", "CloudFront"], ["quota", "配额"], ["recycle", "闲置资源"], ["billing", "账单"]],
  azure: [["vms", "虚拟机"], ["azcreate", "创建 VM"], ["rgs", "资源组"], ["azquota", "配额"], ["foundry", "Foundry"], ["subscription", "订阅"], ["billing", "账单"]],
};
const PNAME = { oci: "Oracle Cloud", aws: "AWS", azure: "Azure" };
// 扩展点（附加云厂商可在自己的代码块里登记）
const PROVS = ["oci", "aws", "azure"];          // 侧栏 / 切换器 / 下拉的顺序
let META = { providers: PROVS.slice() };         // GET /api/meta：当前可添加的云厂商
const NO_REGION = new Set(["azure"]);            // 没有区域概念的云
const NO_CHANGE_IP = new Set();                  // 不能换 IP 的云（监控里不显示「不通自动换 IP」）
const NO_CREATE = new Set();                     // 不能创建实例的云（不能作为迁移目标）
const TAB_FNS_EXTRA = {}, OP_NAMES = {}, TRAFFIC_DIALOG = {}, ADD_BODY = {}, PROV_HINT = {};
const TEXTAREA_FIELDS = new Set(["key_content"]);
const SETTINGS_CARDS = [];                       // [{ html(settings), bind(root) }]
const NOREG = (acc) => NO_REGION.has(acc.provider);
const provOpts = (blank) => (blank ? `<option value="">${esc(blank)}</option>` : "") + PROVS.filter((p) => META.providers.includes(p)).map((p) => `<option value="${p}">${esc(PNAME[p])}</option>`).join("");
// 三家官方 Logo（内联 SVG；AWS 文字随主题用 currentColor）
const PLOGO = {"oci": "<svg class=\"plogo\" aria-hidden=\"true\" viewBox=\"0 0 24 24\" xmlns=\"http://www.w3.org/2000/svg\"><path fill=\"#C74634\" d=\"M16.412 4.412h-8.82a7.588 7.588 0 0 0-.008 15.176h8.828a7.588 7.588 0 0 0 0-15.176zm-.193 12.502H7.786a4.915 4.915 0 0 1 0-9.828h8.433a4.914 4.914 0 1 1 0 9.828z\"/></svg>", "aws": "<svg class=\"plogo aws\" aria-hidden=\"true\" viewBox=\"0 0 304 182\" xmlns=\"http://www.w3.org/2000/svg\"><g><path fill=\"currentColor\" d=\"M86.4,66.4c0,3.7,0.4,6.7,1.1,8.9c0.8,2.2,1.8,4.6,3.2,7.2c0.5,0.8,0.7,1.6,0.7,2.3c0,1-0.6,2-1.9,3l-6.3,4.2 c-0.9,0.6-1.8,0.9-2.6,0.9c-1,0-2-0.5-3-1.4C76.2,90,75,88.4,74,86.8c-1-1.7-2-3.6-3.1-5.9c-7.8,9.2-17.6,13.8-29.4,13.8 c-8.4,0-15.1-2.4-20-7.2c-4.9-4.8-7.4-11.2-7.4-19.2c0-8.5,3-15.4,9.1-20.6c6.1-5.2,14.2-7.8,24.5-7.8c3.4,0,6.9,0.3,10.6,0.8 c3.7,0.5,7.5,1.3,11.5,2.2v-7.3c0-7.6-1.6-12.9-4.7-16c-3.2-3.1-8.6-4.6-16.3-4.6c-3.5,0-7.1,0.4-10.8,1.3c-3.7,0.9-7.3,2-10.8,3.4 c-1.6,0.7-2.8,1.1-3.5,1.3c-0.7,0.2-1.2,0.3-1.6,0.3c-1.4,0-2.1-1-2.1-3.1v-4.9c0-1.6,0.2-2.8,0.7-3.5c0.5-0.7,1.4-1.4,2.8-2.1 c3.5-1.8,7.7-3.3,12.6-4.5c4.9-1.3,10.1-1.9,15.6-1.9c11.9,0,20.6,2.7,26.2,8.1c5.5,5.4,8.3,13.6,8.3,24.6V66.4z M45.8,81.6 c3.3,0,6.7-0.6,10.3-1.8c3.6-1.2,6.8-3.4,9.5-6.4c1.6-1.9,2.8-4,3.4-6.4c0.6-2.4,1-5.3,1-8.7v-4.2c-2.9-0.7-6-1.3-9.2-1.7 c-3.2-0.4-6.3-0.6-9.4-0.6c-6.7,0-11.6,1.3-14.9,4c-3.3,2.7-4.9,6.5-4.9,11.5c0,4.7,1.2,8.2,3.7,10.6 C37.7,80.4,41.2,81.6,45.8,81.6z M126.1,92.4c-1.8,0-3-0.3-3.8-1c-0.8-0.6-1.5-2-2.1-3.9L96.7,10.2c-0.6-2-0.9-3.3-0.9-4 c0-1.6,0.8-2.5,2.4-2.5h9.8c1.9,0,3.2,0.3,3.9,1c0.8,0.6,1.4,2,2,3.9l16.8,66.2l15.6-66.2c0.5-2,1.1-3.3,1.9-3.9c0.8-0.6,2.2-1,4-1 h8c1.9,0,3.2,0.3,4,1c0.8,0.6,1.5,2,1.9,3.9l15.8,67l17.3-67c0.6-2,1.3-3.3,2-3.9c0.8-0.6,2.1-1,3.9-1h9.3c1.6,0,2.5,0.8,2.5,2.5 c0,0.5-0.1,1-0.2,1.6c-0.1,0.6-0.3,1.4-0.7,2.5l-24.1,77.3c-0.6,2-1.3,3.3-2.1,3.9c-0.8,0.6-2.1,1-3.8,1h-8.6c-1.9,0-3.2-0.3-4-1 c-0.8-0.7-1.5-2-1.9-4L156,23l-15.4,64.4c-0.5,2-1.1,3.3-1.9,4c-0.8,0.7-2.2,1-4,1H126.1z M254.6,95.1c-5.2,0-10.4-0.6-15.4-1.8 c-5-1.2-8.9-2.5-11.5-4c-1.6-0.9-2.7-1.9-3.1-2.8c-0.4-0.9-0.6-1.9-0.6-2.8v-5.1c0-2.1,0.8-3.1,2.3-3.1c0.6,0,1.2,0.1,1.8,0.3 c0.6,0.2,1.5,0.6,2.5,1c3.4,1.5,7.1,2.7,11,3.5c4,0.8,7.9,1.2,11.9,1.2c6.3,0,11.2-1.1,14.6-3.3c3.4-2.2,5.2-5.4,5.2-9.5 c0-2.8-0.9-5.1-2.7-7c-1.8-1.9-5.2-3.6-10.1-5.2L246,52c-7.3-2.3-12.7-5.7-16-10.2c-3.3-4.4-5-9.3-5-14.5c0-4.2,0.9-7.9,2.7-11.1 c1.8-3.2,4.2-6,7.2-8.2c3-2.3,6.4-4,10.4-5.2c4-1.2,8.2-1.7,12.6-1.7c2.2,0,4.5,0.1,6.7,0.4c2.3,0.3,4.4,0.7,6.5,1.1 c2,0.5,3.9,1,5.7,1.6c1.8,0.6,3.2,1.2,4.2,1.8c1.4,0.8,2.4,1.6,3,2.5c0.6,0.8,0.9,1.9,0.9,3.3v4.7c0,2.1-0.8,3.2-2.3,3.2 c-0.8,0-2.1-0.4-3.8-1.2c-5.7-2.6-12.1-3.9-19.2-3.9c-5.7,0-10.2,0.9-13.3,2.8c-3.1,1.9-4.7,4.8-4.7,8.9c0,2.8,1,5.2,3,7.1 c2,1.9,5.7,3.8,11,5.5l14.2,4.5c7.2,2.3,12.4,5.5,15.5,9.6c3.1,4.1,4.6,8.8,4.6,14c0,4.3-0.9,8.2-2.6,11.6 c-1.8,3.4-4.2,6.4-7.3,8.8c-3.1,2.5-6.8,4.3-11.1,5.6C264.4,94.4,259.7,95.1,254.6,95.1z\"/><g><path fill=\"#FF9900\" fill-rule=\"evenodd\" clip-rule=\"evenodd\" d=\"M273.5,143.7c-32.9,24.3-80.7,37.2-121.8,37.2c-57.6,0-109.5-21.3-148.7-56.7c-3.1-2.8-0.3-6.6,3.4-4.4 c42.4,24.6,94.7,39.5,148.8,39.5c36.5,0,76.6-7.6,113.5-23.2C274.2,133.6,278.9,139.7,273.5,143.7z\"/><path fill=\"#FF9900\" fill-rule=\"evenodd\" clip-rule=\"evenodd\" d=\"M287.2,128.1c-4.2-5.4-27.8-2.6-38.5-1.3c-3.2,0.4-3.7-2.4-0.8-4.5c18.8-13.2,49.7-9.4,53.3-5 c3.6,4.5-1,35.4-18.6,50.2c-2.7,2.3-5.3,1.1-4.1-1.9C282.5,155.7,291.4,133.4,287.2,128.1z\"/></g></g></svg>", "azure": "<svg class=\"plogo\" aria-hidden=\"true\" viewBox=\"0 0 96 96\" xmlns=\"http://www.w3.org/2000/svg\"><defs><linearGradient id=\"tcaz0\" x1=\"-1032.172\" x2=\"-1059.213\" y1=\"145.312\" y2=\"65.426\" gradientTransform=\"matrix(1 0 0 -1 1075 158)\" gradientUnits=\"userSpaceOnUse\"><stop offset=\"0\" stop-color=\"#114a8b\"/><stop offset=\"1\" stop-color=\"#0669bc\"/></linearGradient><linearGradient id=\"tcaz1\" x1=\"-1023.725\" x2=\"-1029.98\" y1=\"108.083\" y2=\"105.968\" gradientTransform=\"matrix(1 0 0 -1 1075 158)\" gradientUnits=\"userSpaceOnUse\"><stop offset=\"0\" stop-opacity=\".3\"/><stop offset=\".071\" stop-opacity=\".2\"/><stop offset=\".321\" stop-opacity=\".1\"/><stop offset=\".623\" stop-opacity=\".05\"/><stop offset=\"1\" stop-opacity=\"0\"/></linearGradient><linearGradient id=\"tcaz2\" x1=\"-1027.165\" x2=\"-997.482\" y1=\"147.642\" y2=\"68.561\" gradientTransform=\"matrix(1 0 0 -1 1075 158)\" gradientUnits=\"userSpaceOnUse\"><stop offset=\"0\" stop-color=\"#3ccbf4\"/><stop offset=\"1\" stop-color=\"#2892df\"/></linearGradient></defs><path fill=\"url(#tcaz0)\" d=\"M33.338 6.544h26.038l-27.03 80.087a4.152 4.152 0 0 1-3.933 2.824H8.149a4.145 4.145 0 0 1-3.928-5.47L29.404 9.368a4.152 4.152 0 0 1 3.934-2.825z\"/><path fill=\"#0078d4\" d=\"M71.175 60.261h-41.29a1.911 1.911 0 0 0-1.305 3.309l26.532 24.764a4.171 4.171 0 0 0 2.846 1.121h23.38z\"/><path fill=\"url(#tcaz1)\" d=\"M33.338 6.544a4.118 4.118 0 0 0-3.943 2.879L4.252 83.917a4.14 4.14 0 0 0 3.908 5.538h20.787a4.443 4.443 0 0 0 3.41-2.9l5.014-14.777 17.91 16.705a4.237 4.237 0 0 0 2.666.972H81.24L71.024 60.261l-29.781.007L59.47 6.544z\"/><path fill=\"url(#tcaz2)\" d=\"M66.595 9.364a4.145 4.145 0 0 0-3.928-2.82H33.648a4.146 4.146 0 0 1 3.928 2.82l25.184 74.62a4.146 4.146 0 0 1-3.928 5.472h29.02a4.146 4.146 0 0 0 3.927-5.472z\"/></svg>"};

function parseHash() {
  const p = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  return p;
}
function go(h) { if (location.hash !== h) location.hash = h; else route(); }
window.addEventListener("hashchange", route);

async function route() {
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

function renderSide(p) {
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

// ---------------- 区域 ----------------
const regionOf = (acc) => localStorage.getItem("tc_region_" + acc.id) || acc.region || "";
async function regionSelect(acc, onChange) {
  if (NOREG(acc)) return "";
  const id = "rg" + acc.id;
  setTimeout(async () => {
    const sel = document.getElementById(id);
    if (!sel) return;
    try {
      const rs = await api(`/accounts/${acc.id}/regions`);
      const cur = regionOf(acc);
      sel.innerHTML = rs.map((r) => `<option ${r === cur ? "selected" : ""}>${esc(r)}</option>`).join("");
      if (!rs.includes(cur)) sel.insertAdjacentHTML("afterbegin", `<option selected>${esc(cur)}</option>`);
    } catch (e) { /* 保持默认 */ }
    sel.onchange = () => { localStorage.setItem("tc_region_" + acc.id, sel.value); onChange(); };
  });
  return `<select id="${id}" title="区域"><option>${esc(regionOf(acc))}</option></select>`;
}
const rq = (acc) => (NOREG(acc) ? "" : `region=${encodeURIComponent(regionOf(acc))}`);

// ---------------- 总览 ----------------
async function pageHome() {
  if (!ACCOUNTS.length) {
    view.innerHTML = `<div class="card empty">还没有云账号。<br><br><a class="btn primary" href="#/accounts">添加云账号</a></div>`;
    return;
  }
  view.innerHTML = `<div id="expAlerts"></div><div class="card" id="hh"><div class="bar" style="margin:0"><h3 class="grow" style="margin:0">🩺 账号健康度</h3>
    <a class="btn sm" href="#/health">详情</a></div><div id="hhl" class="chips"><span class="spin"></span></div></div><div class="grid">${ACCOUNTS.map((a) => `
    <div class="card"><div class="inst"><div class="hd"><span class="dot ${a.provider}"></span><b>${esc(a.name)}</b>
    <span class="badge">${PNAME[a.provider]}</span></div>
    <div class="kv"><span>区域</span><span>${esc(regionOf(a) || "-")}</span><span>实例</span><span id="cnt${a.id}"><span class="spin"></span></span>
    ${a.cloud_created_at ? `<span>存活</span><span>${ageText(a)}</span>` : ""}</div>
    <a class="btn sm" href="#/${a.provider}/${a.id}">进入管理</a></div></div>`).join("")}</div>`;
  loadExpiryAlerts($("#expAlerts"));
  api("/account-health").then((l) => {
    $("#hhl").innerHTML = l.map((h) => `<a class="chip" href="#/health"><span class="dot ${h.provider}"></span>${esc(h.name)}
      ${h.score == null ? `<span class="muted">未检测</span>` : `<span class="hs ${h.level}">${h.score}</span>`}</a>`).join("");
  }).catch(() => ($("#hhl").innerHTML = `<span class="muted">读取失败</span>`));
  for (const a of ACCOUNTS) {
    api(`/accounts/${a.id}/instances?${rq(a)}`).then((l) => {
      const run = l.filter((i) => i.state === "running").length;
      const el = document.getElementById("cnt" + a.id); if (el) el.textContent = `${l.length} 台（运行 ${run}）`;
    }).catch((e) => { const el = document.getElementById("cnt" + a.id); if (el) el.textContent = "查询失败：" + e.message.slice(0, 60); });
  }
}

// ---------------- 账号页 ----------------
// 标签栏横向滚动：切换标签重绘后，恢复原来的滚动位置，并保证选中的标签可见（手机上标签较多时会横向滚动）
const TAB_SCROLL = {};
function keepTabVisible(bar, key, prev) {
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
async function pageAccount(acc, tab) {
  const tabs = `<div class="tabs">${TABS[acc.provider].map(([k, l]) =>
    `<a href="#/${acc.provider}/${acc.id}/${k}" class="${k === tab ? "on" : ""}">${l}</a>`).join("")}</div>`;
  const prevScroll = TAB_SCROLL[acc.provider] || 0;
  view.innerHTML = tabs + `<div id="tab"></div>`;
  keepTabVisible(view.querySelector(".tabs"), acc.provider, prevScroll);
  const box = $("#tab");
  const fn = {
    instances: tabInstances, ec2: tabInstances, vms: tabInstances, lightsail: tabLightsailV16,
    storage: tabOciStorage, objects: (a, b) => tabOciObjects(a, b), traffic: tabOciTraffic, regionsub: tabOciRegionSub,
    create: tabOciCreate, snatch: tabOciSnatch, cloudfront: tabCloudFront, quota: tabQuota, recycle: tabRecycle, billing: tabBilling,
    limits: tabOciLimits, regions: tabAwsRegions, azcreate: tabAzCreate, rgs: tabAzRgs, azquota: tabAzQuota,
    subscription: tabAzSubscription, secgroup: tabOciSecGroup, foundry: tabAzFoundry,
  }[tab] || TAB_FNS_EXTRA[tab];
  await fn(acc, box);
}

function instOps(acc, kind) {
  const ops = [["start", "启动"], ["stop", acc.provider === "azure" ? "停止(释放)" : "停止"], ["reboot", "重启"], ["changeip", "换 IP"]];
  if (acc.provider === "oci") ops.push(["ipv6", "加 IPv6"], ["delipv6", "删 IPv6"], ["resize", "改配置"], ["rename", "改名"], ["bootvol", "引导卷"],
    ["security", "安全列表"]);
  else if (kind !== "lightsail") ops.push(["rename", "改名"]);   // v1.5：Azure / AWS EC2 也可改名（Lightsail 不支持改名）
  if (kind !== "lightsail") ops.push(["openport", "开放端口"]);   // v1.5：三家云都有（来源 0.0.0.0/0，二次确认）
  if (acc.provider !== "oci") ops.push(["traffic", "流量守护"]);   // OCI 的流量守护统一在「流量」标签里管理
  if (acc.provider === "azure") ops.push(["resize", "改大小"]);
  if (kind !== "lightsail") ops.push(["migrate", "迁移"]);
  ops.push(["dns", "绑定域名"], ["monitor", "监控"], ["terminate", acc.provider === "azure" || kind === "lightsail" ? "删除" : "终止"]);
  return v16Ops(acc, kind, ops);   // v1.6：附加 IP / 500M / 磁盘 / 防火墙 / IP 质量 / 重装系统
}
// v1.5：改名同步主机名 —— 只通过云厂商 Run Command 执行固定命令，不走 SSH
const RENAME_HOSTNAME_TIP = "Azure 直接生效；OCI 需开启 Oracle Cloud Agent 的 Run Command 插件；AWS 需 SSM 托管；重新登录 SSH 后可见。";
function renameResult(r) {
  const h = r && r.hostname;
  if (!h || h.status === "ok") return toast(h ? "已改名，系统主机名已同步" : "已改名");
  if (h.status === "pending") return toast(`已改名。${h.message || "主机名同步已下发"}`);
  if (!h.manual_cmd) return toast(`已改名。主机名未同步：${h.message || ""}`, h.status === "failed");
  modal(h.status === "failed" ? "已改名，主机名同步失败" : "已改名，主机名未自动同步",
    `<p>${esc(h.message || "")}</p><p class="muted">可 SSH 登录后手动执行：</p>
    <textarea id="hnCmd" readonly rows="4" class="mono" onclick="this.select()">${esc(h.manual_cmd)}</textarea>
    <button class="btn sm" id="hnCopy">复制命令</button>`, null, "知道了");
  const b = document.getElementById("hnCopy");
  if (b) b.onclick = async () => {
    const t = document.getElementById("hnCmd");
    try { await navigator.clipboard.writeText(t.value); toast("已复制"); } catch (_) { t.select(); document.execCommand("copy"); toast("已复制"); }
  };
}
function instCard(acc, i, kind) {
  const ip6 = (i.ipv6 || []).join("<br>") || "-";
  const extra = [];
  if (acc.provider === "oci") extra.push(["配置", `${esc(i.shape)} ${i.ocpus ?? ""}C/${i.memory_gb ?? ""}G`]);
  else extra.push(["规格", esc(i.shape)]);
  if (kind === "lightsail") extra.push(["镜像", esc(i.blueprint)], ["静态IP", i.static_ip ? "是" : "否"]);
  if (acc.provider === "azure") extra.push(["资源组", esc(i.resource_group)]);
  const ops = instOps(acc, kind);
  const inl = ops.filter(([o]) => INLINE_OPS.includes(o));
  const more = ops.length > inl.length;
  return `<div class="card inst" data-id="${esc(i.id)}"><div class="hd"><b title="${esc(i.id)}">${esc(i.name)}</b>
    <span class="badge ${esc(i.state)}">${esc(i.state)}</span></div>
    <div class="kv kv2"><span>公网</span><span class="mono">${esc(i.public_ip || "-")}</span>
    <span>内网</span><span class="mono">${esc(i.private_ip || "-")}</span>
    ${extra.map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join("")}
    <span>可用区</span><span>${esc(i.zone || "-")}</span>
    ${ip6 !== "-" ? `<span>IPv6</span><span class="mono wide">${ip6}</span>` : ""}</div>
    <div class="ops">${inl.map(([o, l]) => opBtn(o, l, i)).join("")}${more ? `<button class="btn sm" data-more aria-label="更多操作">更多 ▾</button>` : ""}</div></div>`;
}

async function tabInstances(acc, box, kind = "vm") {
  const reload = () => tabInstances(acc, box, kind);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">刷新</button>
    ${kind === "lightsail" ? `<button class="btn primary" id="lsNew">创建 Lightsail</button>` : ""}
    ${acc.provider === "aws" && kind === "vm" ? `<button class="btn primary" id="ec2New">创建 EC2</button>` : ""}
    <span class="grow"></span><span class="muted" id="info"></span>
    <div class="seg desk-only" id="ivw" title="视图（桌面宽度可用，选择会记住）"><button class="${instView() === "card" ? "on" : ""}" data-v="card">▦ 卡片</button><button class="${instView() === "table" ? "on" : ""}" data-v="table">☰ 表格</button></div></div>
    <div class="grid" id="list"><div class="empty"><span class="spin"></span></div></div>`;
  $("#rf", box).onclick = reload;
  box.querySelectorAll("#ivw [data-v]").forEach((b) => (b.onclick = () => { localStorage.setItem("tc_inst_view", b.dataset.v); reload(); }));
  if (kind === "lightsail") $("#lsNew", box).onclick = () => lightsailCreate(acc, reload);
  if (acc.provider === "aws" && kind === "vm") $("#ec2New", box).onclick = () => ec2Create(acc, reload);
  let list;
  try { list = await api(`/accounts/${acc.id}/instances?kind=${kind}&${rq(acc)}`); }
  catch (e) { $("#list", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#info", box).textContent = `${list.length} 台`;
  const useTable = instView() === "table" && isDesktop() && list.length;
  const lb = $("#list", box);
  lb.className = useTable ? "card itable" : "grid";
  lb.innerHTML = !list.length ? `<div class="empty">该区域没有实例</div>` : useTable ? instTable(acc, list, kind) : list.map((i) => instCard(acc, i, kind)).join("");
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

async function instOp(acc, inst, op, kind, btn, reload) {
  const base = { instance_id: inst.id, region: regionOf(acc) || undefined, kind, name: inst.name };
  const names = OP_NAMES[acc.provider] || { start: "启动", stop: "停止", reboot: "重启", terminate: "终止" };
  if (V16_OPS[op]) return V16_OPS[op](acc, inst, base, kind, btn, reload);
  if (names[op]) {
    const danger = op === "terminate";
    const msg = danger ? `⚠️ 确定要<b>${acc.provider === "azure" || kind === "lightsail" ? "删除" : "终止"}</b>「${esc(inst.name)}」吗？此操作不可恢复，引导卷/磁盘将一并删除。`
      : `确定${names[op]}「${esc(inst.name)}」？` + (op === "stop" && acc.provider === "azure" ? "<br><span class='muted'>Azure 将执行 deallocate，释放计算资源（动态公网 IP 会变化）。</span>" : "");
    const keep = danger && acc.provider === "oci";
    const ok = await modal(names[op], `<p>${msg}</p>${keep ? `<label><input type="checkbox" name="preserve_boot_volume" style="width:auto"> 保留引导卷（可稍后挂回或救援，保留期间计费）</label>` : ""}`,
      (bg) => form(bg), "确认", danger);
    if (!ok) return;
    await act(btn, () => post(`/accounts/${acc.id}/instances/action`, { ...base, action: op, confirm: danger, preserve_boot_volume: !!ok.preserve_boot_volume }), `${names[op]}指令已发送`);
    setTimeout(reload, 2500);
  } else if (op === "changeip") {
    let body = `<p>为「${esc(inst.name)}」更换公网 IP？当前：<code>${esc(inst.public_ip || "-")}</code></p>`;
    if (acc.provider === "aws" && kind === "vm") body += `<label>方式</label><select name="mode"><option value="auto">自动（有弹性 IP 则重分配，否则停机换 IP）</option>
      <option value="eip">重分配弹性 IP（不停机）</option><option value="stopstart">停机再启动（会中断服务）</option></select>`;
    if (acc.provider === "azure") body += `<p class="muted">将删除旧 Public IP 并新建同 SKU 的 PIP，期间网络中断约 1 分钟。</p>`;
    if (kind === "lightsail") body += `<p class="muted">通过分配新静态 IP 并释放旧静态 IP 实现（未绑定的静态 IP 会计费，面板会自动释放旧的）。</p>`;
    const oci = acc.provider === "oci";
    body += `<label>目标网段（可选，逗号分隔；<code>!</code> 开头表示排除，可混用）</label>
      <input name="cidrs" placeholder="${oci ? "如 129.146.0.0/16, !129.146.10.0/24；留空=换一次即可" : "如 !10.0.0.0/8；留空=换一次即可"}">
      <label>最多尝试次数（指定网段或质量要求时生效${oci ? "" : "，AWS/Azure 每次较慢，上限 20"}）</label><input name="max_tries" type="number" min="1" max="${oci ? 100 : 20}" value="${oci ? 20 : 5}">` + QUALITY_FIELDS;
    try { const u = await api(`/accounts/${acc.id}/ip-change-usage`); body += `<p class="muted">今日已换 IP：手动 ${u.manual_used} 次 · 自动 ${u.auto_used}/${u.limit} 次（自动换 IP 每账号每天上限可在设置里修改）</p>`; } catch (_) { /* ignore */ }
    body += `<p class="muted">已在「DNS 联动」绑定域名的实例，换 IP 后会自动更新 Cloudflare 解析。</p>`;
    const r = await modal("更换 IP", body, (bg) => post(`/accounts/${acc.id}/instances/change-ip`, { ...base, ...form(bg) }), "更换");
    if (r) {
      if (r.task_id) toast(`已创建任务 #${r.task_id}，完成后会推送通知`);
      else toast(`新 IP：${r.new_ip}`);
      setTimeout(reload, 1500);
    }
  } else if (op === "migrate") {
    migrateDialog(acc, inst);
  } else if (op === "ipv6") {
    if (!(await confirmBox("一键 IPv6", "将按需为所在 VCN 开启 IPv6、给子网分配 /64、添加 ::/0 路由和出站规则，再给实例分配 IPv6。确定？"))) return;
    await act(btn, () => post(`/accounts/${acc.id}/oci/ipv6`, base), (r) => `已创建任务 #${r.task_id}，完成后推送通知`);
  } else if (op === "delipv6") {
    if (!(await confirmBox("删除 IPv6", `⚠️ 将删除「${esc(inst.name)}」主网卡上的<b>全部 IPv6 地址</b>（VCN / 子网的 IPv6 配置保留）。确定？`, true))) return;
    if (await act(btn, () => post(`/accounts/${acc.id}/oci/ipv6/delete`, { ...base, confirm: true }), (r) => `已删除：${r.deleted.join(", ")}`)) setTimeout(reload, 1500);
  } else if (op === "rename") {
    const r = await modal("实例改名", `<input name="new_name" value="${esc(inst.name)}">
      <label><input type="checkbox" name="sync_hostname" style="width:auto" checked> 同步修改系统主机名（SSH 显示）</label>
      <p class="muted">${RENAME_HOSTNAME_TIP}</p>`, (bg) => post(`/accounts/${acc.id}/instances/rename`, { ...base, ...form(bg) }), "保存");
    if (r) { renameResult(r); reload(); }
  } else if (op === "bootvol") {
    let bv;
    try { toast("读取引导卷…"); bv = await api(`/accounts/${acc.id}/oci/boot-volume?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
    const r = await modal("引导卷", `<div class="kv"><span>名称</span><span>${esc(bv.name)}</span><span>大小</span><span>${bv.size_gb} GB</span>
      <span>性能</span><span>${bv.vpus_per_gb} VPU/GB</span><span>状态</span><span>${esc(bv.state)}</span></div>
      <div class="row2"><div><label>扩容到 (GB，只能变大)</label><input name="size_gb" type="number" min="${bv.size_gb}" placeholder="${bv.size_gb}"></div>
      <div><label>性能 VPU/GB</label><select name="vpus_per_gb">${[10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120].map((v) => `<option ${v === bv.vpus_per_gb ? "selected" : ""}>${v}</option>`).join("")}</select></div></div>
      <label><input type="checkbox" name="grow" style="width:auto" checked> 扩容后通过 Run Command 自动扩展根分区（需 Oracle Cloud Agent 插件）</label>
      <p class="muted">10 = 均衡（免费额度内），20+ 为高性能，按量计费。总免费额度 200GB。</p>`,
      (bg) => post(`/accounts/${acc.id}/oci/boot-volume`, { ...base, ...form(bg) }), "提交");
    if (r) toast(r.grow ? `已扩容；扩分区：${r.grow.status === "ok" ? "完成" : r.grow.message}` : (r.hint || "已提交"));
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
      const r = await modal("修改配置", `<p class="muted">Flex 实例可在线调整（部分系统会自动重启）。</p><div class="row2">
        <div><label>OCPU</label><input name="ocpus" type="number" step="1" min="1" value="${inst.ocpus || 1}"></div>
        <div><label>内存 (GB)</label><input name="memory_gb" type="number" min="1" value="${inst.memory_gb || 6}"></div></div>`,
        (bg) => post(`/accounts/${acc.id}/instances/resize`, { ...base, ...form(bg) }), "提交");
      if (r) toast(`已创建任务 #${r.task_id}`);
    } else {
      let sizes = [];
      try { sizes = await api(`/accounts/${acc.id}/azure/sizes?instance_id=${encodeURIComponent(inst.id)}`); } catch (e) { return toast(e.message, true); }
      const r = await modal("调整 VM 大小", `<p class="muted">调整大小会重启 VM。当前：${esc(inst.shape)}</p><label>新大小</label><select name="size">
        ${sizes.map((s) => `<option value="${esc(s.name)}" ${s.name === inst.shape ? "selected" : ""}>${esc(s.name)} · ${s.cores}C/${(s.memory_mb / 1024).toFixed(1)}G</option>`).join("")}</select>`,
        (bg) => post(`/accounts/${acc.id}/instances/resize`, { ...base, ...form(bg) }), "提交");
      if (r) toast(`已创建任务 #${r.task_id}`);
    }
  } else if (op === "monitor") {
    const r = await modal("加入监控", `<p>监控「${esc(inst.name)}」，发现非面板操作导致的停止/终止时推送 Telegram 告警。</p>
      <label><input type="checkbox" name="auto_start" style="width:auto"> 异常停止时自动启动</label>
      <label>IP 连通检测端口（0=不检测，常用 22）</label><input name="check_port" type="number" min="0" max="65535" value="0">
      ${NO_CHANGE_IP.has(acc.provider) ? `<p class="muted">该云不支持换 IP：连不上时只推送告警。</p>` : `<label><input type="checkbox" name="auto_change_ip" style="width:auto"> 连续 3 次连不上时自动换 IP（并更新已绑定域名）</label>`}
      <p class="muted">检测从面板所在服务器发起；若面板与实例跨境，结果反映的是这条线路的连通性。</p>`,
      (bg) => post(`/monitors`, { account_id: acc.id, instance_id: inst.id, region: regionOf(acc) || null, kind, name: inst.name, state: inst.state, public_ip: inst.public_ip, ...form(bg) }), "保存");
    if (r) toast("已加入监控");
  }
}

// ---------------- Lightsail ----------------
const tabLightsail = (acc, box) => tabInstances(acc, box, "lightsail");
async function lightsailCreate(acc, reload) {
  let o;
  try { toast("正在读取镜像与套餐…"); o = await api(`/accounts/${acc.id}/lightsail/options?${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  const d = SETTINGS.default_create?.lightsail || {};
  const r = await modal("创建 Lightsail 实例", `<label>名称</label><input name="name" value="ls-${Date.now().toString(36)}">
    <label>可用区</label><select name="zone">${o.zones.map((z) => `<option ${z === d.zone ? "selected" : ""}>${esc(z)}</option>`).join("")}</select>
    <label>系统镜像</label><select name="blueprint">${o.blueprints.map((b) => `<option value="${esc(b.id)}" ${b.id === d.blueprint ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select>
    <label>套餐</label><select name="bundle">${o.bundles.map((b) => `<option value="${esc(b.id)}" ${b.id === d.bundle ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select>
    <label>网络</label><select name="ip_type"><option value="dualstack">IPv4 + IPv6</option><option value="ipv6" ${d.ip_type === "ipv6" ? "selected" : ""}>仅 IPv6（更便宜）</option></select>
    ${await loginFields()}<div class="bar">${saveDefaultBtn("lightsail")}</div>`,
    (bg) => post(`/accounts/${acc.id}/lightsail/create`, { ...form(bg), region: regionOf(acc) }), "创建");
  if (r) { showCreated(r); setTimeout(reload, 3000); }
}

// ---------------- OCI 创建 / 抢机 ----------------
// OCI 规格：标明是否 Always Free（免费额度只在主区域有效）
const OCI_SHAPES = [
  ["VM.Standard.A1.Flex", "ARM · ✅ Always Free（免费号合计 2 OCPU / 12 GB，付费号 4 / 24）"],
  ["VM.Standard.E2.1.Micro", "AMD 1/8 OCPU · 1 GB · ✅ Always Free（最多 2 台）"],
  ["VM.Standard.E4.Flex", "AMD · 💰 付费，非 Always Free"],
  ["VM.Standard3.Flex", "Intel · 💰 付费，非 Always Free"],
];
const ociShapeOpts = (cur, only) => OCI_SHAPES.filter(([v]) => !only || only.includes(v))
  .map(([v, t]) => `<option value="${v}" ${v === cur ? "selected" : ""}>${v} — ${t}</option>`).join("");
// v1.5：OCI「系统 / 系统版本」联动下拉。内置列表先显示，再按规格异步拉 /oci/os-versions 替换；"" = 最新（_pick_image 取最新镜像）
const OCI_OS_VERSIONS = { "Canonical Ubuntu": ["24.04", "22.04", "20.04"], "Oracle Linux": ["9", "8"] };
function ociOsOpts(cur) {
  const os = OCI_OS_VERSIONS[cur] ? cur : "Canonical Ubuntu";
  return Object.keys(OCI_OS_VERSIONS).map((s) => `<option ${s === os ? "selected" : ""}>${s}</option>`).join("");
}
function ociVerOpts(os, cur, map) {
  const vs = ["", ...((map && map[os]) || OCI_OS_VERSIONS[os] || []).filter(Boolean)];
  if (cur && !vs.includes(cur)) vs.push(cur);   // 默认值里保存的版本不在列表里：临时加成一个选项
  return vs.map((v) => `<option value="${esc(v)}" ${v === (cur || "") ? "selected" : ""}>${v ? esc(v) : "最新"}</option>`).join("");
}
const ociOsFields = (d) => `<div><label>系统</label><select name="os">${ociOsOpts(d.os)}</select></div>
    <div><label>系统版本</label><select name="os_version">${ociVerOpts(OCI_OS_VERSIONS[d.os] ? d.os : "Canonical Ubuntu", d.os_version || "")}</select></div>`;
// keep: "always" 保留当前值（不在列表里就临时加）；"present" 只在新列表里有时保留；其他 = 回到「最新」
function refillOciVer(box, keep) {
  const os = box.querySelector("[name=os]"), sel = box.querySelector("[name=os_version]");
  if (!os || !sel) return;
  let cur = keep ? sel.value : "";
  const list = (box._osv && box._osv[os.value]) || OCI_OS_VERSIONS[os.value] || [];
  if (keep === "present" && cur && !list.includes(cur)) cur = "";
  sel.innerHTML = ociVerOpts(os.value, cur, box._osv);
}
async function loadOciVersions(box, keep = "present") {
  const acc = box._ociAcc, shape = box.querySelector("[name=shape]");
  if (!acc || !shape) return;
  const req = (box._osvReq = (box._osvReq || 0) + 1);
  try {
    const m = await api(`/accounts/${acc.id}/oci/os-versions?shape=${encodeURIComponent(shape.value)}&${rq(acc)}`);
    if (req !== box._osvReq || !m || !Object.keys(m).length) return;
    box._osv = m; refillOciVer(box, keep);
  } catch (_) { /* 失败继续用内置列表 */ }
}
function wireOciOs(box, acc) { if (!box) return; box._ociAcc = acc; loadOciVersions(box, "always"); }
document.addEventListener("change", (e) => {
  const box = e.target.closest && e.target.closest("[data-oci-os]");
  if (!box) return;
  if (e.target.name === "os") refillOciVer(box);
  else if (e.target.name === "shape") { box._osv = null; refillOciVer(box, "present"); loadOciVersions(box); }   // 换规格（A1=aarch64 / E2=x86）重新拉
});
function ociCreateFields(d) {
  d = d || {};
  return `<div class="row2" data-oci-os>
    <div><label>实例名称</label><input name="name" value="${esc(d.name || "oci-" + Date.now().toString(36))}"></div>
    <div><label>规格</label><select name="shape">
      ${ociShapeOpts(d.shape)}</select></div>
    <div><label>OCPU（Flex）</label><input name="ocpus" type="number" min="1" value="${esc(d.ocpus || 4)}"></div>
    <div><label>内存 GB（Flex）</label><input name="memory_gb" type="number" min="1" value="${esc(d.memory_gb || 24)}"></div>
    <div><label>引导卷 GB</label><input name="disk_gb" type="number" min="47" value="${esc(d.disk_gb || 50)}"></div>
    ${ociOsFields(d)}
    <div><label>可用域（留空=第一个）</label><input name="ad" value="${esc(d.ad || "")}"></div></div>
    <label>子网 OCID（留空=自动选择公有子网）</label><input name="subnet_id" value="${esc(d.subnet_id || "")}">
    <label>SSH 公钥（可选）</label><textarea name="ssh_key" placeholder="ssh-ed25519 AAAA...">${esc(d.ssh_key || "")}</textarea>
    <label><input type="checkbox" name="ipv6" style="width:auto" ${d.ipv6 ? "checked" : ""}> 分配 IPv6（子网需已启用 IPv6）</label>
    <p class="muted">可用域填 auto = 抢机时每次轮换可用域。没有公有子网时会自动创建 VCN/子网/网关（默认仅放行 22）。</p>`;
}
async function tabOciCreate(acc, box) {
  box.innerHTML = `<div class="bar">${await regionSelect(acc, () => tabOciCreate(acc, box))}<span class="muted">参数默认值可在「设置 → 默认创建参数」修改</span></div>
    <div class="card" id="f">${ociCreateFields(SETTINGS.default_create?.oci)}${await loginFields()}<div class="bar" style="margin-top:14px"><button class="btn primary" id="go">立即创建</button>${saveDefaultBtn("oci")}</div></div>`;
  wireOciOs($("[data-oci-os]", box), acc);
  $("#go", box).onclick = async (e) => { const r = await act(e.target, () => post(`/accounts/${acc.id}/oci/create`, { region: regionOf(acc), create: form($("#f", box)) })); if (r) showCreated(r); };
}
async function tabOciSnatch(acc, box) {
  box.innerHTML = `<div class="bar">${await regionSelect(acc, () => tabOciSnatch(acc, box))}</div>
    <div class="card" id="f"><h3>自动抢机</h3><p class="muted">容量不足时按间隔持续重试，成功/失败/停止都会推送 Telegram。任务在本机后台运行，凭证不出服务器。</p>
    ${ociCreateFields(SETTINGS.default_create?.oci)}${await loginFields()}
    <label>同时为这些 OCI 账号各起一个任务（批量抢机）</label>
    <div class="chips">${ACCOUNTS.filter((a) => a.provider === "oci").map((a) => `<label class="chip"><input type="checkbox" data-acc="${a.id}" ${a.id === acc.id ? "checked" : ""} style="width:auto"> ${esc(a.name)}</label>`).join("")}</div>
    <div class="row2"><div><label>重试间隔（秒，≥30）</label><input name="interval" type="number" min="30" value="60"></div>
    <div><label>最大尝试次数（0=不限）</label><input name="max_attempts" type="number" min="0" value="0"></div></div>
    <div class="bar" style="margin-top:14px"><button class="btn primary" id="go">开始抢机</button><a class="btn" href="#/tasks">查看任务</a>${saveDefaultBtn("oci")}</div></div>`;
  wireOciOs($("[data-oci-os]", box), acc);
  $("#go", box).onclick = (e) => {
    const f = form($("#f", box));
    const { interval, max_attempts, ...create } = f;
    const account_ids = [...box.querySelectorAll("[data-acc]:checked")].map((x) => +x.dataset.acc);
    if (!account_ids.length) return toast("至少选择一个账号", true);
    act(e.target, () => post(`/accounts/${acc.id}/oci/snatch`, { region: regionOf(acc), interval, max_attempts, create, account_ids }),
      (r) => `已启动 ${r.task_ids.length} 个抢机任务：#${r.task_ids.join(", #")}`);
  };
}

// ---------------- 配额 ----------------
async function tabQuota(acc, box, refresh = false) {
  box.innerHTML = `<div class="card"><span class="spin"></span> 正在逐区域查询（串行，约 10–30 秒）…</div>`;
  let q;
  try { q = await api(`/accounts/${acc.id}/quotas${refresh ? "?refresh=true" : ""}`); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const v = q.standard_vcpu, cf = q.cloudfront_distributions || {};
  box.innerHTML = `<div class="grid">
    <div class="card"><h3>Standard vCPU 上限</h3><div class="big">${v ? esc(v.value) : "-"} ${esc(v?.unit || "")}</div>
      <div class="muted">全区域最大值，来自 ${esc(v?.region || "-")}（L-1216C47A）</div></div>
    <div class="card"><h3>CloudFront 分发数上限</h3><div class="big">${cf.value ?? "-"} ${esc(cf.unit || "")}</div>
      <div class="muted">每账号（L-24B04930）${cf.default ? "· AWS 默认值" : ""}${cf.error ? " · " + esc(cf.error) : ""}</div></div></div>
    <div class="card"><div class="bar"><h3 class="grow" style="margin:0">各区域 vCPU</h3><span class="muted">更新于 ${esc(q.updated_at)}（缓存 6 小时）</span>
    <button class="btn sm" id="rf">重新查询</button></div>
    <table><tr><th>区域</th><th>vCPU</th></tr>${q.per_region.map((r) => `<tr><td>${esc(r.region)}</td><td>${r.value ?? `<span class="muted">${esc(r.error || "-")}</span>`}</td></tr>`).join("")}</table></div>`;
  $("#rf", box).onclick = () => tabQuota(acc, box, true);
}

// ---------------- 回收站估算（AWS 闲置仍计费资源） ----------------
async function tabRecycle(acc, box) {
  const reload = () => tabRecycle(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">重新扫描</button></div>
    <div id="rb"><div class="card"><span class="spin"></span> 正在扫描闲置资源（EC2/Lightsail 免费 API）…</div></div>`;
  $("#rf", box).onclick = reload;
  const out = $("#rb", box);
  let r;
  try { r = await api(`/accounts/${acc.id}/recycle?${rq(acc)}`); } catch (e) { out.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  out.innerHTML = `<div class="grid">
    <div class="card"><h3>闲置资源月费估算</h3><div class="big">$${esc(r.monthly_total)}</div>
      <div class="muted">区域 ${esc(r.region)} · ${r.items.length} 项 · 按公示单价估算，实际以账单为准</div></div>
    <div class="card"><h3>账单参考（缓存）</h3><div class="big">${r.month_to_date == null ? "—" : "$" + esc(r.month_to_date)}</div>
      <div class="muted">本月已产生 · 数据更新于 ${esc(r.billing_updated_at)}（不调用 Cost Explorer）</div>
      ${r.credit_remaining != null ? `<div class="muted">Credit 余 $${esc(r.credit_remaining)}${r.credit_months_for_idle ? `，仅闲置资源可再扣约 ${esc(r.credit_months_for_idle)} 个月` : ""}</div>` : ""}</div></div>
    <div class="card"><h3>明细</h3>
    ${r.items.length ? `<table><tr><th>资源</th><th>说明</th><th style="text-align:right">月费估算</th><th>建议</th></tr>
    ${r.items.map((i) => `<tr><td><b>${esc(i.name)}</b><div class="muted mono">${esc(i.id)}</div></td><td>${esc(i.detail)}</td>
    <td style="text-align:right">$${esc(i.monthly)}</td><td class="muted">${esc(i.tip)}</td></tr>`).join("")}</table>` : `<div class="empty">没有闲置计费资源 🎉</div>`}</div>`;
}

// ---------------- 账单 ----------------
async function tabBilling(acc, box, force = false) {
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let b;
  try { b = await api(`/accounts/${acc.id}/billing${force ? "?force=true" : ""}`); }
  catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div><div id="credbox"></div>`; creditCard(acc, $("#credbox", box)); return; }
  const isAws = acc.provider === "aws";
  let html = `<div class="grid"><div class="card"><h3>本月费用</h3><div class="big">${b.no_cache ? "—" : esc(b.total)} <span style="font-size:14px">${esc(b.currency)}</span></div>
    <div class="muted">${esc(b.period)} · 数据更新于 ${esc(b.updated_at)}</div>
    ${b.no_cache ? `<div class="muted">尚无缓存：将在 ${esc(b.next_refresh)} 自动查询，或点手动刷新（收费）</div>` : ""}
    ${isAws ? `<div class="muted">AWS 账单每月仅在 15 号与月末自动查询（Cost Explorer $0.01/次），下次：${esc(b.next_refresh)}；本月已调用 ${esc(b.ce_calls_this_month)} 次</div>
    <div class="bar" style="margin-top:8px"><button class="btn sm" id="force">手动刷新（约 $0.02）</button></div>` : ""}</div>`;
  if (isAws) {
    const c = b.credits;
    html += `<div class="card"><h3>Credit 余额</h3><div class="big">${b.no_cache ? "—" : "$" + esc(c.remaining)}</div>
      <div class="muted">总额 $${esc(c.total)} − 已抵扣 $${esc(c.used)}（CE 自最早 Credit 起始日累计）</div></div>`;
  }
  html += `</div><div class="card"><h3>按服务</h3>${b.services.length ? `<table><tr><th>服务</th><th style="text-align:right">金额</th></tr>
    ${b.services.map((s) => `<tr><td>${esc(s.service)}</td><td style="text-align:right">${esc(s.amount)}</td></tr>`).join("")}</table>` : `<div class="muted">本月暂无费用</div>`}</div>`;
  html += `<div id="credbox"><div class="card"><span class="spin"></span> 读取 Credit…</div></div>`;
  box.innerHTML = html;
  creditCard(acc, $("#credbox", box));   // v1.4：Credit 与教育优惠（三家云通用）
  if (!isAws) return;
  $("#force", box).onclick = async () => {
    if (await confirmBox("手动刷新 AWS 账单", "这会调用 Cost Explorer API（每次 $0.01，本次约 1–2 次）。确定？")) tabBilling(acc, box, true);
  };
}

// ---------------- 云账号管理 ----------------
const CRED_FIELDS = {
  oci: [["user", "用户 OCID"], ["tenancy", "租户 OCID"], ["fingerprint", "API Key 指纹"], ["region", "区域", "ap-tokyo-1"],
    ["key_content", "私钥 (PEM)", "", "textarea"], ["pass_phrase", "私钥密码（可选）"], ["compartment", "区间 OCID（可选，默认根区间）"], ["home_region", "主区域（账单用，可选）"],
    ["proxy", "出口代理（可选）", "http://host:port"], ["proxy_user", "代理用户名（可选）"], ["proxy_pass", "代理密码（可选）", "", "password"]],
  aws: [["access_key", "Access Key ID"], ["secret_key", "Secret Access Key", "", "password"], ["region", "默认区域", "us-east-1"], ["proxy", "出口代理（可选）", "socks5://host:port"],
    ["proxy_user", "代理用户名（可选）"], ["proxy_pass", "代理密码（可选）", "", "password"]],
  azure: [["tenant_id", "Tenant ID"], ["client_id", "Client (App) ID"], ["client_secret", "Client Secret", "", "password"], ["subscription_id", "Subscription ID"],
    ["proxy", "出口代理（可选）", "http://host:port"], ["proxy_user", "代理用户名（可选）"], ["proxy_pass", "代理密码（可选）", "", "password"]],
};
async function pageAccounts() {
  const prov = (p) => ACCOUNTS.filter((a) => a.provider === p).length;
  view.innerHTML = `<div class="bar"><button class="btn primary" id="add">添加云账号</button><button class="btn" id="batch">批量添加</button>
    <select id="tprov" title="测活范围"><option value="">全部账号</option>${PROVS.filter(prov).map((p) => `<option value="${p}">${PNAME[p]}</option>`).join("")}</select>
    <button class="btn" id="testAll">⚡ 一键测活</button><a class="btn" href="#/deleted">🗑 已删账号</a><span class="grow"></span><span class="muted" id="tsum">凭证经 Fernet 加密保存在本机 SQLite，不经过任何第三方</span></div>
    <div class="card"><table><tr><th>名称</th><th>云</th><th>默认区域</th><th>云上创建 / 存活</th><th>连通</th><th>出口代理</th><th>添加时间</th><th></th></tr>
    ${ACCOUNTS.map((a) => `<tr data-acc="${a.id}" class="${a.disabled ? "acc-off" : ""}"><td><a href="#/${a.provider}/${a.id}">${esc(a.name)}</a>${a.disabled ? ` <span class="badge failed" title="${esc(a.disabled_reason || "")}">已停用</span>` : ""}${acctTypeTag(a)}</td><td><span class="dot ${a.provider}"></span> ${PNAME[a.provider]}</td>
    <td>${esc(a.region || "-")}</td><td>${ageText(a)}</td><td class="tcell">${testCell(a)}</td><td class="mono">${esc(a.proxy || "直连")}${a.proxy_user ? `<div class="muted">${esc(a.proxy_user)}${a.proxy_pass_set ? " · ●●●" : ""}</div>` : ""}</td><td>${new Date(a.created * 1000).toLocaleString()}</td>
    <td><button class="btn sm" data-test="${a.id}">测活</button> <button class="btn sm" data-info="${a.id}">信息</button> <button class="btn sm" data-type="${a.id}">类型</button>${a.disabled ? ` <button class="btn sm" data-off="${a.id}">启用</button>` : ""} <button class="btn sm" data-edit="${a.id}">编辑</button> <button class="btn sm" data-px="${a.id}">代理</button> <button class="btn sm danger" data-del="${a.id}">删除</button></td></tr>`).join("") || `<tr><td colspan=8 class="muted">暂无</td></tr>`}</table></div>`;
  $("#add").onclick = addAccount;
  $("#batch").onclick = batchAddAccounts;
  $("#testAll").onclick = async (e) => {
    const p = $("#tprov").value;
    view.querySelectorAll("tr[data-acc]").forEach((tr) => { const a = ACCOUNTS.find((x) => x.id == tr.dataset.acc); if (!p || a.provider === p) tr.querySelector(".tcell").innerHTML = `<span class="spin"></span>`; });
    const r = await act(e.target, () => post("/accounts/test-all", { provider: p || undefined }));
    if (!r) return;
    $("#tsum").textContent = `测活完成：${r.ok}/${r.total} 连通，用时 ${(r.ms / 1000).toFixed(1)} 秒`;
    await loadAccounts();
    r.results.forEach((x) => { const tr = view.querySelector(`tr[data-acc="${x.account_id}"]`); if (tr) tr.querySelector(".tcell").innerHTML = testCell(ACCOUNTS.find((a) => a.id === x.account_id) || {}, x); });
  };
  view.querySelectorAll("[data-test]").forEach((b) => (b.onclick = async () => {
    const tr = b.closest("tr"); tr.querySelector(".tcell").innerHTML = `<span class="spin"></span>`;
    const r = await act(b, () => post(`/accounts/${b.dataset.test}/test`));
    await loadAccounts();
    tr.querySelector(".tcell").innerHTML = testCell(ACCOUNTS.find((a) => a.id == b.dataset.test) || {}, r || undefined);
  }));
  view.querySelectorAll("[data-info]").forEach((b) => (b.onclick = () => accountInfoDialog(ACCOUNTS.find((x) => x.id == b.dataset.info))));
  view.querySelectorAll("[data-type]").forEach((b) => (b.onclick = () => accountTypeDialog(ACCOUNTS.find((x) => x.id == b.dataset.type))));
  view.querySelectorAll("[data-off]").forEach((b) => (b.onclick = () => toggleDisable(ACCOUNTS.find((x) => x.id == b.dataset.off))));
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (!(await confirmBox("删除账号", "仅从面板删除凭证，不影响云上资源。确定？", true))) return;
    await act(b, () => del(`/accounts/${b.dataset.del}`), "已删除"); await loadAccounts(); route();
  }));
  view.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => editAccount(ACCOUNTS.find((x) => x.id == b.dataset.edit))));
  view.querySelectorAll("[data-px]").forEach((b) => (b.onclick = async () => {
    const a = ACCOUNTS.find((x) => x.id == b.dataset.px);
    const r = await modal("出口代理", `<p class="muted">该账号的所有云 API 请求经此代理发出（固定出口 IP、避免多号同 IP 关联）。</p>
      <p class="muted">当前：${esc(a.proxy || "直连")}${a.proxy_user ? ` · 用户 ${esc(a.proxy_user)}` : ""}${a.proxy_pass_set ? " · 已设密码" : ""}</p>
      ${proxyFields({ proxy_user: a.proxy_user, proxy_pass_set: a.proxy_pass_set })}
      ${a.proxy ? `<label><input type="checkbox" name="clear_all" style="width:auto"> 改为直连（清除代理地址、用户名和密码）</label>` : ""}`, (bg) => {
      const f = form(bg); const body = {};
      if (f.clear_all) body.proxy = "";
      else {
        if (f.proxy) body.proxy = f.proxy;
        else if (!a.proxy && (f.proxy_user || f.proxy_pass)) throw new Error("请先填写代理地址");
        if (f.proxy_user !== (a.proxy_user || "")) body.proxy_user = f.proxy_user;
        if (f.proxy_pass) body.proxy_pass = f.proxy_pass;
        if (f.proxy_pass_clear) body.proxy_pass_clear = true;
      }
      if (!Object.keys(body).length) return true;
      return api(`/accounts/${a.id}`, { method: "PATCH", body });
    }, "保存");
    if (r) { toast("已保存"); await loadAccounts(); route(); }
  }));
}
const credInput = ([k, l, ph, t]) => `<label>${l}</label>` + (t === "textarea" ? `<textarea name="c_${k}" placeholder="${esc(ph || (k === "key_content" ? "-----BEGIN PRIVATE KEY-----" : ""))}"></textarea>`
  : `<input name="c_${k}" type="${t || "text"}" placeholder="${esc(ph || "")}" autocomplete="off">`);
async function addAccount() {
  const fields = (p) => CRED_FIELDS[p].map(credInput).join("");
  const r = await modal("添加云账号", `<label>云厂商</label><select name="provider" id="np">${provOpts()}</select>
    <label>备注名称</label><input name="name" placeholder="例如 东京主号">
    <details id="smartpaste" open><summary class="muted">粘贴内容自动识别（控制台复制、环境变量、AWS CSV、Azure 门户、OCI config 都行）</summary>
    <textarea id="smarttext" placeholder="把复制的一堆内容直接贴进来，例如：&#10;Access key ID: AKIA...&#10;Secret access key: ...&#10;或 Azure 应用注册页的 应用程序(客户端) ID / 目录(租户) ID / 值 / 订阅 ID&#10;或 OCI 配置文件预览 + 私钥 PEM"></textarea>
    <select id="smartpick" style="display:none" title="识别到多个账号时选择"></select><p class="muted" id="smarthint"></p></details>
    <div id="cf">${fields("oci")}</div>
    <p class="muted" id="hint"></p>`, async (bg) => {
    const f = form(bg); const cred = {};
    for (const k in f) if (k.startsWith("c_")) cred[k.slice(2)] = f[k];
    toast("正在校验凭证…");
    return post("/accounts", ADD_BODY[f.provider] ? ADD_BODY[f.provider](f, cred, bg) : { provider: f.provider, name: f.name, cred });
  }, "校验并保存");
  if (r) { toast("账号已添加"); await loadAccounts(); go("#/accounts"); }
}
document.addEventListener("change", (e) => {
  if (e.target.id !== "np") return;
  const p = e.target.value;
  const hint = { oci: "在 OCI 控制台「我的概要信息 → API 密钥」生成。", aws: "建议使用仅含 EC2/Lightsail/CloudFront/Service Quotas/CE 权限的 IAM 用户。", azure: "az ad sp create-for-rbac --role Contributor --scopes /subscriptions/<id> 生成。", ...PROV_HINT }[p];
  $("#cf").innerHTML = CRED_FIELDS[p].map(credInput).join("");
  $("#hint").textContent = hint;
});

// ---------------- 任务 ----------------
async function pageTasks() {
  loading();
  const list = await api("/tasks");
  const TN = TASK_NAME;
  view.innerHTML = `<div class="bar"><button class="btn" id="rf">刷新</button><span class="muted">任务完成 / 失败 / 停止会自动推送 Telegram</span></div>
    <div class="card"><table><tr><th>#</th><th>类型</th><th>账号</th><th>状态</th><th>次数</th><th>信息</th><th>更新</th><th></th></tr>
    ${list.map((t) => `<tr><td>${t.id}</td><td>${TN[t.type] || esc(t.type)}</td><td>${esc(t.account_name || "-")}</td>
    <td><span class="badge ${esc(t.status)}">${esc(t.status)}</span></td><td>${t.attempts}</td><td class="mono">${esc(t.message)}</td>
    <td>${new Date(t.updated * 1000).toLocaleString()}</td>
    <td><button class="btn sm" data-log="${t.id}">日志</button> ${t.status === "running" ? `<button class="btn sm danger" data-stop="${t.id}">停止</button>` : `<button class="btn sm" data-del="${t.id}">删除</button>`}</td></tr>`).join("") || `<tr><td colspan=8 class="muted">暂无任务</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-log]").forEach((b) => (b.onclick = () => TaskDrawer.open(+b.dataset.log)));
  $("#rf").onclick = pageTasks;
  view.querySelectorAll("[data-stop]").forEach((b) => (b.onclick = async () => { await act(b, () => post(`/tasks/${b.dataset.stop}/stop`), "已停止"); pageTasks(); }));
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { await del(`/tasks/${b.dataset.del}`); pageTasks(); }));
  clearTimeout(window._tt);
  window._tt = setTimeout(() => { if (location.hash === "#/tasks") pageTasks(); }, 10000);
}

// ---------------- 监控 ----------------
async function pageMonitors() {
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

// ---------------- 设置 ----------------
async function pageSettings() {
  loading();
  SETTINGS = await api("/settings");
  const s = SETTINGS;
  const dc = s.default_create || {};
  view.innerHTML = `<div class="grid">
  <div class="card" id="tg"><h3>Telegram</h3>
    <label>Bot Token ${s.tg_token_set ? `<span class="badge done">已设置 ${esc(s.tg_token_hint)}</span>` : ""}</label>
    <input name="tg_token" type="password" placeholder="${s.tg_token_set ? "留空保持不变" : "123456:ABC..."}" autocomplete="off">
    <label>Chat ID（Bot 只响应此 ID）</label><input name="tg_chat_id" value="${esc(s.tg_chat_id || "")}">
    <label><input type="checkbox" name="daily_report" style="width:auto" ${s.daily_report ? "checked" : ""}> 每日账单报告</label>
    <div class="row2"><div><label>报告时间</label><input name="report_time" type="time" value="${esc(s.report_time || "09:00")}"></div>
    <div><label>监控间隔（分钟）</label><input name="monitor_interval" type="number" min="1" value="${esc(s.monitor_interval || 5)}"></div></div>
    <label>时区</label><input name="timezone" value="${esc(s.timezone || "Asia/Shanghai")}">
    <div class="bar" style="margin-top:12px"><button class="btn primary" id="save">保存</button><button class="btn" id="test">发送测试消息</button></div></div>
  <div class="card" id="cfc"><h3>Cloudflare</h3><p class="muted">用于换 IP 后自动更新 DNS。建议创建仅含「Zone.DNS 编辑」权限、限定域名的 API Token。</p>
    <label>API Token ${s.cf_token_set ? `<span class="badge done">已设置</span>` : ""}</label>
    <input name="cf_token" type="password" placeholder="${s.cf_token_set ? "留空保持不变" : "Cloudflare API Token"}" autocomplete="off">
    <div class="bar" style="margin-top:12px"><button class="btn primary" id="saveCf">保存</button>${s.cf_token_set ? `<button class="btn" id="clrCf">清除</button>` : ""}</div></div>
  <div class="card" id="pcc"><h3>IP 质量检测</h3><p class="muted">风险分来自 proxycheck.io：不填 Key 每天 100 次，免费注册的 Key 每天 1000 次。只发送要检测的公网 IP。</p>
    <label>proxycheck.io Key（可选）${s.proxycheck_key_set ? ` <span class="badge done">已设置</span>` : ""}</label>
    <input name="proxycheck_key" type="password" placeholder="${s.proxycheck_key_set ? "留空保持不变" : "可不填"}" autocomplete="off">
    <div class="bar" style="margin-top:12px"><button class="btn primary" id="savePc">保存</button>${s.proxycheck_key_set ? `<button class="btn" id="clrPc">清除</button>` : ""}</div></div>
  <div class="card"><h3>默认创建参数</h3><p class="muted">OCI 创建/抢机、Lightsail 创建表单的默认值（JSON）。</p>
    <textarea id="dc" style="min-height:220px">${esc(JSON.stringify(Object.keys(dc).length ? dc : {
      oci: { shape: "VM.Standard.A1.Flex", ocpus: 4, memory_gb: 24, disk_gb: 50, os: "Canonical Ubuntu", os_version: "22.04", ssh_key: "" },
      lightsail: { blueprint: "debian_12", bundle: "nano_3_0", zone: "" } }, null, 2))}</textarea>
    <div class="bar" style="margin-top:12px"><button class="btn primary" id="saveDc">保存</button></div></div>
  <div class="card" id="fg"><h3>免费额度护栏</h3><p class="muted">创建、改配置、扩容前估算是否超出 OCI / AWS / Azure 免费额度，超出时弹窗二次确认。只提醒，不拦截你的决定。</p>
    <label><input type="checkbox" name="free_guard" ${s.free_guard === false ? "" : "checked"}> 开启护栏（推荐）</label>
    <div class="bar" style="margin-top:12px"><button class="btn primary" id="saveFg">保存</button></div></div>
  <div class="card" id="v14"><h3>自动换 IP 与界面</h3>
    <label>自动换 IP 每账号每天上限（IP 不通触发；0 = 不自动换）</label><input name="auto_ip_daily_limit" type="number" min="0" max="50" value="${esc(s.auto_ip_daily_limit ?? 3)}">
    <p class="muted">达到上限后只推送 Telegram 告警，不再自动更换；自动换 IP 失败也只告警、不重试。今日用量见「监控」页。</p>
    <div class="bar" style="margin-top:8px"><button class="btn primary" id="saveV14">保存</button></div>
    <label><input type="checkbox" id="compact" ${document.documentElement.classList.contains("compact") ? "checked" : ""}> 紧凑模式（缩小行高和留白，只对本设备生效）</label></div>
  <div class="card" id="pw"><h3>修改面板密码</h3><label>原密码</label><input name="old" type="password">
    <label>新密码（≥10 位）</label><input name="new" type="password"><div class="bar" style="margin-top:12px"><button class="btn primary" id="savePw">修改</button></div>
    <p class="muted">修改后所有设备需要重新登录。登录连续失败 5 次将锁定该 IP 15 分钟。</p></div>${SETTINGS_CARDS.map((c) => c.html(s)).join("")}</div>`;
  SETTINGS_CARDS.forEach((c) => c.bind(view));
  $("#save").onclick = (e) => { const f = form($("#tg")); if (!f.tg_token) delete f.tg_token; act(e.target, () => post("/settings", f), "已保存").then(pageSettings); };
  $("#test").onclick = (e) => act(e.target, () => post("/settings/tg-test"), "测试消息已发送");
  $("#saveCf").onclick = (e) => { const f = form($("#cfc")); if (!f.cf_token) return toast("请输入 Token", true); act(e.target, () => post("/settings", f), "已保存").then(pageSettings); };
  $("#savePc").onclick = (e) => { const f = form($("#pcc")); if (!f.proxycheck_key) return toast("请输入 Key", true); act(e.target, () => post("/settings", f), "已保存").then(pageSettings); };
  if ($("#clrPc")) $("#clrPc").onclick = (e) => act(e.target, () => post("/settings", { proxycheck_key_clear: true }), "已清除").then(pageSettings);
  if ($("#clrCf")) $("#clrCf").onclick = (e) => act(e.target, () => post("/settings", { cf_token_clear: true }), "已清除").then(pageSettings);
  $("#saveDc").onclick = (e) => { let v; try { v = JSON.parse($("#dc").value); } catch (_) { return toast("JSON 格式错误", true); } act(e.target, () => post("/settings", { default_create: v }), "已保存"); SETTINGS.default_create = v; };
  $("#saveFg").onclick = (e) => act(e.target, () => post("/settings", form($("#fg"))), "已保存");
  $("#saveV14").onclick = (e) => act(e.target, () => post("/settings", { auto_ip_daily_limit: +$("[name=auto_ip_daily_limit]").value }), "已保存");
  $("#compact").onchange = (e) => setCompact(e.target.checked);
  $("#savePw").onclick = (e) => act(e.target, () => post("/password", form($("#pw"))), "已修改，请重新登录").then((r) => r && setTimeout(() => (location.href = "/login"), 1200));
}


// ================= v1.1 新增 =================
// 登录方式 + 开机脚本（创建表单通用）
async function loginFields() {
  let scripts = [];
  try { scripts = await api("/scripts"); } catch (_) { /* ignore */ }
  return `<label><input type="checkbox" name="password_login" style="width:auto" checked> 生成随机 root 密码并开启密码登录（密码加密保存，可在「开机密码」查看）</label>
    <label>开机脚本</label><select name="script_id"><option value="">不使用模板</option>${scripts.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select>
    <textarea name="script" placeholder="或直接填写 bash 脚本（以 root 执行，日志在 /root/tricloud-init.log）"></textarea>
`;
}
async function showCreated(r) {
  if (!r) return;
  const pw = r.password ? `<label>用户名</label><code>${esc(r.username)}</code><label>密码（只显示这一次，之后需输入面板密码查看）</label>
    <input value="${esc(r.password)}" readonly onclick="this.select()">` : `<p class="muted">未设置密码，请用 SSH 密钥登录。</p>`;
  await modal("创建已提交", `<p>${esc(r.name || "")} · ${esc(r.state || "")}${r.public_ip ? " · " + esc(r.public_ip) : ""}</p>${pw}`, null, "我已保存");
}
async function ec2Create(acc, reload) {
  let o;
  try { o = await api(`/accounts/${acc.id}/aws/ec2-options`); } catch (e) { return toast(e.message, true); }
  const d = SETTINGS.default_create?.aws || {};
  const r = await modal("创建 EC2 实例", `<div class="row2">
    <div><label>名称</label><input name="name" value="ec2-${Date.now().toString(36)}"></div>
    <div><label>实例类型</label><input name="type" list="ec2types" value="${esc(d.type || "t3.micro")}"><datalist id="ec2types">${o.types.map((t) => `<option>${t}</option>`).join("")}</datalist></div>
    <div><label>系统</label><select name="os">${o.os.map((x) => `<option ${x === d.os ? "selected" : ""}>${x}</option>`).join("")}</select></div>
    <div><label>系统盘 GB (gp3)</label><input name="disk_gb" type="number" min="8" value="${esc(d.disk_gb || 10)}"></div></div>
    <label>额外放行端口（默认只开 22，逗号分隔）</label><input name="ports" placeholder="80,443" value="${esc(d.ports || "")}">
    ${await loginFields()}<div class="bar">${saveDefaultBtn("aws")}</div>`, (bg) => post(`/accounts/${acc.id}/aws/ec2-create`, { ...form(bg), region: regionOf(acc) }), "创建");
  if (r) { showCreated(r); setTimeout(reload, 4000); }
}

// v1.5 公网放行警告（实例「开放端口」/ 安全列表 / 安全组页共用）
const publicWarn = (cidr, what, okText = "我已了解，继续") => modal("⚠️ 对整个互联网开放", `<p>来源 <code>${esc(cidr)}</code> 表示<b>任何人</b>都能访问${what}。</p>
  <ul class="guard"><li>请确认这些端口上的服务有密码 / 密钥保护，并保持更新</li><li>只需要自己访问时，建议到安全组页填写你的 IP 段</li></ul>`, null, okText, true);
const OPEN_PORT_WHERE = { oci: "实例所在子网的安全列表", aws: "实例关联的全部安全组", azure: "实例网卡 / 子网上的网络安全组（NSG）" };
// v1.5 实例操作「开放端口」：POST /instances/{id}/open-port，来源固定 0.0.0.0/0；先填端口，再弹公网警告二次确认
async function openPortDialog(acc, inst, base, btn) {
  const v = await modal("开放端口", `<p>在「${esc(inst.name)}」的${OPEN_PORT_WHERE[acc.provider] || "安全组"}放行入站端口，来源 <code>0.0.0.0/0</code>。</p>
    <div class="row2"><div><label>端口（单个或批量，如 8443 或 80, 443, 8000-8100）</label><input name="port" placeholder="例如 8443"></div>
    <div><label>协议</label><select name="protocol"><option value="tcp">TCP</option><option value="udp">UDP</option></select></div></div>
    <p class="muted">每个端口 / 范围一条规则，已存在的自动跳过。不支持放行全部端口（1-65535）。</p>`, (f) => {
    const x = form(f);
    if (!x.port) throw new Error("请填写端口");
    return x;
  }, "下一步");
  if (!v) return;
  if (!(await publicWarn("0.0.0.0/0", `${v.protocol.toUpperCase()} 端口 <code>${esc(v.port)}</code>`, "确认开放"))) return;
  const r = await act(btn, () => post(`/accounts/${acc.id}/instances/${encodeURIComponent(inst.id)}/open-port`,
    { port: v.port, protocol: v.protocol, region: base.region, kind: base.kind, confirm_public: true }));
  if (r) {
    toast(`已开放：新增 ${r.added} 条${r.skipped ? `，跳过已存在 ${r.skipped} 条` : ""}`);
    modal("开放端口结果", `<ul>${(r.groups || []).map((g) => `<li>${esc(g.kind)} <b>${esc(g.name)}</b>：新增 ${g.added} 条，跳过 ${g.skipped} 条</li>`).join("")}</ul>`, null, "好的");
  }
}
// v1.5「添加规则」端口输入：单端口（起始 / 结束）或批量（仿线上版 openSecRuleModal）
const portModeFields = () => `<div data-show-when="protocol=tcp|udp"><label>端口输入方式</label><select name="port_mode">
  <option value="single">单端口（起始 / 结束端口）</option><option value="batch">批量端口（每行一个或逗号分隔）</option></select>
  <div class="row2" data-show-when="port_mode=single"><div><label>起始端口</label><input name="port_min" type="number" min="1" max="65535" placeholder="如 80"></div>
  <div><label>结束端口（留空=同起始）</label><input name="port_max" type="number" min="1" max="65535" placeholder="如 80"></div></div>
  <div data-show-when="port_mode=batch"><label>批量端口</label><textarea name="ports" placeholder="80&#10;443&#10;8000-8100"></textarea>
  <p class="muted">每行一个或逗号分隔；支持单个端口（80）、范围（8000-8100）或混合。每段一条规则，已存在的自动跳过。</p></div></div>`;
// 把弹窗的端口字段统一成 ports 字符串；返回 "" 表示未填
function portsOf(v) {
  if (!["tcp", "udp"].includes(v.protocol)) return "";
  if (v.port_mode === "batch") return String(v.ports || "").trim();
  if (!v.port_min) return "";
  const a = +v.port_min, b = +(v.port_max || v.port_min);
  return a === b ? String(a) : `${a}-${b}`;
}

// OCI 安全列表
async function openSecurity(acc, inst, base) {
  let lists;
  try { toast("读取安全列表…"); lists = await api(`/accounts/${acc.id}/oci/security?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  const body = lists.map((l) => `<h4>${esc(l.name)}</h4><table><tr><th>方向</th><th>协议</th><th>CIDR</th><th>端口</th><th></th></tr>
    ${l.rules.map((r) => `<tr><td>${r.direction === "ingress" ? "入站" : "出站"}</td><td>${esc(r.protocol)}</td><td class="mono">${esc(r.cidr)}</td><td>${esc(r.port)}</td>
    <td><button class="btn sm danger" data-rm="${esc(l.id)}|${r.direction}|${r.idx}">删除</button></td></tr>`).join("")}</table>
    <div class="bar"><button class="btn sm" data-add="${esc(l.id)}">添加规则</button><button class="btn sm" data-ports="1">放行指定端口</button></div>`).join("");
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal wide"><h3>安全列表 · ${esc(inst.name)}</h3><div class="mb">${body}</div><div class="acts"><button class="btn" data-x>关闭</button></div></div>`;
  document.body.appendChild(bg);
  const again = () => { bg.remove(); openSecurity(acc, inst, base); };
  bg.querySelector("[data-x]").onclick = () => bg.remove();
  bg.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = async () => {
    const [sl_id, direction, idx] = b.dataset.rm.split("|");
    if (!(await confirmBox("删除规则", "确定删除这条规则？", true))) return;
    if (await act(b, () => post(`/accounts/${acc.id}/oci/security`, { op: "remove", region: base.region, sl_id, direction, idx }), "已删除")) again();
  }));
  const pubOk = async (cidr, what) => !PUBLIC_CIDR(cidr) || !!(await publicWarn(cidr, esc(what)));
  // 「放行指定端口」：与实例操作「开放端口」同一个接口（来源 0.0.0.0/0）
  bg.querySelectorAll("[data-ports]").forEach((b) => (b.onclick = () => { bg.remove(); openPortDialog(acc, inst, base, null); }));
  bg.querySelectorAll("[data-add]").forEach((b) => (b.onclick = async () => {
    const r = await modal("添加规则", `<div class="row2"><div><label>方向</label><select name="direction"><option value="ingress">入站</option><option value="egress">出站</option></select></div>
      <div><label>协议</label><select name="protocol"><option>tcp</option><option>udp</option><option>icmp</option><option>icmpv6</option><option>all</option></select></div></div>
      <label>CIDR</label><input name="cidr" placeholder="如 203.0.113.0/24；0.0.0.0/0 表示整个互联网">
      ${portModeFields()}<label>备注</label><input name="desc">
      <p class="muted">对 0.0.0.0/0 必须填写具体端口，不支持放行全部端口。</p>`, (f) => form(f), "下一步");
    if (!r) return;
    const ports = portsOf(r);
    if (r.direction === "ingress" && !(await pubOk(r.cidr, ports ? `端口 ${ports}` : "该协议"))) return;
    const res = await act(null, () => post(`/accounts/${acc.id}/security-rules`, { instance_id: inst.id, region: base.region, sl_id: b.dataset.add,
      direction: r.direction, protocol: r.protocol, cidr: r.cidr, ports, description: r.desc, confirm_public: PUBLIC_CIDR(r.cidr) }));
    if (res) { toast(`已添加 ${res.added} 条${res.skipped ? `，跳过已存在 ${res.skipped} 条` : ""}`); again(); }
  }));
}

// OCI 配额 / 网络
async function tabOciLimits(acc, box) {
  const reload = () => tabOciLimits(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">刷新</button><button class="btn" id="net">自动创建网络</button></div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
  $("#rf", box).onclick = reload;
  $("#net", box).onclick = async (e) => {
    if (!(await confirmBox("自动创建网络", "新建 VCN（含 IPv6）、互联网网关、路由和公有子网，安全列表默认只放行 22 与 ICMP。确定？"))) return;
    act(e.target, () => post(`/accounts/${acc.id}/oci/network`, { region: regionOf(acc) }), (r) => `已创建任务 #${r.task_id}`);
  };
  let r;
  try { r = await api(`/accounts/${acc.id}/oci/limits?${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#lb", box).innerHTML = `<div class="card"><h3>计算配额 · ${esc(r.region)}</h3><table><tr><th>项目</th><th>上限</th><th>已用</th><th>可用</th><th>免费剩余</th></tr>
    ${r.items.map((i) => `<tr><td>${esc(i.name)}</td><td>${i.limit}</td><td>${i.used ?? "-"}</td><td>${i.available ?? "-"}</td><td>${i.free == null ? "-" : `${i.free_left ?? "?"} / ${i.free}`}</td></tr>`).join("") || `<tr><td colspan=5 class="muted">无数据</td></tr>`}</table>
    <p class="muted">「上限」是 OCI 允许开的量，升级按量付费（PAYG）后会很大；「免费剩余」A1 按${r.a1_basis === "paid" ? "付费号 4 OCPU / 24GB" : r.a1_basis === "free" ? "免费号 2 OCPU / 12GB" : "免费号 2 OCPU / 12GB（未识别账号类型，可在「类型」里刷新）"}计算（2026-06 起免费号减半），E2.1.Micro 2 台，超出部分计费。可用量为 0 时抢机必然失败。</p></div>`;
}

// AWS 区域
async function tabAwsRegions(acc, box, refresh = false) {
  box.innerHTML = `<div class="grid"><div class="card" id="st"><span class="spin"></span> 读取区域状态…</div><div class="card" id="sc"><span class="spin"></span> 全区域实例扫描（串行，约 30–60 秒）…</div></div>`;
  api(`/accounts/${acc.id}/aws/regions-status`).then((rs) => {
    $("#st", box).innerHTML = `<h3>区域激活</h3><p class="muted">香港、雅加达等 Opt-in 区域需先激活才能开机。</p><table><tr><th>区域</th><th>状态</th><th></th></tr>
      ${rs.map((r) => `<tr><td>${esc(r.region)}</td><td><span class="badge ${r.status === "ENABLED_BY_DEFAULT" || r.status === "ENABLED" ? "running" : ""}">${esc(r.status)}</span></td>
      <td>${r.status === "DISABLED" ? `<button class="btn sm" data-en="${esc(r.region)}">激活</button>` : ""}</td></tr>`).join("")}</table>`;
    box.querySelectorAll("[data-en]").forEach((b) => (b.onclick = async () => {
      const r = await act(b, () => post(`/accounts/${acc.id}/aws/enable-region`, { region: b.dataset.en }));
      if (r) { toast(r.hint); b.remove(); }
    }));
  }).catch((e) => ($("#st", box).innerHTML = `❌ ${esc(e.message)}<p class="muted">需要 account:ListRegions / account:EnableRegion 权限</p>`));
  api(`/accounts/${acc.id}/aws/scan${refresh ? "?refresh=true" : ""}`).then((d) => {
    const rows = d.regions.filter((r) => r.ec2 || r.lightsail);
    $("#sc", box).innerHTML = `<div class="bar"><h3 class="grow" style="margin:0">全区域实例</h3><span class="muted">${esc(d.updated_at)}</span><button class="btn sm" id="rs">重新扫描</button></div>
      ${rows.length ? `<table><tr><th>区域</th><th>EC2（运行）</th><th>Lightsail</th><th></th></tr>${rows.map((r) => `<tr><td>${esc(r.region)}</td><td>${r.ec2}（${r.ec2_running}）</td><td>${r.lightsail ?? "-"}</td>
      <td><button class="btn sm" data-go="${esc(r.region)}">查看</button></td></tr>`).join("")}</table>` : `<div class="empty">所有区域都没有实例</div>`}`;
    $("#rs", box).onclick = () => tabAwsRegions(acc, box, true);
    box.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => { localStorage.setItem("tc_region_" + acc.id, b.dataset.go); go(`#/aws/${acc.id}/ec2`); }));
  }).catch((e) => ($("#sc", box).innerHTML = `❌ ${esc(e.message)}`));
}

// Azure 创建 / 资源组 / 配额
let AZ_LOC = {};
async function azLocations(acc) {
  if (!AZ_LOC[acc.id]) AZ_LOC[acc.id] = await api(`/accounts/${acc.id}/azure/locations`);
  return AZ_LOC[acc.id];
}
async function tabAzCreate(acc, box) {
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let locs = [];
  try { locs = await azLocations(acc); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const dz = SETTINGS.default_create?.azure || {};
  const last = localStorage.getItem("tc_azloc_" + acc.id) || dz.location || "eastasia";
  box.innerHTML = `<div class="card" id="f"><h3>创建 Azure VM</h3><div class="row2">
    <div><label>名称</label><input name="name" value="vm-${Date.now().toString(36)}"></div>
    <div><label>区域</label><select name="location">${locs.map((l) => `<option ${l === last ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    <div><label>大小</label><input name="size" value="${esc(dz.size || "Standard_B1s")}" list="azs"><datalist id="azs">${["Standard_B1s", "Standard_B1ms", "Standard_B2ats_v2", "Standard_B2pts_v2", "Standard_B2s", "Standard_D2as_v5"].map((x) => `<option>${x}</option>`).join("")}</datalist></div>
    <div><label>系统</label><select name="os">${["debian-12", "ubuntu-24.04", "ubuntu-22.04"].map((x) => `<option ${x === dz.os ? "selected" : ""}>${x}</option>`).join("")}</select></div>
    <div><label>系统盘 GB</label><input name="disk_gb" type="number" min="30" value="${esc(dz.disk_gb || 30)}"></div>
    <div><label>磁盘类型</label><select name="disk_type"><option>StandardSSD_LRS</option><option>Standard_LRS</option><option>Premium_LRS</option></select></div>
    <div><label>资源组（留空=新建 名称-rg）</label><input name="resource_group"></div>
    <div><label>额外放行端口（默认只开 22）</label><input name="ports" placeholder="80,443"></div></div>
    <label><input type="checkbox" name="ipv6" style="width:auto"> 同时分配公网 IPv6</label>
    <label>SSH 公钥（可选）</label><textarea name="ssh_key">${esc(dz.ssh_key || "")}</textarea>
    ${await loginFields()}
    <p class="muted">学生订阅免费额度：B1s 750 小时/月 + 2×64GB P6 SSD。创建约 2–4 分钟，后台执行并推送通知。</p>
    <div class="bar" style="margin-top:14px"><button class="btn primary" id="go">创建</button>${saveDefaultBtn("azure")}</div></div>`;
  $("#go", box).onclick = (e) => {
    const f = form($("#f", box));
    localStorage.setItem("tc_azloc_" + acc.id, f.location);
    act(e.target, () => post(`/accounts/${acc.id}/azure/create`, f), (r) => `已创建任务 #${r.task_id}，完成后可在「开机密码」查看密码`);
  };
}
async function tabAzRgs(acc, box) {
  const reload = () => tabAzRgs(acc, box);
  box.innerHTML = `<div class="bar"><button class="btn" id="rf">刷新</button><button class="btn primary" id="new">新建资源组</button></div><div class="card" id="t"><span class="spin"></span></div>`;
  $("#rf", box).onclick = reload;
  $("#new", box).onclick = async () => {
    const locs = await azLocations(acc).catch(() => []);
    const r = await modal("新建资源组", `<label>名称</label><input name="name"><label>区域</label><select name="location">${locs.map((l) => `<option>${l}</option>`).join("")}</select>`,
      (bg) => post(`/accounts/${acc.id}/azure/rgs`, form(bg)), "创建");
    if (r) reload();
  };
  let list;
  try { list = await api(`/accounts/${acc.id}/azure/rgs`); } catch (e) { $("#t", box).textContent = "❌ " + e.message; return; }
  $("#t", box).innerHTML = `<table><tr><th>名称</th><th>区域</th><th>状态</th><th></th></tr>${list.map((g) => `<tr><td>${esc(g.name)}</td><td>${esc(g.location)}</td><td>${esc(g.state)}</td>
    <td><button class="btn sm danger" data-del="${esc(g.name)}">删除</button></td></tr>`).join("") || `<tr><td colspan=4 class="muted">暂无</td></tr>`}</table>`;
  box.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    const r = await modal("删除资源组", `<p>⚠️ 将删除资源组 <b>${esc(b.dataset.del)}</b> 内的<b>全部资源</b>（VM、磁盘、IP、网络），不可恢复。</p><label>输入资源组名称确认</label><input name="confirm">`,
      (bg) => post(`/accounts/${acc.id}/azure/rgs`, { op: "delete", name: b.dataset.del, ...form(bg) }), "删除", true);
    if (r) { toast("已提交删除，几分钟后完成"); setTimeout(reload, 3000); }
  }));
}
async function tabAzQuota(acc, box) {
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
      $("#q", box).innerHTML = `<table><tr><th>项目</th><th>已用</th><th>上限</th></tr>${r.items.map((i) => `<tr><td>${esc(i.name)}</td><td>${i.used}</td><td>${i.limit}</td></tr>`).join("")}</table>`;
    } catch (e) { $("#q", box).textContent = "❌ " + e.message; }
  };
  $("#loc", box).onchange = load;
  load();
}

// DNS 绑定
async function bindDns(acc, inst) {
  let zones;
  try { zones = await api("/cf/zones"); } catch (e) { return toast(e.message + "，请先在设置页填写 Cloudflare Token", true); }
  const r = await modal("绑定域名", `<p class="muted">绑定后，换 IP / 分配 IPv6 会自动更新这条 Cloudflare 记录。</p>
    <label>域名</label><select name="zone">${zones.map((z) => `<option value="${esc(z.id)}|${esc(z.name)}">${esc(z.name)}</option>`).join("")}</select>
    <label>完整记录名</label><input name="record" placeholder="node1.example.com">
    <label><input type="checkbox" name="v4" style="width:auto" checked> 更新 A 记录（IPv4）</label>
    <label><input type="checkbox" name="v6" style="width:auto"> 更新 AAAA 记录（IPv6）</label>
    <label><input type="checkbox" name="proxied" style="width:auto"> 开启 Cloudflare 代理（橙色云）</label>
    <label><input type="checkbox" name="sync_now" style="width:auto" checked> 立即用当前 IP 同步一次</label>`, (bg) => {
    const f = form(bg); const [zone_id, zone_name] = f.zone.split("|");
    return post("/dns-bindings", { account_id: acc.id, instance_id: inst.id, name: inst.name, zone_id, zone_name, record: f.record,
      v4: f.v4, v6: f.v6, proxied: f.proxied, sync_now: f.sync_now, ipv4: inst.public_ip, ipv6: inst.ipv6 });
  }, "绑定");
  if (r) toast(r.dns && r.dns.length ? r.dns.join("；") : "已绑定");
}
async function pageDns() {
  loading();
  const list = await api("/dns-bindings");
  view.innerHTML = `<div class="card"><p class="muted">在实例卡片上点「绑定域名」添加。Token 在「设置 → Cloudflare」配置。</p>
    <table><tr><th>记录</th><th>实例</th><th>账号</th><th>类型</th><th></th></tr>${list.map((d) => `<tr><td class="mono">${esc(d.record)}</td><td>${esc(d.name)}</td><td>${esc(d.account_name)}</td>
    <td>${d.v4 ? "A " : ""}${d.v6 ? "AAAA " : ""}${d.proxied ? "· 代理" : ""}</td><td><button class="btn sm danger" data-del="${d.id}">解绑</button></td></tr>`).join("") || `<tr><td colspan=5 class="muted">暂无</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (!(await confirmBox("解绑域名", "解绑后换 IP 不再自动更新这条解析（Cloudflare 上的记录保留）。确定？", true))) return; if (await act(b, () => del(`/dns-bindings/${b.dataset.del}`), "已解绑")) pageDns(); }));
}

// 开机密码
async function pageSecrets() {
  loading();
  const list = await api("/secrets");
  view.innerHTML = `<div class="card"><p class="muted">面板创建/抢机生成的随机密码，经 Fernet 加密保存。查看需要输入面板密码。</p>
    <table><tr><th>实例</th><th>账号</th><th>用户</th><th>创建时间</th><th></th></tr>${list.map((x) => `<tr><td>${esc(x.name)}</td><td>${esc(x.account_name || "-")}</td><td>${esc(x.username)}</td>
    <td>${new Date(x.created * 1000).toLocaleString()}</td><td><button class="btn sm" data-see="${x.id}">查看</button> <button class="btn sm danger" data-del="${x.id}">删除</button></td></tr>`).join("") || `<tr><td colspan=5 class="muted">暂无</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-see]").forEach((b) => (b.onclick = async () => {
    const r = await modal("验证面板密码", `<input name="password" type="password" autocomplete="current-password">`, (bg) => post(`/secrets/${b.dataset.see}/reveal`, form(bg)), "查看");
    if (r) modal("开机密码", `<label>用户</label><code>${esc(r.username)}</code><label>密码</label><input value="${esc(r.password)}" readonly onclick="this.select()">`, null, "关闭");
  }));
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (await confirmBox("删除", "删除后无法再找回此密码。确定？", true)) { await del(`/secrets/${b.dataset.del}`); pageSecrets(); } }));
}

// 脚本模板
const SCRIPT_PRESETS = {
  "开启 BBR": "#!/bin/bash\necho 'net.core.default_qdisc=fq' >> /etc/sysctl.conf\necho 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.conf\nsysctl -p",
  "2GB Swap": "#!/bin/bash\nfallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile\necho '/swapfile none swap sw 0 0' >> /etc/fstab",
  "关闭 OCI 系统防火墙": "#!/bin/bash\niptables -P INPUT ACCEPT; iptables -P FORWARD ACCEPT; iptables -P OUTPUT ACCEPT; iptables -F\nnetfilter-persistent save 2>/dev/null || true\nsystemctl disable --now firewalld 2>/dev/null || true",
  "时区上海 + 常用工具": "#!/bin/bash\ntimedatectl set-timezone Asia/Shanghai\n(apt-get update && apt-get install -y curl wget unzip htop) || (dnf install -y curl wget unzip htop)",
};
async function pageScripts() {
  loading();
  const list = await api("/scripts");
  view.innerHTML = `<div class="bar"><button class="btn primary" id="new">新建模板</button><span class="muted">创建 EC2/Lightsail/OCI/Azure 时可选用，以 root 在首次开机执行</span></div>
    <div class="card"><table><tr><th>名称</th><th>内容</th><th></th></tr>${list.map((x) => `<tr><td>${esc(x.name)}</td><td class="mono">${esc(x.content.slice(0, 80))}${x.content.length > 80 ? "…" : ""}</td>
    <td><button class="btn sm" data-ed="${x.id}">编辑</button> <button class="btn sm danger" data-del="${x.id}">删除</button></td></tr>`).join("") || `<tr><td colspan=3 class="muted">暂无</td></tr>`}</table></div>`;
  const edit = async (x) => {
    const r = await modal(x ? "编辑模板" : "新建模板", `<label>名称</label><input name="name" value="${esc(x?.name || "")}">
      ${x ? "" : `<label>从预设开始</label><select id="pre"><option value="">空白</option>${Object.keys(SCRIPT_PRESETS).map((k) => `<option>${k}</option>`).join("")}</select>`}
      <label>脚本</label><textarea name="content" style="min-height:220px">${esc(x?.content || "#!/bin/bash\n")}</textarea>
      <p class="muted">不建议在脚本中 curl | bash 来源不明的远程脚本。</p>`, (bg) => post("/scripts", { id: x?.id, ...form(bg) }), "保存");
    if (r) pageScripts();
  };
  if (!window._preBound) {
    window._preBound = true;
    document.addEventListener("change", (e) => {
      if (e.target.id !== "pre" || !e.target.value) return;
      const m = e.target.closest(".modal"); m.querySelector("[name=content]").value = SCRIPT_PRESETS[e.target.value]; m.querySelector("[name=name]").value ||= e.target.value;
    });
  }
  $("#new").onclick = () => edit(null);
  view.querySelectorAll("[data-ed]").forEach((b) => (b.onclick = () => edit(list.find((x) => x.id == b.dataset.ed))));
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (!(await confirmBox("删除模板", "确定删除这个脚本模板？", true))) return; if (await act(b, () => del(`/scripts/${b.dataset.del}`), "已删除")) pageScripts(); }));
}

// 安全与备份：2FA、API Token、审计、备份恢复
async function pageSecurity() {
  loading();
  const [toks, logs] = await Promise.all([api("/tokens"), api("/audit?limit=100")]);
  const s = await api("/settings");
  view.innerHTML = `<div class="grid">
  <div class="card"><h3>二次验证（TOTP）</h3>
    ${s.totp_enabled ? `<p><span class="badge running">已开启</span> 登录需要身份验证器 App 上的 6 位验证码。</p><button class="btn danger" id="off">关闭</button>`
      : `<p class="muted">支持 Google Authenticator、1Password、Authy 等。开启后即使面板密码泄露也无法登录。</p><button class="btn primary" id="on">开启</button>`}</div>
  <div class="card"><h3>加密备份 / 恢复</h3><p class="muted">备份包含全部账号凭证、设置和加密密钥，整包再用你设置的口令加密（scrypt + Fernet）。口令丢失则无法恢复。</p>
    <div class="bar"><button class="btn primary" id="bk">下载备份</button><button class="btn" id="rs">从备份恢复</button></div></div>
  <div class="card"><div class="bar"><h3 class="grow" style="margin:0">API Token</h3><button class="btn sm primary" id="nt">新建</button></div>
    <p class="muted">给脚本、自建 Bot 调用面板 API 用（Header：Authorization: Bearer tc_...）。只读 Token 只能 GET；任何 Token 都不能改密码、2FA、备份。</p>
    <table><tr><th>名称</th><th>前缀</th><th>权限</th><th>最近使用</th><th></th></tr>${toks.map((t) => `<tr><td>${esc(t.name)}</td><td class="mono">${esc(t.prefix)}…</td><td>${t.scope === "read" ? "只读" : "完全"}</td>
    <td>${t.last_used ? new Date(t.last_used * 1000).toLocaleString() : "从未"}</td><td><button class="btn sm danger" data-rv="${t.id}">吊销</button></td></tr>`).join("") || `<tr><td colspan=5 class="muted">暂无</td></tr>`}</table></div></div>
  <div class="card"><h3>审计日志（最近 100 条写操作，保留 180 天）</h3><table><tr><th>时间</th><th>IP</th><th>来源</th><th>操作</th><th>结果</th></tr>
    ${logs.map((l) => `<tr><td>${new Date(l.ts * 1000).toLocaleString()}</td><td class="mono">${esc(l.ip)}</td><td>${esc(l.actor)}</td><td class="mono">${esc(l.action)}</td><td>${esc(l.detail)}</td></tr>`).join("") || `<tr><td colspan=5 class="muted">暂无</td></tr>`}</table></div>`;
  if ($("#on")) $("#on").onclick = async () => {
    const r = await post("/2fa/setup").catch((e) => toast(e.message, true));
    if (!r) return;
    const ok = await modal("开启二次验证", `<p>在身份验证器 App 中「手动输入密钥」：</p><input value="${esc(r.secret)}" readonly onclick="this.select()" class="mono">
      <p class="muted">或复制此链接到支持的 App：</p><input value="${esc(r.uri)}" readonly onclick="this.select()" class="mono">
      <label>输入 App 显示的 6 位验证码完成绑定</label><input name="code" inputmode="numeric" maxlength="6">`, (bg) => post("/2fa/enable", form(bg)), "开启");
    if (ok) { toast("二次验证已开启"); pageSecurity(); }
  };
  if ($("#off")) $("#off").onclick = async () => {
    const ok = await modal("关闭二次验证", `<label>面板密码</label><input name="password" type="password"><label>当前验证码</label><input name="code" inputmode="numeric" maxlength="6">`,
      (bg) => post("/2fa/disable", form(bg)), "关闭", true);
    if (ok) { toast("已关闭"); pageSecurity(); }
  };
  $("#nt").onclick = async () => {
    const r = await modal("新建 API Token", `<label>名称</label><input name="name" value="bot"><label>权限</label><select name="scope"><option value="read">只读</option><option value="full">完全（可开关机、换 IP）</option></select>`,
      (bg) => post("/tokens", form(bg)), "生成");
    if (r) { await modal("Token 已生成", `<p>只显示这一次，请立即保存：</p><input value="${esc(r.token)}" readonly onclick="this.select()" class="mono">`, null, "我已保存"); pageSecurity(); }
  };
  view.querySelectorAll("[data-rv]").forEach((b) => (b.onclick = async () => { if (await confirmBox("吊销 Token", "使用此 Token 的程序将立即失效。确定？", true)) { await del(`/tokens/${b.dataset.rv}`); pageSecurity(); } }));
  $("#bk").onclick = async () => {
    await modal("下载加密备份", `<label>面板密码</label><input name="password" type="password"><label>备份口令（≥10 位，恢复时需要）</label><input name="passphrase" type="password">`, async (bg) => {
      const r = await fetch("/api/backup", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form(bg)) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "备份失败");
      const blob = await r.blob(); const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = (r.headers.get("content-disposition") || "").split('filename="')[1]?.replace('"', "") || "tricloud.tcbk"; a.click();
      return true;
    }, "下载");
  };
  $("#rs").onclick = async () => {
    const ok = await modal("从备份恢复", `<p>⚠️ 当前所有数据将被备份内容覆盖，所有设备需重新登录。</p><label>备份文件 (.tcbk)</label><input type="file" id="bf" accept=".tcbk">
      <label>备份口令</label><input name="passphrase" type="password"><label>当前面板密码</label><input name="password" type="password">`, async (bg) => {
      const file = bg.querySelector("#bf").files[0]; if (!file) throw new Error("请选择文件");
      const buf = new Uint8Array(await file.arrayBuffer()); let bin = ""; for (let i = 0; i < buf.length; i += 32768) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 32768));
      return post("/restore", { ...form(bg), file_b64: btoa(bin) });
    }, "恢复", true);
    if (ok) { toast("已恢复，请重新登录"); setTimeout(() => (location.href = "/login"), 1200); }
  };
}


// ================= v1.2 新增 =================
const HL = { good: "健康", warn: "注意", bad: "危险" };
async function pageHealth() {
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

const migSpec = (p) => ({
    oci: `<div class="row2" data-oci-os><div><label>规格</label><select name="shape">${ociShapeOpts("VM.Standard.A1.Flex", ["VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"])}</select></div>
      ${ociOsFields({ os: "Canonical Ubuntu" })}
      <div><label>OCPU</label><input name="ocpus" type="number" min="1" value="1"></div><div><label>内存 GB</label><input name="memory_gb" type="number" min="1" value="6"></div>
      <div><label>系统盘 GB</label><input name="disk_gb" type="number" min="47" value="50"></div></div>`,
    aws: `<div class="row2"><div><label>实例类型</label><input name="type" value="t3.micro"></div>
      <div><label>系统</label><select name="os"><option>debian-12</option><option>ubuntu-24.04</option><option>ubuntu-22.04</option></select></div>
      <div><label>系统盘 GB</label><input name="disk_gb" type="number" min="8" value="10"></div><div><label>额外端口</label><input name="ports" placeholder="80,443"></div></div>`,
    azure: `<div class="row2"><div><label>区域</label><input name="location" value="eastasia"></div><div><label>大小</label><input name="size" value="Standard_B1s"></div>
      <div><label>系统</label><select name="os"><option>debian-12</option><option>ubuntu-24.04</option></select></div>
      <div><label>磁盘类型</label><select name="disk_type"><option>Premium_LRS</option><option>StandardSSD_LRS</option></select></div>
      <div><label>系统盘 GB</label><input name="disk_gb" type="number" min="30" value="64"></div><div><label>额外端口</label><input name="ports" placeholder="80,443"></div></div>`,
  }[p]);
async function migrateDialog(acc, inst) {
  const targets = ACCOUNTS.filter((a) => a.id !== acc.id && !NO_CREATE.has(a.provider));
  if (!targets.length) return toast("至少需要两个云账号才能迁移", true);
  const lf = await loginFields();

  const r = await modal("跨云迁移 / 重建", `<p>把「${esc(inst.name)}」在另一个账号重建：用同一个开机脚本新建实例，可自动把绑定的域名切到新 IP。</p>
    <p class="muted">⚠️ 不复制磁盘数据。需要保留的数据请先自行备份，或放进开机脚本里拉取。</p>
    <label>目标账号</label><select name="to" id="mto">${targets.map((a) => `<option value="${a.id}">${PNAME[a.provider]} · ${esc(a.name)}</option>`).join("")}</select>
    <label>新实例名称</label><input name="name" value="${esc(inst.name)}-new">
    <div id="mspec">${migSpec(targets[0].provider)}</div>${lf}
    <label><input type="checkbox" name="switch_dns" checked> 完成后把源实例绑定的域名切到新 IP</label>
    <label><input type="checkbox" name="copy_monitor" checked> 复制监控设置</label>
    <label><input type="checkbox" name="stop_source"> 完成后停掉源实例（不删除）</label>`, (bg) => {
    const f = form(bg); const to = ACCOUNTS.find((a) => a.id == f.to);
    const { to: _t, switch_dns, copy_monitor, stop_source, ...create } = f;
    return post("/migrate", { from_account_id: acc.id, from_region: regionOf(acc) || undefined, instance_id: inst.id, name: inst.name,
      to_account_id: to.id, region: to.provider === "azure" ? undefined : regionOf(to) || undefined, create, switch_dns, copy_monitor, stop_source });
  }, "开始迁移");
  if (r) toast(`已创建迁移任务 #${r.task_id}，完成后推送通知`);
}
document.addEventListener("change", (e) => {
  if (e.target.id !== "mto") return;
  const a = ACCOUNTS.find((x) => x.id == e.target.value); const box = document.getElementById("mspec");
  if (a && box) box.innerHTML = migSpec(a.provider);
});

// ================= v1.3 新增：流量守护 / 串口控制台 =================
const FREE_OUT = { oci: 10240, aws: 100, azure: 100 };
async function trafficDialog(acc, inst, kind, onSaved) {
  let gs = [];
  try { gs = await api("/traffic-guards"); } catch (_) { /* ignore */ }
  const g = gs.find((x) => x.account_id === acc.id && x.instance_id === inst.id) || {};
  if (TRAFFIC_DIALOG[acc.provider]) return TRAFFIC_DIALOG[acc.provider](acc, inst, g, onSaved);
  let use = "";
  try {
    const rgq = NOREG(acc) ? "" : `region=${encodeURIComponent(inst.region || regionOf(acc))}`;
    const t = await api(`/accounts/${acc.id}/traffic?instance_id=${encodeURIComponent(inst.id)}&kind=${kind}&${rgq}`);
    use = `<p>本月（${esc(t.period)}）出站 <b>${t.out_gb} GB</b>，入站 ${t.in_gb} GB。</p>`;
  } catch (e) { use = `<p class="muted">读取流量失败：${esc(e.message)}</p>`; }
  const mode = g.mode || "monthly", dir = g.direction || (g.count_in ? "both" : "out");
  const r = await modal(`流量守护 · ${inst.name}`, `${use}
    <p class="muted">月度模式每 30 分钟、滚动窗口每 10 分钟查一次平台指标（免费，有 5~15 分钟延迟，建议留余量）。到预警比例推送 Telegram；到上限推送，可选自动停机。</p>
    <div class="row2"><div><label>统计方式</label><select name="mode"><option value="monthly">本月累计</option><option value="rolling" ${mode === "rolling" ? "selected" : ""}>滚动窗口（最近 N 小时）</option></select></div>
    <div data-show-when="mode=rolling"><label>窗口小时数 N</label><input name="window_hours" type="number" min="1" max="720" value="${g.window_hours || 24}"></div>
    <div><label>方向</label><select name="direction">${[["out", "出站"], ["in", "入站"], ["both", "双向（出+入）"]].map(([v, l]) => `<option value="${v}" ${dir === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    <div><label><span data-show-when="mode=monthly">每月</span><span data-show-when="mode=rolling">窗口内</span>上限 GB（免费出站 ${FREE_OUT[acc.provider]} GB/月）</label><input name="limit_gb" type="number" min="1" value="${g.limit_gb || FREE_OUT[acc.provider]}"></div>
    <div><label>预警比例 %</label><input name="warn_pct" type="number" min="10" max="99" value="${g.warn_pct || 80}"></div>
    <div><label>到达上限后</label><select name="action"><option value="notify">只推送</option><option value="stop" ${g.action === "stop" ? "selected" : ""}>推送并自动停机</option></select></div>
    <div data-show-when="action=stop"><label>关机多少小时后自动开机（0 = 不自动开机）</label><input name="shutdown_hours" type="number" min="0" max="720" step="0.5" value="${g.shutdown_hours || 0}"></div></div>
    <p class="muted" data-show-when="action=stop">自动开机失败只推送 Telegram 告警，不会反复重试。</p>
    <label><input type="checkbox" name="enabled" ${g.enabled === 0 ? "" : "checked"}> 启用这条规则</label>`,
    (bg) => post("/traffic-guards", { account_id: acc.id, instance_id: inst.id, region: inst.region || regionOf(acc) || undefined, kind, name: inst.name, ...form(bg) }), "保存");
  if (r) { toast(r.warning || `已保存，当前已用 ${r.last_gb ?? "-"} GB（${r.last_pct ?? "-"}%）`, !!r.warning); if (onSaved) onSaved(); }
}

const GST = { ok: "running", warn: "pending", over: "failed", tripped: "stopped", resume_failed: "failed", disabled: "" };
async function pageTraffic() {
  loading();
  const list = await api("/traffic-guards");
  const fmt = (t) => (t ? new Date(t * 1000).toLocaleString() : "-");
  const actText = (g) => g.action !== "stop" ? "只推送" : g.shutdown_hours > 0 ? `停机 ${g.shutdown_hours} 小时后自动开机` : "自动停机";
  view.innerHTML = `<div class="card"><p class="muted">在实例卡片上点「流量守护」添加规则（OCI 在账号的「流量」标签里设置）：本月累计或滚动窗口（最近 N 小时，出站 / 入站 / 双向）。超限可自动停机，并可在 M 小时后自动开机（失败只告警、不重试）。也可以给 Telegram Bot 发 /traffic 查看。</p>
    ${list.length ? `<table><tr><th>实例</th><th>账号</th><th>统计</th><th>用量</th><th>上限</th><th>到上限</th><th>状态</th><th>启用</th><th>检查于</th><th></th></tr>
    ${list.map((g) => `<tr data-g="${g.id}"><td>${esc(g.name || g.instance_id.slice(-12))}</td><td><span class="dot ${g.provider}"></span>${esc(g.account_name || "-")}</td>
      <td>${esc(g.scope || "本月出站")}</td>
      <td><div class="meter"><i style="width:${Math.min(100, g.last_pct || 0)}%" class="${(g.last_pct || 0) >= 100 ? "bad" : (g.last_pct || 0) >= g.warn_pct ? "warn" : ""}"></i></div>
        ${g.last_gb ?? "-"} GB · ${g.last_pct ?? "-"}%</td><td>${g.limit_gb} GB</td><td>${actText(g)}</td>
      <td><span class="badge ${GST[g.status] || ""}">${esc(g.status_text || "正常")}</span>${g.resume_at_text ? `<div class="muted">预计 ${esc(g.resume_at_text)} 开机</div>` : g.state_msg && g.status !== "ok" ? `<div class="muted">${esc(g.state_msg)}</div>` : ""}</td>
      <td><label class="switch"><input type="checkbox" data-en="${g.id}" ${g.enabled ? "checked" : ""}><span></span></label></td>
      <td>${fmt(g.checked_at)}</td><td><button class="btn sm" data-chk="${g.id}">立即检查</button> <button class="btn sm" data-ed="${g.id}">编辑</button>
      ${g.resume_at ? `<button class="btn sm" data-cr="${g.id}">取消自动开机</button>` : ""}${["tripped", "resume_failed"].includes(g.status) ? ` <button class="btn sm" data-rs="${g.id}">清除状态</button>` : ""}
      <button class="btn sm danger" data-del="${g.id}">删除</button></td></tr>`).join("")}</table>`
    : `<div class="empty">还没有流量守护规则</div>`}</div>`;
  view.querySelectorAll("[data-chk]").forEach((b) => (b.onclick = () => act(b, () => post(`/traffic-guards/${b.dataset.chk}/check`), "已检查").then(pageTraffic)));
  view.querySelectorAll("[data-en]").forEach((b) => (b.onchange = () => act(null, () => api(`/traffic-guards/${b.dataset.en}`, { method: "PATCH", body: { enabled: b.checked } }), b.checked ? "已启用" : "已停用").then(pageTraffic)));
  view.querySelectorAll("[data-cr]").forEach((b) => (b.onclick = () => act(b, () => api(`/traffic-guards/${b.dataset.cr}`, { method: "PATCH", body: { cancel_resume: true } }), "已取消自动开机").then(pageTraffic)));
  view.querySelectorAll("[data-rs]").forEach((b) => (b.onclick = () => act(b, () => api(`/traffic-guards/${b.dataset.rs}`, { method: "PATCH", body: { reset_state: true } }), "已清除").then(pageTraffic)));
  view.querySelectorAll("[data-ed]").forEach((b) => (b.onclick = () => {
    const g = list.find((x) => x.id == b.dataset.ed); const acc = ACCOUNTS.find((a) => a.id === g.account_id);
    if (acc) trafficDialog(acc, { id: g.instance_id, name: g.name || g.instance_id.slice(-12), region: g.region || undefined }, g.kind || "vm", pageTraffic);
  }));
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("删除规则", "删除这条流量守护？", true)) act(b, () => api(`/traffic-guards/${b.dataset.del}`, { method: "DELETE" }), "已删除").then(pageTraffic);
  }));
}

// ================= v1.4 新增 =================
const TASK_NAME = { snatch: "抢机", change_ip: "换 IP", resize: "改配置", ipv6: "IPv6", azure_create: "创建 VM", ensure_network: "自动建网",
  snapshot: "快照（已移除）", migrate: "迁移" , cf_delete: "删除 CDN 分发" };
const TST = { running: "运行中", done: "完成", failed: "失败", stopped: "已停止", interrupted: "已中断" };
const fmtTime = (t) => (t ? new Date(t * 1000).toLocaleTimeString([], { hour12: false }) : "");
const fmtDT = (t) => (t ? new Date(t * 1000).toLocaleString([], { hour12: false }) : "-");
const isDesktop = () => !window.matchMedia || window.matchMedia("(min-width: 901px)").matches;
const instView = () => { let v = null; try { v = localStorage.getItem("tc_inst_view"); } catch (_) { /* 沙箱中无 localStorage */ } return v === "card" ? "card" : "table"; };
function setCompact(on) {
  document.documentElement.classList.toggle("compact", !!on);
  localStorage.setItem("tc_compact", on ? "1" : "0");
}

// ---------- 任务抽屉：提交任务后自动打开并跟踪，运行中每 2 秒刷新 ----------
const TaskDrawer = {
  tid: null, last: 0, timer: null, task: null, stick: true,
  el: () => document.getElementById("tdrawer"),
  isOpen() { const d = this.el(); return !!(d && d.classList.contains("open")); },
  async open(tid) {
    const d = this.el(); if (!d) return;
    d.classList.add("open"); d.setAttribute("aria-hidden", "false"); document.body.classList.add("td-open");
    if (tid && tid !== this.tid) { this.tid = tid; this.last = 0; this.task = null; this.stick = true; $("#tdCur").innerHTML = `<div class="empty"><span class="spin"></span></div>`; }
    if (!this.tid) $("#tdCur").innerHTML = `<div class="muted td-hint">点下面的任务查看实时日志。提交任务（抢机、换 IP、改配置、迁移…）后这里会自动打开并跟踪。</div>`;
    await this.tick(true);
  },
  close() {
    const d = this.el(); if (!d) return;
    d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); document.body.classList.remove("td-open");
    clearTimeout(this.timer); this.timer = null;
  },
  async tick(full) {
    clearTimeout(this.timer); this.timer = null;
    if (!this.isOpen()) return;
    try {
      if (this.tid) {
        const t = await api(`/tasks/${this.tid}?after=${this.last}`);
        this.render(t, full || !this.task);
      }
      await this.renderList();
    } catch (e) {
      if (this.tid) $("#tdCur").innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`;
    }
    if (this.isOpen() && ((this.task && this.task.status === "running") || !this.tid)) this.timer = setTimeout(() => this.tick(false), this.task && this.task.status === "running" ? 2000 : 8000);
  },
  render(t, full) {
    const box = $("#tdCur");
    const prev = this.task;
    this.task = t;
    if (full || !box.querySelector("#tdLog") || !prev || prev.id !== t.id) {
      box.innerHTML = `<div class="td-task"><div class="td-title"><b>#${t.id} ${esc(t.type_name || TASK_NAME[t.type] || t.type)}</b>
        <span class="badge ${esc(t.status)}" id="tdSt">${TST[t.status] || esc(t.status)}</span></div>
        <div class="muted">${t.provider ? `<span class="dot ${t.provider}"></span> ` : ""}${esc(t.account_name || "-")}${t.params && t.params.name ? " · " + esc(t.params.name) : ""}
          · 创建于 ${fmtDT(t.created)}</div>
        <div class="td-msg" id="tdMsg"></div>
        <div class="tlog mono" id="tdLog" role="log" aria-live="polite"></div>
        <div class="td-res" id="tdRes"></div>
        <div class="bar td-acts" id="tdActs"></div></div>`;
      const log = box.querySelector("#tdLog");
      log.addEventListener("scroll", () => { this.stick = log.scrollHeight - log.scrollTop - log.clientHeight < 40; });
    }
    const log = box.querySelector("#tdLog");
    if ((t.logs || []).length) {
      log.insertAdjacentHTML("beforeend", t.logs.map((l) => `<div class="ll lv-${esc(l.level)}"><span class="lt">${fmtTime(l.ts)}</span> ${esc(l.msg)}</div>`).join(""));
      this.last = t.last_log_id || this.last;
      while (log.children.length > 800) log.firstChild.remove();
    }
    if (!log.children.length) log.innerHTML = `<div class="ll muted">暂无日志</div>`;
    if (this.stick) log.scrollTop = log.scrollHeight;    // 自动滚到最底部（手动上翻时暂停）
    const st = box.querySelector("#tdSt"); st.className = "badge " + t.status; st.textContent = TST[t.status] || t.status;
    box.querySelector("#tdMsg").textContent = (t.attempts > 1 ? `已尝试 ${t.attempts} 次 · ` : "") + (t.message || "");
    const res = t.result && typeof t.result === "object" ? Object.entries(t.result).filter(([, v]) => v != null && v !== "" && !(Array.isArray(v) && !v.length)) : [];
    box.querySelector("#tdRes").innerHTML = res.length ? `<div class="kv">${res.map(([k, v]) => `<span>${esc(k)}</span><span class="mono">${esc(Array.isArray(v) ? v.join("；") : v)}</span>`).join("")}</div>` : "";
    const acts = box.querySelector("#tdActs");
    acts.innerHTML = (t.status === "running" ? `<button class="btn sm danger" id="tdStop">停止任务</button>` : `<button class="btn sm" id="tdDel">删除记录</button>`)
      + `<span class="grow"></span><span class="muted">${t.status === "running" ? "每 2 秒自动刷新" : "更新于 " + fmtDT(t.updated)}</span>`;
    const stop = acts.querySelector("#tdStop"), dl = acts.querySelector("#tdDel");
    if (stop) stop.onclick = async () => { if (await confirmBox("停止任务", `停止任务 #${t.id}？正在进行的云端操作会在当前步骤完成后停下。`, true)) { await act(stop, () => post(`/tasks/${t.id}/stop`), "已停止"); this.tick(false); } };
    if (dl) dl.onclick = async () => {
      if (!(await confirmBox("删除记录", `删除任务 #${t.id} 及其日志？`, true))) return;
      await act(dl, () => del(`/tasks/${t.id}`), "已删除"); this.tid = null; this.task = null; this.last = 0; this.open();
      if (location.hash === "#/tasks") pageTasks();
    };
  },
  async renderList() {
    const list = await api("/tasks?limit=20");
    updateTaskBadge(list);
    $("#tdList").innerHTML = list.length ? list.map((t) => `<button class="td-item ${t.id === this.tid ? "on" : ""}" data-tid="${t.id}">
      <span class="badge ${esc(t.status)}">${TST[t.status] || esc(t.status)}</span>
      <span class="ti-main"><b>#${t.id} ${TASK_NAME[t.type] || esc(t.type)}</b> <span class="muted">${esc(t.account_name || "")}</span>
      <span class="ti-msg">${esc(t.message || "")}</span></span><span class="muted ti-time">${fmtTime(t.updated)}</span></button>`).join("")
      : `<div class="empty">暂无任务</div>`;
    $("#tdList").querySelectorAll("[data-tid]").forEach((b) => (b.onclick = () => this.open(+b.dataset.tid)));
  },
};
window.TaskDrawer = TaskDrawer;
function updateTaskBadge(list) {
  const n = list.filter((t) => t.status === "running").length;
  const b = document.getElementById("taskCnt"); if (b) { b.textContent = n || ""; b.style.display = n ? "" : "none"; }
}

// ---------- 顶栏账号快速切换器 ----------
const TAB_EQUIV = [["instances", "ec2", "vms"], ["create", "azcreate"], ["limits", "quota", "azquota"], ["billing"]];
function mapTab(tab, prov) {
  if (!tab) return TABS[prov][0][0];
  if (TABS[prov].some((t) => t[0] === tab)) return tab;
  const grp = TAB_EQUIV.find((g) => g.includes(tab));
  const hit = grp && TABS[prov].find((t) => grp.includes(t[0]));
  return hit ? hit[0] : TABS[prov][0][0];
}
function renderAccSwitch(cur) {
  const el = document.getElementById("accsw"); if (!el) return;
  if (!ACCOUNTS.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<button class="btn accsw-btn" id="accswBtn" aria-haspopup="listbox" title="切换账号">${cur ? `<span class="dot ${cur.provider}"></span><span class="accsw-name">${esc(cur.name)}</span>` : `<span class="accsw-name">切换账号</span>`} ▾</button>`;
  $("#accswBtn").onclick = (e) => { e.stopPropagation(); openAccMenu(); };
}
function openAccMenu() {
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
function closeAccMenu() { const m = document.getElementById("accmenu"); if (m) m.remove(); }
document.addEventListener("click", (e) => { if (!e.target.closest("#accmenu") && !e.target.closest("#accswBtn")) closeAccMenu(); if (!e.target.closest(".opsmenu")) closeOpsMenu(); });

// ---------- 实例表格视图 ----------
const INLINE_OPS = ["start", "stop", "reboot", "changeip"];
// 按实例状态禁用无意义的操作：运行中不能再启动，已停止不能停止/重启
function opOff(op, i) {
  const st = String(i.state || "").toLowerCase();
  const up = ["running", "starting", "provisioning", "pending"].includes(st), down = ["stopped", "stopping", "deallocated", "deallocating", "stopped (deallocated)"].includes(st);
  if (op === "start" && up) return "已在运行";
  if ((op === "stop" || op === "reboot") && down) return "已停止";
  return "";
}
const opBtn = (o, l, i, cls = "") => { const off = opOff(o, i); return `<button class="btn sm ${cls}" data-op="${o}"${off ? ` disabled title="${off}"` : ""}>${l}</button>`; };
function instTable(acc, list, kind) {
  // v1.5：参照线上版——默认表格视图，列：名称/状态/规格/公网 IP/内网 IP/地域/创建时间，行内操作全部平铺
  const spec = (i) => acc.provider === "oci" ? `${esc(i.shape)} ${i.ocpus ?? ""}C/${i.memory_gb ?? ""}G` : esc(i.shape || "-");
  const when = (c) => { if (!c || c === "None") return "-"; const t = String(c).replace("T", " "); return esc(t.slice(0, 16)); };
  const ops = instOps(acc, kind);
  return `<table class="inst-table"><tr><th>名称</th><th>状态</th><th>规格</th><th>公网 IP</th><th>内网 IP</th><th>地域</th><th>创建时间</th><th>操作</th></tr>
    ${list.map((i) => `<tr data-id="${esc(i.id)}"><td><b title="${esc(i.id)}">${esc(i.name)}</b>${(i.ipv6 || []).length ? `<div class="muted mono" title="${esc(i.ipv6.join("\n"))}">${esc(i.ipv6[i.ipv6.length - 1])}${i.ipv6.length > 1 ? ` +${i.ipv6.length - 1}` : ""}</div>` : ""}</td>
    <td><span class="badge ${esc(i.state)}">${esc(i.state)}</span></td><td>${spec(i)}</td><td class="mono nowrap">${esc(i.public_ip || "-")}</td><td class="mono nowrap">${esc(i.private_ip || "-")}</td>
    <td class="nowrap">${esc(i.zone || i.region || "-")}</td><td class="mono nowrap">${when(i.created)}</td>
    <td class="row-ops"><div class="row-ops-in">${ops.map(([o, l]) => opBtn(o, l, i, o === "terminate" ? "danger" : "")).join("")}</div></td></tr>`).join("")}</table>`;
}
function opsMenu(anchor, ops, pick) {
  closeOpsMenu();
  const m = document.createElement("div"); m.className = "opsmenu"; m.setAttribute("role", "menu");
  m.innerHTML = ops.map(([o, l]) => `<button role="menuitem" class="${o === "terminate" ? "danger" : ""}" data-o="${o}">${l}</button>`).join("");
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  m.style.top = `${Math.min(r.bottom + 4, window.innerHeight - m.offsetHeight - 8)}px`;
  m.style.left = `${Math.max(8, Math.min(r.right - 200, window.innerWidth - 216))}px`;
  m.querySelectorAll("[data-o]").forEach((b) => (b.onclick = () => { closeOpsMenu(); pick(b.dataset.o); }));
}
function closeOpsMenu() { document.querySelectorAll(".opsmenu").forEach((m) => m.remove()); }

// ---------- 账号：存活天数、测活、信息、批量添加 ----------
function acctTypeTag(a) {   // v1.6：缓存的账号类型（点「类型」查询后显示）
  try { const t = a.acct_type ? JSON.parse(a.acct_type) : null; return t && t.label ? ` <span class="badge" title="${esc(t.plan_type || "")}">${esc(t.label)}${t.age_days != null ? ` · ${t.age_days} 天` : ""}</span>` : ""; } catch (_) { return ""; }
}
function ageText(a) {
  if (!a.cloud_created_at) return `<span class="muted">未填写</span>`;
  const days = Math.floor((Date.now() - new Date(a.cloud_created_at + "T00:00:00").getTime()) / 86400000);
  return `${esc(a.cloud_created_at)}<div class="muted">已存活 ${days} 天</div>`;
}
function testCell(a, r) {
  const ok = r ? r.ok : a.last_test_ok, ms = r ? r.ms : a.last_test_ms, err = r ? r.error : a.last_test_error;
  if (ok == null) return `<span class="muted">未测</span>`;
  return ok ? `<span class="badge running">连通</span> <span class="muted">${ms} ms</span>`
    : `<span class="badge failed">失败</span> <span class="muted" title="${esc(err || "")}">${esc((err || "").slice(0, 40))}</span>`;
}
async function accountInfoDialog(a) {
  const r = await modal(`账号信息 · ${a.name}`, `<label>云账号创建日期（用于计算存活天数${a.provider === "azure" ? "、估算教育优惠到期日" : ""}）</label>
    <input name="cloud_created_at" type="date" value="${esc(a.cloud_created_at || "")}">
    <p class="muted">${a.provider === "oci" ? `OCI 可自动读取租户创建时间。 <button type="button" class="btn sm" id="ccDetect">从 OCI 读取</button> <span id="ccMsg"></span>` : "该云没有免费接口能读到账号创建日期，请按控制台或注册邮件填写。"}</p>
    ${a.provider === "azure" ? `<label>Azure 教育优惠到期日（留空 = 按创建日期 + 12 个月估算）</label><input name="edu_expires_at" type="date" value="${esc(a.edu_expires_at || "")}">` : ""}`,
    (bg) => api(`/accounts/${a.id}`, { method: "PATCH", body: form(bg) }), "保存", false, (bg) => {
      const b = bg.querySelector("#ccDetect");
      if (!b) return;
      const go = async () => {
        const m = bg.querySelector("#ccMsg"); b.disabled = true; m.innerHTML = `<span class="spin"></span>`;
        try { const r = await post(`/accounts/${a.id}/detect-created`, {}); bg.querySelector('[name="cloud_created_at"]').value = r.cloud_created_at; a.cloud_created_at = r.cloud_created_at; m.textContent = "已读取"; }
        catch (e) { m.textContent = `❌ ${e.message}`; } finally { b.disabled = false; }
      };
      b.onclick = go;
      if (!a.cloud_created_at) go();
    });
  if (r) { toast("已保存"); await loadAccounts(); route(); }
}
async function batchAddAccounts(prefill) {
  const sample = `{"provider": "aws", "name": "东京", "cred": {"access_key": "AKIA...", "secret_key": "...", "region": "ap-northeast-1"}}
{"provider": "azure", "name": "学生", "tenant_id": "...", "client_id": "...", "client_secret": "...", "subscription_id": "..."}
[东京-OCI]
user=ocid1.user.oc1..xxx
fingerprint=aa:bb:...
tenancy=ocid1.tenancy.oc1..xxx
region=ap-tokyo-1
-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----`;
  const r = await modal("批量添加云账号", `<p class="muted">直接粘贴复制来的一堆内容：控制台页面、环境变量、AWS accessKeys.csv、Azure 应用注册页、OCI config + 私钥，或 JSON，混在一起也能自动识别、自动拆分成多个账号。每条都会在线校验凭证，结果逐条显示。</p>
    <textarea name="text" style="min-height:260px" placeholder="${esc(sample)}">${esc(prefill || "")}</textarea>
    <div class="row2"><div><label>无法判断云厂商时按</label><select name="provider">${provOpts("不猜测（报错）")}</select></div>
    <div><label>&nbsp;</label><label><input type="checkbox" name="dry_run"> 只检查格式，不校验、不保存</label></div></div>`, (bg) => {
    const f = form(bg); if (!f.text) throw new Error("请粘贴内容");
    toast("正在逐条校验…");
    return post("/accounts/batch", { text: bg.querySelector("[name=text]").value, provider: f.provider || undefined, dry_run: f.dry_run });
  }, "校验并添加");
  if (!r) return;
  await modal(`批量添加结果：成功 ${r.ok} / 共 ${r.total}`, `<table><tr><th>#</th><th>名称</th><th>云</th><th>结果</th></tr>
    ${r.results.map((x) => `<tr><td>${x.index}</td><td>${esc(x.name || "-")}</td><td>${x.provider ? `<span class="dot ${x.provider}"></span> ${PNAME[x.provider] || esc(x.provider)}` : "-"}</td>
    <td>${x.ok ? `<span class="badge running">${x.dry_run ? "格式正确" : "已添加"}</span>${x.ms ? ` <span class="muted">${x.ms} ms</span>` : ""}` : `<span class="badge failed">失败</span> <span class="muted">${esc(x.error)}</span>`}</td></tr>`).join("")}</table>`, null, "好的");
  await loadAccounts(); route();
}

// ---------- 到期提醒（总览） ----------
async function loadExpiryAlerts(box) {
  if (!box) return;
  try {
    const al = await api("/expiry-alerts");
    box.innerHTML = al.length ? `<div class="card alert-card"><h3>⏰ 30 天内到期</h3>${al.map((a) => `<div class="al ${a.days_left <= 7 ? "bad" : "warn"}">
      <span class="dot ${a.provider}"></span><a href="#/${a.provider}/${a.account_id}/billing">${esc(a.account_name)}</a> · ${esc(a.name)}
      <span class="grow"></span><b>${a.days_left === 0 ? "今天到期" : `剩 ${a.days_left} 天`}</b><span class="muted">${esc(a.date)}${a.estimated ? "（估算）" : ""}</span></div>`).join("")}</div>` : "";
  } catch (_) { box.innerHTML = ""; }
}

// ---------- 账单页：Credit 与教育优惠 ----------
async function creditCard(acc, box) {
  if (!box) return;
  let s;
  try { s = await api(`/accounts/${acc.id}/credit-summary`); } catch (e) { box.innerHTML = `<div class="card">❌ Credit：${esc(e.message)}</div>`; return; }
  const money = (v) => (v == null ? "—" : "$" + (+v).toFixed(2));
  const src = { billing: "按账单估算", manual: "手动填写" };
  const edu = s.edu;
  box.innerHTML = `<div class="card" id="credit"><div class="bar"><h3 class="grow" style="margin:0">Credit 与优惠</h3>
    <button class="btn sm" id="ctot">设置总额</button><button class="btn sm primary" id="cadd">添加 Credit</button></div>
    ${s.alerts.length ? s.alerts.map((a) => `<div class="al ${a.days_left <= 7 ? "bad" : "warn"}">⏰ ${esc(a.name)} ${a.days_left === 0 ? "今天到期" : `还剩 ${a.days_left} 天`}（${esc(a.date)}${a.estimated ? "，估算" : ""}）</div>`).join("") : ""}
    <div class="grid3"><div><div class="muted">Credit 总额${s.credit_total_manual ? "（手动设置）" : "（各条合计）"}</div><div class="big">${money(s.credit_total)}</div></div>
      <div><div class="muted">已用${s.used_source ? `（${src[s.used_source]}）` : ""}</div><div class="big">${money(s.used)}</div></div>
      <div><div class="muted">剩余</div><div class="big">${money(s.remaining)}</div></div></div>
    <p class="muted">${s.used == null && s.items.length ? "已用额度暂时估不出，可在每条 Credit 里手动填写。" : ""}估算依据：${esc(s.estimate_note || "-")}${s.billing_updated_at ? `（账单数据更新于 ${esc(s.billing_updated_at)}）` : ""}。
      ${acc.provider === "aws" ? "AWS 只读账单缓存，不会额外调用 Cost Explorer。" : "先到期的 Credit 先抵扣。"}</p>
    <table><tr><th>名称</th><th>初始额度</th><th>已用</th><th>剩余</th><th>起始</th><th>到期</th><th></th></tr>
    ${s.items.map((c) => `<tr><td>${esc(c.name)}</td><td>${money(c.amount)}</td><td>${money(c.used)}${c.used_source ? `<div class="muted">${src[c.used_source]}</div>` : `<div class="muted">估不出</div>`}</td>
      <td>${money(c.remaining)}</td><td>${esc(c.start_date || "-")}</td>
      <td>${esc(c.expire_date || "-")}${c.days_left != null ? `<div class="muted">${c.expired ? "已过期" : `剩 ${c.days_left} 天`}</div>` : ""}</td>
      <td><button class="btn sm" data-ced="${c.id}">编辑</button> <button class="btn sm danger" data-cdel="${c.id}">删除</button></td></tr>`).join("") || `<tr><td colspan=7 class="muted">还没有录入 Credit</td></tr>`}</table>
    <div class="kv" style="margin-top:14px"><span>云上创建</span><span>${s.cloud_created_at ? `${esc(s.cloud_created_at)}（已存活 ${s.age_days} 天）` : `<span class="muted">未填写</span>`}</span>
    ${edu ? `<span>教育优惠</span><span>${edu.expires_at ? `${esc(edu.expires_at)}${edu.estimated ? ` <span class="badge pending">估算</span>` : ""} · ${edu.days_left >= 0 ? `剩 ${edu.days_left} 天` : "已过期"}` : "未知"}
      <div class="muted">${esc(edu.basis)}</div></span>` : ""}</div>
    <div class="bar"><button class="btn sm" id="cinfo">${edu ? "设置创建日期 / 教育优惠到期日" : "设置云账号创建日期"}</button></div></div>`;
  const again = () => creditCard(acc, box);
  const credForm = (c = {}) => `<label>名称</label><input name="name" value="${esc(c.name || (acc.provider === "azure" ? "Azure 学生 Credit" : acc.provider === "oci" ? "OCI 试用 Credit" : "AWS Credit"))}">
    <div class="row2"><div><label>初始额度（USD）</label><input name="amount" type="number" step="0.01" min="0" value="${c.amount ?? ""}"></div>
    <div><label>已用额度（留空 = 按账单估算）</label><input name="used_manual" type="number" step="0.01" min="0" value="${c.used_manual ?? ""}"></div>
    <div><label>起始日期${acc.provider === "aws" ? "（AWS 用于统计累计抵扣）" : "（可选）"}</label><input name="start_date" type="date" value="${esc(c.start_date || "")}"></div>
    <div><label>到期日期</label><input name="expire_date" type="date" value="${esc(c.expire_date || "")}"></div></div>
    <p class="muted">30 天内到期会在总览提醒，并在 30 / 7 / 1 天各推送一次 Telegram。</p>`;
  $("#cadd", box).onclick = async () => {
    const r = await modal("添加 Credit", credForm(), (bg) => { const f = form(bg); if (!f.amount) throw new Error("初始额度必填"); return post(`/accounts/${acc.id}/credits-manual`, f); }, "保存");
    if (r) again();
  };
  $("#ctot", box).onclick = async () => {
    const r = await modal("Credit 总额", `<label>总额（USD，留空 = 各条 Credit 之和）</label><input name="credit_total" type="number" step="0.01" min="0" value="${s.credit_total_manual ? s.credit_total : ""}">`,
      (bg) => api(`/accounts/${acc.id}/credit-total`, { method: "PUT", body: form(bg) }), "保存");
    if (r) again();
  };
  $("#cinfo", box).onclick = () => accountInfoDialog(ACCOUNTS.find((a) => a.id === acc.id) || acc);
  box.querySelectorAll("[data-ced]").forEach((b) => (b.onclick = async () => {
    const c = s.items.find((x) => x.id == b.dataset.ced);
    const r = await modal("编辑 Credit", credForm(c), (bg) => api(`/accounts/${acc.id}/credits-manual/${c.id}`, { method: "PUT", body: form(bg) }), "保存");
    if (r) again();
  }));
  box.querySelectorAll("[data-cdel]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("删除 Credit", "确定删除这条 Credit？", true)) { await act(b, () => del(`/accounts/${acc.id}/credits-manual/${b.dataset.cdel}`), "已删除"); again(); }
  }));
}

// ---------- Azure 订阅（只读） ----------
async function tabAzSubscription(acc, box) {
  box.innerHTML = `<div class="card"><span class="spin"></span> 读取订阅信息…</div>`;
  let s;
  try { s = await api(`/accounts/${acc.id}/azure/subscription`); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const stCls = { Enabled: "running", Warned: "pending", PastDue: "pending", Disabled: "failed", Deleted: "failed" }[s.state] || "";
  const edu = s.edu || {};
  box.innerHTML = `<div class="grid"><div class="card"><h3>订阅</h3>
    ${s.error ? `<p>❌ ${esc(s.error)}</p><p class="muted">需要订阅的 Reader 权限。</p>` : `<div class="kv">
      <span>名称</span><span>${esc(s.display_name || "-")}</span><span>订阅 ID</span><span class="mono">${esc(s.subscription_id || "-")}</span>
      <span>状态</span><span><span class="badge ${stCls}">${esc(s.state || "-")}</span></span>
      <span>类型</span><span>${esc(s.offer || "-")}${s.quota_id ? `<div class="muted mono">${esc(s.quota_id)}</div>` : ""}</span>
      <span>支出限额</span><span>${esc({ On: "开启（额度用完即停用）", Off: "关闭", CurrentPeriodOff: "本期关闭" }[s.spending_limit] || s.spending_limit || "-")}</span>
      <span>区域策略</span><span class="mono">${esc(s.location_placement_id || "-")}</span>
      <span>授权方式</span><span>${esc(s.authorization_source || "-")}</span><span>租户</span><span class="mono">${esc(s.tenant_id || "-")}</span></div>`}</div>
    <div class="card"><h3>教育优惠</h3><div class="big">${edu.expires_at ? esc(edu.expires_at) : "—"}</div>
      <div class="muted">${edu.expires_at ? `${edu.estimated ? "估算 · " : ""}${edu.days_left >= 0 ? `还剩 ${edu.days_left} 天` : "已过期"}` : ""}</div>
      <p class="muted">${esc(edu.basis || "")}${s.age_days != null ? ` · 账号已存活 ${s.age_days} 天` : ""}</p>
      <div class="bar"><button class="btn sm" id="ainfo">设置创建日期 / 到期日</button><a class="btn sm" href="#/azure/${acc.id}/billing">Credit 与账单</a></div></div></div>
    <p class="muted">只读信息，来自 Azure Subscriptions API（免费）。Foundry 配额与模型部署暂不支持。</p>`;
  $("#ainfo", box).onclick = () => accountInfoDialog(ACCOUNTS.find((a) => a.id === acc.id) || acc);
}

// ================= v1.5 新增 =================
// ---- 创建弹窗「保存为默认」：与「设置 → 默认创建参数」是同一份数据 ----
const DEFAULT_SKIP = ["name", "interval", "max_attempts", "script", "password_login", "region", "location_hint"];
const saveDefaultBtn = (kind) => `<button class="btn" type="button" data-savedef="${kind}" title="把当前表单的值保存为该云的创建默认值（不含名称、密码、脚本内容）">💾 保存为默认</button>`;
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-savedef]");
  if (!b) return;
  const root = b.closest(".modal") || b.closest(".card") || document;
  const vals = form(root);
  for (const k of Object.keys(vals)) if (DEFAULT_SKIP.includes(k) || k.startsWith("c_")) delete vals[k];
  const r = await act(b, () => api("/create-defaults", { method: "PUT", body: { provider: b.dataset.savedef, defaults: vals } }), "已保存为默认值");
  if (r) SETTINGS.default_create = { ...(SETTINGS.default_create || {}), [b.dataset.savedef]: r.defaults };
});

// ---- OCI 安全组（独立标签页）：按规则内容删除、批量端口、对公网放行二次确认 ----
const PUBLIC_CIDR = (c) => ["0.0.0.0/0", "::/0"].includes(String(c || "").replace(/\s/g, ""));
async function tabOciSecGroup(acc, box) {
  const reload = () => tabOciSecGroup(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<select id="sgInst"><option value="">加载实例…</option></select>
    <button class="btn" id="sgRf">刷新</button><button class="btn primary" id="sgAdd" disabled>添加规则</button><span class="grow"></span>
    <span class="muted">规则作用于实例所在子网的安全列表（同子网实例共享）</span></div><div class="card" id="sgBox"><div class="empty">选择实例后显示安全规则</div></div>`;
  $("#sgRf", box).onclick = reload;
  let list = [];
  try { list = await api(`/accounts/${acc.id}/instances?kind=vm&${rq(acc)}`); } catch (e) { $("#sgBox", box).innerHTML = `❌ ${esc(e.message)}`; return; }
  const last = localStorage.getItem("tc_sg_" + acc.id);
  $("#sgInst", box).innerHTML = list.length ? list.map((i) => `<option value="${esc(i.id)}" ${i.id === last ? "selected" : ""}>${esc(i.name)} · ${esc(i.public_ip || i.state)}</option>`).join("")
    : `<option value="">该区域没有实例</option>`;
  const load = async () => {
    const iid = $("#sgInst", box).value;
    $("#sgAdd", box).disabled = !iid;
    if (!iid) return;
    localStorage.setItem("tc_sg_" + acc.id, iid);
    $("#sgBox", box).innerHTML = `<span class="spin"></span>`;
    let d;
    try { d = await api(`/accounts/${acc.id}/security-rules?instance_id=${encodeURIComponent(iid)}&${rq(acc)}`); }
    catch (e) { $("#sgBox", box).innerHTML = `❌ ${esc(e.message)}`; return; }
    const multi = d.lists.length > 1;
    const st = { dir: "all", q: "" };
    const many = d.rules.length > 10;
    $("#sgBox", box).innerHTML = `<div class="bar sgf"><span class="seg">${[["all", "全部"], ["ingress", "入站"], ["egress", "出站"]].map(([k, t]) => `<button class="btn sm${k === "all" ? " primary" : ""}" data-sgdir="${k}">${t}</button>`).join("")}</span>
      ${many ? `<input id="sgQ" class="sm" placeholder="筛选端口 / IP / 协议 / 描述" style="max-width:240px">` : ""}<span class="grow"></span><span class="muted" id="sgCnt"></span></div><div id="sgTbl"></div>`;
    const draw = () => {
      const q = st.q.trim().toLowerCase();
      const shown = d.rules.map((r, i) => [r, i]).filter(([r]) => (st.dir === "all" || r.direction === st.dir)
        && (!q || [r.port, r.cidr, r.protocol, r.desc, r.sl_name].some((x) => String(x ?? "").toLowerCase().includes(q))));
      $("#sgCnt", box).textContent = shown.length === d.rules.length ? `共 ${d.rules.length} 条` : `${shown.length} / ${d.rules.length} 条`;
      $("#sgTbl", box).innerHTML = `<table><tr><th>方向</th><th>协议</th><th>来源 / 目标</th><th>端口</th><th>描述</th>${multi ? "<th>安全列表</th>" : ""}<th></th></tr>
      ${shown.map(([r, i]) => `<tr><td>${r.direction === "ingress" ? "入站" : "出站"}</td><td>${esc(r.protocol)}</td>
      <td class="mono">${esc(r.cidr)}${PUBLIC_CIDR(r.cidr) && r.direction === "ingress" ? ` <span class="badge failed">公网</span>` : ""}</td><td class="mono">${esc(r.port)}</td>
      <td>${esc(r.desc)}</td>${multi ? `<td>${esc(r.sl_name)}</td>` : ""}<td><button class="btn sm danger" data-sgdel="${i}">删除</button></td></tr>`).join("")
      || `<tr><td colspan="7" class="muted">${d.rules.length ? "没有匹配的规则" : "没有规则"}</td></tr>`}</table>`;
    $("#sgTbl", box).querySelectorAll("[data-sgdel]").forEach((b) => (b.onclick = async () => {
      const r = d.rules[+b.dataset.sgdel];
      if (!(await confirmBox("删除规则", `删除${r.direction === "ingress" ? "入站" : "出站"} ${esc(r.protocol)} ${esc(r.cidr)} 端口 ${esc(r.port)}？${r.direction === "ingress" && r.port === "22" ? "<br>⚠️ 删除 22 端口规则可能导致无法 SSH 登录。" : ""}`, true))) return;
      const proto = { TCP: "tcp", UDP: "udp", ICMP: "icmp", ICMPv6: "icmpv6", "全部": "all" }[r.protocol] || String(r.protocol).toLowerCase();
      if (await act(b, () => api(`/accounts/${acc.id}/security-rules`, { method: "DELETE", body: { instance_id: iid, region: regionOf(acc) || undefined, sl_id: r.sl_id,
        direction: r.direction, protocol: proto, cidr: r.cidr, port_min: r.port_min, port_max: r.port_max } }), "已删除")) load();
    }));
    };
    box.querySelectorAll("[data-sgdir]").forEach((b) => (b.onclick = () => {
      st.dir = b.dataset.sgdir;
      box.querySelectorAll("[data-sgdir]").forEach((x) => x.classList.toggle("primary", x === b));
      draw();
    }));
    if (many) $("#sgQ", box).oninput = (e) => { st.q = e.target.value; draw(); };
    draw();
    $("#sgAdd", box).onclick = () => addRule(iid, d.lists);
  };
  const addRule = async (iid, lists) => {
    const v = await modal("添加安全规则", `<div class="row2"><div><label>方向</label><select name="direction"><option value="ingress">入站</option><option value="egress">出站</option></select></div>
      <div><label>协议</label><select name="protocol"><option value="tcp">TCP</option><option value="udp">UDP</option><option value="icmp">ICMP</option><option value="icmpv6">ICMPv6</option><option value="all">全部协议</option></select></div></div>
      <label>来源 CIDR（出站规则为目标 CIDR）</label><input name="cidr" placeholder="如 203.0.113.0/24；0.0.0.0/0 表示整个互联网">
      ${portModeFields()}
      ${lists.length > 1 ? `<label>安全列表</label><select name="sl_id">${lists.map((l) => `<option value="${esc(l.id)}">${esc(l.name)}</option>`).join("")}</select>` : ""}
      <label>描述（可选）</label><input name="description">
      <p class="muted">不支持对 0.0.0.0/0 一键放行全部端口（需要请到 OCI 控制台操作）。</p>`, (bg) => form(bg), "下一步");
    if (!v) return;
    const { port_mode, port_min, port_max, ...rest } = v;   // eslint-disable-line no-unused-vars
    const body = { instance_id: iid, region: regionOf(acc) || undefined, ...rest, ports: portsOf(v) };
    if (!body.ports) delete body.ports;
    if (PUBLIC_CIDR(v.cidr) && v.direction === "ingress") {
      const go = await publicWarn(v.cidr, body.ports ? `端口 <code>${esc(body.ports)}</code>` : "该协议", "我已了解，继续添加");
      if (!go) return;
      body.confirm_public = true;
    }
    const r = await act(null, () => post(`/accounts/${acc.id}/security-rules`, body));
    if (r) { toast(`已添加 ${r.added} 条${r.skipped ? `，跳过已存在 ${r.skipped} 条` : ""}`); load(); }
  };
  $("#sgInst", box).onchange = load;
  load();
}

// ---- CloudFront：新建 / 缓存刷新 / 编辑配置 / 启停 / 套餐 / 删除（启用中先停用再删） ----
const CF_PLAN = { PAYGO: "按量付费", FREE: "Free $0/月", PRO: "Pro $15/月", BUSINESS: "Business $200/月", PREMIUM: "Premium $1000/月起" };
async function tabCloudFront(acc, box) {
  const reload = () => tabCloudFront(acc, box);
  box.innerHTML = `<div class="bar"><button class="btn" id="rf">刷新</button><button class="btn primary" id="new">新建分发</button>
    <span class="grow"></span><span class="muted">缓存刷新每月前 1000 条路径免费（/* 算 1 条）</span></div><div class="card" id="t"><span class="spin"></span></div>`;
  $("#rf", box).onclick = reload;
  $("#new", box).onclick = async () => {
    const r = await modal("新建 CloudFront 分发", `<label>源站域名</label><input name="origin" placeholder="origin.example.com（不带 https:// 和路径）">
      <div class="row2"><div><label>回源协议</label><select name="origin_protocol"><option value="http-only">HTTP</option><option value="https-only">HTTPS</option><option value="match-viewer">跟随访客</option></select></div>
      <div><label>价格等级</label><select name="price_class"><option value="all">全部边缘节点</option><option value="200">200（含亚洲）</option><option value="100">100（北美+欧洲，最便宜）</option></select></div>
      <div><label>缓存模式</label><select name="cache_mode"><option value="disabled">不缓存（反代动态内容）</option><option value="optimized">缓存优化（静态资源）</option></select></div>
      <div><label>&nbsp;</label><label><input type="checkbox" name="compress" style="width:auto" checked> 自动压缩</label></div></div>
      <label>备注</label><input name="comment"><p class="muted">部署约 5~15 分钟。默认值与 v1.4 相同：不缓存 + 全部边缘节点。</p>`,
      (bg) => post(`/accounts/${acc.id}/cloudfront`, { op: "create", ...form(bg) }), "创建");
    if (r) { toast(`已创建：${r.domain}`); reload(); }
  };
  let list;
  try { list = await api(`/accounts/${acc.id}/cloudfront`); } catch (e) { $("#t", box).textContent = "❌ " + e.message; return; }
  $("#t", box).innerHTML = list.length ? `<table><tr><th>ID / 域名</th><th>源站</th><th>状态</th><th>套餐 / 价格等级</th><th>操作</th></tr>
    ${list.map((d) => `<tr><td><b>${esc(d.id)}</b><br><code>${esc(d.domain)}</code>${d.aliases.length ? "<br>" + d.aliases.map(esc).join(", ") : ""}
    <div class="muted">${esc(d.comment)}</div></td><td class="mono">${d.origins.map(esc).join("<br>")}</td>
    <td><span class="badge ${esc(d.status)}">${esc(d.status)}</span><br>${d.enabled ? "已启用" : "已停用"}</td>
    <td>${d.plan == null ? "未知" : esc(CF_PLAN[d.plan] || d.plan)}<div class="muted">${esc(d.price_class || "-")}</div></td>
    <td><button class="btn sm" data-cf="inv" data-id="${esc(d.id)}">缓存刷新</button> <button class="btn sm" data-cf="edit" data-id="${esc(d.id)}">编辑</button>
    <button class="btn sm" data-cf="toggle" data-id="${esc(d.id)}">${d.enabled ? "停用" : "启用"}</button> <button class="btn sm" data-cf="plan" data-id="${esc(d.id)}">套餐</button>
    <button class="btn sm danger" data-cf="delete" data-id="${esc(d.id)}">删除</button></td></tr>`).join("")}</table>` : `<div class="empty">暂无分发</div>`;
  box.querySelectorAll("[data-cf]").forEach((b) => (b.onclick = () => cfOp(acc, list.find((x) => x.id === b.dataset.id), b.dataset.cf, b, reload)));
}
async function cfOp(acc, d, op, btn, reload) {
  const base = `/accounts/${acc.id}/cloudfront`;
  if (op === "inv") {
    const r = await modal(`缓存刷新 · ${d.id}`, `<label>路径（每行一条，留空 = /*）</label><textarea name="paths" placeholder="/*&#10;/index.html&#10;/static/*"></textarea>
      <p class="muted">每月前 1000 条路径免费，超出按条计费；通配符 /* 只算 1 条。</p>`, (bg) => post(`${base}/invalidate`, { distribution_id: d.id, paths: form(bg).paths }), "提交刷新");
    if (r) toast(`已提交刷新 ${r.invalidation_id}：${r.paths.join(", ")}`);
  } else if (op === "edit") {
    let c;
    try { c = await api(`${base}/${encodeURIComponent(d.id)}/config`); } catch (e) { return toast(e.message, true); }
    const r = await modal(`编辑分发 · ${d.id}`, `<label>备注</label><input name="comment" value="${esc(c.comment)}">
      <label>源站域名</label><input name="origin_domain" value="${esc(c.origin_domain)}">
      <div class="row2"><div><label>回源协议</label><select name="origin_protocol">${["http-only", "https-only", "match-viewer"].map((x) => `<option ${x === c.origin_protocol ? "selected" : ""}>${x}</option>`).join("")}</select></div>
      <div><label>价格等级</label><select name="price_class">${["100", "200", "All"].map((x) => `<option ${x === c.price_class ? "selected" : ""}>${x}</option>`).join("")}</select></div></div>
      <label>默认根对象</label><input name="default_root_object" value="${esc(c.default_root_object)}" placeholder="index.html">
      <p class="muted">保存后重新部署，约需几分钟生效。</p>`, (bg) => {
      const f = form(bg);
      if (!c.origin_protocol) delete f.origin_protocol;
      return api(`${base}/${encodeURIComponent(d.id)}`, { method: "PUT", body: f });
    }, "保存");
    if (r) { toast(r.message); reload(); }
  } else if (op === "toggle") {
    if (!(await confirmBox(d.enabled ? "停用分发" : "启用分发", d.enabled ? `停用后 ${esc(d.domain)} 将无法访问（配置保留，可再启用）。确定？` : `启用 ${esc(d.id)}？`, d.enabled))) return;
    if (await act(btn, () => post(`${base}/toggle`, { distribution_id: d.id, enabled: !d.enabled }), (x) => x.message)) setTimeout(reload, 1500);
  } else if (op === "plan") {
    const cur = d.plan || "PAYGO";
    const tier = await modal(`切换套餐 · ${d.id}`, `<p class="muted">当前：${d.plan == null ? "未知（无 pricing-plan-manager 权限时显示未知）" : esc(CF_PLAN[cur] || cur)}。包月套餐按分发单独计费，切换后立即生效；价格以 AWS 官网为准。</p>
      ${Object.entries(CF_PLAN).map(([k, l]) => `<label class="chip" style="display:flex"><input type="radio" name="tier" value="${k}" style="width:auto" ${k === cur ? "checked" : ""}> ${l}</label>`).join("")}`,
      (bg) => { const v = bg.querySelector("input[name=tier]:checked"); return v ? v.value : false; }, "下一步");
    if (!tier || tier === cur) return tier === cur && toast("已是当前套餐");
    const paid = ["PRO", "BUSINESS", "PREMIUM"].includes(tier);
    if (paid && !(await confirmBox("确认订阅付费套餐", `⚠️ 为分发 ${esc(d.id)} 订阅 <b>${esc(CF_PLAN[tier])}</b>，将立即开始按月计费。确定？`, true))) return;
    if (await act(btn, () => post(`${base}/plan`, { distribution_id: d.id, plan_tier: tier, confirm: paid }), (x) => x.message)) reload();
  } else if (op === "delete") {
    const msg = d.enabled || d.status !== "Deployed"
      ? `⚠️ 删除分发 <b>${esc(d.id)}</b>（${esc(d.domain)}）？<br>它当前${d.enabled ? "仍在启用" : "正在部署"}：面板会先停用、等待部署完成（通常 5~20 分钟），再自动删除。删除后不可恢复。`
      : `⚠️ 删除分发 <b>${esc(d.id)}</b>（${esc(d.domain)}）？删除后不可恢复。`;
    if (!(await confirmBox("删除分发", msg, true))) return;
    const r = await act(btn, () => del(`${base}/${encodeURIComponent(d.id)}?confirm=true`));
    if (r) { toast(r.deleted ? "已删除" : `已创建任务 #${r.task_id}：停用并等待部署完成后自动删除`); reload(); }
  }
}

// ---- 已删账号（账号管理入口）。注意与 AWS「闲置资源」估算不是一回事 ----
async function pageDeletedAccounts() {
  loading();
  const d = await api("/recycle-bin");
  const s = d.stats;
  const money = (x) => (x == null ? "—" : `${x.currency === "USD" || !x.currency ? "$" : ""}${(+x.est_cost).toFixed(2)}${x.currency && x.currency !== "USD" ? " " + esc(x.currency) : ""}`);
  view.innerHTML = `<div class="bar"><a class="btn" href="#/accounts">← 云账号</a><span class="grow"></span>
    ${s.count ? `<button class="btn danger" id="clr">清空记录</button>` : ""}</div>
  <div class="grid"><div class="card"><h3>已删账号</h3><div class="big">${s.count}</div><div class="muted">${Object.entries(s.by_provider).map(([k, v]) => `${PNAME[k] || esc(k)} ${v}`).join(" · ") || "暂无"}</div></div>
    <div class="card"><h3>存活天数</h3><div class="big">${s.avg_lifecycle_days ?? "—"}</div><div class="muted">平均 · 最长 ${s.max_lifecycle_days ?? "—"} 天</div></div>
    <div class="card"><h3>预估费用合计</h3><div class="big">$${(s.total_est_cost_usd || 0).toFixed(2)}</div><div class="muted">单个最高 $${(s.max_est_cost_usd || 0).toFixed(2)}（仅统计 USD）</div></div></div>
  <div class="card"><p class="muted">删除账号时自动留档：名称、云、存活天数、预估费用（取自删除前的本地账单缓存，删除时不调用任何云 API）。只是记录，不会恢复账号或影响云上资源。
    AWS 账号页的「闲置资源」是另一项功能：估算仍在计费的闲置 EIP / 卷 / 快照等。</p>
    <table><tr><th>名称</th><th>云</th><th>存活</th><th>预估费用</th><th>删除时间</th><th></th></tr>
    ${d.items.map((x) => `<tr><td>${esc(x.name)}${x.source === "legacy" ? ` <span class="badge">旧版迁移</span>` : ""}</td><td><span class="dot ${esc(x.provider)}"></span> ${PNAME[x.provider] || esc(x.provider)}</td>
    <td>${x.lifecycle_days == null ? "—" : `${x.lifecycle_days} 天`}<div class="muted">${esc(x.age_basis || "")}</div></td>
    <td>${money(x)}<div class="muted">${esc(x.cost_basis || "")}</div></td><td>${fmtDT(x.deleted_at)}</td>
    <td><button class="btn sm" data-rdel="${x.id}">移除记录</button></td></tr>`).join("") || `<tr><td colspan="6" class="muted">还没有删除过账号</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-rdel]").forEach((b) => (b.onclick = async () => { await act(b, () => del(`/recycle-bin/${b.dataset.rdel}`)); pageDeletedAccounts(); }));
  if ($("#clr")) $("#clr").onclick = async () => { if (await confirmBox("清空已删账号记录", "只清空记录，不影响任何账号或云资源。确定？", true)) { await act(null, () => del("/recycle-bin?confirm=true"), "已清空"); pageDeletedAccounts(); } };
}

// ---- 账号编辑：非敏感字段回显，密钥类留空不改；代理 URL + 用户名 + 密码 ----
const CRED_LABEL = { user: "用户 OCID", tenancy: "租户 OCID", fingerprint: "API Key 指纹", key_content: "私钥 (PEM)", pass_phrase: "私钥密码", region: "区域",
  compartment: "区间 OCID（可选）", home_region: "主区域（可选）", access_key: "Access Key ID", secret_key: "Secret Access Key", tenant_id: "Tenant ID",
  client_id: "Client (App) ID", client_secret: "Client Secret", subscription_id: "Subscription ID" };
const proxyFields = (d = {}) => `<label>出口代理地址（可选，留空 = 直连）</label><input name="proxy" value="${esc(d.proxyUrl || "")}" placeholder="http://host:3128 或 socks5://host:1080" autocomplete="off">
  <div class="row2"><div><label>代理用户名（可选）</label><input name="proxy_user" value="${esc(d.proxy_user || "")}" autocomplete="off"></div>
  <div><label>代理密码${d.proxy_pass_set ? "（已设置，留空不改）" : "（可选）"}</label><input name="proxy_pass" type="password" placeholder="${d.proxy_pass_set ? "留空保持不变" : ""}" autocomplete="new-password"></div></div>
  ${d.proxy_pass_set ? `<label><input type="checkbox" name="proxy_pass_clear" style="width:auto"> 清除代理密码</label>` : ""}
  <p class="muted">也兼容旧写法 http://user:pass@host:port。密码加密保存、不回显。</p>`;
async function editAccount(a) {
  let d;
  if (!a) return toast("找不到该账号，请刷新后重试", true);
  toast("正在读取账号信息…");
  try { d = await Promise.race([api(`/accounts/${a.id}/detail`), new Promise((_, rj) => setTimeout(() => rj(new Error("读取账号信息超时（15 秒），请检查网络或刷新")), 15000))]); }
  catch (e) { return toast(e.message, true); }
  const fld = Object.entries(d.fields).map(([k, v]) => {
    const label = CRED_LABEL[k] || k;
    if (typeof v === "string") return TEXTAREA_FIELDS.has(k) ? `<label>${label}</label><textarea name="c_${k}" rows="4" class="mono">${esc(v)}</textarea>`
      : `<label>${label}</label><input name="c_${k}" value="${esc(v)}" autocomplete="off">`;
    const ph = v.set ? `已设置${v.hint ? " " + v.hint : ""}，留空不改` : "未设置";
    return TEXTAREA_FIELDS.has(k) ? `<label>${label}</label><textarea name="c_${k}" placeholder="${esc(ph)}"></textarea>`
      : `<label>${label}</label><input name="c_${k}" type="${/secret|pass_phrase/.test(k) ? "password" : "text"}" placeholder="${esc(ph)}" autocomplete="new-password">`;
  }).join("");
  const r = await modal(`编辑账号 · ${a.name}`, `<label>备注名称</label><input name="name" value="${esc(d.name)}">${fld}
    <h4 style="margin:14px 0 4px">出口代理</h4>${proxyFields(d)}
    <p class="muted">修改了凭证时会先测活，通过才保存。代理地址出于安全只回显主机，修改代理请重新填写完整地址；只改用户名 / 密码时地址可留空不动。</p>`, async (bg) => {
    const f = form(bg); const body = { name: f.name }; const cred = {};
    for (const k in f) if (k.startsWith("c_")) cred[k.slice(2)] = f[k];
    if (Object.keys(cred).length) body.cred = cred;
    if (f.proxy) body.proxy = f.proxy;
    if (f.proxy_user !== (d.proxy_user || "")) body.proxy_user = f.proxy_user;
    if (f.proxy_pass) body.proxy_pass = f.proxy_pass;
    if (f.proxy_pass_clear) body.proxy_pass_clear = true;
    return api(`/accounts/${a.id}`, { method: "PATCH", body });
  }, "保存");
  if (r) { toast("已保存"); await loadAccounts(); route(); }
}

// ---- OCI config 粘贴识别：多 profile 段 + PEM 私钥 ----
// v1.6：添加账号弹窗的「粘贴自动识别」，由后端 /accounts/parse 统一解析
let SMART_ITEMS = [], SMART_T = 0;
function smartFill() {
  const sel = document.getElementById("smartpick"), hint = document.getElementById("smarthint");
  if (!sel || !hint) return;
  const it = SMART_ITEMS[+sel.value || 0];
  if (!it) return;
  const np = document.getElementById("np");
  if (np && np.value !== it.provider) { np.value = it.provider; np.dispatchEvent(new Event("change", { bubbles: true })); }
  for (const [k, v] of Object.entries(it.cred || {})) { const el = document.querySelector(`.modal [name="c_${k}"]`); if (el && v) el.value = v; }
  const nm = document.querySelector('.modal [name="name"]');
  if (nm && it.name && (!nm.value || nm.dataset.auto)) { nm.value = it.name; nm.dataset.auto = "1"; }
  hint.innerHTML = `已识别为 <b>${PNAME[it.provider] || esc(it.provider)}</b>` + (it.missing.length ? `，还缺：${it.missing.map(esc).join("、")}` : "，字段齐全")
    + (it.error ? `；${esc(it.error)}` : "")
    + (SMART_ITEMS.length > 1 ? `。共识别到 ${SMART_ITEMS.length} 个账号，可在上面切换，或 <a href="#" id="smartbatch">全部批量添加</a>` : "");
  const bl = document.getElementById("smartbatch");
  if (bl) bl.onclick = (e) => { e.preventDefault(); const t = document.getElementById("smarttext").value; document.querySelector(".modal [data-x]")?.click(); batchAddAccounts(t); };
}
async function smartParse() {
  const ta = document.getElementById("smarttext"), sel = document.getElementById("smartpick"), hint = document.getElementById("smarthint");
  if (!ta) return;
  if (!ta.value.trim()) { SMART_ITEMS = []; sel.style.display = "none"; hint.textContent = ""; return; }
  try {
    const r = await post("/accounts/parse", { text: ta.value });
    SMART_ITEMS = (r.items || []).filter((x) => x.provider);
    if (!SMART_ITEMS.length) { sel.style.display = "none"; hint.textContent = "没有识别到云账号凭证"; return; }
    sel.innerHTML = SMART_ITEMS.map((x, i) => `<option value="${i}">${i + 1}. ${PNAME[x.provider]} · ${esc(x.name || "未命名")}</option>`).join("");
    sel.style.display = SMART_ITEMS.length > 1 ? "" : "none";
    smartFill();
  } catch (e) { hint.textContent = `❌ ${e.message}`; }
}
document.addEventListener("input", (e) => { if (e.target.id === "smarttext") { clearTimeout(SMART_T); SMART_T = setTimeout(smartParse, 350); } });
document.addEventListener("change", (e) => { if (e.target.id === "smartpick") smartFill(); });


// ---------------- 启动 ----------------
async function loadAccounts() {
  ACCOUNTS = await api("/accounts");
  try { const m = await api("/meta"); if (m && Array.isArray(m.providers)) META = m; } catch (_) { /* 旧后端没有 /meta：按默认 */ }
}
(async function init() {
  const th = $("#theme"); th.value = TCTheme.get(); th.onchange = () => TCTheme.set(th.value);
  // 手机（≤600px）顶栏配色下拉只显示图标，避免「🖥 跟」被截断
  const thMq = window.matchMedia ? window.matchMedia("(max-width: 600px)") : null;
  const thLabels = () => [...th.options].forEach((o) => {
    if (!o.dataset.full) o.dataset.full = o.textContent;
    o.textContent = thMq && thMq.matches ? o.dataset.full.split(" ")[0] : o.dataset.full;
  });
  thLabels();
  if (thMq) (thMq.addEventListener ? thMq.addEventListener("change", thLabels) : thMq.addListener && thMq.addListener(thLabels));
  $("#menuBtn").onclick = () => $("#side").classList.toggle("open");
  // 手机抽屉遮罩：点击关闭
  let scrim = $(".drawer-scrim");
  if (!scrim) { scrim = document.createElement("div"); scrim.className = "drawer-scrim"; $("#side").after(scrim); }
  scrim.onclick = () => $("#side").classList.remove("open");
  // 顶栏滚动时加阴影（Material top app bar）
  window.addEventListener("scroll", () => $(".top").style.boxShadow = window.scrollY > 4 ? "var(--e2)" : "", { passive: true });
  // 手机端表格转卡片：给每个 td 标注列名
  const labelTables = (root) => root.querySelectorAll("table").forEach((t) => {
    const ths = [...t.querySelectorAll("tr:first-child th")].map((h) => h.textContent.trim());
    if (!ths.length) return;
    t.querySelectorAll("tr").forEach((tr) => [...tr.children].forEach((td, i) => { if (td.tagName === "TD" && !td.hasAttribute("colspan")) td.dataset.label = ths[i] || ""; }));
  });
  new MutationObserver((ms) => { for (const m of ms) m.addedNodes.forEach((n) => n.nodeType === 1 && labelTables(n.tagName === "TABLE" ? n.parentNode : n)); })
    .observe(document.body, { childList: true, subtree: true });
  $("#logout").onclick = async () => { await post("/logout"); location.href = "/login"; };
  // v1.4 任务抽屉
  $("#taskBtn").onclick = () => (TaskDrawer.isOpen() ? TaskDrawer.close() : TaskDrawer.open());
  $("#tdClose").onclick = () => TaskDrawer.close();
  $("#tdScrim").onclick = () => TaskDrawer.close();
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && TaskDrawer.isOpen() && !document.querySelector(".modal-bg")) TaskDrawer.close(); });
  const badge = () => { if (!document.hidden && !TaskDrawer.isOpen()) api("/tasks?limit=20").then(updateTaskBadge).catch(() => {}); };
  setInterval(badge, 15000);
  await loadAccounts();
  SETTINGS = await api("/settings").catch(() => ({}));
  route();
  api("/tasks?limit=20").then(updateTaskBadge).catch(() => {});
})();

// =====================================================================
// v1.6：重装系统、块存储卷、区域订阅、附加 IP / 预留 IP / 辅助网卡、IP 质量、账号类型与停用、
//       Azure 磁盘、免费 AMD 下行 500Mbps、对象存储、Lightsail 静态 IP 与防火墙、免费额度体检
// =====================================================================
const lastModal = () => { const l = document.querySelectorAll(".modal-bg"); return l[l.length - 1]; };
const fmtBytes = (n) => { n = +n || 0; const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return `${n.toFixed(i ? 1 : 0)} ${u[i]}`; };

// ---------- 3. 重装系统 ----------
const AWS_OS = [["debian-12", "Debian 12"], ["ubuntu-24.04", "Ubuntu 24.04"], ["ubuntu-22.04", "Ubuntu 22.04"], ["al2023", "Amazon Linux 2023"]];
const AZ_OS = [["debian-12", "Debian 12"], ["ubuntu-24.04", "Ubuntu 24.04"], ["ubuntu-22.04", "Ubuntu 22.04"]];
async function reinstallDialog(acc, inst, base) {
  const oci = acc.provider === "oci";
  const osField = oci ? `<div class="row2" data-oci-os><input type="hidden" name="shape" value="${esc(inst.shape || "")}">${ociOsFields({})}</div>
      <label>新引导卷大小 GB（留空 = 与当前相同，不能变小）</label><input name="disk_gb" type="number" min="47">`
    : `<label>系统</label><select name="os">${(acc.provider === "aws" ? AWS_OS : AZ_OS).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>`;
  const how = oci ? "替换引导卷：实例 OCID、私网 IP、公网 IP 不变。"
    : acc.provider === "aws" ? "替换根卷（Replace Root Volume）：实例 ID、私网 IP、弹性 IP 不变；沿用原密钥对与 user-data。"
      : "删除 VM 后用同名、同大小、原网卡（含公网 IP）和原数据盘重新创建。";
  const p = modal("重装系统", `<p>⚠️ 将重装「${esc(inst.name)}」，<b>系统盘上的全部数据会被清空</b>，不可恢复。</p>
    <p class="muted">${how}实例会停机几分钟。</p>${osField}
    ${acc.provider === "aws" ? "" : `<label><input type="checkbox" name="password_login" style="width:auto" checked> 生成新的随机 root 密码（完成后在「开机密码」查看）</label>
    <label>SSH 公钥（可选，留空沿用原公钥）</label><textarea name="ssh_key" placeholder="ssh-ed25519 AAAA..."></textarea>`}
    <label><input type="checkbox" name="confirm" style="width:auto"> 我已确认要清空系统盘数据</label>`, (bg) => {
    const f = form(bg);
    if (!f.confirm) throw new Error("请先勾选确认");
    delete f.shape;
    return post(`/accounts/${acc.id}/instances/reinstall`, { ...base, ...f, confirm: true });
  }, "开始重装", true);
  if (oci) setTimeout(() => wireOciOs(lastModal() && lastModal().querySelector("[data-oci-os]"), acc), 0);
  const r = await p;
  if (r) toast(`已创建任务 #${r.task_id}，完成后推送通知`);
}

// ---------- 8. OCI 附加 IP / 辅助网卡 / 预留 IP ----------
async function ociIpsDialog(acc, inst, base, reload) {
  let d;
  try { toast("读取网卡与 IP…"); d = await api(`/accounts/${acc.id}/oci/ips?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  const ipRow = (v, ip) => `<tr><td class="mono">${esc(ip.ip)}${ip.primary ? ` <span class="badge">主</span>` : ""}</td>
    <td class="mono">${ip.public ? `${esc(ip.public.ip)} <span class="muted">${ip.public.lifetime === "RESERVED" ? "预留" : "临时"}</span>` : "-"}</td>
    <td>${ip.primary ? "" : `<button class="btn sm danger" data-delip="${esc(ip.id)}">删除</button>`}</td></tr>`;
  const html = d.vnics.map((v) => `<h4>${v.primary ? "主网卡" : "辅助网卡"} · ${esc(v.name || "")}
      ${v.primary ? `<button class="btn sm" data-addip="${esc(v.vnic_id)}">+ 辅助 IP</button>` : `<button class="btn sm danger" data-detach="${esc(v.attachment_id)}">卸载网卡</button>`}</h4>
    <table><tr><th>私网 IP</th><th>公网 IP</th><th></th></tr>${v.ips.map((ip) => ipRow(v, ip)).join("")}</table>`).join("")
    + `<div class="bar" style="margin-top:10px"><button class="btn" id="addVnic">+ 辅助网卡</button></div>
    <h4>预留公网 IP（换机 / 重装后 IP 不变）<button class="btn sm" id="newRes">+ 新建预留 IP</button></h4>
    <table><tr><th>IP</th><th>状态</th><th></th></tr>${d.reserved.map((r) => `<tr><td class="mono">${esc(r.ip)}</td><td>${r.assigned ? "已绑定" : "未绑定"}</td>
      <td>${r.assigned ? `<button class="btn sm" data-unres="${esc(r.id)}">解绑</button>` : `<button class="btn sm" data-res="${esc(r.id)}" data-ip="${esc(r.ip)}">绑到本机</button> <button class="btn sm danger" data-delres="${esc(r.id)}">删除</button>`}</td></tr>`).join("") || `<tr><td colspan=3 class="muted">暂无</td></tr>`}</table>
    <p class="muted">辅助 IP / 辅助网卡需要在系统内配置后才生效（完成后会给出命令）。预留 IP 绑到本机会替换当前临时公网 IP。</p>`;
  const done = (r) => { if (r && r.hint) modal("已完成", `<p>${esc(r.hint)}</p>`, null, "知道了"); else toast("已完成"); lastModal() && lastModal().remove(); ociIpsDialog(acc, inst, base, reload); };
  const opp = (b, body) => act(b, () => post(`/accounts/${acc.id}/oci/ips`, { region: regionOf(acc) || undefined, instance_id: inst.id, ...body })).then((r) => r && done(r));
  modal(`附加 IP · ${inst.name}`, html, null, "关闭");
  const bg = lastModal();
  bg.querySelectorAll("[data-addip]").forEach((b) => (b.onclick = () => opp(b, { op: "add_secondary", vnic_id: b.dataset.addip })));
  bg.querySelectorAll("[data-delip]").forEach((b) => (b.onclick = async () => { if (await confirmBox("删除辅助 IP", "删除这个辅助私网 IP（及其公网 IP）？", true)) opp(b, { op: "delete_private", private_ip_id: b.dataset.delip }); }));
  bg.querySelectorAll("[data-detach]").forEach((b) => (b.onclick = async () => { if (await confirmBox("卸载辅助网卡", "卸载后该网卡上的 IP 全部释放。确定？", true)) opp(b, { op: "detach_vnic", attachment_id: b.dataset.detach }); }));
  bg.querySelector("#addVnic").onclick = (e) => opp(e.target, { op: "attach_vnic" });
  bg.querySelector("#newRes").onclick = (e) => opp(e.target, { op: "create_reserved" });
  bg.querySelectorAll("[data-res]").forEach((b) => (b.onclick = async () => { if (await confirmBox("绑定预留 IP", `把 ${esc(b.dataset.ip)} 绑到「${esc(inst.name)}」？当前临时公网 IP 会被释放。`)) opp(b, { op: "assign_reserved", public_ip_id: b.dataset.res, ip: b.dataset.ip }).then(() => setTimeout(reload, 1500)); }));
  bg.querySelectorAll("[data-unres]").forEach((b) => (b.onclick = async () => { if (await confirmBox("解绑预留 IP", "解绑后会自动给实例分配一个新的临时公网 IP。确定？")) opp(b, { op: "unassign_reserved", public_ip_id: b.dataset.unres }).then(() => setTimeout(reload, 1500)); }));
  bg.querySelectorAll("[data-delres]").forEach((b) => (b.onclick = async () => { if (await confirmBox("删除预留 IP", "删除后这个 IP 无法找回。确定？", true)) opp(b, { op: "delete_reserved", public_ip_id: b.dataset.delres }); }));
}

// ---------- 9. IP 质量 ----------
function qualityHtml(q) {
  const lv = q.risk == null ? "" : q.risk <= 33 ? "done" : q.risk <= 66 ? "running" : "failed";
  return `<div class="kv"><span>IP</span><span class="mono">${esc(q.ip)}</span>
    <span>风险分</span><span>${q.risk == null ? "查询失败" : `<span class="badge ${lv}">${q.risk}</span> <span class="muted">0~100，越低越干净</span>`}</span>
    <span>类型</span><span>${esc(q.type || "-")}${q.proxy ? " · 被标记为代理/VPN" : ""}</span>
    <span>归属</span><span>${esc(q.country || "-")} ${esc(q.country_code || "")}</span>
    <span>ISP / ASN</span><span>${esc(q.isp || "-")} ${esc(q.asn || "")}</span>
    <span>机房 IP</span><span>${q.hosting == null ? "-" : q.hosting ? "是" : "否"}</span></div>
    ${q.error ? `<p class="muted">${esc(q.error)}</p>` : ""}<p class="muted">数据源：${esc(q.source || "")}。只发送这个公网 IP，不发送任何凭证。流媒体解锁需在实例内检测，面板不提供。</p>`;
}
async function qualityDialog(inst) {
  if (!inst.public_ip) return toast("实例没有公网 IP", true);
  let q;
  try { toast("检测中…"); q = await api(`/ip-quality?ip=${encodeURIComponent(inst.public_ip)}`); } catch (e) { return toast(e.message, true); }
  modal(`IP 质量 · ${inst.name}`, qualityHtml(q), null, "关闭");
}
const QUALITY_FIELDS = `<details><summary class="muted">IP 质量要求（可选：不合格自动重换）</summary>
  <div class="row2"><div><label>风险分上限（0~100，留空不限）</label><input name="quality_max_risk" type="number" min="0" max="100" placeholder="如 50"></div>
  <div><label>归属国家（留空不限）</label><input name="quality_country" placeholder="如 US 或 US,JP"></div></div>
  <p class="muted">每换一次都会查询风险分（proxycheck.io，无 Key 每天 100 次）和归属地（ip-api.com）。</p></details>`;

// ---------- 15. 免费 AMD 下行 500Mbps ----------
async function net500Dialog(acc, inst, base) {
  let st;
  try { st = await api(`/accounts/${acc.id}/oci/500m?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  if (st.enabled) {
    const r = await modal("关闭下行 500Mbps", `<p>当前已开启，入口 IP：<code>${esc(st.public_ip || "-")}</code></p><p class="muted">关闭后删除网络负载均衡器，实例恢复用原公网 IP 入站。</p>`,
      () => post(`/accounts/${acc.id}/oci/500m`, { ...base, enable: false }), "关闭", true);
    if (r) toast(`已创建任务 #${r.task_id}`);
    return;
  }
  const r = await modal("开启下行 500Mbps", `<p>给免费 AMD（E2.1.Micro）开启约 500Mbps 下行：</p>
    <ul class="guard"><li>新建一个网络负载均衡器（Always Free 含 1 个）转发全部 TCP/UDP 端口到本机，<b>入口 IP 变成负载均衡器的公网 IP</b>；</li>
    <li>实例网卡改走 NAT 网关出站（原公网 IP 不再接收入站）；</li><li>账号里已有其他负载均衡器时不会动它，会直接提示。</li></ul>
    <label>健康检查端口（SSH 端口）</label><input name="ssh_port" type="number" value="22" min="1" max="65535">
    <p class="muted">参考 oci-helper 的公开做法。随时可以关闭还原。</p>`, (bg) => post(`/accounts/${acc.id}/oci/500m`, { ...base, ...form(bg), enable: true, confirm: true }), "开启");
  if (r) toast(`已创建任务 #${r.task_id}，完成后会推送新的入口 IP`);
}

// ---------- 14. Azure 磁盘 ----------
async function azDiskDialog(acc, inst) {
  let d;
  try { toast("读取磁盘…"); d = await api(`/accounts/${acc.id}/azure/disks?instance_id=${encodeURIComponent(inst.id)}`); } catch (e) { return toast(e.message, true); }
  const rows = d.disks.map((k) => `<tr><td>${k.role === "os" ? "系统盘" : `数据盘 LUN ${k.lun}`}<div class="muted mono">${esc(k.name)}</div></td><td>${k.size_gb} GB</td><td>${esc(k.sku || "-")}</td><td>${esc(k.tier || "-")}</td>
    <td><button class="btn sm" data-disk="${esc(k.id)}">调整</button></td></tr>`).join("");
  modal(`磁盘 · ${inst.name}`, `<table><tr><th>磁盘</th><th>大小</th><th>类型</th><th>性能层</th><th></th></tr>${rows}</table><p class="muted">${esc(d.hint)}</p>`, null, "关闭");
  lastModal().querySelectorAll("[data-disk]").forEach((b) => (b.onclick = async () => {
    const k = d.disks.find((x) => x.id === b.dataset.disk);
    const r = await modal(`调整 ${k.name}`, `<div class="row2"><div><label>大小 GB（只能变大）</label><input name="size_gb" type="number" min="${k.size_gb}" placeholder="${k.size_gb}"></div>
      <div><label>类型</label><select name="sku">${d.skus.map((s) => `<option ${s === k.sku ? "selected" : ""}>${s}</option>`).join("")}</select></div></div>
      <label>Premium 性能层（只对 Premium SSD 有效）</label><select name="tier"><option value="">不变</option>${d.tiers.map((t) => `<option ${t === k.tier ? "selected" : ""}>${t}</option>`).join("")}</select>`,
      (bg) => { const f = form(bg); if (f.sku === k.sku) delete f.sku; return post(`/accounts/${acc.id}/azure/disks`, { instance_id: inst.id, disk_id: k.id, ...f }); }, "提交");
    if (r) { toast(r.hint || "已调整"); lastModal() && lastModal().remove(); azDiskDialog(acc, inst); }
  }));
}

// ---------- 19. Lightsail 防火墙 ----------
async function lsPortsDialog(acc, inst) {
  const load = () => api(`/accounts/${acc.id}/lightsail/ports?instance=${encodeURIComponent(inst.id)}&${rq(acc)}`);
  let ports;
  try { ports = await load(); } catch (e) { return toast(e.message, true); }
  modal(`防火墙 · ${inst.name}`, `<table><tr><th>协议</th><th>端口</th><th>来源</th><th></th></tr>${ports.map((p, i) => `<tr><td>${esc(p.protocol)}</td><td>${p.from === p.to ? p.from : `${p.from}-${p.to}`}</td>
    <td class="mono">${esc([...p.cidrs, ...p.ipv6_cidrs].join(", ") || "-")}</td><td><button class="btn sm danger" data-close="${i}">关闭</button></td></tr>`).join("") || `<tr><td colspan=4 class="muted">没有开放的端口</td></tr>`}</table>
    <div class="row2"><div><label>协议</label><select name="protocol"><option>tcp</option><option>udp</option><option>icmp</option></select></div>
    <div><label>端口（单个或范围，如 8443 或 8000-8100）</label><input name="port" placeholder="例如 8443"></div></div>
    <label>来源 CIDR（逗号分隔）</label><input name="cidrs" value="0.0.0.0/0">
    <div class="bar"><button class="btn primary" id="lsOpen">开放端口</button></div>`, null, "关闭");
  const bg = lastModal();
  bg.querySelectorAll("[data-close]").forEach((b) => (b.onclick = async () => {
    const p = ports[+b.dataset.close];
    if (!(await confirmBox("关闭端口", `关闭 ${esc(p.protocol)} ${p.from}-${p.to}？`, true))) return;
    if (await act(b, () => post(`/accounts/${acc.id}/lightsail/ports`, { op: "close", instance: inst.id, region: regionOf(acc), protocol: p.protocol, from_port: p.from, to_port: p.to }), "已关闭")) { bg.remove(); lsPortsDialog(acc, inst); }
  }));
  bg.querySelector("#lsOpen").onclick = async (e) => {
    const f = form(bg); const m = /^(\d+)(?:\s*-\s*(\d+))?$/.exec(f.port || "");
    if (f.protocol !== "icmp" && !m) return toast("请填写端口，如 8443 或 8000-8100", true);
    const body = { op: "open", instance: inst.id, region: regionOf(acc), protocol: f.protocol, from_port: m ? +m[1] : -1, to_port: m ? +(m[2] || m[1]) : -1, cidrs: f.cidrs };
    if (f.protocol === "icmp") { body.from_port = 0; body.to_port = 0; }
    try { await post(`/accounts/${acc.id}/lightsail/ports`, body); }
    catch (err) {
      if (!/0\.0\.0\.0|整个互联网/.test(err.message)) return toast(err.message, true);
      if (!(await confirmBox("对整个互联网开放", `来源 0.0.0.0/0：任何人都能访问 ${esc(f.port || "ICMP")}。确定？`, true))) return;
      if (!(await act(e.target, () => post(`/accounts/${acc.id}/lightsail/ports`, { ...body, confirm_public: true })))) return;
    }
    toast("已开放"); bg.remove(); lsPortsDialog(acc, inst);
  };
}

// ---------- 实例操作入口 ----------
const V16_OPS = {
  reinstall: (acc, inst, base) => reinstallDialog(acc, inst, base),
  ips: (acc, inst, base, kind, btn, reload) => ociIpsDialog(acc, inst, base, reload),
  quality: (acc, inst) => qualityDialog(inst),
  net500: (acc, inst, base) => net500Dialog(acc, inst, base),
  disks: (acc, inst) => azDiskDialog(acc, inst),
  lsports: (acc, inst) => lsPortsDialog(acc, inst),
};
function v16Ops(acc, kind, ops) {
  const i = ops.findIndex(([o]) => o === "terminate");
  const add = [];
  if (acc.provider === "oci") add.push(["ips", "附加 IP"], ["net500", "500M 下行"]);
  if (acc.provider === "azure") add.push(["disks", "磁盘"]);
  if (kind === "lightsail") add.push(["lsports", "防火墙"]);
  add.push(["quality", "IP 质量"]);
  if (kind !== "lightsail") add.push(["reinstall", "重装系统"]);
  ops.splice(i < 0 ? ops.length : i, 0, ...add);
  return ops;
}

// ---------- 6. OCI 存储（块存储卷 + 引导卷） ----------
async function tabOciStorage(acc, box) {
  const reload = () => tabOciStorage(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">刷新</button><button class="btn primary" id="newVol">新建块存储卷</button><span class="grow"></span><span class="muted" id="used"></span></div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
  $("#rf", box).onclick = reload;
  let d, insts = [];
  try { [d, insts] = await Promise.all([api(`/accounts/${acc.id}/oci/volumes?${rq(acc)}`), api(`/accounts/${acc.id}/instances?kind=vm&${rq(acc)}`).catch(() => [])]); }
  catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const iname = (id) => (insts.find((i) => i.id === id) || {}).name || (id ? id.slice(-10) : "-");
  $("#used", box).textContent = `已用 ${d.used_gb} / ${d.free_gb} GB（Always Free 合计含引导卷）`;
  $("#lb", box).innerHTML = `<div class="card"><h3>块存储卷（数据盘）</h3><table><tr><th>名称</th><th>大小</th><th>性能</th><th>挂载到</th><th>状态</th><th></th></tr>
    ${d.volumes.map((v) => `<tr data-v="${esc(v.id)}"><td>${esc(v.name)}</td><td>${v.size_gb} GB</td><td>${v.vpus_per_gb} VPU/GB</td><td>${v.attached_to ? esc(iname(v.attached_to)) + (v.device ? ` <span class="muted mono">${esc(v.device)}</span>` : "") : "未挂载"}</td><td>${esc(v.state)}</td>
    <td><button class="btn sm" data-upd="${esc(v.id)}">调整</button> ${v.attached_to ? `<button class="btn sm" data-det="${esc(v.attachment_id)}">卸载</button>` : `<button class="btn sm" data-att="${esc(v.id)}">挂载</button> <button class="btn sm danger" data-del="${esc(v.id)}">删除</button>`}</td></tr>`).join("") || `<tr><td colspan=6 class="muted">暂无块存储卷</td></tr>`}</table>
    <p class="muted">挂载方式为半虚拟化，系统内用 lsblk 查看新盘，首次使用需分区格式化。卸载前请先在系统内 umount。</p></div>
    <div class="card"><h3>引导卷（系统盘）</h3><table><tr><th>名称</th><th>大小</th><th>性能</th><th>状态</th></tr>${d.boot_volumes.map((b) => `<tr><td>${esc(b.name)}</td><td>${b.size_gb} GB</td><td>${b.vpus_per_gb} VPU/GB</td><td>${esc(b.state)}</td></tr>`).join("") || `<tr><td colspan=4 class="muted">暂无</td></tr>`}</table>
    <p class="muted">引导卷扩容在实例操作「引导卷」里，可勾选扩容后自动扩分区。</p></div>`;
  const op = (b, body, msg) => act(b, () => post(`/accounts/${acc.id}/oci/volumes`, { region: regionOf(acc) || undefined, ...body }), msg).then((r) => { if (r) { if (r.hint) toast(r.hint); reload(); } return r; });
  const instOpts = insts.map((i) => `<option value="${esc(i.id)}">${esc(i.name)}</option>`).join("");
  $("#newVol", box).onclick = async () => {
    const r = await modal("新建块存储卷", `<label>名称</label><input name="name" placeholder="data-1">
      <div class="row2"><div><label>大小 GB（最小 50）</label><input name="size_gb" type="number" min="50" value="50"></div>
      <div><label>性能 VPU/GB</label><select name="vpus_per_gb">${[0, 10, 20, 30, 60, 90, 120].map((v) => `<option ${v === 10 ? "selected" : ""} value="${v}">${v}${v === 0 ? "（低成本）" : v === 10 ? "（均衡，免费）" : ""}</option>`).join("")}</select></div></div>
      <label>创建后挂载到（可选，自动选同可用域）</label><select name="instance_id"><option value="">不挂载</option>${instOpts}</select>
      <p class="muted">${esc(`当前已用 ${d.used_gb} GB，Always Free 合计 ${d.free_gb} GB`)}</p>`, (bg) => post(`/accounts/${acc.id}/oci/volumes`, { op: "create", region: regionOf(acc) || undefined, ...form(bg) }), "创建");
    if (r) { toast(r.attach && r.attach.hint ? r.attach.hint : "已创建"); reload(); }
  };
  box.querySelectorAll("[data-att]").forEach((b) => (b.onclick = async () => {
    const r = await modal("挂载块存储卷", `<label>挂载到实例（需同一可用域）</label><select name="instance_id">${instOpts}</select>`, (bg) => post(`/accounts/${acc.id}/oci/volumes`, { op: "attach", region: regionOf(acc) || undefined, volume_id: b.dataset.att, ...form(bg) }), "挂载");
    if (r) { toast(r.hint || "已挂载"); reload(); }
  }));
  box.querySelectorAll("[data-det]").forEach((b) => (b.onclick = async () => { if (await confirmBox("卸载块存储卷", "请先在系统内 umount 并移除 /etc/fstab 条目，否则可能丢数据或开机失败。确定卸载？", true)) op(b, { op: "detach", attachment_id: b.dataset.det }); }));
  box.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (await confirmBox("删除块存储卷", "删除后数据无法恢复。确定？", true)) op(b, { op: "delete", volume_id: b.dataset.del, confirm: true }, "已删除"); }));
  box.querySelectorAll("[data-upd]").forEach((b) => (b.onclick = async () => {
    const v = d.volumes.find((x) => x.id === b.dataset.upd);
    const r = await modal(`调整 ${v.name}`, `<div class="row2"><div><label>扩容到 GB（只能变大）</label><input name="size_gb" type="number" min="${v.size_gb}" placeholder="${v.size_gb}"></div>
      <div><label>性能 VPU/GB</label><select name="vpus_per_gb">${[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120].map((x) => `<option ${x === v.vpus_per_gb ? "selected" : ""}>${x}</option>`).join("")}</select></div></div>
      ${v.attached_to ? `<label><input type="checkbox" name="grow" style="width:auto" checked> 扩容后通过 Run Command 让系统重新识别磁盘大小（分区需自行扩展）</label>` : ""}`,
      (bg) => post(`/accounts/${acc.id}/oci/volumes`, { op: "update", region: regionOf(acc) || undefined, volume_id: v.id, instance_id: v.attached_to, ...form(bg) }), "提交");
    if (r) { toast(r.grow ? `已提交；系统内：${r.grow.status === "ok" ? "已重新识别" : r.grow.message}` : "已提交"); reload(); }
  }));
}

// ---------- 18. OCI 对象存储 ----------
async function tabOciObjects(acc, box, bucket, prefix = "") {
  const reload = () => tabOciObjects(acc, box, bucket, prefix);
  if (!bucket) {
    box.innerHTML = `<div class="bar">${await regionSelect(acc, () => tabOciObjects(acc, box))}<button class="btn" id="rf">刷新</button><button class="btn primary" id="nb">新建 Bucket</button><span class="grow"></span><span class="muted" id="ns"></span></div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
    $("#rf", box).onclick = reload;
    let d;
    try { d = await api(`/accounts/${acc.id}/oci/buckets?${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
    $("#ns", box).textContent = `命名空间 ${d.namespace} · Always Free 共 ${d.free_gb} GB`;
    $("#lb", box).innerHTML = `<div class="card"><table><tr><th>Bucket</th><th>创建时间</th><th></th></tr>${d.buckets.map((b) => `<tr><td><a href="javascript:void 0" data-open="${esc(b.name)}">📁 ${esc(b.name)}</a></td><td class="mono">${esc(b.created)}</td>
      <td><button class="btn sm" data-open="${esc(b.name)}">打开</button> <button class="btn sm danger" data-delb="${esc(b.name)}">删除</button></td></tr>`).join("") || `<tr><td colspan=3 class="muted">暂无 Bucket</td></tr>`}</table></div>`;
    $("#nb", box).onclick = async () => {
      const r = await modal("新建 Bucket", `<label>名称（字母、数字、- _ .）</label><input name="name" placeholder="backup">
        <label><input type="checkbox" name="public" style="width:auto"> 公开读取（任何人知道链接都能下载对象，慎用）</label>`, (bg) => post(`/accounts/${acc.id}/oci/buckets`, { op: "create", region: regionOf(acc) || undefined, ...form(bg) }), "创建");
      if (r) { toast("已创建"); reload(); }
    };
    box.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => tabOciObjects(acc, box, b.dataset.open)));
    box.querySelectorAll("[data-delb]").forEach((b) => (b.onclick = async () => {
      if (await confirmBox("删除 Bucket", `删除「${esc(b.dataset.delb)}」？Bucket 需为空。`, true) && await act(b, () => post(`/accounts/${acc.id}/oci/buckets`, { op: "delete", region: regionOf(acc) || undefined, name: b.dataset.delb, confirm: true }), "已删除")) reload();
    }));
    return;
  }
  box.innerHTML = `<div class="bar"><button class="btn" id="back">← Bucket 列表</button><b class="mono">${esc(bucket)}/${esc(prefix)}</b><span class="grow"></span>
    <label class="btn primary" style="margin:0">上传文件<input type="file" id="up" multiple style="display:none"></label><button class="btn" id="rf">刷新</button></div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
  $("#back", box).onclick = () => (prefix ? tabOciObjects(acc, box, bucket, prefix.replace(/[^/]+\/$/, "")) : tabOciObjects(acc, box));
  $("#rf", box).onclick = reload;
  $("#up", box).onchange = async (e) => {
    for (const f of e.target.files) {
      if (f.size > 100 * 1024 * 1024) { toast(`${f.name} 超过 100MB，请用 OCI 控制台上传`, true); continue; }
      toast(`上传 ${f.name}…`);
      const r = await fetch(`/api/accounts/${acc.id}/oci/objects?bucket=${encodeURIComponent(bucket)}&name=${encodeURIComponent(prefix + f.name)}&${rq(acc)}`, { method: "PUT", body: f, credentials: "same-origin" });
      if (!r.ok) { const j = await r.json().catch(() => ({})); toast(`${f.name}：${j.detail || r.statusText}`, true); } else toast(`${f.name} 已上传`);
    }
    reload();
  };
  let d;
  try { d = await api(`/accounts/${acc.id}/oci/objects?bucket=${encodeURIComponent(bucket)}&prefix=${encodeURIComponent(prefix)}&${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#lb", box).innerHTML = `<div class="card"><table><tr><th>名称</th><th>大小</th><th>上传时间</th><th></th></tr>
    ${d.prefixes.map((p) => `<tr><td><a href="javascript:void 0" data-dir="${esc(p)}">📁 ${esc(p.slice(prefix.length))}</a></td><td>-</td><td>-</td><td></td></tr>`).join("")}
    ${d.objects.filter((o) => o.name !== prefix).map((o) => `<tr><td class="mono">${esc(o.name.slice(prefix.length))}</td><td>${fmtBytes(o.size)}</td><td class="mono">${esc(o.created)}</td>
      <td><button class="btn sm" data-dl="${esc(o.name)}">下载链接</button> <button class="btn sm danger" data-delo="${esc(o.name)}">删除</button></td></tr>`).join("")}
    ${!d.prefixes.length && !d.objects.length ? `<tr><td colspan=4 class="muted">空</td></tr>` : ""}</table>${d.next ? `<p class="muted">只显示前 200 个对象</p>` : ""}</div>`;
  box.querySelectorAll("[data-dir]").forEach((b) => (b.onclick = () => tabOciObjects(acc, box, bucket, b.dataset.dir)));
  box.querySelectorAll("[data-dl]").forEach((b) => (b.onclick = async () => {
    const r = await act(b, () => post(`/accounts/${acc.id}/oci/objects`, { op: "url", region: regionOf(acc) || undefined, bucket, name: b.dataset.dl, minutes: 60 }));
    if (r) modal("下载链接", `<p class="muted">预认证只读链接，${esc(r.expires)} 前有效，任何拿到链接的人都能下载。</p><input readonly value="${esc(r.url)}" onclick="this.select()"><div class="bar"><a class="btn primary" href="${esc(r.url)}" target="_blank" rel="noopener">打开</a></div>`, null, "关闭");
  }));
  box.querySelectorAll("[data-delo]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("删除对象", `删除「${esc(b.dataset.delo)}」？`, true) && await act(b, () => post(`/accounts/${acc.id}/oci/objects`, { op: "delete", region: regionOf(acc) || undefined, bucket, name: b.dataset.delo }), "已删除")) reload();
  }));
}

// ---------- OCI 流量：本区域实例本月出站 / 入站（OCI Monitoring，免费） ----------
async function tabOciTraffic(acc, box) {
  const reload = () => tabOciTraffic(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">刷新</button><span class="grow"></span><span class="muted" id="pd"></span></div><div id="lb"><div class="card"><span class="spin"></span> 正在读取各实例流量…</div></div>`;
  $("#rf", box).onclick = reload;
  let d, gs = [];
  try { gs = (await api("/traffic-guards")).filter((g) => g.account_id === acc.id); } catch (_) { /* ignore */ }
  try { d = await api(`/accounts/${acc.id}/oci/traffic-summary?${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#pd", box).textContent = `统计 ${d.period}（UTC）`;
  const pct = d.free_out_gb ? Math.min(100, (d.out_gb / d.free_out_gb) * 100) : 0;
  const gb = (v) => (v == null ? "-" : v >= 1024 ? `${(v / 1024).toFixed(2)} TB` : `${(+v).toFixed(2)} GB`);
  $("#lb", box).innerHTML = `<div class="card"><p>本区域本月出站 <b>${gb(d.out_gb)}</b> / 免费 ${gb(d.free_out_gb)}（${pct.toFixed(pct < 1 ? 2 : 1)}%），入站 ${gb(d.in_gb)}（入站不计费）。</p>
      <div class="meter"><i style="width:${pct}%" class="${pct >= 100 ? "bad" : pct >= 80 ? "warn" : ""}"></i></div>
      <p class="muted">10TB 免费出站按整个租户所有区域合计；数据来自 OCI Monitoring，有 5~15 分钟延迟。需要超量提醒或自动停机，在下表给实例设置「流量守护」。</p></div>
    <div class="card"><table><tr><th>实例</th><th>状态</th><th>公网 IP</th><th>本月出站</th><th>本月入站</th><th>流量守护</th><th></th></tr>
    ${d.items.map((r, i) => `<tr><td>${esc(r.name)}<div class="muted mono" style="font-size:11px">${esc(r.shape || "")}</div></td><td>${esc(r.state || "")}</td><td class="mono">${esc(r.public_ip || "-")}</td>
      <td>${r.error ? `<span class="muted" title="${esc(r.error)}">读取失败</span>` : `<b>${gb(r.out_gb)}</b>`}</td><td>${r.error ? "-" : gb(r.in_gb)}</td>
      <td>${guardCell(gs.find((g) => g.instance_id === r.id))}</td>
      <td>${(() => { const g = gs.find((x) => x.instance_id === r.id); return g ? `<button class="btn sm" data-tg="${i}">编辑</button> <button class="btn sm" data-tgchk="${g.id}">立即检查</button> <button class="btn sm danger" data-tgdel="${g.id}">删除</button>` : `<button class="btn sm" data-tg="${i}">设置守护</button>`; })()}</td></tr>`).join("") || `<tr><td colspan=7 class="muted">本区域没有实例</td></tr>`}</table></div>`;
  box.querySelectorAll("[data-tg]").forEach((b) => (b.onclick = () => trafficDialog(acc, d.items[+b.dataset.tg], "vm", reload)));
  box.querySelectorAll("[data-tgchk]").forEach((b) => (b.onclick = () => act(b, () => post(`/traffic-guards/${b.dataset.tgchk}/check`), "已检查").then(reload)));
  box.querySelectorAll("[data-tgdel]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("删除规则", "删除这台实例的流量守护？", true)) act(b, () => api(`/traffic-guards/${b.dataset.tgdel}`, { method: "DELETE" }), "已删除").then(reload);
  }));
}
function guardCell(g) {
  if (!g) return `<span class="muted">未设置</span>`;
  const st = `<span class="badge ${GST[g.status] || ""}">${esc(g.enabled ? g.status_text || "正常" : "已关闭")}</span>`;
  return `${st} <span class="muted">${g.last_gb ?? "-"} / ${g.limit_gb} GB${g.action === "stop" ? " · 超限停机" : " · 只推送"}</span>`;
}

// ---------- Azure Foundry（AI Services）：配额、AI 资源与模型部署、Endpoint / Key ----------
const FOUNDRY_REGION = {};
async function tabAzFoundry(acc, box) {
  const region = FOUNDRY_REGION[acc.id] || "swedencentral";
  const reload = () => tabAzFoundry(acc, box);
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let d;
  try { d = await api(`/accounts/${acc.id}/azure/foundry?region=${encodeURIComponent(region)}`); }
  catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}<p class="muted">需要服务主体对订阅有 Contributor 权限，并已注册 Microsoft.CognitiveServices 资源提供程序。</p></div>`; return; }
  const res = d.resources || [], models = d.models || [];
  const regs = (d.regions || [region]).map((r) => `<option ${r === region ? "selected" : ""}>${esc(r)}</option>`).join("");
  const resHtml = res.length ? res.map((r) => `<div class="card"><h3>${esc(r.name)} <span class="badge">${esc(r.kind)}</span> <span class="muted">${esc(r.region)} · ${esc(r.resource_group)} · ${esc(r.state || "")}</span></h3>
      <p class="mono" style="word-break:break-all">${esc(r.endpoint || "-")}</p>
      <div class="acts" style="justify-content:flex-start;flex-wrap:wrap"><button class="btn sm" data-key="${esc(r.id)}">查看 Endpoint / Key</button>
        <button class="btn sm primary" data-dep="${esc(r.id)}" data-reg="${esc(r.region)}">＋ 部署模型</button>
        <button class="btn sm danger" data-delr="${esc(r.id)}" data-n="${esc(r.name)}">删除资源</button></div>
      ${r.deployments.length ? `<table><tr><th>部署名</th><th>模型</th><th>类型</th><th>容量</th><th>状态</th><th></th></tr>${r.deployments.map((x) => `<tr><td class="mono">${esc(x.name)}</td>
        <td>${esc(x.model || "-")} <span class="muted">${esc(x.version || "")}</span></td><td>${esc(x.sku || "-")}</td><td>${x.capacity != null ? esc(x.capacity) + "K TPM" : "-"}</td><td>${esc(x.state || "-")}</td>
        <td><button class="btn sm danger" data-deld="${esc(x.name)}" data-rid="${esc(r.id)}">删除</button></td></tr>`).join("")}</table>` : `<p class="muted">还没有部署模型</p>`}</div>`).join("")
    : `<div class="card"><p class="muted">订阅里还没有 AI Services / Azure OpenAI 资源。</p></div>`;
  const q = d.quotas || [];
  box.innerHTML = `<div class="card"><h3>Foundry（Azure AI）</h3>
      <p class="muted">在订阅里创建 AI Services 资源并部署 GPT 等模型，得到 Endpoint 和 Key，可按 OpenAI 接口调用。<b>按调用量计费</b>，会消耗订阅额度；部署本身不收费。</p>
      <div class="acts" style="justify-content:flex-start;flex-wrap:wrap"><label style="margin:0">区域</label><select id="fdReg" style="width:auto">${regs}</select>
        <button class="btn primary" id="fdNew">＋ 新建资源并部署模型</button></div></div>
    ${resHtml}
    <div class="card"><h3>模型配额 · ${esc(region)}</h3>${q.length ? `<table><tr><th>配额项</th><th>已用 / 上限</th></tr>${q.map((x) => `<tr><td>${esc(x.name)}</td><td>${esc(x.used)} / ${esc(x.limit)}</td></tr>`).join("")}</table>`
      : `<p class="muted">该区域没有可用配额（学生 / 免费订阅很多区域为 0）。</p>`}</div>`;
  $("#fdReg", box).onchange = (e) => { FOUNDRY_REGION[acc.id] = e.target.value; reload(); };
  const modelOpts = (list) => list.length ? list.map((m) => `<option value="${esc(m.name)}|${esc(m.version)}" data-skus="${esc(m.skus.join(","))}">${esc(m.name)} ${esc(m.version)}${m.default ? "（默认）" : ""}</option>`).join("")
    : ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini", "text-embedding-3-small"].map((n) => `<option value="${n}|">${n}</option>`).join("");
  const depForm = async (rid, reg) => {
    let list = models;
    if (reg !== region) { try { list = (await api(`/accounts/${acc.id}/azure/foundry?region=${encodeURIComponent(reg)}&part=models`)).models || []; } catch (_) { list = []; } }
    const newRes = !rid;
    const v = await modal(newRes ? "新建资源并部署模型" : "部署模型", `${newRes ? `<label>资源名称（全局唯一，也是 Endpoint 子域名）</label><input name="name" placeholder="例如 my-ai-01">
        <label>资源组（留空 = 资源名-rg）</label><input name="resource_group" placeholder="可选">
        <p class="muted">区域：${esc(reg)}（在上方下拉切换）</p>` : ""}
      <label>模型</label><select name="model">${modelOpts(list)}</select>
      <div class="row2"><div><label>部署类型</label><select name="sku"><option value="GlobalStandard">Global Standard（全球路由，配额多）</option><option value="Standard">Standard（仅本区域）</option><option value="DataZoneStandard">DataZone Standard</option></select></div>
        <div><label>容量（千 TPM）</label><input name="capacity" type="number" min="1" max="1000" value="10"></div></div>
      <label>部署名（留空 = 模型名）</label><input name="deployment" placeholder="可选，调用时要用">
      <p class="muted">容量受上方配额限制；部署完成后在「查看 Endpoint / Key」里拿到调用地址。</p>`, (bg) => {
      const f = Object.fromEntries([...bg.querySelectorAll("[name]")].map((x) => [x.name, x.value.trim()]));
      if (newRes && !/^[a-zA-Z0-9][a-zA-Z0-9-]{1,62}$/.test(f.name)) { toast("资源名称 2~63 位，只能含字母、数字和 -", true); return false; }
      if (f.deployment && !/^[a-zA-Z0-9][a-zA-Z0-9-]{1,62}$/.test(f.deployment)) { toast("部署名只能含字母、数字和 -", true); return false; }
      return f;
    }, "开始部署");
    if (!v) return;
    const [model, version] = v.model.split("|");
    const body = { op: "deploy", model, version: version || undefined, sku: v.sku, capacity: Number(v.capacity) || 10, deployment: v.deployment || undefined };
    if (rid) body.resource_id = rid; else Object.assign(body, { name: v.name, region: reg, resource_group: v.resource_group || undefined });
    const r = await act(null, () => post(`/accounts/${acc.id}/azure/foundry`, body), (x) => `已创建任务 #${x.task_id}，完成后推送通知`);
    if (r) setTimeout(reload, 1500);
  };
  $("#fdNew", box).onclick = () => depForm(null, region);
  box.querySelectorAll("[data-dep]").forEach((b) => (b.onclick = () => depForm(b.dataset.dep, b.dataset.reg)));
  box.querySelectorAll("[data-key]").forEach((b) => (b.onclick = async () => {
    if (!(await confirmBox("查看密钥", "Key 等同于调用权限，泄露会被盗刷额度。确定显示？", false))) return;
    const k = await act(b, () => post(`/accounts/${acc.id}/azure/foundry`, { op: "keys", resource_id: b.dataset.key, confirm: true }));
    if (!k) return;
    modal("Endpoint / Key", `<label>Endpoint</label><input readonly class="mono" value="${esc(k.endpoint || "")}" onclick="this.select()">
      <label>Key 1</label><input readonly class="mono" id="fdK1" value="${esc(k.key1 || "")}" onclick="this.select()"> <button class="btn sm" id="fdCopy">复制 Key 1</button>
      <label>OpenAI 兼容 base_url</label><input readonly class="mono" value="${esc(k.openai_base_url || "")}" onclick="this.select()">
      <p class="muted">OpenAI SDK：base_url 填上面地址，api_key 填 Key，model 填部署名。</p>`, null, "关闭");
    const c = document.getElementById("fdCopy");
    if (c) c.onclick = async () => { const t = document.getElementById("fdK1"); try { await navigator.clipboard.writeText(t.value); toast("已复制"); } catch (_) { t.select(); document.execCommand("copy"); toast("已复制"); } };
  }));
  box.querySelectorAll("[data-deld]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("删除部署", `删除部署「${esc(b.dataset.deld)}」？用这个部署名的调用会立刻失败。`, true)
      && await act(b, () => post(`/accounts/${acc.id}/azure/foundry`, { op: "delete_deployment", resource_id: b.dataset.rid, deployment: b.dataset.deld, confirm: true }), "已删除部署")) reload();
  }));
  box.querySelectorAll("[data-delr]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("删除 AI 资源", `删除「${esc(b.dataset.n)}」及其全部部署？Key 立刻失效；资源会软删除保留 48 小时，期间不能用同名重建。`, true)
      && await act(b, () => post(`/accounts/${acc.id}/azure/foundry`, { op: "delete_resource", resource_id: b.dataset.delr, confirm: true }), (x) => x.hint || "已删除")) reload();
  }));
}

// ---------- 7. OCI 区域订阅 ----------
async function tabOciRegionSub(acc, box) {
  const reload = () => tabOciRegionSub(acc, box);
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let d;
  try { d = await api(`/accounts/${acc.id}/oci/region-subscriptions`); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const subd = d.regions.filter((r) => r.subscribed);
  box.innerHTML = `<div class="card"><h3>已订阅 ${subd.length} 个区域 · 主区域 ${esc(d.home || "-")}</h3>
    <p class="muted">${esc(d.limit_hint)}。订阅<b>不可撤销</b>，订阅后可在顶部区域下拉里切换。</p>
    <table><tr><th>区域</th><th>Key</th><th>状态</th><th></th></tr>${d.regions.map((r) => `<tr><td>${esc(r.name)}${r.home ? ` <span class="badge done">主区域</span>` : ""}</td><td class="mono">${esc(r.key)}</td>
      <td>${r.subscribed ? esc(r.status || "已订阅") : `<span class="muted">未订阅</span>`}</td><td>${r.subscribed ? "" : `<button class="btn sm" data-sub="${esc(r.key)}" data-n="${esc(r.name)}">订阅</button>`}</td></tr>`).join("")}</table></div>`;
  box.querySelectorAll("[data-sub]").forEach((b) => (b.onclick = async () => {
    if (!(await confirmBox("订阅区域", `订阅 ${esc(b.dataset.n)}（${esc(b.dataset.sub)}）？<br>⚠️ 订阅后<b>无法取消</b>，免费账号的额外区域名额通常只有 1 个；Always Free 资源仍只在主区域。`, true))) return;
    if (await act(b, () => post(`/accounts/${acc.id}/oci/region-subscriptions`, { region_key: b.dataset.sub, confirm: true }), (r) => `已提交订阅：${r.region}（${r.status}），几分钟后生效`)) reload();
  }));
}

// ---------- 19. Lightsail 静态 IP（Lightsail 标签页下方） ----------
async function tabLightsailV16(acc, box) {
  await tabInstances(acc, box, "lightsail");
  const card = document.createElement("div");
  card.className = "card"; card.id = "lsips";
  card.innerHTML = `<h3>静态 IP</h3><span class="spin"></span>`;
  box.appendChild(card);
  const reload = () => { card.remove(); tabLightsailV16(acc, box); };
  let ips, insts = [];
  try { [ips, insts] = await Promise.all([api(`/accounts/${acc.id}/lightsail/static-ips?${rq(acc)}`), api(`/accounts/${acc.id}/instances?kind=lightsail&${rq(acc)}`).catch(() => [])]); }
  catch (e) { card.innerHTML = `<h3>静态 IP</h3>❌ ${esc(e.message)}`; return; }
  const opts = insts.map((i) => `<option>${esc(i.name)}</option>`).join("");
  card.innerHTML = `<h3>静态 IP <button class="btn sm" id="lsAlloc">+ 分配</button></h3><table><tr><th>名称</th><th>IP</th><th>绑定到</th><th></th></tr>
    ${ips.map((s) => `<tr><td>${esc(s.name)}</td><td class="mono">${esc(s.ip)}</td><td>${s.attached ? esc(s.attached_to) : `<span class="badge running">未绑定 · 计费中</span>`}</td>
      <td>${s.attached ? `<button class="btn sm" data-lsdet="${esc(s.name)}">解绑</button>` : `<button class="btn sm" data-lsatt="${esc(s.name)}">绑定</button> <button class="btn sm danger" data-lsrel="${esc(s.name)}">释放</button>`}</td></tr>`).join("") || `<tr><td colspan=4 class="muted">暂无静态 IP</td></tr>`}</table>
    <p class="muted">绑定在实例上的静态 IP 免费；未绑定的按小时计费，不用请释放。</p>`;
  const op = (b, body, msg) => act(b, () => post(`/accounts/${acc.id}/lightsail/static-ips`, { region: regionOf(acc), ...body }), msg).then((r) => { if (r) { if (r.hint) toast(r.hint); reload(); } });
  card.querySelector("#lsAlloc").onclick = async () => {
    const r = await modal("分配静态 IP", `<label>名称</label><input name="name" placeholder="ip-1"><label>立即绑定到</label><select name="instance"><option value="">不绑定（会计费）</option>${opts}</select>`,
      (bg) => post(`/accounts/${acc.id}/lightsail/static-ips`, { op: "allocate", region: regionOf(acc), ...form(bg) }), "分配");
    if (r) { toast(`已分配 ${r.ip}`); reload(); }
  };
  card.querySelectorAll("[data-lsatt]").forEach((b) => (b.onclick = async () => {
    const r = await modal("绑定静态 IP", `<label>实例</label><select name="instance">${opts}</select><p class="muted">实例原来的公网 IP 会被替换。</p>`,
      (bg) => post(`/accounts/${acc.id}/lightsail/static-ips`, { op: "attach", region: regionOf(acc), name: b.dataset.lsatt, ...form(bg) }), "绑定");
    if (r) { toast("已绑定"); reload(); }
  }));
  card.querySelectorAll("[data-lsdet]").forEach((b) => (b.onclick = async () => { if (await confirmBox("解绑静态 IP", "解绑后实例会换成新的动态 IP，静态 IP 开始计费。确定？", true)) op(b, { op: "detach", name: b.dataset.lsdet }); }));
  card.querySelectorAll("[data-lsrel]").forEach((b) => (b.onclick = async () => { if (await confirmBox("释放静态 IP", "释放后这个 IP 无法找回。确定？", true)) op(b, { op: "release", name: b.dataset.lsrel }, "已释放"); }));
}

// ---------- 11. 账号类型 / 停用 ----------
async function accountTypeDialog(a, refresh) {
  let r;
  try { toast("查询账号类型…"); r = await api(`/accounts/${a.id}/account-type${refresh ? "?refresh=1" : ""}`); } catch (e) { return toast(e.message, true); }
  const ok = await modal(`账号类型 · ${a.name}`, `<div class="kv"><span>类型</span><span><b>${esc(r.label || "-")}</b></span>
    ${r.plan_type ? `<span>计划</span><span class="mono">${esc(r.plan_type)}</span>` : ""}${r.account_type ? `<span>账户</span><span>${esc(r.account_type)}</span>` : ""}
    ${r.upgrade_state ? `<span>升级状态</span><span>${esc(r.upgrade_state)}</span>` : ""}${r.time_start ? `<span>开户日期</span><span>${esc(r.time_start)}</span>` : ""}
    ${r.age_days != null ? `<span>开户天数</span><span>${r.age_days} 天</span>` : ""}${r.home_region ? `<span>主区域</span><span>${esc(r.home_region)}</span>` : ""}
    ${r.state ? `<span>订阅状态</span><span>${esc(r.state)}</span>` : ""}</div>${r.error || r.hint ? `<p class="muted">${esc(r.error || r.hint)}</p>` : ""}
    <p class="muted">查询于 ${new Date((r.checked_at || 0) * 1000).toLocaleString()}</p>`, null, "重新查询");
  if (ok) accountTypeDialog(a, true);
}
async function toggleDisable(a) {
  if (a.disabled) {
    if (await act(null, () => post(`/accounts/${a.id}/disable`, { disabled: false }), "已启用")) { await loadAccounts(); route(); }
    return;
  }
  const r = await modal("停用账号", `<p>停用「${esc(a.name)}」（比如被封号）：</p><ul class="guard"><li>不再测活、不监控、不跑流量守护；</li><li>该账号运行中的任务（抢机等）全部停止；</li><li>凭证和云上资源都不动，随时可以重新启用。</li></ul>
    <label>原因（可选）</label><input name="reason" placeholder="如 被封号 / 欠费">`, (bg) => post(`/accounts/${a.id}/disable`, { disabled: true, ...form(bg) }), "停用", true);
  if (r) { toast(`已停用${r.stopped_tasks.length ? `，停止了 ${r.stopped_tasks.length} 个任务` : ""}`); await loadAccounts(); route(); }
}

// ---------- 20. 免费额度体检 ----------
async function pageFreeCheck() {
  loading();
  const list = await api("/oci/free-check");
  const bar = (v, max) => `<span class="${v > max ? "bad" : ""}">${v ?? "-"} / ${max}</span>`;
  view.innerHTML = `<div class="card"><p class="muted">逐个检查 OCI 账号（主区域 / 默认区域）的 A1、E2.1.Micro、块存储用量是否超出 Always Free。只给建议，降配需要你确认后才执行（只降不升，不会删实例）。A1 免费额度：免费号 2 OCPU / 12 GB（2026-06 起），付费号仍为 4 OCPU / 24 GB。</p>
    <table><tr><th>账号</th><th>A1 OCPU</th><th>A1 内存 GB</th><th>Micro 台数</th><th>块存储 GB</th><th>结论</th></tr>
    ${list.map((r) => r.error ? `<tr><td>${esc(r.name)}</td><td colspan=5 class="muted">❌ ${esc(r.error)}</td></tr>` : `<tr><td><a href="#/oci/${r.account_id}">${esc(r.name)}</a></td>
      <td>${bar(r.a1.ocpus, r.a1.limit_ocpus)}</td><td>${bar(r.a1.memory_gb, r.a1.limit_mem)}</td><td>${bar(r.micro.count, r.micro.limit)}</td><td>${bar(r.storage.used_gb, r.storage.limit)}</td>
      <td>${r.ok ? `<span class="badge done">都在免费额度内</span>` : r.issues.map((x) => `<div class="bad">${esc(x)}</div>`).join("")}
      ${r.suggestions.map((s) => `<div class="muted">${esc(s.name)}：${s.ocpus}C/${s.memory_gb}G → ${s.delete ? "额度已用完，建议停用或删除" : `${s.to_ocpus}C/${s.to_memory_gb}G`}
        ${s.delete ? "" : `<button class="btn sm" data-down='${esc(JSON.stringify({ acc: r.account_id, ...s }))}'>降配</button>`}</div>`).join("")}</td></tr>`).join("") || `<tr><td colspan=6 class="muted">没有启用中的 OCI 账号</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-down]").forEach((b) => (b.onclick = async () => {
    const s = JSON.parse(b.dataset.down);
    if (!(await confirmBox("降配", `把「${esc(s.name)}」从 ${s.ocpus}C/${s.memory_gb}G 降到 ${s.to_ocpus}C/${s.to_memory_gb}G？实例可能会重启。`))) return;
    act(b, () => post(`/accounts/${s.acc}/instances/resize`, { instance_id: s.id, name: s.name, ocpus: s.to_ocpus, memory_gb: s.to_memory_gb, confirm_overage: true }), (r) => `已创建任务 #${r.task_id}`);
  }));
}
