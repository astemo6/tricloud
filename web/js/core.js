// TriCloud 前端 v1.6.0 · 基础：DOM 工具、API 请求、提示 / 弹窗、全局常量与共享状态（账号 / 设置 / 可添加云厂商）、区域、时间格式化
// v1.4 紧凑模式（每台设备单独记忆）尽早生效，避免闪烁
try { if (localStorage.getItem("tc_compact") === "1") document.documentElement.classList.add("compact"); } catch (_) { /* ignore */ }
export const $ = (s, r = document) => r.querySelector(s);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const view = $("#view");
export let ACCOUNTS = [];
export let SETTINGS = {};

// ---------------- API ----------------
export async function api(path, opt = {}) {
  const init = { method: opt.method || "GET", headers: {}, credentials: "same-origin" };
  if (opt.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opt.body); }
  const r = await fetch("/api" + path, init);
  if (r.status === 401) { sessionStorage.setItem("tc_back", location.hash); location.href = "/login"; throw new Error("未登录"); }
  const j = await r.json().catch(() => ({}));
  if (r.status === 409 && j.detail && j.detail.guard) {   // v1.2 免费额度护栏：二次确认后带 confirm_overage 重发
    const go = await modal("⚠️ 可能超出免费额度", `<ul class="guard">${j.detail.guard.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
      <p class="muted">免费额度以云厂商公示和你的账号类型为准。可在「设置 → 免费额度护栏」关闭此提醒。</p>`, null, "仍然继续", true);
    if (!go) throw new Error("已取消");
    return api(path, { ...opt, body: { ...(opt.body || {}), confirm_overage: true } });
  }
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : (j.detail && j.detail.msg) || r.statusText);
  // v1.4：提交了后台任务 → 自动打开右侧任务抽屉并跟踪
  if (init.method !== "GET" && j && (j.task_id || (j.task_ids && j.task_ids.length)) && window.TaskDrawer) window.TaskDrawer.open(j.task_id || j.task_ids[0]);
  return j;
}
export const post = (p, b) => api(p, { method: "POST", body: b || {} });
export const del = (p) => api(p, { method: "DELETE" });

// 页面脚本出错时直接提示，避免点了按钮没反应（例如 Windows 客户端里）
window.addEventListener("error", (e) => { try { toast("页面出错：" + (e.message || e.error), true); } catch (_) {} });
window.addEventListener("unhandledrejection", (e) => { try { toast("操作出错：" + ((e.reason && e.reason.message) || e.reason), true); } catch (_) {} });
export function toast(msg, err) {
  const d = document.createElement("div");
  d.className = "toast" + (err ? " err" : "");
  d.textContent = msg;
  document.body.appendChild(d);
  setTimeout(() => d.remove(), err ? 6000 : 4500);
}
export async function act(btn, fn, okMsg) {
  if (btn) btn.disabled = true;
  try { const r = await fn(); if (okMsg) toast(typeof okMsg === "function" ? okMsg(r) : okMsg); return r; }
  catch (e) { toast(e.message, true); }
  finally { if (btn) btn.disabled = false; }
}
export function modal(title, bodyHtml, onOk, okText = "确定", danger = false, onOpen = null) {
  return new Promise((resolve) => {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `<div class="modal"><h3>${esc(title)}</h3><div class="mb">${bodyHtml}</div>
      <div class="acts"><button class="btn" data-x>取消</button><button class="btn ${danger ? "danger" : "primary"}" data-ok>${esc(okText)}</button></div></div>`;
    document.body.appendChild(bg);
    applyShowWhen(bg); bg.addEventListener("change", () => applyShowWhen(bg));
    if (onOpen) onOpen(bg);
    const close = (v) => { bg.remove(); resolve(v); };
    bg.querySelector("[data-x]").onclick = () => close(null);
    // 只有按下和松开都在遮罩本身时才关闭：在输入框里拖选文字、松开时落到遮罩上，click 的目标也是遮罩，不能因此关窗
    let downOnBg = false;
    const markDown = (e) => { downOnBg = e.target === bg; };
    bg.addEventListener("pointerdown", markDown); bg.addEventListener("mousedown", markDown);
    bg.onclick = (e) => { if (e.target === bg && downOnBg) close(null); downOnBg = false; };
    bg.querySelector("[data-ok]").onclick = async (e) => {
      const b = e.target; b.disabled = true;
      try { const v = onOk ? await onOk(bg) : true; if (v !== false) close(v ?? true); }
      catch (err) { toast(err.message, true); }
      finally { b.disabled = false; }
    };
  });
}
// v1.4：<div data-show-when="mode=rolling"> 按同一弹窗里字段的值显示 / 隐藏（多个条件用 & 连接，值可用 | 表示或）
export function applyShowWhen(root) {
  root.querySelectorAll("[data-show-when]").forEach((el) => {
    const okAll = el.dataset.showWhen.split("&").every((cond) => {
      const [k, v] = cond.split("="); const f = root.querySelector(`[name="${k}"]`);
      if (!f) return true;
      const val = f.type === "checkbox" ? String(f.checked) : f.value;
      return v.split("|").includes(val);
    });
    el.style.display = okAll ? "" : "none";
  });
}
export const confirmBox = (t, msg, danger) => modal(t, `<p>${msg}</p>`, null, "确认", danger);
export const form = (root) => Object.fromEntries([...root.querySelectorAll("[name]")].map((i) => [i.name, i.type === "checkbox" ? i.checked : i.value.trim()]));
export const loading = () => (view.innerHTML = `<div class="empty"><span class="spin"></span> 加载中…</div>`);

