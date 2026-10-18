// TriCloud 前端 v1.6.0 · 云账号管理：添加 / 批量添加 / 编辑 / 粘贴识别、测活、账号类型与停用、已删账号
import { $, accountRegionText, ACCOUNTS, act, ADD_BODY, api, confirmBox, del, esc, fmtDT, form, loadAccounts, loading, modal, PNAME, post, PROV_HINT, provOpts, PROVS, refreshMachineRegions, regionLabel, TEXTAREA_FIELDS, toast, view } from "./core.js";
import { go, route } from "./router.js";

// ---------------- 云账号管理 ----------------
export const CRED_FIELDS = {
  oci: [["user", "用户 OCID"], ["tenancy", "租户 OCID"], ["fingerprint", "API Key 指纹"], ["region", "区域", "ap-tokyo-1"],
    ["key_content", "私钥 (PEM)", "", "textarea"], ["pass_phrase", "私钥密码（可选）"], ["compartment", "区间 OCID（可选，默认根区间）"], ["home_region", "主区域（账单用，可选）"],
    ["proxy", "出口代理（可选）", "http://host:port"], ["proxy_user", "代理用户名（可选）"], ["proxy_pass", "代理密码（可选）", "", "password"]],
  aws: [["access_key", "Access Key ID"], ["secret_key", "Secret Access Key", "", "password"], ["region", "默认区域", "us-east-1"], ["proxy", "出口代理（可选）", "socks5://host:port"],
    ["proxy_user", "代理用户名（可选）"], ["proxy_pass", "代理密码（可选）", "", "password"]],
  azure: [["tenant_id", "Tenant ID"], ["client_id", "Client (App) ID"], ["client_secret", "Client Secret", "", "password"], ["subscription_id", "Subscription ID"],
    ["proxy", "出口代理（可选）", "http://host:port"], ["proxy_user", "代理用户名（可选）"], ["proxy_pass", "代理密码（可选）", "", "password"]],
};
// build 25：区域列显示有机器的区域；与默认区域不同时下面小字注明默认区域
export function accRegionCell(a) {
  const l = a.machine_regions || [];
  const sub = l.length > 1 ? l.map((r) => `${regionLabel(r.region)}：${r.count} 台`).join("\n") : "";
  const def = a.provider !== "azure" && l.length && a.region && a.region !== l[0].region ? `<div class="muted">默认 ${esc(regionLabel(a.region))}</div>` : "";
  return `<span${sub ? ` title="${esc(sub)}"` : ""}>${esc(accountRegionText(a) || "-")}</span>${def}`;
}
export async function pageAccounts() {
  const prov = (p) => ACCOUNTS.filter((a) => a.provider === p).length;
  view.innerHTML = `<div class="bar"><button class="btn primary" id="add">添加云账号</button><button class="btn" id="batch">批量添加</button>
    <select id="tprov" title="测活范围"><option value="">全部账号</option>${PROVS.filter(prov).map((p) => `<option value="${p}">${PNAME[p]}</option>`).join("")}</select>
    <button class="btn" id="testAll">⚡ 一键测活</button><a class="btn" href="#/deleted">🗑 已删账号</a><span class="grow"></span><span class="muted" id="tsum">凭证经 Fernet 加密保存在本机 SQLite，不经过任何第三方</span></div>
    <div class="card"><table><tr><th>名称</th><th>云</th><th>区域</th><th>云上创建 / 存活</th><th>连通</th><th>出口代理</th><th>添加时间</th><th></th></tr>
    ${ACCOUNTS.map((a) => `<tr data-acc="${a.id}" class="${a.disabled ? "acc-off" : ""}"><td><a href="#/${a.provider}/${a.id}">${esc(a.name)}</a>${a.disabled ? ` <span class="badge failed" title="${esc(a.disabled_reason || "")}">已停用</span>` : ""}${acctTypeTag(a)}</td><td><span class="dot ${a.provider}"></span> ${PNAME[a.provider]}</td>
    <td id="mr${a.id}">${accRegionCell(a)}</td><td>${ageText(a)}</td><td class="tcell">${testCell(a)}</td><td class="mono">${esc(a.proxy || "直连")}${a.proxy_user ? `<div class="muted">${esc(a.proxy_user)}${a.proxy_pass_set ? " · ●●●" : ""}</div>` : ""}</td><td>${new Date(a.created * 1000).toLocaleString()}</td>
    <td><button class="btn sm" data-test="${a.id}">测活</button> <button class="btn sm" data-info="${a.id}">信息</button> <button class="btn sm" data-type="${a.id}">类型</button>${a.disabled ? ` <button class="btn sm" data-off="${a.id}">启用</button>` : ""} <button class="btn sm" data-edit="${a.id}">编辑</button> <button class="btn sm" data-px="${a.id}">代理</button> <button class="btn sm danger" data-del="${a.id}">删除</button></td></tr>`).join("") || `<tr><td colspan=8 class="muted">暂无</td></tr>`}</table></div>`;
  $("#add").onclick = addAccount;
  $("#batch").onclick = batchAddAccounts;
  refreshMachineRegions(ACCOUNTS, (a) => { const td = document.getElementById("mr" + a.id); if (td) td.innerHTML = accRegionCell(a); });
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
export const credInput = ([k, l, ph, t]) => `<label>${l}</label>` + (t === "textarea" ? `<textarea name="c_${k}" placeholder="${esc(ph || (k === "key_content" ? "-----BEGIN PRIVATE KEY-----" : ""))}"></textarea>`
  : `<input name="c_${k}" type="${t || "text"}" placeholder="${esc(ph || "")}" autocomplete="off">`);
export async function addAccount() {
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
  const hint = { oci: "OCI 控制台右上角头像 → User settings（进入 My profile）→ Tokens and keys 标签 → Add API key 生成。", aws: "建议使用仅含 EC2/Lightsail/CloudFront/Service Quotas/CE 权限的 IAM 用户。", azure: "az ad sp create-for-rbac --role Contributor --scopes /subscriptions/<id> 生成。", ...PROV_HINT }[p];
  $("#cf").innerHTML = CRED_FIELDS[p].map(credInput).join("");
  $("#hint").textContent = hint;
});

