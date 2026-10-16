// TriCloud 前端 v1.6.0 · Azure：创建 VM、资源组、配额、订阅、Foundry
import { $, ACCOUNTS, act, api, confirmBox, esc, form, modal, post, regionLabel, regionOpt, SETTINGS, toast } from "./core.js";
import { accountInfoDialog } from "./accounts.js";
import { loginFields } from "./instances.js";
import { saveDefaultBtn } from "./settings.js";

// Azure 创建 / 资源组 / 配额
export let AZ_LOC = {};
export async function azLocations(acc) {
  if (!AZ_LOC[acc.id]) AZ_LOC[acc.id] = await api(`/accounts/${acc.id}/azure/locations`);
  return AZ_LOC[acc.id];
}
export async function tabAzCreate(acc, box) {
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let locs = [];
  try { locs = await azLocations(acc); } catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const dz = SETTINGS.default_create?.azure || {};
  const last = localStorage.getItem("tc_azloc_" + acc.id) || dz.location || "eastasia";
  box.innerHTML = `<div class="card" id="f"><h3>创建 Azure VM</h3><div class="row2">
    <div><label>名称</label><input name="name" value="vm-${Date.now().toString(36)}"></div>
    <div><label>区域</label><select name="location">${locs.map((l) => regionOpt(l, l === last)).join("")}</select></div>
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
export async function tabAzRgs(acc, box) {
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
export async function tabAzQuota(acc, box) {
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

// ---------- Azure 订阅（只读） ----------
export async function tabAzSubscription(acc, box) {
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

// ---------- Azure Foundry（AI Services）：配额、AI 资源与模型部署、Endpoint / Key ----------
export const FOUNDRY_REGION = {};
export async function tabAzFoundry(acc, box) {
  const region = FOUNDRY_REGION[acc.id] || "swedencentral";
  const reload = () => tabAzFoundry(acc, box);
  box.innerHTML = `<div class="card"><span class="spin"></span></div>`;
  let d;
  try { d = await api(`/accounts/${acc.id}/azure/foundry?region=${encodeURIComponent(region)}`); }
  catch (e) { box.innerHTML = `<div class="card">❌ ${esc(e.message)}<p class="muted">需要服务主体对订阅有 Contributor 权限，并已注册 Microsoft.CognitiveServices 资源提供程序。</p></div>`; return; }
  const res = d.resources || [], models = d.models || [];
  const regs = (d.regions || [region]).map((r) => regionOpt(r, r === region)).join("");
  const resHtml = res.length ? res.map((r) => `<div class="card"><h3>${esc(r.name)} <span class="badge">${esc(r.kind)}</span> <span class="muted">${esc(regionLabel(r.region))} · ${esc(r.resource_group)} · ${esc(r.state || "")}</span></h3>
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
    <div class="card"><h3>模型配额 · ${esc(regionLabel(region))}</h3>${q.length ? `<table><tr><th>配额项</th><th>已用 / 上限</th></tr>${q.map((x) => `<tr><td>${esc(x.name)}</td><td>${esc(x.used)} / ${esc(x.limit)}</td></tr>`).join("")}</table>`
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