// ---------------- 路由 ----------------
export const TABS = {
  oci: [["instances", "实例"], ["create", "创建实例"], ["snatch", "自动抢机"], ["secgroup", "安全组"], ["storage", "存储"], ["objects", "对象存储"], ["traffic", "流量"], ["limits", "配额/网络"], ["billing", "账单"]],   // 区域订阅收在「配额/网络」页底部的折叠区（防误点）
  aws: [["ec2", "EC2"], ["lightsail", "Lightsail"], ["regions", "区域"], ["cloudfront", "CloudFront"], ["quota", "配额"], ["recycle", "闲置资源"], ["billing", "账单"], ["credit", "新号 Credit"]],
  azure: [["vms", "虚拟机"], ["azcreate", "创建 VM"], ["rgs", "资源组"], ["azquota", "配额"], ["foundry", "Foundry"], ["subscription", "订阅"], ["billing", "账单"]],
};
// 已移除的标签：旧链接跳到新位置（#/oci/1/regionsub → 配额/网络）
export const TAB_ALIAS = { oci: { regionsub: "limits" } };
export const PNAME = { oci: "Oracle Cloud", aws: "AWS", azure: "Azure" };
// 扩展点（附加云厂商可在自己的代码块里登记）
export const PROVS = ["oci", "aws", "azure"];          // 侧栏 / 切换器 / 下拉的顺序
export let META = { providers: PROVS.slice() };         // GET /api/meta：当前可添加的云厂商
export const NO_REGION = new Set(["azure"]);            // 没有区域概念的云
export const NO_CHANGE_IP = new Set();                  // 不能换 IP 的云（监控里不显示「不通自动换 IP」）
export const NO_CREATE = new Set();                     // 不能创建实例的云（不能作为迁移目标）
export const TAB_FNS_EXTRA = {}, OP_NAMES = {}, TRAFFIC_DIALOG = {}, ADD_BODY = {}, PROV_HINT = {};
export const TEXTAREA_FIELDS = new Set(["key_content"]);
export const SETTINGS_CARDS = [];                       // [{ html(settings), bind(root) }]
export const NOREG = (acc) => NO_REGION.has(acc.provider);
export const provOpts = (blank) => (blank ? `<option value="">${esc(blank)}</option>` : "") + PROVS.filter((p) => META.providers.includes(p)).map((p) => `<option value="${p}">${esc(PNAME[p])}</option>`).join("");
// 三家官方 Logo（内联 SVG；AWS 文字随主题用 currentColor）
export const PLOGO = {"oci": "<svg class=\"plogo\" aria-hidden=\"true\" viewBox=\"0 0 24 24\" xmlns=\"http://www.w3.org/2000/svg\"><path fill=\"#C74634\" d=\"M16.412 4.412h-8.82a7.588 7.588 0 0 0-.008 15.176h8.828a7.588 7.588 0 0 0 0-15.176zm-.193 12.502H7.786a4.915 4.915 0 0 1 0-9.828h8.433a4.914 4.914 0 1 1 0 9.828z\"/></svg>", "aws": "<svg class=\"plogo aws\" aria-hidden=\"true\" viewBox=\"0 0 304 182\" xmlns=\"http://www.w3.org/2000/svg\"><g><path fill=\"currentColor\" d=\"M86.4,66.4c0,3.7,0.4,6.7,1.1,8.9c0.8,2.2,1.8,4.6,3.2,7.2c0.5,0.8,0.7,1.6,0.7,2.3c0,1-0.6,2-1.9,3l-6.3,4.2 c-0.9,0.6-1.8,0.9-2.6,0.9c-1,0-2-0.5-3-1.4C76.2,90,75,88.4,74,86.8c-1-1.7-2-3.6-3.1-5.9c-7.8,9.2-17.6,13.8-29.4,13.8 c-8.4,0-15.1-2.4-20-7.2c-4.9-4.8-7.4-11.2-7.4-19.2c0-8.5,3-15.4,9.1-20.6c6.1-5.2,14.2-7.8,24.5-7.8c3.4,0,6.9,0.3,10.6,0.8 c3.7,0.5,7.5,1.3,11.5,2.2v-7.3c0-7.6-1.6-12.9-4.7-16c-3.2-3.1-8.6-4.6-16.3-4.6c-3.5,0-7.1,0.4-10.8,1.3c-3.7,0.9-7.3,2-10.8,3.4 c-1.6,0.7-2.8,1.1-3.5,1.3c-0.7,0.2-1.2,0.3-1.6,0.3c-1.4,0-2.1-1-2.1-3.1v-4.9c0-1.6,0.2-2.8,0.7-3.5c0.5-0.7,1.4-1.4,2.8-2.1 c3.5-1.8,7.7-3.3,12.6-4.5c4.9-1.3,10.1-1.9,15.6-1.9c11.9,0,20.6,2.7,26.2,8.1c5.5,5.4,8.3,13.6,8.3,24.6V66.4z M45.8,81.6 c3.3,0,6.7-0.6,10.3-1.8c3.6-1.2,6.8-3.4,9.5-6.4c1.6-1.9,2.8-4,3.4-6.4c0.6-2.4,1-5.3,1-8.7v-4.2c-2.9-0.7-6-1.3-9.2-1.7 c-3.2-0.4-6.3-0.6-9.4-0.6c-6.7,0-11.6,1.3-14.9,4c-3.3,2.7-4.9,6.5-4.9,11.5c0,4.7,1.2,8.2,3.7,10.6 C37.7,80.4,41.2,81.6,45.8,81.6z M126.1,92.4c-1.8,0-3-0.3-3.8-1c-0.8-0.6-1.5-2-2.1-3.9L96.7,10.2c-0.6-2-0.9-3.3-0.9-4 c0-1.6,0.8-2.5,2.4-2.5h9.8c1.9,0,3.2,0.3,3.9,1c0.8,0.6,1.4,2,2,3.9l16.8,66.2l15.6-66.2c0.5-2,1.1-3.3,1.9-3.9c0.8-0.6,2.2-1,4-1 h8c1.9,0,3.2,0.3,4,1c0.8,0.6,1.5,2,1.9,3.9l15.8,67l17.3-67c0.6-2,1.3-3.3,2-3.9c0.8-0.6,2.1-1,3.9-1h9.3c1.6,0,2.5,0.8,2.5,2.5 c0,0.5-0.1,1-0.2,1.6c-0.1,0.6-0.3,1.4-0.7,2.5l-24.1,77.3c-0.6,2-1.3,3.3-2.1,3.9c-0.8,0.6-2.1,1-3.8,1h-8.6c-1.9,0-3.2-0.3-4-1 c-0.8-0.7-1.5-2-1.9-4L156,23l-15.4,64.4c-0.5,2-1.1,3.3-1.9,4c-0.8,0.7-2.2,1-4,1H126.1z M254.6,95.1c-5.2,0-10.4-0.6-15.4-1.8 c-5-1.2-8.9-2.5-11.5-4c-1.6-0.9-2.7-1.9-3.1-2.8c-0.4-0.9-0.6-1.9-0.6-2.8v-5.1c0-2.1,0.8-3.1,2.3-3.1c0.6,0,1.2,0.1,1.8,0.3 c0.6,0.2,1.5,0.6,2.5,1c3.4,1.5,7.1,2.7,11,3.5c4,0.8,7.9,1.2,11.9,1.2c6.3,0,11.2-1.1,14.6-3.3c3.4-2.2,5.2-5.4,5.2-9.5 c0-2.8-0.9-5.1-2.7-7c-1.8-1.9-5.2-3.6-10.1-5.2L246,52c-7.3-2.3-12.7-5.7-16-10.2c-3.3-4.4-5-9.3-5-14.5c0-4.2,0.9-7.9,2.7-11.1 c1.8-3.2,4.2-6,7.2-8.2c3-2.3,6.4-4,10.4-5.2c4-1.2,8.2-1.7,12.6-1.7c2.2,0,4.5,0.1,6.7,0.4c2.3,0.3,4.4,0.7,6.5,1.1 c2,0.5,3.9,1,5.7,1.6c1.8,0.6,3.2,1.2,4.2,1.8c1.4,0.8,2.4,1.6,3,2.5c0.6,0.8,0.9,1.9,0.9,3.3v4.7c0,2.1-0.8,3.2-2.3,3.2 c-0.8,0-2.1-0.4-3.8-1.2c-5.7-2.6-12.1-3.9-19.2-3.9c-5.7,0-10.2,0.9-13.3,2.8c-3.1,1.9-4.7,4.8-4.7,8.9c0,2.8,1,5.2,3,7.1 c2,1.9,5.7,3.8,11,5.5l14.2,4.5c7.2,2.3,12.4,5.5,15.5,9.6c3.1,4.1,4.6,8.8,4.6,14c0,4.3-0.9,8.2-2.6,11.6 c-1.8,3.4-4.2,6.4-7.3,8.8c-3.1,2.5-6.8,4.3-11.1,5.6C264.4,94.4,259.7,95.1,254.6,95.1z\"/><g><path fill=\"#FF9900\" fill-rule=\"evenodd\" clip-rule=\"evenodd\" d=\"M273.5,143.7c-32.9,24.3-80.7,37.2-121.8,37.2c-57.6,0-109.5-21.3-148.7-56.7c-3.1-2.8-0.3-6.6,3.4-4.4 c42.4,24.6,94.7,39.5,148.8,39.5c36.5,0,76.6-7.6,113.5-23.2C274.2,133.6,278.9,139.7,273.5,143.7z\"/><path fill=\"#FF9900\" fill-rule=\"evenodd\" clip-rule=\"evenodd\" d=\"M287.2,128.1c-4.2-5.4-27.8-2.6-38.5-1.3c-3.2,0.4-3.7-2.4-0.8-4.5c18.8-13.2,49.7-9.4,53.3-5 c3.6,4.5-1,35.4-18.6,50.2c-2.7,2.3-5.3,1.1-4.1-1.9C282.5,155.7,291.4,133.4,287.2,128.1z\"/></g></g></svg>", "azure": "<svg class=\"plogo\" aria-hidden=\"true\" viewBox=\"0 0 96 96\" xmlns=\"http://www.w3.org/2000/svg\"><defs><linearGradient id=\"tcaz0\" x1=\"-1032.172\" x2=\"-1059.213\" y1=\"145.312\" y2=\"65.426\" gradientTransform=\"matrix(1 0 0 -1 1075 158)\" gradientUnits=\"userSpaceOnUse\"><stop offset=\"0\" stop-color=\"#114a8b\"/><stop offset=\"1\" stop-color=\"#0669bc\"/></linearGradient><linearGradient id=\"tcaz1\" x1=\"-1023.725\" x2=\"-1029.98\" y1=\"108.083\" y2=\"105.968\" gradientTransform=\"matrix(1 0 0 -1 1075 158)\" gradientUnits=\"userSpaceOnUse\"><stop offset=\"0\" stop-opacity=\".3\"/><stop offset=\".071\" stop-opacity=\".2\"/><stop offset=\".321\" stop-opacity=\".1\"/><stop offset=\".623\" stop-opacity=\".05\"/><stop offset=\"1\" stop-opacity=\"0\"/></linearGradient><linearGradient id=\"tcaz2\" x1=\"-1027.165\" x2=\"-997.482\" y1=\"147.642\" y2=\"68.561\" gradientTransform=\"matrix(1 0 0 -1 1075 158)\" gradientUnits=\"userSpaceOnUse\"><stop offset=\"0\" stop-color=\"#3ccbf4\"/><stop offset=\"1\" stop-color=\"#2892df\"/></linearGradient></defs><path fill=\"url(#tcaz0)\" d=\"M33.338 6.544h26.038l-27.03 80.087a4.152 4.152 0 0 1-3.933 2.824H8.149a4.145 4.145 0 0 1-3.928-5.47L29.404 9.368a4.152 4.152 0 0 1 3.934-2.825z\"/><path fill=\"#0078d4\" d=\"M71.175 60.261h-41.29a1.911 1.911 0 0 0-1.305 3.309l26.532 24.764a4.171 4.171 0 0 0 2.846 1.121h23.38z\"/><path fill=\"url(#tcaz1)\" d=\"M33.338 6.544a4.118 4.118 0 0 0-3.943 2.879L4.252 83.917a4.14 4.14 0 0 0 3.908 5.538h20.787a4.443 4.443 0 0 0 3.41-2.9l5.014-14.777 17.91 16.705a4.237 4.237 0 0 0 2.666.972H81.24L71.024 60.261l-29.781.007L59.47 6.544z\"/><path fill=\"url(#tcaz2)\" d=\"M66.595 9.364a4.145 4.145 0 0 0-3.928-2.82H33.648a4.146 4.146 0 0 1 3.928 2.82l25.184 74.62a4.146 4.146 0 0 1-3.928 5.472h29.02a4.146 4.146 0 0 0 3.927-5.472z\"/></svg>"};

