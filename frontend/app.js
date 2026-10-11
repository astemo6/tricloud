/* TriCloud 前端逻辑 */
let providers = [], curProvider = null;
let accounts = [], curAccount = null;
let instances = [];
let curTab = 'instances';
let jobTimer = null, jobDetailId = null, drawerPoll = null;

async function api(method, path, body) {
const r = await fetch(path, {
method, headers: {'Content-Type': 'application/json'},
body: body? JSON.stringify(body): undefined
});
if (r.status === 401) { location.href = '/login.html'; throw new Error('未登录');}
const d = await r.json().catch(() => ({}));
if (!r.ok) throw new Error(d.detail || ('请求失败 ' + r.status));
return d;
}

function toast(msg, isErr) {
const t = document.getElementById('toast');
t.textContent = msg; t.className = 'toast show' + (isErr? ' err': '');
clearTimeout(t._h); t._h = setTimeout(() => t.className = 'toast', 3200);
}
const esc = s => String(s == null? '': s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// 用量进度条：按 used/total 比例填充，<60% 绿、60-85% 橙、>85% 红
const usageBar = (used, total) => {
const u = total > 0? Math.min(1, Math.max(0, used / total)): 0;
const pct = Math.round(u * 100);
const cls = pct < 60? 'low': (pct <= 85? 'mid': 'high');
return `<span class="meter" title="已用 ${pct}%"><span class="meter-fill ${cls}" style="width:${pct}%"></span></span>`;
};
const fmtTime = s => { if (!s) return '-'; const d = new Date(s); return isNaN(d)? s: d.toLocaleString('zh-CN', {hour12: false});};

function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('tricloud-theme', t); } catch (e) {}
  const sel = document.getElementById('themeSel');
  if (sel) sel.value = t;
}

async function init() {
const me = await api('GET', '/api/me');
if (!me.logged_in) { location.href = '/login.html'; return;}
// 同步主题选择器
try {
  const t = localStorage.getItem('tricloud-theme') || 'auto';
  const sel = document.getElementById('themeSel');
  if (sel) sel.value = t;
} catch (e) {}
providers = await api('GET', '/api/providers');
const nav = document.getElementById('providerNav');
const colors = {oci: 'var(--oci)', aws: 'var(--aws)', azure: 'var(--azure)'};
const icons = {oci: '☁️', aws: '🟠', azure: '🔷'};
nav.innerHTML = providers.map(p =>
`<div class="nav-item" data-p="${p.id}" onclick="selectProvider('${p.id}')">
<span class="dot" style="background:${colors[p.id] || 'var(--muted)'}"></span>${icons[p.id] || ''} ${esc(p.name)}
</div>`).join('');
const s = parseHash();
if (s && providers.find(p => p.id === s.provider)) {
selectProvider(s.provider, s.accountId, s.tab);
} else {
selectProvider(providers[0].id);
}
window.addEventListener('hashchange', onHashChange);
}

function selectProvider(id, accountId, tab) {
curProvider = providers.find(p => p.id === id) || providers[0];
document.querySelectorAll('#providerNav.nav-item').forEach(el =>
el.classList.toggle('active', el.dataset.p === curProvider.id));
curTab = tab || 'instances';
loadAccounts(accountId);
}

/* ---------- hash 路由：刷新/前进后退保持当前页面 ---------- */
let _hashSyncing = false;
function syncHash() {
if (!curProvider) return;
const h = `#/${curProvider.id}/${curAccount? curAccount.id: 0}/${curTab}`;
if (location.hash !== h) { _hashSyncing = true; location.hash = h;}
}
function parseHash() {
const m = (location.hash || '').match(/^#\/([a-z]+)\/(\d+)\/([a-z]+)$/);
return m? {provider: m[1], accountId: m[2], tab: m[3]}: null;
}
function onHashChange() {
if (_hashSyncing) { _hashSyncing = false; return;}
const s = parseHash();
if (!s || !providers.find(p => p.id === s.provider)) return;
if (s.provider !== curProvider.id) {
selectProvider(s.provider, s.accountId, s.tab);
} else if (!curAccount || String(curAccount.id) !== String(s.accountId)) {
const sel = document.getElementById('accountSel');
if (sel) sel.value = s.accountId;
onAccountChange(s.tab);
} else if (s.tab !== curTab) {
switchTab(s.tab);
}
}

function renderTabs() {
const defs = [{key: 'instances', label: curProvider.id === 'aws'? 'EC2': '实例'}];
if (curProvider.supports_lightsail) defs.push({key: 'lightsail', label: 'Lightsail'});
if (curProvider.supports_cloudfront) defs.push({key: 'cloudfront', label: 'CloudFront'});
if (curProvider.supports_billing) defs.push({key: 'billing', label: '账单'});
if (curProvider.supports_quotas) defs.push({key: 'quotas', label: '配额'});
if (curProvider.supports_subscription) defs.push({key: 'subscription', label: '订阅'});
if (curProvider.id === 'azure' || curProvider.id === 'oci') defs.push({key: 'traffic', label: '流量控制'});
if (curProvider.id === 'oci') defs.push({key: 'security', label: '安全组'});
if (curProvider.id === 'azure') defs.push({key: 'foundry', label: 'Foundry'});
if (curProvider.id === 'azure') defs.push({key: 'rgroups', label: '资源组'});
if (!defs.find(d => d.key === curTab)) curTab = 'instances';
const tabIcons = {instances: '🖥️', lightsail: '💡', cloudfront: '🌐', billing: '💰',
  quotas: '📊', subscription: '📄', traffic: '🚦', security: '🛡️', foundry: '🧠', rgroups: '📁'};
document.getElementById('tabs').innerHTML = defs.map(d =>
`<div class="tab${d.key === curTab? ' active': ''}" onclick="switchTab('${d.key}')">${tabIcons[d.key] || ''} ${d.label}</div>`).join('');
const isInst = curTab === 'instances';
document.getElementById('createBtn').style.display = isInst? '': 'none';
document.getElementById('snatchBtn').style.display =
(isInst && curProvider.supports_snatch)? '': 'none';
}

function switchTab(key) {
curTab = key;
renderTabs();
refreshCurTab();
syncHash();
}

function refreshCurTab() {
if (!curAccount) { renderEmpty(); return;}
if (curTab === 'billing') loadBilling();
else if (curTab === 'lightsail') loadLightsail();
else if (curTab === 'cloudfront') loadCloudFront();
else if (curTab === 'quotas') loadQuotas();
else if (curTab === 'subscription') loadSubscription();
else if (curTab === 'traffic') loadTrafficRules();
else if (curTab === 'security') loadSecurityRules();
else if (curTab === 'foundry') loadFoundry();
else if (curTab === 'rgroups') loadResourceGroups();
else loadInstances();
}

/* ---------- 流量控制 ---------- */
async function loadTrafficRules() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
try {
const rules = await api('GET', `/api/traffic-rules?account_id=${curAccount.id}`);
const metricName = {in: '入向', out: '出向', both: '双向'};
c.innerHTML = `<div style="margin-bottom:12px"><button class="btn sm" onclick="openTrafficRuleModal()">+ 添加规则</button>
<span style="color:var(--muted);font-size:12px;margin-left:8px">超限自动关机（释放资源），到期自动开机，TG 推送通知</span></div>` +
(rules.length? `<table><thead><tr><th>规则</th><th>实例</th><th>指标</th><th>阈值</th><th>超限关机时长</th><th>状态</th><th>操作</th></tr></thead><tbody>` +
rules.map(r => `<tr>
<td>${esc(r.name)}<br><span style="color:var(--faint);font-size:11px">${r.enabled? '启用': '停用'}</span></td>
<td style="font-size:12px">${esc(r.instance_name || r.instance_key)}</td>
<td>${metricName[r.metric] || r.metric} / ${r.window_hours}小时</td>
<td>${r.limit_gb} GB</td>
<td>${r.duration_hours} 小时</td>
<td>${r.state === 'triggered'? '<span class="badge b-stopped">已触发关机</span>': '<span class="badge b-running">正常</span>'}</td>
<td><div class="row-actions">
<button class="btn sm" onclick="toggleTrafficRule(${r.id}, ${r.enabled? 0: 1})">${r.enabled? '停用': '启用'}</button>
<button class="btn sm danger" onclick="delTrafficRule(${r.id})">删除</button>
</div></td></tr>`).join('') + '</tbody></table>'
: '<div class="empty">暂无流量规则</div>');
} catch (e) {
c.innerHTML = `<div class="empty">加载失败: ${esc(e.message)}</div>`;
}
}

async function openTrafficRuleModal() {
// 需要实例列表来选择
let insts = [];
try {
insts = await api('GET', `/api/accounts/${curAccount.id}/instances`);
} catch (e) { toast('获取实例列表失败: ' + e.message, true); return;}
if (!insts.length) { toast('该账号下没有实例', true); return;}
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>添加流量规则</h2>
<form id="trafficForm">
${formField({key: 'name', label: '规则名称', required: true, placeholder: '如：防跑流量'})}
${formField({key: 'instance_key', label: '实例', type: 'select',
options: insts.map(i => i.id), value: insts[0].id})}
${row({key: 'metric', label: '监控指标', type: 'select', options: ['out', 'in', 'both'], value: 'out'},
{key: 'window_hours', label: '统计窗口（小时）', type: 'number', value: '24'})}
${row({key: 'limit_gb', label: '流量阈值（GB）', type: 'number', required: true, placeholder: '如 100'},
{key: 'duration_hours', label: '关机时长（小时）', type: 'number', value: '24'})}
<div class="help" style="color:var(--muted);margin-bottom:14px">超限后自动关机（停止计费），到期自动开机并 TG 通知。</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">保存</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
const instMap = Object.fromEntries(insts.map(i => [i.id, i.name || i.id]));
document.getElementById('trafficForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
const ik = fd.get('instance_key');
try {
await api('POST', '/api/traffic-rules', {
account_id: curAccount.id,
instance_key: ik,
instance_name: instMap[ik] || ik,
name: (fd.get('name') || '').trim(),
metric: fd.get('metric'),
window_hours: parseInt(fd.get('window_hours')) || 24,
limit_gb: parseFloat(fd.get('limit_gb')) || 0,
duration_hours: parseInt(fd.get('duration_hours')) || 24,
});
toast('规则已添加'); closeModal(); loadTrafficRules();
} catch (err) { toast(err.message, true);}
};
}

async function toggleTrafficRule(id, enabled) {
try {
await api('PUT', `/api/traffic-rules/${id}`, {enabled});
loadTrafficRules();
} catch (e) { toast(e.message, true);}
}

async function delTrafficRule(id) {
if (!confirm('确定删除这条流量规则吗？')) return;
try {
await api('DELETE', `/api/traffic-rules/${id}`);
loadTrafficRules();
} catch (e) { toast(e.message, true);}
}

/* ---------- OCI 安全组（安全列表规则） ----------*/
let secInstId = '';
let secRules = [];
const SEC_PROTO = {tcp: 'TCP', udp: 'UDP', icmp: 'ICMP', all: '全部'};
const secDirName = d => d === 'ingress'? '入向': '出向';

async function loadSecurityRules() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
let insts;
try {
insts = await api('GET', `/api/accounts/${curAccount.id}/instances`);
} catch (e) { c.innerHTML = `<div class="empty">加载实例列表失败: ${esc(e.message)}</div>`; return;}
if (!insts.length) { c.innerHTML = '<div class="empty">该账号下没有实例</div>'; return;}
if (!secInstId || !insts.find(i => i.id === secInstId)) secInstId = insts[0].id;
try {
secRules = await api('GET', `/api/accounts/${curAccount.id}/security-rules?instance_id=${encodeURIComponent(secInstId)}`);
c.innerHTML = `<div style="margin-bottom:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<select id="secInstSel" onchange="secInstId=this.value;loadSecurityRules()" style="background:var(--bg);color:var(--text);border:1px solid var(--border2);border-radius:8px;padding:8px 10px">
${insts.map(i => `<option value="${esc(i.id)}"${i.id === secInstId? ' selected': ''}>${esc(i.name)}</option>`).join('')}
</select>
<button class="btn sm" onclick="openSecRuleModal()">+ 添加规则</button>
<span style="color:var(--muted);font-size:12px">安全列表规则，修改立即生效；删除前请确认影响</span></div>` +
(secRules.length? `<table><thead><tr><th>方向</th><th>协议</th><th>来源/目标</th><th>端口</th><th>描述</th><th>无状态</th><th>操作</th></tr></thead><tbody>` +
secRules.map((r, i) => `<tr>
<td>${secDirName(r.direction)}</td>
<td>${esc(SEC_PROTO[r.protocol] || r.protocol)}</td>
<td class="mono">${esc(r.source || r.destination || '-')}</td>
<td>${esc(r.ports || '全部')}</td>
<td style="font-size:12px">${esc(r.description || '-')}</td>
<td>${r.stateless? '是': '否'}</td>
<td><div class="row-actions">
<button class="btn sm danger" onclick="delSecRule(${i})">删除</button>
</div></td></tr>`).join('') + '</tbody></table>'
: '<div class="empty">该实例暂无安全规则</div>');
} catch (e) {
c.innerHTML = `<div class="empty">加载失败: ${esc(e.message)}<br><button class="btn" onclick="loadSecurityRules()">重试</button></div>`;
}
}

async function delSecRule(i) {
const r = secRules[i];
if (!r) return;
const summary = `${secDirName(r.direction)} ${SEC_PROTO[r.protocol] || r.protocol} ${r.source || r.destination || ''} 端口 ${r.ports || '全部'}`;
if (!confirm(`确定删除这条安全规则吗？\n${summary}\n删除后立即生效，可能影响实例访问。`)) return;
try {
await api('DELETE', `/api/accounts/${curAccount.id}/security-rules`, {
instance_id: secInstId,
rule: {direction: r.direction, protocol: r.protocol,
source: r.source || r.destination || '',
port_min: r.port_min, port_max: r.port_max},
});
toast('已删除'); loadSecurityRules();
} catch (e) { toast(e.message, true);}
}

