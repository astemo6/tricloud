// TriCloud 前端 v1.6.0 build 23 · OneDrive 定期备份（设备码绑定、计划与保留、备份密码、立即备份、备份列表与恢复、解绑）
// build 23：计划支持 每 N 小时 / 每天多个时间点 / 每周多选 / 每月日期（含月末）/ Cron，保存前预览接下来 3 次
import { $, act, api, applyShowWhen, confirmBox, esc, fmtBytes, fmtDT, form, loading, modal, post, toast, view } from "./core.js";

const OD_WD = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
export const OD_LOGIN_URL = "https://microsoft.com/devicelogin";
let odTimer = null;

const OD_MODES = [["hourly", "每 N 小时"], ["daily", "每天（多个时间点）"], ["weekly", "每周（多选星期）"], ["monthly", "每月（指定日期）"], ["cron", "高级：Cron 表达式"]];
let odPrevTimer = null, odPrevSeq = 0;
// build 23：计划描述由后端给（s.desc）；旧后端没有 desc 时退回 freq/time
export const odPlan = (c, desc) => esc(desc || ((c.freq === "weekly" ? `每${OD_WD[+c.weekday || 0]} ` : "每天 ") + c.time)) + `，保留 ${esc(c.keep)} 份`;

// 设置页里的小卡片：状态一行 + 进入按钮
export function odSettingsCard() {
  return `<div class="card" id="odCard"><h3>OneDrive 备份</h3><p class="muted">把数据库和加密密钥用你的备份密码加密后，定期上传到你自己的 OneDrive「应用」文件夹（只授权这一个文件夹）。</p>
    <div id="odSum" class="muted">读取中…</div><div class="bar" style="margin-top:12px"><a class="btn primary" href="#/onedrive">打开 OneDrive 备份</a></div></div>`;
}
export async function odSettingsBind() {
  const el = document.getElementById("odSum"); if (!el) return;
  try {
    const s = await api("/onedrive");
    el.innerHTML = !s.bound ? `<span class="badge">未绑定</span>` : `<span class="badge done">已绑定</span> ${s.ready ? `${odPlan(s.cfg, s.desc)} · 下次 ${esc(s.next_run || "-")}` : s.password_set ? "定时备份已停用" : "还没设置备份密码"}`
      + (s.state.last_ok ? `<br>上次成功 ${esc(fmtDT(s.state.last_ok))}` : "") + (s.state.last_result === "failed" ? `<br><span class="err-text">上次失败：${esc(s.state.last_error || "")}</span>` : "");
  } catch (e) { el.textContent = e.message; }
}

function stopPoll() { if (odTimer) { clearTimeout(odTimer); odTimer = null; } }

