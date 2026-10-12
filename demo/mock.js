// TriCloud 演示模式 v1.6.0：内存 localStorage 垫片 + 拦截 fetch("/api/...") 返回假数据。必须在 theme.js / app.js 之前执行。
(function () {
  function mem() { var d = {}; return { getItem: function (k) { return k in d ? d[k] : null; }, setItem: function (k, v) { d[k] = String(v); }, removeItem: function (k) { delete d[k]; }, clear: function () { d = {}; } }; }
  try { window.localStorage.getItem("x"); } catch (e) { Object.defineProperty(window, "localStorage", { value: mem() }); }
  try { window.sessionStorage.getItem("x"); } catch (e) { Object.defineProperty(window, "sessionStorage", { value: mem() }); }

  var now = Math.floor(Date.now() / 1000);
  function ymd(daysFromNow) { var t = new Date(Date.now() + daysFromNow * 86400000); return t.getFullYear() + "-" + ("0" + (t.getMonth() + 1)).slice(-2) + "-" + ("0" + t.getDate()).slice(-2); }
  var accounts = [
    { id: 1, provider: "oci", name: "东京主号", region: "ap-tokyo-1", created: now - 86400 * 30, cloud_created_at: ymd(-412), last_test_ok: 1, last_test_ms: 842, last_test_at: now - 3600 },
    { id: 2, provider: "oci", name: "首尔备用", region: "ap-seoul-1", created: now - 86400 * 12, cloud_created_at: ymd(-26), last_test_ok: 1, last_test_ms: 1203, last_test_at: now - 3600 },
    { id: 3, provider: "aws", name: "AWS 学习号", region: "ap-northeast-1", proxy: "proxy.example.com:3128", proxy_user: "tc-demo", proxy_pass_set: true, created: now - 86400 * 20, cloud_created_at: ymd(-190), last_test_ok: 1, last_test_ms: 311, last_test_at: now - 3600 },
    { id: 4, provider: "azure", name: "Azure 学生", region: null, created: now - 86400 * 8, cloud_created_at: ymd(-342), edu_expires_at: null, last_test_ok: 0, last_test_ms: 2210, last_test_at: now - 3600, last_test_error: "ClientAuthenticationError: AADSTS7000222 client secret expired（演示）" },
  ];
  var inst = {
    1: [
      { id: "ocid1.instance.oc1.ap-tokyo-1.demo1", name: "arm-main", state: "running", public_ip: "203.0.113.10", private_ip: "10.0.0.12", ipv6: ["2001:db8::12"], shape: "VM.Standard.A1.Flex", ocpus: 4, memory_gb: 24, zone: "AP-TOKYO-1-AD-1", created: "2025-09-02 08:14" },
      { id: "ocid1.instance.oc1.ap-tokyo-1.demo2", name: "amd-micro", state: "stopped", public_ip: null, private_ip: "10.0.0.15", ipv6: [], shape: "VM.Standard.E2.1.Micro", ocpus: 1, memory_gb: 1, zone: "AP-TOKYO-1-AD-1", created: "2025-11-20 21:03" },
    ],
    2: [{ id: "ocid1.instance.oc1.ap-seoul-1.demo3", name: "seoul-arm", state: "running", public_ip: "203.0.113.20", private_ip: "10.1.0.5", ipv6: [], shape: "VM.Standard.A1.Flex", ocpus: 2, memory_gb: 12, zone: "AP-SEOUL-1-AD-1", created: "2026-08-30 10:45" }],
    3: [
      { id: "i-0demo1234abcd", name: "tokyo-t3", state: "running", public_ip: "198.51.100.7", private_ip: "172.31.5.9", ipv6: [], shape: "t3.micro", zone: "ap-northeast-1a", created: "2026-03-12 16:20" },
      { id: "i-0demo5678efgh", name: "test-box", state: "stopped", public_ip: null, private_ip: "172.31.8.2", ipv6: [], shape: "t2.micro", zone: "ap-northeast-1c", created: "2026-09-27 09:02" },
    ],
    4: [{ id: "/subscriptions/demo/resourceGroups/rg-demo/providers/Microsoft.Compute/virtualMachines/az-b1s", name: "az-b1s", state: "running", public_ip: "192.0.2.44", private_ip: "10.2.0.4", ipv6: [], shape: "Standard_B1s", zone: "-", resource_group: "rg-demo", created: "2026-04-09 15:26" }],
  };
  var lightsail = [{ id: "ls-debian", name: "ls-debian", state: "running", public_ip: "198.51.100.30", private_ip: "172.26.1.4", ipv6: ["2001:db8:1::30"], shape: "nano_3_0", blueprint: "debian_12", static_ip: true, zone: "ap-northeast-1a" }];
  var tasks = [
    { id: 12, type: "snatch", account_id: 1, account_name: "东京主号", provider: "oci", status: "running", attempts: 1384, message: "第 1384 次：容量不足", created: now - 86400, updated: now - 40, params: { name: "arm-main-2", create: { shape: "VM.Standard.A1.Flex", ocpus: 4, memory_gb: 24 }, interval: 60 } },
    { id: 11, type: "change_ip", account_id: 3, account_name: "AWS 学习号", provider: "aws", status: "done", attempts: 1, message: "198.51.100.3 → 198.51.100.7", created: now - 3660, updated: now - 3600, params: { name: "tokyo-t3", mode: "eip" }, result: { old_ip: "198.51.100.3", new_ip: "198.51.100.7", tries: 1 } },
    { id: 10, type: "snatch", account_id: 2, account_name: "首尔备用", provider: "oci", status: "done", attempts: 52, message: "抢机成功：seoul-arm", created: now - 86400 * 2 - 3200, updated: now - 86400 * 2, result: { name: "seoul-arm", ad: "AP-SEOUL-1-AD-1" } },
    { id: 8, type: "change_ip", account_id: 1, account_name: "东京主号", provider: "oci", status: "interrupted", attempts: 1, message: "服务重启时任务中断，未自动重做；请检查实例状态后手动重新发起", created: now - 86400 * 4, updated: now - 86400 * 4 + 30 },
    { id: 9, type: "resize", account_id: 4, account_name: "Azure 学生", provider: "azure", status: "failed", attempts: 1, message: "SkuNotAvailable: 该区域暂无 Standard_B2s", created: now - 86400 * 3 - 60, updated: now - 86400 * 3 },
  ];
  var tlogs = {}, logSeq = 1;
  function tlog(tid, msg, level, ts) { (tlogs[tid] = tlogs[tid] || []).push({ id: logSeq++, ts: ts || Math.floor(Date.now() / 1000), level: level || "info", msg: msg }); if (tlogs[tid].length > 500) tlogs[tid].shift(); }
  (function seedLogs() {
    tlog(12, "任务已创建：抢机 · arm-main-2 · VM.Standard.A1.Flex 4C/24G，间隔 60s", "info", now - 86400);
    for (var i = 1374; i <= 1384; i++) tlog(12, "第 " + i + " 次：容量不足", "info", now - (1384 - i) * 60 - 40);
    [["任务已创建：换 IP · tokyo-t3", "info"], ["开始执行：换 IP · tokyo-t3（AWS · AWS 学习号）", "info"], ["分配新弹性 IP…", "info"], ["绑定到实例…", "info"], ["释放旧弹性 IP…", "info"],
     ["同步 DNS 绑定…", "info"], ["198.51.100.3 → 198.51.100.7", "ok"]].forEach(function (x, i) { tlog(11, x[0], x[1], now - 3660 + i * 8); });
    [["任务已创建：抢机 · seoul-arm", "info"], ["第 50 次：容量不足", "info"], ["第 51 次：容量不足", "info"], ["抢机成功：seoul-arm（AP-SEOUL-1-AD-1）", "ok"]].forEach(function (x, i) { tlog(10, x[0], x[1], now - 86400 * 2 - 180 + i * 60); });
    [["任务已创建：改配置", "info"], ["开始执行：改配置（AZURE · Azure 学生）", "info"], ["调整 VM 大小为 Standard_B2s（VM 会重启）…", "info"], ["SkuNotAvailable: 该区域暂无 Standard_B2s", "error"]].forEach(function (x, i) { tlog(9, x[0], x[1], now - 86400 * 3 - 60 + i * 15); });
  })();
  setInterval(function () { var t = tasks.find(function (x) { return x.id === 12; }); if (t && t.status === "running") { t.attempts++; t.message = "第 " + t.attempts + " 次：容量不足"; t.updated = Math.floor(Date.now() / 1000); tlog(12, t.message); } }, 3000);
  var monitors = [{ id: 1, account_id: 1, account_name: "东京主号", instance_id: "ocid1.instance.oc1.ap-tokyo-1.demo1", name: "arm-main", last_state: "running", auto_start: 1, check_port: 22, public_ip: "203.0.113.10", auto_change_ip: 1, fail_count: 0 }, { id: 2, account_id: 3, account_name: "AWS 学习号", instance_id: "i-0demo1234abcd", name: "tokyo-t3", last_state: "running", auto_start: 0, check_port: 443, public_ip: "198.51.100.7", auto_change_ip: 0, fail_count: 1 }];
  var credits = [{ id: 1, account_id: 3, name: "AWS 新用户 Credit", amount: 100, start_date: "2026-08-01", expire_date: ymd(300), used_manual: null }, { id: 2, account_id: 3, name: "教程奖励", amount: 20, start_date: "2026-09-10", expire_date: ymd(21), used_manual: null },
                 { id: 3, account_id: 2, name: "OCI 试用 Credit", amount: 300, start_date: ymd(-26), expire_date: ymd(4), used_manual: null },
                 { id: 4, account_id: 4, name: "Azure for Students", amount: 100, start_date: ymd(-342), expire_date: ymd(23), used_manual: 61.4 }];
  var billMonths = { 2: 37.85, 4: 0 };    // 演示：OCI / Azure 按月账单累计（估算 Credit 已用额度）
  var creditTotal = {};
  var settings = { tg_chat_id: "123456789", daily_report: true, report_time: "09:00", monitor_interval: 5, timezone: "Asia/Shanghai", default_create: null, tg_token_set: true, tg_token_hint: "7000000000:***", cf_token_set: true, totp_enabled: false, free_guard: true, auto_ip_daily_limit: 3, version: "1.6.0" };


  // ---------- v1.1 数据 ----------
  var scripts = [
    { id: 1, name: "开启 BBR", content: "#!/bin/bash\necho 'net.core.default_qdisc=fq' >> /etc/sysctl.conf\necho 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.conf\nsysctl -p" },
    { id: 2, name: "2GB Swap", content: "#!/bin/bash\nfallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile" },
  ];
  var secrets = [
    { id: 1, name: "arm-main", account_name: "东京主号", username: "root", created: now - 86400 * 9 },
    { id: 2, name: "tokyo-t3", account_name: "AWS 学习号", username: "admin", created: now - 86400 * 3 },
  ];
  var zones = [{ id: "zone-demo-1", name: "example.com" }, { id: "zone-demo-2", name: "example.net" }];
  var dnsb = [{ id: 1, record: "jp1.example.com", name: "arm-main", account_name: "东京主号", v4: 1, v6: 1, proxied: 0 }];
  var tokens = [{ id: 1, name: "tg-bot", prefix: "tc_9fK2", scope: "read", last_used: now - 1800 }, { id: 2, name: "备份脚本", prefix: "tc_Q7xm", scope: "full", last_used: null }];
  var audit = [
    [60, "panel", "POST /oci/snatch", "创建抢机任务 #12"], [1800, "token:tg-bot", "GET /instances", "ok"], [3600, "panel", "POST /instances/change-ip", "198.51.100.3 → 198.51.100.7"],
    [7200, "panel", "POST /dns-bindings", "jp1.example.com"], [10800, "panel", "POST /scripts", "开启 BBR"], [14400, "panel", "POST /settings", "monitor_interval=5"],
    [28800, "panel", "POST /login", "成功"], [36000, "203.0.113.99", "POST /login", "密码错误"], [86400, "panel", "POST /oci/security", "add tcp 443"],
    [90000, "panel", "POST /oci/ipv6", "2001:db8::12"], [172800, "panel", "POST /oci/snatch", "抢机成功 seoul-arm"], [180000, "panel", "POST /azure/create", "SkuNotAvailable"],
    [200000, "panel", "POST /tokens", "tg-bot (read)"], [260000, "panel", "POST /accounts", "Azure 学生"], [300000, "panel", "POST /backup", "已导出加密备份"],
  ].map(function (a, i) { return { id: i + 1, ts: now - a[0], ip: a[1].indexOf(".") > 0 ? a[1] : "192.0.2.15", actor: a[1].indexOf(".") > 0 ? "anonymous" : a[1], action: a[2], detail: a[3] }; });
  var seclists = [{ id: "ocid1.securitylist.demo", name: "Default Security List", rules: [
    { direction: "ingress", protocol: "tcp", cidr: "0.0.0.0/0", port: "22", idx: 0 }, { direction: "ingress", protocol: "icmp", cidr: "0.0.0.0/0", port: "-", idx: 1 },
    { direction: "ingress", protocol: "tcp", cidr: "::/0", port: "443", idx: 2 }, { direction: "egress", protocol: "all", cidr: "0.0.0.0/0", port: "全部", idx: 0 }] }];
  var rgs = [{ name: "rg-demo", location: "eastasia", state: "Succeeded" }, { name: "az-b1s-rg", location: "japaneast", state: "Succeeded" }];
  var nextTask = 13;
  var STEPS = {
    change_ip: ["开始执行：换 IP", "解绑旧公网 IP…", "创建新公网 IP…", "同步 DNS 绑定…"],
    resize: ["开始执行：改配置", "提交改配置请求…", "等待实例重启…"],
    migrate: ["开始执行：迁移", "在目标账号创建新实例…", "等待公网 IP…", "切换 DNS…"],
    ipv6: ["开始执行：IPv6", "为 VCN 开启 IPv6…", "子网分配 /64…", "添加 ::/0 路由与出站规则…", "分配 IPv6 地址…"],
    network: ["开始执行：自动建网", "创建 VCN、互联网网关、路由表与公有子网…"], create: ["开始执行：创建 VM", "创建资源组…", "创建网络安全组（默认仅放行 22）…", "创建虚拟网络…", "创建公网 IP…", "创建虚拟机…"],
  };
  function addTask(type, acc, msg, opt) {
    opt = opt || {};
    var a = accounts.find(function (x) { return x.id == acc; }) || accounts[0];
    var t = { id: nextTask++, type: type, account_id: a.id, account_name: a.name, provider: a.provider, status: "running", attempts: type === "snatch" ? 0 : 1, message: "排队中", created: Math.floor(Date.now() / 1000), updated: Math.floor(Date.now() / 1000), params: opt.params || {} };
    tasks.unshift(t); tlog(t.id, "任务已创建：" + (msg || type));
    if (type === "snatch") {
      var iv = setInterval(function () { if (t.status !== "running") return clearInterval(iv); t.attempts++; t.message = "第 " + t.attempts + " 次：容量不足"; t.updated = Math.floor(Date.now() / 1000); tlog(t.id, t.message); }, 2500);
      return t.id;
    }
    var base = STEPS[type] || ["开始执行"], steps = base.slice(0, 1).concat(opt.extra || [], base.slice(1)), i = 0;
    var iv2 = setInterval(function () {
      if (t.status !== "running") { clearInterval(iv2); return; }
      if (i < steps.length) { t.message = steps[i]; t.updated = Math.floor(Date.now() / 1000); tlog(t.id, steps[i]); i++; return; }
      clearInterval(iv2); t.status = opt.fail ? "failed" : "done"; t.message = opt.done || ((msg || "") + " · 完成"); t.result = opt.result || null; t.updated = Math.floor(Date.now() / 1000); if (!opt.fail && opt.onDone) opt.onDone();
      tlog(t.id, t.message, opt.fail ? "error" : "ok");
    }, 900);
    return t.id;
  }
  function audit1(action, detail) { audit.unshift({ id: audit.length + 1, ts: Math.floor(Date.now() / 1000), ip: "192.0.2.15", actor: "panel", action: action, detail: detail || "ok" }); }
  function rpw() { var c = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"; var s = ""; for (var i = 0; i < 16; i++) s += c[Math.floor(Math.random() * c.length)]; return s; }
  function created(name, ip, user) { var pw = rpw(); secrets.unshift({ id: Date.now(), name: name, account_name: "演示", username: user || "root", created: Math.floor(Date.now() / 1000) }); return { ok: true, name: name, state: "PROVISIONING", public_ip: ip, username: user || "root", password: pw }; }
  function accOf(p) { var m = p.match(/^\/accounts\/(\d+)/); return m ? accounts.find(function (a) { return a.id == m[1]; }) : null; }


  // ---------- v1.2 数据 ----------
  var health = {
    1: { score: 100, items: [["凭证与账号状态", 1, "API 调用正常", 0], ["实例异常停机", 1, "无", 0], ["实例消失", 1, "无", 0], ["近 24 小时任务失败", 1, "无", 0], ["A1 配额", 1, "上限 4 OCPU", 0]] },
    2: { score: 70, items: [["凭证与账号状态", 1, "API 调用正常", 0], ["实例异常停机", 1, "无", 0], ["实例消失", 1, "无", 0], ["近 24 小时任务失败", 1, "无", 0], ["A1 配额", 0, "上限 0 OCPU（上次 4，被下调）；为 0 常见于账号受限或试用转换期", 30]] },
    3: { score: 85, items: [["凭证与账号状态", 1, "API 调用正常", 0], ["实例异常停机", 0, "被动停机：test-box", 10], ["近 24 小时任务失败", 1, "无", 0], ["Credit 到期", 0, "教程奖励 还剩 21 天", 5], ["Credit 余额", 1, "剩余 $101.58（账单缓存）", 0]] },
    4: { score: 100, items: [["凭证与账号状态", 1, "API 调用正常", 0], ["实例异常停机", 1, "无", 0], ["近 24 小时任务失败", 1, "无", 0], ["订阅状态", 1, "Enabled", 0]] },
  };
  function healthOut(id) {
    var a = accounts.find(function (x) { return x.id == id; }); var h = health[id];
    if (!a) return null;
    if (!h) return { account_id: a.id, name: a.name, provider: a.provider, score: null, level: null, items: [], checked_at: null };
    return { account_id: a.id, name: a.name, provider: a.provider, score: h.score, level: h.score >= 80 ? "good" : h.score >= 50 ? "warn" : "bad",
      items: h.items.map(function (i) { return { name: i[0], ok: !!i[1], detail: i[2], penalty: i[3] }; }), checked_at: h.at || now - 3600 * 2 };
  }
  function guardDemo(acc, op, b) {
    if (!b || b.confirm_overage || settings.free_guard === false) return null;
    var w = [];
    if (acc.provider === "oci" && (op === "create")) { var c = b.create || b; if ((c.shape || "VM.Standard.A1.Flex") === "VM.Standard.A1.Flex") w.push("A1 合计将达到 " + (4 + (+c.ocpus || 1)) + " OCPU / " + (24 + (+c.memory_gb || 6)) + " GB，超出免费的 4 OCPU / 24 GB，超出部分按小时计费"); }
    if (acc.provider === "oci" && op === "bootvol" && b.vpus_per_gb && b.vpus_per_gb != 10) w.push("性能 " + b.vpus_per_gb + " VPU/GB 高于免费的 10（均衡），会按量计费");
    if (acc.provider === "aws" && op === "create") { if (["t2.micro", "t3.micro", "t3.small", "t4g.micro", "t4g.small"].indexOf(b.type || "t3.micro") < 0) w.push((b.type) + " 不在免费套餐机型内，按小时计费"); w.push("已有 1 台免费机型在运行；旧版免费套餐每月共 750 小时，多台同时运行会超出"); }
    if (acc.provider === "azure" && op === "create") { if (["Standard_B1s", "Standard_B2pts_v2", "Standard_B2ats_v2"].indexOf(b.size) < 0) w.push(b.size + " 不在免费额度内（免费：B1s / B2pts_v2 / B2ats_v2 各 750 小时/月），按小时计费"); if ((b.disk_type || "") !== "Premium_LRS") w.push("免费磁盘是 Premium SSD（P6 64GB×2），" + b.disk_type + " 不在免费范围内，会按量计费"); }
    return w.length ? { __status: 409, detail: { msg: "可能超出免费额度", guard: w } } : null;
  }


  // ---------- v1.3 数据 ----------
  var tguards = [{ id: 1, account_id: 1, account_name: "东京主力", provider: "oci", instance_id: "ocid1.instance.oc1.ap-tokyo-1.demo1", name: "arm-main", limit_gb: 10240, warn_pct: 80, action: "notify", count_in: 0, last_gb: 1834.2, last_pct: 17.9, checked_at: now - 900, mode: "monthly", direction: "out", window_hours: 24, enabled: 1, shutdown_hours: 0, state: "ok" },
                 { id: 2, account_id: 3, account_name: "AWS 学生号", provider: "aws", instance_id: "i-0demo1234abcd", name: "tokyo-t3", limit_gb: 100, warn_pct: 80, action: "stop", count_in: 0, last_gb: 83.6, last_pct: 83.6, checked_at: now - 1200, mode: "monthly", direction: "out", window_hours: 24, enabled: 1, shutdown_hours: 0, state: "ok" },
                 { id: 3, account_id: 2, account_name: "首尔备用", provider: "oci", instance_id: "ocid1.instance.oc1.ap-seoul-1.demo3", name: "seoul-arm", limit_gb: 20, warn_pct: 80, action: "stop", count_in: 1, last_gb: 21.7, last_pct: 108.5, checked_at: now - 2400, mode: "rolling", direction: "both", window_hours: 6, enabled: 1, shutdown_hours: 3, state: "tripped", resume_at: now + 3600 * 2 + 600, state_msg: "超限停机，预计自动开机" },
                 { id: 4, account_id: 4, account_name: "Azure 学生", provider: "azure", instance_id: "/subscriptions/demo/resourceGroups/rg-demo/providers/Microsoft.Compute/virtualMachines/az-b1s", name: "az-b1s", limit_gb: 15, warn_pct: 80, action: "notify", count_in: 0, last_gb: 2.1, last_pct: 14, checked_at: now - 600, mode: "rolling", direction: "in", window_hours: 24, enabled: 0, shutdown_hours: 0, state: "ok" }];
  var DIRT = { out: "出站", in: "入站", both: "双向" }, GSTT = { ok: "正常", warn: "已到预警", over: "已超限", tripped: "已触发关机", resume_failed: "自动开机失败", disabled: "已停用" };
  function fmtTs(ts) { var t = new Date(ts * 1000); return ("0" + (t.getMonth() + 1)).slice(-2) + "-" + ("0" + t.getDate()).slice(-2) + " " + ("0" + t.getHours()).slice(-2) + ":" + ("0" + t.getMinutes()).slice(-2); }
  function guardView(g) {
    var a = accounts.find(function (x) { return x.id == g.account_id; });
    var st = g.state === "tripped" ? "tripped" : g.state === "resume_failed" ? "resume_failed" : !g.enabled ? "disabled" : g.last_pct >= 100 ? "over" : g.last_pct >= g.warn_pct ? "warn" : "ok";
    return Object.assign({}, g, { account_name: a ? a.name : g.account_name, provider: a ? a.provider : g.provider, status: st, status_text: GSTT[st],
      scope: g.mode === "rolling" ? "最近 " + g.window_hours + " 小时" + DIRT[g.direction] : "本月" + DIRT[g.direction], resume_at_text: g.resume_at ? fmtTs(g.resume_at) : null });
  }
  function fakeTraffic(acc) { var o = acc.provider === "oci" ? 1834.2 : acc.provider === "aws" ? 83.6 : 12.4; var d = new Date(); return { out_gb: o, in_gb: +(o * 0.31).toFixed(1), period: d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-01 ~ 今天" }; }
  // ---------- v1.5 数据与路由：已删账号 / 默认创建参数 / 账号编辑 / 代理账密 / OCI 安全组 / 删 IPv6 / CloudFront ----------
  var deleted = [
    { id: 2, provider: "aws", name: "AWS 试用号", region: "us-east-1", lifecycle_days: 47.5, age_basis: "云上创建日期", est_cost: 0.86, currency: "USD", cost_basis: "账单缓存 2026-09", deleted_at: now - 86400 * 9, source: "panel" },
    { id: 1, provider: "oci", name: "旧号（迁移）", lifecycle_days: 33.5, age_basis: "旧版记录", est_cost: 0, currency: "USD", cost_basis: "旧版记录（删除时的本月账单）", deleted_at: now - 86400 * 40, source: "legacy" }];
  var secRules = { "sl-demo": [
    { direction: "ingress", protocol: "TCP", cidr: "0.0.0.0/0", port: "22", desc: "ssh", port_min: 22, port_max: 22 },
    { direction: "ingress", protocol: "TCP", cidr: "203.0.113.0/24", port: "443", desc: "", port_min: 443, port_max: 443 },
    { direction: "ingress", protocol: "ICMP", cidr: "0.0.0.0/0", port: "全部", desc: "", port_min: null, port_max: null },
    { direction: "egress", protocol: "全部", cidr: "0.0.0.0/0", port: "全部", desc: "", port_min: null, port_max: null }] };
  var cfs = [
    { id: "E2DEMO123ABC", domain: "d1demo.cloudfront.net", status: "Deployed", enabled: true, origins: ["origin.example.com"], aliases: [], comment: "反代示例", price_class: "All", plan: "PAYGO",
      cfg: { origin_protocol: "http-only", default_root_object: "" } },
    { id: "E9STATIC0001", domain: "d9static.cloudfront.net", status: "Deployed", enabled: false, origins: ["static.example.com"], aliases: ["cdn.example.com"], comment: "静态资源", price_class: "100", plan: "FREE",
      cfg: { origin_protocol: "https-only", default_root_object: "index.html" } }];
  var PROTO = { tcp: "TCP", udp: "UDP", icmp: "ICMP", icmpv6: "ICMPv6", all: "全部" };
  function stats15() {
    var by = {}; deleted.forEach(function (d) { by[d.provider] = (by[d.provider] || 0) + 1; });
    var days = deleted.map(function (d) { return d.lifecycle_days; }).filter(function (x) { return x != null; });
    var usd = deleted.map(function (d) { return d.est_cost; }).filter(function (x) { return x != null; });
    return { count: deleted.length, by_provider: by, avg_lifecycle_days: days.length ? +(days.reduce(function (s, x) { return s + x; }, 0) / days.length).toFixed(1) : null,
      max_lifecycle_days: days.length ? Math.max.apply(null, days) : null, total_est_cost_usd: +usd.reduce(function (s, x) { return s + x; }, 0).toFixed(2), max_est_cost_usd: usd.length ? Math.max.apply(null, usd) : 0 };
  }
  function parsePorts(s) {
    var out = [], bad = null;
    String(s || "").split(/[\s,，;；]+/).filter(Boolean).forEach(function (x) { var mm = x.match(/^(\d{1,5})(?:-(\d{1,5}))?$/); if (!mm) { bad = x; return; } var a = +mm[1], b = +(mm[2] || mm[1]); if (!(a >= 1 && a <= b && b <= 65535)) { bad = x; return; } out.push([a, b]); });
    return bad ? { error: "端口格式不正确：" + bad } : out;
  }
  // v1.5 实例操作「开放端口」：OCI 写演示安全列表；AWS 写实例全部安全组；Azure 写网卡 / 子网 NSG（已存在的跳过）
  var demoGroups = {};
  function groupsOf(acc, iid) {
    if (!demoGroups[iid]) demoGroups[iid] = acc.provider === "aws" ? [{ kind: "安全组", id: "sg-0demo1", name: "launch-wizard-1", have: ["tcp:22"] }, { kind: "安全组", id: "sg-0demo2", name: "default", have: [] }]
      : [{ kind: "NSG", id: "az-b1s-nsg", name: "az-b1s-nsg", have: ["tcp:22"] }];
    return demoGroups[iid];
  }
  function openPort15(accId, iid, b) {
    var acc = accounts.find(function (a) { return a.id == accId; });
    if (!acc) return { __status: 404, detail: "账号不存在" };
    if (acc.provider === "aws" && (b.kind || "vm") !== "vm") return { __status: 400, detail: "Lightsail 请在 AWS 控制台的“网络”页设置防火墙；此处仅支持 EC2" };
    var pr = String(b.protocol || "tcp").toLowerCase();
    if (pr !== "tcp" && pr !== "udp") return { __status: 400, detail: "协议只能是 tcp 或 udp" };
    var port = String(b.port == null ? "" : b.port).trim();
    if (!port) return { __status: 400, detail: "请填写端口，如 8443 或 80, 443, 8000-8100" };
    var rg = parsePorts(port);
    if (rg.error) return { __status: 400, detail: rg.error };
    if (!rg.length || rg.some(function (x) { return x[0] <= 1 && x[1] >= 65535; })) return { __status: 400, detail: "不支持对 0.0.0.0/0（或 ::/0）放行全部端口，请填写具体端口" };
    if (!b.confirm_public) return { __status: 409, detail: { msg: "来源为 0.0.0.0/0：将对整个互联网开放", public_warning: true } };
    var pts = rg.map(function (x) { return x[0] === x[1] ? String(x[0]) : x[0] + "-" + x[1]; }), groups = [];
    if (acc.provider === "oci") {
      var sl = seclists[0], ad = 0, sk = 0;
      pts.forEach(function (pt) { if (sl.rules.some(function (y) { return y.direction === "ingress" && y.protocol === pr && y.cidr === "0.0.0.0/0" && y.port === pt; })) { sk++; return; }
        sl.rules.push({ direction: "ingress", protocol: pr, cidr: "0.0.0.0/0", port: pt, idx: sl.rules.length + 10 }); ad++; });
      groups.push({ kind: "安全列表", id: sl.id, name: sl.name, added: ad, skipped: sk });
    } else {
      groupsOf(acc, iid).forEach(function (g) { var ad2 = 0, sk2 = 0;
        pts.forEach(function (pt) { var k = pr + ":" + pt; if (g.have.indexOf(k) >= 0) { sk2++; return; } g.have.push(k); ad2++; });
        groups.push({ kind: g.kind, id: g.id, name: g.name, added: ad2, skipped: sk2 }); });
    }
    var tot = groups.reduce(function (s, g) { return s + g.added; }, 0), skt = groups.reduce(function (s, g) { return s + g.skipped; }, 0);
    audit1("POST /instances/open-port", pr.toUpperCase() + " " + port);
    return { ok: true, added: tot, skipped: skt, groups: groups, msg: pr.toUpperCase() + " " + port + "（来源 0.0.0.0/0）\n" + groups.map(function (g) { return g.kind + " " + g.name + "：新增 " + g.added + " 条，跳过 " + g.skipped + " 条（已存在）"; }).join("\n") };
  }

  // ---------- v1.6 路由：重装 / 块存储 / 区域订阅 / 附加 IP / IP 质量 / 账号类型与停用 / Azure 磁盘 / 500M / 对象存储 / Lightsail 静态 IP / 免费体检 ----------
  var vols = { 1: [{ id: "ocid1.volume.demo1", name: "data-1", size_gb: 50, vpus_per_gb: 10, state: "AVAILABLE", attached_to: "ocid1.instance.oc1.ap-tokyo-1.demo1", attachment_id: "att-demo1", device: "/dev/oracleoci/oraclevdb" }] };
  var boots = { 1: [{ id: "bv1", name: "arm-main (Boot Volume)", size_gb: 100, vpus_per_gb: 10, state: "AVAILABLE" }, { id: "bv2", name: "amd-micro (Boot Volume)", size_gb: 47, vpus_per_gb: 10, state: "AVAILABLE" }] };
  var buckets = { 1: [{ name: "backup", created: "2026-03-02 10:11", objs: [{ name: "db/2026-10-01.sql.gz", size: 12582912, created: "2026-10-01 03:00" }, { name: "db/2026-10-08.sql.gz", size: 13107200, created: "2026-10-08 03:00" }, { name: "readme.txt", size: 312, created: "2026-03-02 10:12" }] }] };
  var regionSubs = { 1: ["ap-tokyo-1", "ap-osaka-1"], 2: ["ap-seoul-1"] };
  var ALL_REGIONS = [["ap-tokyo-1", "NRT"], ["ap-osaka-1", "KIX"], ["ap-seoul-1", "ICN"], ["ap-chuncheon-1", "YNY"], ["ap-singapore-1", "SIN"], ["us-ashburn-1", "IAD"], ["us-phoenix-1", "PHX"], ["us-sanjose-1", "SJC"], ["eu-frankfurt-1", "FRA"], ["uk-london-1", "LHR"]];
  var reserved = { 1: [{ id: "res-demo1", ip: "203.0.113.200", name: "reserved-1", state: "AVAILABLE", assigned: false }] };
  var secIps = {};
  var lsIps = [{ name: "ls-debian-ip", ip: "198.51.100.30", attached_to: "ls-debian", attached: true }];
  var lsPorts = { "ls-debian": [{ from: 22, to: 22, protocol: "tcp", state: "open", cidrs: ["0.0.0.0/0"], ipv6_cidrs: ["::/0"] }, { from: 443, to: 443, protocol: "tcp", state: "open", cidrs: ["0.0.0.0/0"], ipv6_cidrs: ["::/0"] }] };
  var foundryRes = [{ id: "/subscriptions/demo/resourceGroups/ai-demo-rg/providers/Microsoft.CognitiveServices/accounts/ai-demo", name: "ai-demo", kind: "AIServices", region: "swedencentral", resource_group: "ai-demo-rg", sku: "S0",
    endpoint: "https://ai-demo.cognitiveservices.azure.com/", state: "Succeeded", deployments: [{ name: "gpt-4o-mini", model: "gpt-4o-mini", version: "2024-07-18", sku: "GlobalStandard", capacity: 30, state: "Succeeded" }] }];
  var azDisks = { "az-b1s": [{ id: "/subscriptions/demo/resourceGroups/rg-demo/providers/Microsoft.Compute/disks/az-b1s-os", name: "az-b1s-os", role: "os", lun: null, size_gb: 64, sku: "Premium_LRS", tier: "P6", state: "Attached" }] };
  var nlb500 = {};
  var ACCT_TYPES = { 1: { label: "升级号（按量付费）", plan_type: "PAYG", account_type: "PERSONAL", upgrade_state: "UPGRADED", time_start: "2025-08-25", age_days: 412, home_region: "ap-tokyo-1" },
                     2: { label: "免费试用 / 免费号", plan_type: "FREE_TIER", account_type: "PERSONAL", time_start: "2026-08-30", age_days: 42, home_region: "ap-seoul-1" },
                     3: { label: "AWS 账号", hint: "AWS 没有公开的「试用 / 付费」类型接口；新账号的免费套餐期限请以控制台 Billing 为准" },
                     4: { label: "Azure for Students（学生）", plan_type: "AzureForStudents_2018-01-01", state: "Enabled" } };
  function instOf(accId, id) { return (inst[accId] || []).find(function (i) { return i.id === id; }); }
  function ipsOf(a, i) {
    var k = a.id + "|" + i.id;
    if (!secIps[k]) secIps[k] = { vnics: [{ vnic_id: "vnic-" + i.id.slice(-5), attachment_id: "va-" + i.id.slice(-5), name: i.name, primary: true, subnet_id: "sub-demo",
      ips: [{ id: "pip-" + i.id.slice(-5), ip: i.private_ip, primary: true, public: i.public_ip ? { id: "eph-" + i.id.slice(-5), ip: i.public_ip, lifetime: "EPHEMERAL" } : null }] }] };
    return secIps[k];
  }
  function rnd(n) { return Math.floor(Math.random() * n); }
  function route16(method, p, q, body) {
    var a = accOf(p), m, id = a && a.id;
    if (p.match(/\/azure\/foundry/) && method === "GET") {
      var freg = (p.match(/region=([^&]+)/) || [0, "swedencentral"])[1];
      var fq = freg === "swedencentral" || freg === "eastus2" ? [{ name: "Tokens Per Minute (thousands) - GPT-4o - GlobalStandard", used: foundryRes.reduce(function (s, r) { return s + r.deployments.filter(function (d) { return d.model === "gpt-4o"; }).reduce(function (a, d) { return a + d.capacity; }, 0); }, 0), limit: 450 },
        { name: "Tokens Per Minute (thousands) - GPT-4o-mini - GlobalStandard", used: 0, limit: 2000 }, { name: "Tokens Per Minute (thousands) - text-embedding-3-small - Standard", used: 0, limit: 350 }] : [];
      return { region: freg, regions: ["swedencentral", "eastus", "eastus2", "westus3", "francecentral", "japaneast", "southeastasia"], quotas: fq, resources: foundryRes,
        models: [{ name: "gpt-4o", version: "2024-11-20", skus: ["GlobalStandard", "Standard"], default: true }, { name: "gpt-4o-mini", version: "2024-07-18", skus: ["GlobalStandard", "Standard"], default: true },
          { name: "gpt-4.1", version: "2025-04-14", skus: ["GlobalStandard"], default: true }, { name: "o4-mini", version: "2025-04-16", skus: ["GlobalStandard"], default: true }, { name: "text-embedding-3-small", version: "1", skus: ["Standard"], default: true }] };
    }
    if (p.match(/\/azure\/foundry$/)) {
      if (body.op === "deploy") {
        var fr = body.resource_id ? foundryRes.find(function (r) { return r.id === body.resource_id; }) : null;
        if (!fr && !/^[a-zA-Z0-9][a-zA-Z0-9-]{1,62}$/.test(body.name || "")) return { __status: 400, detail: "资源名称 2~63 位，只能含字母、数字和 -" };
        var dn = body.deployment || String(body.model).toLowerCase().replace(/[^a-z0-9-]+/g, "-");
        return { ok: true, task_id: addTask("foundry", id, "部署 AI 模型 · " + body.model, { extra: (fr ? [] : ["创建/复用资源组 " + (body.resource_group || body.name + "-rg"), "创建 AI Services 资源 " + body.name + "（S0）"]).concat(["部署模型 " + body.model + "（" + body.sku + "，" + body.capacity + "K TPM）→ " + dn]),
          done: "已部署 " + body.model + " → " + dn, onDone: function () {
            if (!fr) { fr = { id: "/subscriptions/demo/resourceGroups/" + (body.resource_group || body.name + "-rg") + "/providers/Microsoft.CognitiveServices/accounts/" + body.name, name: body.name, kind: "AIServices", region: body.region, resource_group: body.resource_group || body.name + "-rg", sku: "S0", endpoint: "https://" + body.name.toLowerCase() + ".cognitiveservices.azure.com/", state: "Succeeded", deployments: [] }; foundryRes.push(fr); }
            fr.deployments.push({ name: dn, model: body.model, version: body.version || "", sku: body.sku, capacity: body.capacity, state: "Succeeded" }); } }) };
      }
      var frr = foundryRes.find(function (r) { return r.id === body.resource_id; });
      if (!frr) return { __status: 400, detail: "资源 ID 无效" };
      if (body.op === "keys") return { endpoint: frr.endpoint, openai_base_url: "https://" + frr.name.toLowerCase() + ".openai.azure.com/openai/v1/", key1: "demo0000000000000000000000000000", key2: "demo1111111111111111111111111111" };
      if (body.op === "delete_deployment") { frr.deployments = frr.deployments.filter(function (d) { return d.name !== body.deployment; }); return { ok: true }; }
      if (body.op === "delete_resource") { foundryRes.splice(foundryRes.indexOf(frr), 1); return { ok: true, hint: "资源进入软删除状态 48 小时，期间同名资源无法重建" }; }
      return { __status: 400, detail: "未知操作" };
    }
    if (p.match(/\/instances\/reinstall$/)) {
      if (!body.confirm) return { __status: 400, detail: "重装会清空系统盘全部数据，需确认" };
      if (a.provider === "aws" && body.kind === "lightsail") return { __status: 400, detail: "Lightsail 不支持重装系统，可删除后重建" };
      var ri = instOf(id, body.instance_id);
      if (ri) { ri.state = "stopping"; setTimeout(function () { ri.state = "running"; }, 6000); }
      return { ok: true, task_id: addTask("reinstall", id, "重装系统 · " + (body.name || ""), { extra: ["停止实例…", "替换系统盘（" + (body.os || "默认系统") + " " + (body.os_version || "最新") + "）…", "等待实例重新运行…"],
        done: "重装完成" + (body.password_login === false ? "" : "，新密码已存入「开机密码」"), onDone: function () { if (body.password_login !== false) created(body.name || "reinstalled", null, "root"); } }) };
    }
    if (p.match(/\/oci\/volumes$/) && method === "GET") { var vl = vols[id] || []; var bl = boots[id] || []; var used = vl.concat(bl).reduce(function (s, v) { return s + v.size_gb; }, 0); return { volumes: vl, boot_volumes: bl, used_gb: used, free_gb: 200 }; }
    if (p.match(/\/oci\/volumes$/)) {
      var V = vols[id] = vols[id] || [], v = V.find(function (x) { return x.id === body.volume_id || x.attachment_id === body.attachment_id; });
      if (body.op === "create") {
        var sz = +body.size_gb || 50; if (sz < 50) return { __status: 400, detail: "块存储卷容量范围 50 ~ 32768 GB" };
        var nv = { id: "ocid1.volume.demo" + Date.now(), name: body.name || "tricloud-vol", size_gb: sz, vpus_per_gb: +body.vpus_per_gb || 10, state: "AVAILABLE", attached_to: body.instance_id || null, attachment_id: body.instance_id ? "att-" + Date.now() : null, device: body.instance_id ? "/dev/oracleoci/oraclevdc" : null };
        V.push(nv); audit1("POST /oci/volumes", "create " + nv.name);
        return { ok: true, id: nv.id, name: nv.name, attach: body.instance_id ? { ok: true, hint: "半虚拟化挂载，系统内用 lsblk 查看新盘（通常是 /dev/sdb），首次使用需自行分区和格式化" } : undefined };
      }
      if (!v) return { __status: 400, detail: "卷不存在" };
      if (body.op === "attach") { v.attached_to = body.instance_id; v.attachment_id = "att-" + Date.now(); v.device = "/dev/oracleoci/oraclevdc"; return { ok: true, hint: "半虚拟化挂载，系统内用 lsblk 查看新盘，首次使用需自行分区和格式化" }; }
      if (body.op === "detach") { v.attached_to = null; v.attachment_id = null; v.device = null; return { ok: true, hint: "建议先在系统内 umount 并移除 /etc/fstab 中的条目" }; }
      if (body.op === "update") { if (body.size_gb && +body.size_gb < v.size_gb) return { __status: 400, detail: "块存储卷只能扩容不能缩小" }; var ex = body.size_gb && +body.size_gb > v.size_gb; if (body.size_gb) v.size_gb = +body.size_gb; if (body.vpus_per_gb !== undefined) v.vpus_per_gb = +body.vpus_per_gb;
        return { ok: true, expanded: !!ex, grow: ex && body.grow ? { status: "ok", message: "sdb 8:16 0 " + v.size_gb + "G 0 disk" } : undefined }; }
      if (body.op === "delete") { if (!body.confirm) return { __status: 400, detail: "删除块存储卷不可恢复，需确认" }; if (v.attached_to) return { __status: 400, detail: "卷仍挂载在实例上，请先卸载" }; vols[id] = V.filter(function (x) { return x !== v; }); return { ok: true }; }
    }
    if (p.match(/\/oci\/region-subscriptions$/) && method === "GET") {
      var subs = regionSubs[id] || [a.region];
      return { home: subs[0], limit_hint: "免费账号通常只能订阅 1 个额外区域；Always Free 资源只在主区域", regions: ALL_REGIONS.map(function (r) { var i = subs.indexOf(r[0]); return { name: r[0], key: r[1], subscribed: i >= 0, status: i >= 0 ? "READY" : null, home: i === 0 }; }) };
    }
    if (p.match(/\/oci\/region-subscriptions$/)) {
      if (!body.confirm) return { __status: 400, detail: "订阅区域不可撤销，需确认" };
      var rr = ALL_REGIONS.find(function (r) { return r[1] === body.region_key; }); if (!rr) return { __status: 400, detail: "区域 key 不合法（如 NRT、ICN）" };
      (regionSubs[id] = regionSubs[id] || [a.region]).push(rr[0]); audit1("POST /oci/region-subscriptions", rr[0]); return { ok: true, region: rr[0], status: "IN_PROGRESS" };
    }
    if (p.match(/\/oci\/ips$/) && method === "GET") { var gi = instOf(id, q.get("instance_id")); return Object.assign({}, ipsOf(a, gi), { reserved: reserved[id] || [] }); }
    if (p.match(/\/oci\/ips$/)) {
      var ii = instOf(id, body.instance_id), d = ii && ipsOf(a, ii), R = reserved[id] = reserved[id] || [];
      if (body.op === "add_secondary") { var pv = "10.0.0." + (30 + rnd(200)), pub = "203.0.113." + (100 + rnd(150)); d.vnics.find(function (x) { return x.vnic_id === body.vnic_id; }).ips.push({ id: "pip-" + Date.now(), ip: pv, primary: false, public: { id: "eph-" + Date.now(), ip: pub, lifetime: "EPHEMERAL" } });
        return { ok: true, private_ip: pv, public_ip: pub, hint: "系统内需手动添加地址：ip addr add " + pv + "/24 dev ens3（或写入 netplan 持久化）；Oracle Linux 可用 oci-network-config" }; }
      if (body.op === "delete_private") { d.vnics.forEach(function (x) { x.ips = x.ips.filter(function (y) { return y.id !== body.private_ip_id; }); }); return { ok: true }; }
      if (body.op === "attach_vnic") { d.vnics.push({ vnic_id: "vnic-" + Date.now(), attachment_id: "va-" + Date.now(), name: "tricloud-vnic", primary: false, ips: [{ id: "pip-" + Date.now(), ip: "10.0.0." + (30 + rnd(200)), primary: true, public: { id: "e", ip: "203.0.113." + (100 + rnd(150)), lifetime: "EPHEMERAL" } }] });
        return { ok: true, hint: "辅助网卡需在系统内配置（Oracle Linux：oci-network-config；Ubuntu：按官方 secondary VNIC 脚本配置路由）。免费规格网卡数量有限：E2.1.Micro 1 块、A1 每 OCPU 1 块" }; }
      if (body.op === "detach_vnic") { d.vnics = d.vnics.filter(function (x) { return x.attachment_id !== body.attachment_id; }); return { ok: true }; }
      if (body.op === "create_reserved") { if (R.length >= 1 && !body.confirm_overage) return { __status: 409, detail: { msg: "可能超出免费额度", guard: ["已有 " + R.length + " 个预留公网 IP；Always Free 一般只含 1 个，超出或闲置（未绑定）可能计费"] } };
        var nr = { id: "res-" + Date.now(), ip: "203.0.113." + (150 + rnd(100)), name: "tricloud-reserved", state: "AVAILABLE", assigned: false }; R.push(nr); return { ok: true, id: nr.id, ip: nr.ip }; }
      var res = R.find(function (x) { return x.id === body.public_ip_id; });
      if (body.op === "assign_reserved") { res.assigned = true; ii.public_ip = res.ip; d.vnics[0].ips[0].public = { id: res.id, ip: res.ip, lifetime: "RESERVED" }; return { ok: true }; }
      if (body.op === "unassign_reserved") { res.assigned = false; Object.keys(inst).forEach(function (k) { inst[k].forEach(function (x) { if (x.public_ip === res.ip) { x.public_ip = "203.0.113." + (100 + rnd(150)); var dd = secIps[k + "|" + x.id]; if (dd) dd.vnics[0].ips[0].public = { id: "eph", ip: x.public_ip, lifetime: "EPHEMERAL" }; } }); }); return { ok: true }; }
      if (body.op === "delete_reserved") { if (res.assigned) return { __status: 400, detail: "预留 IP 仍绑定在实例上，请先解绑" }; reserved[id] = R.filter(function (x) { return x !== res; }); return { ok: true }; }
    }
    if (p === "/ip-quality") { var ip = q.get("ip") || ""; if (!/^\d+\.\d+\.\d+\.\d+$/.test(ip)) return { __status: 400, detail: "IP 格式错误" };
      var h = ip.split(".").reduce(function (s, x) { return s + +x; }, 0); return { ip: ip, risk: h % 70, type: h % 3 ? "Business" : "Hosting", proxy: h % 70 > 60, country: "Japan", country_code: "JP", isp: "Oracle Corporation", asn: "AS31898", hosting: true, source: "proxycheck.io（风险分）+ ip-api.com（归属地 / ISP）" }; }
    if ((m = p.match(/^\/accounts\/(\d+)\/account-type$/))) { var at = Object.assign({}, ACCT_TYPES[m[1]] || { label: "未知" }, { checked_at: Math.floor(Date.now() / 1000) }); var aa = accounts.find(function (x) { return x.id == m[1]; }); if (aa) aa.acct_type = JSON.stringify(at); return at; }
    if ((m = p.match(/^\/accounts\/(\d+)\/disable$/))) { var da = accounts.find(function (x) { return x.id == m[1]; }); var on = body.disabled !== false; da.disabled = on ? 1 : 0; da.disabled_reason = on ? (body.reason || null) : null;
      var st = []; if (on) tasks.forEach(function (t) { if (t.account_id == m[1] && t.status === "running") { t.status = "stopped"; t.message = "已手动停止"; st.push(t.id); } }); audit1("POST /accounts/disable", da.name + (on ? " 停用" : " 启用")); return { ok: true, disabled: on, stopped_tasks: st }; }
    if (p.match(/\/azure\/disks$/) && method === "GET") { var vmn = (q.get("instance_id") || "").split("/").pop(); return { disks: azDisks[vmn] || [], skus: ["Standard_LRS", "StandardSSD_LRS", "Premium_LRS", "StandardSSD_ZRS", "Premium_ZRS"], tiers: ["P1", "P2", "P3", "P4", "P6", "P10", "P15", "P20", "P30", "P40", "P50"], hint: "扩大系统盘或改类型一般需要先停止（释放）VM；Azure for Students 免费额度含 2 块 64GB P6 SSD" }; }
    if (p.match(/\/azure\/disks$/)) { var dk = (azDisks[body.instance_id.split("/").pop()] || []).find(function (x) { return x.id === body.disk_id; });
      if (body.size_gb && +body.size_gb < dk.size_gb) return { __status: 400, detail: "Azure 磁盘只能扩大不能缩小" }; if (body.tier && (body.sku || dk.sku).indexOf("Premium") !== 0) return { __status: 400, detail: "性能层只对 Premium SSD 有效" };
      if (!body.size_gb && !body.sku && !body.tier) return { __status: 400, detail: "没有要修改的项" };
      if (body.size_gb) dk.size_gb = +body.size_gb; if (body.sku) dk.sku = body.sku; if (body.tier) dk.tier = body.tier; return { ok: true, hint: body.size_gb ? "扩容后需在系统内扩展分区（Ubuntu 通常开机自动扩展；否则 growpart + resize2fs）" : "" }; }
    if (p.match(/\/oci\/500m$/) && method === "GET") { var k5 = q.get("instance_id"); return nlb500[k5] ? { enabled: true, public_ip: nlb500[k5], state: "ACTIVE" } : { enabled: false }; }
    if (p.match(/\/oci\/500m$/)) { var i5 = instOf(id, body.instance_id);
      if (body.enable !== false) { if (i5.shape !== "VM.Standard.E2.1.Micro") return { __status: 400, detail: "仅支持免费 AMD 规格 VM.Standard.E2.1.Micro" }; if (!body.confirm) return { __status: 400, detail: "开启后入口 IP 会变成负载均衡器的公网 IP，需确认" };
        var nip = "203.0.113." + (60 + rnd(30)); return { ok: true, task_id: addTask("net500m", id, "下行 500Mbps · " + i5.name, { extra: ["准备 NAT 网关…", "创建网络负载均衡器（保留源地址，TCP+UDP 全端口转发）…", "创建 NAT 路由表并绑定到实例网卡…"], done: "已开启，新入口 IP " + nip, onDone: function () { nlb500[i5.id] = nip; } }) }; }
      return { ok: true, task_id: addTask("net500m", id, "关闭 500Mbps · " + i5.name, { extra: ["还原实例网卡路由…", "删除网络负载均衡器…"], done: "已关闭并还原原公网 IP 入站", onDone: function () { delete nlb500[i5.id]; } }) }; }
    if (p.match(/\/oci\/buckets$/) && method === "GET") return { namespace: "demonamespace", buckets: (buckets[id] || []).map(function (b) { return { name: b.name, created: b.created }; }), free_gb: 20 };
    if (p.match(/\/oci\/buckets$/)) { var B = buckets[id] = buckets[id] || [];
      if (body.op === "create") { if (!/^[A-Za-z0-9_.-]{1,256}$/.test(body.name || "")) return { __status: 400, detail: "Bucket 名称只能包含字母、数字、- _ ." }; B.push({ name: body.name, created: new Date().toISOString().slice(0, 16).replace("T", " "), objs: [] }); return { ok: true }; }
      if (body.op === "delete") { var bb = B.find(function (x) { return x.name === body.name; }); if (bb && bb.objs.length) return { __status: 400, detail: "Bucket 不为空，请先删除其中的对象" }; buckets[id] = B.filter(function (x) { return x !== bb; }); return { ok: true }; } }
    if (p.match(/\/oci\/objects$/)) {
      var bk = (buckets[id] || []).find(function (x) { return x.name === (q.get("bucket") || (body && body.bucket)); });
      if (!bk) return { __status: 400, detail: "Bucket 不存在" };
      if (method === "GET") { var pre = q.get("prefix") || "", objs = [], pres = [];
        bk.objs.forEach(function (o) { if (o.name.indexOf(pre) !== 0) return; var rest = o.name.slice(pre.length), j = rest.indexOf("/"); if (j >= 0) { if (pres.indexOf(pre + rest.slice(0, j + 1)) < 0) pres.push(pre + rest.slice(0, j + 1)); } else objs.push(o); });
        return { objects: objs, prefixes: pres, next: null }; }
      if (method === "PUT") { var nm = q.get("name"); bk.objs = bk.objs.filter(function (o) { return o.name !== nm; }); bk.objs.push({ name: nm, size: (body && body.__file) || 0, created: new Date().toISOString().slice(0, 16).replace("T", " ") }); return { ok: true, size: (body && body.__file) || 0 }; }
      if (body.op === "url") return { url: "https://objectstorage.ap-tokyo-1.oraclecloud.com/p/DEMO-PAR-TOKEN/n/demonamespace/b/" + bk.name + "/o/" + encodeURIComponent(body.name), expires: new Date(Date.now() + 3600e3).toISOString().slice(0, 16).replace("T", " ") + " UTC" };
      if (body.op === "delete") { bk.objs = bk.objs.filter(function (o) { return o.name !== body.name; }); return { ok: true }; }
    }
    if (p.match(/\/lightsail\/static-ips$/) && method === "GET") return lsIps;
    if (p.match(/\/lightsail\/static-ips$/)) { var s = lsIps.find(function (x) { return x.name === body.name; });
      if (body.op === "allocate") { if (!body.name) return { __status: 400, detail: "缺少参数：name" }; var ns = { name: body.name, ip: "198.51.100." + (40 + rnd(150)), attached_to: body.instance || null, attached: !!body.instance }; lsIps.push(ns); return { ok: true, ip: ns.ip }; }
      if (body.op === "attach") { s.attached = true; s.attached_to = body.instance; return { ok: true }; }
      if (body.op === "detach") { s.attached = false; s.attached_to = null; return { ok: true, hint: "已解绑：未绑定的静态 IP 会按小时计费，不用请释放" }; }
      if (body.op === "release") { if (s.attached) return { __status: 400, detail: "静态 IP 仍绑定在实例上，请先解绑" }; lsIps = lsIps.filter(function (x) { return x !== s; }); return { ok: true }; } }
    if (p.match(/\/lightsail\/ports$/) && method === "GET") return lsPorts[q.get("instance")] || [];
    if (p.match(/\/lightsail\/ports$/)) { var LP = lsPorts[body.instance] = lsPorts[body.instance] || [];
      if (body.op === "close") { lsPorts[body.instance] = LP.filter(function (x) { return !(x.from === body.from_port && x.to === body.to_port && x.protocol === body.protocol); }); return { ok: true }; }
      var cs = String(body.cidrs || "0.0.0.0/0").split(/[,，]/).map(function (x) { return x.trim(); }).filter(Boolean);
      if (cs.indexOf("0.0.0.0/0") >= 0 && body.from_port <= 1 && body.to_port >= 65535) return { __status: 400, detail: "不支持对 0.0.0.0/0（或 ::/0）放行全部端口，请填写具体端口" };
      if (cs.indexOf("0.0.0.0/0") >= 0 && !body.confirm_public) return { __status: 409, detail: { msg: "来源为 0.0.0.0/0：将对整个互联网开放", public_warning: true } };
      LP.push({ from: body.from_port, to: body.to_port, protocol: body.protocol, state: "open", cidrs: cs, ipv6_cidrs: cs.indexOf("0.0.0.0/0") >= 0 ? ["::/0"] : [] }); return { ok: true }; }
    if (p === "/oci/free-check") return accounts.filter(function (x) { return x.provider === "oci" && !x.disabled; }).map(function (x) {
      var L = (inst[x.id] || []), a1 = L.filter(function (i) { return i.shape === "VM.Standard.A1.Flex"; }), mic = L.filter(function (i) { return i.shape === "VM.Standard.E2.1.Micro"; });
      var c = a1.reduce(function (s, i) { return s + (+i.ocpus || 0); }, 0), mm = a1.reduce(function (s, i) { return s + (+i.memory_gb || 0); }, 0);
      var stg = (vols[x.id] || []).concat(boots[x.id] || [{ size_gb: 47 }]).reduce(function (s, v) { return s + v.size_gb; }, 0), iss = [], sug = [];
      if (c > 4) iss.push("A1 OCPU 合计 " + c + "，超出免费 4"); if (mm > 24) iss.push("A1 内存合计 " + mm + " GB，超出免费 24 GB"); if (mic.length > 2) iss.push("E2.1.Micro " + mic.length + " 台，超出免费 2 台"); if (stg > 200) iss.push("块存储合计 " + stg + " GB，超出免费 200 GB");
      var lc = 4, lm = 24; a1.slice().sort(function (p1, p2) { return (p1.created || "") < (p2.created || "") ? -1 : 1; }).forEach(function (i) { var nc = Math.min(i.ocpus, Math.max(lc, 0)), nm2 = Math.min(i.memory_gb, Math.max(lm, 0)); if (nc !== i.ocpus || nm2 !== i.memory_gb) sug.push({ id: i.id, name: i.name, ocpus: i.ocpus, memory_gb: i.memory_gb, to_ocpus: nc, to_memory_gb: nm2, delete: nc < 1 || nm2 < 1 }); lc -= nc; lm -= nm2; });
      return { account_id: x.id, name: x.name, ok: !iss.length, issues: iss, suggestions: sug, a1: { ocpus: c, memory_gb: mm, count: a1.length, limit_ocpus: 4, limit_mem: 24 }, micro: { count: mic.length, limit: 2 }, storage: { used_gb: stg, limit: 200 }, paid: [] }; });
    if (p.match(/\/oci\/boot-volume$/) && method === "POST" && body.size_gb && body.grow) { var r0 = { ok: true, hint: "扩容后需在系统内扩展分区", grow: { status: "ok", message: "/dev/sda1 " + body.size_gb + "G" } }; return r0; }
    return undefined;
  }
  function route15(method, p, q, body) {
    var m;
    if (p === "/recycle-bin" && method === "GET") return { items: deleted, stats: stats15() };
    if (p === "/recycle-bin/stats") return stats15();
    if (p === "/recycle-bin" && method === "DELETE") { if (q.get("confirm") !== "true") return { __status: 400, detail: "需确认" }; deleted = []; return { ok: true }; }
    if ((m = p.match(/^\/recycle-bin\/(\d+)$/))) { deleted = deleted.filter(function (d) { return d.id != m[1]; }); return { ok: true }; }
    if ((m = p.match(/^\/create-defaults\/(\w+)$/))) return (settings.default_create || {})[m[1]] || {};
    if (p === "/create-defaults" && method === "PUT") { settings.default_create = Object.assign({}, settings.default_create || {}); var dv = {}; Object.keys(body.defaults || {}).forEach(function (k) { if (["password", "region"].indexOf(k) < 0) dv[k] = body.defaults[k]; }); settings.default_create[body.provider] = dv; return { ok: true, defaults: dv }; }
    if ((m = p.match(/^\/accounts\/(\d+)$/)) && method === "DELETE") {
      var da = accounts.find(function (a) { return a.id == m[1]; });
      if (da) deleted.unshift({ id: Date.now() % 100000, provider: da.provider, name: da.name, region: da.region, lifecycle_days: da.cloud_created_at ? daysTo(ymd(0)) - daysTo(da.cloud_created_at) : 3, age_basis: da.cloud_created_at ? "云上创建日期" : "面板添加时间", est_cost: da.provider === "aws" ? 1.27 : 0, currency: "USD", cost_basis: da.provider === "aws" ? "账单缓存" : "本月账单记录", deleted_at: Math.floor(Date.now() / 1000), source: "panel" });
      return undefined;
    }
    if ((m = p.match(/^\/accounts\/(\d+)\/detail$/))) {
      var a = accounts.find(function (x) { return x.id == m[1]; });
      var F = { oci: { user: { set: true, hint: "…demo01" }, tenancy: { set: true, hint: "…demo02" }, fingerprint: { set: true, hint: "…:ab:cd" }, key_content: { set: true }, pass_phrase: { set: false }, region: a.region || "", compartment: "", home_region: "" },
        aws: { access_key: { set: true, hint: "…DEMO12" }, secret_key: { set: true }, region: a.region || "" },
        azure: { tenant_id: { set: true, hint: "…000000" }, client_id: { set: true, hint: "…111111" }, client_secret: { set: true }, subscription_id: { set: true, hint: "…222222" }, region: "" } }[a.provider];
      return { id: a.id, name: a.name, provider: a.provider, region: a.region, proxy: a.proxy || "", proxy_user: a.proxy_user || "", proxy_pass_set: !!a.proxy_pass_set, fields: F };
    }
    if ((m = p.match(/^\/accounts\/(\d+)$/)) && method === "PATCH" && body) {
      var ea = accounts.find(function (x) { return x.id == m[1]; });
      if ("proxy" in body && !body.proxy) { ea.proxy = ""; ea.proxy_user = ""; ea.proxy_pass_set = false; }
      else if (body.proxy) { if (!/^(https?|socks5h?):\/\//.test(body.proxy)) return { __status: 400, detail: "代理需以 http:// https:// socks5:// 开头" }; ea.proxy = String(body.proxy).split("@").pop(); }
      if (("proxy_user" in body || body.proxy_pass) && !ea.proxy) return { __status: 400, detail: "请先填写代理地址（proxy），再填用户名 / 密码" };
      if ("proxy_user" in body) ea.proxy_user = body.proxy_user || "";
      if (body.proxy_pass) ea.proxy_pass_set = true;
      if (body.proxy_pass_clear) ea.proxy_pass_set = false;
      if (body.cred && body.cred.region) ea.region = body.cred.region;
      if (body.name) ea.name = body.name;
      if (Object.keys(body).every(function (k) { return /^(proxy|proxy_user|proxy_pass|proxy_pass_clear|cred|name)$/.test(k); })) { audit1("PATCH /accounts/" + m[1], "编辑账号"); return { ok: true }; }
      return undefined;
    }
    if ((m = p.match(/^\/accounts\/(\d+)\/instances\/(.+)\/open-port$/)) && method === "POST") return openPort15(+m[1], decodeURIComponent(m[2]), body || {});
    if ((m = p.match(/^\/accounts\/(\d+)\/security-rules$/)) && method === "POST" && body && body.sl_id === seclists[0].id) {
      // 实例「安全列表」弹窗里的「添加规则」：写入演示安全列表（与 /oci/security 同一份数据）
      var r0 = body.rule || body, pr0 = String(r0.protocol || "").toLowerCase(), c1 = String(r0.cidr || "").replace(/\s/g, ""), d0 = r0.direction || "ingress";
      if (!c1) return { __status: 400, detail: "请填写来源 / 目标 CIDR" };
      var g0 = (pr0 === "tcp" || pr0 === "udp") && r0.ports ? parsePorts(r0.ports) : [];
      if (g0.error) return { __status: 400, detail: g0.error };
      if (d0 === "ingress" && (c1 === "0.0.0.0/0" || c1 === "::/0")) {
        if (pr0 === "all" || ((pr0 === "tcp" || pr0 === "udp") && (!g0.length || g0.some(function (x) { return x[0] <= 1 && x[1] >= 65535; })))) return { __status: 400, detail: "不支持对 0.0.0.0/0（或 ::/0）放行全部端口，请填写具体端口" };
        if (!body.confirm_public) return { __status: 409, detail: { msg: "来源为 0.0.0.0/0：将对整个互联网开放", public_warning: true } };
      }
      var a0 = 0, k0 = 0;
      (g0.length ? g0 : [null]).forEach(function (x) { var pt = x ? (x[0] === x[1] ? String(x[0]) : x[0] + "-" + x[1]) : "全部";
        if (seclists[0].rules.some(function (y) { return y.direction === d0 && y.protocol === pr0 && y.cidr === c1 && y.port === pt; })) { k0++; return; }
        seclists[0].rules.push({ direction: d0, protocol: pr0, cidr: c1, port: pt, idx: seclists[0].rules.length + 10 }); a0++; });
      audit1("POST /security-rules", "添加 " + a0 + " 条"); return { ok: true, sl_id: seclists[0].id, added: a0, skipped: k0 };
    }
    if ((m = p.match(/^\/accounts\/(\d+)\/security-rules$/))) {
      var rules = secRules["sl-demo"];
      if (method === "GET") return { lists: [{ id: "sl-demo", name: "Default Security List for vcn-demo" }], rules: rules.map(function (r, i) { return Object.assign({ idx: i, sl_id: "sl-demo", sl_name: "Default Security List for vcn-demo", stateless: false }, r); }) };
      var r = body.rule || body, pr = (r.protocol || "").toLowerCase(), cidr = (r.cidr || r.source || "").trim(), dir = r.direction || "ingress";
      if (method === "DELETE") {
        var ix = rules.findIndex(function (x) { return x.direction === dir && PROTO[pr] === x.protocol && x.cidr === cidr && (x.port_min == (r.port_min == null ? null : +r.port_min)); });
        if (ix < 0) return { __status: 404, detail: "未找到匹配的规则（可能已被删除，请刷新）" };
        rules.splice(ix, 1); audit1("DELETE /security-rules", PROTO[pr] + " " + cidr); return { ok: true, deleted: 1 };
      }
      if (!cidr) return { __status: 400, detail: "请填写来源 / 目标 CIDR" };
      var rg = (pr === "tcp" || pr === "udp") && r.ports ? parsePorts(r.ports) : [];
      if (rg.error) return { __status: 400, detail: rg.error };
      var pub = cidr === "0.0.0.0/0" || cidr === "::/0";
      if (pub && dir === "ingress") {
        if (pr === "all" || ((pr === "tcp" || pr === "udp") && (!rg.length || rg.some(function (x) { return x[0] <= 1 && x[1] >= 65535; })))) return { __status: 400, detail: "不支持对 0.0.0.0/0（或 ::/0）放行全部端口，请填写具体端口" };
        if (!body.confirm_public) return { __status: 409, detail: { msg: "来源为 0.0.0.0/0：将对整个互联网开放", public_warning: true } };
      }
      var added = 0, skipped = 0;
      (rg.length ? rg : [null]).forEach(function (x) {
        var exists = rules.some(function (y) { return y.direction === dir && y.protocol === PROTO[pr] && y.cidr === cidr && y.port_min == (x ? x[0] : null) && y.port_max == (x ? x[1] : null); });
        if (exists) { skipped++; return; }
        rules.push({ direction: dir, protocol: PROTO[pr], cidr: cidr, port: x ? (x[0] === x[1] ? String(x[0]) : x[0] + "-" + x[1]) : "全部", desc: r.description || "", port_min: x ? x[0] : null, port_max: x ? x[1] : null }); added++;
      });
      audit1("POST /security-rules", "添加 " + added + " 条"); return { ok: true, sl_id: "sl-demo", added: added, skipped: skipped };
    }
    if (p.match(/\/oci\/ipv6\/delete$/)) { if (!body.confirm) return { __status: 400, detail: "删除 IPv6 需确认" }; var oi = (inst[(accOf(p) || {}).id] || []).find(function (i) { return i.id === body.instance_id; }); if (!oi || !oi.ipv6.length) return { __status: 404, detail: "该实例没有 IPv6 地址" }; var dl = oi.ipv6; oi.ipv6 = []; return { ok: true, deleted: dl }; }
    // CloudFront
    if (p.match(/\/cloudfront$/) && method === "GET") return cfs.map(function (d) { var o = Object.assign({}, d); delete o.cfg; return o; });
    if (p.match(/\/cloudfront$/) && body && body.op === "create") {
      var og = String(body.origin || "").replace(/^https?:\/\//, "").replace(/\/+$/, "");
      if (!og || og.indexOf("/") >= 0) return { __status: 400, detail: "请填写源站域名（如 origin.example.com，不带路径）" };
      var nid = "E" + Math.random().toString(36).slice(2, 12).toUpperCase(), dom = "d" + Math.random().toString(36).slice(2, 12) + ".cloudfront.net";
      cfs.push({ id: nid, domain: dom, status: "InProgress", enabled: true, origins: [og], aliases: [], comment: body.comment || "TriCloud", price_class: body.price_class === "all" || !body.price_class ? "All" : body.price_class, plan: "PAYGO", cfg: { origin_protocol: body.origin_protocol || "http-only", default_root_object: "" } });
      return { id: nid, domain: dom };
    }
    if (p.match(/\/cloudfront\/invalidate$/)) { var ps = String(body.paths || "").split(/[\n,]/).map(function (x) { return x.trim(); }).filter(Boolean).map(function (x) { return x[0] === "/" ? x : "/" + x; }); if (!ps.length) ps = ["/*"]; return { ok: true, invalidation_id: "I" + Date.now().toString(36).toUpperCase(), status: "InProgress", paths: ps }; }
    if (p.match(/\/cloudfront\/toggle$/)) { var td = cfs.find(function (d) { return d.id === body.distribution_id; }); td.enabled = !!body.enabled; td.status = "InProgress"; setTimeout(function () { td.status = "Deployed"; }, 8000); return { ok: true, message: "分发已" + (body.enabled ? "启用" : "停用") + "，部署约需几分钟" }; }
    if (p.match(/\/cloudfront\/plan$/)) { var tier = String(body.plan_tier || "").toUpperCase(); if (["PRO", "BUSINESS", "PREMIUM"].indexOf(tier) >= 0 && !body.confirm) return { __status: 400, detail: tier + " 套餐按月计费，需确认" }; cfs.find(function (d) { return d.id === body.distribution_id; }).plan = tier; return { ok: true, plan: tier, message: tier === "PAYGO" ? "已切回按量付费" : "已订阅 " + tier + " 套餐（演示）" }; }
    if ((m = p.match(/\/cloudfront\/([A-Z0-9]+)\/config$/))) { var cd = cfs.find(function (d) { return d.id === m[1]; }); return { id: cd.id, comment: cd.comment, origin_domain: cd.origins[0], origin_protocol: cd.cfg.origin_protocol, price_class: cd.price_class, default_root_object: cd.cfg.default_root_object, enabled: cd.enabled, aliases: cd.aliases }; }
    if ((m = p.match(/\/cloudfront\/([A-Z0-9]+)$/)) && method === "PUT") {
      var ud = cfs.find(function (d) { return d.id === m[1]; }), ch = [];
      if (body.comment != null && body.comment !== ud.comment) { ud.comment = body.comment; ch.push("备注"); }
      if (body.origin_domain && body.origin_domain !== ud.origins[0]) { ud.origins = [body.origin_domain]; ch.push("源站"); }
      if (body.price_class && body.price_class !== ud.price_class) { ud.price_class = body.price_class; ch.push("价格等级"); }
      if (body.origin_protocol && body.origin_protocol !== ud.cfg.origin_protocol) { ud.cfg.origin_protocol = body.origin_protocol; ch.push("回源协议"); }
      if (body.default_root_object != null && body.default_root_object !== ud.cfg.default_root_object) { ud.cfg.default_root_object = body.default_root_object; ch.push("默认根对象"); }
      if (!ch.length) ch.push("备注");
      ud.status = "InProgress"; setTimeout(function () { ud.status = "Deployed"; }, 8000);
      return { ok: true, changed: ch, message: "已更新：" + ch.join("、") + "（部署约需几分钟）" };
    }
    if ((m = p.match(/\/cloudfront\/([A-Z0-9]+)$/)) && method === "DELETE") {
      if (q.get("confirm") !== "true") return { __status: 400, detail: "删除分发需确认" };
      var xd = cfs.find(function (d) { return d.id === m[1]; });
      if (!xd.enabled && xd.status === "Deployed") { cfs = cfs.filter(function (d) { return d !== xd; }); return { ok: true, deleted: true }; }
      xd.enabled = false; xd.status = "InProgress";
      var tid = addTask("cf_delete", (accOf(p) || {}).id, "删除 CDN 分发 · " + xd.id, { params: { name: xd.id }, extra: ["分发仍在启用中，先停用…", "等待停用部署完成（当前 InProgress）…"], done: "分发 " + xd.id + " 已删除", result: { distribution_id: xd.id, deleted: true } });
      setTimeout(function () { cfs = cfs.filter(function (d) { return d !== xd; }); }, 9000);
      return { ok: true, deleted: false, task_id: tid, message: "分发仍在启用或部署中：已创建后台任务，先停用并等待部署完成后自动删除" };
    }
    return undefined;
  }

  function billing(id) {
    var a = accounts.find(function (x) { return x.id == id; });
    if (a.provider === "aws") {
      var tot = credits.reduce(function (s, c) { return s + c.amount; }, 0);
      return { period: "2026-10-01 ~ 2026-10-10", currency: "USD", total: 0.16, services: [{ service: "AWS Cost Explorer", amount: 0.16 }, { service: "Amazon Elastic Compute Cloud - Compute", amount: 0.0 }],
        credits: { items: credits, total: tot, used: 18.42, remaining: +(tot - 18.42).toFixed(2) }, cached: true, updated_at: "2026-09-30 08:01", next_refresh: "2026-10-15", ce_calls_this_month: 0 };
    }
    if (a.provider === "oci") return { period: "2026-10-01 ~ 2026-10-10", currency: "USD", total: 0, services: [], cached: false, updated_at: "2026-10-10 18:30" };
    return { period: "本月至今", currency: "USD", total: 3.27, services: [{ service: "Virtual Machines", amount: 2.91 }, { service: "Bandwidth", amount: 0.36 }], cached: false, updated_at: "2026-10-10 18:30" };
  }

  // ---------- v1.4 数据与路由：任务日志 / 批量添加 / 测活 / Credit / 教育优惠 / 订阅 / 换 IP 次数 ----------
  var ipUse = { auto: { 1: 1, 3: 3 }, manual: { 1: 2 } };
  function addMonths(s, n) { var d = new Date(s + "T00:00:00"); var day = d.getDate(); d.setDate(1); d.setMonth(d.getMonth() + n); var last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate(); d.setDate(Math.min(day, last)); return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); }
  function daysTo(s) { return Math.round((new Date(s + "T00:00:00") - new Date(ymd(0) + "T00:00:00")) / 86400000); }
  function eduInfo(a) {
    if (a.provider !== "azure") return null;
    if (a.edu_expires_at) return { expires_at: a.edu_expires_at, estimated: false, days_left: daysTo(a.edu_expires_at), basis: "手动填写" };
    if (!a.cloud_created_at) return { expires_at: null, estimated: false, days_left: null, basis: "未填写到期日，也没有云账号创建日期，无法估算" };
    var e = addMonths(a.cloud_created_at, 12);
    return { expires_at: e, estimated: true, days_left: daysTo(e), basis: "估算：创建日期 " + a.cloud_created_at + " + 12 个月" };
  }
  function creditSummary(id) {
    var a = accounts.find(function (x) { return x.id == id; });
    var items = credits.filter(function (c) { return c.account_id == id; }).sort(function (x, y) { return (x.expire_date || "9999") < (y.expire_date || "9999") ? -1 : 1; });
    var used = a.provider === "aws" ? 18.42 : (id in billMonths ? billMonths[id] : null);
    var note = a.provider === "aws" ? "Cost Explorer 累计抵扣（缓存）" : used == null ? "还没有账单记录（打开一次账单页后开始记录）" : "按月账单累加（演示）";
    var pool = used == null ? null : Math.max(0, used - items.reduce(function (s, c) { return s + (c.used_manual != null ? +c.used_manual : 0); }, 0));
    var out = items.map(function (c) {
      var u = null, src = null;
      if (c.used_manual != null && c.used_manual !== "") { u = +c.used_manual; src = "manual"; } else if (pool != null) { u = +Math.min(c.amount, pool).toFixed(2); src = "billing"; pool -= u; }
      var dl = c.expire_date ? daysTo(c.expire_date) : null;
      return { id: c.id, name: c.name, amount: +c.amount, start_date: c.start_date, expire_date: c.expire_date, used: u, used_manual: c.used_manual, used_source: src,
        remaining: u == null ? null : +(c.amount - u).toFixed(2), days_left: dl, expired: dl != null && dl < 0 };
    });
    var tm = creditTotal[id] != null, total = tm ? creditTotal[id] : out.reduce(function (s, c) { return s + c.amount; }, 0);
    var known = out.filter(function (c) { return c.used != null; });
    var ut = out.length && known.length === out.length ? +known.reduce(function (s, c) { return s + c.used; }, 0).toFixed(2) : null;
    var edu = eduInfo(a), alerts = [];
    out.forEach(function (c) { if (c.days_left != null && c.days_left >= 0 && c.days_left <= 30) alerts.push({ account_id: a.id, account_name: a.name, provider: a.provider, kind: "credit", name: c.name, date: c.expire_date, days_left: c.days_left, estimated: false }); });
    if (edu && edu.days_left != null && edu.days_left >= 0 && edu.days_left <= 30) alerts.push({ account_id: a.id, account_name: a.name, provider: a.provider, kind: "edu", name: "Azure 教育优惠", date: edu.expires_at, days_left: edu.days_left, estimated: edu.estimated });
    return { account_id: a.id, provider: a.provider, name: a.name, currency: "USD", items: out, credit_total: +total.toFixed(2), credit_total_manual: tm, used: ut,
      used_source: ut == null ? null : out.every(function (c) { return c.used_source === "manual"; }) ? "manual" : "billing", remaining: ut == null ? null : +(total - ut).toFixed(2),
      billing_used: used, estimate_note: note, billing_updated_at: used == null ? null : "2026-10-10 18:30", edu: edu, cloud_created_at: a.cloud_created_at,
      age_days: a.cloud_created_at ? -daysTo(a.cloud_created_at) : null, alerts: alerts };
  }
  function parseBatch(text) {
    var out = [], re = /\{[^{}]*(\{[^{}]*\}[^{}]*)?\}/g, mm;
    var jsonPart = text.replace(/\[[^\]\n"{]+\][\s\S]*?(?=\n\s*\{|\n\[[^\]\n"{]+\]|$)/g, function (sec) { out.push({ oci: sec }); return ""; });
    while ((mm = re.exec(jsonPart))) { try { out.push({ json: JSON.parse(mm[0]) }); } catch (e) { out.push({ error: "JSON 解析失败：" + e.message }); } }
    return out.map(function (x, i) {
      if (x.error) return { index: i + 1, ok: false, name: "", error: x.error };
      if (x.oci) {
        var nm = (x.oci.match(/^\s*\[([^\]]+)\]/) || [])[1] || "OCI-" + (i + 1), hasKey = /BEGIN [A-Z ]*PRIVATE KEY/.test(x.oci);
        var miss = ["user", "fingerprint", "tenancy", "region"].filter(function (k) { return !new RegExp("^\\s*" + k + "\\s*=", "m").test(x.oci); });
        if (!hasKey) miss.push("key_content");
        return { index: i + 1, provider: "oci", name: nm, ok: !miss.length, error: miss.length ? (/key_file/.test(x.oci) && !hasKey ? "key_file 在面板服务器上读不到，请把私钥 PEM 直接贴在该段后面" : "缺少字段：" + miss.join(", ")) : undefined };
      }
      var o = x.json, c = o.cred || o, pv = o.provider || (c.access_key || c.aws_access_key_id ? "aws" : c.tenant_id || c.appId ? "azure" : c.tenancy ? "oci" : null);
      if (!pv) return { index: i + 1, ok: false, name: o.name || "", error: "无法判断云厂商，请加上 \"provider\"" };
      var req = { aws: ["access_key", "secret_key", "region"], azure: ["tenant_id", "client_id", "client_secret", "subscription_id"], oci: ["user", "tenancy", "fingerprint", "key_content", "region"] }[pv];
      var alias = { aws_access_key_id: "access_key", aws_secret_access_key: "secret_key", appId: "client_id", password: "client_secret", tenant: "tenant_id" };
      var cc = {}; Object.keys(c).forEach(function (k) { cc[alias[k] || k] = c[k]; });
      var miss2 = req.filter(function (k) { return !cc[k]; });
      return { index: i + 1, provider: pv, name: o.name || pv.toUpperCase() + "-" + (i + 1), ok: !miss2.length, error: miss2.length ? "缺少字段：" + miss2.join(", ") : undefined };
    });
  }
  function testOne(a) {
    var ok = (a.id !== 4 || !!a._fixed) && !a._badcred, ms = 200 + Math.floor(Math.random() * 900);
    a.last_test_ok = ok ? 1 : 0; a.last_test_ms = ms; a.last_test_at = Math.floor(Date.now() / 1000); a.last_test_error = ok ? null : "ClientAuthenticationError: AADSTS7000222 client secret expired（演示）";
    return { account_id: a.id, name: a.name, provider: a.provider, ok: ok, ms: ms, error: a.last_test_error || undefined };
  }
  function route14(method, p, q, body) {
    var m;
    if ((m = p.match(/^\/tasks\/(\d+)$/)) && method === "GET") {
      var t = tasks.find(function (x) { return x.id == m[1]; });
      if (!t) return { __status: 404, detail: "任务不存在" };
      var after = +(q.get("after") || 0), all = tlogs[t.id] || [];
      var logs = after ? all.filter(function (l) { return l.id > after; }) : all.slice(-500);
      var TN = { snatch: "抢机", change_ip: "换 IP", resize: "改配置", ipv6: "IPv6", azure_create: "创建 VM", create: "创建 VM", ensure_network: "自动建网", network: "自动建网", snapshot: "快照（已移除）", migrate: "迁移" };
      return Object.assign({}, t, { type_name: TN[t.type] || t.type, params: t.params || {}, result: t.result || null, logs: logs, last_log_id: logs.length ? logs[logs.length - 1].id : after });
    }
    if (p === "/accounts/parse") {   // 演示版：简化的自动识别（真实面板由后端完整解析）
      var t = String((body && body.text) || ""), out = [];
      var pick = function (re) { var m = t.match(re); return m ? m[1].trim() : ""; };
      var ak = pick(/\b((?:AKIA|ASIA)[A-Z0-9]{16})\b/);
      if (ak) out.push({ provider: "aws", name: pick(/(?:名称|备注|name)\s*[:：=]\s*(.+)/i), cred: { access_key: ak, secret_key: pick(/(?<![A-Za-z0-9\/+=])([A-Za-z0-9\/+]{40})(?![A-Za-z0-9\/+=])/), region: pick(/\b((?:us|eu|ap|sa|ca|me)-[a-z]+-\d)\b/) || "us-east-1" } });
      var ten = pick(/(?:tenant|租户)[^\n:：=]*[:：=\n]\s*([0-9a-f-]{36})/i);
      if (ten) out.push({ provider: "azure", name: "", cred: { tenant_id: ten, client_id: pick(/(?:client|app|客户端)[^\n:：=]*[:：=\n]\s*([0-9a-f-]{36})/i), client_secret: pick(/(?:secret|password|值)[^\n:：=]*[:：=\n]\s*(\S*~\S+)/i), subscription_id: pick(/(?:subscription|订阅)[^\n:：=]*[:：=\n]\s*([0-9a-f-]{36})/i) } });
      var us = pick(/\b(ocid1\.user\.\S+)/);
      if (us) out.push({ provider: "oci", name: pick(/^\s*\[([^\]]+)\]/m).replace(/^DEFAULT$/, ""), cred: { user: us, tenancy: pick(/\b(ocid1\.tenancy\.\S+)/), fingerprint: pick(/\b((?:[0-9a-f]{2}:){15}[0-9a-f]{2})\b/), region: pick(/region\s*=\s*(\S+)/), key_content: pick(/(-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----)/) } });
      var REQ = { aws: ["access_key", "secret_key", "region"], azure: ["tenant_id", "client_id", "client_secret", "subscription_id"], oci: ["user", "tenancy", "fingerprint", "key_content", "region"] };
      return { items: out.map(function (x) { x.missing = REQ[x.provider].filter(function (k) { return !x.cred[k]; }); x.error = null; return x; }) };
    }
    if (p === "/accounts/batch") {
      if (!body || !String(body.text || "").trim()) return { __status: 400, detail: "没有解析到任何账号" };
      var res = parseBatch(body.text);
      res.forEach(function (r) {
        if (!r.ok || body.dry_run) { if (r.ok) r.dry_run = true; return; }
        if (accounts.some(function (a) { return a.name === r.name && a.provider === r.provider; })) { r.ok = false; r.error = "同名账号已存在"; return; }
        var na = { id: Date.now() % 100000 + r.index, provider: r.provider, name: r.name, region: r.provider === "azure" ? null : "ap-tokyo-1", created: Math.floor(Date.now() / 1000), cloud_created_at: r.provider === "oci" ? ymd(-30) : null, last_test_ok: 1, last_test_ms: 640 };
        accounts.push(na); inst[na.id] = []; r.id = na.id; r.ms = 640;
      });
      audit1("POST /accounts/batch", res.filter(function (r) { return r.ok; }).length + " 个");
      return { total: res.length, ok: res.filter(function (r) { return r.ok; }).length, failed: res.filter(function (r) { return !r.ok; }).length, results: res };
    }
    if (p === "/accounts/test-all") {
      var list = accounts.filter(function (a) { return !a.disabled && (!body || !body.provider || a.provider === body.provider); }).map(testOne);
      return { total: list.length, ok: list.filter(function (x) { return x.ok; }).length, failed: list.filter(function (x) { return !x.ok; }).length, ms: 1180, results: list };
    }
    if ((m = p.match(/^\/accounts\/(\d+)\/test$/))) return testOne(accounts.find(function (a) { return a.id == m[1]; }));
    if ((m = p.match(/^\/accounts\/(\d+)\/credit-summary$/))) return creditSummary(+m[1]);
    if ((m = p.match(/^\/accounts\/(\d+)\/credits-manual$/))) {
      if (method === "GET") return credits.filter(function (c) { return c.account_id == m[1]; });
      if (body.amount === "" || body.amount == null) return { __status: 400, detail: "初始额度必填" };
      var nc = { id: Date.now(), account_id: +m[1], name: body.name || "Credit", amount: +body.amount, start_date: body.start_date || null, expire_date: body.expire_date || null, used_manual: body.used_manual === "" || body.used_manual == null ? null : +body.used_manual };
      credits.push(nc); audit1("POST /credits-manual", nc.name); return { id: nc.id };
    }
    if ((m = p.match(/^\/accounts\/(\d+)\/credits-manual\/(\d+)$/))) {
      if (method === "DELETE") { credits = credits.filter(function (c) { return c.id != m[2]; }); return { ok: true }; }
      var ec = credits.find(function (c) { return c.id == m[2]; }); if (!ec) return { __status: 404, detail: "Credit 不存在" };
      ["name", "start_date", "expire_date"].forEach(function (k) { if (k in body) ec[k] = body[k] || null; });
      if ("amount" in body) ec.amount = +body.amount; if ("used_manual" in body) ec.used_manual = body.used_manual === "" || body.used_manual == null ? null : +body.used_manual;
      return { ok: true };
    }
    if ((m = p.match(/^\/accounts\/(\d+)\/credit-total$/))) { creditTotal[m[1]] = body.credit_total === "" || body.credit_total == null ? null : +body.credit_total; if (creditTotal[m[1]] == null) delete creditTotal[m[1]]; return { ok: true }; }
    if ((m = p.match(/^\/accounts\/(\d+)\/edu-expires-at$/))) { accounts.find(function (a) { return a.id == m[1]; }).edu_expires_at = body.edu_expires_at || null; return { ok: true }; }
    if (p === "/expiry-alerts") { var al = []; accounts.forEach(function (a) { al = al.concat(creditSummary(a.id).alerts); }); return al.sort(function (x, y) { return x.days_left - y.days_left; }); }
    if ((m = p.match(/^\/accounts\/(\d+)\/azure\/subscription$/))) {
      var az = accounts.find(function (a) { return a.id == m[1]; });
      return { name: az.name, subscription_id: "00000000-0000-0000-0000-00000000demo", display_name: "Azure for Students", state: "Enabled", quota_id: "AzureForStudents_2018-01-01",
        offer: "Azure for Students（学生）", spending_limit: "On", location_placement_id: "Public_2014-09-01", authorization_source: "RoleBased", tenant_id: "11111111-2222-3333-4444-55555demo",
        edu: eduInfo(az), cloud_created_at: az.cloud_created_at, age_days: az.cloud_created_at ? -daysTo(az.cloud_created_at) : null };
    }
    if ((m = p.match(/^\/accounts\/(\d+)\/ip-change-usage$/))) { var lim = +settings.auto_ip_daily_limit; var au = ipUse.auto[m[1]] || 0; return { account_id: +m[1], day: ymd(0), auto_used: au, manual_used: ipUse.manual[m[1]] || 0, limit: lim, auto_left: Math.max(0, lim - au) }; }
    if (p === "/ip-change-usage") return accounts.map(function (a) { var lim = +settings.auto_ip_daily_limit, au = ipUse.auto[a.id] || 0; return { account_id: a.id, name: a.name, provider: a.provider, day: ymd(0), auto_used: au, manual_used: ipUse.manual[a.id] || 0, limit: lim, auto_left: Math.max(0, lim - au) }; });
    if (p === "/settings" && method === "POST" && body && "auto_ip_daily_limit" in body && !(+body.auto_ip_daily_limit >= 0 && +body.auto_ip_daily_limit <= 50)) return { __status: 400, detail: "自动换 IP 每日上限 0~50" };
    if ((m = p.match(/^\/accounts\/(\d+)\/billing$/))) { var ba = accounts.find(function (a) { return a.id == m[1]; }); if (ba && ba.provider !== "aws" && !(ba.id in billMonths)) billMonths[ba.id] = ba.provider === "oci" ? 0 : 3.27; }
    return undefined;
  }

  function route(method, path, body) {
    var u = new URL(path, "http://x"); var p = u.pathname.replace(/^\/api/, ""); var q = u.searchParams; var m;
    var r16 = route16(method, p, q, body); if (r16 !== undefined) return r16;
    var r15 = route15(method, p, q, body); if (r15 !== undefined) return r15;
    var r14 = route14(method, p, q, body); if (r14 !== undefined) return r14;



    // ---------- v1.3 路由 ----------
    if (p === "/traffic-guards" && method === "GET") return tguards.map(guardView);
    if (p === "/traffic-guards" && method === "POST") {
      var ta2 = accounts.find(function (a) { return a.id == body.account_id; }); var lim = +body.limit_gb || ({ oci: 10240, aws: 100, azure: 100 })[ta2.provider];
      var used = fakeTraffic(ta2).out_gb + (body.count_in ? fakeTraffic(ta2).in_gb : 0);
      tguards = tguards.filter(function (g) { return !(g.account_id == body.account_id && g.instance_id === body.instance_id); });
      var dir = body.direction || (body.count_in ? "both" : "out"), ft = fakeTraffic(ta2), rolling = body.mode === "rolling", wh = +body.window_hours || 24;
      if (rolling && (wh < 1 || wh > 720)) return { __status: 400, detail: "滚动窗口 1~720 小时" };
      var base = rolling ? wh / (24 * 30) : 1; used = (dir === "out" ? ft.out_gb : dir === "in" ? ft.in_gb : ft.out_gb + ft.in_gb) * base;
      var ng = { id: Date.now(), account_id: ta2.id, account_name: ta2.name, provider: ta2.provider, instance_id: body.instance_id, name: body.name, limit_gb: lim, warn_pct: +body.warn_pct || 80, action: body.action, count_in: dir === "both" ? 1 : 0, last_gb: +used.toFixed(1), last_pct: +(used / lim * 100).toFixed(1), checked_at: Math.floor(Date.now() / 1000),
        mode: rolling ? "rolling" : "monthly", window_hours: wh, direction: dir, shutdown_hours: body.action === "stop" ? +body.shutdown_hours || 0 : 0, enabled: body.enabled === false ? 0 : 1, state: "ok" };
      tguards.push(ng); audit1("POST /traffic-guards", body.name); return { ok: true, last_gb: ng.last_gb, last_pct: ng.last_pct };
    }
    if ((m = p.match(/^\/traffic-guards\/(\d+)\/check$/))) { var tg = tguards.find(function (g) { return g.id == m[1]; }); tg.checked_at = Math.floor(Date.now() / 1000); return guardView(tg); }
    if ((m = p.match(/^\/traffic-guards\/(\d+)$/)) && method === "PATCH") {
      var pg = tguards.find(function (g) { return g.id == m[1]; });
      if ("enabled" in body) pg.enabled = body.enabled ? 1 : 0;
      if (body.cancel_resume) { pg.resume_at = null; pg.state_msg = "已取消自动开机"; }
      if (body.reset_state) { pg.state = "ok"; pg.resume_at = null; pg.state_msg = null; }
      audit1("PATCH /traffic-guards", JSON.stringify(body)); return guardView(pg);
    }
    if ((m = p.match(/^\/traffic-guards\/(\d+)$/)) && method === "DELETE") { tguards = tguards.filter(function (g) { return g.id != m[1]; }); return { ok: true }; }
    if (p.match(/^\/accounts\/\d+\/traffic$/)) return fakeTraffic(accOf(p));
    // ---------- v1.2 路由 ----------
    var ga = accOf(p), g;
    if (ga && method === "POST") {
      var gop = p.match(/\/oci\/create$|\/oci\/snatch$|\/aws\/ec2-create$|\/azure\/create$/) ? "create" : p.match(/\/oci\/boot-volume$/) ? "bootvol" : null;
      if (gop && (g = guardDemo(ga, gop, body))) return g;
    }
    if (p === "/account-health") return accounts.map(function (a) { return healthOut(a.id); });
    if (p === "/account-health/refresh") { var ids = body && body.account_id ? [body.account_id] : accounts.map(function (a) { return a.id; });
      ids.forEach(function (i) { if (!health[i]) health[i] = { score: 100, items: [["凭证与账号状态", 1, "API 调用正常", 0], ["实例异常停机", 1, "无", 0], ["近 24 小时任务失败", 1, "无", 0]] }; health[i].at = Math.floor(Date.now() / 1000); });
      return ids.map(healthOut); }
    if (p === "/migrate") {
      if (body.from_account_id == body.to_account_id) return { __status: 400, detail: "目标账号不能与源账号相同" };
      var ta = accounts.find(function (a) { return a.id == body.to_account_id; });
      if ((g = guardDemo(ta, "create", Object.assign({ confirm_overage: body.confirm_overage }, body.create)))) return g;
      var nn = (body.create && body.create.name) || "migrated";
      setTimeout(function () { (inst[ta.id] = inst[ta.id] || []).push({ id: "demo-mig-" + Date.now(), name: nn, state: "running", public_ip: "203.0.113.150", private_ip: "10.9.0.5", ipv6: [], shape: (body.create && (body.create.shape || body.create.type || body.create.size)) || "-", ocpus: 1, memory_gb: 6, zone: "-" });
        if (body.switch_dns) dnsb.forEach(function (b) { if (b.name === body.name) { b.name = nn; b.account_name = ta.name; } }); }, 5000);
      audit1("POST /migrate", body.name + " → " + ta.name);
      return { ok: true, task_id: addTask("migrate", ta.id, "迁移 " + body.name + " → " + ta.name + (body.switch_dns ? "，DNS 已切换" : "")) };
    }
    // ---------- v1.1 路由 ----------
    if (p === "/login") return settings.totp_enabled && !(body && body.otp) ? { __status: 401, detail: "需要二次验证码" } : { ok: true };
    if (p === "/password") return { ok: true };
    if (p === "/accounts" && method === "POST") {
      var REQ = { oci: ["user", "tenancy", "fingerprint", "key_content", "region"], aws: ["access_key", "secret_key", "region"], azure: ["tenant_id", "client_id", "client_secret", "subscription_id"] };
      var cr = body.cred || {}, miss = (REQ[body.provider] || []).filter(function (k) { return !String(cr[k] || "").trim(); });
      if (!String(body.name || "").trim()) miss.unshift("name");
      if (miss.length) return { __status: 400, detail: "缺少字段：" + miss.join(", ") };
    }
    if (p === "/accounts" && method === "POST") { var na = Object.assign({ id: Date.now() % 100000, created: Math.floor(Date.now() / 1000) }, { provider: body.provider || "oci", name: body.name || "新账号", region: body.region || null }); accounts.push(na); inst[na.id] = []; audit1("POST /accounts", na.name); return na; }
    if ((m = p.match(/^\/accounts\/(\d+)$/))) {
      if (method === "DELETE") { accounts = accounts.filter(function (a) { return a.id != m[1]; }); return { ok: true }; }
      if (method === "GET") return Object.assign({ proxy: "", config: { region: "ap-tokyo-1" } }, accounts.find(function (a) { return a.id == m[1]; }));
      var ea = accounts.find(function (a) { return a.id == m[1]; });
      if (ea && body) {
        if (body.name) ea.name = body.name;
        var bad = ["cloud_created_at", "edu_expires_at"].find(function (k) { return k in body && body[k] && !/^\d{4}-\d{2}-\d{2}$/.test(body[k]); });
        if (bad) return { __status: 400, detail: bad + " 日期格式应为 YYYY-MM-DD" };
        if ("cloud_created_at" in body) ea.cloud_created_at = body.cloud_created_at || null;
        if ("edu_expires_at" in body) ea.edu_expires_at = body.edu_expires_at || null;
        if ("proxy" in body) ea.proxy = body.proxy ? String(body.proxy).split("@").pop() : "";
      }
      return { ok: true };
    }
    if ((m = p.match(/^\/tasks\/(\d+)$/)) && method === "DELETE") { tasks = tasks.filter(function (t) { return t.id != m[1] || t.status === "running"; }); if (!tasks.some(function (t) { return t.id == m[1]; })) delete tlogs[m[1]]; return { ok: true }; }
    if (p === "/monitors" && method === "POST") { var ac = accounts.find(function (a) { return a.id == body.account_id; }) || {}; monitors.push(Object.assign({ id: Date.now(), account_name: ac.name, last_state: "running" }, body)); return { ok: true }; }
    if ((m = p.match(/^\/monitors\/(\d+)$/))) { monitors = monitors.filter(function (x) { return x.id != m[1]; }); return { ok: true }; }
    if (p === "/scripts" && method === "GET") return scripts;
    if (p === "/scripts" && (!String(body.name || "").trim() || !String(body.content || "").trim())) return { __status: 400, detail: "名称和内容必填" };
    if (p === "/scripts") { if (body.id) { var sc = scripts.find(function (x) { return x.id == body.id; }); Object.assign(sc, body); } else scripts.push({ id: Date.now(), name: body.name || "未命名", content: body.content || "" }); audit1("POST /scripts", body.name); return { ok: true }; }
    if ((m = p.match(/^\/scripts\/(\d+)$/))) { scripts = scripts.filter(function (x) { return x.id != m[1]; }); return { ok: true }; }
    if (p === "/secrets") return secrets;
    if ((m = p.match(/^\/secrets\/(\d+)\/reveal$/))) { if (!body || !body.password) return { __status: 400, detail: "请输入面板密码（演示：任意）" }; var se = secrets.find(function (x) { return x.id == m[1]; }); return { username: se.username, password: rpw() }; }
    if ((m = p.match(/^\/secrets\/(\d+)$/))) { secrets = secrets.filter(function (x) { return x.id != m[1]; }); return { ok: true }; }
    if (p === "/cf/zones") return zones;
    if (p === "/dns-bindings" && method === "GET") return dnsb;
    if (p === "/dns-bindings") { dnsb.push({ id: Date.now(), record: body.record || "node.example.com", name: body.name, account_name: (accounts.find(function (a) { return a.id == body.account_id; }) || {}).name, v4: body.v4 ? 1 : 0, v6: body.v6 ? 1 : 0, proxied: body.proxied ? 1 : 0 }); audit1("POST /dns-bindings", body.record);
      return { ok: true, dns: body.sync_now ? [(body.v4 ? "A " + body.record + " → " + (body.ipv4 || "203.0.113.10") : ""), (body.v6 ? "AAAA 已同步" : "")].filter(Boolean) : [] }; }
    if ((m = p.match(/^\/dns-bindings\/(\d+)$/))) { dnsb = dnsb.filter(function (x) { return x.id != m[1]; }); return { ok: true }; }
    if (p === "/tokens" && method === "GET") return tokens;
    if (p === "/tokens") { var tk = "tc_" + rpw() + rpw(); tokens.push({ id: Date.now(), name: body.name || "token", prefix: tk.slice(0, 7), scope: body.scope || "read", last_used: null }); audit1("POST /tokens", body.name); return { token: tk }; }
    if ((m = p.match(/^\/tokens\/(\d+)$/))) { tokens = tokens.filter(function (x) { return x.id != m[1]; }); return { ok: true }; }
    if (p === "/audit") return audit.slice(0, +(q.get("limit") || 100));
    if (p === "/2fa/setup") return { secret: "JBSWY3DPEHPK3PXP", uri: "otpauth://totp/TriCloud:demo?secret=JBSWY3DPEHPK3PXP&issuer=TriCloud" };
    if (p === "/2fa/enable") { if (!/^\d{6}$/.test((body && body.code) || "")) return { __status: 400, detail: "请输入 6 位数字（演示：任意 6 位）" }; settings.totp_enabled = true; audit1("POST /2fa/enable"); return { ok: true }; }
    if (p === "/2fa/disable") { settings.totp_enabled = false; audit1("POST /2fa/disable"); return { ok: true }; }
    if (p === "/backup") { if (!body || (body.passphrase || "").length < 10) return { __status: 400, detail: "备份口令至少 10 位" }; audit1("POST /backup", "已导出加密备份"); return { __blob: "TCBK1-DEMO-" + btoa(String(Date.now())), __name: "tricloud-demo.tcbk" }; }
    if (p === "/restore") return { __status: 400, detail: "演示模式不支持恢复" };
    // OCI
    if (p.match(/\/detect-created$/)) return { cloud_created_at: "2025-04-27" };
    if (p.match(/\/oci\/boot-volume$/) && method === "GET") return { name: "arm-main (Boot Volume)", size_gb: 50, vpus_per_gb: 10, state: "AVAILABLE" };
    if (p.match(/\/oci\/boot-volume$/)) return { ok: true, hint: "已提交，扩容后需在系统内执行 growpart 扩展分区" };
    if (p.match(/\/oci\/limits$/)) return { region: q.get("region") || "ap-tokyo-1", a1_basis: "paid", items: [
      { name: "A1 ARM OCPU", limit: 250, used: 1, available: 249, free: 4, free_left: 3 }, { name: "A1 ARM 内存(GB)", limit: 1666, used: 4, available: 1662, free: 24, free_left: 20 },
      { name: "E2.1.Micro 数量", limit: 2, used: 1, available: 1, free: 2, free_left: 1 }, { name: "引导卷总容量 GB", limit: 200, used: 97, available: 103 }, { name: "保留公网 IP", limit: 1, used: 0, available: 1 }] };
    if (p.match(/\/oci\/security$/) && method === "GET") return seclists;
    if (p.match(/\/oci\/security$/)) { var sl = seclists[0];
      if (body.op === "remove") sl.rules = sl.rules.filter(function (r) { return !(r.direction === body.direction && r.idx == body.idx); });
      if (body.op === "add" || body.op === "add_ports") {
        var c0 = (body.cidr || "0.0.0.0/0").replace(/\s/g, ""), pubc = c0 === "0.0.0.0/0" || c0 === "::/0", pp = body.op === "add_ports" ? body.ports : body.port;
        var prs = body.op === "add_ports" ? (body.protocols || ["tcp"]) : [String(body.protocol || "").toLowerCase()];
        var prg = pp ? parsePorts(pp) : [];
        if (prg.error) return { __status: 400, detail: prg.error };
        if ((body.op === "add_ports" || body.direction === "ingress") && pubc) {
          if (prs[0] === "all" || ((prs[0] === "tcp" || prs[0] === "udp") && (!prg.length || prg.some(function (x) { return x[0] <= 1 && x[1] >= 65535; })))) return { __status: 400, detail: "不支持对 0.0.0.0/0（或 ::/0）放行全部端口，请填写具体端口" };
          if (!body.confirm_public) return { __status: 409, detail: { msg: "来源为 0.0.0.0/0：将对整个互联网开放", public_warning: true } };
        }
      }
      if (body.op === "add_ports") { var ad = 0, sk = 0;
        body.protocols.forEach(function (pr) { prg.forEach(function (x) { var pt = x[0] === x[1] ? String(x[0]) : x[0] + "-" + x[1];
          if (sl.rules.some(function (y) { return y.direction === "ingress" && y.protocol === pr && y.cidr === c0 && y.port === pt; })) { sk++; return; }
          sl.rules.push({ direction: "ingress", protocol: pr, cidr: c0, port: pt, idx: sl.rules.length + 10 }); ad++; }); });
        audit1("POST /oci/security", "add_ports " + body.ports); return { ok: true, added: ad, skipped: sk }; }
      if (body.op === "add") sl.rules.push({ direction: body.direction, protocol: body.protocol, cidr: body.cidr, port: body.port || "全部", idx: sl.rules.length + 10 });
      audit1("POST /oci/security", body.op); return { ok: true }; }
    // v1.5：按规格返回平台镜像版本（A1 = aarch64，E2 = x86；演示数据）
    if (p.match(/\/oci\/os-versions$/)) return /A1/.test(q.get("shape") || "")
      ? { "Canonical Ubuntu": ["24.04", "24.04 Minimal aarch64", "22.04", "22.04 Minimal aarch64", "20.04"], "Oracle Linux": ["9", "8"] }
      : { "Canonical Ubuntu": ["24.04", "24.04 Minimal", "22.04", "22.04 Minimal", "20.04"], "Oracle Linux": ["9", "8", "7.9"] };
    if ((m = p.match(/^\/accounts\/(\d+)\/oci\/traffic-summary$/))) { var tsi = (inst[m[1]] || []).map(function (i, k) { var o = [1834.2, 38.6, 512.9, 7.3][k % 4]; return { id: i.id, name: i.name, state: i.state, public_ip: i.public_ip, shape: i.shape, region: i.region, out_gb: o, in_gb: +(o * 0.31).toFixed(1) }; });
      var tdn = new Date(); return { region: q.get("region") || "ap-tokyo-1", period: tdn.getFullYear() + "-" + ("0" + (tdn.getMonth() + 1)).slice(-2) + "-01 ~ 今天", items: tsi,
        out_gb: +tsi.reduce(function (a, r) { return a + r.out_gb; }, 0).toFixed(3), in_gb: +tsi.reduce(function (a, r) { return a + r.in_gb; }, 0).toFixed(3), free_out_gb: 10240 }; }
    if (p.match(/\/oci\/traffic$/)) return { period: "2026-10-01 ~ 今天", out_gb: 38.6, in_gb: 112.4 };
    if (p.match(/\/(oci|instances)\/rename$/) && method === "POST") { var ra = accOf(p) || {};
      Object.keys(inst).forEach(function (k) { inst[k].forEach(function (i) { if (i.id === body.instance_id) i.name = body.new_name; }); });
      var hn = String(body.new_name || "").toLowerCase().replace(/[\s_.]+/g, "-").replace(/[^a-z0-9-]/g, "").replace(/-{2,}/g, "-").replace(/^-+|-+$/g, "").slice(0, 63).replace(/-+$/, "");
      audit1("POST /instances/rename", body.new_name + (body.sync_hostname === false ? "" : " · hostname " + (hn || "-")));
      if (body.sync_hostname === false) return { ok: true, hostname: null };
      if (!hn) return { ok: true, hostname: { status: "unsupported", message: "名称规范化后为空（只保留 a-z 0-9 -），已跳过主机名同步（演示）" } };
      // 演示：Azure（Run Command）与 OCI（Oracle Cloud Agent）均同步成功
      return { ok: true, hostname: { status: "ok", hostname: hn, message: (ra.provider === "azure" ? "Azure Run Command" : ra.provider === "aws" ? "SSM" : "Oracle Cloud Agent")
        + "：系统主机名已改为 " + hn + "，重新登录 SSH 可见（演示）" } }; }
    if (p.match(/\/oci\/network$/)) return { ok: true, task_id: addTask("network", (accOf(p) || {}).id, "自动创建 VCN + IPv6") };
    // AWS
    if (p.match(/\/aws\/ec2-options$/)) return { types: ["t3.micro", "t3.small", "t3.medium", "t4g.micro", "t4g.small", "c7i.large"], os: ["debian-12", "ubuntu-24.04", "ubuntu-22.04", "amazon-linux-2023"] };
    if (p.match(/\/aws\/ec2-create$/)) { audit1("POST /aws/ec2-create", body.name); return created(body.name || "ec2-demo", "198.51.100.41", "admin"); }
    if (p.match(/\/aws\/regions-status$/)) return [["us-east-1", "ENABLED_BY_DEFAULT"], ["us-west-2", "ENABLED_BY_DEFAULT"], ["ap-northeast-1", "ENABLED_BY_DEFAULT"], ["ap-southeast-1", "ENABLED_BY_DEFAULT"], ["eu-central-1", "ENABLED_BY_DEFAULT"], ["ap-east-1", "DISABLED"], ["ap-southeast-3", "DISABLED"], ["me-central-1", "ENABLED"], ["af-south-1", "DISABLED"]].map(function (r) { return { region: r[0], status: r[1] }; });
    if (p.match(/\/aws\/enable-region$/)) return { ok: true, hint: body.region + " 激活中，通常需要几分钟到几小时" };
    if (p.match(/\/aws\/scan$/)) return { updated_at: new Date().toLocaleString(), regions: [{ region: "ap-northeast-1", ec2: 2, ec2_running: 1, lightsail: 1 }, { region: "us-west-2", ec2: 1, ec2_running: 0, lightsail: 0 }, { region: "eu-central-1", ec2: 0, ec2_running: 0, lightsail: null }] };
    if (p.match(/\/recycle$/)) return { region: q.get("region") || "ap-northeast-1", monthly_total: "4.38", month_to_date: "0.16", billing_updated_at: "2026-09-30 08:01", credit_remaining: "101.58", credit_months_for_idle: 23, items: [
      { name: "test-box 的 EBS", id: "vol-0demo11aa", detail: "停机实例的 8GB gp2 系统盘仍计费", monthly: "0.96", tip: "不再使用可终止实例" },
      { name: "未挂载卷", id: "vol-0demo22bb", detail: "20GB gp3，未挂载", monthly: "1.92", tip: "确认无数据后删除" },
      { name: "闲置弹性 IP", id: "eipalloc-0demo33", detail: "198.51.100.88 未绑定", monthly: "3.60", tip: "释放 IP" },
      { name: "快照", id: "snap-0demo44cc", detail: "8GB 快照", monthly: "0.40", tip: "过期快照可删除" }].slice(0, 4).map(function (x) { return x; }) };
    // Azure
    if (p.match(/\/azure\/locations$/)) return ["eastasia", "southeastasia", "japaneast", "japanwest", "koreacentral", "westus2", "eastus"];
    if (p.match(/\/azure\/quotas$/)) return { items: [{ name: "Total Regional vCPUs", used: 1, limit: 6 }, { name: "Standard BS Family vCPUs", used: 1, limit: 6 }, { name: "Standard DASv5 Family vCPUs", used: 0, limit: 0 }, { name: "Public IP Addresses - Standard", used: 1, limit: 3 }] };
    if (p.match(/\/azure\/rgs$/) && method === "GET") return rgs;
    if (p.match(/\/azure\/rgs$/)) { if (body.op === "delete") { if (body.confirm !== body.name) return { __status: 400, detail: "资源组名称不匹配" }; rgs = rgs.filter(function (g) { return g.name !== body.name; }); } else rgs.push({ name: body.name || "rg-new", location: body.location || "eastasia", state: "Succeeded" }); return { ok: true }; }
    if (p.match(/\/azure\/create$/)) { secrets.unshift({ id: Date.now(), name: body.name, account_name: "Azure 学生", username: "azureuser", created: Math.floor(Date.now() / 1000) }); audit1("POST /azure/create", body.name); return { ok: true, task_id: addTask("create", 4, "创建 VM " + body.name) }; }
    if (p === "/accounts") return accounts;
    if (p === "/settings" && method === "GET") return settings;
    if (p === "/settings") { Object.assign(settings, body || {}); return { ok: true }; }
    if (p === "/settings/tg-test") return { ok: true };
    if (p === "/tasks") return tasks.slice(0, +(q.get("limit") || 50));
    if ((m = p.match(/^\/tasks\/(\d+)\/stop$/))) { tasks.forEach(function (t) { if (t.id == m[1] && t.status === "running") { t.status = "stopped"; t.message = "已手动停止"; t.updated = Math.floor(Date.now() / 1000); tlog(t.id, "已手动停止", "warn"); } }); return { ok: true }; }
    if (p === "/monitors" && method === "GET") return monitors;
    if (p === "/logout") return { ok: true };
    if ((m = p.match(/^\/accounts\/(\d+)\/regions$/))) { var pr = accounts.find(function (a) { return a.id == m[1]; }).provider; return pr === "oci" ? ["ap-tokyo-1", "ap-seoul-1", "ap-osaka-1"] : ["ap-northeast-1", "ap-southeast-1", "us-east-1", "us-west-2"]; }
    if ((m = p.match(/^\/accounts\/(\d+)\/instances$/)) && method === "GET") return q.get("kind") === "lightsail" ? lightsail : (inst[m[1]] || []);
    if (p.match(/\/instances\/change-ip$/)) {
      var ca = accOf(p), cidrs = String(body.cidrs || "").split(/[,，\n]/).map(function (x) { return x.trim(); }).filter(Boolean);
      if (cidrs.some(function (c) { return !/^!?\s*[0-9a-fA-F:.]+\/\d{1,3}$/.test(c); })) return { __status: 400, detail: "网段格式错误：" + cidrs.join(", ") };
      ipUse.manual[ca.id] = (ipUse.manual[ca.id] || 0) + 1;
      if (ca.provider === "oci" && !cidrs.length) return { ok: true, old_ip: "203.0.113.10", new_ip: "203.0.113.99", dns: [] };
      var exc = cidrs.filter(function (c) { return c[0] === "!"; }), inc = cidrs.filter(function (c) { return c[0] !== "!"; });
      var extra = cidrs.length ? ["网段要求：" + (inc.length ? "命中 " + inc.join(", ") : "") + (inc.length && exc.length ? "；" : "") + (exc.length ? "排除 " + exc.map(function (x) { return x.slice(1); }).join(", ") : ""),
        "第 1 次：203.0.113.41 不满足网段要求，继续…", "第 2 次：198.51.100.9 不满足网段要求，继续…"] : [];
      return { ok: true, task_id: addTask("change_ip", ca.id, "换 IP · " + (body.name || ""), { params: { name: body.name, cidrs: cidrs, max_tries: +body.max_tries || 20 }, extra: extra,
        done: (body.name === "tokyo-t3" ? "198.51.100.7" : "203.0.113.10") + " → 203.0.113.177" + (cidrs.length ? "（3 次）" : ""), result: { old_ip: "203.0.113.10", new_ip: "203.0.113.177", tries: cidrs.length ? 3 : 1 } }) };
    }
    if (p.match(/\/instances\/action$/)) {
      var al = inst[(accOf(p) || {}).id] || [], ai = al.find(function (i) { return i.id === body.instance_id; });
      if (ai && body.action === "terminate") { if (!body.confirm) return { __status: 400, detail: "终止需确认" }; inst[(accOf(p) || {}).id] = al.filter(function (i) { return i !== ai; }); }
      else if (ai) {
        var to = { start: "running", stop: "stopped", reboot: "running" }[body.action];
        ai.state = body.action === "stop" ? "stopping" : "starting";
        setTimeout(function () { ai.state = to; if (to === "running" && !ai.public_ip) ai.public_ip = "203.0.113." + (100 + Math.floor(Math.random() * 100)); }, 2000);
      }
      audit1("POST /instances/action", body.action + " " + (body.name || ""));
      return { ok: true };
    }
    if (p.match(/\/instances\/resize$/)) return { ok: true, task_id: addTask("resize", (accOf(p) || {}).id, "改配置 · " + (body.name || ""), { params: { name: body.name }, done: "改配置完成" }) };
    if (p.match(/\/oci\/ipv6$/)) var v6 = "2001:db8::" + (0xa000 + Math.floor(Math.random() * 0xfff)).toString(16);
    if (p.match(/\/oci\/ipv6$/)) return { ok: true, task_id: addTask("ipv6", (accOf(p) || {}).id, "IPv6 · " + (body.name || ""), { done: "IPv6：" + v6, result: { ipv6: v6 }, onDone: function () { var x = (inst[(accOf(p) || {}).id] || []).find(function (i) { return i.id === body.instance_id; }); if (x) x.ipv6 = (x.ipv6 || []).concat([v6]); } }) };
    if (p.match(/\/oci\/snatch$/)) return { ok: true, task_id: addTask("snatch", (accOf(p) || {}).id, "抢机中"), task_ids: [nextTask - 1] };
    if (p.match(/\/oci\/create$/)) return created((body && (body.name || (body.create && body.create.name))) || "oci-demo", "203.0.113.77", "root");
    if (p.match(/\/azure\/sizes$/)) return [{ name: "Standard_B1s", cores: 1, memory_mb: 1024 }, { name: "Standard_B1ms", cores: 1, memory_mb: 2048 }, { name: "Standard_B2s", cores: 2, memory_mb: 4096 }];
    if (p.match(/\/lightsail\/options$/)) return { zones: ["ap-northeast-1a", "ap-northeast-1c", "ap-northeast-1d"], blueprints: [{ id: "debian_12", name: "Debian 12" }, { id: "ubuntu_24_04", name: "Ubuntu 24.04 LTS" }], bundles: [{ id: "nano_3_0", name: "Nano · 2C/0.5G/20G · $5/月" }, { id: "micro_3_0", name: "Micro · 2C/1G/40G · $7/月" }] };
    if (p.match(/\/lightsail\/create$/)) return created((body && body.name) || "ls-demo", "198.51.100.52", "admin");
    if (p.match(/\/cloudfront$/)) return { id: "E3NEW", domain: "d2new.cloudfront.net", ok: true };
    if (p.match(/\/quotas$/)) return { standard_vcpu: { region: "us-east-1", value: 32, unit: "" }, cloudfront_distributions: { value: 200, unit: "" }, updated_at: "2026-10-10 18:20",
      per_region: [{ region: "ap-northeast-1", value: 16 }, { region: "ap-southeast-1", value: 16 }, { region: "us-east-1", value: 32 }, { region: "us-west-2", value: 16 }, { region: "af-south-1", value: null, error: "未启用" }] };
    if ((m = p.match(/^\/accounts\/(\d+)\/billing$/))) return billing(m[1]);
    if (p.match(/\/credits$/)) { credits.push(Object.assign({ id: Date.now(), account_id: 3, used_manual: null }, body, { amount: +body.amount })); return { id: 1 }; }
    if ((m = p.match(/^\/credits\/(\d+)$/))) { credits = credits.filter(function (c) { return c.id != m[1]; }); return { ok: true }; }
    return { ok: true, demo: true };
  }

  var realFetch = window.fetch;
  window.fetch = function (url, init) {
    url = String(url);
    if (url.indexOf("/api/") !== 0) return realFetch.apply(this, arguments);
    init = init || {};
    var body = init.body ? (typeof init.body === "string" ? JSON.parse(init.body) : { __file: init.body.size || 0 }) : undefined;
    return new Promise(function (res) {
      setTimeout(function () {
        var out; try { out = route(init.method || "GET", url, body); } catch (e) { out = { __status: 500, detail: "演示数据错误：" + e.message }; }
        if (out && out.__blob) return res(new Response(new Blob([out.__blob]), { status: 200, headers: { "Content-Disposition": 'attachment; filename="' + out.__name + '"' } }));
        var st = (out && out.__status) || 200; if (out && out.__status) delete out.__status;
        res(new Response(JSON.stringify(out), { status: st, headers: { "Content-Type": "application/json" } }));
      }, 250);
    });
  };
})();