function openSecRuleModal() {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>添加安全规则 · 实例 <span class="mono" style="font-size:13px">${esc(secInstId.slice(-12))}</span></h2>
<form id="secRuleForm">
${row({key: 'direction', label: '方向', type: 'select', options: ['ingress', 'egress'], value: 'ingress'},
{key: 'protocol', label: '协议', type: 'select', options: ['tcp', 'udp', 'icmp', 'all'], value: 'tcp'})}
${formField({key: 'source', label: '来源 CIDR（出向规则为目标 CIDR）', required: true, placeholder: '如 0.0.0.0/0'})}
${row({key: 'port_min', label: '起始端口', type: 'number', placeholder: '如 80'},
{key: 'port_max', label: '结束端口', type: 'number', placeholder: '如 80'})}
${formField({key: 'description', label: '描述（可选）', placeholder: '如 开放web端口'})}
<div class="help" style="color:var(--muted);margin-bottom:6px">入向规则控制谁能访问实例；来源 0.0.0.0/0 表示对公网开放。TCP/UDP 需填端口范围，ICMP/ALL 不需要。</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">添加</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
const form = document.getElementById('secRuleForm');
const togglePorts = () => {
const dis = form.querySelector('[name="protocol"]').value === 'icmp'
|| form.querySelector('[name="protocol"]').value === 'all';
form.querySelector('[name="port_min"]').disabled = dis;
form.querySelector('[name="port_max"]').disabled = dis;
};
form.querySelector('[name="protocol"]').onchange = togglePorts;
togglePorts();
form.onsubmit = async e => {
e.preventDefault();
const fd = new FormData(form);
const protocol = fd.get('protocol');
const rule = {
direction: fd.get('direction'),
protocol,
source: (fd.get('source') || '').trim(),
port_min: (protocol === 'tcp' || protocol === 'udp')? (parseInt(fd.get('port_min'), 10) || null): null,
port_max: (protocol === 'tcp' || protocol === 'udp')? (parseInt(fd.get('port_max'), 10) || null): null,
description: (fd.get('description') || '').trim(),
};
if (!rule.source) { toast('请填写来源 CIDR', true); return;}
if ((protocol === 'tcp' || protocol === 'udp') && (rule.port_min == null || rule.port_max == null)) {
toast('请填写端口范围', true); return;}
// 放行全部端口：必须两次确认
const isAllPorts = protocol === 'all'
|| (rule.port_min === 1 && rule.port_max === 65535);
if (isAllPorts) {
if (!confirm('⚠️ 风险提示：即将放行全部端口（1-65535），实例将对公网完全暴露，存在被攻击/挖矿等严重安全风险。\n确定要继续吗？')) return;
const ans = prompt('再次确认：请输入 YES 以放行全部端口');
if (ans === null) return;
if (ans.trim().toUpperCase() !== 'YES') { toast('两次确认不一致，已取消提交', true); return;}
}
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/security-rules`, {instance_id: secInstId, rule});
toast(r.message || '规则已添加'); closeModal(); loadSecurityRules();
} catch (err) { toast(err.message, true);}
};
}

/* ---------- 账号存活天数（按云账号创建时间） ---------- */
const aliveDays = a => a.cloud_created_at != null? Math.max(0, Math.floor((Date.now() / 1000 - a.cloud_created_at) / 86400)): null;
const aliveLabel = a => { const d = aliveDays(a); return d == null? '': `（存活${d}天）`; };
const fmtDate = ts => { const d = new Date(ts * 1000); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

async function loadAccounts(selectId) {
accounts = await api('GET', `/api/accounts?provider=${curProvider.id}`);
const sel = document.getElementById('accountSel');
sel.innerHTML = accounts.map(a => `<option value="${a.id}">${esc(a.name)}${esc(aliveLabel(a))}</option>`).join('')
|| '<option value="">（暂无账号）</option>';
curAccount = accounts.find(a => String(a.id) === String(selectId || sel.value)) || accounts[0] || null;
if (curAccount) sel.value = curAccount.id;
renderTabs();
refreshCurTab();
syncHash();
}

function onAccountChange(tab) {
const id = document.getElementById('accountSel').value;
curAccount = accounts.find(a => String(a.id) === id) || null;
curTab = tab || 'instances';
renderTabs();
refreshCurTab();
syncHash();
}

function renderEmpty() {
document.getElementById('content').innerHTML =
`<div class="empty">还没有添加 ${esc(curProvider.name)} 账号<br>
<button class="btn primary" onclick="openAccountModal()">添加账号</button></div>`;
}

async function loadInstances() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
try {
instances = await api('GET', `/api/accounts/${curAccount.id}/instances`);
} catch (e) { c.innerHTML = `<div class="empty">加载失败: ${esc(e.message)}<br><button class="btn" onclick="loadInstances()">重试</button></div>`; return;}
if (!instances.length) { c.innerHTML = '<div class="empty">该账号下没有实例</div>'; return;}
const badge = s => `<span class="badge b-${s}">${s}</span>`;
c.innerHTML = `<div style="display:flex;justify-content:flex-end;margin-bottom:8px">
<button class="btn sm" onclick="openDnsMappingModal()">🔗 Cloudflare DNS 映射</button></div>` +
`<table><thead><tr>
<th>名称</th><th>状态</th><th>规格</th><th>公网 IP</th><th>内网 IP</th>
<th>地域</th><th>创建时间</th><th>操作</th></tr></thead><tbody>` +
instances.map((it, i) => `<tr>
<td>${esc(it.name)}<br><span class="mono">${esc(it.id.slice(-12))}</span></td>
<td>${badge(it.status)}<br><span style="color:var(--faint);font-size:11px">${esc(it.status_text || '')}</span></td>
<td>${esc(it.shape)}${it.cpu? `<br><span style="color:var(--muted)">${esc(it.cpu)}C / ${esc(it.memory)}G</span>`: ''}</td>
<td class="mono">${esc(it.public_ip || '-')}</td>
<td class="mono">${esc(it.private_ip || '-')}${it.ipv6? `<br>${esc(it.ipv6)}`: ''}</td>
<td>${esc(it.region || '')}${it.zone? `<br><span style="color:var(--faint);font-size:11px">${esc(it.zone)}</span>`: ''}</td>
<td style="font-size:12px">${fmtTime(it.created)}</td>
<td><div class="row-actions">${curProvider.actions.map(a =>
`<button class="btn sm${a.danger? ' danger': ''}" onclick="doAction(${i}, '${a.key}')">${a.label}</button>`
).join('')}</div></td></tr>`).join('') + '</tbody></table>';
}

async function doAction(idx, action) {
const inst = instances[idx];
const meta = curProvider.actions.find(a => a.key === action);
if (action === 'update_shape') { openShapeModal(inst); return;}
if (action === 'rename') {
openParamModal('改名', inst, 'rename',
[{key: 'new_name', label: '新名称', required: true, placeholder: '输入新的实例名称'}], '');
return;}
if (action === 'extend_disk') {
openParamModal('磁盘扩容', inst, 'extend_disk',
[{key: 'size_gb', label: '目标大小（GB）', type: 'number', required: true, placeholder: '如 100'}],
'只能调大不能调小，扩容后需在系统内手动扩展分区。');
return;}
if (action === 'resize') {
openParamModal('改配置', inst, 'resize',
[{key: 'size', label: '目标规格', required: true, placeholder: '如 Standard_B2s'}],
'会先释放资源（deallocate，停止计费）再变更规格，完成后自动重启。部分规格变更可能不支持，请确认该规格在当前区域可用。');
return;}
if (action === 'open_port') {
openParamModal('开放端口', inst, 'open_port',
[{key: 'port', label: '端口', type: 'number', required: true, placeholder: '如 8080'}],
'将在安全组/安全列表放行该 TCP 端口（来源 0.0.0.0/0）。');
return;}
if (action === 'change_ip') { openChangeIpModal(inst); return;}
if (action === 'boot_volume_vpus') { openVpusModal(inst); return;}
if (action === 'terminate' && curProvider.id === 'oci') { openTerminateModal(inst); return;}
const needConfirm = meta.danger || action === 'change_ip' || action === 'terminate';
const tips = {terminate: '确定要终止/删除该实例吗？此操作不可恢复！',
change_ip: '更换公网 IP 后原 IP 会释放，确定继续吗？'};
if (needConfirm &&!confirm(tips[action] || `确定执行「${meta.label}」吗？`)) return;
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/action`,
{instance: inst, action, params: {}});
toast('任务已提交，在任务历史中查看进度');
toggleDrawer(true); trackJob(r.job_id);
} catch (e) { toast(e.message, true);}
}

/* ---------- 账单 ---------- */
function eduHtml(b) {
if (curProvider.id !== 'azure') return '';
if (!b.edu_expires_at) {
return `<div style="margin:12px 0"><button class="btn sm" onclick="setEduExpires()">设置教育优惠到期日</button>
<span style="color:var(--faint);font-size:12px;margin-left:8px">Azure 学生订阅 $100 额度，到期日可在 Sponsorships 门户查看；如已设置云账号创建时间，会自动按 +12 个月预估</span></div>`;
}
const color = b.edu_expired ? 'var(--red2)' : (b.edu_expiring_soon ? 'var(--yellow)' : 'var(--green)');
const status = b.edu_expired ? '已过期' : `剩余 ${b.edu_days_left} 天`;
const estTag = b.edu_estimated ? '（预估：按账号创建时间+12个月算）' : '';
return `<div style="display:flex;gap:24px;margin:12px 0;padding:12px 16px;background:var(--card);border-radius:14px;box-shadow:var(--card-shadow);flex-wrap:wrap;align-items:center">
<div><div style="color:var(--muted);font-size:12px">🎓 教育优惠到期日${estTag}</div>
<div style="font-size:18px;color:${color}">${esc(b.edu_expires)}（${status}）</div></div>
<div style="margin-left:auto;display:flex;gap:8px">
<button class="btn sm" onclick="setEduExpires()">修改</button>
<a class="btn sm" href="https://azure.microsoft.com/free/students/" target="_blank" style="text-decoration:none">去续期</a>
</div></div>
${b.edu_expiring_soon && !b.edu_expired ? '<div class="help" style="color:var(--yellow);font-size:12px;margin-bottom:12px">⚠ 教育优惠 30 天内到期，到期后订阅会被禁用。如仍是学生身份请及时续期。</div>' : ''}
${b.edu_expired ? '<div class="help" style="color:var(--red2);font-size:12px;margin-bottom:12px">⚠ 教育优惠已过期，请续期或升级为即用即付。</div>' : ''}`;
}

async function setEduExpires() {
const cur = prompt('教育优惠到期日（格式 YYYY-MM-DD，留空清除）：');
if (cur === null) return;
let ts = null;
if (cur.trim()) {
const m = cur.trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
if (!m) { toast('日期格式不正确', true); return; }
ts = new Date(`${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}T00:00:00`).getTime() / 1000;
}
try {
await api('PUT', `/api/accounts/${curAccount.id}/edu-expires-at`, {timestamp: ts});
toast('已保存');
loadBilling();
} catch (e) { toast(e.message, true); }
}

