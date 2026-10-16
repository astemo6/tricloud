# Changelog

## 1.6.0（build 19）(2026-10-16)
- App 补齐今天只在后端 + Web 上线的功能（Android versionCode 19 / iOS build 19，versionName 仍 1.6.0）：
  - OCI 对象存储页顶部「一键生成保号账单」卡片（仅 PAYG）：先检测已有存储（标准层已用 X GB / 免费 10 GB，已满足 / 还差 X GB，自动分层 / 归档另注，已有 Bucket 列表），大小默认填补足值（0.5–20 GB），显示补足后合计；已满足时按钮变次要「仍要生成」并多一次红色确认；上传进度、续传、删除（含未完成上传）。免费号显示「免费号 20GB 内不收费，无需操作」。Bucket 列表显示大小 / 对象数 / 存储层（自动分层单独标注）。
  - 区域显示城市名（「ap-northeast-1 · 东京」）：AWS / OCI / Azure 区域、可用区、OCI AD 名都识别；提交仍用纯代码。映射与 Web `REGION_CITY` 相同（Android `Regions.java`、iOS `Regions.swift`）。
  - OCI 安全组按子网选择（「VCN / 子网 CIDR · 实例名」，同子网一次，记住上次）；查看 / 添加 / 删除规则带 `subnet_id`；实例另挂 NSG 时只读提示。
  - 设置 → 安全：审计日志「一键清空」（红色按钮 + 确认，`DELETE /api/audit?confirm=true`）。
  - OCI 创建 / 抢机：A1 免费额度按账号类型显示（免费号 2 OCPU / 12 GB，PAYG 4 OCPU / 24 GB），免费号 / 未知类型默认填 2 / 12。
- 新功能：OCI 子网改名（同时可改所属 VCN 名称）。`PATCH /api/accounts/{id}/oci/subnets/{subnet_id}`、`PATCH /api/accounts/{id}/oci/vcns/{vcn_id}`，body `{display_name}`（去首尾空格，1–255 字符），只改显示名称，不影响实例、IP、安全规则；写审计记录（旧名 → 新名）。Web 安全组页子网下拉旁「改名」按钮，保存后刷新下拉并保持选中；Android / iOS 安全组子网卡片里「改名」。
- 修复：AWS Lightsail 页区域列表复用 EC2 区域，选到 Lightsail 不提供服务的区域（如台北 `ap-east-2`）报 `EndpointConnectionError`。现在 `GET /api/accounts/{id}/regions?service=lightsail` 只返回账号已启用且 Lightsail 支持的区域（Lightsail GetRegions 校正并缓存 1 天，失败时用 botocore 端点表）；Web / Android / iOS 的 Lightsail 页、创建、静态 IP 只列这些区域，保存的区域不支持时自动切换并提示「Lightsail 不支持 xxx，已切换到 yyy」；后端 Lightsail 接口遇到不支持的区域返回 400「Lightsail 不支持该区域（台北 ap-east-2），请换区域」；AWS「区域」页扫描跳过不支持 Lightsail 的区域（显示 -）。

## 1.6.0 后端 + Web（2026-10-16，App 未变，仍为 build 18）
- 保号账单「先检测已有存储」：新接口 `GET /api/accounts/{id}/oci/billing-keep/scan[?refresh=true]`（只读，缓存 5 分钟）遍历所有已订阅区域 × 租户根和子区间的 Bucket，用 GetBucket `approximateSize/approximateCount` 按标准层 / 标准层+自动分层 / 归档层汇总，给出「已满足 / 还差 X GB」和补足大小（11 − 已用，向上取 0.1，最小 0.5）。卡片先显示「正在检测已有存储…」；标准层已 >10 GB 时提示无需生成，按钮降为次要并需额外确认。`size_gb` 范围放宽为 0.5–20（仍需 confirm、仍仅 PAYG）。对象存储 Bucket 列表新增「大小」「对象数」「存储层」列（并发 GetBucket，失败显示 —）。
- 新增 OCI「一键生成保号账单」（仅 PAYG 升级号）：对象存储页顶部卡片。在主区域建（或复用）私有标准层 Bucket `tricloud-billing-keep`（关闭自动分层），用 multipart 串行 64 MiB 分片流式上传全零对象（默认 11 GiB；现按已有存储补足，可选 0.5–20），不落盘，内存约一片大小；后台任务显示进度，失败 / 停止后再次发起会续传，删除会中止未完成上传并清理 Bucket。超出 10 GB 标准层免费额度，每月约 $0.02–0.03；上传是入网流量，不计费。免费号直接提示「免费号 20GB 内不收费，无需操作」。新接口：`GET/POST/DELETE /api/accounts/{id}/oci/billing-keep`。
- 修复：弹窗里在输入框拖选文字、松开时指针落在遮罩上会误关弹窗；现在只有按下和点击都在遮罩上才关闭。
- 修复：编辑 Azure 账号显示「区域」且留空保存报「区域不能为空」；Azure 订阅没有默认区域，编辑不再显示 / 要求区域（已存区域的旧账号保持不变）；OCI / AWS 仍必填。

## 1.6.0（build 18）(2026-10-16)
- OCI「区域订阅」移出账号标签栏，防止误点（订阅不可撤销）：Web 收在「配额/网络」页最底部默认折叠的「高级 · 区域订阅（不可撤销）」区块，展开才加载；Android 同样在该页底部折叠；iOS 在该页底部「高级」分组里作为二级页面。订阅除原确认框外，还要手动输入完整区域标识（如 `ap-osaka-1`）才能提交。旧链接 `#/oci/<id>/regionsub` 自动跳到「配额/网络」。后端接口不变。Android versionCode 18 / iOS build 18。

