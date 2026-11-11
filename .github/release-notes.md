### 1.6.7 build 41 更新内容

- **侧边栏分组可以折叠了**（网页 / Android / iOS 全平台）：点厂商名（Oracle Cloud / AWS / Azure / SolusVM / VirtFusion）或「管理」标题就能收起这一组，再点展开，标题右侧有 ▾ / ▸ 指示；折叠状态会记住，重启 App 不用重新折。账号多的时候侧边栏清爽多了。
- **iOS 用户一次拿两版更新**：上一版的绿云管理（SolusVM / VirtFusion）没有单独发 iOS 包，本版连同折叠功能一起发布。
- 版本：Android versionCode 41 / iOS build 41（versionName 1.6.7），需同时更新面板到最新版。

### 1.6.6 build 40 更新内容

- **App 补齐绿云管理**（Android / iOS）：SolusVM / VirtFusion 两类面板型厂商现在 App 里也能完整用了——添加账号（粘贴识别 / 批量添加都行）、实例列表、开关机 / 重启、流量（卡片直接显示已用 / 总额）、流量守护、监控，VirtFusion 还能改名；不支持的操作（换 IP、开放端口、迁移、重装等）不再显示。此前 App 里绿云账号打开是 Azure 的页面、整页不可用，本版修好。
- **修了一个三端都有的小毛病**：绿云账号的「账号类型」此前被误显示成「AWS 账号」，已改。
- 版本：Android versionCode 40 / iOS build 40（versionName 1.6.6），需同时更新面板到最新版。

### 1.6.5 build 39 更新内容

- **修了几个 bug**（后端/网页端，App 升级后配合最新面板生效）：账号编辑点开就报错 500 修好了（SolusVM/VirtFusion 账号）；cft 套餐显示修好了（刚订阅完不再误显「按量付费」）；VirtFusion VNC 控制台按要求去掉了。
- **新增 SolusVM / VirtFusion 两类面板型云厂商**（绿云等走这两套面板）：账号、实例列表、开关机、流量、改名都已接入。
- 版本：Android versionCode 39 / iOS build 39（versionName 1.6.5），需同时更新面板到最新版。

### 1.6.4 build 38 更新内容

- **App 功能对齐网页版**（Android / iOS）：补齐近两日网页版新增能力——EC2 创建机型带规格与官方月价（最低价标「最便宜」）+ 可手动输入其他机型、系统盘默认 8G；Lightsail 创建改官网逻辑（先选套餐类型 + 网络，规格只列匹配的）；开放端口支持 ICMP / ICMPv6 / 全部协议；开机脚本模板改为多选（按序拼接执行）；脚本预设补「更新环境」「安装 Fail2ban」。
- **安全页补齐**（Android / iOS）：开通二次验证可扫码绑定（后端新增 qr_png）；新增「已登录设备」（设备名 / IP / 登录与最后活跃时间，可逐台退出或一键退出其他设备）与「登录记录」；审计日志里登录动作标「🔐 登录」。
- 版本：Android versionCode 38 / iOS build 38（versionName 1.6.4），需同时更新面板到最新版。

### 1.6.3 build 37 更新内容

- **账号手动排序**（Android / iOS）：云账号列表支持手动上移/下移调整账号排列顺序并保存（POST /accounts/reorder）。
- **OCI 系统版本动态下拉**（Android / iOS）：选规格后按规格动态获取平台镜像系统与版本列表，无法连接时回退内置列表。
- **CloudFront 缓存刷新按钮开关可在 App 内改**（Android / iOS）：设置页新增「CloudFront 缓存刷新按钮」开关，可直接在 App 内开启/关闭，关闭时分发列表隐藏刷新按钮防误点。
- **Android 保存为默认创建参数**（Android）：创建实例时支持勾选「把本次参数保存为默认创建参数」（不含名称、密码、脚本），补齐与 iOS 一致能力。
- **安全列表（实例级）**（Android / iOS）：OCI 实例操作菜单新增「安全列表」入口，支持查看实例所在子网安全列表规则并支持单个规则删除确认。
- **账号快速切换器**（Android / iOS）：账号详情页新增「切换账号」入口，支持搜索与按云厂商分组快速切换，选中后直接停留在账号详情页换为新账号。
- 版本：Android versionCode 37 / iOS build 37（versionName 1.6.3），需同时更新面板到最新版。

### 1.6.2 build 36 更新内容

- **显示版本升至 1.6.2**：功能内容与 build 35 完全一致，本次仅升版本号（应用户要求：版本号要动起来）；新建 Release v1.6.2，原 v1.6.1 保留不动。
- 版本：Android versionCode 36 / iOS build 36（versionName 1.6.2），需同时更新面板到最新版。