async function loadBilling() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
try {
const b = await api('GET', `/api/accounts/${curAccount.id}/billing`);
const money = v => (b.currency? b.currency + ' ': '') + Number(v).toFixed(2);
window._manualCredits = b.manual_credits || [];
let creditHtml = '';
const apiCredits = b.credits || [];
const manualCredits = b.manual_credits || [];
const allCredits = [...apiCredits, ...manualCredits];
if (allCredits.length) {
const apiRemain = b.credit_remaining || 0;
const apiInit = b.credit_initial || 0;
const manTotal = manualCredits.reduce((s, c) => s + c.initial, 0);
const manRemain = b.manual_remaining != null? b.manual_remaining: manTotal;
creditHtml = `<div style="display:flex;gap:24px;margin:12px 0;padding:12px 16px;background:var(--card);border-radius:14px;box-shadow:var(--card-shadow);flex-wrap:wrap">
<div><div style="color:var(--muted);font-size:12px">Credit 剩余（合计·自动更新）</div>
<div style="font-size:18px;color:var(--green)">${money(apiRemain + manRemain)}</div></div>
${apiCredits.length? `<div><div style="color:var(--muted);font-size:12px">API 已用</div>
<div style="font-size:18px;color:var(--yellow)">${money(apiInit - apiRemain)}</div></div>`: ''}
${manualCredits.length? `<div><div style="color:var(--muted);font-size:12px">手动已用（累计抵扣）</div>
<div style="font-size:18px;color:var(--yellow)">${money(b.manual_applied || 0)}</div></div>`: ''}
<div><div style="color:var(--muted);font-size:12px">本月抵扣</div>
<div style="font-size:18px">-${money(b.credit_used || 0)}</div></div>
<div style="margin-left:auto;align-self:center">
<button class="btn sm" onclick="addManualCredit()">+ 添加 Credit</button></div></div>
<div class="help" style="color:var(--faint);font-size:12px;margin-bottom:12px">手动 credit 的剩余 = 总额 − Cost Explorer 累计抵扣（从最早生效日算起，约 24 小时延迟），每天自动更新</div>
<table><thead><tr><th>Credit</th><th style="width:110px">总额</th><th style="width:110px">剩余</th>
<th style="width:120px">到期日</th><th style="width:90px">状态</th><th style="width:70px"></th></tr></thead><tbody>` +
allCredits.map(cr => `<tr><td>${esc(cr.name)}</td><td class="mono">${money(cr.initial)}</td>
<td class="mono" style="color:var(--green)">${money(cr.remaining)}<br>${usageBar(cr.initial - cr.remaining, cr.initial)}</td>
<td class="mono">${esc(cr.expires)}</td>
<td>${esc(cr.status)}${cr.source === 'manual'? '（手动）': ''}</td>
<td>${cr.source === 'manual'? `<button class="btn sm" onclick="editManualCredit(${cr.id})">编辑</button>
<button class="btn sm danger" onclick="delManualCredit(${cr.id})">删除</button>`: ''}</td></tr>`).join('') + '</tbody></table>';
} else {
creditHtml = `<div style="margin:12px 0"><button class="btn sm" onclick="addManualCredit()">+ 添加 Credit</button>
<span style="color:var(--faint);font-size:12px;margin-left:8px">API 未返回 credit 明细（如教程奖励类），可手动添加</span></div>`;
if (b.credit_used > 0) {
creditHtml += `<div style="display:flex;gap:24px;margin:12px 0;padding:12px 16px;background:var(--card);border-radius:14px;box-shadow:var(--card-shadow)">
<div><div style="color:var(--muted);font-size:12px">Credit 抵扣（本月）</div>
<div style="font-size:18px;color:var(--green)">-${money(b.credit_used)}</div></div></div>`;
}
}
c.innerHTML = `<div class="bill-total"><div class="amount">${money(b.total)}</div>
<div class="meta">统计周期：${esc(b.period)}${b.note? '<br>' + esc(b.note): ''}${b._cache_date? `<br><span style="color:var(--faint)">AWS 账单每月 15 号/月末更新，当前数据更新于 ${esc(b._cache_date)}</span>`: ''}</div></div>` +
eduHtml(b) +
creditHtml +
(b.services && b.services.length
? `<table><thead><tr><th>服务</th><th style="width:160px">费用</th></tr></thead><tbody>` +
b.services.map(s => `<tr><td>${esc(s.name)}</td><td class="mono">${money(s.cost)}</td></tr>`).join('') +
'</tbody></table>'
: '<div class="empty">本周期暂无费用明细</div>');
} catch (e) {
c.innerHTML = `<div class="empty">加载失败: ${esc(e.message)}<br><button class="btn" onclick="loadBilling()">重试</button></div>`;
}
}

async function addManualCredit() {
const name = prompt('Credit 名称（如：Explore AWS: Launch an instance using EC2）：');
if (name === null || !name.trim()) return;
const amt = prompt('金额（美元数字，如 20）：');
if (amt === null) return;
const amount = Number(amt.trim());
if (!isFinite(amount) || amount <= 0) { toast('金额无效', true); return;}
const exp = prompt('到期日（格式 YYYY-MM-DD，留空则不设）：');
let expires_at = null;
if (exp !== null && exp.trim()) {
const m = exp.trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
if (!m) { toast('日期格式不正确', true); return;}
expires_at = new Date(`${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}T00:00:00`).getTime() / 1000;
}
const st = prompt('生效日期（格式 YYYY-MM-DD，留空则为今天）：');
let start_at = null;
if (st !== null && st.trim()) {
const m2 = st.trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
if (!m2) { toast('日期格式不正确', true); return;}
start_at = new Date(`${m2[1]}-${m2[2].padStart(2, '0')}-${m2[3].padStart(2, '0')}T00:00:00`).getTime() / 1000;
}
try {
await api('POST', `/api/accounts/${curAccount.id}/credits-manual`, {name: name.trim(), amount, expires_at, start_at});
toast('已添加'); loadBilling();
} catch (e) { toast(e.message, true);}
}

async function delManualCredit(id) {
if (!confirm('确定删除这条 Credit 记录吗？')) return;
try {
await api('DELETE', `/api/accounts/${curAccount.id}/credits-manual/${id}`);
toast('已删除'); loadBilling();
} catch (e) { toast(e.message, true);}
}

function _fmtDateInput(ts) {
if (!ts) return '';
const d = new Date(ts * 1000);
return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function _parseDateInput(s) {
if (!s || !s.trim()) return null;
const m = s.trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
if (!m) return undefined;
return new Date(`${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}T00:00:00`).getTime() / 1000;
}

async function editManualCredit(id) {
const cr = (window._manualCredits || []).find(c => c.id === id);
if (!cr) { toast('找不到该记录', true); return;}
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>编辑 Credit</h2>
<form id="creditEditForm">
${formField({key: 'name', label: 'Credit 名称', required: true, value: cr.name})}
${formField({key: 'amount', label: '金额（美元）', type: 'number', required: true, value: cr.initial})}
${row({key: 'start_at', label: '生效日期', placeholder: 'YYYY-MM-DD', value: _fmtDateInput(cr.start_at)},
{key: 'expires_at', label: '到期日', placeholder: 'YYYY-MM-DD，可空', value: _fmtDateInput(cr.expires_at_raw)})}
<div class="help" style="color:var(--muted);margin-bottom:14px">修改生效日期会重新计算抵扣基线。</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">保存</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('creditEditForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
const amount = Number((fd.get('amount') || '').trim());
if (!isFinite(amount) || amount <= 0) { toast('金额无效', true); return;}
const start_at = _parseDateInput(fd.get('start_at'));
const expires_at = _parseDateInput(fd.get('expires_at'));
if (start_at === undefined || expires_at === undefined) { toast('日期格式不正确（YYYY-MM-DD）', true); return;}
try {
await api('PUT', `/api/accounts/${curAccount.id}/credits-manual/${id}`,
{name: (fd.get('name') || '').trim(), amount, start_at, expires_at});
toast('已保存'); closeModal(); loadBilling();
} catch (err) { toast(err.message, true);}
};
}

/* ---------- 配额 / 订阅 ---------- */
async function loadQuotas() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
try {
const q = await api('GET', `/api/accounts/${curAccount.id}/quotas`);
c.innerHTML = (q.groups || []).map(g =>
`<h3 style="margin:18px 0 10px;font-size:14px;color:var(--text2)">${esc(g.title)}</h3>
<table><thead><tr><th>项目</th><th>详情</th></tr></thead><tbody>` +
(g.items || []).map(it => `<tr><td class="mono">${esc(it.name)}</td><td>${esc(it.detail)}</td></tr>`).join('') +
'</tbody></table>').join('') +
(q.note? `<div class="help" style="color:var(--faint);margin-top:12px;font-size:12px">${esc(q.note)}</div>`: '') ||
'<div class="empty">暂无配额数据</div>';
} catch (e) {
c.innerHTML = `<div class="empty">加载失败: ${esc(e.message)}<br><button class="btn" onclick="loadQuotas()">重试</button></div>`;
}
}

async function loadSubscription() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
try {
const s = await api('GET', `/api/accounts/${curAccount.id}/subscription`);
c.innerHTML = `<table><thead><tr><th>项目</th><th>详情</th></tr></thead><tbody>` +
(s.items || []).map(it => `<tr><td>${esc(it.name)}</td><td class="mono">${esc(it.detail)}</td></tr>`).join('') +
'</tbody></table>' +
(s.note? `<div class="help" style="color:var(--faint);margin-top:12px;font-size:12px">${esc(s.note)}</div>`: '');
} catch (e) {
c.innerHTML = `<div class="empty">加载失败: ${esc(e.message)}<br><button class="btn" onclick="loadSubscription()">重试</button></div>`;
}
}

/* ---------- Azure Foundry ---------- */
const FOUNDRY_REGIONS = ['swedencentral', 'eastus2', 'eastus', 'westeurope', 'japaneast', 'southeastasia'];
let foundryRegion = 'swedencentral';

async function loadFoundry() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
let q;
try {
q = await api('GET', `/api/accounts/${curAccount.id}/foundry-quotas?region=${encodeURIComponent(foundryRegion)}`);
} catch (e) {
q = {error: e.message};
}
c.innerHTML = `<div style="margin-bottom:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<select id="foundryRegionSel" onchange="foundryRegion=this.value;loadFoundry()" style="background:var(--bg);color:var(--text);border:1px solid var(--border2);border-radius:8px;padding:8px 10px">
${FOUNDRY_REGIONS.map(r => `<option value="${r}"${r === foundryRegion? ' selected': ''}>${esc(r)}</option>`).join('')}
</select>
<button class="btn sm" onclick="loadFoundry()">刷新配额</button>
</div>` +
(q.error
? `<div class="empty" style="color:var(--muted)">配额查询失败: ${esc(q.error)}</div>`
: ((q.quotas || []).length
? `<table><thead><tr><th>配额项</th><th>已用</th><th>上限</th></tr></thead><tbody>` +
(q.quotas || []).map(it => `<tr><td>${esc(it.name)}</td>
<td>${esc(String(it.used))}<br>${usageBar(Number(it.used) || 0, Number(it.limit) || 0)}</td>
<td>${esc(String(it.limit))}</td></tr>`).join('') + '</tbody></table>'
: '<div class="empty">该区域暂无配额数据</div>')) +
`<h3 style="margin:18px 0 10px;font-size:14px;color:var(--text2)">部署模型</h3>
<form id="foundryForm">
${row({key: 'account_name', label: 'AI Services 账号名', placeholder: '留空用默认 tricloud-ai'},
{key: 'region', label: '区域', type: 'select', options: FOUNDRY_REGIONS, value: foundryRegion})}
${formField({key: 'model_name', label: '模型名', placeholder: '默认 gpt-4o'})}
<div class="help" style="color:var(--muted);margin-bottom:14px">创建/更新 AI Services 账号并部署一个模型（默认 gpt-4o）。需要订阅级别的 Cognitive Services 权限。</div>
<div class="modal-actions">
<button type="submit" class="btn primary" id="foundryDeployBtn">部署</button>
</div>
</form>
<div id="foundryResult" style="margin-top:12px"></div>`;
document.getElementById('foundryForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
const btn = document.getElementById('foundryDeployBtn');
btn.disabled = true;
const out = document.getElementById('foundryResult');
out.innerHTML = '<div class="empty">部署中，请稍候…</div>';
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/foundry-deploy`, {
account_name: (fd.get('account_name') || '').trim(),
region: (fd.get('region') || foundryRegion).trim(),
model_name: (fd.get('model_name') || '').trim(),
});
out.innerHTML = `<div class="help" style="color:var(--text);white-space:pre-wrap">${esc(r.result || '部署完成')}</div>` +
((r.logs || []).map(l => `<div style="color:var(--faint);font-size:11px">${esc(l)}</div>`).join(''));
foundryRegion = (fd.get('region') || foundryRegion).trim();
} catch (err) {
out.innerHTML = `<div class="empty" style="color:var(--muted)">部署失败: ${esc(err.message)}</div>`;
} finally {
btn.disabled = false;
}
};
}

/* ---------- Azure 资源组 ---------- */
async function loadResourceGroups() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
try {
const r = await api('GET', `/api/accounts/${curAccount.id}/resource-groups`);
const groups = r.groups || [];
c.innerHTML = (groups.length
? `<table><thead><tr><th>资源组</th><th>区域</th><th>VM 数</th><th>操作</th></tr></thead><tbody>` +
groups.map(g => `<tr>
<td class="mono">${esc(g.name)}</td>
<td>${esc(g.location || '-')}</td>
<td>${esc(String(g.vm_count != null? g.vm_count: 0))}</td>
<td><div class="row-actions">
<button class="btn sm danger" onclick="delResourceGroup('${esc(g.name)}')">删除</button>
</div></td></tr>`).join('') + '</tbody></table>'
: '<div class="empty">该账号下没有资源组</div>') +
`<div class="help" style="color:var(--faint);margin-top:12px;font-size:12px">删除资源组会一并删除组内所有资源（虚拟机、网络等），不可恢复。</div>`;
} catch (e) {
c.innerHTML = `<div class="empty">加载失败: ${esc(e.message)}<br><button class="btn" onclick="loadResourceGroups()">重试</button></div>`;
}
}

async function delResourceGroup(name) {
if (!confirm(`确定删除资源组 ${name} 吗？组内资源会一起删除！`)) return;
try {
await api('DELETE', `/api/accounts/${curAccount.id}/resource-groups/${encodeURIComponent(name)}`);
toast('资源组已删除');
loadResourceGroups();
} catch (e) { toast(e.message, true);}
}

/* ---------- Lightsail ---------- */const LS_REGIONS = ['us-east-1', 'us-east-2', 'us-west-2', 'eu-west-1', 'eu-west-2',
'eu-west-3', 'eu-central-1', 'ap-southeast-1', 'ap-southeast-2',
'ap-northeast-1', 'ap-northeast-2', 'ap-south-1', 'ca-central-1'];
const LS_REGION_CITY = {'us-east-1': '美东·弗吉尼亚', 'us-east-2': '美东·俄亥俄',
'us-west-2': '美西·俄勒冈', 'eu-west-1': '欧洲·爱尔兰', 'eu-west-2': '欧洲·伦敦',
'eu-west-3': '欧洲·巴黎', 'eu-central-1': '欧洲·法兰克福',
'ap-southeast-1': '亚太·新加坡', 'ap-southeast-2': '亚太·悉尼',
'ap-northeast-1': '亚太·东京', 'ap-northeast-2': '亚太·首尔',
'ap-south-1': '亚太·孟买', 'ca-central-1': '加拿大·中部'};
const lsRegionLabel = r => LS_REGION_CITY[r]? `${r}（${LS_REGION_CITY[r]}）`: r;
let lsRegion = '';

async function loadLightsail() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
try {
const list = await api('GET', `/api/accounts/${curAccount.id}/lightsail?region=${encodeURIComponent(lsRegion)}`);
const badge = s => {
const cls = s === 'running'? 'b-running': (s === 'stopped'? 'b-stopped': 'b-unknown');
return `<span class="badge ${cls}">${esc(s || 'unknown')}</span>`;
};
c.innerHTML = `<div style="margin-bottom:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<select id="lsRegionSel" onchange="lsRegion=this.value;loadLightsail()" style="background:var(--bg);color:var(--text);border:1px solid var(--border2);border-radius:8px;padding:8px 10px">
<option value="">全部区域（自动扫描）</option>
${LS_REGIONS.map(r => `<option value="${r}"${r === lsRegion? ' selected': ''}>${esc(lsRegionLabel(r))}</option>`).join('')}
</select>
<button class="btn sm" onclick="openLightsailCreateModal()">创建实例</button></div>` +
(list.length
? `<table><thead><tr><th>名称</th><th>状态</th><th>套餐</th><th>公网 IP</th><th>内网 IP</th>
<th>区域</th><th>创建时间</th><th>操作</th></tr></thead><tbody>` +
list.map(it => `<tr>
<td>${esc(it.name)}</td>
<td>${badge(it.state)}</td>
<td>${esc(it.bundle)}<br><span style="color:var(--faint);font-size:11px">${esc(it.blueprint)}${it.cpu? `<br>${esc(it.cpu)}C${it.memory? ' / ' + esc(it.memory) + 'G': ''}`: ''}</span></td>
<td class="mono">${esc(it.public_ip || '-')}${it.ipv6? `<br>${esc(it.ipv6)}`: ''}</td>
<td class="mono">${esc(it.private_ip || '-')}</td>
<td>${esc(lsRegionLabel(it.region))}${it.zone? `<br><span style="color:var(--faint);font-size:11px">${esc(it.zone)}</span>`: ''}</td>
<td style="font-size:12px">${fmtTime(it.created)}</td>
<td><div class="row-actions">
${it.state === 'running'
? `<button class="btn sm" onclick="lsAction('${esc(it.name)}','reboot','${esc(it.region)}')">重启</button>
<button class="btn sm" onclick="lsChangeIp('${esc(it.name)}','${esc(it.region)}')">换 IP</button>
<button class="btn sm danger" onclick="lsAction('${esc(it.name)}','stop','${esc(it.region)}')">停止</button>`
: `<button class="btn sm" onclick="lsAction('${esc(it.name)}','start','${esc(it.region)}')">启动</button>
<button class="btn sm" onclick="lsChangeIp('${esc(it.name)}','${esc(it.region)}')">换 IP</button>`}
</div></td></tr>`).join('') + '</tbody></table>'
: '<div class="empty">该范围下没有 Lightsail 实例</div>');
} catch (e) {
c.innerHTML = `<div class="empty">加载失败: ${esc(e.message)}<br><button class="btn" onclick="loadLightsail()">重试</button></div>`;
}
}

async function lsAction(name, action, region) {
if (action === 'stop' && !confirm(`确定停止 Lightsail 实例 ${name} 吗？`)) return;
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/lightsail/action`,
{name, action, region});
toast(r.message);
loadLightsail();
} catch (e) { toast(e.message, true);}
}