// ---------------- 区域 ----------------
// 区域代码 → 中文城市名（AWS 以官方区域列表为准，34 个商用区域；OCI 商用区域；Azure 常用 location）。未知区域只显示代码
export const REGION_CITY = {
  // AWS
  "us-east-1": "弗吉尼亚北部", "us-east-2": "俄亥俄", "us-west-1": "加州北部", "us-west-2": "俄勒冈",
  "af-south-1": "开普敦", "ap-east-1": "香港", "ap-east-2": "台北", "ap-south-1": "孟买", "ap-south-2": "海得拉巴",
  "ap-northeast-1": "东京", "ap-northeast-2": "首尔", "ap-northeast-3": "大阪",
  "ap-southeast-1": "新加坡", "ap-southeast-2": "悉尼", "ap-southeast-3": "雅加达", "ap-southeast-4": "墨尔本",
  "ap-southeast-5": "吉隆坡", "ap-southeast-6": "新西兰", "ap-southeast-7": "曼谷",
  "ca-central-1": "蒙特利尔", "ca-west-1": "卡尔加里",
  "eu-central-1": "法兰克福", "eu-central-2": "苏黎世", "eu-north-1": "斯德哥尔摩", "eu-south-1": "米兰", "eu-south-2": "西班牙",
  "eu-west-1": "爱尔兰", "eu-west-2": "伦敦", "eu-west-3": "巴黎",
  "il-central-1": "特拉维夫", "me-central-1": "阿联酋", "me-south-1": "巴林", "mx-central-1": "墨西哥", "sa-east-1": "圣保罗",
  "cn-north-1": "北京", "cn-northwest-1": "宁夏", "us-gov-west-1": "GovCloud 西部", "us-gov-east-1": "GovCloud 东部",
  // OCI
  "ap-sydney-1": "悉尼", "ap-melbourne-1": "墨尔本", "sa-saopaulo-1": "圣保罗", "sa-vinhedo-1": "维涅杜",
  "ca-montreal-1": "蒙特利尔", "ca-toronto-1": "多伦多", "sa-santiago-1": "圣地亚哥", "sa-valparaiso-1": "瓦尔帕莱索", "sa-bogota-1": "波哥大",
  "eu-paris-1": "巴黎", "eu-marseille-1": "马赛", "eu-frankfurt-1": "法兰克福", "ap-hyderabad-1": "海得拉巴", "ap-mumbai-1": "孟买",
  "ap-batam-1": "巴淡岛", "il-jerusalem-1": "耶路撒冷", "eu-milan-1": "米兰", "eu-turin-1": "都灵", "ap-osaka-1": "大阪", "ap-tokyo-1": "东京",
  "ap-kulai-2": "古来", "mx-queretaro-1": "克雷塔罗", "mx-monterrey-1": "蒙特雷", "af-casablanca-1": "卡萨布兰卡", "eu-amsterdam-1": "阿姆斯特丹",
  "me-riyadh-1": "利雅得", "me-jeddah-1": "吉达", "eu-jovanovac-1": "约瓦诺瓦茨", "ap-singapore-1": "新加坡", "ap-singapore-2": "新加坡西",
  "af-johannesburg-1": "约翰内斯堡", "ap-seoul-1": "首尔", "ap-chuncheon-1": "春川", "eu-madrid-1": "马德里", "eu-madrid-3": "马德里 3",
  "eu-stockholm-1": "斯德哥尔摩", "eu-zurich-1": "苏黎世", "me-abudhabi-1": "阿布扎比", "me-dubai-1": "迪拜", "uk-london-1": "伦敦",
  "uk-cardiff-1": "纽波特", "us-ashburn-1": "阿什本", "us-chicago-1": "芝加哥", "us-phoenix-1": "凤凰城", "us-sanjose-1": "圣何塞",
  // Azure
  "eastasia": "香港", "southeastasia": "新加坡", "japaneast": "东日本", "japanwest": "西日本", "koreacentral": "韩国中部", "koreasouth": "韩国南部",
  "australiaeast": "新南威尔士", "australiasoutheast": "维多利亚", "australiacentral": "堪培拉", "centralindia": "浦那", "southindia": "金奈", "westindia": "孟买",
  "eastus": "弗吉尼亚", "eastus2": "弗吉尼亚 2", "westus": "加州", "westus2": "华盛顿州", "westus3": "亚利桑那", "centralus": "爱荷华",
  "northcentralus": "伊利诺伊", "southcentralus": "德克萨斯", "westcentralus": "怀俄明", "canadacentral": "多伦多", "canadaeast": "魁北克",
  "brazilsouth": "圣保罗", "mexicocentral": "克雷塔罗", "northeurope": "爱尔兰", "westeurope": "荷兰", "uksouth": "伦敦", "ukwest": "加的夫",
  "francecentral": "巴黎", "germanywestcentral": "法兰克福", "switzerlandnorth": "苏黎世", "norwayeast": "奥斯陆", "swedencentral": "耶夫勒",
  "polandcentral": "华沙", "italynorth": "米兰", "spaincentral": "马德里", "uaenorth": "迪拜", "qatarcentral": "多哈", "israelcentral": "以色列",
  "southafricanorth": "约翰内斯堡", "indonesiacentral": "雅加达", "malaysiawest": "吉隆坡", "newzealandnorth": "奥克兰",
};
// OCI 可用域名形如「Uocm:NRT-AD-1」，用区域 Key 反查
const OCI_KEY = { SYD: "ap-sydney-1", MEL: "ap-melbourne-1", GRU: "sa-saopaulo-1", VCP: "sa-vinhedo-1", YUL: "ca-montreal-1", YYZ: "ca-toronto-1",
  SCL: "sa-santiago-1", VAP: "sa-valparaiso-1", BOG: "sa-bogota-1", CDG: "eu-paris-1", MRS: "eu-marseille-1", FRA: "eu-frankfurt-1",
  HYD: "ap-hyderabad-1", BOM: "ap-mumbai-1", HSG: "ap-batam-1", MTZ: "il-jerusalem-1", LIN: "eu-milan-1", NRQ: "eu-turin-1", KIX: "ap-osaka-1",
  NRT: "ap-tokyo-1", JBP: "ap-kulai-2", QRO: "mx-queretaro-1", MTY: "mx-monterrey-1", LEJ: "af-casablanca-1", AMS: "eu-amsterdam-1",
  RUH: "me-riyadh-1", JED: "me-jeddah-1", BEG: "eu-jovanovac-1", SIN: "ap-singapore-1", XSP: "ap-singapore-2", JNB: "af-johannesburg-1",
  ICN: "ap-seoul-1", YNY: "ap-chuncheon-1", MAD: "eu-madrid-1", ORF: "eu-madrid-3", ARN: "eu-stockholm-1", ZRH: "eu-zurich-1",
  AUH: "me-abudhabi-1", DXB: "me-dubai-1", LHR: "uk-london-1", CWL: "uk-cardiff-1", IAD: "us-ashburn-1", ORD: "us-chicago-1",
  PHX: "us-phoenix-1", SJC: "us-sanjose-1" };