### 1.6.1 build 35 更新内容

- **分发卡片改显备注**（Android / iOS，与网页版一致）：CloudFront 分发卡片标题改显备注（无备注时回退显示分发 ID），分发 ID 移到下方小字（仅当有备注时显示），与网页版保持一致。
- 版本：Android versionCode 35 / iOS build 35（versionName 1.6.1），需同时更新面板到最新版。

### 1.6.1 build 34 更新内容

- **分发域名一键复制**（Android / iOS，与网页版一致）：CloudFront 分发卡片新增「复制」按钮，点一下把分发域名（如 dxxxx.cloudfront.net）复制到剪贴板，按钮短暂显示「已复制」后自动恢复。
- 版本：Android versionCode 34 / iOS build 34（versionName 1.6.1），需同时更新面板到最新版。

### 1.6.1 build 33 更新内容

- **分发流量多一行「近30天」总量**（Android / iOS，与网页版一致）：CloudFront 分发卡片在「已用流量」（本订阅周期已用 / 额度）下方再显示一行近 30 天总流量（下行 + 上行），方便看节点实际跑了多少流量；周期口径不变，仍用于看套餐额度。
- 版本：Android versionCode 33 / iOS build 33（versionName 1.6.1），需同时更新面板到最新版。

### 1.6.1 build 32 更新内容

- **账号列表显示「权限被拒」**（Android / iOS，与网页版一致）：只授权了账单 + CloudFront 等部分权限的账号（如 AWS 精简策略账号）没有实例查询权限，机器扫描会被权限拒绝。这类账号在账号列表的副标题现在直接显示「权限被拒」，不再和「无机器」「还没扫描过」混淆，一眼能看出是权限问题而不是没有机器。
- 版本：Android versionCode 32 / iOS build 32（versionName 1.6.1），需同时更新面板到最新版。

### 1.6.1 build 31 更新内容

- **App 功能补齐**（Android / iOS）：CloudFront 新建 / 编辑分发补齐网页版字段——HTTP / HTTPS 回源端口分开设置、新建时可选包月套餐、源站 IP 类型（IPv6 回源）、WebSocket 节点模式（编辑只能开不能关）；分发列表显示本周期已用流量（套餐分发显示已用 / 额度，含上下行拆分）；AWS 账单页显示本月手动刷新已用 / 上限并可直接增加次数；App 里的「缓存刷新」按钮跟随网页版设置开关（默认隐藏，防误点）。
- 版本：Android versionCode 31 / iOS build 31（versionName 1.6.1），需同时更新面板到最新版。

### 1.6.1 build 30 更新内容

- **OCI 一键切换受限 API**（防盗号）：云账号页 OCI 账号点「受限 API」，经 Telegram 验证码确认后，面板用当前全权限 Key 自动创建只能管理实例 / 存储 / 网络 / 对象存储、只读账单的受限用户和新 Key，自检通过后替换面板保存的 Key。**OCI 云端原 API Key 不会被删除或撤销，请自己保管**；切换后面板不能管理 IAM / 身份域。失败自动回滚。需要先在设置里绑定 Telegram。
- 版本：Android versionCode 30 / iOS build 30（versionName 1.6.1），需同时更新面板到最新版。

### 1.6.1 build 29 更新内容

- **改名不再勾选同步主机名**：实例改名对话框去掉「同步修改系统主机名」勾选——面板只修改云端显示名，不进系统执行命令（后端已关停 OCI Run Command / Azure Run Command / AWS SSM 自动同步链）。保存后会给出修改系统主机名的命令，复制后 SSH 登录手动执行即可。
- 版本：Android versionCode 29 / iOS build 29（versionName 1.6.1），需同时更新面板到最新版。

**Android**：下载 `TriCloud-*.apk` 直接安装（需允许安装未知来源应用），可覆盖升级。

**Windows**：`TriCloud-*-windows-setup.exe` 是安装版，`TriCloud-*-windows-portable.exe` 是免安装版，双击即可运行（需要 WebView2，Windows 10/11 自带）。

**iOS**：`TriCloud-*-unsigned.ipa` 是未签名包，用轻松签 / 爱思助手 / Sideloadly / AltStore / TrollStore 等工具自签安装。

首次打开 App 填你自己的面板地址。面板一键安装见 README。

> 本项目代码全部由 AI 生成，请自行评估风险，作者不对任何账号凭证泄露、账号被盗或由此产生的损失承担责任。