async function lsChangeIp(name, region) {
if (!confirm(`确定更换 Lightsail 实例 ${name} 的公网 IP 吗？\n动态 IP 会停机重启约 1-2 分钟；静态 IP 会重新分配绑定。`)) return;
try {
await api('POST', `/api/accounts/${curAccount.id}/lightsail/change-ip`, {name, action: 'change_ip', region});
toast('更换 IP 任务已提交，可在任务历史查看进度');
} catch (e) { toast(e.message, true);}
}

async function openLightsailCreateModal() {
if (!curAccount) { toast('请先添加账号', true); return;}
const box = document.getElementById('modalBox');
const initRegion = lsRegion || 'ap-northeast-1';
box.innerHTML = `<h2>创建 Lightsail 实例</h2>
<form id="lsCreateForm">
${formField({key: 'name', label: '实例名', placeholder: '留空自动生成'})}
${row({key: 'region', label: '区域', type: 'select', options: LS_REGIONS.map(lsRegionLabel), value: lsRegionLabel(initRegion)},
{key: 'zone', label: '可用区', type: 'select', options: []})}
${row({key: 'blueprint', label: '系统镜像', type: 'select', options: []},
{key: 'bundle', label: '套餐', type: 'select', options: []})}
${formField({key: 'key_pair', label: '密钥对（可选）', placeholder: '已有的 Lightsail 密钥对名，留空则不绑定', help: '留空则不绑定密钥对'})}
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">提交创建（后台执行）</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
const form = document.getElementById('lsCreateForm');
async function fillOpts(region) {
const sel = n => form.querySelector(`[name="${n}"]`);
try {
const opts = await api('GET', `/api/accounts/${curAccount.id}/lightsail/options?region=${encodeURIComponent(region)}`);
sel('zone').innerHTML = opts.zones.map(z => `<option value="${esc(z)}">${esc(z)}</option>`).join('');
sel('blueprint').innerHTML = opts.blueprints.map(b => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join('');
const ub = opts.blueprints.find(b => /ubuntu/i.test(b.id));
if (ub) sel('blueprint').value = ub.id;
sel('bundle').innerHTML = opts.bundles.map(b => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join('');
} catch (e) { toast(e.message, true);}
}
form.querySelector('[name="region"]').onchange = e => fillOpts(e.target.value.split('（')[0]);
await fillOpts(initRegion);
form.onsubmit = async e => {
e.preventDefault();
const fd = new FormData(form), o = {};
['name', 'region', 'zone', 'blueprint', 'bundle', 'key_pair'].forEach(k => o[k] = (fd.get(k) || '').trim());
o.region = o.region.split('（')[0]; // 去掉城市备注，取区域码
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/lightsail/create`, o);
closeModal(); toast('创建任务已提交'); toggleDrawer(true); trackJob(r.job_id);
} catch (err) { toast(err.message, true);}
};
}

/* ---------- CloudFront ---------- */
async function loadCloudFront() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
try {
const list = await api('GET', `/api/accounts/${curAccount.id}/cloudfront`);
const header = `<div style="margin-bottom:12px"><button class="btn sm" onclick="openCfCreateModal()">创建分发</button></div>`;
const planBadge = p => p === 'paygo'
? '<span style="color:var(--muted);font-size:12px">按量付费</span>'
: `<span class="badge b-running">${esc(p)}</span>`;
c.innerHTML = header + (list.length
? `<table><thead><tr><th>分发</th><th>状态</th><th>域名/别名</th><th>源站</th><th>价格等级</th><th>套餐</th><th>操作</th></tr></thead><tbody>` +
list.map(d => `<tr>
<td><span class="mono">${esc(d.id)}</span><br><span style="color:var(--faint);font-size:11px">${esc(d.domain)}</span>
${d.comment? `<br><span style="font-size:12px">${esc(d.comment)}</span>`: ''}</td>
<td>${d.enabled? '<span class="badge b-running">已启用</span>': '<span class="badge b-stopped">已停用</span>'}
<br><span style="color:var(--faint);font-size:11px">${esc(d.status)}</span></td>
<td style="font-size:12px">${d.aliases.map(esc).join('<br>') || '-'}</td>
<td style="font-size:12px" class="mono">${d.origins.map(esc).join('<br>') || '-'}</td>
<td>${esc(d.price_class || '-')}</td>
<td>${planBadge(d.plan || 'paygo')}</td>
<td><div class="row-actions">
<button class="btn sm" onclick="openInvalidateModal('${esc(d.id)}')">刷新缓存</button>
<button class="btn sm" onclick="openCfEditModal('${esc(d.id)}')">编辑</button>
<button class="btn sm" onclick="openCfPlanModal('${esc(d.id)}','${esc(d.plan || 'paygo')}')">套餐</button>
${d.enabled
? `<button class="btn sm danger" onclick="cfToggle('${esc(d.id)}', false)">停用</button>`
: `<button class="btn sm" onclick="cfToggle('${esc(d.id)}', true)">启用</button>
<button class="btn sm danger" onclick="cfDelete('${esc(d.id)}')">删除</button>`}
</div></td></tr>`).join('') + '</tbody></table>'
: '<div class="empty">该账号下没有 CloudFront 分发</div>');
} catch (e) {
c.innerHTML = `<div class="empty">加载失败: ${esc(e.message)}<br><button class="btn" onclick="loadCloudFront()">重试</button></div>`;
}
}

