/* TriCloud 前端逻辑 */
let providers = [], curProvider = null;
let accounts = [], curAccount = null;
let instances = [];
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
document.getElementById('snatchBtn').style.display = curProvider.supports_snatch? '': 'none';
loadAccounts();
}

async function loadAccounts(selectId) {
accounts = await api('GET', `/api/accounts?provider=${curProvider.id}`);
const sel = document.getElementById('accountSel');
sel.innerHTML = accounts.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join('')
|| '<option value="">（暂无账号）</option>';
curAccount = accounts.find(a => String(a.id) === String(selectId || sel.value)) || accounts[0] || null;
if (curAccount) sel.value = curAccount.id;
if (curAccount) loadInstances(); else renderEmpty();
}

function onAccountChange() {
const id = document.getElementById('accountSel').value;
curAccount = accounts.find(a => String(a.id) === id) || null;
if (curAccount) loadInstances();
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
${accounts.map(a => `<div style="display:flex;align-items:center;gap:8px;padding:9px 0;border-bottom:1px solid #232b45">
<span style="flex:1">${esc(a.name)}</span>
<button class="btn sm" onclick="testAccount(${a.id})">测试连接</button>
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
${row({key: 'instance_type', label: '实例类型', type: 'select', options: opts.instance_types, value: 't2.micro'},
{key: 'key_name', label: '密钥对', type: 'select', options: ['（自动创建新密钥对）',...(opts.key_pairs || [])]})}
${formField({key: 'ami', label: 'AMI（可选）', placeholder: '留空自动使用最新 Ubuntu 22.04'})}
<div class="help" style="color:#8b93ad;margin:-6px 0 14px">将在默认 VPC 自动创建安全组（放行 SSH）。新密钥对的私钥只在任务结果中显示一次。</div>`;
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

function readForm(form, p) {
const fd = new FormData(form), o = {};
const fields = p.id === 'oci'
? ['name', 'availability_domain', 'shape', 'ocpus', 'memory_gbs', 'os', 'ssh_key', 'boot_volume_gb', 'login_user', 'password', 'startup_script']
: p.id === 'aws'? ['name', 'instance_type', 'ami', 'key_name']
: ['name', 'resource_group', 'location', 'vm_size', 'image', 'admin_username', 'password', 'ssh_key', 'disk_gb'];
fields.forEach(k => o[k] = (fd.get(k) || '').trim());
if (p.id === 'oci') {
o.assign_public_ip =!!fd.get('assign_public_ip');
if (o.key_name === '（自动创建新密钥对）') o.key_name = '';
}
if (p.id === 'aws' && o.key_name === '（自动创建新密钥对）') o.key_name = '';
return o;
}

async function openCreateModal() {
if (!curAccount) { toast('请先添加账号', true); return;}
const opts = await api('GET', `/api/accounts/${curAccount.id}/create-options`).catch(e => { toast(e.message, true); return null;});
if (!opts) return;
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

function openShapeModal(inst) {
const box = document.getElementById('modalBox');
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

init();
