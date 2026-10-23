### 1.6.1 build 29 更新内容

- **改名不再勾选同步主机名**：实例改名对话框去掉「同步修改系统主机名」勾选——面板只修改云端显示名，不进系统执行命令（后端已关停 OCI Run Command / Azure Run Command / AWS SSM 自动同步链）。保存后会给出修改系统主机名的命令，复制后 SSH 登录手动执行即可。
- 版本：Android versionCode 29 / iOS build 29（versionName 1.6.1），需同时更新面板到最新版。

**Android**：下载 `TriCloud-*.apk` 直接安装（需允许安装未知来源应用），可覆盖升级。

**Windows**：`TriCloud-*-windows-setup.exe` 是安装版，`TriCloud-*-windows-portable.exe` 是免安装版，双击即可运行（需要 WebView2，Windows 10/11 自带）。

**iOS**：`TriCloud-*-unsigned.ipa` 是未签名包，用轻松签 / 爱思助手 / Sideloadly / AltStore / TrollStore 等工具自签安装。

首次打开 App 填你自己的面板地址。面板一键安装见 README。

> 本项目代码全部由 AI 生成，请自行评估风险，作者不对任何账号凭证泄露、账号被盗或由此产生的损失承担责任。