function openInvalidateModal(distId) {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>刷新缓存 · <span class="mono">${esc(distId)}</span></h2>
<form id="invForm">
<div class="field"><label>路径（每行一个，留空 = 刷新全部 /*）</label>
<textarea name="paths" placeholder="/*&#10;/images/*"></textarea></div>
<div class="help" style="color:var(--muted);margin-bottom:14px">CloudFront 每月前 1000 条刷新路径免费，超出后按量收费。</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">提交刷新</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('invForm').onsubmit = async e => {
e.preventDefault();
const paths = new FormData(e.target).get('paths').split('\n').map(s => s.trim()).filter(Boolean);
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/cloudfront/invalidate`,
{distribution_id: distId, paths});
closeModal();
toast('刷新请求已提交');
} catch (err) { toast(err.message, true);}
};
}

async function cfToggle(distId, enabled) {
if (!confirm(`确定${enabled? '启用': '停用'}分发 ${distId} 吗？配置部署约需几分钟生效。`)) return;
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/cloudfront/toggle`,
{distribution_id: distId, enabled});
toast(r.message);
loadCloudFront();
} catch (e) { toast(e.message, true);}
}

async function cfDelete(distId) {
if (!confirm(`确定删除分发 ${distId} 吗？此操作不可恢复！`)) return;
if (!confirm(`再次确认：真的要删除 ${distId} 吗？`)) return;
try {
const r = await api('DELETE', `/api/accounts/${curAccount.id}/cloudfront/${distId}`);
toast(r.message);
loadCloudFront();
} catch (e) { toast(e.message, true);}
}

async function openCfEditModal(distId) {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>编辑分发</h2><div class="empty">加载配置中…</div>`;
document.getElementById('modalMask').classList.add('show');
try {
const cfg = await api('GET', `/api/accounts/${curAccount.id}/cloudfront/${distId}/config`);
box.innerHTML = `<h2>编辑分发 <span class="mono" style="font-size:13px">${esc(distId)}</span></h2>
<form id="cfEditForm">
${formField({key: 'comment', label: '备注', placeholder: '分发说明，可空', value: cfg.comment || ''})}
${formField({key: 'origin_domain', label: '源站域名', required: true, placeholder: '如 example.com（不带 https://）', value: cfg.origin_domain || ''})}
${row({key: 'price_class', label: '价格等级', type: 'select',
options: ['100', '200', 'All'], value: cfg.price_class || '100'},
{key: 'default_root_object', label: '默认根对象', placeholder: '如 index.html，可空', value: cfg.default_root_object || ''})}
<div class="help" style="color:var(--muted);margin-bottom:14px">修改后配置部署约需几分钟生效；源站只改第一个源站的域名。</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">保存</button>
</div></form>`;
document.getElementById('cfEditForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
const params = {
comment: (fd.get('comment') || '').trim(),
origin_domain: (fd.get('origin_domain') || '').trim(),
price_class: fd.get('price_class'),
default_root_object: (fd.get('default_root_object') || '').trim(),
};
if (!params.origin_domain) { toast('源站域名不能为空', true); return;}
try {
const r = await api('PUT', `/api/accounts/${curAccount.id}/cloudfront/${distId}`, params);
toast(r.message); closeModal(); loadCloudFront();
} catch (err) { toast(err.message, true);}
};
} catch (e) {
box.innerHTML = `<h2>编辑分发</h2><div class="empty">加载失败: ${esc(e.message)}</div>`;
}
}

const CF_PLANS = [
{key: 'paygo', label: '按量付费（Pay as you go）', desc: '按流量+请求数计费，无月费上限'},
{key: 'FREE', label: 'FREE — $0/月', desc: '100GB 流量 / 100万请求，含 WAF/DNS，无超额费'},
{key: 'PRO', label: 'PRO — $15/月', desc: '50TB 流量 / 1000万请求，含 WAF/DNS/日志，无超额费'},
{key: 'BUSINESS', label: 'BUSINESS — $200/月', desc: '50TB 流量 / 1.25亿请求，高级防护+机器人管理'},
{key: 'PREMIUM', label: 'PREMIUM — $1000/月起', desc: '50TB~600TB 可配， mission-critical 负载'},
];

function openCfPlanModal(distId, curPlan) {
const box = document.getElementById('modalBox');
const cur = (curPlan || 'paygo').toUpperCase();
box.innerHTML = `<h2>切换套餐 <span class="mono" style="font-size:13px">${esc(distId)}</span></h2>
<div class="help" style="color:var(--muted);margin-bottom:12px">当前：${cur === 'PAYGO' ? '按量付费' : esc(curPlan)}。包月套餐每个分发单独计费，切换立即生效并开始计费。</div>
<form id="cfPlanForm">
${CF_PLANS.map(p => `
<label style="display:block;border:1px solid var(--border2);border-radius:8px;padding:10px 12px;margin-bottom:8px;cursor:pointer">
<input type="radio" name="plan_tier" value="${p.key}" ${p.key.toUpperCase() === cur ? 'checked' : ''}
style="margin-right:8px">
<b>${esc(p.label)}</b><br>
<span style="color:var(--muted);font-size:12px;margin-left:24px">${esc(p.desc)}</span>
</label>`).join('')}
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">确认切换</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('cfPlanForm').onsubmit = async e => {
e.preventDefault();
const tier = new FormData(e.target).get('plan_tier');
if (tier.toUpperCase() === cur) { toast('已是当前套餐，无需切换'); return;}
if (tier !== 'paygo' && !confirm(`确定为分发 ${distId} 订阅 ${tier} 套餐吗？将立即开始按月计费。`)) return;
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/cloudfront/plan`,
{distribution_id: distId, plan_tier: tier});
toast(r.message); closeModal(); loadCloudFront();
} catch (err) { toast(err.message, true);}
};
}

function openCfCreateModal() {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>创建 CloudFront 分发</h2>
<form id="cfCreateForm">
${formField({key: 'origin_domain', label: '源站域名', required: true, placeholder: '如 example.com（不带 https://）'})}
${row({key: 'price_class', label: '价格等级', type: 'select',
options: ['100（北美+欧洲·最便宜）', '200（+亚洲）', 'all（全部边缘节点）'], value: '100（北美+欧洲·最便宜）'},
{key: 'comment', label: '备注（可选）', placeholder: '如 官网加速'})}
<div class="help" style="color:var(--muted);margin:-6px 0 14px">默认配置：回源走 HTTP、访客侧 HTTP 跳 HTTPS、缓存优化策略。分发部署约需 15 分钟。</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">提交创建</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('cfCreateForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
const origin = (fd.get('origin_domain') || '').trim();
if (!origin) { toast('请填写源站域名', true); return;}
let pc = (fd.get('price_class') || '100');
pc = pc.startsWith('200')? '200': pc.startsWith('all')? 'all': '100';
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/cloudfront/create`,
{origin_domain: origin, comment: (fd.get('comment') || '').trim(), price_class: pc});
closeModal(); toast('分发创建已提交'); loadCloudFront();
} catch (err) { toast(err.message, true);}
};
}

/* ---------- 账号管理 ---------- */
function fieldInput(f, val) {
const v = esc(val || '');
if (f.field_type === 'textarea')
return `<textarea name="${f.key}" placeholder="${esc(f.placeholder || '')}">${v}</textarea>`;
return `<input name="${f.key}" type="${f.field_type === 'password'? 'password': 'text'}"
placeholder="${esc(f.placeholder || '')}" value="${v}">`;
}

// 代理出口（可选）区；cur 传账号对象时回显已存配置（密码不回显）
function proxyFieldsHtml(cur) {
const c = cur || {};
const hasProxy = !!(c.proxy_url || '');
return `<div style="margin:16px 0 6px;font-size:13px;color:var(--text2)">代理出口（可选）</div>
<div class="field"><label>代理 URL</label>
<input name="proxy_url" autocomplete="off" value="${esc(c.proxy_url || '')}"
placeholder="如 http://host:port 或 socks5://host:port">
<div class="help">留空表示直连${hasProxy? '；清空并保存可移除代理': ''}</div></div>
<div class="field"><label>代理用户名</label>
<input name="proxy_user" autocomplete="off" value="${esc(c.proxy_user || '')}"
placeholder="代理无需认证时留空"></div>
<div class="field"><label>代理密码</label>
<input name="proxy_pass" type="password" autocomplete="new-password"
placeholder="${hasProxy? '已保存，留空保持不变': '代理需要认证时填写'}"></div>`;
}

function openAccountModal() {
const p = curProvider;
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>账号管理 · ${esc(p.name)}</h2>
<div style="margin-bottom:10px"><button class="btn sm" onclick="testAllAccounts()">🔍 一键测活（测试本云全部账号）</button>
<button class="btn sm" style="margin-left:8px" onclick="openRecycleBin()">🗑️ 回收站</button></div>
<div id="testAllResult"></div>
${accounts.map(a => { const d = aliveDays(a); return `<div style="display:flex;align-items:center;gap:8px;padding:9px 0;border-bottom:1px solid var(--border)">
<span style="flex:1">${esc(a.name)}<br><span style="color:var(--faint);font-size:12px">${
d != null? `存活 ${d} 天（${fmtDate(a.cloud_created_at)}创建） <a href="javascript:void(0)" onclick="setCloudCreatedAt(${a.id},'${p.id}')" style="color:var(--accent)">修改</a>`
: `云账号创建时间未设置 <a href="javascript:void(0)" onclick="setCloudCreatedAt(${a.id},'${p.id}')" style="color:var(--accent)">设置</a>`}</span></span>
<button class="btn sm" onclick="testAccount(${a.id})">测试连接</button>
<button class="btn sm" onclick="openMonitorModal(${a.id})">🔔 监控</button>
<button class="btn sm" onclick="editAccount(${a.id})">编辑</button>
<button class="btn sm danger" onclick="delAccount(${a.id})">删除</button></div>`; }).join('')
|| '<div style="color:var(--muted);padding:8px 0">暂无账号</div>'}
<h2 style="margin-top:20px">添加账号
<button class="btn sm" style="margin-left:8px" onclick="toggleBatchAdd()">批量添加</button></h2>
<div id="singleAddForm">
<form id="accForm">
<div class="field"><label>账号别名 <span class="req">*</span></label>
<input name="name" required placeholder="如：甲骨文-东京"></div>
${p.fields.map(f => `<div class="field"><label>${esc(f.label)}${f.required? ' <span class="req">*</span>': ''}</label>
${fieldInput(f, '')}${f.help? `<div class="help">${esc(f.help)}</div>`: ''}</div>`).join('')}
${proxyFieldsHtml()}
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">保存（自动校验连通性）</button>
</div>
</form>
</div>
<div id="batchAddForm" style="display:none">
<form id="accBatchForm">
<div class="field"><label>批量添加（每行一个账号，字段用 | 分隔）</label>
<textarea name="batch" rows="6" style="width:100%" placeholder="别名 | 字段1 | 字段2 | ..."></textarea>
<div class="help" id="batchHelp" style="color:var(--muted)"></div></div>
<div class="modal-actions">
<button type="button" class="btn" onclick="toggleBatchAdd()">返回单个添加</button>
<button type="submit" class="btn primary">批量保存（逐个校验）</button>
</div>
</form>
<div id="batchResult"></div>
</div>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('accForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
const creds = {};
p.fields.forEach(f => creds[f.key] = (fd.get(f.key) || '').trim());
try {
await api('POST', '/api/accounts', {provider: p.id, name: fd.get('name').trim(), creds,
proxy_url: (fd.get('proxy_url') || '').trim(),
proxy_user: (fd.get('proxy_user') || '').trim(),
proxy_pass: fd.get('proxy_pass') || ''});
toast('账号已添加'); closeModal(); loadAccounts();
} catch (err) { toast(err.message, true);}
};
// 批量添加说明
document.getElementById('batchHelp').textContent =
`格式：别名 | ${p.fields.map(f => f.label).join(' | ')}（每行一个）`;
document.getElementById('accBatchForm').onsubmit = async e => {
e.preventDefault();
const text = (new FormData(e.target).get('batch') || '').trim();
const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
if (!lines.length) { toast('请先粘贴账号信息', true); return;}
const accounts = [];
for (const line of lines) {
const parts = line.split('|').map(s => s.trim());
if (parts.length < p.fields.length + 1) {
toast(`格式错误（需要 ${p.fields.length + 1} 个字段）: ${line.slice(0, 30)}…`, true); return;}
const creds = {};
p.fields.forEach((f, i) => creds[f.key] = parts[i + 1] || '');
accounts.push({name: parts[0], creds});
}
if (!confirm(`确定批量添加 ${accounts.length} 个账号吗？将逐个校验连通性。`)) return;
try {
const r = await api('POST', '/api/accounts/batch', {provider: p.id, accounts});
const box = document.getElementById('batchResult');
box.innerHTML = `<div style="margin-top:10px"><b>${esc(r.summary)}</b><br>` +
r.results.map(x => `<div style="font-size:12px;color:${x.ok? 'var(--green)': 'var(--red2)'}">${x.ok? '✅': '❌'} ${esc(x.name)}${x.ok? '': ': ' + esc(x.error)}</div>`).join('') + '</div>';
loadAccounts();
} catch (err) { toast(err.message, true);}
};
}

function toggleBatchAdd() {
const s = document.getElementById('singleAddForm');
const b = document.getElementById('batchAddForm');
const showBatch = s.style.display !== 'none';
s.style.display = showBatch? 'none': '';
b.style.display = showBatch? '': 'none';
}

async function openRecycleBin() {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>🗑️ 回收站</h2><div class="empty">加载中…</div>`;
try {
const r = await api('GET', '/api/recycle-bin');
const s = r.stats;
box.innerHTML = `<h2>🗑️ 回收站</h2>
<div style="color:var(--muted);font-size:13px;margin-bottom:12px">
共 ${s.count} 个已删账号 · 最长存活 ${s.max_lifecycle_days} 天 · 最高费用 $${s.max_cost_usd}
</div>` +
(r.items.length? `<table><thead><tr><th>账号</th><th>云</th><th>预估费用</th><th>存活天数</th><th>删除时间</th></tr></thead><tbody>` +
r.items.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.provider)}</td>
<td>$${x.est_cost_usd}</td><td>${x.lifecycle_days} 天</td>
<td style="font-size:12px">${new Date(x.deleted_at * 1000).toLocaleString()}</td></tr>`).join('') +
'</tbody></table>': '<div class="empty">回收站是空的</div>') +
`<div class="modal-actions"><button type="button" class="btn" onclick="openAccountModal()">返回</button></div>`;
} catch (e) {
box.innerHTML = `<h2>🗑️ 回收站</h2><div class="empty">加载失败: ${esc(e.message)}</div>`;
}
}

async function editAccount(id) {
const p = curProvider;
const cur = accounts.find(a => a.id === id) || {};
// 重新拉取解密后的凭证需要后端支持，这里简化：只改别名，或重填全部凭证
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>编辑账号</h2>
<form id="accEditForm">
<div class="field"><label>账号别名 <span class="req">*</span></label>
<input name="name" required value="${esc(cur.name)}"></div>
<div class="help" style="color:var(--muted);margin-bottom:14px">如需更换凭证请删除后重新添加；这里只修改别名。</div>
${proxyFieldsHtml(cur)}
<div class="modal-actions">
<button type="button" class="btn" onclick="openAccountModal()">返回</button>
<button type="submit" class="btn primary">保存</button>
</div>
</form>`;
document.getElementById('accEditForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
const body = {name: fd.get('name').trim()};
// 代理区未改动（URL/用户名与已存一致且密码留空）时不提交，保持原配置（含已存密码）
const purl = (fd.get('proxy_url') || '').trim();
const puser = (fd.get('proxy_user') || '').trim();
const ppass = fd.get('proxy_pass') || '';
if (purl !== (cur.proxy_url || '') || puser !== (cur.proxy_user || '') || ppass) {
body.proxy_url = purl;
body.proxy_user = puser;
body.proxy_pass = ppass;
}
try { await api('PUT', `/api/accounts/${id}`, body); toast('已保存'); closeModal(); loadAccounts(id);}
catch (err) { toast(err.message, true);}
};
}

async function delAccount(id) {
if (!confirm('确定删除该账号吗？其凭证将从本地彻底删除。')) return;
try { await api('DELETE', `/api/accounts/${id}`); toast('已删除'); openAccountModal(); loadAccounts();}
catch (e) { toast(e.message, true);}
}

async function setCloudCreatedAt(id, provider) {
const cur = accounts.find(a => a.id === id);
const v = prompt('请输入云账号注册/创建日期（格式 YYYY-MM-DD）：',
cur && cur.cloud_created_at? fmtDate(cur.cloud_created_at): '');
if (v === null) return;
const m = v.trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
if (!m) { toast('日期格式不正确', true); return;}
const ts = new Date(`${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}T00:00:00`).getTime() / 1000;
if (!isFinite(ts) || ts <= 0 || ts > Date.now() / 1000) { toast('日期无效', true); return;}
try {
await api('PUT', `/api/accounts/${id}/cloud-created-at`, {timestamp: ts});
toast('已保存'); openAccountModal(); loadAccounts();
} catch (e) { toast(e.message, true);}
}

async function testAccount(id) {
try { await api('POST', `/api/accounts/${id}/test`); toast('连接正常');}
catch (e) { toast(e.message, true);}
}

async function testAllAccounts() {
const box = document.getElementById('testAllResult');
box.innerHTML = '<div style="color:var(--muted);padding:6px 0">测活中…</div>';
try {
const list = await api('POST', `/api/accounts/test-all?provider=${curProvider.id}`);
box.innerHTML = list.map(r =>
`<div style="padding:6px 0;border-bottom:1px solid var(--border);font-size:13px">
${r.ok? '✅': '❌'} ${esc(r.name)} <span style="color:var(--faint)">${esc(r.message)}</span></div>`).join('')
|| '<div style="color:var(--muted)">暂无账号</div>';
} catch (e) { box.innerHTML = `<div style="color:var(--red)">测活失败: ${esc(e.message)}</div>`;}
}

async function openMonitorModal(id) {
const acc = accounts.find(a => a.id === id);
let m = {monitor_alert: false, monitor_restart: false, monitor_ip_check: false, auto_change_ip: false, auto_change_ip_used: 0, auto_change_ip_limit: 3};
try { m = await api('GET', `/api/accounts/${id}/monitor`);} catch (e) { toast(e.message, true); return;}
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>监控设置 · ${esc(acc.name)}</h2>
<form id="monitorForm">
<div class="check-row"><input type="checkbox" name="monitor_alert"${m.monitor_alert? ' checked': ''}>
<span>状态告警：实例异常停止/恢复时 Telegram 推送通知</span></div>
<div class="check-row"><input type="checkbox" name="monitor_restart"${m.monitor_restart? ' checked': ''}>
<span>异常自启：实例异常停止后自动提交启动任务</span></div>
<div class="check-row"><input type="checkbox" name="monitor_ip_check"${m.monitor_ip_check? ' checked': ''}>
<span>IP 连通性检测：定期探测运行中实例的公网 IP（ping + TCP 22/80/443/3389），由连通变为不通时 Telegram 告警</span></div>
<div class="check-row"><input type="checkbox" name="auto_change_ip"${m.auto_change_ip? ' checked': ''}>
<span>IP 不通自动换 IP：检测到 IP 不通时自动更换公网 IP（每天最多 ${m.auto_change_ip_limit} 次，今日已用 ${m.auto_change_ip_used} 次；换 IP 失败只发 TG 告警，不循环重试）</span></div>
<div class="help" style="color:var(--muted);margin-bottom:14px">后台每 N 分钟巡检一次（N 在"设置"里配置，默认 5 分钟），IP 检测与自动换 IP 共用该巡检周期。需要先在设置里配置 Telegram 才能收到通知。换 IP 成功后若已配置 Cloudflare 联动，会自动更新对应 A 记录。</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="openAccountModal()">返回</button>
<button type="submit" class="btn primary">保存</button>
</div></form>`;
document.getElementById('monitorForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
try {
await api('PUT', `/api/accounts/${id}/monitor`,
{monitor_alert: !!fd.get('monitor_alert'), monitor_restart: !!fd.get('monitor_restart'),
monitor_ip_check: !!fd.get('monitor_ip_check'), auto_change_ip: !!fd.get('auto_change_ip')});
toast('监控设置已保存'); openAccountModal();
} catch (err) { toast(err.message, true);}
};
}

