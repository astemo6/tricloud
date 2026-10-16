### 1.6.0 build 22 更新内容

- **新功能：流量守护「推送并限速」**：到达上限后可选「推送并限速」（默认 1 Mbps，可改），由你自己在实例上运行面板给出的安装命令装一个轻量 agent（bash 脚本 + systemd timer，每 5 分钟检查一次），超限时出站限速、SSH 端口不限，回落或下月自动解除，也可手动解除；agent 离线时 Telegram 提示「无法限速」。面板不会远程在实例上执行任何命令。
- **新功能：按端口 / 服务的流量明细**：同一个 agent 用只计数、不拦截的 nftables（或 iptables）规则统计每个监听端口的入站 / 出站流量，自动识别进程名（sshd、x-ui、xray…），非监听端口的流量归为「其他/出站连接」。在流量守护的「agent / 明细」里看今日 / 本月按端口和按服务的 Top 与占比；Telegram 新增 `/ports 实例名`。数据保留 90 天。
- 每条守护有自己的 agent token：可复制安装 / 卸载命令、看 agent 在线状态与最后心跳、重置 token。
- OneDrive：未绑定时「绑定 OneDrive」改为醒目的蓝色按钮，保存 client_id 后会提示点它获取代码；备份密码不再限制长度和复杂度（不能为空、两次一致即可）。
- 版本：Android versionCode 22 / iOS build 22（版本号仍 1.6.0），需同时更新面板到最新版。

**Android**：下载 `TriCloud-*.apk` 直接安装（需允许安装未知来源应用），可覆盖升级。

**Windows**：`TriCloud-*-windows-setup.exe` 是安装版，`TriCloud-*-windows-portable.exe` 是免安装版，双击即可运行（需要 WebView2，Windows 10/11 自带）。

**iOS**：`TriCloud-*-unsigned.ipa` 是未签名包，用轻松签 / 爱思助手 / Sideloadly / AltStore / TrollStore 等工具自签安装。

首次打开 App 填你自己的面板地址。面板一键安装见 README。

> 本项目代码全部由 AI 生成，请自行评估风险，作者不对任何账号凭证泄露、账号被盗或由此产生的损失承担责任。