## 1.6.0 结构整理（2026-10-15，接口与数据不变）
- 后端：`app/main.py` 只保留 app 创建、生命周期、认证 / 审计中间件、异常处理；124 个接口按功能拆到 `app/routers/`（auth、accounts、instances、oci、aws、azure、billing、tasks_monitors、settings、security、cloudflare、guard_health、pages，公共工具在 common），`routes_v16.py` 的 27 个接口并入对应模块。全部 151 个接口的路径、方法、参数与匹配顺序不变。
- `extras.py` 拆为 `security`（TOTP / API Token / 审计 / 备份恢复）、`cloudinit`（开机密码 / cloud-init / 脚本模板）、`dns`（Cloudflare）、`net`（TCP 检测 / 网段 / IP 质量）。
- `tasks.py` 一次性任务按类型改为注册表（`ONCE_HANDLERS`），行为不变。
- 内存：三家云 SDK 改为用到哪家才导入；AWS `c()`、OCI `_c()`、Azure 订阅 / 成本客户端按（服务, 区域）复用并加锁；Docker 镜像设置 `MALLOC_ARENA_MAX=2`。
- Web：`web/app.js` 拆为 `web/js/` 下按页面划分的原生 ES 模块（无框架、无打包）；首页生成 import map 给每个模块加内容哈希版本号，`/static/js/*` 另加 `Cache-Control: no-cache`。`demo/build.py` 按模块求值顺序把模块拼回单文件演示页。
- 测试：`tests/selftest*.py` 按模块重命名为 `tests/test_*.py`，新增 `test_structure.py`（23 项）；合计 524 项。

## 1.6.0（build 17）(2026-10-14)
- 1.6.0（build 17）：首页 AWS 实例数包含 Lightsail

## 1.5.0 (2026-10-11)
- 移除快照功能（手动快照、快照列表/删除、定时快照策略；`/api/accounts/{id}/snapshots` 路由、Web/Android 快照 tab 与按钮）。新库不再建 `snapshot_policies` 表，旧库已有的表保留不动；历史 snapshot 任务显示为「快照（已移除）」。AWS 闲置资源里的 EBS / Recycle Bin 快照计费统计保留。
- OCI 创建/抢机/迁移的规格下拉标明 Always Free（A1.Flex、E2.1.Micro）或付费（E4.Flex、Standard3.Flex）；Android 同步。
- 修复手机账号页标签栏切换后跳回最左边（保持滚动位置并让选中标签可见）。
- 修复手机 Web 顶栏挤压导致标题竖排：≤600px 改为两行布局。
- Removed: serial console (WebSocket terminal, OCI/AWS/Azure serial endpoints, xterm, Android ConsoleActivity, paramiko). Use the cloud provider console instead.
- Merged from the legacy panel: Telegram inline-button menu, deleted-accounts bin, separate proxy username/password, per-cloud create defaults, OCI security groups (batch ports, 0.0.0.0/0 confirmation), AWS CloudFront invalidate/edit/toggle/plan/create/delete, account edit with field echo, OCI config multi-profile paste, OCI IPv6 delete confirmation.
- Instance action "Open port" for OCI / AWS / Azure: `POST /api/accounts/{id}/instances/{iid}/open-port` with `{port, protocol: tcp|udp, region, confirm_public}`. Single or batch ports (`80, 443, 8000-8100`), source fixed to 0.0.0.0/0. OCI writes the subnet security list, AWS writes every security group attached to the instance, Azure writes the NIC and subnet NSGs (unique rule names, first free priority). Existing rules are skipped; the response lists added / skipped per group. 409 + `public_warning` without `confirm_public`; 400 for empty ports or 1-65535. Not available for Lightsail.
- Web: "Open port" in the instance card / table "more" menu with a public-exposure warning; the OCI security-list "放行指定端口" button now uses the same endpoint; "Add rule" dialogs gained a single-port / batch-port switch.
- Telegram: "开放端口" in the instance menu — the bot asks for a port reply (`8443`, `80, 443`, `udp 51820`), then shows a confirm button with the public warning; `/cancel` aborts.
- Android: "开放端口" on instance cards (input + warning confirm).
- Removed: OCI legacy security list "open all" (`op=open_all`); added `op=add_ports` (ports required, 0.0.0.0/0 needs confirm_public); `op=add` also enforces the public guard.
- Snatch tasks resume after restart; other interrupted tasks are marked `interrupted`.
- tools/migrate_from_legacy.py (read-only legacy DB, --dry-run, refuses non-empty target).
- 实例改名可同步系统主机名（`sync_hostname`，默认开）：Azure Run Command / OCI 主 VNIC hostname_label + Oracle Cloud Agent Run Command / AWS SSM 执行固定命令，不走 SSH；新增通用 `POST /api/accounts/{id}/instances/rename`（Azure 写 `tricloud-name` 标签、EC2 写 Name 标签，Lightsail 不支持），失败返回原因与 `manual_cmd`，并写审计；新建实例主机名默认 = 实例名（cloud-init hostname、OCI hostname_label、Azure computer_name）。Web / Android 改名弹窗加「同步修改系统主机名（SSH 显示）」复选框。
- OCI 创建/抢机/迁移「系统版本」改为随系统联动的下拉（Ubuntu 24.04/22.04/20.04、Oracle Linux 9/8，「最新」= 空），移除 CentOS；新增 `GET /api/accounts/{id}/oci/os-versions?shape=`（按规格列平台镜像版本，缓存 6 小时）；Android 改为「系统 / 版本」组合下拉。手机顶栏配色下拉 ≤600px 只显示图标。
- Android 1.5.0 (versionCode 6).
- Tests: selftest7 (143), selftest8 (71); total 413 passing (snapshot tests removed).

## 1.4.0
See README.