function closeModal() { document.getElementById('modalMask').classList.remove('show');}
document.getElementById('modalMask').addEventListener('click', e => {
if (e.target.id === 'modalMask') closeModal();
});

/* ---------- 创建实例 ---------- */
function formField(def) {
// def: {key,label,type,options,value,help,required,placeholder,rows}
const req = def.required? ' <span class="req">*</span>': '';
let input = '';
if (def.type === 'select')
input = `<select name="${def.key}">${(def.options || []).map(o =>
`<option value="${esc(o)}"${o === def.value? ' selected': ''}>${esc(o)}</option>`).join('')}</select>`;
else if (def.type === 'textarea')
input = `<textarea name="${def.key}" placeholder="${esc(def.placeholder || '')}">${esc(def.value || '')}</textarea>`;
else if (def.type === 'checkbox')
input = `<div class="check-row"><input type="checkbox" name="${def.key}"${def.value? ' checked': ''}><span>${esc(def.label)}</span></div>`;
else
input = `<input name="${def.key}" type="${def.type || 'text'}" value="${esc(def.value || '')}"
placeholder="${esc(def.placeholder || '')}"${def.required? ' required': ''}>`;
if (def.type === 'checkbox') return input;
return `<div class="field"><label>${esc(def.label)}${req}</label>${input}
${def.help? `<div class="help">${esc(def.help)}</div>`: ''}</div>`;
}
const row = (...defs) => `<div class="field-row">${defs.map(formField).join('')}</div>`;

/* ---------- 开机脚本模板 ---------- */
let _scriptTemplates = [];  // 最近一次加载的模板列表

function startupScriptFields() {
return `<div class="field"><label>开机脚本模板（可选）</label>
<select id="scriptTplSel" onchange="applyScriptTemplate()"><option value="">（不使用模板，手填）</option></select>
<div class="help">选择模板后填充到下方，可再手动修改；保留手填</div></div>
${formField({key: 'startup_script', label: '开机脚本（可选）', type: 'textarea', help: '留空则不注入'})}`;
}

async function loadScriptTemplates() {
try { _scriptTemplates = await api('GET', '/api/script-templates'); }
catch (e) { _scriptTemplates = []; }
const sel = document.getElementById('scriptTplSel');
if (!sel) return;
sel.innerHTML = '<option value="">（不使用模板，手填）</option>' +
_scriptTemplates.map(t =>
`<option value="${t.id}">[${t.os_type}] ${esc(t.name)}</option>`).join('');
}

function applyScriptTemplate() {
const sel = document.getElementById('scriptTplSel');
const id = sel? parseInt(sel.value, 10): 0;
if (!id) return;
const t = _scriptTemplates.find(x => x.id === id);
if (!t) return;
const ta = document.querySelector('#createForm [name="startup_script"]');
if (ta) ta.value = t.content || '';
}

async function openScriptTemplatesModal() {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>开机脚本模板</h2>
<div class="modal-actions" style="margin-bottom:14px">
<button class="btn primary sm" onclick="openScriptTemplateEditor(0)">＋ 新增模板</button>
<span style="flex:1"></span>
<button class="btn sm" onclick="openScriptTemplatesModal()">刷新</button>
</div>
<div id="tplList"><div class="empty">加载中…</div></div>`;
document.getElementById('modalMask').classList.add('show');
try {
const list = await api('GET', '/api/script-templates');
document.getElementById('tplList').innerHTML = list.length? `
<table><thead><tr><th>名称</th><th>系统</th><th>创建时间</th><th>操作</th></tr></thead>
<tbody>${list.map(t => `<tr>
<td>${esc(t.name)}</td><td class="mono">${esc(t.os_type)}</td>
<td class="mono">${esc(fmtTime(t.created_at * 1000))}</td>
<td style="white-space:nowrap">
<button class="btn sm" onclick="openScriptTemplateEditor(${t.id})">编辑</button>
<button class="btn sm danger" onclick="deleteScriptTemplate(${t.id}, ${JSON.stringify(t.name)})">删除</button>
</td></tr>`).join('')}</tbody></table>`
: '<div class="empty">暂无模板</div>';
} catch (e) {
document.getElementById('tplList').innerHTML = `<div class="empty">加载失败: ${esc(e.message)}</div>`;
}
}

async function openScriptTemplateEditor(id) {
let t = {name: '', os_type: 'linux', content: ''};
if (id) {
try {
const list = await api('GET', '/api/script-templates');
t = list.find(x => x.id === id) || t;
} catch (e) { toast(e.message, true); return; }
}
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>${id? '编辑模板': '新增模板'}</h2>
<div class="field"><label>模板名称</label>
<input id="tplName" value="${esc(t.name)}" placeholder="如：换 apt 源 + 装 docker"></div>
<div class="field"><label>系统类型</label>
<select id="tplOsType">
<option value="linux"${t.os_type === 'linux'? ' selected': ''}>linux</option>
<option value="windows"${t.os_type === 'windows'? ' selected': ''}>windows</option>
</select></div>
<div class="field"><label>脚本内容</label>
<textarea id="tplContent" style="min-height:180px" placeholder="开机执行的脚本内容">${esc(t.content)}</textarea></div>
<div class="modal-actions">
<button type="button" class="btn" onclick="openScriptTemplatesModal()">返回列表</button>
<button type="button" class="btn primary" onclick="saveScriptTemplate(${id || 0})">保存</button>
</div>`;
document.getElementById('modalMask').classList.add('show');
}

async function saveScriptTemplate(id) {
const name = document.getElementById('tplName').value.trim();
const os_type = document.getElementById('tplOsType').value;
const content = document.getElementById('tplContent').value;
if (!name) { toast('模板名称不能为空', true); return; }
try {
if (id) await api('PUT', `/api/script-templates/${id}`, {name, os_type, content});
else await api('POST', '/api/script-templates', {name, os_type, content});
toast('已保存'); openScriptTemplatesModal();
} catch (e) { toast(e.message, true); }
}

async function deleteScriptTemplate(id, name) {
if (!confirm(`确定删除模板「${name}」吗？`)) return;
try {
await api('DELETE', `/api/script-templates/${id}`);
toast('已删除'); openScriptTemplatesModal();
} catch (e) { toast(e.message, true); }
}

function createFormHTML(p, opts) {
if (p.id === 'oci') return `
${formField({key: 'name', label: '实例名（可选）', placeholder: '留空自动生成'})}
${row({key: 'availability_domain', label: '可用域', type: 'select', options: opts.availability_domains},
{key: 'shape', label: '规格', type: 'select', options: opts.shapes, value: opts.shapes.find(s => s.includes('E2.1.Micro')) || opts.shapes[0]})}
${row({key: 'ocpus', label: 'OCPU（仅 Flex）', type: 'number', value: '1'},
{key: 'memory_gbs', label: '内存 GB（仅 Flex）', type: 'number', value: '6'})}
${row({key: 'os', label: '操作系统', type: 'select', options: opts.os_options},
{key: 'boot_volume_gb', label: '引导卷 GB', type: 'number', value: '50'})}
${formField({key: 'ssh_key', label: 'SSH 公钥（可选）', type: 'textarea', help: '留空则使用账号的默认 SSH 公钥'})}
${row({key: 'login_user', label: '登录用户', value: 'ubuntu'},
{key: 'password', label: '密码（可选）', placeholder: '留空自动生成 16 位随机密码', help: '留空自动生成 16 位随机密码'})}
${formField({key: 'assign_public_ip', label: '分配公网 IP', type: 'checkbox', value: true})}
${startupScriptFields()}`;
if (p.id === 'aws') return `
${formField({key: 'name', label: '实例名（Name 标签）', placeholder: '留空自动生成'})}
${row({key: 'region', label: '区域', type: 'select', options: opts.regions, value: opts.default_region || opts.regions[0]},
{key: 'instance_type', label: '实例类型', type: 'select', options: opts.instance_types, value: 't2.micro'})}
${row({key: 'key_name', label: '密钥对', type: 'select', options: ['（自动创建新密钥对）',...(opts.key_pairs || [])]},
{key: 'ami', label: 'AMI（可选）', placeholder: '留空自动使用最新 Ubuntu 22.04', help: '留空自动使用最新 Ubuntu 22.04'})}
<div class="help" style="color:var(--muted);margin:-6px 0 14px">将在目标区域的默认 VPC 自动创建安全组（放行 SSH）。密钥对列表为账号默认区域的——若选择其他区域，将自动创建新密钥对。新密钥对的私钥只在任务结果中显示一次。</div>
${startupScriptFields()}`;
if (p.id === 'azure') return `
${row({key: 'name', label: '虚拟机名（可选）', placeholder: '留空自动生成'},
{key: 'resource_group', label: '资源组（可选）', placeholder: '留空自动创建'})}
${row({key: 'location', label: '区域', type: 'select', options: opts.locations, value: opts.locations.includes('japaneast')? 'japaneast': opts.locations[0]},
{key: 'vm_size', label: '规格', type: 'select', options: opts.vm_sizes, value: 'Standard_B1s'})}
${row({key: 'image', label: '镜像', type: 'select', options: opts.images},
{key: 'disk_gb', label: '系统盘 GB', type: 'number', value: '30'})}
${row({key: 'admin_username', label: '管理员用户', value: 'azureuser'},
{key: 'password', label: '密码（可选）', placeholder: '留空自动生成', help: '留空自动生成随机密码'})}
${formField({key: 'ssh_key', label: 'SSH 公钥（可选，Linux 有效）', type: 'textarea'})}
${formField({key: 'startup_script', label: '开机脚本（可选）', type: 'textarea', help: 'cloud-init 格式（如 #cloud-config），留空则不注入'})}`;
return '';
}

let lastCreateOpts = null; // 最近一次创建选项，供 readForm 判断跨区
function readForm(form, p) {
const fd = new FormData(form), o = {};
const fields = p.id === 'oci'
? ['name', 'availability_domain', 'shape', 'ocpus', 'memory_gbs', 'os', 'ssh_key', 'boot_volume_gb', 'login_user', 'password', 'startup_script']
: p.id === 'aws'? ['name', 'region', 'instance_type', 'ami', 'key_name', 'startup_script']
: ['name', 'resource_group', 'location', 'vm_size', 'image', 'admin_username', 'password', 'ssh_key', 'disk_gb', 'startup_script'];
fields.forEach(k => o[k] = (fd.get(k) || '').trim());
if (p.id === 'oci') {
o.assign_public_ip =!!fd.get('assign_public_ip');
if (o.key_name === '（自动创建新密钥对）') o.key_name = '';
}
if (p.id === 'aws') {
if (o.key_name === '（自动创建新密钥对）') o.key_name = '';
// 密钥对列表是账号默认区域的；跨区创建时强制自动创建新密钥对
if (lastCreateOpts && o.region && o.region !== lastCreateOpts.default_region) o.key_name = '';
}
return o;
}

async function saveCreateDefaults() {
const form = document.getElementById('createForm');
if (!form) return;
const params = readForm(form, curProvider);
// 密码/密钥类不存为默认
delete params.password; delete params.ssh_key;
try {
await api('PUT', '/api/create-defaults', {provider: curProvider.id, defaults: params});
toast('已保存为默认创建参数');
} catch (e) { toast(e.message, true);}
}

/* ---------- OCI 引导卷 VPU 调整 / 终止保留引导卷 ---------- */
function openVpusModal(inst) {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>调整引导卷性能 · ${esc(inst.name)}</h2>
<div class="help" style="color:var(--muted);margin-bottom:14px">
调整该实例引导卷的 VPU（每 GB 性能单位）。<b>只能调大不能调小</b>，调大会增加费用，约需数分钟生效。</div>
<div class="field"><label>目标 VPU（正整数，常用 10 / 20）</label>
<input id="vpusInput" type="number" min="1" max="120" placeholder="如 10"></div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="button" class="btn primary" onclick="doVpusUpdate()">提交调整</button>
</div>`;
document.getElementById('modalMask').classList.add('show');
window._vpusInst = inst;
document.getElementById('vpusInput').focus();
}

async function doVpusUpdate() {
const vpus = parseInt((document.getElementById('vpusInput').value || '').trim(), 10);
if (!vpus || vpus <= 0) { toast('请输入正整数 VPU', true); return; }
if (!confirm(`确认将实例「${window._vpusInst.name}」的引导卷 VPU 调整为 ${vpus} 吗？只能调大，调大会增加费用。`)) return;
const inst = window._vpusInst;
closeModal();
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/boot-volume-vpus`,
{instance_id: inst.id, vpus_per_gb: vpus});
toast(r.message || '已提交');
} catch (e) { toast(e.message, true); }
}

