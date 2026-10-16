### 1.6.0 build 23 更新内容

- **新功能：OneDrive 备份频率自定义**：除每天 / 每周外，现在可以选「每 N 小时」（可设第几分钟和起始小时）、「每天多个时间点」、「每周多选星期 + 多个时间点」、「每月指定日期（可选月末）」，以及高级的 Cron 表达式（分 时 日 月 周）。
- 修改计划时会实时显示「接下来 3 次」备份时间，设置不合法（如 Cron 写错、两次间隔不到 30 分钟、2 月 30 日）会直接提示原因。
- 原来的每天 / 每周设置升级后自动保留，下次备份时间不变；Telegram `/backup` 显示新的计划描述和下次时间。
- 短周期（每 1–3 小时）备份失败时在本期内更快重试，不会拖到下一期。
- 版本：Android versionCode 23 / iOS build 23（版本号仍 1.6.0），需同时更新面板到最新版。

**Android**：下载 `TriCloud-*.apk` 直接安装（需允许安装未知来源应用），可覆盖升级。

**Windows**：`TriCloud-*-windows-setup.exe` 是安装版，`TriCloud-*-windows-portable.exe` 是免安装版，双击即可运行（需要 WebView2，Windows 10/11 自带）。

**iOS**：`TriCloud-*-unsigned.ipa` 是未签名包，用轻松签 / 爱思助手 / Sideloadly / AltStore / TrollStore 等工具自签安装。

首次打开 App 填你自己的面板地址。面板一键安装见 README。

> 本项目代码全部由 AI 生成，请自行评估风险，作者不对任何账号凭证泄露、账号被盗或由此产生的损失承担责任。