export function regionCity(code) {
  const c = String(code ?? "").trim().toLowerCase();
  if (!c) return "";
  if (REGION_CITY[c]) return REGION_CITY[c];
  let m = c.match(/^([a-z]{2}(?:-[a-z]+)+-\d+)[a-z]$/);           // AWS / Lightsail 可用区 ap-northeast-1a
  if (m && REGION_CITY[m[1]]) return REGION_CITY[m[1]];
  m = c.match(/([a-z]+-[a-z]+-\d+)-ad-\d+$/);                       // ap-tokyo-1-ad-1
  if (m && REGION_CITY[m[1]]) return REGION_CITY[m[1]];
  m = String(code).trim().match(/(?:^|:)([A-Z]{3})-AD-\d+$/i);       // Uocm:NRT-AD-1
  if (m && OCI_KEY[m[1].toUpperCase()]) return REGION_CITY[OCI_KEY[m[1].toUpperCase()]];
  return "";
}
// 「ap-northeast-1 · 东京」；未知区域只返回代码（未转义，调用方自行 esc）
export const regionLabel = (code) => { const c = regionCity(code); return c ? `${code} · ${c}` : String(code ?? ""); };
// 下拉选项：value 永远是纯代码，显示带城市名
export const regionOpt = (code, selected) => `<option value="${esc(code)}"${selected ? " selected" : ""}>${esc(regionLabel(code))}</option>`;
// 总览卡片（/accounts/{id}/overview）：有机器的区域 → 「ap-northeast-1 · 东京」或「东京 等 2 个区域」；没有机器返回 ""（调用方显示默认区域）
export const regionsBrief = (regions) => {
  const l = regions || [];
  if (!l.length) return "";
  if (l.length === 1) return regionLabel(l[0].region);
  return `${regionCity(l[0].region) || l[0].region} 等 ${l.length} 个区域`;
};
// 多区域分布：「东京 2 · 新加坡 1」（城市名未知时用代码）
export const regionsDist = (regions) => (regions || []).map((r) => `${regionCity(r.region) || r.region} ${r.count}`).join(" · ");
// 实例数文字：「3 台（运行 2）· EC2 2 · Lightsail 1」；AWS Lightsail 全部失败显示「查询失败」，部分失败加注
export const overviewCount = (o) => {
  const parts = [];
  if (o.provider === "aws") parts.push(`EC2 ${o.ec2}`, `Lightsail ${o.lightsail_failed ? (o.lightsail ? `${o.lightsail}（部分区域失败）` : "查询失败") : o.lightsail}`);
  if (o.errors && o.errors.length) parts.push(`${o.errors.length} 个区域查询失败`);
  return `${o.total} 台（运行 ${o.running}）` + (parts.length ? "· " + parts.join(" · ") : "");
};
export const regionOf = (acc) => localStorage.getItem("tc_region_" + acc.id) || acc.region || "";
// Lightsail 只在部分区域提供服务（如台北 ap-east-2 没有）：区域下拉用 /regions?service=lightsail；当前区域不支持时自动切换并提示
const LS_REGIONS = {};
export async function lsRegions(acc) {
  if (!LS_REGIONS[acc.id]) LS_REGIONS[acc.id] = api(`/accounts/${acc.id}/regions?service=lightsail`).catch((e) => { delete LS_REGIONS[acc.id]; throw e; });
  return LS_REGIONS[acc.id];
}
export async function ensureLsRegion(acc) {
  let rs;
  try { rs = await lsRegions(acc); } catch (e) { return regionOf(acc); }
  const cur = regionOf(acc);
  if (!rs.length || rs.includes(cur)) return cur;
  const to = rs.includes(acc.region) ? acc.region : rs[0];
  localStorage.setItem("tc_region_" + acc.id, to);
  toast(`Lightsail 不支持 ${regionLabel(cur)}，已切换到 ${regionLabel(to)}`);
  return to;
}
export async function regionSelect(acc, onChange, service) {
  if (NOREG(acc)) return "";
  const id = "rg" + acc.id;
  setTimeout(async () => {
    const sel = document.getElementById(id);
    if (!sel) return;
    try {
      const rs = service === "lightsail" ? await lsRegions(acc) : await api(`/accounts/${acc.id}/regions`);
      const cur = regionOf(acc);
      sel.innerHTML = rs.map((r) => regionOpt(r, r === cur)).join("");
      if (!rs.includes(cur)) sel.insertAdjacentHTML("afterbegin", regionOpt(cur, true));
      sel.value = cur;                         // 插入带 selected 的 option 不一定会被选中，显式设置
    } catch (e) { /* 保持默认 */ }
    sel.onchange = () => { localStorage.setItem("tc_region_" + acc.id, sel.value); onChange(); };
  });
  return `<select id="${id}" title="区域">${regionOpt(regionOf(acc), true)}</select>`;
}
export const rq = (acc) => (NOREG(acc) ? "" : `region=${encodeURIComponent(regionOf(acc))}`);
export const fmtTime = (t) => (t ? new Date(t * 1000).toLocaleTimeString([], { hour12: false }) : "");
export const fmtDT = (t) => (t ? new Date(t * 1000).toLocaleString([], { hour12: false }) : "-");
export const isDesktop = () => !window.matchMedia || window.matchMedia("(min-width: 901px)").matches;
export const instView = () => { let v = null; try { v = localStorage.getItem("tc_inst_view"); } catch (_) { /* 沙箱中无 localStorage */ } return v === "card" ? "card" : "table"; };
export function setCompact(on) {
  document.documentElement.classList.toggle("compact", !!on);
  localStorage.setItem("tc_compact", on ? "1" : "0");
}

// ---------------- 启动 ----------------
export async function loadAccounts() {
  setAccounts(await api("/accounts"));
  try { const m = await api("/meta"); if (m && Array.isArray(m.providers)) setMeta(m); } catch (_) { /* 旧后端没有 /meta：按默认 */ }
}

// =====================================================================
// v1.6：重装系统、块存储卷、区域订阅、附加 IP / 预留 IP / 辅助网卡、IP 质量、账号类型与停用、
//       Azure 磁盘、免费 AMD 下行 500Mbps、对象存储、Lightsail 静态 IP 与防火墙、免费额度体检
// =====================================================================
export const lastModal = () => { const l = document.querySelectorAll(".modal-bg"); return l[l.length - 1]; };
export const fmtBytes = (n) => { n = +n || 0; const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return `${n.toFixed(i ? 1 : 0)} ${u[i]}`; };
// 共享状态只能在本模块赋值（导入绑定只读），其他模块通过 setter 更新
export function setAccounts(v) { ACCOUNTS = v; }
export function setSettings(v) { SETTINGS = v; }
export function setMeta(v) { META = v; }
