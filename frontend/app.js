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
const fmtTime = s => { if (!s) return '-'; const d = new Date(s); return isNaN(d)? s: d.toLocaleString('zh-CN', {hour12: false});};

async function init() {
const me = await api('GET', '/api/me');
if (!me.logged_in) { location.href = '/login.html'; return;}
providers = await api('GET', '/api/providers');
const nav = document.getElementById('providerNav');
const colors = {oci: '#4ade80', aws: '#fbbf24', azure: '#5aa9ff'};
nav.innerHTML = providers.map(p =>
`<div class="nav-item" data-p="${p.id}" onclick="selectProvider('${p.id}')">
<span class="dot" style="background:${colors[p.id] || '#8b93ad'}"></span>${esc(p.name)}
</div>`).join('');
selectProvider(providers[0].id);
}

function selectProvider(id) {
curProvider = providers.find(p => p.id === id);
document.querySelectorAll('#providerNav.nav-item').forEach(el =>
el.classList.toggle('active', el.dataset.p === id));
curTab = 'instances';
loadAccounts();
}

function renderTabs() {
const defs = [{key: 'instances', label: curProvider.id === 'aws'? 'EC2': '实例'}];
if (curProvider.supports_lightsail) defs.push({key: 'lightsail', label: 'Lightsail'});
if (curProvider.supports_cloudfront) defs.push({key: 'cloudfront', label: 'CloudFront'});
if (curProvider.supports_billing) defs.push({key: 'billing', label: '账单'});
if (curProvider.supports_quotas) defs.push({key: 'quotas', label: '配额'});
if (curProvider.supports_subscription) defs.push({key: 'subscription', label: '订阅'});
if (!defs.find(d => d.key === curTab)) curTab = 'instances';
document.getElementById('tabs').innerHTML = defs.map(d =>
`<div class="tab${d.key === curTab? ' active': ''}" onclick="switchTab('${d.key}')">${d.label}</div>`).join('');
const isInst = curTab === 'instances';
document.getElementById('createBtn').style.display = isInst? '': 'none';
document.getElementById('snatchBtn').style.display =
(isInst && curProvider.supports_snatch)? '': 'none';
}

function switchTab(key) {
curTab = key;
renderTabs();
refreshCurTab();
}

function refreshCurTab() {
if (!curAccount) { renderEmpty(); return;}
if (curTab === 'billing') loadBilling();
else if (curTab === 'lightsail') loadLightsail();
else if (curTab === 'cloudfront') loadCloudFront();
else if (curTab === 'quotas') loadQuotas();
else if (curTab === 'subscription') loadSubscription();
else loadInstances();
}

/* ---------- 账号存活天数 ---------- */
const aliveDays = a => a.created_at != null? Math.max(0, Math.floor((Date.now() / 1000 - a.created_at) / 86400)): null;
const aliveLabel = a => { const d = aliveDays(a); return d == null? '': `（存活${d}天）`; };

async function loadAccounts(selectId) {
accounts = await api('GET', `/api/accounts?provider=${curProvider.id}`);
const sel = document.getElementById('accountSel');
sel.innerHTML = accounts.map(a => `<option value="${a.id}">${esc(a.name)}${esc(aliveLabel(a))}</option>`).join('')
|| '<option value="">（暂无账号）</option>';
curAccount = accounts.find(a => String(a.id) === String(selectId || sel.value)) || accounts[0] || null;
if (curAccount) sel.value = curAccount.id;
renderTabs();
refreshCurTab();
}

