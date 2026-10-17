# TriCloud 功能详解（按版本）

## v1.1 新增（取各家面板之长）

| 模块 | 内容 |
|---|---|
| OCI 网络 | 无公有子网时**自动建网**（VCN + IPv6 + 网关 + 路由 + 子网，安全列表默认只放行 22/ICMP）；**一键 IPv6 全链路**（VCN 开 IPv6 → 子网 /64 → ::/0 路由 → 出站规则 → 分配地址） |
| OCI 换 IP | 可指定**目标网段**，持续更换直到命中（遇 429 自动退避） |
| OCI 管理 | 安全列表查看/增删（「添加规则」支持单端口 / 批量端口）/放行指定端口（与实例「开放端口」同一接口，来源 0.0.0.0/0 需二次确认，不支持放行全部端口）；引导卷扩容与 VPU 调整；实例改名（可同步系统主机名，见下文）；终止时可**保留引导卷**；计算配额（A1/E2 等已用/可用）；本月 VNIC 流量 |
| 抢机 | 可用域 `auto` 轮换；**多租户批量抢机**（勾选多个账号各起一个任务） |
| 开机 | 创建（OCI/EC2/Lightsail/Azure）可**生成随机 root 密码**，加密留存，查看需面板密码；**开机脚本模板库**（BBR、Swap、关闭 OCI 防火墙等预设）；不硬编码任何默认密码，不 curl\|bash 第三方脚本 |
| AWS | **EC2 创建**（SSM 取最新官方镜像、gp3、IMDSv2、默认只放行 22 + 指定端口）；**Opt-in 区域激活**；**全区域实例扫描** |
| Azure | **创建 VM**（自动资源组/VNet/NSG 只放行 22/静态 IP，可选 IPv6）；**资源组**管理（删除需输入名称确认）；**Compute 配额** |
| DNS 联动 | 绑定 Cloudflare 记录，**换 IP / 加 IPv6 后自动更新 A/AAAA** |
| 监控 | **IP 不通检测**（面板 TCP 探测指定端口），连续 3 次失败告警，可选**自动换 IP** |
| 代理 | **每账号独立出口代理**（http/https/socks5），代理密码加密、不回显 |
| 安全 | **TOTP 二次验证**（防重放）；**API Token**（只读/完全，仅存哈希，不能触碰 2FA/备份/密码）；**审计日志**（写操作、来源、IP，保留 180 天） |
| 备份 | **加密备份/恢复**：数据库 + 密钥整包用口令（scrypt + Fernet）加密，下载与恢复都需面板密码 |
| 备份 | **OneDrive 定期备份**（1.6.0 build 21；build 23 自定义频率：每 N 小时 / 每天多个时间 / 每周多选 / 每月含月末 / Cron）：见下方「OneDrive 定期备份」 |
| 流量守护 | **推送并限速 + 端口流量明细**（1.6.0 build 22）：见下方「流量守护 agent」 |

## 实例改名 + 同步系统主机名（v1.5）
- 接口：`POST /api/accounts/{id}/instances/rename`，`{instance_id, region, kind, new_name, sync_hostname=true}`（`/oci/rename` 保留，同一逻辑）。OCI 改显示名；AWS EC2 改 `Name` 标签；Azure 的 VM 资源名不可修改，显示名写入 `tricloud-name` 标签（列表优先显示）；Lightsail 不支持改名。
- `sync_hostname`（默认开）：名称先规范化为合法主机名（小写，只留 a-z 0-9 -，最长 63，不以 - 开头/结尾；为空则跳过），再通过**云厂商自带的 Run Command** 在实例内执行一条固定命令（`hostnamectl` / `/etc/hostname` / `/etc/hosts` 的 127.0.1.1，并写 `/etc/cloud/cloud.cfg.d/99-tricloud-hostname.cfg` 设 `preserve_hostname: true`，防止 cloud-init 重启后改回）。不使用 SSH、不提供远程终端，用户输入不会直接拼进命令。
- 前提：**Azure** Linux VM 需处于运行状态（RunShellScript，Windows 跳过）；**OCI** 需开启 Oracle Cloud Agent 的「Compute Instance Run Command」插件、IAM 策略允许 `instance-agent-command-family`，且插件的 `ocarun` 用户需免密 sudo（`/etc/sudoers.d/101-oracle-cloud-agent-run-command`），同时会尽力把主 VNIC 的 hostname_label（内网 DNS 名）改成新名字，冲突只记录；**AWS EC2** 需被 SSM 托管（SSM Agent 在线 + 实例角色带 AmazonSSMManagedInstanceCore）。
- 尽力而为：改名本身照常成功，结果带 `hostname: {status: ok|pending|unsupported|failed, message, manual_cmd}`，失败时给出原因和可复制的手动命令；每次同步写一条审计（actor `hostname-sync`）。重新登录 SSH 后可见。
- 新建实例（OCI / EC2 / Azure）主机名默认等于规范化后的实例名：cloud-init 写 `hostname` / `fqdn` / `preserve_hostname: false`；OCI 子网开了 DNS 时设置 `hostname_label`（冲突时自动去掉重试）；Azure `computer_name` 同步。原有开机密码 / 开机脚本不受影响。

