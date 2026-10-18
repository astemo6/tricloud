// TriCloud 前端 v1.6.0 · 账号页框架与实例：列表 / 卡片 / 表格、实例操作、开放端口与安全组弹窗、迁移、流量守护弹窗、v1.6 实例弹窗（重装 / 附加 IP / IP 质量 / 500M / 磁盘 / Lightsail 防火墙）
import { agentLine, guardAgentDialog, guardPortsDialog } from "./guard.js";
import { $, ACCOUNTS, act, api, confirmBox, ensureLsRegion, ensureMachineRegion, esc, form, instView, isDesktop, lastModal, modal, NO_CHANGE_IP, NO_CREATE, NOREG, OP_NAMES, PNAME, post, regionLabel, regionOf, regionSelect, rq, TAB_FNS_EXTRA, TABS, toast, TRAFFIC_DIALOG, view } from "./core.js";
import { ociOsFields, ociShapeOpts, PUBLIC_CIDR, tabOciCreate, tabOciLimits, tabOciObjects, tabOciSecGroup, tabOciSnatch, tabOciStorage, tabOciTraffic, wireOciOs } from "./oci.js";
import { ec2Create, lightsailCreate, tabAwsCredit, tabAwsRegions, tabCloudFront, tabLightsailV16, tabQuota, tabRecycle } from "./aws.js";
import { tabAzCreate, tabAzFoundry, tabAzQuota, tabAzRgs, tabAzSubscription } from "./azure.js";
import { tabBilling } from "./billing.js";
import { bindDns } from "./settings.js";

// ---------------- 账号页 ----------------
// 标签栏横向滚动：切换标签重绘后，恢复原来的滚动位置，并保证选中的标签可见（手机上标签较多时会横向滚动）
export const TAB_SCROLL = {};
export function keepTabVisible(bar, key, prev) {
  if (!bar) return;
  bar.scrollLeft = prev;
  const on = bar.querySelector("a.on");
  if (on) {
    const l = on.offsetLeft - bar.offsetLeft, r = l + on.offsetWidth;
    if (l < bar.scrollLeft) bar.scrollLeft = Math.max(0, l - 24);
    else if (r > bar.scrollLeft + bar.clientWidth) bar.scrollLeft = r - bar.clientWidth + 24;
  }
  TAB_SCROLL[key] = bar.scrollLeft;
  bar.addEventListener("scroll", () => { TAB_SCROLL[key] = bar.scrollLeft; }, { passive: true });
}
// 不按区域显示的标签（与 App 顶部区域按钮的排除列表一致）
export const NO_REGION_TABS = ["cloudfront", "quota", "billing", "subscription", "regions", "credit"];
export async function pageAccount(acc, tab) {
  const tabs = `<div class="tabs">${TABS[acc.provider].map(([k, l]) =>
    `<a href="#/${acc.provider}/${acc.id}/${k}" class="${k === tab ? "on" : ""}">${l}</a>`).join("")}</div>`;
  const prevScroll = TAB_SCROLL[acc.provider] || 0;
  view.innerHTML = tabs + `<div id="tab"></div>`;
  keepTabVisible(view.querySelector(".tabs"), acc.provider, prevScroll);
  const box = $("#tab");
  // build 25：默认选中有机器的区域 —— 还没有区域记录时先查一次总览（有缓存，最多等 8 秒）
  if (!NOREG(acc) && !NO_REGION_TABS.includes(tab) && !acc.machine_regions && !localStorage.getItem("tc_region_" + acc.id) && !acc.disabled) {
    box.innerHTML = `<div class="empty"><span class="spin"></span> 正在定位有机器的区域…</div>`;
    await ensureMachineRegion(acc);
    if (!box.isConnected) return;
  }
  const fn = {
    instances: tabInstances, ec2: tabInstances, vms: tabInstances, lightsail: tabLightsailV16,
    storage: tabOciStorage, objects: (a, b) => tabOciObjects(a, b), traffic: tabOciTraffic,
    create: tabOciCreate, snatch: tabOciSnatch, cloudfront: tabCloudFront, quota: tabQuota, recycle: tabRecycle, billing: tabBilling,
    limits: tabOciLimits, regions: tabAwsRegions, azcreate: tabAzCreate, rgs: tabAzRgs, azquota: tabAzQuota,
    subscription: tabAzSubscription, secgroup: tabOciSecGroup, foundry: tabAzFoundry, credit: tabAwsCredit,
  }[tab] || TAB_FNS_EXTRA[tab];
  await fn(acc, box);
}

export function instOps(acc, kind) {
  const ops = [["start", "启动"], ["stop", acc.provider === "azure" ? "停止(释放)" : "停止"], ["reboot", "重启"], ["changeip", "换 IP"]];
  if (acc.provider === "oci") ops.push(["ipv6", "加 IPv6"], ["delipv6", "删 IPv6"], ["resize", "改配置"], ["rename", "改名"], ["bootvol", "引导卷"],
    ["security", "安全列表"]);
  else if (kind !== "lightsail") ops.push(["rename", "改名"]);   // v1.5：Azure / AWS EC2 也可改名（Lightsail 不支持改名）
  if (kind !== "lightsail") ops.push(["openport", "开放端口"]);   // v1.5：三家云都有（来源 0.0.0.0/0，二次确认）
  if (acc.provider !== "oci") ops.push(["traffic", "流量守护"]);   // OCI 的流量守护统一在「流量」标签里管理
  if (acc.provider === "azure") ops.push(["resize", "改大小"]);
  if (kind !== "lightsail") ops.push(["migrate", "迁移"]);
  ops.push(["dns", "绑定域名"], ["monitor", "监控"], ["terminate", acc.provider === "azure" || kind === "lightsail" ? "删除" : "终止"]);
  return v16Ops(acc, kind, ops);   // v1.6：附加 IP / 500M / 磁盘 / 防火墙 / IP 质量 / 重装系统
}
// v1.5：改名同步主机名 —— 只通过云厂商 Run Command 执行固定命令，不走 SSH
export const RENAME_HOSTNAME_TIP = "Azure 直接生效；OCI 需开启 Oracle Cloud Agent 的 Run Command 插件；AWS 需 SSM 托管；重新登录 SSH 后可见。";
export function renameResult(r) {
  const h = r && r.hostname;
  if (!h || h.status === "ok") return toast(h ? "已改名，系统主机名已同步" : "已改名");
  if (h.status === "pending") return toast(`已改名。${h.message || "主机名同步已下发"}`);
  if (!h.manual_cmd) return toast(`已改名。主机名未同步：${h.message || ""}`, h.status === "failed");
  modal(h.status === "failed" ? "已改名，主机名同步失败" : "已改名，主机名未自动同步",
    `<p>${esc(h.message || "")}</p><p class="muted">可 SSH 登录后手动执行：</p>
    <textarea id="hnCmd" readonly rows="4" class="mono" onclick="this.select()">${esc(h.manual_cmd)}</textarea>
    <button class="btn sm" id="hnCopy">复制命令</button>`, null, "知道了");
  const b = document.getElementById("hnCopy");
  if (b) b.onclick = async () => {
    const t = document.getElementById("hnCmd");
    try { await navigator.clipboard.writeText(t.value); toast("已复制"); } catch (_) { t.select(); document.execCommand("copy"); toast("已复制"); }
  };
}
export function instCard(acc, i, kind) {
  const ip6 = (i.ipv6 || []).join("<br>") || "-";
  const extra = [];
  if (acc.provider === "oci") extra.push(["配置", `${esc(i.shape)} ${i.ocpus ?? ""}C/${i.memory_gb ?? ""}G`]);
  else extra.push(["规格", esc(i.shape)]);
  if (kind === "lightsail") extra.push(["镜像", esc(i.blueprint)], ["静态IP", i.static_ip ? "是" : "否"]);
  if (acc.provider === "azure") extra.push(["资源组", esc(i.resource_group)]);
  const ops = instOps(acc, kind);
  const inl = ops.filter(([o]) => INLINE_OPS.includes(o));
  const more = ops.length > inl.length;
  return `<div class="card inst" data-id="${esc(i.id)}"><div class="hd"><b title="${esc(i.id)}">${esc(i.name)}</b>
    <span class="badge ${esc(i.state)}">${esc(i.state)}</span></div>
    <div class="kv kv2"><span>公网</span><span class="mono">${esc(i.public_ip || "-")}</span>
    <span>内网</span><span class="mono">${esc(i.private_ip || "-")}</span>
    ${extra.map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join("")}
    <span>可用区</span><span>${esc(i.zone ? regionLabel(i.zone) : "-")}</span>
    ${ip6 !== "-" ? `<span>IPv6</span><span class="mono wide">${ip6}</span>` : ""}</div>
    <div class="ops">${inl.map(([o, l]) => opBtn(o, l, i)).join("")}${more ? `<button class="btn sm" data-more aria-label="更多操作">更多 ▾</button>` : ""}</div></div>`;
}