function onAccountChange() {
const id = document.getElementById('accountSel').value;
curAccount = accounts.find(a => String(a.id) === id) || null;
curTab = 'instances';
renderTabs();
refreshCurTab();
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
c.innerHTML = `<table><thead><tr>
<th>名称</th><th>状态</th><th>规格</th><th>公网 IP</th><th>内网 IP</th>
<th>地域</th><th>创建时间</th><th>操作</th></tr></thead><tbody>` +
instances.map((it, i) => `<tr>
<td>${esc(it.name)}<br><span class="mono">${esc(it.id.slice(-12))}</span></td>
<td>${badge(it.status)}<br><span style="color:#6f7794;font-size:11px">${esc(it.status_text || '')}</span></td>
<td>${esc(it.shape)}${it.cpu? `<br><span style="color:#8b93ad">${esc(it.cpu)}C / ${esc(it.memory)}G</span>`: ''}</td>
<td class="mono">${esc(it.public_ip || '-')}</td>
<td class="mono">${esc(it.private_ip || '-')}${it.ipv6? `<br>${esc(it.ipv6)}`: ''}</td>
<td>${esc(it.region || '')}${it.zone? `<br><span style="color:#6f7794;font-size:11px">${esc(it.zone)}</span>`: ''}</td>
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
if (action === 'open_port') {
openParamModal('开放端口', inst, 'open_port',
[{key: 'port', label: '端口', type: 'number', required: true, placeholder: '如 8080'}],
'将在安全组/安全列表放行该 TCP 端口（来源 0.0.0.0/0）。');
return;}
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
async function loadBilling() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
try {
const b = await api('GET', `/api/accounts/${curAccount.id}/billing`);
const money = v => (b.currency? b.currency + ' ': '') + Number(v).toFixed(2);
let creditHtml = '';
if (b.credit_used > 0 || b.credit_total != null) {
const remain = b.credit_total != null? Math.max(0, b.credit_total - (b.credit_used || 0)): null;
creditHtml = `<div style="display:flex;gap:24px;margin:12px 0;padding:12px 16px;background:#1a2138;border-radius:8px">
<div><div style="color:#8b93ad;font-size:12px">Credit 抵扣（本月）</div>
<div style="font-size:18px;color:#4ade80">-${money(b.credit_used || 0)}</div></div>
${remain != null? `<div><div style="color:#8b93ad;font-size:12px">Credit 剩余（估算）</div>
<div style="font-size:18px;color:#fbbf24">${money(remain)}</div></div>`: ''}
<div style="margin-left:auto;align-self:center">
<button class="btn sm" onclick="setCreditTotal(${b.credit_total != null? b.credit_total: ''})">
${b.credit_total != null? '修改': '设置'} Credit 总额</button></div></div>
${remain != null? '<div class="help" style="color:#6f7794;font-size:12px;margin-bottom:12px">剩余 = 总额 − 本月已用；AWS 不提供剩余 credit 的 API，总额需手动填写</div>': ''}`;
}
c.innerHTML = `<div class="bill-total"><div class="amount">${money(b.total)}</div>
<div class="meta">统计周期：${esc(b.period)}${b.note? '<br>' + esc(b.note): ''}</div></div>` +
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

async function setCreditTotal(cur) {
const v = prompt('请输入该 AWS 账号的 Credit 总额（数字，留空则清除）：', cur === ''? '': cur);
if (v === null) return;
const t = v.trim() === ''? null: Number(v.trim());
if (t !== null && (!isFinite(t) || t < 0)) { toast('请输入有效的非负数字', true); return;}
try {
await api('PUT', `/api/accounts/${curAccount.id}/credit-total`, {total: t});
toast('已保存'); loadBilling();
} catch (e) { toast(e.message, true);}
}

/* ---------- 配额 / 订阅 ---------- */
async function loadQuotas() {
const c = document.getElementById('content');
c.innerHTML = '<div class="empty">加载中…</div>';
try {
const q = await api('GET', `/api/accounts/${curAccount.id}/quotas`);
c.innerHTML = (q.groups || []).map(g =>
`<h3 style="margin:18px 0 10px;font-size:14px;color:#aab2cc">${esc(g.title)}</h3>
<table><thead><tr><th>项目</th><th>详情</th></tr></thead><tbody>` +
(g.items || []).map(it => `<tr><td class="mono">${esc(it.name)}</td><td>${esc(it.detail)}</td></tr>`).join('') +
'</tbody></table>').join('') +
(q.note? `<div class="help" style="color:#6f7794;margin-top:12px;font-size:12px">${esc(q.note)}</div>`: '') ||
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
(s.note? `<div class="help" style="color:#6f7794;margin-top:12px;font-size:12px">${esc(s.note)}</div>`: '');
} catch (e) {
c.innerHTML = `<div class="empty">加载失败: ${esc(e.message)}<br><button class="btn" onclick="loadSubscription()">重试</button></div>`;
}
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
<select id="lsRegionSel" onchange="lsRegion=this.value;loadLightsail()" style="background:#0f1420;color:#e6e9f0;border:1px solid #2a3350;border-radius:8px;padding:8px 10px">
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
<td>${esc(it.bundle)}<br><span style="color:#6f7794;font-size:11px">${esc(it.blueprint)}</span></td>
<td class="mono">${esc(it.public_ip || '-')}${it.ipv6? `<br>${esc(it.ipv6)}`: ''}</td>
<td class="mono">${esc(it.private_ip || '-')}</td>
<td>${esc(lsRegionLabel(it.region))}${it.zone? `<br><span style="color:#6f7794;font-size:11px">${esc(it.zone)}</span>`: ''}</td>
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
${formField({key: 'key_pair', label: '密钥对（可选）', placeholder: '已有的 Lightsail 密钥对名，留空则不绑定'})}
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
c.innerHTML = header + (list.length
? `<table><thead><tr><th>分发</th><th>状态</th><th>域名/别名</th><th>源站</th><th>价格等级</th><th>操作</th></tr></thead><tbody>` +
list.map(d => `<tr>
<td><span class="mono">${esc(d.id)}</span><br><span style="color:#6f7794;font-size:11px">${esc(d.domain)}</span>
${d.comment? `<br><span style="font-size:12px">${esc(d.comment)}</span>`: ''}</td>
<td>${d.enabled? '<span class="badge b-running">已启用</span>': '<span class="badge b-stopped">已停用</span>'}
<br><span style="color:#6f7794;font-size:11px">${esc(d.status)}</span></td>
<td style="font-size:12px">${d.aliases.map(esc).join('<br>') || '-'}</td>
<td style="font-size:12px" class="mono">${d.origins.map(esc).join('<br>') || '-'}</td>
<td>${esc(d.price_class || '-')}</td>
<td><div class="row-actions">
<button class="btn sm" onclick="openInvalidateModal('${esc(d.id)}')">刷新缓存</button>
${d.enabled
? `<button class="btn sm danger" onclick="cfToggle('${esc(d.id)}', false)">停用</button>`
: `<button class="btn sm" onclick="cfToggle('${esc(d.id)}', true)">启用</button>`}
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
<div class="help" style="color:#8b93ad;margin-bottom:14px">CloudFront 每月前 1000 条刷新路径免费，超出后按量收费。</div>
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

function openCfCreateModal() {
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>创建 CloudFront 分发</h2>
<form id="cfCreateForm">
${formField({key: 'origin_domain', label: '源站域名', required: true, placeholder: '如 example.com（不带 https://）'})}
${row({key: 'price_class', label: '价格等级', type: 'select',
options: ['100（北美+欧洲·最便宜）', '200（+亚洲）', 'all（全部边缘节点）'], value: '100（北美+欧洲·最便宜）'},
{key: 'comment', label: '备注（可选）', placeholder: '如 官网加速'})}
<div class="help" style="color:#8b93ad;margin:-6px 0 14px">默认配置：回源走 HTTP、访客侧 HTTP 跳 HTTPS、缓存优化策略。分发部署约需 15 分钟。</div>
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

function openAccountModal() {
const p = curProvider;
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>账号管理 · ${esc(p.name)}</h2>
<div style="margin-bottom:10px"><button class="btn sm" onclick="testAllAccounts()">🔍 一键测活（测试本云全部账号）</button></div>
<div id="testAllResult"></div>
${accounts.map(a => `<div style="display:flex;align-items:center;gap:8px;padding:9px 0;border-bottom:1px solid #232b45">
<span style="flex:1">${esc(a.name)}${aliveDays(a) != null? `<br><span style="color:#6f7794;font-size:12px">存活 ${aliveDays(a)} 天</span>`: ''}</span>
<button class="btn sm" onclick="testAccount(${a.id})">测试连接</button>
<button class="btn sm" onclick="openMonitorModal(${a.id})">🔔 监控</button>
<button class="btn sm" onclick="editAccount(${a.id})">编辑</button>
<button class="btn sm danger" onclick="delAccount(${a.id})">删除</button></div>`).join('')
|| '<div style="color:#8b93ad;padding:8px 0">暂无账号</div>'}
<h2 style="margin-top:20px">添加账号</h2>
<form id="accForm">
<div class="field"><label>账号别名 <span class="req">*</span></label>
<input name="name" required placeholder="如：甲骨文-东京"></div>
${p.fields.map(f => `<div class="field"><label>${esc(f.label)}${f.required? ' <span class="req">*</span>': ''}</label>
${fieldInput(f, '')}${f.help? `<div class="help">${esc(f.help)}</div>`: ''}</div>`).join('')}
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">保存（自动校验连通性）</button>
</div>
</form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('accForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
const creds = {};
p.fields.forEach(f => creds[f.key] = (fd.get(f.key) || '').trim());
try {
await api('POST', '/api/accounts', {provider: p.id, name: fd.get('name').trim(), creds});
toast('账号已添加'); closeModal(); loadAccounts();
} catch (err) { toast(err.message, true);}
};
}

async function editAccount(id) {
const p = curProvider;
// 重新拉取解密后的凭证需要后端支持，这里简化：只改别名，或重填全部凭证
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>编辑账号</h2>
<form id="accEditForm">
<div class="field"><label>账号别名 <span class="req">*</span></label>
<input name="name" required value="${esc(accounts.find(a => a.id === id).name)}"></div>
<div class="help" style="color:#8b93ad;margin-bottom:14px">如需更换凭证请删除后重新添加；这里只修改别名。</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="openAccountModal()">返回</button>
<button type="submit" class="btn primary">保存</button>
</div>
</form>`;
document.getElementById('accEditForm').onsubmit = async e => {
e.preventDefault();
const name = new FormData(e.target).get('name').trim();
try { await api('PUT', `/api/accounts/${id}`, {name}); toast('已保存'); closeModal(); loadAccounts(id);}
catch (err) { toast(err.message, true);}
};
}

async function delAccount(id) {
if (!confirm('确定删除该账号吗？其凭证将从本地彻底删除。')) return;
try { await api('DELETE', `/api/accounts/${id}`); toast('已删除'); openAccountModal(); loadAccounts();}
catch (e) { toast(e.message, true);}
}

async function testAccount(id) {
try { await api('POST', `/api/accounts/${id}/test`); toast('连接正常');}
catch (e) { toast(e.message, true);}
}

async function testAllAccounts() {
const box = document.getElementById('testAllResult');
box.innerHTML = '<div style="color:#8b93ad;padding:6px 0">测活中…</div>';
try {
const list = await api('POST', `/api/accounts/test-all?provider=${curProvider.id}`);
box.innerHTML = list.map(r =>
`<div style="padding:6px 0;border-bottom:1px solid #232b45;font-size:13px">
${r.ok? '✅': '❌'} ${esc(r.name)} <span style="color:#6f7794">${esc(r.message)}</span></div>`).join('')
|| '<div style="color:#8b93ad">暂无账号</div>';
} catch (e) { box.innerHTML = `<div style="color:#ff7a7a">测活失败: ${esc(e.message)}</div>`;}
}

async function openMonitorModal(id) {
const acc = accounts.find(a => a.id === id);
let m = {monitor_alert: false, monitor_restart: false};
try { m = await api('GET', `/api/accounts/${id}/monitor`);} catch (e) { toast(e.message, true); return;}
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>监控设置 · ${esc(acc.name)}</h2>
<form id="monitorForm">
<div class="check-row"><input type="checkbox" name="monitor_alert"${m.monitor_alert? ' checked': ''}>
<span>状态告警：实例异常停止/恢复时 Telegram 推送通知</span></div>
<div class="check-row"><input type="checkbox" name="monitor_restart"${m.monitor_restart? ' checked': ''}>
<span>异常自启：实例异常停止后自动提交启动任务</span></div>
<div class="help" style="color:#8b93ad;margin-bottom:14px">后台每 N 分钟巡检一次（N 在"设置"里配置，默认 5 分钟）。需要先在设置里配置 Telegram 才能收到通知。</div>
<div class="modal-actions">
<button type="button" class="btn" onclick="openAccountModal()">返回</button>
<button type="submit" class="btn primary">保存</button>
</div></form>`;
document.getElementById('monitorForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
try {
await api('PUT', `/api/accounts/${id}/monitor`,
{monitor_alert: !!fd.get('monitor_alert'), monitor_restart: !!fd.get('monitor_restart')});
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
{key: 'password', label: '密码（可选）', placeholder: '留空自动生成 16 位随机密码'})}
${formField({key: 'assign_public_ip', label: '分配公网 IP', type: 'checkbox', value: true})}
${formField({key: 'startup_script', label: '开机脚本（可选）', type: 'textarea'})}`;
if (p.id === 'aws') return `
${formField({key: 'name', label: '实例名（Name 标签）', placeholder: '留空自动生成'})}
${row({key: 'region', label: '区域', type: 'select', options: opts.regions, value: opts.default_region || opts.regions[0]},
{key: 'instance_type', label: '实例类型', type: 'select', options: opts.instance_types, value: 't2.micro'})}
${row({key: 'key_name', label: '密钥对', type: 'select', options: ['（自动创建新密钥对）',...(opts.key_pairs || [])]},
{key: 'ami', label: 'AMI（可选）', placeholder: '留空自动使用最新 Ubuntu 22.04'})}
<div class="help" style="color:#8b93ad;margin:-6px 0 14px">将在目标区域的默认 VPC 自动创建安全组（放行 SSH）。密钥对列表为账号默认区域的——若选择其他区域，将自动创建新密钥对。新密钥对的私钥只在任务结果中显示一次。</div>`;
if (p.id === 'azure') return `
${row({key: 'name', label: '虚拟机名（可选）', placeholder: '留空自动生成'},
{key: 'resource_group', label: '资源组（可选）', placeholder: '留空自动创建'})}
${row({key: 'location', label: '区域', type: 'select', options: opts.locations, value: opts.locations.includes('japaneast')? 'japaneast': opts.locations[0]},
{key: 'vm_size', label: '规格', type: 'select', options: opts.vm_sizes, value: 'Standard_B1s'})}
${row({key: 'image', label: '镜像', type: 'select', options: opts.images},
{key: 'disk_gb', label: '系统盘 GB', type: 'number', value: '30'})}
${row({key: 'admin_username', label: '管理员用户', value: 'azureuser'},
{key: 'password', label: '密码（可选）', placeholder: '留空自动生成'})}
${formField({key: 'ssh_key', label: 'SSH 公钥（可选，Linux 有效）', type: 'textarea'})}`;
return '';
}

let lastCreateOpts = null; // 最近一次创建选项，供 readForm 判断跨区
function readForm(form, p) {
const fd = new FormData(form), o = {};
const fields = p.id === 'oci'
? ['name', 'availability_domain', 'shape', 'ocpus', 'memory_gbs', 'os', 'ssh_key', 'boot_volume_gb', 'login_user', 'password', 'startup_script']
: p.id === 'aws'? ['name', 'region', 'instance_type', 'ami', 'key_name']
: ['name', 'resource_group', 'location', 'vm_size', 'image', 'admin_username', 'password', 'ssh_key', 'disk_gb'];
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

async function openCreateModal() {
if (!curAccount) { toast('请先添加账号', true); return;}
const opts = await api('GET', `/api/accounts/${curAccount.id}/create-options`).catch(e => { toast(e.message, true); return null;});
if (!opts) return;
lastCreateOpts = opts;
const box = document.getElementById('modalBox');
box.innerHTML = `<h2>创建实例 · ${esc(curProvider.name)}</h2>
<form id="createForm">${createFormHTML(curProvider, opts)}
<div class="modal-actions">
<button type="button" class="btn" onclick="closeModal()">取消</button>
<button type="submit" class="btn primary">提交创建（后台执行）</button>
</div></form>`;
document.getElementById('modalMask').classList.add('show');
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
<div class="help" style="color:#fbbf24;margin-bottom:14px">后台循环尝试创建，遇到资源不足自动按间隔重试，手动停止前不会停。请合理设置间隔，避免被限流。</div>
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
${tip? `<div class="help" style="color:#fbbf24;margin-bottom:6px">${esc(tip)}</div>`: ''}
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
try {
const r = await api('POST', `/api/accounts/${curAccount.id}/action`,
{instance: inst, action, params});
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
<div class="help" style="color:#fbbf24;margin-bottom:6px">注意：OCI 要求实例先关机再改配置，面板会自动处理等待。请确认规格在该可用域可用。</div>
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
box.innerHTML = `<h2>设置 · Telegram 联动</h2>
<div class="help" style="color:#8b93ad;margin-bottom:14px">
1. 在 Telegram 里找 @BotFather 创建 Bot，拿到 Token<br>
2. 给你的 Bot 发任意消息，然后访问 <span class="mono">https://api.telegram.org/bot&lt;Token&gt;/getUpdates</span> 查出 chat.id<br>
3. 填到下面保存。之后任务完成/失败会自动推送，Bot 里点 /start 可用按钮操作实例。<br>
${s.tg_bot_token_set ? '当前状态：' + (s.tg_bot_running ? 'Bot 运行中 ✅' : 'Token 已保存，Bot 未运行') : '当前状态：未配置'}</div>
<form id="tgForm">
<div class="field"><label>Bot Token</label>
<input name="tg_bot_token" type="password" placeholder="${s.tg_bot_token_set ? '已保存，留空不修改' : '如 123456:ABC-DEF…'}"></div>
<div class="field"><label>Chat ID</label>
<input name="tg_chat_id" value="${esc(s.tg_chat_id || '')}" placeholder="如 123456789"></div>
<h2 style="margin-top:20px">监控与每日报告</h2>
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
</div></form>`;
document.getElementById('modalMask').classList.add('show');
document.getElementById('tgForm').onsubmit = async e => {
e.preventDefault();
const fd = new FormData(e.target);
try {
await api('PUT', '/api/settings', {
tg_bot_token: fd.get('tg_bot_token').trim(),
tg_chat_id: fd.get('tg_chat_id').trim(),
daily_report: !!fd.get('daily_report'),
daily_report_hour: parseInt(fd.get('daily_report_hour') || '9', 10),
monitor_interval_min: parseInt(fd.get('monitor_interval_min') || '5', 10),
});
closeModal(); toast('设置已保存');
} catch (err) { toast(err.message, true); }
};
}).catch(e => toast(e.message, true));
}

async function tgTest() {
try { await api('POST', '/api/settings/tg-test'); toast('测试消息已发送，去 Telegram 看看'); }
catch (e) { toast(e.message, true); }
}

init();
