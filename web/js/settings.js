// TriCloud 前端 v1.6.0 · 设置、安全（二次验证 / API Token / 审计 / 备份）、开机密码、脚本模板、DNS 联动、保存为默认
import { getLang, t } from "./i18n.js";
import { $, act, api, confirmBox, del, esc, form, loading, modal, post, setCompact, setSettings, SETTINGS, SETTINGS_CARDS, toast, view } from "./core.js";
import { odSettingsBind, odSettingsCard } from "./onedrive.js";

// ---------------- 设置 ----------------
export async function pageSettings() {
  loading();
  setSettings(await api("/settings"));
  const s = SETTINGS;
  const dc = s.default_create || {};
  view.innerHTML = `<div class="grid">
  <div class="card" id="tg"><h3>Telegram</h3>
    <label>Bot Token ${s.tg_token_set ? `<span class="badge done">${t("set.setBadge", { hint: esc(s.tg_token_hint) })}</span>` : ""}</label>
    <input name="tg_token" type="password" placeholder="${s.tg_token_set ? t("set.keepPh") : "123456:ABC..."}" autocomplete="off">
    <label>${t("set.chatId")}</label><input name="tg_chat_id" value="${esc(s.tg_chat_id || "")}">
    <label><input type="checkbox" name="daily_report" style="width:auto" ${s.daily_report ? "checked" : ""}> ${t("set.dailyReport")}</label>
    <div class="row2"><div><label>${t("set.reportTime")}</label><input name="report_time" type="time" value="${esc(s.report_time || "09:00")}"></div>
    <div><label>${t("set.monInterval")}</label><input name="monitor_interval" type="number" min="1" value="${esc(s.monitor_interval || 5)}"></div></div>
    <label>${t("set.timezone")}</label><input name="timezone" value="${esc(s.timezone || "Asia/Shanghai")}">
    <div class="bar" style="margin-top:12px"><button class="btn primary" id="save">${t("common.save")}</button><button class="btn" id="test">${t("set.tgTest")}</button></div></div>
  <div class="card" id="cfc"><h3>Cloudflare</h3><p class="muted">${t("set.cfNote")}</p>
    <label>API Token ${s.cf_token_set ? `<span class="badge done">${t("set.isSet")}</span>` : ""}</label>
    <input name="cf_token" type="password" placeholder="${s.cf_token_set ? t("set.keepPh") : "Cloudflare API Token"}" autocomplete="off">
    <div class="bar" style="margin-top:12px"><button class="btn primary" id="saveCf">${t("common.save")}</button>${s.cf_token_set ? `<button class="btn" id="clrCf">${t("set.clear")}</button>` : ""}</div></div>
  <div class="card" id="pcc"><h3>${t("set.pc")}</h3><p class="muted">${t("set.pcNote")}</p>
    <label>${t("set.pcKey")}${s.proxycheck_key_set ? ` <span class="badge done">${t("set.isSet")}</span>` : ""}</label>
    <input name="proxycheck_key" type="password" placeholder="${s.proxycheck_key_set ? t("set.keepPh") : t("set.pcPh")}" autocomplete="off">
    <div class="bar" style="margin-top:12px"><button class="btn primary" id="savePc">${t("common.save")}</button>${s.proxycheck_key_set ? `<button class="btn" id="clrPc">${t("set.clear")}</button>` : ""}</div></div>
  <div class="card"><h3>${t("set.dcTitle")}</h3><p class="muted">${t("set.dcNote")}</p>
    <textarea id="dc" style="min-height:220px">${esc(JSON.stringify(Object.keys(dc).length ? dc : {
      oci: { shape: "VM.Standard.A1.Flex", ocpus: 4, memory_gb: 24, disk_gb: 50, os: "Canonical Ubuntu", os_version: "22.04", ssh_key: "" },
      lightsail: { blueprint: "debian_12", bundle: "nano_3_0", zone: "" } }, null, 2))}</textarea>
    <div class="bar" style="margin-top:12px"><button class="btn primary" id="saveDc">${t("common.save")}</button></div></div>
  <div class="card" id="fg"><h3>${t("set.fgTitle")}</h3><p class="muted">${t("set.fgNote")}</p>
    <label><input type="checkbox" name="free_guard" ${s.free_guard === false ? "" : "checked"}> ${t("set.fgOn")}</label>
    <div class="bar" style="margin-top:12px"><button class="btn primary" id="saveFg">${t("common.save")}</button></div></div>
  <div class="card" id="v14"><h3>${t("set.v14Title")}</h3>
    <label>${t("set.autoIpLimit")}</label><input name="auto_ip_daily_limit" type="number" min="0" max="50" value="${esc(s.auto_ip_daily_limit ?? 3)}">
    <p class="muted">${t("set.autoIpNote")}</p>
    <div class="bar" style="margin-top:8px"><button class="btn primary" id="saveV14">${t("common.save")}</button></div>
    <label><input type="checkbox" id="compact" ${document.documentElement.classList.contains("compact") ? "checked" : ""}> ${t("set.compact")}</label></div>
  <div class="card" id="pw"><h3>${t("set.pwTitle")}</h3><label>${t("set.oldPw")}</label><input name="old" type="password">
    <label>${t("set.newPw")}</label><input name="new" type="password"><div class="bar" style="margin-top:12px"><button class="btn primary" id="savePw">${t("set.change")}</button></div>
    <p class="muted">${t("set.pwNote")}</p></div>${odSettingsCard()}${SETTINGS_CARDS.map((c) => c.html(s)).join("")}</div>`;
  SETTINGS_CARDS.forEach((c) => c.bind(view));
  odSettingsBind();
  $("#save").onclick = (e) => { const f = form($("#tg")); if (!f.tg_token) delete f.tg_token; act(e.target, () => post("/settings", f), t("common.saved")).then(pageSettings); };
  $("#test").onclick = (e) => act(e.target, () => post("/settings/tg-test"), t("set.tgTestSent"));
  $("#saveCf").onclick = (e) => { const f = form($("#cfc")); if (!f.cf_token) return toast(t("set.needToken"), true); act(e.target, () => post("/settings", f), t("common.saved")).then(pageSettings); };
  $("#savePc").onclick = (e) => { const f = form($("#pcc")); if (!f.proxycheck_key) return toast(t("set.needKey"), true); act(e.target, () => post("/settings", f), t("common.saved")).then(pageSettings); };
  if ($("#clrPc")) $("#clrPc").onclick = (e) => act(e.target, () => post("/settings", { proxycheck_key_clear: true }), t("set.cleared")).then(pageSettings);
  if ($("#clrCf")) $("#clrCf").onclick = (e) => act(e.target, () => post("/settings", { cf_token_clear: true }), t("set.cleared")).then(pageSettings);
  $("#saveDc").onclick = (e) => { let v; try { v = JSON.parse($("#dc").value); } catch (_) { return toast(t("set.jsonErr"), true); } act(e.target, () => post("/settings", { default_create: v }), t("common.saved")); SETTINGS.default_create = v; };
  $("#saveFg").onclick = (e) => act(e.target, () => post("/settings", form($("#fg"))), t("common.saved"));
  $("#saveV14").onclick = (e) => act(e.target, () => post("/settings", { auto_ip_daily_limit: +$("[name=auto_ip_daily_limit]").value }), t("common.saved"));
  $("#compact").onchange = (e) => setCompact(e.target.checked);
  $("#savePw").onclick = (e) => act(e.target, () => post("/password", form($("#pw"))), t("set.pwChanged")).then((r) => r && setTimeout(() => (location.href = "/login"), 1200));
}