// ---------- 账号：存活天数、测活、信息、批量添加 ----------
export function acctTypeTag(a) {   // v1.6：缓存的账号类型（点「类型」查询后显示）
  try { const t = a.acct_type ? JSON.parse(a.acct_type) : null; return t && t.label ? ` <span class="badge" title="${esc(t.plan_type || "")}">${esc(t.label)}${t.age_days != null ? ` · ${t.age_days} 天` : ""}</span>` : ""; } catch (_) { return ""; }
}
export function ageText(a) {
  if (!a.cloud_created_at) return `<span class="muted">未填写</span>`;
  const days = Math.floor((Date.now() - new Date(a.cloud_created_at + "T00:00:00").getTime()) / 86400000);
  return `${esc(a.cloud_created_at)}<div class="muted">已存活 ${days} 天</div>`;
}
export function testCell(a, r) {
  const ok = r ? r.ok : a.last_test_ok, ms = r ? r.ms : a.last_test_ms, err = r ? r.error : a.last_test_error;
  if (ok == null) return `<span class="muted">未测</span>`;
  return ok ? `<span class="badge running">连通</span> <span class="muted">${ms} ms</span>`
    : `<span class="badge failed">失败</span> <span class="muted" title="${esc(err || "")}">${esc((err || "").slice(0, 40))}</span>`;
}
export async function accountInfoDialog(a) {
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
export async function batchAddAccounts(prefill) {
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

// ---- 已删账号（账号管理入口）。注意与 AWS「闲置资源」估算不是一回事 ----
export async function pageDeletedAccounts() {
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
export const CRED_LABEL = { user: "用户 OCID", tenancy: "租户 OCID", fingerprint: "API Key 指纹", key_content: "私钥 (PEM)", pass_phrase: "私钥密码", region: "区域",
  compartment: "区间 OCID（可选）", home_region: "主区域（可选）", access_key: "Access Key ID", secret_key: "Secret Access Key", tenant_id: "Tenant ID",
  client_id: "Client (App) ID", client_secret: "Client Secret", subscription_id: "Subscription ID" };
export const proxyFields = (d = {}) => `<label>出口代理地址（可选，留空 = 直连）</label><input name="proxy" value="${esc(d.proxyUrl || "")}" placeholder="http://host:3128 或 socks5://host:1080" autocomplete="off">
  <div class="row2"><div><label>代理用户名（可选）</label><input name="proxy_user" value="${esc(d.proxy_user || "")}" autocomplete="off"></div>
  <div><label>代理密码${d.proxy_pass_set ? "（已设置，留空不改）" : "（可选）"}</label><input name="proxy_pass" type="password" placeholder="${d.proxy_pass_set ? "留空保持不变" : ""}" autocomplete="new-password"></div></div>
  ${d.proxy_pass_set ? `<label><input type="checkbox" name="proxy_pass_clear" style="width:auto"> 清除代理密码</label>` : ""}
  <p class="muted">也兼容旧写法 http://user:pass@host:port。密码加密保存、不回显。</p>`;
export async function editAccount(a) {
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
export let SMART_ITEMS = [], SMART_T = 0;
export function smartFill() {
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
export async function smartParse() {
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

// ---------- 11. 账号类型 / 停用 ----------
export async function accountTypeDialog(a, refresh) {
  let r;
  try { toast("查询账号类型…"); r = await api(`/accounts/${a.id}/account-type${refresh ? "?refresh=1" : ""}`); } catch (e) { return toast(e.message, true); }
  const ok = await modal(`账号类型 · ${a.name}`, `<div class="kv"><span>类型</span><span><b>${esc(r.label || "-")}</b></span>
    ${r.plan_type ? `<span>计划</span><span class="mono">${esc(r.plan_type)}</span>` : ""}${r.account_type ? `<span>账户</span><span>${esc(r.account_type)}</span>` : ""}
    ${r.upgrade_state ? `<span>升级状态</span><span>${esc(r.upgrade_state)}</span>` : ""}${r.time_start ? `<span>开户日期</span><span>${esc(r.time_start)}</span>` : ""}
    ${r.age_days != null ? `<span>开户天数</span><span>${r.age_days} 天</span>` : ""}${r.home_region ? `<span>主区域</span><span>${esc(regionLabel(r.home_region))}</span>` : ""}
    ${r.state ? `<span>订阅状态</span><span>${esc(r.state)}</span>` : ""}</div>${r.error || r.hint ? `<p class="muted">${esc(r.error || r.hint)}</p>` : ""}
    <p class="muted">查询于 ${new Date((r.checked_at || 0) * 1000).toLocaleString()}</p>`, null, "重新查询");
  if (ok) accountTypeDialog(a, true);
}
export async function toggleDisable(a) {
  if (a.disabled) {
    if (await act(null, () => post(`/accounts/${a.id}/disable`, { disabled: false }), "已启用")) { await loadAccounts(); route(); }
    return;
  }
  const r = await modal("停用账号", `<p>停用「${esc(a.name)}」（比如被封号）：</p><ul class="guard"><li>不再测活、不监控、不跑流量守护；</li><li>该账号运行中的任务（抢机等）全部停止；</li><li>凭证和云上资源都不动，随时可以重新启用。</li></ul>
    <label>原因（可选）</label><input name="reason" placeholder="如 被封号 / 欠费">`, (bg) => post(`/accounts/${a.id}/disable`, { disabled: true, ...form(bg) }), "停用", true);
  if (r) { toast(`已停用${r.stopped_tasks.length ? `，停止了 ${r.stopped_tasks.length} 个任务` : ""}`); await loadAccounts(); route(); }
}
