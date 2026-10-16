// TriCloud 前端 v1.6.0 · AWS：EC2 创建、Lightsail、区域、配额、闲置资源、CloudFront
import { $, act, api, confirmBox, del, esc, form, modal, post, regionLabel, regionOf, regionOpt, regionSelect, rq, SETTINGS, toast } from "./core.js";
import { go } from "./router.js";
import { loginFields, showCreated, tabInstances } from "./instances.js";
import { saveDefaultBtn } from "./settings.js";

// ---------------- Lightsail ----------------
export const tabLightsail = (acc, box) => tabInstances(acc, box, "lightsail");
export async function lightsailCreate(acc, reload) {
  let o;
  try { toast("正在读取镜像与套餐…"); o = await api(`/accounts/${acc.id}/lightsail/options?${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  const d = SETTINGS.default_create?.lightsail || {};
  const r = await modal("创建 Lightsail 实例", `<label>名称</label><input name="name" value="ls-${Date.now().toString(36)}">
    <label>可用区</label><select name="zone">${o.zones.map((z) => regionOpt(z, z === d.zone)).join("")}</select>
    <label>系统镜像</label><select name="blueprint">${o.blueprints.map((b) => `<option value="${esc(b.id)}" ${b.id === d.blueprint ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select>
    <label>套餐</label><select name="bundle">${o.bundles.map((b) => `<option value="${esc(b.id)}" ${b.id === d.bundle ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select>
    <label>网络</label><select name="ip_type"><option value="dualstack">IPv4 + IPv6</option><option value="ipv6" ${d.ip_type === "ipv6" ? "selected" : ""}>仅 IPv6（更便宜）</option></select>
    ${await loginFields()}<div class="bar">${saveDefaultBtn("lightsail")}</div>`,
    (bg) => post(`/accounts/${acc.id}/lightsail/create`, { ...form(bg), region: regionOf(acc) }), "创建");
  if (r) { showCreated(r); setTimeout(reload, 3000); }
}

// ---------------- 配额 ----------------
export async function tabQuota(acc, box, refresh = false) {
  box.innerHTML = `<div class="card"><span class="spin"></span> 正在逐区域查询（串行，约 10–30 秒）…</div>`;
  let q;
  try { q = await api(`/accounts/${acc.id}/quotas${refresh ? "?refresh=true" : ""}`); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const v = q.standard_vcpu, cf = q.cloudfront_distributions || {};
  box.innerHTML = `<div class="grid">
    <div class="card"><h3>Standard vCPU 上限</h3><div class="big">${v ? esc(v.value) : "-"} ${esc(v?.unit || "")}</div>
      <div class="muted">全区域最大值，来自 ${esc(v?.region ? regionLabel(v.region) : "-")}（L-1216C47A）</div></div>
    <div class="card"><h3>CloudFront 分发数上限</h3><div class="big">${cf.value ?? "-"} ${esc(cf.unit || "")}</div>
      <div class="muted">每账号（L-24B04930）${cf.default ? "· AWS 默认值" : ""}${cf.error ? " · " + esc(cf.error) : ""}</div></div></div>
    <div class="card"><div class="bar"><h3 class="grow" style="margin:0">各区域 vCPU</h3><span class="muted">更新于 ${esc(q.updated_at)}（缓存 6 小时）</span>
    <button class="btn sm" id="rf">重新查询</button></div>
    <table><tr><th>区域</th><th>vCPU</th></tr>${q.per_region.map((r) => `<tr><td>${esc(regionLabel(r.region))}</td><td>${r.value ?? `<span class="muted">${esc(r.error || "-")}</span>`}</td></tr>`).join("")}</table></div>`;
  $("#rf", box).onclick = () => tabQuota(acc, box, true);
}

// ---------------- 回收站估算（AWS 闲置仍计费资源） ----------------
export async function tabRecycle(acc, box) {
  const reload = () => tabRecycle(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">重新扫描</button></div>
    <div id="rb"><div class="card"><span class="spin"></span> 正在扫描闲置资源（EC2/Lightsail 免费 API）…</div></div>`;
  $("#rf", box).onclick = reload;
  const out = $("#rb", box);
  let r;
  try { r = await api(`/accounts/${acc.id}/recycle?${rq(acc)}`); } catch (e) { out.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  out.innerHTML = `<div class="grid">
    <div class="card"><h3>闲置资源月费估算</h3><div class="big">$${esc(r.monthly_total)}</div>
      <div class="muted">区域 ${esc(regionLabel(r.region))} · ${r.items.length} 项 · 按公示单价估算，实际以账单为准</div></div>
    <div class="card"><h3>账单参考（缓存）</h3><div class="big">${r.month_to_date == null ? "—" : "$" + esc(r.month_to_date)}</div>
      <div class="muted">本月已产生 · 数据更新于 ${esc(r.billing_updated_at)}（不调用 Cost Explorer）</div>
      ${r.credit_remaining != null ? `<div class="muted">Credit 余 $${esc(r.credit_remaining)}${r.credit_months_for_idle ? `，仅闲置资源可再扣约 ${esc(r.credit_months_for_idle)} 个月` : ""}</div>` : ""}</div></div>
    <div class="card"><h3>明细</h3>
    ${r.items.length ? `<table><tr><th>资源</th><th>说明</th><th style="text-align:right">月费估算</th><th>建议</th></tr>
    ${r.items.map((i) => `<tr><td><b>${esc(i.name)}</b><div class="muted mono">${esc(i.id)}</div></td><td>${esc(i.detail)}</td>
    <td style="text-align:right">$${esc(i.monthly)}</td><td class="muted">${esc(i.tip)}</td></tr>`).join("")}</table>` : `<div class="empty">没有闲置计费资源 🎉</div>`}</div>`;
}
export async function ec2Create(acc, reload) {
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

// AWS 区域
export async function tabAwsRegions(acc, box, refresh = false) {
  box.innerHTML = `<div class="grid"><div class="card" id="st"><span class="spin"></span> 读取区域状态…</div><div class="card" id="sc"><span class="spin"></span> 全区域实例扫描（串行，约 30–60 秒）…</div></div>`;
  api(`/accounts/${acc.id}/aws/regions-status`).then((rs) => {
    $("#st", box).innerHTML = `<h3>区域激活</h3><p class="muted">香港、雅加达等 Opt-in 区域需先激活才能开机。</p><table><tr><th>区域</th><th>状态</th><th></th></tr>
      ${rs.map((r) => `<tr><td>${esc(regionLabel(r.region))}</td><td><span class="badge ${r.status === "ENABLED_BY_DEFAULT" || r.status === "ENABLED" ? "running" : ""}">${esc(r.status)}</span></td>
      <td>${r.status === "DISABLED" ? `<button class="btn sm" data-en="${esc(r.region)}">激活</button>` : ""}</td></tr>`).join("")}</table>`;
    box.querySelectorAll("[data-en]").forEach((b) => (b.onclick = async () => {
      const r = await act(b, () => post(`/accounts/${acc.id}/aws/enable-region`, { region: b.dataset.en }));
      if (r) { toast(r.hint); b.remove(); }
    }));
  }).catch((e) => ($("#st", box).innerHTML = `❌ ${esc(e.message)}<p class="muted">需要 account:ListRegions / account:EnableRegion 权限</p>`));
  api(`/accounts/${acc.id}/aws/scan${refresh ? "?refresh=true" : ""}`).then((d) => {
    const rows = d.regions.filter((r) => r.ec2 || r.lightsail);
    $("#sc", box).innerHTML = `<div class="bar"><h3 class="grow" style="margin:0">全区域实例</h3><span class="muted">${esc(d.updated_at)}</span><button class="btn sm" id="rs">重新扫描</button></div>
      ${rows.length ? `<table><tr><th>区域</th><th>EC2（运行）</th><th>Lightsail</th><th></th></tr>${rows.map((r) => `<tr><td>${esc(regionLabel(r.region))}</td><td>${r.ec2}（${r.ec2_running}）</td><td>${r.lightsail ?? "-"}</td>
      <td><button class="btn sm" data-go="${esc(r.region)}">查看</button></td></tr>`).join("")}</table>` : `<div class="empty">所有区域都没有实例</div>`}`;
    $("#rs", box).onclick = () => tabAwsRegions(acc, box, true);
    box.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => { localStorage.setItem("tc_region_" + acc.id, b.dataset.go); go(`#/aws/${acc.id}/ec2`); }));
  }).catch((e) => ($("#sc", box).innerHTML = `❌ ${esc(e.message)}`));
}

// ---- CloudFront：新建 / 缓存刷新 / 编辑配置 / 启停 / 套餐 / 删除（启用中先停用再删） ----
export const CF_PLAN = { PAYGO: "按量付费", FREE: "Free $0/月", PRO: "Pro $15/月", BUSINESS: "Business $200/月", PREMIUM: "Premium $1000/月起" };
export async function tabCloudFront(acc, box) {
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
export async function cfOp(acc, d, op, btn, reload) {
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

// ---------- 19. Lightsail 静态 IP（Lightsail 标签页下方） ----------
export async function tabLightsailV16(acc, box) {
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

// ---------------- build 20：新号 Credit（AWS 新免费计划 Free Tier credit + 5 个活动一键完成） ----------------
const CR_BADGE = { COMPLETED: "done", IN_PROGRESS: "pending", EXPIRING: "interrupted", NOT_STARTED: "" };
const CR_STEP = { executed: "已执行，等待 AWS 识别", failed: "执行失败", stopped: "已停止", skipped: "未执行", running: "执行中…", pending: "排队中" };
export const crMoney = (v, u) => (v == null || v === "" ? "-" : `${u && u !== "USD" ? u + " " : "$"}${(+v).toFixed(2).replace(/\.00$/, "")}`);
export const crDate = (s) => (s ? String(s).replace("T", " ").slice(0, 16) : "-");
function crLastRun(a) {
  const l = a.last_run;
  if (!l) return "";
  const cls = l.status === "executed" ? "ok" : l.status === "failed" ? "bad" : "";
  return `<div class="muted cr-last ${cls}">任务 #${l.task_id}：${esc(CR_STEP[l.status] || l.status)}${l.status === "failed" && l.message ? "：" + esc(l.message) : ""}</div>`;
}
export async function tabAwsCredit(acc, box, refresh = false) {
  const reload = (rf) => tabAwsCredit(acc, box, rf);
  box.innerHTML = `<div class="card"><span class="spin"></span> 正在读取 Free Tier 计划与活动（freetier，免费接口）…</div>`;
  let d;
  try { d = await api(`/accounts/${acc.id}/aws/credits${refresh ? "?refresh=true" : ""}`); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  if (!box.isConnected) return;
  const p = d.plan || {}, rt = d.running_task;
  const head = d.state === "ok" ? `<div class="grid" id="crPlan">
      <div class="card"><h3>剩余 Credit</h3><div class="big">${crMoney(p.remaining, p.unit)}</div><div class="muted">计划 ${esc(p.type || "-")} · ${esc(p.status || "-")}</div></div>
      <div class="card"><h3>到期时间</h3><div class="big" style="font-size:20px">${esc(crDate(p.expires))}</div><div class="muted">到期后未用完的 credit 失效（以 AWS 为准）</div></div></div>`
    : `<div class="card al warn" id="crState">⚠️ ${esc(d.message || "无法读取 Free Tier 状态")}${d.permissions ? `<div class="muted">需要的 IAM 只读权限：<span class="mono">${d.permissions.map(esc).join(" / ")}</span></div>` : ""}
      ${d.state === "not_applicable" ? `<div class="muted">只有使用新免费计划（2025-07-15 之后注册）的账号才有这些活动；下面仍可手动执行，但不会有奖励。</div>` : ""}</div>`;
  const rows = d.activities.map((a) => `<tr data-k="${a.key}"><td><b>${esc(a.label)}</b>${a.title ? `<div class="muted">${esc(a.title)}</div>` : ""}
      <div class="muted cr-plan">${esc(a.plan)}</div>${a.note ? `<div class="al warn cr-note">ℹ️ ${esc(a.note)}</div>` : ""}${crLastRun(a)}</td>
      <td><span class="badge ${CR_BADGE[a.status] || ""}">${esc(a.status_text)}</span></td><td>${crMoney(a.reward, a.unit)}</td>
      <td>${a.completed_at ? esc(crDate(a.completed_at)) : a.started_at ? `开始于 ${esc(crDate(a.started_at))}` : "-"}</td>
      <td>${a.runnable ? `<button class="btn sm primary" data-run="${a.key}" ${rt ? "disabled" : ""}>一键完成</button>` : `<span class="muted">✅</span>`}</td></tr>`).join("");
  const extra = (d.extra_activities || []).length ? `<p class="muted">AWS 另外返回的活动（面板暂不支持一键完成）：${d.extra_activities.map((a) => `${esc(a.title)}（${esc(a.status_text)}）`).join("、")}</p>` : "";
  box.innerHTML = `${head}
    <div class="card"><div class="bar"><h3 class="grow" style="margin:0">新号 Credit 活动</h3>
      <span class="muted">${esc(d.updated_at || "")}${d.cached ? `（缓存，${Math.round(d.age / 60)} 分钟前）` : ""}</span>
      <button class="btn sm" id="crRf">刷新</button><button class="btn sm" id="crAll" ${rt || !d.pending.length ? "disabled" : ""}>一键全部完成</button>
      <button class="btn sm danger" id="crClean" ${rt ? "disabled" : ""}>清理残留</button></div>
      <div id="crRun"></div>
      <table id="crTable"><tr><th>活动</th><th>状态</th><th>奖励</th><th>完成时间</th><th></th></tr>${rows}</table>${extra}
      <ul class="muted" id="crNotes">${(d.notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>`;
  $("#crRf", box).onclick = () => reload(true);
  if (rt) crProgress(acc, box, rt);
  box.querySelectorAll("[data-run]").forEach((b) => (b.onclick = async () => {
    const a = d.activities.find((x) => x.key === b.dataset.run);
    const ok = await confirmBox(`一键完成：${a.label}`, `${esc(a.plan)}<br><br>${a.note ? esc(a.note) + "<br><br>" : ""}资源打标签 <span class="mono">tricloud-credit=1</span>，用完自动清理。
      完成后显示「已执行，等待 AWS 识别」——AWS 未公开说明 API 操作是否计入活动，最终以 AWS 返回的活动状态为准（可能要几分钟到几小时）。确认执行？`);
    if (!ok) return;
    const r = await act(b, () => post(`/accounts/${acc.id}/aws/credits/activities/${a.key}/run`, { confirm: true }));
    if (r) { toast(r.message); reload(false); }
  }));
  $("#crAll", box).onclick = async () => {
    const names = d.activities.filter((a) => d.pending.includes(a.key)).map((a) => a.label).join("、");
    if (!(await confirmBox("一键全部完成", `将按顺序执行未完成的活动：<b>${esc(names)}</b>。<br>每个活动用完自动清理；全部跑完约 20–40 分钟（RDS 最久）。`))) return;
    if (!(await confirmBox("再次确认：会产生少量费用", `EC2、RDS 会各运行几分钟，Lambda / Bedrock 调用极少，费用金额极小，<b>从 credit 中扣</b>。<br>执行后只表示「已执行，等待 AWS 识别」，不代表已拿到奖励。确认开始？`, true))) return;
    const r = await act($("#crAll", box), () => post(`/accounts/${acc.id}/aws/credits/run-all`, { confirm: true }));
    if (r) { toast(r.message + (r.skipped?.length ? "：" + r.skipped.map((s) => s.reason).join("；") : "")); reload(false); }
  };
  $("#crClean", box).onclick = async () => {
    const r0 = await modal("清理残留资源", `<p>删除带 <span class="mono">tricloud-credit=1</span> 标签的 EC2 实例、名称以 tricloud-credit-db 开头的 RDS 实例、Lambda 函数 tricloud-credit-web 和角色 tricloud-credit-lambda-role（不会动其他资源）。</p>
      <label><input type="checkbox" name="include_budget" style="width:auto"> 同时删除预算 tricloud-credit-budget（预算免费，一般不用删）</label>`,
      (bg) => post(`/accounts/${acc.id}/aws/credits/cleanup`, { confirm: true, ...form(bg) }), "清理", true);
    if (!r0) return;
    const n = r0.deleted.length, e = r0.errors.length;
    toast(n ? `已清理 ${n} 项：${r0.deleted.map((x) => x.id).join("、")}` + (e ? `；${e} 项失败：${r0.errors.map((x) => x.error).join("；")}` : "") : e ? `清理失败：${r0.errors.map((x) => x.error).join("；")}` : "没有残留资源", e > 0);
  };
}
async function crProgress(acc, box, rt) {
  const el = $("#crRun", box);
  let after = 0, lines = [];
  const tick = async () => {
    if (!el.isConnected) return;
    let t;
    try { t = await api(`/tasks/${rt.id}?after=${after}`); } catch (_) { setTimeout(tick, 5000); return; }
    after = t.last_log_id || after;
    lines = lines.concat((t.logs || []).map((l) => l.msg)).slice(-8);
    const steps = (t.result && t.result.steps) || {};
    const keys = rt.activities || [];
    const done = keys.filter((k) => steps[k] && !["running", "pending"].includes(steps[k].status)).length;
    el.innerHTML = `<div class="al" id="crProg"><b>任务 #${rt.id} 执行中</b>（${done}/${keys.length}）：${esc(t.message || "")}
      <progress max="${keys.length || 1}" value="${done}" style="width:100%"></progress>
      <pre class="mono" style="white-space:pre-wrap;margin:4px 0 0;font-size:12px">${lines.map(esc).join("\n")}</pre>
      <a href="javascript:void 0" id="crTask">查看完整日志</a></div>`;
    $("#crTask", el).onclick = () => window.TaskDrawer && window.TaskDrawer.open(rt.id);
    if (t.status === "running") setTimeout(tick, 3000);
    else { toast(t.message || "任务结束", t.status === "failed"); tabAwsCredit(acc, box, false); }
  };
  tick();
}