// DNS 绑定
export async function bindDns(acc, inst) {
  let zones;
  try { zones = await api("/cf/zones"); } catch (e) { return toast(e.message + t("set.dnsNeedToken"), true); }
  // 回显本实例已有的绑定（此前对话框只摆空表单，绑没绑过分不清）；列表拉不到也不挡新增
  let mine = [];
  try { mine = (await api("/dns-bindings")).filter((d) => +d.account_id === +acc.id && d.instance_id === inst.id); } catch (_) { /* ignore */ }
  const boundHtml = mine.length
    ? `<label>${t("set.dnsBound")}</label>${mine.map((d) => `<div style="display:flex;align-items:center;gap:8px;margin:2px 0 6px"><span class="mono" style="flex:1;min-width:0;overflow-wrap:anywhere">${esc(d.record)}</span><span class="muted">${[d.v4 ? "A" : "", d.v6 ? "AAAA" : ""].filter(Boolean).join(" · ")}${d.proxied ? t("set.dnsProxySuffix") : ""}</span><button class="btn sm danger" type="button" data-unbind="${d.id}">${t("inst.unbind")}</button></div>`).join("")}`
    : `<p class="muted">${t("set.dnsNoneBound")}</p>`;
  const r = await modal(t("op.dns"), `${boundHtml}<p class="muted">${t("set.dnsNote")}</p>
    <label>${t("set.dnsDomain")}</label><select name="zone">${zones.map((z) => `<option value="${esc(z.id)}|${esc(z.name)}">${esc(z.name)}</option>`).join("")}</select>
    <label>${t("set.dnsRecord")}</label><div style="display:flex;align-items:center;gap:6px"><input name="record" placeholder="node1" style="flex:1;min-width:0"><span class="mono muted" id="dnsSuffix" style="white-space:nowrap">.${esc((zones[0] || {}).name || "")}</span></div><p class="muted" style="margin:2px 0 6px">${t("set.dnsRecordHint")}</p>
    <label><input type="checkbox" name="v4" style="width:auto" checked> ${t("set.dnsA")}</label>
    <label><input type="checkbox" name="v6" style="width:auto"> ${t("set.dnsAAAA")}</label>
    <label><input type="checkbox" name="proxied" style="width:auto"> ${t("set.dnsProxied")}</label>
    <label><input type="checkbox" name="sync_now" style="width:auto" checked> ${t("set.dnsSync")}</label>`, (bg) => {
    const f = form(bg); const [zone_id, zone_name] = f.zone.split("|");
    return post("/dns-bindings", { account_id: acc.id, instance_id: inst.id, name: inst.name, zone_id, zone_name, record: f.record,
      v4: f.v4, v6: f.v6, proxied: f.proxied, sync_now: f.sync_now, ipv4: inst.public_ip, ipv6: inst.ipv6 });
  }, t("aws.lsBind"), false, (bg) => {
    const sel = bg.querySelector("[name=zone]"), suf = bg.querySelector("#dnsSuffix");
    if (sel && suf) sel.onchange = () => (suf.textContent = "." + (sel.value.split("|")[1] || ""));
    bg.querySelectorAll("[data-unbind]").forEach((b) => (b.onclick = async () => {
      if (!(await confirmBox(t("set.dnsUnbindTitle"), t("set.dnsUnbindMsg"), true))) return;
      if (await act(b, () => del(`/dns-bindings/${b.dataset.unbind}`), t("set.unbound"))) {
        bg.querySelector("[data-x]").click();   // 关掉当前弹窗（以 null 结束，不会误弹成功提示）
        bindDns(acc, inst);   // 重新打开，刷新已绑定列表
      }
    }));
  });
  if (r) toast(r.dns && r.dns.length ? r.dns.join("；") : t("set.dnsBound"));
}
export async function pageDns() {
  loading();
  const list = await api("/dns-bindings");
  view.innerHTML = `<div class="card"><p class="muted">${t("set.dnsPageNote")}</p>
    <table><tr><th>${t("set.dnsColRecord")}</th><th>${t("oci.colInst")}</th><th>${t("oci.colAccount")}</th><th>${t("common.type")}</th><th></th></tr>${list.map((d) => `<tr><td class="mono">${esc(d.record)}</td><td>${esc(d.name)}</td><td>${esc(d.account_name)}</td>
    <td>${d.v4 ? "A " : ""}${d.v6 ? "AAAA " : ""}${d.proxied ? t("set.dnsProxySuffix") : ""}</td><td><button class="btn sm danger" data-del="${d.id}">${t("inst.unbind")}</button></td></tr>`).join("") || `<tr><td colspan=5 class="muted">${t("common.none")}</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (!(await confirmBox(t("set.dnsUnbindTitle"), t("set.dnsUnbindMsg"), true))) return; if (await act(b, () => del(`/dns-bindings/${b.dataset.del}`), t("set.unbound"))) pageDns(); }));
}