## OCI 系统版本下拉（v1.5）
- 创建 / 抢机 / 迁移表单的「系统版本」改为下拉，随「系统」联动：Canonical Ubuntu（最新 / 24.04 / 22.04 / 20.04）、Oracle Linux（最新 / 9 / 8）；「最新」= 空值，取最新镜像。CentOS 已移除（OCI 已无平台镜像）。
- `GET /api/accounts/{id}/oci/os-versions?shape=`：按规格列平台镜像可用版本 `{os: [versions…]}`（去重、降序，缓存 6 小时），前端先显示内置列表、拿到结果后替换；切换规格（A1 = aarch64、E2 = x86）会重新拉取。默认创建参数里保存的版本不在列表中时临时加为选项。

## v1.2 新增
- **免费额度护栏**：创建、改配置、扩容引导卷、调 VPU、抢机、跨云迁移之前，先估算会不会超出 OCI / AWS / Azure 的免费额度（A1 4C/24G、E2.1.Micro 2 台、200GB 块存储、非主区域；AWS 免费机型、750 小时、30GB EBS；Azure B1s/B2pts_v2/B2ats_v2、P6 磁盘）。可能超额时弹窗列出原因，确认后才继续；云 API 查询失败时不拦截。可在设置里关闭。
- **账号健康度**：每天 07:30 给每个账号打 0–100 分（凭证/封禁、被动停机、实例消失、非容量类任务失败、OCI A1 配额被下调或归零、AWS Credit 到期/余额、Azure 订阅状态）。分数下降 ≥15 或进入「危险」时推送 Telegram。只用免费只读接口。
- **跨云迁移 / 重建**：用同一开机脚本在另一个账号（可跨云）新建实例，等公网 IP 就绪后自动把 Cloudflare 记录切过去，可复制监控、停掉源实例。**不复制磁盘数据**。

## v1.3 新增
- **流量守护**：按实例设置每月出站上限（默认 = 免费额度：OCI 10TB、AWS/Azure 100GB），每 30 分钟读平台指标（免费），到预警比例推送 TG，到上限推送并可自动停机。网页侧栏「流量守护」、TG `/traffic`。指标有 5~15 分钟延迟，上限请留余量。
- ~~串口控制台~~：v1.5.0 已移除，需要时请直接使用云厂商控制台。
- TG 新命令：`/health`、`/traffic`。
- Android 1.3.0：同步免费额度护栏（409 二次确认）、账号健康度、跨云迁移、流量守护、护栏开关（串口控制台、Azure 启动日志与快照已在 1.5.0 移除）。

