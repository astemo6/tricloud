// TriCloud 前端 v1.6.0 · 总览页与到期提醒
import { $, ACCOUNTS, api, esc, PNAME, regionOf, rq, view } from "./core.js";
import { ageText } from "./accounts.js";

// ---------------- 总览 ----------------
export async function pageHome() {
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
    // AWS 首页台数 = EC2 + Lightsail（Lightsail 查询失败不影响 EC2 显示）
    Promise.all([api(`/accounts/${a.id}/instances?${rq(a)}`),
      a.provider === "aws" ? api(`/accounts/${a.id}/instances?kind=lightsail&${rq(a)}`).catch(() => null) : Promise.resolve([])]).then(([l, ls]) => {
      const all = l.concat(ls || []);
      const run = all.filter((i) => i.state === "running").length;
      const extra = a.provider === "aws" ? ` · EC2 ${l.length} · Lightsail ${ls ? ls.length : "查询失败"}` : "";
      const el = document.getElementById("cnt" + a.id); if (el) el.textContent = `${all.length} 台（运行 ${run}）${extra}`;
    }).catch((e) => { const el = document.getElementById("cnt" + a.id); if (el) el.textContent = "查询失败：" + e.message.slice(0, 60); });
  }
}

// ---------- 到期提醒（总览） ----------
export async function loadExpiryAlerts(box) {
  if (!box) return;
  try {
    const al = await api("/expiry-alerts");
    box.innerHTML = al.length ? `<div class="card alert-card"><h3>⏰ 30 天内到期</h3>${al.map((a) => `<div class="al ${a.days_left <= 7 ? "bad" : "warn"}">
      <span class="dot ${a.provider}"></span><a href="#/${a.provider}/${a.account_id}/billing">${esc(a.account_name)}</a> · ${esc(a.name)}
      <span class="grow"></span><b>${a.days_left === 0 ? "今天到期" : `剩 ${a.days_left} 天`}</b><span class="muted">${esc(a.date)}${a.estimated ? "（估算）" : ""}</span></div>`).join("")}</div>` : "";
  } catch (_) { box.innerHTML = ""; }
}
