// TriCloud 前端 v1.6.0 · 设置、安全（二次验证 / API Token / 审计 / 备份）、开机密码、脚本模板、DNS 联动、保存为默认
import { $, act, api, confirmBox, del, esc, form, loading, modal, post, setCompact, setSettings, SETTINGS, SETTINGS_CARDS, toast, view } from "./core.js";

// ---------------- 设置 ----------------
export async function pageSettings() {
  loading();
  setSettings(await api("/settings"));
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

// DNS 绑定
export async function bindDns(acc, inst) {
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
export async function pageDns() {
  loading();
  const list = await api("/dns-bindings");
  view.innerHTML = `<div class="card"><p class="muted">在实例卡片上点「绑定域名」添加。Token 在「设置 → Cloudflare」配置。</p>
    <table><tr><th>记录</th><th>实例</th><th>账号</th><th>类型</th><th></th></tr>${list.map((d) => `<tr><td class="mono">${esc(d.record)}</td><td>${esc(d.name)}</td><td>${esc(d.account_name)}</td>
    <td>${d.v4 ? "A " : ""}${d.v6 ? "AAAA " : ""}${d.proxied ? "· 代理" : ""}</td><td><button class="btn sm danger" data-del="${d.id}">解绑</button></td></tr>`).join("") || `<tr><td colspan=5 class="muted">暂无</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (!(await confirmBox("解绑域名", "解绑后换 IP 不再自动更新这条解析（Cloudflare 上的记录保留）。确定？", true))) return; if (await act(b, () => del(`/dns-bindings/${b.dataset.del}`), "已解绑")) pageDns(); }));
}

// 开机密码
export async function pageSecrets() {
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
export const SCRIPT_PRESETS = {
  "开启 BBR": "#!/bin/bash\necho 'net.core.default_qdisc=fq' >> /etc/sysctl.conf\necho 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.conf\nsysctl -p",
  "2GB Swap": "#!/bin/bash\nfallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile\necho '/swapfile none swap sw 0 0' >> /etc/fstab",
  "关闭 OCI 系统防火墙": "#!/bin/bash\niptables -P INPUT ACCEPT; iptables -P FORWARD ACCEPT; iptables -P OUTPUT ACCEPT; iptables -F\nnetfilter-persistent save 2>/dev/null || true\nsystemctl disable --now firewalld 2>/dev/null || true",
  "时区上海 + 常用工具": "#!/bin/bash\ntimedatectl set-timezone Asia/Shanghai\n(apt-get update && apt-get install -y curl wget unzip htop) || (dnf install -y curl wget unzip htop)",
};
export async function pageScripts() {
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
export async function pageSecurity() {
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

// ================= v1.5 新增 =================
// ---- 创建弹窗「保存为默认」：与「设置 → 默认创建参数」是同一份数据 ----
export const DEFAULT_SKIP = ["name", "interval", "max_attempts", "script", "password_login", "region", "location_hint"];
export const saveDefaultBtn = (kind) => `<button class="btn" type="button" data-savedef="${kind}" title="把当前表单的值保存为该云的创建默认值（不含名称、密码、脚本内容）">💾 保存为默认</button>`;
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-savedef]");
  if (!b) return;
  const root = b.closest(".modal") || b.closest(".card") || document;
  const vals = form(root);
  for (const k of Object.keys(vals)) if (DEFAULT_SKIP.includes(k) || k.startsWith("c_")) delete vals[k];
  const r = await act(b, () => api("/create-defaults", { method: "PUT", body: { provider: b.dataset.savedef, defaults: vals } }), "已保存为默认值");
  if (r) SETTINGS.default_create = { ...(SETTINGS.default_create || {}), [b.dataset.savedef]: r.defaults };
});
