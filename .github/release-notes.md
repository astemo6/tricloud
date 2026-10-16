### 1.6.0 build 21 更新内容

- **新功能：OneDrive 定期备份**（Web 设置 → OneDrive 备份 / 侧栏，Android 与 iOS 在「更多 → OneDrive 备份」和设置页）：用你自己注册的 Azure 应用（公共客户端，填 client_id）通过设备码登录 Microsoft（打开 microsoft.com/devicelogin 输入代码），只申请 `Files.ReadWrite.AppFolder` + `offline_access`，只能读写 OneDrive「应用」下这一个文件夹。
- 备份内容：数据库一致快照 + 加密密钥，用你设置的备份密码（scrypt + AES-256-GCM）加密后上传，文件名带时间戳；每天 / 每周定时（时间按面板时区），保留最近 N 份（默认 30），也可「立即备份」；失败 Telegram 通知并 1 小时后重试（每期最多 3 次），成功写审计。Telegram 新增 `/backup`（立即备份 + 状态）。
- 恢复：备份列表选一份 → 输入备份密码 → 二次确认；恢复前自动在 data/ 保存当前数据，替换后面板自动重启，所有设备重新登录。新装机：装好 → 登录 → 绑定同一个 OneDrive → 恢复。可解绑（只删本机授权，网盘上的备份保留）。离线解密：`python -m tools.decrypt_backup 文件 输出目录`。
- 安全：refresh token 和备份密码用面板 Fernet 密钥加密存库（定时备份需要无人值守）；API Token 只能看状态 / 列表和立即备份，绑定、设置、恢复、解绑返回 403。Azure 应用注册教程见 `docs/api-credentials.md` 第四节。
- 版本：Android versionCode 21 / iOS build 21（版本号仍 1.6.0），需同时更新面板到最新版。

**Android**：下载 `TriCloud-*.apk` 直接安装（需允许安装未知来源应用），可覆盖升级。

**Windows**：`TriCloud-*-windows-setup.exe` 是安装版，`TriCloud-*-windows-portable.exe` 是免安装版，双击即可运行（需要 WebView2，Windows 10/11 自带）。

**iOS**：`TriCloud-*-unsigned.ipa` 是未签名包，用轻松签 / 爱思助手 / Sideloadly / AltStore / TrollStore 等工具自签安装。

首次打开 App 填你自己的面板地址。面板一键安装见 README。

> 本项目代码全部由 AI 生成，请自行评估风险，作者不对任何账号凭证泄露、账号被盗或由此产生的损失承担责任。