// 开机密码
export async function pageSecrets() {
  loading();
  const list = await api("/secrets");
  view.innerHTML = `<div class="card"><p class="muted">${t("set.secNote")}</p>
    <table><tr><th>${t("oci.colInst")}</th><th>${t("oci.colAccount")}</th><th>${t("set.colUser")}</th><th>${t("inst.colCreated")}</th><th></th></tr>${list.map((x) => `<tr><td>${esc(x.name)}</td><td>${esc(x.account_name || "-")}</td><td>${esc(x.username)}</td>
    <td>${new Date(x.created * 1000).toLocaleString()}</td><td><button class="btn sm" data-see="${x.id}">${t("aws.view")}</button> <button class="btn sm danger" data-del="${x.id}">${t("common.delete")}</button></td></tr>`).join("") || `<tr><td colspan=5 class="muted">${t("common.none")}</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-see]").forEach((b) => (b.onclick = async () => {
    const r = await modal(t("set.verifyPw"), `<input name="password" type="password" autocomplete="current-password">`, (bg) => post(`/secrets/${b.dataset.see}/reveal`, form(bg)), t("aws.view"));
    if (r) modal(t("set.bootPw"), `<label>${t("set.colUser")}</label><code>${esc(r.username)}</code><label>${t("set.colPassword")}</label><input value="${esc(r.password)}" readonly onclick="this.select()">`, null, t("common.close"));
  }));
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("set.delTitle"), t("set.secDelMsg"), true)) { await del(`/secrets/${b.dataset.del}`); pageSecrets(); } }));
}