function openTerminateModal(inst) {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>终止实例</h2>
<div class="help" style="color:var(--red2);margin-bottom:14px">
确定要终止/删除实例 <b>${esc(inst.name)}</b>（${esc(inst.id)}）吗？此操作不可恢复！</div>
<div class="check-row"><input type="checkbox" id="preserveBv">
<span>保留引导卷（只删除实例，保留 boot volume，之后可挂到其他实例恢复数据）</span></div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="button" class="btn danger" onclick="doTerminateConfirmed()">确认终止</button>
</div>`;
document.getElementById('modalMask').classList.add('show');
window._terminateInst = inst;
}

async function doTerminateConfirmed() {
const inst = window._terminateInst;
const preserve = document.getElementById('preserveBv').checked;
if (!confirm(`最后确认：终止实例「${inst.name}」${preserve? '（保留引导卷）': '（引导卷一并删除）'}？`)) return;
closeModal();
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/action`,
{instance: inst, action: 'terminate', params: {preserve_boot_volume: preserve}});
toast('任务已提交，在任务历史中查看进度');
toggleDrawer(true); trackJob(r.job_id);
} catch (e) { toast(e.message, true); }
}

async function openCreateModal() {
if (!curAccount) { toast('请先添加账号', true); return;}
const opts = await api('GET', `/api/accounts/${curAccount.id}/create-options`).catch(e => { toast(e.message, true); return null;});
if (!opts) return;
lastCreateOpts = opts;
const defaults = await api('GET', `/api/create-defaults/${curProvider.id}`).catch(() => ({}));
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>创建实例 · ${esc(curProvider.name)}</h2>
<form id="createForm">${createFormHTML(curProvider, opts)}
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="button" class="btn" onclick="saveCreateDefaults()">保存为默认</button>
<button type="submit" class="btn primary">提交创建（后台执行）</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
// 应用默认参数
const form = document.getElementById('createForm');
for (const [k, v] of Object.entries(defaults || {})) {
const el = form.querySelector(`[name="${k}"]`);
if (el && v !== '' && v != null) el.value = v;
}
loadScriptTemplates();  // 填充开机脚本模板下拉（OCI/AWS）
document.getElementById('createForm').onsubmit = async e => {
e.preventDefault();
const params = readForm(e.target, curProvider);
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/create`, params);
closeModal(); toast('创建任务已提交'); toggleDrawer(true); trackJob(r.job_id);
} catch (err) { toast(err.message, true);}
};
}

async function openSnatchModal() {
if (!curAccount) { toast('请先添加账号', true); return;}
const opts = await api('GET', `/api/accounts/${curAccount.id}/create-options`).catch(e => { toast(e.message, true); return null;});
if (!opts) return;
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>自动抢机 · ${esc(curProvider.name)}</h2>
<div class="help" style="color:var(--yellow);margin-bottom:14px">后台循环尝试创建，遇到资源不足自动按间隔重试，手动停止前不会停。请合理设置间隔，避免被限流。</div>
<form id="snatchForm">
${row({key: 'shape', label: '规格', type: 'select', options: opts.shapes, value: opts.shapes.find(s => s.includes('A1.Flex')) || opts.shapes[0]},
{key: 'retry_interval', label: '重试间隔（秒）', type: 'number', value: '30'})}
${row({key: 'ocpus', label: 'OCPU（仅 Flex）', type: 'number', value: '4'},
{key: 'memory_gbs', label: '内存 GB（仅 Flex）', type: 'number', value: '24'})}
${row({key: 'availability_domain', label: '可用域', type: 'select', options: opts.availability_domains},
{key: 'os', label: '操作系统', type: 'select', options: opts.os_options})}
${row({key: 'name', label: '实例名（可选）', placeholder: '留空自动生成'},
{key: 'password', label: '密码（可选）', placeholder: '留空自动生成'})}
${formField({key: 'ssh_key', label: 'SSH 公钥（可选）', type: 'textarea'})}
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">开始抢机</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('snatchForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target), o = {};
['shape', 'retry_interval', 'ocpus', 'memory_gbs', 'availability_domain', 'os', 'name', 'password', 'ssh_key']
.forEach(k => o[k] = (fd.get(k) || '').trim());
o.assign_public_ip = true;
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/snatch`, o);
closeModal(); toast('抢机任务已启动'); toggleDrawer(true); trackJob(r.job_id);
} catch (err) { toast(err.message, true);}
};
}

/* 通用参数弹窗：改名 / 磁盘扩容 / 开放端口 */
function openParamModal(title, inst, action, fields, tip) {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>${esc(title)} · ${esc(inst.name)}</h2>
<form id="paramForm">
${fields.map(formField).join('')}
${tip? `<div class="help" style="color:var(--yellow);margin-bottom:6px">${esc(tip)}</div>`: ''}
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">提交</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('paramForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target), params = {};
for (const f of fields) {
const v = (fd.get(f.key) || '').trim();
if (f.required && !v) { toast(`请填写「${f.label}」`, true); return; }
params[f.key] = v;
}
if (action === 'extend_disk' && !confirm(`确定把磁盘扩容到 ${params.size_gb}GB 吗？（不可逆，且可能产生费用）`)) return;
if (action === 'resize' && !confirm(`确定把规格改为 ${params.size} 吗？会先释放资源再重启，可能产生费用差异。`)) return;
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/action`,
{instance: inst, action, params});
closeModal(); toast('任务已提交'); toggleDrawer(true); trackJob(r.job_id);
} catch (err) { toast(err.message, true);}
};
}

/* 换 IP 确认框：可附带目标网段（留空走原有随机换 IP 逻辑） */
function openChangeIpModal(inst) {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>更换公网 IP · ${esc(inst.name)}</h2>
<form id="changeIpForm">
${formField({key: 'cidr', label: '目标网段（可选）', placeholder: '如 192.0.2.0/24', help: 'CIDR 如 192.0.2.0/24，! 开头为排除，留空随机。可指定新 IP 必须落在的网段，或加 ! 前缀排除某网段；换到的 IP 不符合时会自动重试，最多 5 次，用尽则任务失败。'})}
<div class="help" style="color:var(--yellow);margin-bottom:6px">更换公网 IP 后原 IP 会释放，确定继续吗？</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">确定</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('changeIpForm').onsubmit = async e => {
e.preventDefault();
const cidr = (new FormData(e.target).get('cidr') || '').trim();
if (cidr && !/^!?(?:(?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F:]+)\/\d{1,2}$/.test(cidr)) {
toast('网段格式不正确：应为 CIDR 格式（如 192.0.2.0/24），排除网段加 ! 前缀', true); return;
}
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/action`,
{instance: inst, action: 'change_ip', params: {cidr}});
closeModal(); toast('任务已提交'); toggleDrawer(true); trackJob(r.job_id);
} catch (err) { toast(err.message, true);}
};
}

function openShapeModal(inst) {const box = document.getElementById('modalBox');
box.innerHTML = `<h2>更改实例配置 · ${esc(inst.name)}</h2>
<form id="shapeForm">
${formField({key: 'shape', label: '目标规格', required: true, placeholder: '如 VM.Standard.A1.Flex'})}
${row({key: 'ocpus', label: 'OCPU（Flex）', type: 'number', value: inst.cpu || '1'},
{key: 'memory_gbs', label: '内存 GB（Flex）', type: 'number', value: inst.memory || '6'})}
<div class="help" style="color:var(--yellow);margin-bottom:6px">注意：OCI 要求实例先关机再改配置，面板会自动处理等待。请确认规格在该可用域可用。</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">提交</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('shapeForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
const params = {shape: fd.get('shape').trim(), ocpus: fd.get('ocpus').trim(), memory_gbs: fd.get('memory_gbs').trim()};
if (!params.shape) { toast('请填写目标规格', true); return;}
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/action`,
{instance: inst, action: 'update_shape', params});
closeModal(); toast('任务已提交'); toggleDrawer(true); trackJob(r.job_id);
} catch (err) { toast(err.message, true);}
};
}

/* ---------- 任务历史 ---------- */
function toggleDrawer(open) {
document.getElementById('drawer').classList.toggle('open', open);
clearInterval(drawerPoll); drawerPoll = null;
if (open) { showJobList(); drawerPoll = setInterval(() => { if (!jobDetailId) loadJobs();}, 3000);}
}
function showJobList() { jobDetailId = null; document.getElementById('jobDetail').classList.remove('show'); loadJobs();}

async function loadJobs() {
const list = await api('GET', '/api/jobs?limit=60').catch(() => []);
document.getElementById('jobList').innerHTML = list.map(j => `
<div class="job-item" onclick="showJobDetail('${j.id}')">
<div class="title">${esc(j.title)}</div>
<div class="meta"><span class="badge b-${j.status}">${j.status}</span>
<span>${fmtTime(j.created_at * 1000)}</span></div>
</div>`).join('') || '<div class="empty">暂无任务</div>';
}
function trackJob(id) { showJobDetail(id);}

async function showJobDetail(id) {
jobDetailId = id;
document.getElementById('jobDetail').classList.add('show');
const render = async () => {
const j = await api('GET', `/api/jobs/${id}`).catch(() => null);
if (!j || jobDetailId!== id) return;
document.getElementById('jobLog').textContent =
` 状态: ${j.status}\n${'='.repeat(40)}\n${j.log || ''}${j.result? '\n' + '='.repeat(40) + '\n' + j.result: ''}`;
document.getElementById('jobLog').scrollTop = 1e9;
const running = j.status === 'running' || j.status === 'queued' || j.status === 'stop_requested';
document.getElementById('jobActions').innerHTML =
(running? `<button class="btn danger" onclick="stopJob('${id}')">停止任务</button>`: '') +
`<button class="btn" onclick="delJob('${id}')">删除记录</button>
<button class="btn" onclick="loadInstances()">刷新实例列表</button>`;
return running;
};
const running = await render();
clearInterval(jobTimer);
if (running) jobTimer = setInterval(async () => { if (!(await render())) clearInterval(jobTimer);}, 2000);
}
async function stopJob(id) {
try { await api('POST', `/api/jobs/${id}/stop`); toast('停止请求已发送');} catch (e) { toast(e.message, true);}
}
async function delJob(id) {
try { await api('DELETE', `/api/jobs/${id}`); showJobList();} catch (e) { toast(e.message, true);}
}

async function doLogout() {
await api('POST', '/api/logout').catch(() => {});
location.href = '/login.html';
}

function openPasswordModal() {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>修改面板密码</h2>
<form id="pwdForm">
<div class="field"><label>原密码 <span class="req">*</span></label><input name="old" type="password" required></div>
<div class="field"><label>新密码 <span class="req">*</span></label><input name="new" type="password" required placeholder="至少 6 位"></div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">保存</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('pwdForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
try {
await api('POST', '/api/change-password', {old_password: fd.get('old'), new_password: fd.get('new')});
closeModal(); toast('密码已修改');
} catch (err) { toast(err.message, true); }
};
}

