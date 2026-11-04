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