// 脚本模板
export const SCRIPT_PRESETS = {
  "开启 BBR": "#!/bin/bash\necho 'net.core.default_qdisc=fq' >> /etc/sysctl.conf\necho 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.conf\nsysctl -p",
  "2GB Swap": "#!/bin/bash\nfallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile\necho '/swapfile none swap sw 0 0' >> /etc/fstab",
  "关闭 OCI 系统防火墙": "#!/bin/bash\niptables -P INPUT ACCEPT; iptables -P FORWARD ACCEPT; iptables -P OUTPUT ACCEPT; iptables -F\nnetfilter-persistent save 2>/dev/null || true\nsystemctl disable --now firewalld 2>/dev/null || true",
  "时区上海 + 常用工具": "#!/bin/bash\ntimedatectl set-timezone Asia/Shanghai\n(apt-get update && apt-get install -y curl wget unzip htop) || (dnf install -y curl wget unzip htop)",
};
const PRESET_LABEL = { "开启 BBR": "set.presetBbr", "2GB Swap": "set.presetSwap", "关闭 OCI 系统防火墙": "set.presetFw", "时区上海 + 常用工具": "set.presetTz" };

export async function pageScripts() {
  loading();
  const list = await api("/scripts");
  view.innerHTML = `<div class="bar"><button class="btn primary" id="new">${t("set.newTpl")}</button><span class="muted">${t("set.tplBarNote")}</span></div>
    <div class="card"><table><tr><th>${t("acc.colName")}</th><th>${t("set.colContent")}</th><th></th></tr>${list.map((x) => `<tr><td>${esc(x.name)}</td><td class="mono">${esc(x.content.slice(0, 80))}${x.content.length > 80 ? "…" : ""}</td>
    <td><button class="btn sm" data-ed="${x.id}">${t("common.edit")}</button> <button class="btn sm danger" data-del="${x.id}">${t("common.delete")}</button></td></tr>`).join("") || `<tr><td colspan=3 class="muted">${t("common.none")}</td></tr>`}</table></div>`;
  const edit = async (x) => {
    const r = await modal(x ? t("set.editTpl") : t("set.newTpl"), `<label>${t("acc.colName")}</label><input name="name" value="${esc(x?.name || "")}">
      ${x ? "" : `<label>${t("set.fromPreset")}</label><select id="pre"><option value="">${t("set.tplBlank")}</option>${Object.keys(SCRIPT_PRESETS).map((k) => `<option value="${esc(k)}">${esc(PRESET_LABEL[k] ? t(PRESET_LABEL[k]) : k)}</option>`).join("")}</select>`}
      <label>${t("set.colScript")}</label><textarea name="content" style="min-height:220px">${esc(x?.content || "#!/bin/bash\n")}</textarea>
      <p class="muted">${t("set.tplCurl")}</p>`, (bg) => post("/scripts", { id: x?.id, ...form(bg) }), t("common.save"));
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
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (!(await confirmBox(t("set.delTplTitle"), t("set.delTplMsg2"), true))) return; if (await act(b, () => del(`/scripts/${b.dataset.del}`), t("common.deleted"))) pageScripts(); }));
}

