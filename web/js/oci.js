// TriCloud 前端 v1.6.0 · OCI：创建 / 抢机、配额、安全组、存储、对象存储、流量、区域订阅、免费额度体检
import { $, ACCOUNTS, act, api, confirmBox, del, esc, fmtBytes, form, loading, modal, post, regionOf, regionSelect, rq, SETTINGS, toast, view } from "./core.js";
import { loginFields, portModeFields, portsOf, publicWarn, showCreated, trafficDialog } from "./instances.js";
import { GST } from "./monitors.js";
import { saveDefaultBtn } from "./settings.js";

// ---------------- OCI 创建 / 抢机 ----------------
// OCI 规格：标明是否 Always Free（免费额度只在主区域有效）
export const OCI_SHAPES = [
  ["VM.Standard.A1.Flex", "ARM · ✅ Always Free（免费号合计 2 OCPU / 12 GB，付费号 4 / 24）"],
  ["VM.Standard.E2.1.Micro", "AMD 1/8 OCPU · 1 GB · ✅ Always Free（最多 2 台）"],
  ["VM.Standard.E4.Flex", "AMD · 💰 付费，非 Always Free"],
  ["VM.Standard3.Flex", "Intel · 💰 付费，非 Always Free"],
];
export const ociShapeOpts = (cur, only) => OCI_SHAPES.filter(([v]) => !only || only.includes(v))
  .map(([v, t]) => `<option value="${v}" ${v === cur ? "selected" : ""}>${v} — ${t}</option>`).join("");
// v1.5：OCI「系统 / 系统版本」联动下拉。内置列表先显示，再按规格异步拉 /oci/os-versions 替换；"" = 最新（_pick_image 取最新镜像）
export const OCI_OS_VERSIONS = { "Canonical Ubuntu": ["24.04", "22.04", "20.04"], "Oracle Linux": ["9", "8"] };
export function ociOsOpts(cur) {
  const os = OCI_OS_VERSIONS[cur] ? cur : "Canonical Ubuntu";
  return Object.keys(OCI_OS_VERSIONS).map((s) => `<option ${s === os ? "selected" : ""}>${s}</option>`).join("");
}
export function ociVerOpts(os, cur, map) {
  const vs = ["", ...((map && map[os]) || OCI_OS_VERSIONS[os] || []).filter(Boolean)];
  if (cur && !vs.includes(cur)) vs.push(cur);   // 默认值里保存的版本不在列表里：临时加成一个选项
  return vs.map((v) => `<option value="${esc(v)}" ${v === (cur || "") ? "selected" : ""}>${v ? esc(v) : "最新"}</option>`).join("");
}
export const ociOsFields = (d) => `<div><label>系统</label><select name="os">${ociOsOpts(d.os)}</select></div>
    <div><label>系统版本</label><select name="os_version">${ociVerOpts(OCI_OS_VERSIONS[d.os] ? d.os : "Canonical Ubuntu", d.os_version || "")}</select></div>`;
// keep: "always" 保留当前值（不在列表里就临时加）；"present" 只在新列表里有时保留；其他 = 回到「最新」
export function refillOciVer(box, keep) {
  const os = box.querySelector("[name=os]"), sel = box.querySelector("[name=os_version]");
  if (!os || !sel) return;
  let cur = keep ? sel.value : "";
  const list = (box._osv && box._osv[os.value]) || OCI_OS_VERSIONS[os.value] || [];
  if (keep === "present" && cur && !list.includes(cur)) cur = "";
  sel.innerHTML = ociVerOpts(os.value, cur, box._osv);
}
export async function loadOciVersions(box, keep = "present") {
  const acc = box._ociAcc, shape = box.querySelector("[name=shape]");
  if (!acc || !shape) return;
  const req = (box._osvReq = (box._osvReq || 0) + 1);
  try {
    const m = await api(`/accounts/${acc.id}/oci/os-versions?shape=${encodeURIComponent(shape.value)}&${rq(acc)}`);
    if (req !== box._osvReq || !m || !Object.keys(m).length) return;
    box._osv = m; refillOciVer(box, keep);
  } catch (_) { /* 失败继续用内置列表 */ }
}
export function wireOciOs(box, acc) { if (!box) return; box._ociAcc = acc; loadOciVersions(box, "always"); }
document.addEventListener("change", (e) => {
  const box = e.target.closest && e.target.closest("[data-oci-os]");
  if (!box) return;
  if (e.target.name === "os") refillOciVer(box);
  else if (e.target.name === "shape") { box._osv = null; refillOciVer(box, "present"); loadOciVersions(box); }   // 换规格（A1=aarch64 / E2=x86）重新拉
});
export function ociCreateFields(d) {
  d = d || {};
  return `<div class="row2" data-oci-os>
    <div><label>实例名称</label><input name="name" value="${esc(d.name || "oci-" + Date.now().toString(36))}"></div>
    <div><label>规格</label><select name="shape">
      ${ociShapeOpts(d.shape)}</select></div>
    <div><label>OCPU（Flex）</label><input name="ocpus" type="number" min="1" value="${esc(d.ocpus || 4)}"></div>
    <div><label>内存 GB（Flex）</label><input name="memory_gb" type="number" min="1" value="${esc(d.memory_gb || 24)}"></div>
    <div><label>引导卷 GB</label><input name="disk_gb" type="number" min="47" value="${esc(d.disk_gb || 50)}"></div>
    ${ociOsFields(d)}
    <div><label>可用域（留空=第一个）</label><input name="ad" value="${esc(d.ad || "")}"></div></div>
    <label>子网 OCID（留空=自动选择公有子网）</label><input name="subnet_id" value="${esc(d.subnet_id || "")}">
    <label>SSH 公钥（可选）</label><textarea name="ssh_key" placeholder="ssh-ed25519 AAAA...">${esc(d.ssh_key || "")}</textarea>
    <label><input type="checkbox" name="ipv6" style="width:auto" ${d.ipv6 ? "checked" : ""}> 分配 IPv6（子网需已启用 IPv6）</label>
    <p class="muted">可用域填 auto = 抢机时每次轮换可用域。没有公有子网时会自动创建 VCN/子网/网关（默认仅放行 22）。</p>`;
}
export async function tabOciCreate(acc, box) {
  box.innerHTML = `<div class="bar">${await regionSelect(acc, () => tabOciCreate(acc, box))}<span class="muted">参数默认值可在「设置 → 默认创建参数」修改</span></div>
    <div class="card" id="f">${ociCreateFields(SETTINGS.default_create?.oci)}${await loginFields()}<div class="bar" style="margin-top:14px"><button class="btn primary" id="go">立即创建</button>${saveDefaultBtn("oci")}</div></div>`;
  wireOciOs($("[data-oci-os]", box), acc);
  $("#go", box).onclick = async (e) => { const r = await act(e.target, () => post(`/accounts/${acc.id}/oci/create`, { region: regionOf(acc), create: form($("#f", box)) })); if (r) showCreated(r); };
}
export async function tabOciSnatch(acc, box) {
  box.innerHTML = `<div class="bar">${await regionSelect(acc, () => tabOciSnatch(acc, box))}</div>
    <div class="card" id="f"><h3>自动抢机</h3><p class="muted">容量不足时按间隔持续重试，成功/失败/停止都会推送 Telegram。任务在本机后台运行，凭证不出服务器。</p>
    ${ociCreateFields(SETTINGS.default_create?.oci)}${await loginFields()}
    <label>同时为这些 OCI 账号各起一个任务（批量抢机）</label>
    <div class="chips">${ACCOUNTS.filter((a) => a.provider === "oci").map((a) => `<label class="chip"><input type="checkbox" data-acc="${a.id}" ${a.id === acc.id ? "checked" : ""} style="width:auto"> ${esc(a.name)}</label>`).join("")}</div>
    <div class="row2"><div><label>重试间隔（秒，≥30）</label><input name="interval" type="number" min="30" value="60"></div>
    <div><label>最大尝试次数（0=不限）</label><input name="max_attempts" type="number" min="0" value="0"></div></div>
    <div class="bar" style="margin-top:14px"><button class="btn primary" id="go">开始抢机</button><a class="btn" href="#/tasks">查看任务</a>${saveDefaultBtn("oci")}</div></div>`;
  wireOciOs($("[data-oci-os]", box), acc);
  $("#go", box).onclick = (e) => {
    const f = form($("#f", box));
    const { interval, max_attempts, ...create } = f;
    const account_ids = [...box.querySelectorAll("[data-acc]:checked")].map((x) => +x.dataset.acc);
    if (!account_ids.length) return toast("至少选择一个账号", true);
    act(e.target, () => post(`/accounts/${acc.id}/oci/snatch`, { region: regionOf(acc), interval, max_attempts, create, account_ids }),
      (r) => `已启动 ${r.task_ids.length} 个抢机任务：#${r.task_ids.join(", #")}`);
  };
}