export async function tabInstances(acc, box, kind = "vm") {
  const reload = () => tabInstances(acc, box, kind);
  if (kind === "lightsail") await ensureLsRegion(acc);
  box.innerHTML = `<div class="bar">${await regionSelect(acc, reload, kind === "lightsail" ? "lightsail" : undefined)}<button class="btn" id="rf">刷新</button>
    ${kind === "lightsail" ? `<button class="btn primary" id="lsNew">创建 Lightsail</button>` : ""}
    ${acc.provider === "aws" && kind === "vm" ? `<button class="btn primary" id="ec2New">创建 EC2</button>` : ""}
    <span class="grow"></span><span class="muted" id="info"></span>
    <div class="seg desk-only" id="ivw" title="视图（桌面宽度可用，选择会记住）"><button class="${instView() === "card" ? "on" : ""}" data-v="card">▦ 卡片</button><button class="${instView() === "table" ? "on" : ""}" data-v="table">☰ 表格</button></div></div>
    <div class="grid" id="list"><div class="empty"><span class="spin"></span></div></div>`;
  $("#rf", box).onclick = reload;
  box.querySelectorAll("#ivw [data-v]").forEach((b) => (b.onclick = () => { localStorage.setItem("tc_inst_view", b.dataset.v); reload(); }));
  if (kind === "lightsail") $("#lsNew", box).onclick = () => lightsailCreate(acc, reload);
  if (acc.provider === "aws" && kind === "vm") $("#ec2New", box).onclick = () => ec2Create(acc, reload);
  let list;
  try { list = await api(`/accounts/${acc.id}/instances?kind=${kind}&${rq(acc)}`); }
  catch (e) { $("#list", box).innerHTML = `<div class="card">❌ ${esc(e.message)}</div>`; return; }
  $("#info", box).textContent = `${list.length} 台`;
  const useTable = instView() === "table" && isDesktop() && list.length;
  const lb = $("#list", box);
  lb.className = useTable ? "card itable" : "grid";
  lb.innerHTML = !list.length ? `<div class="empty">该区域没有实例</div>` : useTable ? instTable(acc, list, kind) : list.map((i) => instCard(acc, i, kind)).join("");
  box.querySelectorAll("[data-op]").forEach((b) => {
    const card = b.closest("[data-id]");
    const inst = list.find((x) => x.id === card.dataset.id);
    b.onclick = () => instOp(acc, inst, b.dataset.op, kind, b, reload);
  });
  box.querySelectorAll("[data-more]").forEach((b) => {
    const inst = list.find((x) => x.id === b.closest("[data-id]").dataset.id);
    b.onclick = (e) => { e.stopPropagation(); opsMenu(b, instOps(acc, kind).filter(([o]) => !INLINE_OPS.includes(o)), (op) => instOp(acc, inst, op, kind, b, reload)); };
  });
}