## v1.4 新增
- **任务实时日志**：每个任务都有追加式日志（抢机每次尝试、换 IP / 改配置 / 迁移 / 建网按步骤记录，带结果）。新接口 `GET /api/tasks/{id}?after=<日志id>`（状态 + 增量日志 + 结果）。网页右侧**任务抽屉**：提交任务后自动打开并跟踪，运行中每 2 秒刷新、自动滚到底部，可停止任务、删除记录，下方列出最近任务；手机上全屏显示。停止长任务时会在两次尝试之间的安全点退出。
- **账号**：**批量添加**（粘贴多段 JSON / 数组 / OCI config，私钥 PEM 直接贴在段后，逐条在线校验并返回每条结果，支持只检查格式）；**一键测活**（并发测试某云或全部账号，显示连通与耗时，结果记在账号上）；**云账号创建日期**与**存活天数**（OCI 自动读取租户创建时间，AWS/Azure 手动填写）。
- **Credit 与教育优惠**（账单页，三家云通用）：手动录入 Credit（名称、初始额度、起始 / 到期日，可增删改）；已用额度按账单估算（AWS 只读 Cost Explorer 缓存，**不新增任何 CE 调用点**；OCI/Azure 按每月账单累加，先到期的先抵扣），估不出时可手填；可设置 Credit 总额；Azure 教育优惠到期日（没填时按创建日期 + 12 个月估算并标明“估算”）。30 天内到期在总览提醒，并在 30 / 7 / 1 天各推送一次 TG。
- **流量守护增强**：新增**滚动窗口模式**（最近 N 小时，出向 / 入向 / 双向）；超限后可**关机 M 小时**，到时自动开机并推送 TG，自动开机失败只告警、不重试；规则可启用 / 停用；显示规则状态（正常 / 已触发关机 + 预计开机时间 / 自动开机失败），可取消待执行的自动开机。三家云都支持；旧规则保持月度模式不变。
- **换 IP**：网段参数支持 `!` 前缀表示排除（如 `129.146.0.0/16, !129.146.10.0/24`，可只写排除网段），OCI / AWS / Azure 都支持；**自动换 IP 每账号每天限次**（设置里可配，默认 3 次，v1.3 之前没有上限），显示今日已用次数；达到上限或失败只推送 TG。
- **Azure 订阅页**（只读）：订阅状态、类型 / offer（quotaId）、spending limit、区域策略等，以及教育优惠到期。
- **界面**：顶栏**账号快速切换器**（可搜索、按云分组，切换后停留在同类页面）；实例页桌面宽度可切换**卡片 / 表格视图**（表格行内放常用操作，其余在「更多」菜单，选择记在 localStorage，手机始终用卡片）；设置里**紧凑模式**。
- **Telegram**：`/tasks`（最近任务及状态）、`/credits`（Credit 余额与到期情况）。
- **Android 1.4.0**：任务日志查看（轮询，提交任务后自动打开）、一键测活、存活天数、Credit 与到期信息（可增删改）、Azure 订阅页、流量规则新字段（滚动窗口 / 方向 / 关机 M 小时 / 启停）、换 IP 排除网段与今日次数、自动换 IP 每日上限设置。
- 依赖：`azure-mgmt-resource` 固定在 `<25`（25 起 `SubscriptionClient` 拆到独立包，26 改了 `ResourceManagementClient` 的导入路径）。

## v1.5 新增（合并线上旧版）
- **移除串口控制台**：删除 WebSocket 终端、OCI/AWS/Azure 串口接口、xterm 与 Android 终端，去掉 paramiko 依赖。不提供 Web SSH 或远程控制台。
- **Telegram 内联按钮菜单**：`/start` → 云 → 账号 → 实例 → 操作（开机 / 关机 / 重启 / 换 IP / 开放端口 / 加删 IPv6 / 终止 / 刷新），每个操作都要确认，危险操作带警告；另有测活、最近任务、账单、Credit。只响应已配置的 chat_id，原有命令保留。
- **已删账号回收站**：删除账号时记录存活天数和估算花费（只读本地缓存，不调用云 API）；网页 `#/deleted`，`/api/recycle-bin`。原 AWS「回收站估算」改名为「闲置资源」。
- **代理用户名 / 密码分开填写**：密码加密保存，留空表示不改；兼容旧的 `user:pass@` 写法。
- **每云默认创建参数**：OCI / EC2 / Lightsail / Azure 创建表单可「保存为默认」。
- **OCI 安全组**：合并子网所有安全列表，批量端口（如 `80, 443, 8000-8100`），按规则内容删除。来源为 `0.0.0.0/0` 或 `::/0` 时需二次确认并警告；拒绝对公网放行全部端口。
- **实例操作「开放端口」（OCI / AWS / Azure）**：`POST /api/accounts/{id}/instances/{iid}/open-port`，参数 `{port, protocol: tcp|udp（默认 tcp）, region, confirm_public}`。端口可填单个或批量（如 `80, 443, 8000-8100`），来源固定 `0.0.0.0/0`。OCI 写入实例子网的安全列表；AWS 写入实例关联的全部安全组；Azure 写入网卡和子网上的 NSG（两处都有时两处都写），规则名唯一、优先级自动找空位。已存在的规则跳过，返回每个安全组 / 列表新增与跳过的条数。不带 `confirm_public` 返回 409（`detail.public_warning`），空端口或 1-65535 返回 400；不支持 Lightsail。入口：Web 实例卡片 / 表格「更多」菜单、OCI 安全列表弹窗的「放行指定端口」、Telegram 实例菜单（回复端口号后再确认）、Android 实例卡片。
- **AWS CloudFront**：缓存刷新（最多 100 条路径）、配置编辑、启用 / 停用、套餐、创建（价格等级 / 压缩 / 缓存模式）、删除（必须确认，启用中的先停用再删）。
- **账号编辑**：回显非敏感字段，敏感字段按需更新，保存前先测试凭证。OCI config 粘贴支持多 profile 和 PEM 识别。OCI 删除 IPv6 需确认。
- **重启续跑**：服务启动时，抢机任务重新排队并保留尝试次数；其他中断的任务标记为 `interrupted`。
- **迁移脚本** `tools/migrate_from_legacy.py`：只读打开旧库，`--dry-run` 只打印数量和字段映射（不打印凭证），拒绝写入非空的新库；旧凭证解密后按字段映射，用新密钥重新加密。
- **Android 1.5.0**：CloudFront 全套、OCI 安全组、实例「开放端口」（输入框 + 公网警告确认）、删除 IPv6、EC2 / Azure 创建、账号编辑与单账号测活、代理字段、批量添加、已删账号回收站、`interrupted` 状态。
- 文档：旧版调研文档已脱敏后放到 `docs/`。