export async function pageOneDrive(hint) {
  stopPoll();
  loading();
  const s = await api("/onedrive");
  const c = s.cfg, st = s.state || {};
  const failed = st.last_result === "failed";
  view.innerHTML = `<div class="grid">
  <div class="card" id="odStat"><h3>状态</h3>
    <p>${s.bound ? `<span class="badge done">已绑定</span> ${esc((s.account && s.account.folder) ? "OneDrive / 应用 / " + s.account.folder : "个人 OneDrive")}` : `<span class="badge">未绑定</span>`}
      ${s.password_set ? `<span class="badge done">已设置备份密码</span>` : `<span class="badge">未设置备份密码</span>`}</p>
    <p>${s.ready ? `定时：${odPlan(c, s.desc)}（${esc(s.timezone)}）<br>下次备份：<b>${esc((s.next_runs_label || [])[0] || s.next_run || "-")}</b>${(s.next_runs_label || []).length > 1 ? `<br><span class="muted">之后：${s.next_runs_label.slice(1).map(esc).join("、")}</span>` : ""}` : `<span class="muted">${!s.bound ? "绑定 OneDrive 并设置备份密码后开始定时备份" : !s.password_set ? "设置备份密码后开始定时备份" : "定时备份已停用"}</span>`}</p>
    ${st.last_ok ? `<p>上次成功：${esc(fmtDT(st.last_ok))} · ${esc(st.last_file || "")}${st.last_size ? ` · ${esc(fmtBytes(st.last_size))}` : ""}</p>` : ""}
    ${failed ? `<p class="err-text">上次失败（${esc(fmtDT(st.last_try))}）：${esc(st.last_error || "")}</p>` : ""}
    ${st.auth_error ? `<p class="err-text">${esc(st.auth_error)}</p>` : ""}
    ${s.running_task_id ? `<p><span class="spin"></span> 备份进行中（任务 #${s.running_task_id}）</p>` : ""}
    <div class="bar" style="margin-top:8px"><button class="btn primary" id="odNow" ${s.bound && s.password_set && !s.running_task_id ? "" : "disabled"}>立即备份</button>
      ${s.bound ? `<button class="btn danger" id="odUnbind">解绑</button>` : ""}</div></div>
  <div class="card" id="odApp"><h3>1. Azure 应用与绑定</h3>
    <p class="muted">在 Azure 门户注册一个你自己的应用（公共客户端、允许个人 Microsoft 帐户、启用「允许公共客户端流」），把「应用程序(客户端) ID」填到这里。教程见文档 docs/api-credentials.md 的「OneDrive 备份」一节。只申请 <code>Files.ReadWrite.AppFolder</code> + <code>offline_access</code>，看不到网盘里的其他文件。</p>
    <label>client_id（应用程序(客户端) ID）</label><input name="client_id" class="mono" value="${esc(s.client_id || "")}" placeholder="00000000-0000-0000-0000-000000000000" autocomplete="off">
    <label>登录端点</label><select name="tenant"><option value="consumers" ${s.tenant === "consumers" ? "selected" : ""}>consumers（个人 Microsoft 帐户，推荐）</option><option value="common" ${s.tenant === "common" ? "selected" : ""}>common（个人 + 工作/学校帐户）</option></select>
    <div class="bar" style="margin-top:12px">${s.bound
      ? `<button class="btn" id="odSaveApp">保存</button><button class="btn" id="odBind">重新绑定</button>`
      : `<button class="btn sm" id="odSaveApp">保存</button><button class="btn primary" id="odBind" style="font-weight:600;padding:10px 22px" ${s.client_id ? "" : "disabled"}>🔗 绑定 OneDrive</button>`}</div>
    ${!s.bound && s.client_id ? `<p class="muted" id="odBindHint">${hint ? "✅ 已保存。" : ""}点右边蓝色「绑定 OneDrive」获取代码，代码会显示在下方。</p>` : !s.bound ? `<p class="muted" id="odBindHint">填好 client_id 后点右边蓝色「绑定 OneDrive」，下方会弹出代码（会自动先保存 client_id）。</p>` : ""}
    <div id="odPendBox"></div></div>
  <div class="card" id="odPlan"><h3>2. 计划、保留与备份密码</h3>
    <label><input type="checkbox" name="enabled" style="width:auto" ${c.enabled ? "checked" : ""}> 启用定时备份</label>
    ${odSchedForm(c, s.timezone)}
    <label>保留最近几份（1–365，多余的自动删除）</label><input name="keep" type="number" min="1" max="365" value="${esc(c.keep)}">
    <label>备份密码（不能为空，长度不限）${s.password_set ? ` <span class="badge done">已设置</span>` : ""}</label><input name="password" type="password" autocomplete="new-password" placeholder="${s.password_set ? "留空保持不变" : "恢复时需要，丢失无法恢复"}">
    <label>再输一次</label><input name="password2" type="password" autocomplete="new-password">
    <p class="muted">备份文件用这个密码加密（scrypt + AES-256-GCM），OneDrive 上的文件没有密码打不开。为了无人值守定时运行，密码用面板的 Fernet 密钥加密后保存在本机数据库里。</p>
    <div class="bar" style="margin-top:8px"><button class="btn primary" id="odSavePlan">保存</button></div></div>
  <div class="card" id="odHelp"><h3>新装机恢复 / 离线解密</h3>
    <ol class="muted"><li>装好面板并登录</li><li>在本页填 client_id → 绑定 OneDrive（同一个 Microsoft 帐户）</li><li>下方备份列表里选一份 → 恢复 → 输入备份密码</li><li>面板自动重启，用备份时的面板密码重新登录</li></ol>
    <p class="muted">离线解密（不需要面板，只需 Python + cryptography）：</p><input class="mono" readonly onclick="this.select()" value="python -m tools.decrypt_backup tricloud-backup-xxxx.tcod 输出目录">
    <p class="muted">恢复前面板会自动在 data/ 下保存一份当前数据（pre-restore-时间）。</p></div></div>
  <div class="card" id="odList"><div class="bar"><h3 class="grow" style="margin:0">OneDrive 上的备份</h3>${s.bound ? `<button class="btn sm" id="odRefresh">刷新</button>` : ""}</div>
    <div id="odItems" class="muted">${s.bound ? `<span class="spin"></span> 读取中…` : "绑定后显示"}</div></div>`;
  odSchedBind($("#odPlan"));
  $("#odSaveApp").onclick = (e) => act(e.target, () => post("/onedrive/config", form($("#odApp"))),
    (r) => (r.changed.includes("unbound") ? "已保存；换了应用，原绑定已解除。点「绑定 OneDrive」获取代码" : !r.bound && r.client_id ? "已保存，点「绑定 OneDrive」获取代码" : "已保存"))
    .then((r) => r && pageOneDrive(!r.bound && !!r.client_id));
  $("#odSavePlan").onclick = (e) => {
    const pf = form($("#odPlan"));
    if (!pf.password && pf.password2) return toast("备份密码不能为空", true);
    if (pf.password && pf.password !== pf.password2) return toast("两次输入的备份密码不一致", true);
    const f = Object.assign(odSchedBody($("#odPlan")), { enabled: pf.enabled, keep: pf.keep });
    if (pf.password) Object.assign(f, { password: pf.password, password2: pf.password2 });
    act(e.target, () => post("/onedrive/config", f), "已保存").then((r) => r && pageOneDrive());
  };
  $("#odBind").onclick = (e) => act(e.target, async () => {
    if ($("#odApp [name=client_id]").value.trim() !== (s.client_id || "")) await post("/onedrive/config", form($("#odApp")));
    return post("/onedrive/bind");
  }).then((p) => p && showPending(p));
  if (s.pending) showPending(s.pending);
  $("#odNow").onclick = (e) => act(e.target, () => post("/onedrive/backup"), (r) => r.message).then((r) => r && setTimeout(pageOneDrive, 800));
  if ($("#odUnbind")) $("#odUnbind").onclick = async () => {
    if (!(await confirmBox("解绑 OneDrive", "将删除本机保存的 OneDrive 授权，定时备份停止。<br>OneDrive 上已有的备份文件<b>不会</b>删除，以后重新绑定还能恢复。确定解绑？", true))) return;
    const r = await act($("#odUnbind"), () => api("/onedrive/bind?confirm=true", { method: "DELETE" }), "已解绑");
    if (r) pageOneDrive();
  };
  if (s.bound) { loadList(); $("#odRefresh").onclick = loadList; }
}

// ---------------- build 23 计划编辑 ----------------
const odTimeRow = (t) => `<span class="od-time"><input type="time" value="${esc(t)}" data-odt><button type="button" class="btn sm" data-odrm title="删除这个时间">✕</button></span>`;
const odChip = (attr, v, label, on) => `<label class="od-chip"><input type="checkbox" ${attr}="${v}" ${on ? "checked" : ""}><span>${label}</span></label>`;

export function odSchedForm(c, tz) {
  const days = new Set(c.days || []), wds = new Set(c.weekdays || []);
  return `<label>频率（时间按面板时区 ${esc(tz || "")}）</label><select name="mode">${OD_MODES.map(([k, v]) => `<option value="${k}" ${c.mode === k ? "selected" : ""}>${v}</option>`).join("")}</select>
    <div data-show-when="mode=hourly"><div class="row2"><div><label>每隔几小时（1–24）</label><input name="every_hours" type="number" min="1" max="24" value="${esc(c.every_hours ?? 6)}"></div>
      <div><label>第几分钟（0 = 整点）</label><input name="minute" type="number" min="0" max="59" value="${esc(c.minute ?? 0)}"></div></div>
      <label>起始小时（0–23，每天从这个小时起按间隔对齐）</label><input name="start_hour" type="number" min="0" max="23" value="${esc(c.start_hour ?? 0)}">
      <p class="muted">例如每 6 小时、第 15 分、起始 0 点 = 每天 00:15、06:15、12:15、18:15。24 不能被间隔整除时，每天最后一段会短一些。</p></div>
    <div data-show-when="mode=daily|weekly|monthly"><label>时间点（可多个）</label><div class="od-times" id="odTimes">${(c.times && c.times.length ? c.times : ["03:30"]).map(odTimeRow).join("")}</div>
      <button type="button" class="btn sm" id="odAddTime">＋ 添加时间</button></div>
    <div data-show-when="mode=weekly"><label>星期（可多选）</label><div class="od-chips">${OD_WD.map((w, i) => odChip("data-odwd", i, w, wds.has(i))).join("")}</div></div>
    <div data-show-when="mode=monthly"><label>日期（可多选；没有这一天的月份会跳过，每月最后一天请选「月末」）</label>
      <div class="od-chips od-days">${Array.from({ length: 31 }, (_, i) => odChip("data-odday", i + 1, i + 1, days.has(i + 1))).join("")}${odChip("data-odlast", 1, "月末", !!c.last_day)}</div></div>
    <div data-show-when="mode=cron"><label>Cron 表达式（分 时 日 月 周）</label><input name="cron" class="mono" value="${esc(c.cron || "30 3 * * *")}" placeholder="30 3 * * 1-5" autocomplete="off" spellcheck="false">
      <p class="muted">标准 5 段，按面板时区；支持 <code>*</code> <code>,</code> <code>-</code> <code>/</code>、数字、英文缩写（mon、jan）和 @daily 等。例：<code>30 3 * * 1-5</code> 工作日 03:30；<code>0 */6 * * *</code> 每 6 小时；<code>0 4 1,15 * *</code> 每月 1、15 日 04:00。日和周都指定时满足任一即可。两次备份至少间隔 30 分钟。</p></div>
    <div class="od-prev" id="odPrev"><span class="muted">接下来 3 次：计算中…</span></div>`;
}

export function odSchedBody(root) {
  const mode = root.querySelector("[name=mode]").value, b = { mode };
  if (mode === "hourly") ["every_hours", "minute", "start_hour"].forEach((k) => (b[k] = root.querySelector(`[name=${k}]`).value));
  if (mode === "daily" || mode === "weekly" || mode === "monthly") b.times = [...root.querySelectorAll("[data-odt]")].map((i) => i.value).filter(Boolean);
  if (mode === "weekly") b.weekdays = [...root.querySelectorAll("[data-odwd]:checked")].map((i) => +i.dataset.odwd);
  if (mode === "monthly") { b.days = [...root.querySelectorAll("[data-odday]:checked")].map((i) => +i.dataset.odday); b.last_day = !!root.querySelector("[data-odlast]:checked"); }
  if (mode === "cron") b.cron = root.querySelector("[name=cron]").value.trim();
  return b;
}

async function odPreview(root) {
  const box = root.querySelector("#odPrev"); if (!box) return;
  const seq = ++odPrevSeq;
  let r;
  try { r = await post("/onedrive/schedule/preview", odSchedBody(root)); } catch (e) { r = { error: e.message }; }
  if (seq !== odPrevSeq || !document.body.contains(box)) return;
  box.innerHTML = r.error ? `<span class="err-text">⚠️ ${esc(r.error)}</span>`
    : `<b>${esc(r.desc)}</b><br><span class="muted">接下来 3 次（${esc(r.timezone)}）：</span>${r.next_runs_label.map((x) => `<br>· ${esc(x)}`).join("")}`;
}

export function odSchedBind(root) {
  const refresh = () => { applyShowWhen(root); clearTimeout(odPrevTimer); odPrevTimer = setTimeout(() => odPreview(root), 350); };
  root.addEventListener("change", refresh);
  root.addEventListener("input", (e) => { if (!e.target.matches("[name=password],[name=password2],[name=keep]")) refresh(); });
  root.addEventListener("click", (e) => {
    const rm = e.target.closest("[data-odrm]");
    if (rm) { const rows = root.querySelectorAll(".od-time"); if (rows.length <= 1) return toast("至少保留一个时间点", true); rm.parentElement.remove(); refresh(); }
  });
  root.querySelector("#odAddTime").onclick = () => {
    const box = root.querySelector("#odTimes");
    if (box.querySelectorAll(".od-time").length >= 24) return toast("最多 24 个时间点", true);
    box.insertAdjacentHTML("beforeend", odTimeRow("12:00")); refresh();
  };
  applyShowWhen(root); odPreview(root);
}

function showPending(p) {
  const box = $("#odPendBox"); if (!box) return;
  const url = p.verification_uri || OD_LOGIN_URL;
  box.innerHTML = `<div class="card" id="odPend" style="margin-top:12px"><p>1）打开 <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url.replace(/^https:\/\//, ""))}</a>（${esc(OD_LOGIN_URL.replace(/^https:\/\//, ""))}）</p>
    <p>2）输入代码：<b class="mono" style="font-size:1.4em;letter-spacing:2px" id="odCode">${esc(p.user_code)}</b> <button class="btn sm" id="odCopy">复制</button></p>
    <p>3）用要存备份的 Microsoft 帐户登录并同意授权</p><p class="muted" id="odPollMsg"><span class="spin"></span> 等待授权…（<span id="odLeft">${Math.ceil((p.expires_in || 900) / 60)}</span> 分钟内有效）</p>
    <div class="bar"><button class="btn sm" id="odCancel">取消</button></div></div>`;
  $("#odCopy").onclick = () => { try { navigator.clipboard.writeText(p.user_code); toast("已复制"); } catch (_) { toast("请手动复制", true); } };
  $("#odCancel").onclick = async () => { stopPoll(); await api("/onedrive/bind?pending_only=true", { method: "DELETE" }).catch(() => {}); box.innerHTML = ""; };
  let interval = Math.max(2, +p.interval || 5);
  const deadline = Date.now() + (p.expires_in || 900) * 1000;
  const tick = async () => {
    odTimer = null;
    if (!document.getElementById("odPend")) return;      // 离开页面就停止轮询
    let r;
    try { r = await post("/onedrive/bind/poll"); } catch (e) { r = { status: "error", message: e.message }; }
    if (!document.getElementById("odPend")) return;
    const left = $("#odLeft"); if (left) left.textContent = Math.max(0, Math.ceil((deadline - Date.now()) / 60000));
    if (r.status === "ok") { toast("OneDrive 已绑定"); return pageOneDrive(); }
    if (r.status === "pending" || r.status === "slow_down") { if (r.interval) interval = r.interval; odTimer = setTimeout(tick, interval * 1000); return; }
    $("#odPollMsg").innerHTML = `<span class="err-text">${esc(r.message || "绑定失败")}</span>`;
  };
  odTimer = setTimeout(tick, interval * 1000);
}

async function loadList() {
  const box = $("#odItems"); if (!box) return;
  box.innerHTML = `<span class="spin"></span> 读取中…`;
  let r;
  try { r = await api("/onedrive/backups"); } catch (e) { box.innerHTML = `<span class="err-text">${esc(e.message)}</span>`; return; }
  if (!document.getElementById("odItems")) return;
  box.classList.remove("muted");
  box.innerHTML = r.items.length ? `<table><tr><th>时间</th><th>大小</th><th>文件</th><th></th></tr>${r.items.map((it) => `<tr><td>${esc(it.time || it.created)}</td><td>${esc(fmtBytes(it.size))}</td>
    <td class="mono">${esc(it.name)}</td><td><button class="btn sm danger" data-odrs="${esc(it.id)}" data-odn="${esc(it.name)}">恢复</button></td></tr>`).join("")}</table>
    <p class="muted">共 ${r.items.length} 份，保留最近 ${esc(r.keep)} 份。</p>` : `<span class="muted">还没有备份，点「立即备份」试一次</span>`;
  box.querySelectorAll("[data-odrs]").forEach((b) => (b.onclick = () => restore(b.dataset.odrs, b.dataset.odn)));
}

async function restore(id, name) {
  const pw = await modal("从 OneDrive 恢复", `<p>备份：<b class="mono">${esc(name)}</b></p><p>⚠️ 当前全部数据（云账号、设置、任务、审计）将被这份备份覆盖。恢复前会自动在 data/ 下保存一份当前数据。</p>
    <label>这份备份的备份密码</label><input name="password" type="password" autocomplete="off">`, (bg) => { const v = form(bg).password; if (!v) throw new Error("请输入备份密码"); return v; }, "下一步", true);
  if (!pw) return;
  if (!(await confirmBox("确认恢复", `确定用 <b class="mono">${esc(name)}</b> 覆盖当前全部数据？<br>此操作会让所有设备重新登录，面板会自动重启。`, true))) return;
  const r = await act(null, () => post("/onedrive/restore", { item_id: id, password: pw, confirm: true }));
  if (!r) return;
  toast(r.message || "已恢复，请重新登录");
  setTimeout(() => (location.href = "/login"), r.restart ? 10000 : 1500);
}
