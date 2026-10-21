// TriCloud 前端 v1.6.0 · 任务页与任务抽屉（实时日志）
import { tr } from "./i18n.js";
import { $, act, api, confirmBox, del, esc, fmtDT, fmtTime, loading, post, view } from "./core.js";

// ---------------- 任务 ----------------
export async function pageTasks() {
  loading();
  const list = await api("/tasks");
  const TN = TASK_NAME;
  view.innerHTML = `<div class="bar"><button class="btn" id="rf">${tr("common.refresh")}</button><span class="muted">${tr("task.tgNote")}</span></div>
    <div class="card"><table><tr><th>#</th><th>${tr("common.type")}</th><th>${tr("common.account")}</th><th>${tr("common.status")}</th><th>${tr("task.col.attempts")}</th><th>${tr("task.col.info")}</th><th>${tr("task.col.updated")}</th><th></th></tr>
    ${list.map((t) => `<tr><td>${t.id}</td><td>${TN[t.type] ? tr(TN[t.type]) : esc(t.type)}</td><td>${esc(t.account_name || "-")}</td>
    <td><span class="badge ${esc(t.status)}">${esc(t.status)}</span></td><td>${t.attempts}</td><td class="mono">${esc(t.message)}</td>
    <td>${new Date(t.updated * 1000).toLocaleString()}</td>
    <td><button class="btn sm" data-log="${t.id}">${tr("task.logBtn")}</button> ${t.status === "running" ? `<button class="btn sm danger" data-stop="${t.id}">${tr("task.stopTitle")}</button>` : `<button class="btn sm" data-del="${t.id}">${tr("common.delete")}</button>`}</td></tr>`).join("") || `<tr><td colspan=8 class="muted">${tr("task.empty")}</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-log]").forEach((b) => (b.onclick = () => TaskDrawer.open(+b.dataset.log)));
  $("#rf").onclick = pageTasks;
  view.querySelectorAll("[data-stop]").forEach((b) => (b.onclick = async () => { await act(b, () => post(`/tasks/${b.dataset.stop}/stop`), tr("task.st.stopped")); pageTasks(); }));
  view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { await del(`/tasks/${b.dataset.del}`); pageTasks(); }));
  clearTimeout(window._tt);
  window._tt = setTimeout(() => { if (location.hash === "#/tasks") pageTasks(); }, 10000);
}

// ================= v1.4 新增 =================
export const TASK_NAME = { snatch: "task.name.snatch", change_ip: "task.name.change_ip", resize: "task.name.resize", ipv6: "task.name.ipv6", azure_create: "task.name.azure_create", ensure_network: "task.name.ensure_network",
  snapshot: "task.name.snapshot", migrate: "task.name.migrate", cf_delete: "task.name.cf_delete", reinstall: "task.name.reinstall", net500m: "task.name.net500m", foundry: "task.name.foundry",
  billing_keep: "task.name.billing_keep", aws_credit: "task.name.aws_credit", onedrive_backup: "task.name.onedrive_backup" };
export const TST = { running: "task.st.running", done: "task.st.done", failed: "task.st.failed", stopped: "task.st.stopped", interrupted: "task.st.interrupted" };