function openSettingsModal() {
api('GET', '/api/settings').then(s => {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>设置</h2>
<h3 style="margin:6px 0 8px">Telegram 联动</h3>
<div class="help" style="color:var(--muted);margin-bottom:14px">
1. 在 Telegram 里找 @BotFather 创建 Bot，拿到 Token<br>
2. 给你的 Bot 发任意消息，然后访问 <span class="mono">https://api.telegram.org/bot&lt;Token&gt;/getUpdates</span> 查出 chat.id<br>
3. 填到下面保存。之后任务完成/失败会自动推送，Bot 里点 /start 可用按钮操作实例。<br>
${s.tg_bot_token_set ? '当前状态：' + (s.tg_bot_running ? 'Bot 运行中 ✅' : 'Token 已保存，Bot 未运行') : '当前状态：未配置'}</div>
<form id="tgForm">
<div class="field"><label>Bot Token</label>
<input class="code" name="tg_bot_token" type="password" placeholder="${s.tg_bot_token_set ? '已保存，留空不修改' : '如 123456:ABC-DEF…'}"></div>
<div class="field"><label>Chat ID</label>
<input name="tg_chat_id" value="${esc(s.tg_chat_id || '')}" placeholder="如 123456789"></div>
<h3 style="margin:18px 0 8px">Cloudflare DNS 联动</h3>
<div class="help" style="color:var(--muted);margin-bottom:14px">
实例更换公网 IP 后，自动更新 Cloudflare 上对应的 A 记录。<br>
Token 权限：Zone:Zone:Read + Zone:DNS:Edit（创建 API Token，勾选这两个模板权限即可）。<br>
${s.cf_token_set ? '当前状态：已保存 ✅' : '当前状态：未配置'}</div>
<div class="field"><label>API Token</label>
<input class="code" name="cf_api_token" type="password" placeholder="${s.cf_token_set ? '已保存，留空不修改' : '如 6pxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'}"></div>
<h3 style="margin:18px 0 8px">监控与每日报告</h3>
<div class="check-row"><input type="checkbox" name="daily_report"${s.daily_report? ' checked': ''}>
<span>每日账单报告（Telegram 推送全部账号当日费用汇总）</span></div>
<div class="field-row">
<div class="field"><label>报告时间（小时，0-23）</label>
<input name="daily_report_hour" type="number" min="0" max="23" value="${s.daily_report_hour}"></div>
<div class="field"><label>监控巡检间隔（分钟）</label>
<input name="monitor_interval_min" type="number" min="1" max="120" value="${s.monitor_interval_min}"></div>
</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="tgTest()">发送测试消息</button>
<span style="flex:1"></span>
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">保存</button>
</div></form>
<h2 style="margin-top:22px">TOTP 二次验证</h2>
<div id="totpSection"><div class="empty">加载中…</div></div>
<h2 style="margin-top:22px">备份 / 恢复</h2>
<div class="check-row">备份为整个数据库的加密文件（含云凭证），备份密码只用于本次加密，服务器不保存。</div>
<div class="field"><label>备份密码（至少 8 位）</label>
<input id="backupPwd" type="password" autocomplete="new-password" placeholder="用于加密备份文件"></div>
<div class="modal-actions" style="margin-bottom:18px">
<button type="button" class="btn" onclick="doBackup()">📥 下载加密备份</button>
</div>
<div class="check-row">恢复</div>
<div class="field"><label>选择备份文件</label>
<input id="restoreFile" type="file" accept=".bin"></div>
<div class="field"><label>备份密码</label>
<input id="restorePwd" type="password" autocomplete="new-password" placeholder="解密备份文件的密码"></div>
<div class="modal-actions" style="margin-bottom:8px">
<button type="button" class="btn" onclick="doRestoreStep1()">校验备份</button>
</div>
<div id="restoreInfo"></div>`;
document.getElementById('modalMask').classList.add('show');
renderTotpSection();
document.getElementById('tgForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
try {
await api('PUT', '/api/settings', {
tg_bot_token: fd.get('tg_bot_token').trim(),
tg_chat_id: fd.get('tg_chat_id').trim(),
cf_api_token: fd.get('cf_api_token').trim(),
daily_report: !!fd.get('daily_report'),
daily_report_hour: parseInt(fd.get('daily_report_hour') || '9', 10),
monitor_interval_min: parseInt(fd.get('monitor_interval_min') || '5', 10),
});
closeModal(); toast('设置已保存');
} catch (err) { toast(err.message, true); }
};
}).catch(e => toast(e.message, true));
}

/* ---------- TOTP 二次验证（设置弹窗内区块） ---------- */
async function renderTotpSection() {
const sec = document.getElementById('totpSection');
if (!sec) return;
let enabled = false;
try { enabled = (await api('GET', '/api/totp/status')).enabled; }
catch (e) { sec.innerHTML = `<div class="help" style="color:var(--red)">加载 TOTP 状态失败: ${esc(e.message)}</div>`; return; }
if (!enabled) {
  sec.innerHTML = `
  <div class="check-row">状态：未启用（登录只需密码）</div>
  <button type="button" class="btn sm" onclick="totpBind()">🔐 绑定验证器</button>`;
} else {
  sec.innerHTML = `
  <div class="check-row">状态：已启用 ✅（登录需密码 + 验证码）</div>
  <button type="button" class="btn sm danger" onclick="totpUnbind()">解绑</button>`;
}
}

async function totpBind() {
const sec = document.getElementById('totpSection');
sec.innerHTML = `<div class="empty">生成密钥中…</div>`;
try {
  const d = await api('POST', '/api/totp/setup');
  sec.innerHTML = `
  <div class="help" style="color:var(--muted);margin-bottom:10px">用验证器（Google / Microsoft Authenticator 等）扫描二维码，或手动输入密钥：<br>确认启用前登录方式不变。</div>
  <img src="${d.qr_data_uri}" alt="TOTP 二维码" style="width:160px;height:160px;background:#fff;border:1px solid var(--border2);border-radius:8px;padding:6px">
  <div class="field" style="margin-top:10px"><label>手动密钥</label>
  <input class="mono" value="${esc(d.secret)}" readonly onclick="this.select()"></div>
  <div class="field"><label>当前 6 位验证码</label>
  <input id="totpConfirmCode" inputmode="numeric" placeholder="如 123456"></div>
  <div class="modal-actions">
  <button type="button" class="btn" onclick="renderTotpSection()">取消</button>
  <button type="button" class="btn primary" onclick="totpConfirm()">确认启用</button>
  </div>`;
  document.getElementById('totpConfirmCode').focus();
} catch (e) { toast(e.message, true); renderTotpSection(); }
}

async function totpConfirm() {
const code = (document.getElementById('totpConfirmCode').value || '').trim();
if (!/^\d{6}$/.test(code)) { toast('请输入 6 位数字验证码', true); return; }
try {
  await api('POST', '/api/totp/confirm', {code});
  toast('TOTP 已启用，下次登录需输入验证码');
  renderTotpSection();
} catch (e) { toast(e.message, true); }
}

function totpUnbind() {
const sec = document.getElementById('totpSection');
sec.innerHTML = `
<div class="help" style="color:var(--yellow);margin-bottom:10px">解绑后登录只需密码。需二次确认：</div>
<div class="field"><label>面板密码</label>
<input id="totpUnbindPwd" type="password" autocomplete="current-password"></div>
<div class="field"><label>当前 6 位验证码</label>
<input id="totpUnbindCode" inputmode="numeric" placeholder="如 123456"></div>
<div class="modal-actions">
<button type="button" class="btn" onclick="renderTotpSection()">取消</button>
<button type="button" class="btn danger" onclick="totpDoUnbind()">确认解绑</button>
</div>`;
}

async function totpDoUnbind() {
const password = document.getElementById('totpUnbindPwd').value;
const code = (document.getElementById('totpUnbindCode').value || '').trim();
if (!/^\d{6}$/.test(code)) { toast('请输入 6 位数字验证码', true); return; }
if (!confirm('确定解绑 TOTP 二次验证吗？解绑后登录只需密码。')) return;
try {
  await api('POST', '/api/totp/disable', {password, code});
  toast('TOTP 已解绑');
  renderTotpSection();
} catch (e) { toast(e.message, true); }
}

/* ---------- 审计日志 ---------- */
async function openAuditLogModal(limit) {
limit = parseInt(limit || '200', 10);
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>审计日志</h2>
<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">
<span style="color:var(--muted);font-size:13px">显示条数</span>
<select id="auditLimitSel" onchange="openAuditLogModal(this.value)" style="padding:6px 9px;border-radius:8px;border:1px solid var(--border2);background:var(--bg);color:var(--text);font-size:13px">
${[50, 200, 500].map(n => `<option value="${n}"${n === limit? ' selected': ''}>${n}</option>`).join('')}
</select>
<span style="flex:1"></span>
<button class="btn sm" onclick="openAuditLogModal(document.getElementById('auditLimitSel').value)">刷新</button>
</div>
<div id="auditBody"><div class="empty">加载中…</div></div>`;
document.getElementById('modalMask').classList.add('show');
try {
const list = await api('GET', `/api/audit-log?limit=${limit}`);
document.getElementById('auditBody').innerHTML = `
<table><thead><tr><th>时间</th><th>IP</th><th>动作</th><th>详情</th></tr></thead>
<tbody>${list.map(a => `<tr>
<td class="mono">${esc(fmtTime(a.ts * 1000))}</td>
<td class="mono">${esc(a.ip)}</td>
<td>${esc(a.action)}</td>
<td style="word-break:break-all">${esc(a.detail)}</td>
</tr>`).join('') || '<tr><td colspan="4" class="empty">暂无记录</td></tr>'}
</tbody></table>`;
} catch (e) {
document.getElementById('auditBody').innerHTML =
`<div class="empty">加载失败: ${esc(e.message)}<br><button class="btn" onclick="openAuditLogModal(${limit})">重试</button></div>`;
}
}

/* ---------- 加密备份 / 恢复 ---------- */
async function doBackup() {
const password = document.getElementById('backupPwd').value;
if (password.length < 8) { toast('备份密码至少 8 位', true); return; }
try {
  const r = await fetch('/api/backup', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({password})
  });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || '备份失败'); }
  const blob = await r.blob();
  const cd = r.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename="?([^";]+)"?/);
  const fname = m ? m[1] : 'tricloud-backup.bin';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = fname;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  toast('备份已下载');
  document.getElementById('backupPwd').value = '';
} catch (e) { toast(e.message, true); }
}

async function doRestoreStep1() {
const fileInput = document.getElementById('restoreFile');
const password = document.getElementById('restorePwd').value;
const info = document.getElementById('restoreInfo');
info.innerHTML = '';
if (!fileInput.files.length) { toast('请先选择备份文件', true); return; }
if (!password) { toast('请输入备份密码', true); return; }
const fd = new FormData();
fd.append('file', fileInput.files[0]);
fd.append('password', password);
try {
  info.innerHTML = '<div class="empty">校验中…</div>';
  const r = await fetch('/api/restore', {method: 'POST', body: fd});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || '校验失败');
  const t = d.latest_record_at ? fmtTime(d.latest_record_at * 1000) : '未知';
  info.innerHTML = `
  <div class="help" style="color:var(--yellow);margin:8px 0">
    备份文件：${esc(d.file_name)}<br>
    包含账号 ${d.accounts} 个，最新账号记录 ${esc(t)}。<br>
    确认覆盖将替换当前数据库（当前库会保留为 .bak），并要求重新登录。
  </div>
  <div class="modal-actions">
  <button type="button" class="btn danger" onclick="doRestoreConfirm()">确认覆盖并恢复</button>
  </div>`;
} catch (e) { info.innerHTML = ''; toast(e.message, true); }
}

async function doRestoreConfirm() {
const password = document.getElementById('restorePwd').value;
const fileInput = document.getElementById('restoreFile');
if (!confirm('确定用该备份覆盖当前数据库吗？当前库会保留为 .bak，恢复后需重新登录。')) return;
const fd = new FormData();
fd.append('file', fileInput.files[0]);
fd.append('password', password);
fd.append('confirm', 'true');
try {
  const r = await fetch('/api/restore', {method: 'POST', body: fd});
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.restored) throw new Error(d.detail || '恢复失败');
  toast('恢复成功，请重新登录');
  setTimeout(() => { location.href = '/login.html'; }, 800);
} catch (e) { toast(e.message, true); }
}

async function tgTest() {
try { await api('POST', '/api/settings/tg-test'); toast('测试消息已发送，去 Telegram 看看'); }
catch (e) { toast(e.message, true); }
}

/* ---------- Cloudflare DNS 映射 ---------- */
async function openDnsMappingModal() {
if (!curAccount) return;
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>Cloudflare DNS 映射</h2>
<div class="help" style="color:var(--muted);margin-bottom:14px">
实例更换公网 IP 后，自动把对应的 Cloudflare A 记录更新为新 IP。<br>
需先在「设置」里配置 Cloudflare API Token（Zone:Zone:Read + Zone:DNS:Edit 权限）。</div>
<div id="dnsMapList">加载中…</div>
<form id="dnsMapForm">
<div class="field"><label>实例</label><select name="instance_id" id="dnsMapInstSel"><option value="">加载中…</option></select></div>
<div class="field-row">
<div class="field"><label>Zone 域名</label><input name="zone_name" placeholder="如 example.com"></div>
<div class="field"><label>A 记录名</label><input name="record_name" placeholder="如 www.example.com 或 @"></div>
</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">添加映射</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
let insts = [];
try { insts = await api('GET', `/api/accounts/${curAccount.id}/instances`); }
catch (e) { toast('获取实例列表失败: ' + e.message, true); }
const sel = document.getElementById('dnsMapInstSel');
sel.innerHTML = insts.length
? insts.map(it => `<option value="${esc(it.id)}">${esc(it.name)}（${esc(it.public_ip || '无公网IP')}）</option>`).join('')
: '<option value="">该账号下没有实例</option>';
document.getElementById('dnsMapForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
const instId = fd.get('instance_id');
if (!instId) { toast('请选择实例', true); return;}
let zone = fd.get('zone_name').trim();
let rec = fd.get('record_name').trim();
if (!zone || !rec) { toast('请填写 Zone 域名和 A 记录名', true); return;}
if (rec === '@') rec = zone;
else if (!rec.includes('.')) rec = rec + '.' + zone;
try {
await api('POST', '/api/dns-mappings', {
account_id: curAccount.id, instance_id: instId,
zone_name: zone, record_name: rec});
toast('映射已添加');
renderDnsMappingList(insts);
e.target.reset();
} catch (err) { toast(err.message, true); }
};
renderDnsMappingList(insts);
}

async function renderDnsMappingList(insts) {
const el = document.getElementById('dnsMapList');
if (!el || !curAccount) return;
if (!insts) insts = instances;
let maps = [];
try { maps = await api('GET', `/api/dns-mappings?account_id=${curAccount.id}`); }
catch (e) { el.innerHTML = '<div class="empty">加载失败</div>'; return;}
const instLabel = id => {
const it = (insts || []).find(x => x.id === id);
return it? `${esc(it.name)}（${esc(it.public_ip || '无公网IP')}）`
: `<span class="mono">${esc(String(id).slice(-16))}</span>`;
};
el.innerHTML = maps.length
? `<table><thead><tr><th>实例</th><th>Zone</th><th>A 记录</th><th>操作</th></tr></thead><tbody>` +
maps.map(m => `<tr><td>${instLabel(m.instance_id)}</td>
<td class="mono">${esc(m.zone_name)}</td>
<td class="mono">${esc(m.record_name)}</td>
<td><button class="btn sm danger" onclick="delDnsMapping(${m.id})">删除</button></td></tr>`).join('') + '</tbody></table>'
: '<div class="empty">还没有映射。添加后，该实例换 IP 会自动更新 A 记录。</div>';
}

async function delDnsMapping(id) {
if (!confirm('确定删除这条 DNS 映射吗？')) return;
try {
await api('DELETE', `/api/dns-mappings/${id}`);
toast('映射已删除');
renderDnsMappingList(instances);
} catch (e) { toast(e.message, true); }
}

init();