// OCI 配额 / 网络
export async function tabOciLimits(acc, box) {
  const reload = () => tabOciLimits(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">刷新</button><button class="btn" id="net">自动创建网络</button></div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
  $("#rf", box).onclick = reload;
  $("#net", box).onclick = async (e) => {
    if (!(await confirmBox("自动创建网络", "新建 VCN（含 IPv6）、互联网网关、路由和公有子网，安全列表默认只放行 22 与 ICMP。确定？"))) return;
    act(e.target, () => post(`/accounts/${acc.id}/oci/network`, { region: regionOf(acc) }), (r) => `已创建任务 #${r.task_id}`);
  };
  box.appendChild(regionSubSection(acc));   // 页面最底部，默认折叠
  let r;
  try { r = await api(`/accounts/${acc.id}/oci/limits?${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#lb", box).innerHTML = `<div class="card"><h3>计算配额 · ${esc(r.region)}</h3><table><tr><th>项目</th><th>上限</th><th>已用</th><th>可用</th><th>免费剩余</th></tr>
    ${r.items.map((i) => `<tr><td>${esc(i.name)}</td><td>${i.limit}</td><td>${i.used ?? "-"}</td><td>${i.available ?? "-"}</td><td>${i.free == null ? "-" : `${i.free_left ?? "?"} / ${i.free}`}</td></tr>`).join("") || `<tr><td colspan=5 class="muted">无数据</td></tr>`}</table>
    <p class="muted">「上限」是 OCI 允许开的量，升级按量付费（PAYG）后会很大；「免费剩余」A1 按${r.a1_basis === "paid" ? "付费号 4 OCPU / 24GB" : r.a1_basis === "free" ? "免费号 2 OCPU / 12GB" : "免费号 2 OCPU / 12GB（未识别账号类型，可在「类型」里刷新）"}计算（2026-06 起免费号减半），E2.1.Micro 2 台，超出部分计费。可用量为 0 时抢机必然失败。</p></div>`;
}

// ---- OCI 安全组（独立标签页）：按规则内容删除、批量端口、对公网放行二次确认 ----
export const PUBLIC_CIDR = (c) => ["0.0.0.0/0", "::/0"].includes(String(c || "").replace(/\s/g, ""));
export async function tabOciSecGroup(acc, box) {
  const reload = () => tabOciSecGroup(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<select id="sgInst"><option value="">加载实例…</option></select>
    <button class="btn" id="sgRf">刷新</button><button class="btn primary" id="sgAdd" disabled>添加规则</button><span class="grow"></span>
    <span class="muted">规则作用于实例所在子网的安全列表（同子网实例共享）</span></div><div class="card" id="sgBox"><div class="empty">选择实例后显示安全规则</div></div>`;
  $("#sgRf", box).onclick = reload;
  let list = [];
  try { list = await api(`/accounts/${acc.id}/instances?kind=vm&${rq(acc)}`); } catch (e) { $("#sgBox", box).innerHTML = `❌ ${esc(e.message)}`; return; }
  const last = localStorage.getItem("tc_sg_" + acc.id);
  $("#sgInst", box).innerHTML = list.length ? list.map((i) => `<option value="${esc(i.id)}" ${i.id === last ? "selected" : ""}>${esc(i.name)} · ${esc(i.public_ip || i.state)}</option>`).join("")
    : `<option value="">该区域没有实例</option>`;
  const load = async () => {
    const iid = $("#sgInst", box).value;
    $("#sgAdd", box).disabled = !iid;
    if (!iid) return;
    localStorage.setItem("tc_sg_" + acc.id, iid);
    $("#sgBox", box).innerHTML = `<span class="spin"></span>`;
    let d;
    try { d = await api(`/accounts/${acc.id}/security-rules?instance_id=${encodeURIComponent(iid)}&${rq(acc)}`); }
    catch (e) { $("#sgBox", box).innerHTML = `❌ ${esc(e.message)}`; return; }
    const multi = d.lists.length > 1;
    const st = { dir: "all", q: "" };
    const many = d.rules.length > 10;
    $("#sgBox", box).innerHTML = `<div class="bar sgf"><span class="seg">${[["all", "全部"], ["ingress", "入站"], ["egress", "出站"]].map(([k, t]) => `<button class="btn sm${k === "all" ? " primary" : ""}" data-sgdir="${k}">${t}</button>`).join("")}</span>
      ${many ? `<input id="sgQ" class="sm" placeholder="筛选端口 / IP / 协议 / 描述" style="max-width:240px">` : ""}<span class="grow"></span><span class="muted" id="sgCnt"></span></div><div id="sgTbl"></div>`;
    const draw = () => {
      const q = st.q.trim().toLowerCase();
      const shown = d.rules.map((r, i) => [r, i]).filter(([r]) => (st.dir === "all" || r.direction === st.dir)
        && (!q || [r.port, r.cidr, r.protocol, r.desc, r.sl_name].some((x) => String(x ?? "").toLowerCase().includes(q))));
      $("#sgCnt", box).textContent = shown.length === d.rules.length ? `共 ${d.rules.length} 条` : `${shown.length} / ${d.rules.length} 条`;
      $("#sgTbl", box).innerHTML = `<table><tr><th>方向</th><th>协议</th><th>来源 / 目标</th><th>端口</th><th>描述</th>${multi ? "<th>安全列表</th>" : ""}<th></th></tr>
      ${shown.map(([r, i]) => `<tr><td>${r.direction === "ingress" ? "入站" : "出站"}</td><td>${esc(r.protocol)}</td>
      <td class="mono">${esc(r.cidr)}${PUBLIC_CIDR(r.cidr) && r.direction === "ingress" ? ` <span class="badge failed">公网</span>` : ""}</td><td class="mono">${esc(r.port)}</td>
      <td>${esc(r.desc)}</td>${multi ? `<td>${esc(r.sl_name)}</td>` : ""}<td><button class="btn sm danger" data-sgdel="${i}">删除</button></td></tr>`).join("")
      || `<tr><td colspan="7" class="muted">${d.rules.length ? "没有匹配的规则" : "没有规则"}</td></tr>`}</table>`;
    $("#sgTbl", box).querySelectorAll("[data-sgdel]").forEach((b) => (b.onclick = async () => {
      const r = d.rules[+b.dataset.sgdel];
      if (!(await confirmBox("删除规则", `删除${r.direction === "ingress" ? "入站" : "出站"} ${esc(r.protocol)} ${esc(r.cidr)} 端口 ${esc(r.port)}？${r.direction === "ingress" && r.port === "22" ? "<br>⚠️ 删除 22 端口规则可能导致无法 SSH 登录。" : ""}`, true))) return;
      const proto = { TCP: "tcp", UDP: "udp", ICMP: "icmp", ICMPv6: "icmpv6", "全部": "all" }[r.protocol] || String(r.protocol).toLowerCase();
      if (await act(b, () => api(`/accounts/${acc.id}/security-rules`, { method: "DELETE", body: { instance_id: iid, region: regionOf(acc) || undefined, sl_id: r.sl_id,
        direction: r.direction, protocol: proto, cidr: r.cidr, port_min: r.port_min, port_max: r.port_max } }), "已删除")) load();
    }));
    };
    box.querySelectorAll("[data-sgdir]").forEach((b) => (b.onclick = () => {
      st.dir = b.dataset.sgdir;
      box.querySelectorAll("[data-sgdir]").forEach((x) => x.classList.toggle("primary", x === b));
      draw();
    }));
    if (many) $("#sgQ", box).oninput = (e) => { st.q = e.target.value; draw(); };
    draw();
    $("#sgAdd", box).onclick = () => addRule(iid, d.lists);
  };
  const addRule = async (iid, lists) => {
    const v = await modal("添加安全规则", `<div class="row2"><div><label>方向</label><select name="direction"><option value="ingress">入站</option><option value="egress">出站</option></select></div>
      <div><label>协议</label><select name="protocol"><option value="tcp">TCP</option><option value="udp">UDP</option><option value="icmp">ICMP</option><option value="icmpv6">ICMPv6</option><option value="all">全部协议</option></select></div></div>
      <label>来源 CIDR（出站规则为目标 CIDR）</label><input name="cidr" placeholder="如 203.0.113.0/24；0.0.0.0/0 表示整个互联网">
      ${portModeFields()}
      ${lists.length > 1 ? `<label>安全列表</label><select name="sl_id">${lists.map((l) => `<option value="${esc(l.id)}">${esc(l.name)}</option>`).join("")}</select>` : ""}
      <label>描述（可选）</label><input name="description">
      <p class="muted">不支持对 0.0.0.0/0 一键放行全部端口（需要请到 OCI 控制台操作）。</p>`, (bg) => form(bg), "下一步");
    if (!v) return;
    const { port_mode, port_min, port_max, ...rest } = v;   // eslint-disable-line no-unused-vars
    const body = { instance_id: iid, region: regionOf(acc) || undefined, ...rest, ports: portsOf(v) };
    if (!body.ports) delete body.ports;
    if (PUBLIC_CIDR(v.cidr) && v.direction === "ingress") {
      const go = await publicWarn(v.cidr, body.ports ? `端口 <code>${esc(body.ports)}</code>` : "该协议", "我已了解，继续添加");
      if (!go) return;
      body.confirm_public = true;
    }
    const r = await act(null, () => post(`/accounts/${acc.id}/security-rules`, body));
    if (r) { toast(`已添加 ${r.added} 条${r.skipped ? `，跳过已存在 ${r.skipped} 条` : ""}`); load(); }
  };
  $("#sgInst", box).onchange = load;
  load();
}

// ---------- 6. OCI 存储（块存储卷 + 引导卷） ----------
export async function tabOciStorage(acc, box) {
  const reload = () => tabOciStorage(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">刷新</button><button class="btn primary" id="newVol">新建块存储卷</button><span class="grow"></span><span class="muted" id="used"></span></div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
  $("#rf", box).onclick = reload;
  let d, insts = [];
  try { [d, insts] = await Promise.all([api(`/accounts/${acc.id}/oci/volumes?${rq(acc)}`), api(`/accounts/${acc.id}/instances?kind=vm&${rq(acc)}`).catch(() => [])]); }
  catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  const iname = (id) => (insts.find((i) => i.id === id) || {}).name || (id ? id.slice(-10) : "-");
  $("#used", box).textContent = `已用 ${d.used_gb} / ${d.free_gb} GB（Always Free 合计含引导卷）`;
  $("#lb", box).innerHTML = `<div class="card"><h3>块存储卷（数据盘）</h3><table><tr><th>名称</th><th>大小</th><th>性能</th><th>挂载到</th><th>状态</th><th></th></tr>
    ${d.volumes.map((v) => `<tr data-v="${esc(v.id)}"><td>${esc(v.name)}</td><td>${v.size_gb} GB</td><td>${v.vpus_per_gb} VPU/GB</td><td>${v.attached_to ? esc(iname(v.attached_to)) + (v.device ? ` <span class="muted mono">${esc(v.device)}</span>` : "") : "未挂载"}</td><td>${esc(v.state)}</td>
    <td><button class="btn sm" data-upd="${esc(v.id)}">调整</button> ${v.attached_to ? `<button class="btn sm" data-det="${esc(v.attachment_id)}">卸载</button>` : `<button class="btn sm" data-att="${esc(v.id)}">挂载</button> <button class="btn sm danger" data-del="${esc(v.id)}">删除</button>`}</td></tr>`).join("") || `<tr><td colspan=6 class="muted">暂无块存储卷</td></tr>`}</table>
    <p class="muted">挂载方式为半虚拟化，系统内用 lsblk 查看新盘，首次使用需分区格式化。卸载前请先在系统内 umount。</p></div>
    <div class="card"><h3>引导卷（系统盘）</h3><table><tr><th>名称</th><th>大小</th><th>性能</th><th>状态</th></tr>${d.boot_volumes.map((b) => `<tr><td>${esc(b.name)}</td><td>${b.size_gb} GB</td><td>${b.vpus_per_gb} VPU/GB</td><td>${esc(b.state)}</td></tr>`).join("") || `<tr><td colspan=4 class="muted">暂无</td></tr>`}</table>
    <p class="muted">引导卷扩容在实例操作「引导卷」里，可勾选扩容后自动扩分区。</p></div>`;
  const op = (b, body, msg) => act(b, () => post(`/accounts/${acc.id}/oci/volumes`, { region: regionOf(acc) || undefined, ...body }), msg).then((r) => { if (r) { if (r.hint) toast(r.hint); reload(); } return r; });
  const instOpts = insts.map((i) => `<option value="${esc(i.id)}">${esc(i.name)}</option>`).join("");
  $("#newVol", box).onclick = async () => {
    const r = await modal("新建块存储卷", `<label>名称</label><input name="name" placeholder="data-1">
      <div class="row2"><div><label>大小 GB（最小 50）</label><input name="size_gb" type="number" min="50" value="50"></div>
      <div><label>性能 VPU/GB</label><select name="vpus_per_gb">${[0, 10, 20, 30, 60, 90, 120].map((v) => `<option ${v === 10 ? "selected" : ""} value="${v}">${v}${v === 0 ? "（低成本）" : v === 10 ? "（均衡，免费）" : ""}</option>`).join("")}</select></div></div>
      <label>创建后挂载到（可选，自动选同可用域）</label><select name="instance_id"><option value="">不挂载</option>${instOpts}</select>
      <p class="muted">${esc(`当前已用 ${d.used_gb} GB，Always Free 合计 ${d.free_gb} GB`)}</p>`, (bg) => post(`/accounts/${acc.id}/oci/volumes`, { op: "create", region: regionOf(acc) || undefined, ...form(bg) }), "创建");
    if (r) { toast(r.attach && r.attach.hint ? r.attach.hint : "已创建"); reload(); }
  };
  box.querySelectorAll("[data-att]").forEach((b) => (b.onclick = async () => {
    const r = await modal("挂载块存储卷", `<label>挂载到实例（需同一可用域）</label><select name="instance_id">${instOpts}</select>`, (bg) => post(`/accounts/${acc.id}/oci/volumes`, { op: "attach", region: regionOf(acc) || undefined, volume_id: b.dataset.att, ...form(bg) }), "挂载");
    if (r) { toast(r.hint || "已挂载"); reload(); }
  }));
  box.querySelectorAll("[data-det]").forEach((b) => (b.onclick = async () => { if (await confirmBox("卸载块存储卷", "请先在系统内 umount 并移除 /etc/fstab 条目，否则可能丢数据或开机失败。确定卸载？", true)) op(b, { op: "detach", attachment_id: b.dataset.det }); }));
  box.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (await confirmBox("删除块存储卷", "删除后数据无法恢复。确定？", true)) op(b, { op: "delete", volume_id: b.dataset.del, confirm: true }, "已删除"); }));
  box.querySelectorAll("[data-upd]").forEach((b) => (b.onclick = async () => {
    const v = d.volumes.find((x) => x.id === b.dataset.upd);
    const r = await modal(`调整 ${v.name}`, `<div class="row2"><div><label>扩容到 GB（只能变大）</label><input name="size_gb" type="number" min="${v.size_gb}" placeholder="${v.size_gb}"></div>
      <div><label>性能 VPU/GB</label><select name="vpus_per_gb">${[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120].map((x) => `<option ${x === v.vpus_per_gb ? "selected" : ""}>${x}</option>`).join("")}</select></div></div>
      ${v.attached_to ? `<label><input type="checkbox" name="grow" style="width:auto" checked> 扩容后通过 Run Command 让系统重新识别磁盘大小（分区需自行扩展）</label>` : ""}`,
      (bg) => post(`/accounts/${acc.id}/oci/volumes`, { op: "update", region: regionOf(acc) || undefined, volume_id: v.id, instance_id: v.attached_to, ...form(bg) }), "提交");
    if (r) { toast(r.grow ? `已提交；系统内：${r.grow.status === "ok" ? "已重新识别" : r.grow.message}` : "已提交"); reload(); }
  }));
}

// ---------- 18. OCI 对象存储 ----------
export async function tabOciObjects(acc, box, bucket, prefix = "") {
  const reload = () => tabOciObjects(acc, box, bucket, prefix);
  if (!bucket) {
    box.innerHTML = `<div class="bar">${await regionSelect(acc, () => tabOciObjects(acc, box))}<button class="btn" id="rf">刷新</button><button class="btn primary" id="nb">新建 Bucket</button><span class="grow"></span><span class="muted" id="ns"></span></div><div id="bkCard" class="card"><span class="spin"></span> 保号账单…</div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
    billingKeepCard(acc, $("#bkCard", box));
    $("#rf", box).onclick = reload;
    let d;
    try { d = await api(`/accounts/${acc.id}/oci/buckets?${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
    $("#ns", box).textContent = `命名空间 ${d.namespace} · Always Free 共 ${d.free_gb} GB`;
    $("#lb", box).innerHTML = `<div class="card"><table id="bkList"><tr><th>Bucket</th><th>大小</th><th>对象数</th><th>存储层</th><th>创建时间</th><th></th></tr>${d.buckets.map((b) => `<tr><td><a href="javascript:void 0" data-open="${esc(b.name)}">📁 ${esc(b.name)}</a></td>
      <td${b.error ? ` title="${esc(b.error)}"` : ""}>${b.size == null ? "—" : fmtBytes(b.size)}</td><td>${b.count == null ? "—" : esc(b.count)}</td><td>${tierLabel(b)}</td><td class="mono">${esc(b.created)}</td>
      <td><button class="btn sm" data-open="${esc(b.name)}">打开</button> <button class="btn sm danger" data-delb="${esc(b.name)}">删除</button></td></tr>`).join("") || `<tr><td colspan=6 class="muted">暂无 Bucket</td></tr>`}</table>
      ${d.buckets.length ? `<p class="muted">大小、对象数为 OCI 定期统计的近似值，可能有几小时延迟。</p>` : ""}</div>`;
    $("#nb", box).onclick = async () => {
      const r = await modal("新建 Bucket", `<label>名称（字母、数字、- _ .）</label><input name="name" placeholder="backup">
        <label><input type="checkbox" name="public" style="width:auto"> 公开读取（任何人知道链接都能下载对象，慎用）</label>`, (bg) => post(`/accounts/${acc.id}/oci/buckets`, { op: "create", region: regionOf(acc) || undefined, ...form(bg) }), "创建");
      if (r) { toast("已创建"); reload(); }
    };
    box.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => tabOciObjects(acc, box, b.dataset.open)));
    box.querySelectorAll("[data-delb]").forEach((b) => (b.onclick = async () => {
      if (await confirmBox("删除 Bucket", `删除「${esc(b.dataset.delb)}」？Bucket 需为空。`, true) && await act(b, () => post(`/accounts/${acc.id}/oci/buckets`, { op: "delete", region: regionOf(acc) || undefined, name: b.dataset.delb, confirm: true }), "已删除")) reload();
    }));
    return;
  }
  box.innerHTML = `<div class="bar"><button class="btn" id="back">← Bucket 列表</button><b class="mono">${esc(bucket)}/${esc(prefix)}</b><span class="grow"></span>
    <label class="btn primary" style="margin:0">上传文件<input type="file" id="up" multiple style="display:none"></label><button class="btn" id="rf">刷新</button></div><div id="lb"><div class="card"><span class="spin"></span></div></div>`;
  $("#back", box).onclick = () => (prefix ? tabOciObjects(acc, box, bucket, prefix.replace(/[^/]+\/$/, "")) : tabOciObjects(acc, box));
  $("#rf", box).onclick = reload;
  $("#up", box).onchange = async (e) => {
    for (const f of e.target.files) {
      if (f.size > 100 * 1024 * 1024) { toast(`${f.name} 超过 100MB，请用 OCI 控制台上传`, true); continue; }
      toast(`上传 ${f.name}…`);
      const r = await fetch(`/api/accounts/${acc.id}/oci/objects?bucket=${encodeURIComponent(bucket)}&name=${encodeURIComponent(prefix + f.name)}&${rq(acc)}`, { method: "PUT", body: f, credentials: "same-origin" });
      if (!r.ok) { const j = await r.json().catch(() => ({})); toast(`${f.name}：${j.detail || r.statusText}`, true); } else toast(`${f.name} 已上传`);
    }
    reload();
  };
  let d;
  try { d = await api(`/accounts/${acc.id}/oci/objects?bucket=${encodeURIComponent(bucket)}&prefix=${encodeURIComponent(prefix)}&${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#lb", box).innerHTML = `<div class="card"><table><tr><th>名称</th><th>大小</th><th>上传时间</th><th></th></tr>
    ${d.prefixes.map((p) => `<tr><td><a href="javascript:void 0" data-dir="${esc(p)}">📁 ${esc(p.slice(prefix.length))}</a></td><td>-</td><td>-</td><td></td></tr>`).join("")}
    ${d.objects.filter((o) => o.name !== prefix).map((o) => `<tr><td class="mono">${esc(o.name.slice(prefix.length))}</td><td>${fmtBytes(o.size)}</td><td class="mono">${esc(o.created)}</td>
      <td><button class="btn sm" data-dl="${esc(o.name)}">下载链接</button> <button class="btn sm danger" data-delo="${esc(o.name)}">删除</button></td></tr>`).join("")}
    ${!d.prefixes.length && !d.objects.length ? `<tr><td colspan=4 class="muted">空</td></tr>` : ""}</table>${d.next ? `<p class="muted">只显示前 200 个对象</p>` : ""}</div>`;
  box.querySelectorAll("[data-dir]").forEach((b) => (b.onclick = () => tabOciObjects(acc, box, bucket, b.dataset.dir)));
  box.querySelectorAll("[data-dl]").forEach((b) => (b.onclick = async () => {
    const r = await act(b, () => post(`/accounts/${acc.id}/oci/objects`, { op: "url", region: regionOf(acc) || undefined, bucket, name: b.dataset.dl, minutes: 60 }));
    if (r) modal("下载链接", `<p class="muted">预认证只读链接，${esc(r.expires)} 前有效，任何拿到链接的人都能下载。</p><input readonly value="${esc(r.url)}" onclick="this.select()"><div class="bar"><a class="btn primary" href="${esc(r.url)}" target="_blank" rel="noopener">打开</a></div>`, null, "关闭");
  }));
  box.querySelectorAll("[data-delo]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("删除对象", `删除「${esc(b.dataset.delo)}」？`, true) && await act(b, () => post(`/accounts/${acc.id}/oci/objects`, { op: "delete", region: regionOf(acc) || undefined, bucket, name: b.dataset.delo }), "已删除")) reload();
  }));
}

// ---------- 18b. 保号账单（仅 PAYG 升级号）：先检测已有存储（所有已订阅区域的 Bucket），标准层补足到约 11 GB，超出 10 GB 免费额度，每月约 $0.02–0.03 ----------
export const BK_TITLE = "一键生成保号账单";
const gib = (n) => `${((+n || 0) / 1024 ** 3).toFixed(2)} GiB`;
const gb1 = (v) => `${(+v || 0).toFixed(2)} GB`;
export function tierLabel(b) {
  const t = b.tier || (b.storage_tier === "Archive" ? "archive" : b.storage_tier === "Standard" ? (b.auto_tiering && b.auto_tiering !== "Disabled" ? "autotier" : "standard") : "unknown");
  return { standard: "标准", autotier: `标准 <span class="badge pending" title="开了自动分层：久未访问的对象会转到低频层">自动分层</span>`, archive: "归档", unknown: "—" }[t] || "—";
}
// 补足大小：11 − 已用，向上取 0.1，最小 0.5（与后端 fill_size_gb 一致）
export function bkFill(used, target = 11) { return Math.max(0.5, Math.ceil(Math.round((target - (+used || 0)) * 1e6) / 1e5) / 10); }
function bkScanHtml(s) {
  const head = `<div>标准层已用 <b id="bkStd">${gb1(s.standard_gb)}</b> / 免费 ${s.free_gb} GB <span class="muted">（${s.regions.length} 个区域 · ${s.buckets.length} 个 Bucket${s.cached ? ` · ${Math.round(s.age / 60)} 分钟前检测` : ""}）</span>
    <button class="btn sm" id="bkRescan">重新检测</button></div>`;
  const verdict = s.over_free
    ? `<p id="bkVerdict" class="al warn">✅ 已满足：标准层已超出 10 GB 免费额度，已经会产生小额账单，无需生成。</p>`
    : `<p id="bkVerdict" class="al">还差 <b>${s.short_gb} GB</b> 才超出 10 GB 免费额度；建议补足 <b>${s.fill_gb} GB</b>，补足后标准层合计约 <b>${(s.standard_gb + s.fill_gb).toFixed(2)} GB</b>。</p>`;
  const extra = [s.autotier_gb > 0 ? `另有 ${gb1(s.autotier_gb)} 在开了自动分层的标准层 Bucket 里（久未访问的对象会转低频层，未计入标准层）` : "",
    s.archive_gb > 0 ? `归档层 ${gb1(s.archive_gb)}（归档层单独计免费额度，不计入标准层）` : "",
    s.unknown_count ? `${s.unknown_count} 个 Bucket 读不到大小（显示 —，未计入）` : "",
    (s.errors || []).length ? `部分区域读取失败：${s.errors.map((e) => esc(e.region)).join("、")}` : "",
    s.compartments_truncated ? `区间太多，只检测了前 ${s.compartments} 个` : ""].filter(Boolean);
  const rows = s.buckets.map((b) => `<tr><td class="mono">${esc(b.name)}${b.billing_keep ? ` <span class="badge">保号</span>` : ""}</td><td class="mono">${esc(b.region)}</td><td>${tierLabel(b)}</td>
    <td>${b.size == null ? "—" : fmtBytes(b.size)}</td><td>${b.count == null ? "—" : esc(b.count)}</td></tr>`).join("");
  return head + verdict + (extra.length ? `<p class="muted">${extra.join("；")}。</p>` : "")
    + (rows ? `<details id="bkBuckets"><summary>已有 Bucket（${s.buckets.length}）</summary><table><tr><th>Bucket</th><th>区域</th><th>存储层</th><th>大小</th><th>对象数</th></tr>${rows}</table></details>` : `<p class="muted">没有找到已有 Bucket。</p>`)
    + `<p class="muted">大小为 OCI 定期统计的近似值（approximateSize），刚上传的数据可能要几小时后才计入。</p>`;
}
export async function billingKeepCard(acc, el, again, rescan) {
  if (!el || !el.isConnected) return;
  const reload = (rs) => billingKeepCard(acc, el, true, rs);
  let d;
  try { d = await api(`/accounts/${acc.id}/oci/billing-keep`); } catch (e) { el.innerHTML = `<h3>${BK_TITLE}</h3><div>❌ ${esc(e.message)}</div>`; return; }
  if (!el.isConnected) return;
  const t = d.task, running = t && t.status === "running";
  const head = `<h3>${BK_TITLE} <span class="badge">${d.plan === "paid" ? "PAYG" : d.plan === "free" ? "免费号" : "类型未知"}</span></h3>`;
  if (!d.eligible) { el.innerHTML = `${head}<p class="muted" id="bkHint">${esc(d.hint || "")}</p>`; return; }
  let body = `<p class="muted" id="bkNote">${esc(d.note)}</p>`;
  if (running) {
    const pct = t.total ? Math.floor((t.uploaded * 100) / t.total) : 0;
    body += `<div id="bkProg"><progress max="100" value="${pct}" style="width:100%"></progress>
      <div>上传中：${gib(t.uploaded)} / ${gib(t.total)}（${pct}%） · <a href="javascript:void 0" id="bkTask">任务 #${t.id}</a></div></div>`;
    el.innerHTML = head + body;
    const tl = $("#bkTask", el); if (tl) tl.onclick = () => window.TaskDrawer && window.TaskDrawer.open(t.id);
    el.dataset.wasRunning = "1";
    setTimeout(() => billingKeepCard(acc, el, true), again ? 3000 : 2000);
    return;
  }
  // 先检测已有存储（上传刚结束或点了「重新检测」时跳过 5 分钟缓存）
  const fresh = rescan || el.dataset.wasRunning === "1";
  delete el.dataset.wasRunning;
  el.innerHTML = head + body + `<div id="bkScan"><span class="spin"></span> 正在检测已有存储…</div>`;
  let s = null, scanErr = "";
  try { s = await api(`/accounts/${acc.id}/oci/billing-keep/scan${fresh ? "?refresh=true" : ""}`); } catch (e) { scanErr = e.message; }
  if (!el.isConnected) return;
  const scanHtml = s ? bkScanHtml(s) : `<p class="al warn">⚠️ 检测已有存储失败：${esc(scanErr)}。无法确认标准层已用量，默认按 ${d.default_gb} GB 生成。</p><button class="btn sm" id="bkRescan">重新检测</button>`;
  const over = !!(s && s.over_free), used = s ? +s.standard_gb : 0, defGb = s ? s.fill_gb : d.default_gb;
  if (d.exists) {
    body += `<div id="bkDone">✅ 已存在保号对象 <span class="mono">${esc(d.bucket)}/${esc(d.object)}</span>：<b>${gib(d.size)}</b>（${esc(d.region)} · ${esc(d.storage_tier || "Standard")}）</div>
      <div id="bkScan">${scanHtml}</div><div class="bar"><button class="btn danger" id="bkDel">删除</button></div>`;
  } else {
    const pend = (d.pending_uploads || []).length, resumable = pend && t && ["failed", "stopped", "interrupted"].includes(t.status) && t.uploaded;
    body += `<div id="bkScan">${scanHtml}</div>` + (t && t.status !== "done" ? `<p class="muted">上次任务 #${t.id}：${esc(t.status)} · ${esc(t.message || "")}</p>` : "")
      + `<div class="bar"><label style="margin:0">大小 GB</label><input id="bkSize" type="number" step="0.1" min="${d.min_gb}" max="${d.max_gb}" value="${defGb}" style="width:6em">
      <button class="btn ${over ? "" : "primary"}" id="bkGo">${resumable ? `继续上传（已传 ${gib(t.uploaded)}）` : over ? "仍要生成" : "生成保号账单"}</button>
      ${pend ? `<button class="btn danger" id="bkDel">删除未完成的上传</button>` : ""}<span class="muted" id="bkAfter"></span></div>`;
  }
  el.innerHTML = head + body;
  const rs = $("#bkRescan", el); if (rs) rs.onclick = () => reload(true);
  const sz = $("#bkSize", el), after = $("#bkAfter", el);
  const upd = () => { if (after && s) after.textContent = `补足后标准层合计约 ${(used + (+sz.value || 0)).toFixed(2)} GB`; };
  if (sz) { sz.addEventListener("input", upd); upd(); }
  const go = $("#bkGo", el);
  if (go) go.onclick = async () => {
    const size = +sz.value || defGb;
    if (!(size >= d.min_gb && size <= d.max_gb)) { toast(`大小范围 ${d.min_gb}–${d.max_gb} GB`, true); return; }
    if (over && !(await confirmBox("无需生成", `标准层已用 ${gb1(used)}，已超出 10 GB 免费额度，已经会产生小额账单，<b>无需生成</b>。<br>再生成会让账单变多，仍要继续？`, true))) return;
    const tot = s ? `，补足后标准层合计约 <b>${(used + size).toFixed(2)} GB</b>` : "";
    if (!(await confirmBox(BK_TITLE, `${esc(d.note)}<br><br>本次大小：<b>${size} GB</b>${tot}（标准层超出 10 GB 的部分按量计费）。删除对象即停止计费。确认开始？`))) return;
    const r = await act(go, () => post(`/accounts/${acc.id}/oci/billing-keep`, { size_gb: size, confirm: true }));
    if (r) { if (r.existed) toast(`对象已存在：${gib(r.size)}，未重复上传`); reload(); }
  };
  const dl = $("#bkDel", el);
  if (dl) dl.onclick = async () => {
    if (!(await confirmBox("删除保号对象", "删除 tricloud-billing-keep 里的保号对象并中止未完成的上传（Bucket 空了一并删除）？之后不再产生这笔账单。", true))) return;
    if (await act(dl, () => del(`/accounts/${acc.id}/oci/billing-keep?confirm=true`), "已删除")) reload(true);
  };
}

// ---------- OCI 流量：本区域实例本月出站 / 入站（OCI Monitoring，免费） ----------
export async function tabOciTraffic(acc, box) {
  const reload = () => tabOciTraffic(acc, box);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload)}<button class="btn" id="rf">刷新</button><span class="grow"></span><span class="muted" id="pd"></span></div><div id="lb"><div class="card"><span class="spin"></span> 正在读取各实例流量…</div></div>`;
  $("#rf", box).onclick = reload;
  let d, gs = [];
  try { gs = (await api("/traffic-guards")).filter((g) => g.account_id === acc.id); } catch (_) { /* ignore */ }
  try { d = await api(`/accounts/${acc.id}/oci/traffic-summary?${rq(acc)}`); } catch (e) { $("#lb", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#pd", box).textContent = `统计 ${d.period}（UTC）`;
  const pct = d.free_out_gb ? Math.min(100, (d.out_gb / d.free_out_gb) * 100) : 0;
  const gb = (v) => (v == null ? "-" : v >= 1024 ? `${(v / 1024).toFixed(2)} TB` : `${(+v).toFixed(2)} GB`);
  $("#lb", box).innerHTML = `<div class="card"><p>本区域本月出站 <b>${gb(d.out_gb)}</b> / 免费 ${gb(d.free_out_gb)}（${pct.toFixed(pct < 1 ? 2 : 1)}%），入站 ${gb(d.in_gb)}（入站不计费）。</p>
      <div class="meter"><i style="width:${pct}%" class="${pct >= 100 ? "bad" : pct >= 80 ? "warn" : ""}"></i></div>
      <p class="muted">10TB 免费出站按整个租户所有区域合计；数据来自 OCI Monitoring，有 5~15 分钟延迟。需要超量提醒或自动停机，在下表给实例设置「流量守护」。</p></div>
    <div class="card"><table><tr><th>实例</th><th>状态</th><th>公网 IP</th><th>本月出站</th><th>本月入站</th><th>流量守护</th><th></th></tr>
    ${d.items.map((r, i) => `<tr><td>${esc(r.name)}<div class="muted mono" style="font-size:11px">${esc(r.shape || "")}</div></td><td>${esc(r.state || "")}</td><td class="mono">${esc(r.public_ip || "-")}</td>
      <td>${r.error ? `<span class="muted" title="${esc(r.error)}">读取失败</span>` : `<b>${gb(r.out_gb)}</b>`}</td><td>${r.error ? "-" : gb(r.in_gb)}</td>
      <td>${guardCell(gs.find((g) => g.instance_id === r.id))}</td>
      <td>${(() => { const g = gs.find((x) => x.instance_id === r.id); return g ? `<button class="btn sm" data-tg="${i}">编辑</button> <button class="btn sm" data-tgchk="${g.id}">立即检查</button> <button class="btn sm danger" data-tgdel="${g.id}">删除</button>` : `<button class="btn sm" data-tg="${i}">设置守护</button>`; })()}</td></tr>`).join("") || `<tr><td colspan=7 class="muted">本区域没有实例</td></tr>`}</table></div>`;
  box.querySelectorAll("[data-tg]").forEach((b) => (b.onclick = () => trafficDialog(acc, d.items[+b.dataset.tg], "vm", reload)));
  box.querySelectorAll("[data-tgchk]").forEach((b) => (b.onclick = () => act(b, () => post(`/traffic-guards/${b.dataset.tgchk}/check`), "已检查").then(reload)));
  box.querySelectorAll("[data-tgdel]").forEach((b) => (b.onclick = async () => {
    if (await confirmBox("删除规则", "删除这台实例的流量守护？", true)) act(b, () => api(`/traffic-guards/${b.dataset.tgdel}`, { method: "DELETE" }), "已删除").then(reload);
  }));
}
export function guardCell(g) {
  if (!g) return `<span class="muted">未设置</span>`;
  const st = `<span class="badge ${GST[g.status] || ""}">${esc(g.enabled ? g.status_text || "正常" : "已关闭")}</span>`;
  return `${st} <span class="muted">${g.last_gb ?? "-"} / ${g.limit_gb} GB${g.action === "stop" ? " · 超限停机" : " · 只推送"}</span>`;
}

// ---------- 7. OCI 区域订阅（v1.6 build 18：不再单独占标签，收在「配额/网络」页底部默认折叠的「高级」区，展开才加载） ----------
// 订阅不可撤销：确认框之后还要手动输入区域标识（如 ap-osaka-1）才能提交，防止误点
export const REGION_SUB_TITLE = "高级 · 区域订阅（不可撤销）";
export function regionSubSection(acc) {
  const el = document.createElement("details");
  el.className = "card rsadv"; el.id = "rsAdv";
  el.innerHTML = `<summary>${REGION_SUB_TITLE}</summary><div id="rsBody"><p class="muted">展开后加载区域列表。</p></div>`;
  let loaded = false;
  el.addEventListener("toggle", () => { if (el.open && !loaded) { loaded = true; tabOciRegionSub(acc, el.querySelector("#rsBody")); } });
  return el;
}
export function typeKeyConfirm(name, key) {
  // 必须手动输入完整的区域标识（如 ap-osaka-1，即列表里的「区域」列），一致后「确认订阅」才可点
  return modal("再次确认：订阅区域", `<p>订阅 <b>${esc(name)}</b>（${esc(key)}）后<b>无法取消</b>。请手动输入区域标识 <code class="mono">${esc(name)}</code> 以确认：</p>
    <input name="rskey" id="rsKey" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${esc(name)}">`,
  (bg) => {
    if (bg.querySelector("#rsKey").value.trim() !== name) { toast("输入的区域标识不一致", true); return false; }
    return true;
  }, "确认订阅", true, (bg) => {
    const ok = bg.querySelector("[data-ok]"), inp = bg.querySelector("#rsKey");
    ok.disabled = true;
    inp.addEventListener("input", () => { ok.disabled = inp.value.trim() !== name; });
    setTimeout(() => inp.focus());
  });
}
export async function tabOciRegionSub(acc, box) {
  const reload = () => tabOciRegionSub(acc, box);
  box.innerHTML = `<div><span class="spin"></span></div>`;
  let d;
  try { d = await api(`/accounts/${acc.id}/oci/region-subscriptions`); } catch (e) { box.innerHTML = `<div>❌ ${esc(e.message)}</div>`; return; }
  const subd = d.regions.filter((r) => r.subscribed);
  box.innerHTML = `<h3>已订阅 ${subd.length} 个区域 · 主区域 ${esc(d.home || "-")}</h3>
    <p class="muted">${esc(d.limit_hint)}。订阅<b>不可撤销</b>，订阅后可在顶部区域下拉里切换。</p>
    <table><tr><th>区域</th><th>Key</th><th>状态</th><th></th></tr>${d.regions.map((r) => `<tr><td>${esc(r.name)}${r.home ? ` <span class="badge done">主区域</span>` : ""}</td><td class="mono">${esc(r.key)}</td>
      <td>${r.subscribed ? esc(r.status || "已订阅") : `<span class="muted">未订阅</span>`}</td><td>${r.subscribed ? "" : `<button class="btn sm danger" data-sub="${esc(r.key)}" data-n="${esc(r.name)}">订阅</button>`}</td></tr>`).join("")}</table>`;
  box.querySelectorAll("[data-sub]").forEach((b) => (b.onclick = async () => {
    if (!(await confirmBox("订阅区域", `订阅 ${esc(b.dataset.n)}（${esc(b.dataset.sub)}）？<br>⚠️ 订阅后<b>无法取消</b>，免费账号的额外区域名额通常只有 1 个；Always Free 资源仍只在主区域。`, true))) return;
    if (!(await typeKeyConfirm(b.dataset.n, b.dataset.sub))) return;
    if (await act(b, () => post(`/accounts/${acc.id}/oci/region-subscriptions`, { region_key: b.dataset.sub, confirm: true }), (r) => `已提交订阅：${r.region}（${r.status}），几分钟后生效`)) reload();
  }));
}

