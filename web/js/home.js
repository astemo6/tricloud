// TriCloud 前端 v1.6.0 · 总览页与到期提醒
import { t } from "./i18n.js";
import { $, ACCOUNTS, api, applyOverview, esc, overviewCount, PNAME, regionLabel, regionOf, regionsBrief, regionsDist, view } from "./core.js";
import { ageText } from "./accounts.js";

// ---------------- 总览 ----------------
export async function pageHome() {
  if (!ACCOUNTS.length) {
    view.innerHTML = `<div class="card empty">${t("home.empty")}<br><br><a class="btn primary" href="#/accounts">${t("acc.addBtn")}</a></div>`;
    return;
  }
  view.innerHTML = `<div id="expAlerts"></div><div class="card" id="hh"><div class="bar" style="margin:0"><h3 class="grow" style="margin:0">🩺 ${t("nav.health")}</h3>
    <a class="btn sm" href="#/health">${t("common.details")}</a></div><div id="hhl" class="chips"><span class="spin"></span></div></div><div class="card"><div class="bar" style="margin:0"><span class="grow muted">${t("home.ovNote")}</span>
    <button class="btn sm" id="ovRescan">${t("home.rescan")}</button></div></div><div class="grid">${ACCOUNTS.map((a) => `
    <div class="card"><div class="inst"><div class="hd"><span class="dot ${a.provider}"></span><b>${esc(a.name)}</b>
    <span class="badge">${PNAME[a.provider]}</span></div>
    <div class="kv"><span>${t("core.region.title")}</span><span id="reg${a.id}">${esc(a.provider === "azure" ? "-" : regionLabel(regionOf(a)) || "-")}</span><span>${t("tab.instances")}</span><span id="cnt${a.id}">${a.disabled ? t("home.disabled") : `<span class="spin"></span>`}</span>
    <span class="ov-dist" id="distk${a.id}" hidden>${t("home.dist")}</span><span class="ov-dist" id="dist${a.id}" hidden></span>
    ${a.cloud_created_at ? `<span>${t("home.alive")}</span><span>${ageText(a)}</span>` : ""}</div>
    <a class="btn sm" href="#/${a.provider}/${a.id}">${t("home.enter")}</a></div></div>`).join("")}</div>`;
  loadExpiryAlerts($("#expAlerts"));
  api("/account-health").then((l) => {
    $("#hhl").innerHTML = l.map((h) => `<a class="chip" href="#/health"><span class="dot ${h.provider}"></span>${esc(h.name)}
      ${h.score == null ? `<span class="muted">${t("common.unchecked")}</span>` : `<span class="hs ${h.level}">${h.score}</span>`}</a>`).join("");
  }).catch(() => ($("#hhl").innerHTML = `<span class="muted">${t("home.readFail")}</span>`));
  loadOverview(false);
  $("#ovRescan").onclick = () => loadOverview(true);
}

// 各账号实例数：后端 /overview 统计所有有机器的区域（AWS EC2+Lightsail 全区域、OCI 订阅区域、Azure 整个订阅），带缓存
function loadOverview(refresh) {
  for (const a of ACCOUNTS) {
    if (a.disabled) continue;
    const el = document.getElementById("cnt" + a.id);
    if (refresh && el) el.innerHTML = `<span class="spin"></span>`;
    api(`/accounts/${a.id}/overview${refresh ? "?refresh=true" : ""}`).then((o) => {
      applyOverview(a, o);   // build 25：账号列表 / 打开账号的默认区域同步更新
      const c = document.getElementById("cnt" + a.id), r = document.getElementById("reg" + a.id);
      if (!c) return;
      c.textContent = overviewCount(o);
      const brief = regionsBrief(o.regions);
      r.textContent = brief || (a.provider === "azure" ? "-" : regionLabel(o.default_region || regionOf(a)) || "-");
      r.title = (o.regions || []).map((x) => t("home.regionTip", { label: regionLabel(x.region), n: x.count })).join("\n");
      const multi = (o.regions || []).length > 1;
      document.getElementById("distk" + a.id).hidden = !multi;
      const d = document.getElementById("dist" + a.id);
      d.hidden = !multi;
      d.textContent = multi ? regionsDist(o.regions) : "";
    }).catch((e) => { const c = document.getElementById("cnt" + a.id); if (c) c.textContent = t("home.queryFail", { msg: e.message.slice(0, 60) }); });
  }
}

// ---------- 到期提醒（总览） ----------
export async function loadExpiryAlerts(box) {
  if (!box) return;
  try {
    const al = await api("/expiry-alerts");
    box.innerHTML = al.length ? `<div class="card alert-card"><h3>${t("home.expiryTitle")}</h3>${al.map((a) => `<div class="al ${a.days_left <= 7 ? "bad" : "warn"}">
      <span class="dot ${a.provider}"></span><a href="#/${a.provider}/${a.account_id}/billing">${esc(a.account_name)}</a> · ${esc(a.name)}
      <span class="grow"></span><b>${a.days_left === 0 ? t("common.expiresToday") : t("common.daysLeft", { n: a.days_left })}</b><span class="muted">${esc(a.date)}${a.estimated ? t("home.estimated") : ""}</span></div>`).join("")}</div>` : "";
  } catch (_) { box.innerHTML = ""; }
}