// 安全与备份：2FA、API Token、审计、备份恢复
export async function pageSecurity() {
  loading();
  const [toks, logs] = await Promise.all([api("/tokens"), api("/audit?limit=100")]);
  const s = await api("/settings");
  view.innerHTML = `<div class="grid">
  <div class="card"><h3>${t("set.totpTitle")}</h3>
    ${s.totp_enabled ? `<p><span class="badge running">${t("set.totpOnBadge")}</span> ${t("set.totpOnNote")}</p><button class="btn danger" id="off">${t("common.close")}</button>`
      : `<p class="muted">${t("set.totpOffNote2")}</p><button class="btn primary" id="on">${t("set.turnOn")}</button>`}</div>
  <div class="card"><h3>${t("set.bkTitle2")}</h3><p class="muted">${t("set.bkNote2")}</p>
    <div class="bar"><button class="btn primary" id="bk">${t("set.bkDownloadBtn")}</button><button class="btn" id="rs">${t("set.rsBtn")}</button></div></div>
  <div class="card"><div class="bar"><h3 class="grow" style="margin:0">API Token</h3><button class="btn sm primary" id="nt">${t("set.newShort")}</button></div>
    <p class="muted">${t("set.tokNote2")}</p>
    <table><tr><th>${t("acc.colName")}</th><th>${t("set.colPrefix")}</th><th>${t("set.colPerm")}</th><th>${t("set.colRecent")}</th><th></th></tr>${toks.map((tk) => `<tr><td>${esc(tk.name)}</td><td class="mono">${esc(tk.prefix)}…</td><td>${tk.scope === "read" ? t("set.scopeRead") : t("set.scopeFullShort")}</td>
    <td>${tk.last_used ? new Date(tk.last_used * 1000).toLocaleString() : t("set.never")}</td><td><button class="btn sm danger" data-rv="${tk.id}">${t("set.revoke")}</button></td></tr>`).join("") || `<tr><td colspan=5 class="muted">${t("common.none")}</td></tr>`}</table></div></div>
  <div class="card"><div class="bar"><h3 class="grow" style="margin:0">${t("set.auditTitle2")}</h3><button class="btn sm danger" id="auClr">${t("set.auditClear2")}</button></div><table><tr><th>${t("set.colTime")}</th><th>IP</th><th>${t("set.colSource")}</th><th>${t("set.colAction")}</th><th>${t("set.colResult")}</th></tr>
    ${logs.map((l) => `<tr><td>${new Date(l.ts * 1000).toLocaleString()}</td><td class="mono">${esc(l.ip)}</td><td>${esc(l.actor)}</td><td class="mono">${esc(l.action)}</td><td>${esc(l.detail)}</td></tr>`).join("") || `<tr><td colspan=5 class="muted">${t("common.none")}</td></tr>`}</table></div>`;
  if ($("#on")) $("#on").onclick = async () => {
    const r = await post("/2fa/setup").catch((e) => toast(e.message, true));
    if (!r) return;
    const ok = await modal(t("set.totpEnableTitle"), `<p>${t("set.totpManual2")}</p><input value="${esc(r.secret)}" readonly onclick="this.select()" class="mono">
      <p class="muted">${t("set.totpLink2")}</p><input value="${esc(r.uri)}" readonly onclick="this.select()" class="mono">
      <label>${t("set.totpCode2")}</label><input name="code" inputmode="numeric" maxlength="6">`, (bg) => post("/2fa/enable", form(bg)), t("set.turnOn"));
    if (ok) { toast(t("set.totpOnToast")); pageSecurity(); }
  };
  if ($("#off")) $("#off").onclick = async () => {
    const ok = await modal(t("set.totpOff"), `<label>${t("set.panelPw")}</label><input name="password" type="password"><label>${t("set.totpCurCode")}</label><input name="code" inputmode="numeric" maxlength="6">`,
      (bg) => post("/2fa/disable", form(bg)), t("common.close"), true);
    if (ok) { toast(t("set.turnedOff")); pageSecurity(); }
  };
  $("#nt").onclick = async () => {
    const r = await modal(t("set.newTokTitle2"), `<label>${t("acc.colName")}</label><input name="name" value="bot"><label>${t("set.colPerm")}</label><select name="scope"><option value="read">${t("set.scopeRead")}</option><option value="full">${t("set.scopeFull2")}</option></select>`,
      (bg) => post("/tokens", form(bg)), t("set.generate"));
    if (r) { await modal(t("set.tokCreated2"), `<p>${t("set.tokOnce2")}</p><input value="${esc(r.token)}" readonly onclick="this.select()" class="mono">`, null, t("set.savedIt2")); pageSecurity(); }
  };
  $("#auClr").onclick = async () => {
    if (!(await confirmBox(t("set.auditClearTitle2"), t("set.auditClearMsg2"), true))) return;
    const r = await act($("#auClr"), () => api("/audit?confirm=true", { method: "DELETE" }));
    if (r) { toast(t("set.auditCleared2", { n: r.deleted })); pageSecurity(); }
  };
  view.querySelectorAll("[data-rv]").forEach((b) => (b.onclick = async () => { if (await confirmBox(t("set.revokeTitle"), t("set.revokeMsg2"), true)) { await del(`/tokens/${b.dataset.rv}`); pageSecurity(); } }));
  $("#bk").onclick = async () => {
    await modal(t("set.bkDlTitle2"), `<label>${t("set.panelPw")}</label><input name="password" type="password"><label>${t("set.bkPass2")}</label><input name="passphrase" type="password">`, async (bg) => {
      const r = await fetch("/api/backup", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Lang": getLang() }, body: JSON.stringify(form(bg)) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || t("set.bkFail"));
      const blob = await r.blob(); const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = (r.headers.get("content-disposition") || "").split('filename="')[1]?.replace('"', "") || "tricloud.tcbk"; a.click();
      return true;
    }, t("set.download"));
  };
  $("#rs").onclick = async () => {
    const ok = await modal(t("set.rsTitle2"), `<p>${t("set.rsWarn2")}</p><label>${t("set.rsFile")}</label><input type="file" id="bf" accept=".tcbk">
      <label>${t("set.rsPass")}</label><input name="passphrase" type="password"><label>${t("set.curPanelPw")}</label><input name="password" type="password">`, async (bg) => {
      const file = bg.querySelector("#bf").files[0]; if (!file) throw new Error(t("set.pickFile"));
      const buf = new Uint8Array(await file.arrayBuffer()); let bin = ""; for (let i = 0; i < buf.length; i += 32768) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 32768));
      return post("/restore", { ...form(bg), file_b64: btoa(bin) });
    }, t("set.restore"), true);
    if (ok) { toast(t("set.restored")); setTimeout(() => (location.href = "/login"), 1200); }
  };
}

// ================= v1.5 新增 =================
// ---- 创建弹窗「保存为默认」：与「设置 → 默认创建参数」是同一份数据 ----
export const DEFAULT_SKIP = ["name", "interval", "max_attempts", "script", "password_login", "region", "location_hint"];
export const saveDefaultBtn = (kind) => `<button class="btn" type="button" data-savedef="${kind}" title="${t("set.saveDefTitle")}">💾 ${t("set.saveDef")}</button>`;
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-savedef]");
  if (!b) return;
  const root = b.closest(".modal") || b.closest(".card") || document;
  const vals = form(root);
  for (const k of Object.keys(vals)) if (DEFAULT_SKIP.includes(k) || k.startsWith("c_")) delete vals[k];
  const r = await act(b, () => api("/create-defaults", { method: "PUT", body: { provider: b.dataset.savedef, defaults: vals } }), t("set.savedDef"));
  if (r) SETTINGS.default_create = { ...(SETTINGS.default_create || {}), [b.dataset.savedef]: r.defaults };
});