// ---------- 20. 免费额度体检 ----------
export async function pageFreeCheck() {
  loading();
  const list = await api("/oci/free-check");
  const bar = (v, max) => `<span class="${v > max ? "bad" : ""}">${v ?? "-"} / ${max}</span>`;
  view.innerHTML = `<div class="card"><p class="muted">逐个检查 OCI 账号（主区域 / 默认区域）的 A1、E2.1.Micro、块存储用量是否超出 Always Free。只给建议，降配需要你确认后才执行（只降不升，不会删实例）。A1 免费额度：免费号 2 OCPU / 12 GB（2026-06 起），付费号仍为 4 OCPU / 24 GB。</p>
    <table><tr><th>账号</th><th>A1 OCPU</th><th>A1 内存 GB</th><th>Micro 台数</th><th>块存储 GB</th><th>结论</th></tr>
    ${list.map((r) => r.error ? `<tr><td>${esc(r.name)}</td><td colspan=5 class="muted">❌ ${esc(r.error)}</td></tr>` : `<tr><td><a href="#/oci/${r.account_id}">${esc(r.name)}</a></td>
      <td>${bar(r.a1.ocpus, r.a1.limit_ocpus)}</td><td>${bar(r.a1.memory_gb, r.a1.limit_mem)}</td><td>${bar(r.micro.count, r.micro.limit)}</td><td>${bar(r.storage.used_gb, r.storage.limit)}</td>
      <td>${r.ok ? `<span class="badge done">都在免费额度内</span>` : r.issues.map((x) => `<div class="bad">${esc(x)}</div>`).join("")}
      ${r.suggestions.map((s) => `<div class="muted">${esc(s.name)}：${s.ocpus}C/${s.memory_gb}G → ${s.delete ? "额度已用完，建议停用或删除" : `${s.to_ocpus}C/${s.to_memory_gb}G`}
        ${s.delete ? "" : `<button class="btn sm" data-down='${esc(JSON.stringify({ acc: r.account_id, ...s }))}'>降配</button>`}</div>`).join("")}</td></tr>`).join("") || `<tr><td colspan=6 class="muted">没有启用中的 OCI 账号</td></tr>`}</table></div>`;
  view.querySelectorAll("[data-down]").forEach((b) => (b.onclick = async () => {
    const s = JSON.parse(b.dataset.down);
    if (!(await confirmBox("降配", `把「${esc(s.name)}」从 ${s.ocpus}C/${s.memory_gb}G 降到 ${s.to_ocpus}C/${s.to_memory_gb}G？实例可能会重启。`))) return;
    act(b, () => post(`/accounts/${s.acc}/instances/resize`, { instance_id: s.id, name: s.name, ocpus: s.to_ocpus, memory_gb: s.to_memory_gb, confirm_overage: true }), (r) => `已创建任务 #${r.task_id}`);
  }));
}