## OneDrive 定期备份（1.6.0 build 21）
- 设备码登录 Microsoft Graph（`/consumers` 或 `/common`），scope 只有 `Files.ReadWrite.AppFolder offline_access`，只能读写 OneDrive「应用 / <应用名>」文件夹。`client_id` 由用户注册自己的公共客户端应用后填写（教程见 `docs/api-credentials.md` 第四节）。
- 备份内容：`tricloud.db`（SQLite backup API 一致快照）+ `fernet.key` + `meta.json` 打 zip，用备份密码 scrypt（N=2^15, r=8, p=1）派生密钥、AES-256-GCM 加密，文件 `tricloud-backup-YYYYMMDD-HHMMSS.tcod`；≤4MB 直接 PUT，更大用 upload session（3.125 MiB 分片）。
- 定时：每天 / 每周（星期几）+ HH:MM，按面板时区；保留最近 N 份（默认 30，只删自己生成的文件）；失败 TG 通知，1 小时后重试，每期最多 3 次；成功写审计 `onedrive-backup`。任务类型 `onedrive_backup`（面板级任务，account_id=0），任务抽屉可看日志。
- 计划（build 23）：`mode` = `hourly`（`every_hours` 1–24、`minute`、`start_hour`）/ `daily`（`times` 多个 HH:MM）/ `weekly`（`weekdays` 多选 0=周一 + `times`）/ `monthly`（`days` 1–31 + `last_day` 月末 + `times`，没有该日的月份跳过）/ `cron`（标准 5 段，自写解析器，支持 `* , - /`、数字、英文缩写、@daily 等宏，日/周按 Vixie cron 规则取或）。按面板时区墙上时间计算，DST 不重复不漏跑；两次至少间隔 30 分钟；`POST /api/onedrive/schedule/preview` 返回描述与接下来 3 次（不保存，不进审计）。旧配置 `freq/time/weekday` 读取时自动迁移（slot key 不变），status 仍返回这三个字段兼容旧版 App；旧版 App 原样带回时不会覆盖新计划。重试：周期 ≥4 小时 1 小时后重试，更短的周期按周期 1/4（≥10 分钟），每期最多 3 次，只在本期内。TG `/backup` 显示计划描述、下次与之后两次时间。
- 备份密码（build 22 起）：只要求不能为空、两次输入一致，不限长度和复杂度。绑定：填 client_id 保存后点蓝色「绑定 OneDrive」才会出现代码（未绑定时页面会提示）。
- 恢复：选一份 + 备份密码 + 二次确认；先在 `data/pre-restore-时间/` 存当前快照，校验完整性与密钥匹配后替换 db + key，保留当前机器的 OneDrive 绑定，所有会话作废；Docker 里随后退出进程由 restart 策略拉起（`TRICLOUD_RESTART_AFTER_RESTORE` 可覆盖）。
- 离线解密：`python -m tools.decrypt_backup 文件 [密码] 输出目录`（只依赖 cryptography）。
- API Token：只能 GET 状态 / 列表与 `POST /api/onedrive/backup`，其余（绑定、设置、恢复、解绑）403。TG：`/backup` 立即备份 + 状态，`/backup status` 只看状态。
- 接口：`GET /api/onedrive`、`POST /api/onedrive/config`、`POST /api/onedrive/bind`、`POST /api/onedrive/bind/poll`、`DELETE /api/onedrive/bind?confirm=true`（`pending_only=true` 取消待授权）、`POST /api/onedrive/backup`、`GET /api/onedrive/backups`、`POST /api/onedrive/restore`、`POST /api/onedrive/schedule/preview`（build 23）。