// ---------- 任务抽屉：提交任务后自动打开并跟踪，运行中每 2 秒刷新 ----------
export const TaskDrawer = {
  tid: null, last: 0, timer: null, task: null, stick: true,
  el: () => document.getElementById("tdrawer"),
  isOpen() { const d = this.el(); return !!(d && d.classList.contains("open")); },
  async open(tid) {
    const d = this.el(); if (!d) return;
    d.classList.add("open"); d.setAttribute("aria-hidden", "false"); document.body.classList.add("td-open");
    if (tid && tid !== this.tid) { this.tid = tid; this.last = 0; this.task = null; this.stick = true; $("#tdCur").innerHTML = `<div class="empty"><span class="spin"></span></div>`; }
    if (!this.tid) $("#tdCur").innerHTML = `<div class="muted td-hint">${tr("task.drawerHint")}</div>`;
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
      box.innerHTML = `<div class="td-task"><div class="td-title"><b>#${t.id} ${esc(t.type_name || (TASK_NAME[t.type] ? tr(TASK_NAME[t.type]) : t.type))}</b>
        <span class="badge ${esc(t.status)}" id="tdSt">${TST[t.status] ? tr(TST[t.status]) : esc(t.status)}</span></div>
        <div class="muted">${t.provider ? `<span class="dot ${t.provider}"></span> ` : ""}${esc(t.account_name || "-")}${t.params && t.params.name ? " · " + esc(t.params.name) : ""}
          · ${tr("task.createdAt", { t: fmtDT(t.created) })}</div>
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
    if (!log.children.length) log.innerHTML = `<div class="ll muted">${tr("task.noLogs")}</div>`;
    if (this.stick) log.scrollTop = log.scrollHeight;    // 自动滚到最底部（手动上翻时暂停）
    const st = box.querySelector("#tdSt"); st.className = "badge " + t.status; st.textContent = TST[t.status] ? tr(TST[t.status]) : t.status;
    box.querySelector("#tdMsg").textContent = (t.attempts > 1 ? tr("task.attempts", { n: t.attempts }) : "") + (t.message || "");
    const res = t.result && typeof t.result === "object" ? Object.entries(t.result).filter(([, v]) => v != null && v !== "" && !(Array.isArray(v) && !v.length)) : [];
    box.querySelector("#tdRes").innerHTML = res.length ? `<div class="kv">${res.map(([k, v]) => `<span>${esc(k)}</span><span class="mono">${esc(Array.isArray(v) ? v.join("；") : v)}</span>`).join("")}</div>` : "";
    const acts = box.querySelector("#tdActs");
    acts.innerHTML = (t.status === "running" ? `<button class="btn sm danger" id="tdStop">${tr("task.stopTitle")}</button>` : `<button class="btn sm" id="tdDel">${tr("task.delRecord")}</button>`)
      + `<span class="grow"></span><span class="muted">${t.status === "running" ? tr("task.autoRefresh") : tr("task.updatedAt", { t: fmtDT(t.updated) })}</span>`;
    const stop = acts.querySelector("#tdStop"), dl = acts.querySelector("#tdDel");
    if (stop) stop.onclick = async () => { if (await confirmBox(tr("task.stopTitle"), tr("task.stopConfirm", { id: t.id }), true)) { await act(stop, () => post(`/tasks/${t.id}/stop`), tr("task.st.stopped")); this.tick(false); } };
    if (dl) dl.onclick = async () => {
      if (!(await confirmBox(tr("task.delRecord"), tr("task.delConfirm", { id: t.id }), true))) return;
      await act(dl, () => del(`/tasks/${t.id}`), tr("common.deleted")); this.tid = null; this.task = null; this.last = 0; this.open();
      if (location.hash === "#/tasks") pageTasks();
    };
  },
  async renderList() {
    const list = await api("/tasks?limit=20");
    updateTaskBadge(list);
    $("#tdList").innerHTML = list.length ? list.map((t) => `<button class="td-item ${t.id === this.tid ? "on" : ""}" data-tid="${t.id}">
      <span class="badge ${esc(t.status)}">${TST[t.status] ? tr(TST[t.status]) : esc(t.status)}</span>
      <span class="ti-main"><b>#${t.id} ${TASK_NAME[t.type] ? tr(TASK_NAME[t.type]) : esc(t.type)}</b> <span class="muted">${esc(t.account_name || "")}</span>
      <span class="ti-msg">${esc(t.message || "")}</span></span><span class="muted ti-time">${fmtTime(t.updated)}</span></button>`).join("")
      : `<div class="empty">${tr("task.empty")}</div>`;
    $("#tdList").querySelectorAll("[data-tid]").forEach((b) => (b.onclick = () => this.open(+b.dataset.tid)));
  },
};
window.TaskDrawer = TaskDrawer;
export function updateTaskBadge(list) {
  const n = list.filter((t) => t.status === "running").length;
  const b = document.getElementById("taskCnt"); if (b) { b.textContent = n || ""; b.style.display = n ? "" : "none"; }
}
