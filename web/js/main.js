// TriCloud 前端 v1.6.0 · 入口：按顺序加载各页面模块，然后初始化顶栏并渲染当前路由
import { $, api, loadAccounts, post, setSettings } from "./core.js";
import { applyI18n, getLang, setLang } from "./i18n.js";
import { route } from "./router.js";
import "./home.js";
import "./accounts.js";
import "./instances.js";
import "./oci.js";
import "./aws.js";
import "./azure.js";
import "./billing.js";
import { TaskDrawer, updateTaskBadge } from "./tasks.js";
import "./monitors.js";
import "./settings.js";

// data-i18n-title 翻译 title 属性；带 aria-label 的元素（任务抽屉关闭按钮）同步跟上
const syncAria = () => document.querySelectorAll("[data-i18n-title][aria-label]").forEach((el) => el.setAttribute("aria-label", el.title));
const applyAll = () => { applyI18n(document); syncAria(); };

(async function init() {
  applyAll();
  const th = $("#theme"); th.value = TCTheme.get(); th.onchange = () => TCTheme.set(th.value);
  // 手机（≤600px）顶栏配色下拉只显示图标，避免「🖥 跟」被截断
  const thMq = window.matchMedia ? window.matchMedia("(max-width: 600px)") : null;
  const thLabels = () => [...th.options].forEach((o) => {
    if (!o.dataset.full) o.dataset.full = o.textContent;
    o.textContent = thMq && thMq.matches ? o.dataset.full.split(" ")[0] : o.dataset.full;
  });
  thLabels();
  if (thMq) (thMq.addEventListener ? thMq.addEventListener("change", thLabels) : thMq.addListener && thMq.addListener(thLabels));
  // 语言切换：不刷新页面 —— 翻译静态文案 → 重缓存主题选项全文 → 重渲染当前路由
  const lg = $("#lang");
  lg.value = getLang();
  lg.onchange = () => {
    setLang(lg.value);
    applyAll();
    [...th.options].forEach((o) => { delete o.dataset.full; });
    thLabels();
    route();
  };
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
  setSettings(await api("/settings").catch(() => ({})));
  route();
  api("/tasks?limit=20").then(updateTaskBadge).catch(() => {});
})();