## 流量守护 agent：推送并限速 + 按端口 / 服务的流量明细（1.6.0 build 22）
- **推送并限速**：流量守护「到达上限后」新增第三种动作 `throttle`，限速默认 **1 Mbps**（0.1–10000，出站）。超限时面板把这条守护标记为「已限速」并推送 Telegram；滚动窗口回落到上限以下、或月度模式跨月（`release_due`，不查云指标）自动解除，也可手动「解除限速」（本期内不再自动限速）。agent 离线 / 未安装时 TG 文案注明「无法限速」；装过的 agent 超过 15 分钟没心跳推送一次「限速 agent 离线」，恢复心跳后重置。
- **agent**（`app/guard_agent/`，纯 bash，过 `bash -n` 与 shellcheck）：由用户自己在实例上用 root 运行安装命令（`curl -fsSL '<面板>/api/guard-agent/install.sh?token=<守护专属 token>' | sudo bash`），面板**不会**经 Run Command 或任何方式远程执行命令。安装 `/usr/local/bin/tricloud-guard`、`/etc/tricloud-guard/conf`（0600）、`tricloud-guard.service`（oneshot）+ `.timer`（每 5 分钟），没有常驻进程。限速用 `tc` HTB：主网卡（默认路由所在网卡，可 `IFACE=` 覆盖）出站 `1:20` 限速，SSH 端口（`sshd -T` / sshd_config，默认 22）的回包走不限速的 `1:10`。token 被重置 / 守护被删除（401/404）立即解除限速并删除计数规则；面板连不上保持现状，连续 24 小时连不上解除限速。子命令 `run | status | clear | uninstall`。
- **流量明细**（守护上的开关 `acct_enabled`，任何动作都能开，只统计也行）：同一个 agent 用**只计数**的规则统计——nftables 独立 table `inet tricloud_acct`（input / output / forward 三个 base chain，priority -160，规则只有 `counter`，没有 drop / accept / reject）；没有 nft 时退回 iptables / ip6tables `mangle` 表里的 `TRICLOUD_ACCT_IN / OUT / FWD` 计数链（规则不带 `-j`，回环用 RETURN 跳过）。按 `ss -lntup` 的监听端口（排除只监听回环的，最多 64 个）自动建计数规则，端口集合或网卡变了才重建（重建前先把旧计数收进待上报），并把端口映射到进程名（`sshd`、`x-ui`、`xray`…；Docker 发布端口映射为 `docker:容器名`，DNAT 到容器的流量在 forward 链按原始目的端口计）。非监听端口的流量 = 网卡总量 − 各端口之和，归为「**其他/出站连接**」（如本机主动访问外网、代理出站）。每 5 分钟把「上次成功上报以来的增量」随心跳 POST 给面板，上报失败留在本地下次补报。面板关闭流量明细 / 卸载时删除计数规则。
- **面板存储**：表 `guard_port_traffic`（守护 × 面板时区日期 × 协议 × 端口：进程名、入站字节、出站字节），每天清理 90 天前的记录；删除守护连带删除。
- **接口**：公开（凭守护专属 token，`X-TriCloud-Guard-Token` 或 `?token=`，只能读写本守护）`GET|POST /api/guard-agent/state`（`format=env` 返回 `throttle / rate_kbit / acct / interval`；POST 正文每行 `协议 端口 进程名 入字节 出字节`，≤64KB、≤400 行，格式不对的行丢弃）、`GET /api/guard-agent/install.sh?token=`、`GET /api/guard-agent/uninstall.sh`；需登录 `GET /api/traffic-guards/{gid}/agent`（安装 / 卸载命令 + agent 在线状态、最后心跳、是否已限速、网卡、SSH 端口、计数后端与端口数）、`POST /api/traffic-guards/{gid}/agent/reset`（重置 token）、`GET /api/traffic-guards/{gid}/ports?range=today|month&limit=`（按端口、按服务的 Top：入站 / 出站 / 合计 / 占比）。`PATCH /api/traffic-guards/{gid}` 新增 `acct_enabled`、`release_throttle`；`POST /api/traffic-guards` 新增 `action=throttle`、`throttle_mbps`、`acct_enabled`。agent token 用 Fernet 加密存库（面板要能再次显示安装命令），另存 sha256 用于查找，任何列表接口都不回传。
- **API Token**：`POST …/agent/reset` 返回 403；`GET …/agent` 只返回状态、不返回带 token 的安装命令；agent 每 5 分钟的心跳不写审计，下载安装脚本 / 重置 token 写审计。
- **界面**：Web 流量守护页与 OCI「流量」标签每条规则有「agent」「端口明细」按钮（agent 弹窗：在线状态与最后心跳、当前是否限速、可复制的安装 / 卸载 / 状态命令、重置 token、流量明细开关；端口明细：今日 / 本月、按端口 / 按服务、占比条）；首次选「推送并限速」或打开流量明细时保存后直接弹出安装命令。Android（Material 3）`GuardAgentActivity`、iOS（HIG）`GuardAgentPage` 同样内容，流量守护表单新增「推送并限速」、限速 Mbps、流量明细开关。
- **Telegram**：`/traffic` 显示「超限限速 / 🐢已限速」；新命令 `/ports 实例名`（本月按端口 Top 10 + 按服务 Top 5，不带参数列出已开流量明细的实例）。