export async function instOp(acc, inst, op, kind, btn, reload) {
  const base = { instance_id: inst.id, region: regionOf(acc) || undefined, kind, name: inst.name };
  const names = OP_NAMES[acc.provider] || { start: "启动", stop: "停止", reboot: "重启", terminate: "终止" };
  if (V16_OPS[op]) return V16_OPS[op](acc, inst, base, kind, btn, reload);
  if (names[op]) {
    const danger = op === "terminate";
    const msg = danger ? `⚠️ 确定要<b>${acc.provider === "azure" || kind === "lightsail" ? "删除" : "终止"}</b>「${esc(inst.name)}」吗？此操作不可恢复，引导卷/磁盘将一并删除。`
      : `确定${names[op]}「${esc(inst.name)}」？` + (op === "stop" && acc.provider === "azure" ? "<br><span class='muted'>Azure 将执行 deallocate，释放计算资源（动态公网 IP 会变化）。</span>" : "");
    const keep = danger && acc.provider === "oci";
    const ok = await modal(names[op], `<p>${msg}</p>${keep ? `<label><input type="checkbox" name="preserve_boot_volume" style="width:auto"> 保留引导卷（可稍后挂回或救援，保留期间计费）</label>` : ""}`,
      (bg) => form(bg), "确认", danger);
    if (!ok) return;
    await act(btn, () => post(`/accounts/${acc.id}/instances/action`, { ...base, action: op, confirm: danger, preserve_boot_volume: !!ok.preserve_boot_volume }), `${names[op]}指令已发送`);
    setTimeout(reload, 2500);
  } else if (op === "changeip") {
    let body = `<p>为「${esc(inst.name)}」更换公网 IP？当前：<code>${esc(inst.public_ip || "-")}</code></p>`;
    if (acc.provider === "aws" && kind === "vm") body += `<label>方式</label><select name="mode"><option value="auto">自动（有弹性 IP 则重分配，否则停机换 IP）</option>
      <option value="eip">重分配弹性 IP（不停机）</option><option value="stopstart">停机再启动（会中断服务）</option></select>`;
    if (acc.provider === "azure") body += `<p class="muted">将删除旧 Public IP 并新建同 SKU 的 PIP，期间网络中断约 1 分钟。</p>`;
    if (kind === "lightsail") body += `<p class="muted">通过分配新静态 IP 并释放旧静态 IP 实现（未绑定的静态 IP 会计费，面板会自动释放旧的）。</p>`;
    const oci = acc.provider === "oci";
    body += `<label>目标网段（可选，逗号分隔；<code>!</code> 开头表示排除，可混用）</label>
      <input name="cidrs" placeholder="${oci ? "如 129.146.0.0/16, !129.146.10.0/24；留空=换一次即可" : "如 !10.0.0.0/8；留空=换一次即可"}">
      <label>最多尝试次数（指定网段或质量要求时生效${oci ? "" : "，AWS/Azure 每次较慢，上限 20"}）</label><input name="max_tries" type="number" min="1" max="${oci ? 100 : 20}" value="${oci ? 20 : 5}">` + QUALITY_FIELDS;
    try { const u = await api(`/accounts/${acc.id}/ip-change-usage`); body += `<p class="muted">今日已换 IP：手动 ${u.manual_used} 次 · 自动 ${u.auto_used}/${u.limit} 次（自动换 IP 每账号每天上限可在设置里修改）</p>`; } catch (_) { /* ignore */ }
    body += `<p class="muted">已在「DNS 联动」绑定域名的实例，换 IP 后会自动更新 Cloudflare 解析。</p>`;
    const r = await modal("更换 IP", body, (bg) => post(`/accounts/${acc.id}/instances/change-ip`, { ...base, ...form(bg) }), "更换");
    if (r) {
      if (r.task_id) toast(`已创建任务 #${r.task_id}，完成后会推送通知`);
      else toast(`新 IP：${r.new_ip}`);
      setTimeout(reload, 1500);
    }
  } else if (op === "migrate") {
    migrateDialog(acc, inst);
  } else if (op === "ipv6") {
    if (!(await confirmBox("一键 IPv6", "将按需为所在 VCN 开启 IPv6、给子网分配 /64、添加 ::/0 路由和出站规则，再给实例分配 IPv6。确定？"))) return;
    await act(btn, () => post(`/accounts/${acc.id}/oci/ipv6`, base), (r) => `已创建任务 #${r.task_id}，完成后推送通知`);
  } else if (op === "delipv6") {
    if (!(await confirmBox("删除 IPv6", `⚠️ 将删除「${esc(inst.name)}」主网卡上的<b>全部 IPv6 地址</b>（VCN / 子网的 IPv6 配置保留）。确定？`, true))) return;
    if (await act(btn, () => post(`/accounts/${acc.id}/oci/ipv6/delete`, { ...base, confirm: true }), (r) => `已删除：${r.deleted.join(", ")}`)) setTimeout(reload, 1500);
  } else if (op === "rename") {
    const r = await modal("实例改名", `<input name="new_name" value="${esc(inst.name)}">
      <label><input type="checkbox" name="sync_hostname" style="width:auto" checked> 同步修改系统主机名（SSH 显示）</label>
      <p class="muted">${RENAME_HOSTNAME_TIP}</p>`, (bg) => post(`/accounts/${acc.id}/instances/rename`, { ...base, ...form(bg) }), "保存");
    if (r) { renameResult(r); reload(); }
  } else if (op === "bootvol") {
    let bv;
    try { toast("读取引导卷…"); bv = await api(`/accounts/${acc.id}/oci/boot-volume?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
    const r = await modal("引导卷", `<div class="kv"><span>名称</span><span>${esc(bv.name)}</span><span>大小</span><span>${bv.size_gb} GB</span>
      <span>性能</span><span>${bv.vpus_per_gb} VPU/GB</span><span>状态</span><span>${esc(bv.state)}</span></div>
      <div class="row2"><div><label>扩容到 (GB，只能变大)</label><input name="size_gb" type="number" min="${bv.size_gb}" placeholder="${bv.size_gb}"></div>
      <div><label>性能 VPU/GB</label><select name="vpus_per_gb">${[10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120].map((v) => `<option ${v === bv.vpus_per_gb ? "selected" : ""}>${v}</option>`).join("")}</select></div></div>
      <label><input type="checkbox" name="grow" style="width:auto" checked> 扩容后通过 Run Command 自动扩展根分区（需 Oracle Cloud Agent 插件）</label>
      <p class="muted">10 = 均衡（免费额度内），20+ 为高性能，按量计费。总免费额度 200GB。</p>`,
      (bg) => post(`/accounts/${acc.id}/oci/boot-volume`, { ...base, ...form(bg) }), "提交");
    if (r) toast(r.grow ? `已扩容；扩分区：${r.grow.status === "ok" ? "完成" : r.grow.message}` : (r.hint || "已提交"));
  } else if (op === "openport") {
    openPortDialog(acc, inst, base, btn);
  } else if (op === "security") {
    openSecurity(acc, inst, base);
  } else if (op === "traffic") {
    trafficDialog(acc, inst, kind);
  } else if (op === "dns") {
    bindDns(acc, inst);
  } else if (op === "resize") {
    if (acc.provider === "oci") {
      const r = await modal("修改配置", `<p class="muted">Flex 实例可在线调整（部分系统会自动重启）。</p><div class="row2">
        <div><label>OCPU</label><input name="ocpus" type="number" step="1" min="1" value="${inst.ocpus || 1}"></div>
        <div><label>内存 (GB)</label><input name="memory_gb" type="number" min="1" value="${inst.memory_gb || 6}"></div></div>`,
        (bg) => post(`/accounts/${acc.id}/instances/resize`, { ...base, ...form(bg) }), "提交");
      if (r) toast(`已创建任务 #${r.task_id}`);
    } else {
      let sizes = [];
      try { sizes = await api(`/accounts/${acc.id}/azure/sizes?instance_id=${encodeURIComponent(inst.id)}`); } catch (e) { return toast(e.message, true); }
      const r = await modal("调整 VM 大小", `<p class="muted">调整大小会重启 VM。当前：${esc(inst.shape)}</p><label>新大小</label><select name="size">
        ${sizes.map((s) => `<option value="${esc(s.name)}" ${s.name === inst.shape ? "selected" : ""}>${esc(s.name)} · ${s.cores}C/${(s.memory_mb / 1024).toFixed(1)}G</option>`).join("")}</select>`,
        (bg) => post(`/accounts/${acc.id}/instances/resize`, { ...base, ...form(bg) }), "提交");
      if (r) toast(`已创建任务 #${r.task_id}`);
    }
  } else if (op === "monitor") {
    const r = await modal("加入监控", `<p>监控「${esc(inst.name)}」，发现非面板操作导致的停止/终止时推送 Telegram 告警。</p>
      <label><input type="checkbox" name="auto_start" style="width:auto"> 异常停止时自动启动</label>
      <label>IP 连通检测端口（0=不检测，常用 22）</label><input name="check_port" type="number" min="0" max="65535" value="0">
      ${NO_CHANGE_IP.has(acc.provider) ? `<p class="muted">该云不支持换 IP：连不上时只推送告警。</p>` : `<label><input type="checkbox" name="auto_change_ip" style="width:auto"> 连续 3 次连不上时自动换 IP（并更新已绑定域名）</label>`}
      <p class="muted">检测从面板所在服务器发起；若面板与实例跨境，结果反映的是这条线路的连通性。</p>`,
      (bg) => post(`/monitors`, { account_id: acc.id, instance_id: inst.id, region: regionOf(acc) || null, kind, name: inst.name, state: inst.state, public_ip: inst.public_ip, ...form(bg) }), "保存");
    if (r) toast("已加入监控");
  }
}

// ================= v1.1 新增 =================
// 登录方式 + 开机脚本（创建表单通用）
export async function loginFields() {
  let scripts = [];
  try { scripts = await api("/scripts"); } catch (_) { /* ignore */ }
  return `<label><input type="checkbox" name="password_login" style="width:auto" checked> 生成随机 root 密码并开启密码登录（密码加密保存，可在「开机密码」查看）</label>
    <label>开机脚本</label><select name="script_id"><option value="">不使用模板</option>${scripts.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select>
    <textarea name="script" placeholder="或直接填写 bash 脚本（以 root 执行，日志在 /root/tricloud-init.log）"></textarea>
`;
}
export async function showCreated(r) {
  if (!r) return;
  const pw = r.password ? `<label>用户名</label><code>${esc(r.username)}</code><label>密码（只显示这一次，之后需输入面板密码查看）</label>
    <input value="${esc(r.password)}" readonly onclick="this.select()">` : `<p class="muted">未设置密码，请用 SSH 密钥登录。</p>`;
  await modal("创建已提交", `<p>${esc(r.name || "")} · ${esc(r.state || "")}${r.public_ip ? " · " + esc(r.public_ip) : ""}</p>${pw}`, null, "我已保存");
}

// v1.5 公网放行警告（实例「开放端口」/ 安全列表 / 安全组页共用）
export const publicWarn = (cidr, what, okText = "我已了解，继续") => modal("⚠️ 对整个互联网开放", `<p>来源 <code>${esc(cidr)}</code> 表示<b>任何人</b>都能访问${what}。</p>
  <ul class="guard"><li>请确认这些端口上的服务有密码 / 密钥保护，并保持更新</li><li>只需要自己访问时，建议到安全组页填写你的 IP 段</li></ul>`, null, okText, true);
export const OPEN_PORT_WHERE = { oci: "实例所在子网的安全列表", aws: "实例关联的全部安全组", azure: "实例网卡 / 子网上的网络安全组（NSG）" };
// v1.5 实例操作「开放端口」：POST /instances/{id}/open-port，来源固定 0.0.0.0/0；先填端口，再弹公网警告二次确认
export async function openPortDialog(acc, inst, base, btn) {
  const v = await modal("开放端口", `<p>在「${esc(inst.name)}」的${OPEN_PORT_WHERE[acc.provider] || "安全组"}放行入站端口，来源 <code>0.0.0.0/0</code>。</p>
    <div class="row2"><div><label>端口（单个或批量，如 8443 或 80, 443, 8000-8100）</label><input name="port" placeholder="例如 8443"></div>
    <div><label>协议</label><select name="protocol"><option value="tcp">TCP</option><option value="udp">UDP</option></select></div></div>
    <p class="muted">每个端口 / 范围一条规则，已存在的自动跳过。不支持放行全部端口（1-65535）。</p>`, (f) => {
    const x = form(f);
    if (!x.port) throw new Error("请填写端口");
    return x;
  }, "下一步");
  if (!v) return;
  if (!(await publicWarn("0.0.0.0/0", `${v.protocol.toUpperCase()} 端口 <code>${esc(v.port)}</code>`, "确认开放"))) return;
  const r = await act(btn, () => post(`/accounts/${acc.id}/instances/${encodeURIComponent(inst.id)}/open-port`,
    { port: v.port, protocol: v.protocol, region: base.region, kind: base.kind, confirm_public: true }));
  if (r) {
    toast(`已开放：新增 ${r.added} 条${r.skipped ? `，跳过已存在 ${r.skipped} 条` : ""}`);
    modal("开放端口结果", `<ul>${(r.groups || []).map((g) => `<li>${esc(g.kind)} <b>${esc(g.name)}</b>：新增 ${g.added} 条，跳过 ${g.skipped} 条</li>`).join("")}</ul>`, null, "好的");
  }
}
// v1.5「添加规则」端口输入：单端口（起始 / 结束）或批量（仿线上版 openSecRuleModal）
export const portModeFields = () => `<div data-show-when="protocol=tcp|udp"><label>端口输入方式</label><select name="port_mode">
  <option value="single">单端口（起始 / 结束端口）</option><option value="batch">批量端口（每行一个或逗号分隔）</option></select>
  <div class="row2" data-show-when="port_mode=single"><div><label>起始端口</label><input name="port_min" type="number" min="1" max="65535" placeholder="如 80"></div>
  <div><label>结束端口（留空=同起始）</label><input name="port_max" type="number" min="1" max="65535" placeholder="如 80"></div></div>
  <div data-show-when="port_mode=batch"><label>批量端口</label><textarea name="ports" placeholder="80&#10;443&#10;8000-8100"></textarea>
  <p class="muted">每行一个或逗号分隔；支持单个端口（80）、范围（8000-8100）或混合。每段一条规则，已存在的自动跳过。</p></div></div>`;
// 把弹窗的端口字段统一成 ports 字符串；返回 "" 表示未填
export function portsOf(v) {
  if (!["tcp", "udp"].includes(v.protocol)) return "";
  if (v.port_mode === "batch") return String(v.ports || "").trim();
  if (!v.port_min) return "";
  const a = +v.port_min, b = +(v.port_max || v.port_min);
  return a === b ? String(a) : `${a}-${b}`;
}

// OCI 安全列表
export async function openSecurity(acc, inst, base) {
  let lists;
  try { toast("读取安全列表…"); lists = await api(`/accounts/${acc.id}/oci/security?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  const body = lists.map((l) => `<h4>${esc(l.name)}</h4><table><tr><th>方向</th><th>协议</th><th>CIDR</th><th>端口</th><th></th></tr>
    ${l.rules.map((r) => `<tr><td>${r.direction === "ingress" ? "入站" : "出站"}</td><td>${esc(r.protocol)}</td><td class="mono">${esc(r.cidr)}</td><td>${esc(r.port)}</td>
    <td><button class="btn sm danger" data-rm="${esc(l.id)}|${r.direction}|${r.idx}">删除</button></td></tr>`).join("")}</table>
    <div class="bar"><button class="btn sm" data-add="${esc(l.id)}">添加规则</button><button class="btn sm" data-ports="1">放行指定端口</button></div>`).join("");
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal wide"><h3>安全列表 · ${esc(inst.name)}</h3><div class="mb">${body}</div><div class="acts"><button class="btn" data-x>关闭</button></div></div>`;
  document.body.appendChild(bg);
  const again = () => { bg.remove(); openSecurity(acc, inst, base); };
  bg.querySelector("[data-x]").onclick = () => bg.remove();
  bg.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = async () => {
    const [sl_id, direction, idx] = b.dataset.rm.split("|");
    if (!(await confirmBox("删除规则", "确定删除这条规则？", true))) return;
    if (await act(b, () => post(`/accounts/${acc.id}/oci/security`, { op: "remove", region: base.region, sl_id, direction, idx }), "已删除")) again();
  }));
  const pubOk = async (cidr, what) => !PUBLIC_CIDR(cidr) || !!(await publicWarn(cidr, esc(what)));
  // 「放行指定端口」：与实例操作「开放端口」同一个接口（来源 0.0.0.0/0）
  bg.querySelectorAll("[data-ports]").forEach((b) => (b.onclick = () => { bg.remove(); openPortDialog(acc, inst, base, null); }));
  bg.querySelectorAll("[data-add]").forEach((b) => (b.onclick = async () => {
    const r = await modal("添加规则", `<div class="row2"><div><label>方向</label><select name="direction"><option value="ingress">入站</option><option value="egress">出站</option></select></div>
      <div><label>协议</label><select name="protocol"><option>tcp</option><option>udp</option><option>icmp</option><option>icmpv6</option><option>all</option></select></div></div>
      <label>CIDR</label><input name="cidr" placeholder="如 203.0.113.0/24；0.0.0.0/0 表示整个互联网">
      ${portModeFields()}<label>备注</label><input name="desc">
      <p class="muted">对 0.0.0.0/0 必须填写具体端口，不支持放行全部端口。</p>`, (f) => form(f), "下一步");
    if (!r) return;
    const ports = portsOf(r);
    if (r.direction === "ingress" && !(await pubOk(r.cidr, ports ? `端口 ${ports}` : "该协议"))) return;
    const res = await act(null, () => post(`/accounts/${acc.id}/security-rules`, { instance_id: inst.id, region: base.region, sl_id: b.dataset.add,
      direction: r.direction, protocol: r.protocol, cidr: r.cidr, ports, description: r.desc, confirm_public: PUBLIC_CIDR(r.cidr) }));
    if (res) { toast(`已添加 ${res.added} 条${res.skipped ? `，跳过已存在 ${res.skipped} 条` : ""}`); again(); }
  }));
}

export const migSpec = (p) => ({
    oci: `<div class="row2" data-oci-os><div><label>规格</label><select name="shape">${ociShapeOpts("VM.Standard.A1.Flex", ["VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"])}</select></div>
      ${ociOsFields({ os: "Canonical Ubuntu" })}
      <div><label>OCPU</label><input name="ocpus" type="number" min="1" value="1"></div><div><label>内存 GB</label><input name="memory_gb" type="number" min="1" value="6"></div>
      <div><label>系统盘 GB</label><input name="disk_gb" type="number" min="47" value="50"></div></div>`,
    aws: `<div class="row2"><div><label>实例类型</label><input name="type" value="t3.micro"></div>
      <div><label>系统</label><select name="os"><option>debian-12</option><option>ubuntu-24.04</option><option>ubuntu-22.04</option></select></div>
      <div><label>系统盘 GB</label><input name="disk_gb" type="number" min="8" value="10"></div><div><label>额外端口</label><input name="ports" placeholder="80,443"></div></div>`,
    azure: `<div class="row2"><div><label>区域</label><input name="location" value="eastasia"></div><div><label>大小</label><input name="size" value="Standard_B1s"></div>
      <div><label>系统</label><select name="os"><option>debian-12</option><option>ubuntu-24.04</option></select></div>
      <div><label>磁盘类型</label><select name="disk_type"><option>Premium_LRS</option><option>StandardSSD_LRS</option></select></div>
      <div><label>系统盘 GB</label><input name="disk_gb" type="number" min="30" value="64"></div><div><label>额外端口</label><input name="ports" placeholder="80,443"></div></div>`,
  }[p]);
export async function migrateDialog(acc, inst) {
  const targets = ACCOUNTS.filter((a) => a.id !== acc.id && !NO_CREATE.has(a.provider));
  if (!targets.length) return toast("至少需要两个云账号才能迁移", true);
  const lf = await loginFields();

  const r = await modal("跨云迁移 / 重建", `<p>把「${esc(inst.name)}」在另一个账号重建：用同一个开机脚本新建实例，可自动把绑定的域名切到新 IP。</p>
    <p class="muted">⚠️ 不复制磁盘数据。需要保留的数据请先自行备份，或放进开机脚本里拉取。</p>
    <label>目标账号</label><select name="to" id="mto">${targets.map((a) => `<option value="${a.id}">${PNAME[a.provider]} · ${esc(a.name)}</option>`).join("")}</select>
    <label>新实例名称</label><input name="name" value="${esc(inst.name)}-new">
    <div id="mspec">${migSpec(targets[0].provider)}</div>${lf}
    <label><input type="checkbox" name="switch_dns" checked> 完成后把源实例绑定的域名切到新 IP</label>
    <label><input type="checkbox" name="copy_monitor" checked> 复制监控设置</label>
    <label><input type="checkbox" name="stop_source"> 完成后停掉源实例（不删除）</label>`, (bg) => {
    const f = form(bg); const to = ACCOUNTS.find((a) => a.id == f.to);
    const { to: _t, switch_dns, copy_monitor, stop_source, ...create } = f;
    return post("/migrate", { from_account_id: acc.id, from_region: regionOf(acc) || undefined, instance_id: inst.id, name: inst.name,
      to_account_id: to.id, region: to.provider === "azure" ? undefined : regionOf(to) || undefined, create, switch_dns, copy_monitor, stop_source });
  }, "开始迁移");
  if (r) toast(`已创建迁移任务 #${r.task_id}，完成后推送通知`);
}
document.addEventListener("change", (e) => {
  if (e.target.id !== "mto") return;
  const a = ACCOUNTS.find((x) => x.id == e.target.value); const box = document.getElementById("mspec");
  if (a && box) box.innerHTML = migSpec(a.provider);
});

// ================= v1.3 新增：流量守护 / 串口控制台 =================
export const FREE_OUT = { oci: 10240, aws: 100, azure: 100 };
export async function trafficDialog(acc, inst, kind, onSaved) {
  let gs = [];
  try { gs = await api("/traffic-guards"); } catch (_) { /* ignore */ }
  const g = gs.find((x) => x.account_id === acc.id && x.instance_id === inst.id) || {};
  if (TRAFFIC_DIALOG[acc.provider]) return TRAFFIC_DIALOG[acc.provider](acc, inst, g, onSaved);
  let use = "";
  try {
    const rgq = NOREG(acc) ? "" : `region=${encodeURIComponent(inst.region || regionOf(acc))}`;
    const t = await api(`/accounts/${acc.id}/traffic?instance_id=${encodeURIComponent(inst.id)}&kind=${kind}&${rgq}`);
    use = `<p>本月（${esc(t.period)}）出站 <b>${t.out_gb} GB</b>，入站 ${t.in_gb} GB。</p>`;
  } catch (e) { use = `<p class="muted">读取流量失败：${esc(e.message)}</p>`; }
  const mode = g.mode || "monthly", dir = g.direction || (g.count_in ? "both" : "out");
  const r = await modal(`流量守护 · ${inst.name}`, `${use}
    <p class="muted">月度模式每 30 分钟、滚动窗口每 10 分钟查一次平台指标（免费，有 5~15 分钟延迟，建议留余量）。到预警比例推送 Telegram；到上限推送，可选自动停机。</p>
    <div class="row2"><div><label>统计方式</label><select name="mode"><option value="monthly">本月累计</option><option value="rolling" ${mode === "rolling" ? "selected" : ""}>滚动窗口（最近 N 小时）</option></select></div>
    <div data-show-when="mode=rolling"><label>窗口小时数 N</label><input name="window_hours" type="number" min="1" max="720" value="${g.window_hours || 24}"></div>
    <div><label>方向</label><select name="direction">${[["out", "出站"], ["in", "入站"], ["both", "双向（出+入）"]].map(([v, l]) => `<option value="${v}" ${dir === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    <div><label><span data-show-when="mode=monthly">每月</span><span data-show-when="mode=rolling">窗口内</span>上限 GB（免费出站 ${FREE_OUT[acc.provider]} GB/月）</label><input name="limit_gb" type="number" min="1" value="${g.limit_gb || FREE_OUT[acc.provider]}"></div>
    <div><label>预警比例 %</label><input name="warn_pct" type="number" min="10" max="99" value="${g.warn_pct || 80}"></div>
    <div><label>到达上限后</label><select name="action"><option value="notify">只推送</option><option value="stop" ${g.action === "stop" ? "selected" : ""}>推送并自动停机</option><option value="throttle" ${g.action === "throttle" ? "selected" : ""}>推送并限速（需在实例上装 agent）</option></select></div>
    <div data-show-when="action=stop"><label>关机多少小时后自动开机（0 = 不自动开机）</label><input name="shutdown_hours" type="number" min="0" max="720" step="0.5" value="${g.shutdown_hours || 0}"></div>
    <div data-show-when="action=throttle"><label>限速到（Mbps，出站，0.1–10000）</label><input name="throttle_mbps" type="number" min="0.1" max="10000" step="0.1" value="${g.throttle_mbps || 1}"></div></div>
    <p class="muted" data-show-when="action=stop">自动开机失败只推送 Telegram 告警，不会反复重试。</p>
    <p class="muted" data-show-when="action=throttle">限速由实例上的 agent（bash + tc，systemd timer 每 5 分钟）执行，SSH 端口不限速；滚动窗口回落或下月 1 日自动解除。agent 未安装或离线时只能推送「无法限速」。保存后在「agent」里复制安装命令。</p>
    <label><input type="checkbox" name="acct_enabled" ${g.acct_enabled ? "checked" : ""}> 流量明细：按端口 / 服务统计（同一个 agent，只计数不拦截；任何动作都可以开）</label>
    <label><input type="checkbox" name="enabled" ${g.enabled === 0 ? "" : "checked"}> 启用这条规则</label>
    ${g.id ? `<div class="bar" style="margin-top:8px"><span class="grow">${agentLine(g.agent, g)}</span><button type="button" class="btn sm" id="tgAgent">agent</button><button type="button" class="btn sm" id="tgPorts">端口明细</button></div>` : ""}`,
    (bg) => post("/traffic-guards", { account_id: acc.id, instance_id: inst.id, region: inst.region || regionOf(acc) || undefined, kind, name: inst.name, ...form(bg) }), "保存", false,
    (bg) => {
      if (bg.querySelector("#tgAgent")) bg.querySelector("#tgAgent").onclick = () => { bg.remove(); guardAgentDialog(g, onSaved); };
      if (bg.querySelector("#tgPorts")) bg.querySelector("#tgPorts").onclick = () => { bg.remove(); guardPortsDialog(g); };
    });
  if (r) {
    toast(r.warning || `已保存，当前已用 ${r.last_gb ?? "-"} GB（${r.last_pct ?? "-"}%）`, !!r.warning);
    if (onSaved) onSaved();
    const ng = (await api("/traffic-guards").catch(() => [])).find((x) => x.id === r.id);
    if (ng && (ng.action === "throttle" || ng.acct_enabled) && !(ng.agent && ng.agent.installed)) guardAgentDialog(ng, onSaved);   // 首次选限速 / 流量明细：直接给安装命令
  }
}

// ---------- 实例表格视图 ----------
export const INLINE_OPS = ["start", "stop", "reboot", "changeip"];
// 按实例状态禁用无意义的操作：运行中不能再启动，已停止不能停止/重启
export function opOff(op, i) {
  const st = String(i.state || "").toLowerCase();
  const up = ["running", "starting", "provisioning", "pending"].includes(st), down = ["stopped", "stopping", "deallocated", "deallocating", "stopped (deallocated)"].includes(st);
  if (op === "start" && up) return "已在运行";
  if ((op === "stop" || op === "reboot") && down) return "已停止";
  return "";
}
export const opBtn = (o, l, i, cls = "") => { const off = opOff(o, i); return `<button class="btn sm ${cls}" data-op="${o}"${off ? ` disabled title="${off}"` : ""}>${l}</button>`; };
export function instTable(acc, list, kind) {
  // v1.5：参照线上版——默认表格视图，列：名称/状态/规格/公网 IP/内网 IP/地域/创建时间，行内操作全部平铺
  const spec = (i) => acc.provider === "oci" ? `${esc(i.shape)} ${i.ocpus ?? ""}C/${i.memory_gb ?? ""}G` : esc(i.shape || "-");
  const when = (c) => { if (!c || c === "None") return "-"; const t = String(c).replace("T", " "); return esc(t.slice(0, 16)); };
  const ops = instOps(acc, kind);
  return `<table class="inst-table"><tr><th>名称</th><th>状态</th><th>规格</th><th>公网 IP</th><th>内网 IP</th><th>地域</th><th>创建时间</th><th>操作</th></tr>
    ${list.map((i) => `<tr data-id="${esc(i.id)}"><td><b title="${esc(i.id)}">${esc(i.name)}</b>${(i.ipv6 || []).length ? `<div class="muted mono" title="${esc(i.ipv6.join("\n"))}">${esc(i.ipv6[i.ipv6.length - 1])}${i.ipv6.length > 1 ? ` +${i.ipv6.length - 1}` : ""}</div>` : ""}</td>
    <td><span class="badge ${esc(i.state)}">${esc(i.state)}</span></td><td>${spec(i)}</td><td class="mono nowrap">${esc(i.public_ip || "-")}</td><td class="mono nowrap">${esc(i.private_ip || "-")}</td>
    <td class="nowrap">${esc(i.zone || i.region ? regionLabel(i.zone || i.region) : "-")}</td><td class="mono nowrap">${when(i.created)}</td>
    <td class="row-ops"><div class="row-ops-in">${ops.map(([o, l]) => opBtn(o, l, i, o === "terminate" ? "danger" : "")).join("")}</div></td></tr>`).join("")}</table>`;
}
export function opsMenu(anchor, ops, pick) {
  closeOpsMenu();
  const m = document.createElement("div"); m.className = "opsmenu"; m.setAttribute("role", "menu");
  m.innerHTML = ops.map(([o, l]) => `<button role="menuitem" class="${o === "terminate" ? "danger" : ""}" data-o="${o}">${l}</button>`).join("");
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  m.style.top = `${Math.min(r.bottom + 4, window.innerHeight - m.offsetHeight - 8)}px`;
  m.style.left = `${Math.max(8, Math.min(r.right - 200, window.innerWidth - 216))}px`;
  m.querySelectorAll("[data-o]").forEach((b) => (b.onclick = () => { closeOpsMenu(); pick(b.dataset.o); }));
}
export function closeOpsMenu() { document.querySelectorAll(".opsmenu").forEach((m) => m.remove()); }

// ---------- 3. 重装系统 ----------
export const AWS_OS = [["debian-12", "Debian 12"], ["ubuntu-24.04", "Ubuntu 24.04"], ["ubuntu-22.04", "Ubuntu 22.04"], ["al2023", "Amazon Linux 2023"]];
export const AZ_OS = [["debian-12", "Debian 12"], ["ubuntu-24.04", "Ubuntu 24.04"], ["ubuntu-22.04", "Ubuntu 22.04"]];
export async function reinstallDialog(acc, inst, base) {
  const oci = acc.provider === "oci";
  const osField = oci ? `<div class="row2" data-oci-os><input type="hidden" name="shape" value="${esc(inst.shape || "")}">${ociOsFields({})}</div>
      <label>新引导卷大小 GB（留空 = 与当前相同，不能变小）</label><input name="disk_gb" type="number" min="47">`
    : `<label>系统</label><select name="os">${(acc.provider === "aws" ? AWS_OS : AZ_OS).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>`;
  const how = oci ? "替换引导卷：实例 OCID、私网 IP、公网 IP 不变。"
    : acc.provider === "aws" ? "替换根卷（Replace Root Volume）：实例 ID、私网 IP、弹性 IP 不变；沿用原密钥对与 user-data。"
      : "删除 VM 后用同名、同大小、原网卡（含公网 IP）和原数据盘重新创建。";
  const p = modal("重装系统", `<p>⚠️ 将重装「${esc(inst.name)}」，<b>系统盘上的全部数据会被清空</b>，不可恢复。</p>
    <p class="muted">${how}实例会停机几分钟。</p>${osField}
    ${acc.provider === "aws" ? "" : `<label><input type="checkbox" name="password_login" style="width:auto" checked> 生成新的随机 root 密码（完成后在「开机密码」查看）</label>
    <label>SSH 公钥（可选，留空沿用原公钥）</label><textarea name="ssh_key" placeholder="ssh-ed25519 AAAA..."></textarea>`}
    <label><input type="checkbox" name="confirm" style="width:auto"> 我已确认要清空系统盘数据</label>`, (bg) => {
    const f = form(bg);
    if (!f.confirm) throw new Error("请先勾选确认");
    delete f.shape;
    return post(`/accounts/${acc.id}/instances/reinstall`, { ...base, ...f, confirm: true });
  }, "开始重装", true);
  if (oci) setTimeout(() => wireOciOs(lastModal() && lastModal().querySelector("[data-oci-os]"), acc), 0);
  const r = await p;
  if (r) toast(`已创建任务 #${r.task_id}，完成后推送通知`);
}

// ---------- 8. OCI 附加 IP / 辅助网卡 / 预留 IP ----------
export async function ociIpsDialog(acc, inst, base, reload) {
  let d;
  try { toast("读取网卡与 IP…"); d = await api(`/accounts/${acc.id}/oci/ips?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  const ipRow = (v, ip) => `<tr><td class="mono">${esc(ip.ip)}${ip.primary ? ` <span class="badge">主</span>` : ""}</td>
    <td class="mono">${ip.public ? `${esc(ip.public.ip)} <span class="muted">${ip.public.lifetime === "RESERVED" ? "预留" : "临时"}</span>` : "-"}</td>
    <td>${ip.primary ? "" : `<button class="btn sm danger" data-delip="${esc(ip.id)}">删除</button>`}</td></tr>`;
  const html = d.vnics.map((v) => `<h4>${v.primary ? "主网卡" : "辅助网卡"} · ${esc(v.name || "")}
      ${v.primary ? `<button class="btn sm" data-addip="${esc(v.vnic_id)}">+ 辅助 IP</button>` : `<button class="btn sm danger" data-detach="${esc(v.attachment_id)}">卸载网卡</button>`}</h4>
    <table><tr><th>私网 IP</th><th>公网 IP</th><th></th></tr>${v.ips.map((ip) => ipRow(v, ip)).join("")}</table>`).join("")
    + `<div class="bar" style="margin-top:10px"><button class="btn" id="addVnic">+ 辅助网卡</button></div>
    <h4>预留公网 IP（换机 / 重装后 IP 不变）<button class="btn sm" id="newRes">+ 新建预留 IP</button></h4>
    <table><tr><th>IP</th><th>状态</th><th></th></tr>${d.reserved.map((r) => `<tr><td class="mono">${esc(r.ip)}</td><td>${r.assigned ? "已绑定" : "未绑定"}</td>
      <td>${r.assigned ? `<button class="btn sm" data-unres="${esc(r.id)}">解绑</button>` : `<button class="btn sm" data-res="${esc(r.id)}" data-ip="${esc(r.ip)}">绑到本机</button> <button class="btn sm danger" data-delres="${esc(r.id)}">删除</button>`}</td></tr>`).join("") || `<tr><td colspan=3 class="muted">暂无</td></tr>`}</table>
    <p class="muted">辅助 IP / 辅助网卡需要在系统内配置后才生效（完成后会给出命令）。预留 IP 绑到本机会替换当前临时公网 IP。</p>`;
  const done = (r) => { if (r && r.hint) modal("已完成", `<p>${esc(r.hint)}</p>`, null, "知道了"); else toast("已完成"); lastModal() && lastModal().remove(); ociIpsDialog(acc, inst, base, reload); };
  const opp = (b, body) => act(b, () => post(`/accounts/${acc.id}/oci/ips`, { region: regionOf(acc) || undefined, instance_id: inst.id, ...body })).then((r) => r && done(r));
  modal(`附加 IP · ${inst.name}`, html, null, "关闭");
  const bg = lastModal();
  bg.querySelectorAll("[data-addip]").forEach((b) => (b.onclick = () => opp(b, { op: "add_secondary", vnic_id: b.dataset.addip })));
  bg.querySelectorAll("[data-delip]").forEach((b) => (b.onclick = async () => { if (await confirmBox("删除辅助 IP", "删除这个辅助私网 IP（及其公网 IP）？", true)) opp(b, { op: "delete_private", private_ip_id: b.dataset.delip }); }));
  bg.querySelectorAll("[data-detach]").forEach((b) => (b.onclick = async () => { if (await confirmBox("卸载辅助网卡", "卸载后该网卡上的 IP 全部释放。确定？", true)) opp(b, { op: "detach_vnic", attachment_id: b.dataset.detach }); }));
  bg.querySelector("#addVnic").onclick = (e) => opp(e.target, { op: "attach_vnic" });
  bg.querySelector("#newRes").onclick = (e) => opp(e.target, { op: "create_reserved" });
  bg.querySelectorAll("[data-res]").forEach((b) => (b.onclick = async () => { if (await confirmBox("绑定预留 IP", `把 ${esc(b.dataset.ip)} 绑到「${esc(inst.name)}」？当前临时公网 IP 会被释放。`)) opp(b, { op: "assign_reserved", public_ip_id: b.dataset.res, ip: b.dataset.ip }).then(() => setTimeout(reload, 1500)); }));
  bg.querySelectorAll("[data-unres]").forEach((b) => (b.onclick = async () => { if (await confirmBox("解绑预留 IP", "解绑后会自动给实例分配一个新的临时公网 IP。确定？")) opp(b, { op: "unassign_reserved", public_ip_id: b.dataset.unres }).then(() => setTimeout(reload, 1500)); }));
  bg.querySelectorAll("[data-delres]").forEach((b) => (b.onclick = async () => { if (await confirmBox("删除预留 IP", "删除后这个 IP 无法找回。确定？", true)) opp(b, { op: "delete_reserved", public_ip_id: b.dataset.delres }); }));
}

// ---------- 9. IP 质量 ----------
export function qualityHtml(q) {
  const lv = q.risk == null ? "" : q.risk <= 33 ? "done" : q.risk <= 66 ? "running" : "failed";
  return `<div class="kv"><span>IP</span><span class="mono">${esc(q.ip)}</span>
    <span>风险分</span><span>${q.risk == null ? "查询失败" : `<span class="badge ${lv}">${q.risk}</span> <span class="muted">0~100，越低越干净</span>`}</span>
    <span>类型</span><span>${esc(q.type || "-")}${q.proxy ? " · 被标记为代理/VPN" : ""}</span>
    <span>归属</span><span>${esc(q.country || "-")} ${esc(q.country_code || "")}</span>
    <span>ISP / ASN</span><span>${esc(q.isp || "-")} ${esc(q.asn || "")}</span>
    <span>机房 IP</span><span>${q.hosting == null ? "-" : q.hosting ? "是" : "否"}</span></div>
    ${q.error ? `<p class="muted">${esc(q.error)}</p>` : ""}<p class="muted">数据源：${esc(q.source || "")}。只发送这个公网 IP，不发送任何凭证。流媒体解锁需在实例内检测，面板不提供。</p>`;
}
export async function qualityDialog(inst) {
  if (!inst.public_ip) return toast("实例没有公网 IP", true);
  let q;
  try { toast("检测中…"); q = await api(`/ip-quality?ip=${encodeURIComponent(inst.public_ip)}`); } catch (e) { return toast(e.message, true); }
  modal(`IP 质量 · ${inst.name}`, qualityHtml(q), null, "关闭");
}
export const QUALITY_FIELDS = `<details><summary class="muted">IP 质量要求（可选：不合格自动重换）</summary>
  <div class="row2"><div><label>风险分上限（0~100，留空不限）</label><input name="quality_max_risk" type="number" min="0" max="100" placeholder="如 50"></div>
  <div><label>归属国家（留空不限）</label><input name="quality_country" placeholder="如 US 或 US,JP"></div></div>
  <p class="muted">每换一次都会查询风险分（proxycheck.io，无 Key 每天 100 次）和归属地（ip-api.com）。</p></details>`;

// ---------- 15. 免费 AMD 下行 500Mbps ----------
export async function net500Dialog(acc, inst, base) {
  let st;
  try { st = await api(`/accounts/${acc.id}/oci/500m?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`); } catch (e) { return toast(e.message, true); }
  if (st.enabled) {
    const r = await modal("关闭下行 500Mbps", `<p>当前已开启，入口 IP：<code>${esc(st.public_ip || "-")}</code></p><p class="muted">关闭后删除网络负载均衡器，实例恢复用原公网 IP 入站。</p>`,
      () => post(`/accounts/${acc.id}/oci/500m`, { ...base, enable: false }), "关闭", true);
    if (r) toast(`已创建任务 #${r.task_id}`);
    return;
  }
  const r = await modal("开启下行 500Mbps", `<p>给免费 AMD（E2.1.Micro）开启约 500Mbps 下行：</p>
    <ul class="guard"><li>新建一个网络负载均衡器（Always Free 含 1 个）转发全部 TCP/UDP 端口到本机，<b>入口 IP 变成负载均衡器的公网 IP</b>；</li>
    <li>实例网卡改走 NAT 网关出站（原公网 IP 不再接收入站）；</li><li>账号里已有其他负载均衡器时不会动它，会直接提示。</li></ul>
    <label>健康检查端口（SSH 端口）</label><input name="ssh_port" type="number" value="22" min="1" max="65535">
    <p class="muted">参考 oci-helper 的公开做法。随时可以关闭还原。</p>`, (bg) => post(`/accounts/${acc.id}/oci/500m`, { ...base, ...form(bg), enable: true, confirm: true }), "开启");
  if (r) toast(`已创建任务 #${r.task_id}，完成后会推送新的入口 IP`);
}

// ---------- 14. Azure 磁盘 ----------
export async function azDiskDialog(acc, inst) {
  let d;
  try { toast("读取磁盘…"); d = await api(`/accounts/${acc.id}/azure/disks?instance_id=${encodeURIComponent(inst.id)}`); } catch (e) { return toast(e.message, true); }
  const rows = d.disks.map((k) => `<tr><td>${k.role === "os" ? "系统盘" : `数据盘 LUN ${k.lun}`}<div class="muted mono">${esc(k.name)}</div></td><td>${k.size_gb} GB</td><td>${esc(k.sku || "-")}</td><td>${esc(k.tier || "-")}</td>
    <td><button class="btn sm" data-disk="${esc(k.id)}">调整</button></td></tr>`).join("");
  modal(`磁盘 · ${inst.name}`, `<table><tr><th>磁盘</th><th>大小</th><th>类型</th><th>性能层</th><th></th></tr>${rows}</table><p class="muted">${esc(d.hint)}</p>`, null, "关闭");
  lastModal().querySelectorAll("[data-disk]").forEach((b) => (b.onclick = async () => {
    const k = d.disks.find((x) => x.id === b.dataset.disk);
    const r = await modal(`调整 ${k.name}`, `<div class="row2"><div><label>大小 GB（只能变大）</label><input name="size_gb" type="number" min="${k.size_gb}" placeholder="${k.size_gb}"></div>
      <div><label>类型</label><select name="sku">${d.skus.map((s) => `<option ${s === k.sku ? "selected" : ""}>${s}</option>`).join("")}</select></div></div>
      <label>Premium 性能层（只对 Premium SSD 有效）</label><select name="tier"><option value="">不变</option>${d.tiers.map((t) => `<option ${t === k.tier ? "selected" : ""}>${t}</option>`).join("")}</select>`,
      (bg) => { const f = form(bg); if (f.sku === k.sku) delete f.sku; return post(`/accounts/${acc.id}/azure/disks`, { instance_id: inst.id, disk_id: k.id, ...f }); }, "提交");
    if (r) { toast(r.hint || "已调整"); lastModal() && lastModal().remove(); azDiskDialog(acc, inst); }
  }));
}

// ---------- 19. Lightsail 防火墙 ----------
export async function lsPortsDialog(acc, inst) {
  const load = () => api(`/accounts/${acc.id}/lightsail/ports?instance=${encodeURIComponent(inst.id)}&${rq(acc)}`);
  let ports;
  try { ports = await load(); } catch (e) { return toast(e.message, true); }
  modal(`防火墙 · ${inst.name}`, `<table><tr><th>协议</th><th>端口</th><th>来源</th><th></th></tr>${ports.map((p, i) => `<tr><td>${esc(p.protocol)}</td><td>${p.from === p.to ? p.from : `${p.from}-${p.to}`}</td>
    <td class="mono">${esc([...p.cidrs, ...p.ipv6_cidrs].join(", ") || "-")}</td><td><button class="btn sm danger" data-close="${i}">关闭</button></td></tr>`).join("") || `<tr><td colspan=4 class="muted">没有开放的端口</td></tr>`}</table>
    <div class="row2"><div><label>协议</label><select name="protocol"><option>tcp</option><option>udp</option><option>icmp</option></select></div>
    <div><label>端口（单个或范围，如 8443 或 8000-8100）</label><input name="port" placeholder="例如 8443"></div></div>
    <label>来源 CIDR（逗号分隔）</label><input name="cidrs" value="0.0.0.0/0">
    <div class="bar"><button class="btn primary" id="lsOpen">开放端口</button></div>`, null, "关闭");
  const bg = lastModal();
  bg.querySelectorAll("[data-close]").forEach((b) => (b.onclick = async () => {
    const p = ports[+b.dataset.close];
    if (!(await confirmBox("关闭端口", `关闭 ${esc(p.protocol)} ${p.from}-${p.to}？`, true))) return;
    if (await act(b, () => post(`/accounts/${acc.id}/lightsail/ports`, { op: "close", instance: inst.id, region: regionOf(acc), protocol: p.protocol, from_port: p.from, to_port: p.to }), "已关闭")) { bg.remove(); lsPortsDialog(acc, inst); }
  }));
  bg.querySelector("#lsOpen").onclick = async (e) => {
    const f = form(bg); const m = /^(\d+)(?:\s*-\s*(\d+))?$/.exec(f.port || "");
    if (f.protocol !== "icmp" && !m) return toast("请填写端口，如 8443 或 8000-8100", true);
    const body = { op: "open", instance: inst.id, region: regionOf(acc), protocol: f.protocol, from_port: m ? +m[1] : -1, to_port: m ? +(m[2] || m[1]) : -1, cidrs: f.cidrs };
    if (f.protocol === "icmp") { body.from_port = 0; body.to_port = 0; }
    try { await post(`/accounts/${acc.id}/lightsail/ports`, body); }
    catch (err) {
      if (!/0\.0\.0\.0|整个互联网/.test(err.message)) return toast(err.message, true);
      if (!(await confirmBox("对整个互联网开放", `来源 0.0.0.0/0：任何人都能访问 ${esc(f.port || "ICMP")}。确定？`, true))) return;
      if (!(await act(e.target, () => post(`/accounts/${acc.id}/lightsail/ports`, { ...body, confirm_public: true })))) return;
    }
    toast("已开放"); bg.remove(); lsPortsDialog(acc, inst);
  };
}

// ---------- 实例操作入口 ----------
export const V16_OPS = {
  reinstall: (acc, inst, base) => reinstallDialog(acc, inst, base),
  ips: (acc, inst, base, kind, btn, reload) => ociIpsDialog(acc, inst, base, reload),
  quality: (acc, inst) => qualityDialog(inst),
  net500: (acc, inst, base) => net500Dialog(acc, inst, base),
  disks: (acc, inst) => azDiskDialog(acc, inst),
  lsports: (acc, inst) => lsPortsDialog(acc, inst),
};
export function v16Ops(acc, kind, ops) {
  const i = ops.findIndex(([o]) => o === "terminate");
  const add = [];
  if (acc.provider === "oci") add.push(["ips", "附加 IP"], ["net500", "500M 下行"]);
  if (acc.provider === "azure") add.push(["disks", "磁盘"]);
  if (kind === "lightsail") add.push(["lsports", "防火墙"]);
  add.push(["quality", "IP 质量"]);
  if (kind !== "lightsail") add.push(["reinstall", "重装系统"]);
  ops.splice(i < 0 ? ops.length : i, 0, ...add);
  return ops;
}