## 从旧版迁移
```
python3 tools/migrate_from_legacy.py --legacy-db <旧 data>/tricloud.db --new-data <新 data> --dry-run
python3 tools/migrate_from_legacy.py --legacy-db <旧 data>/tricloud.db --new-data <新 data>
```
旧密钥依次从 `--legacy-key`、`FERNET_KEY`、旧库旁边的 `fernet.key` 读取。不迁移：会话、旧任务、面板密码与 TOTP、账单缓存。Telegram Bot 新旧两边只能同时运行一个，否则会出现 409 冲突。

## 更新日志

| 版本 | 内容 |
|---|---|
| 1.6.0（build 24） | 修复总览实例数只统计默认区域：按账号所有区域统计（AWS EC2 + Lightsail 全区域、OCI 订阅区域、Azure 整个订阅），显示实际有机器的区域，缓存 + 重新扫描，Web + Android + iOS |
| 1.6.0（build 23） | OneDrive 备份频率自定义：每 N 小时、每天多个时间点、每周多选星期、每月指定日期（含月末）、Cron 表达式，保存前预览接下来 3 次，旧设置自动迁移，Web + Android + iOS + TG |
| 1.6.0（build 22） | 流量守护「推送并限速」（实例自装 bash + tc agent，默认 1 Mbps，SSH 不限）+ 按端口 / 服务的流量明细（nftables / iptables 只计数，今日 / 本月 Top，保留 90 天，TG `/ports`）；OneDrive 绑定按钮更醒目、备份密码不再限制长度，Web + Android + iOS |
| 1.6.0（build 21） | OneDrive 定期备份（设备码绑定、每天 / 每周、保留 N 份、立即备份、列表与恢复、解绑、TG `/backup`、离线解密工具），Web + Android + iOS |
| 1.6.0（build 17） | 首页 AWS 实例数包含 Lightsail（显示为「N 台（运行 X）· EC2 a · Lightsail b」） |
| 1.6.0（build 16） | 移除第四家可选云厂商（彻底删除其后端、Web、演示、Android、iOS 代码），只保留 OCI / AWS / Azure；`/api/meta` 只返回三家云 |
| 1.5.0 | 合并线上旧版：TG 内联按钮、已删账号回收站、代理账密分填、默认创建参数、OCI 安全组、CloudFront 全套、账号编辑、重启续跑、迁移脚本、Android 1.5.0；**移除串口控制台** |
| 1.4.0 | 任务实时日志与任务抽屉、批量添加 / 一键测活 / 存活天数、Credit 与教育优惠、流量守护滚动窗口 + 关机 M 小时自动开机、换 IP 排除网段 + 自动换 IP 每日限次、Azure 订阅页、账号切换器 / 表格视图 / 紧凑模式、TG `/tasks` `/credits`、Android 1.4.0；修复同步接口停止任务时没有事件循环导致的 500 |
| 1.3.0 | 流量守护（月度）、串口控制台（1.5.0 已移除）、TG `/health` `/traffic` |
| 1.2.0 | 免费额度护栏、账号健康度、跨云迁移（当时的快照功能已在 1.5.0 移除） |
| 1.1.x | 融合各家面板功能；Material Design 3 界面、手机竖屏适配 |

