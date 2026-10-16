### 1.6.0 build 19 更新内容

- **App 补齐 Web 已有的功能**：OCI 对象存储「一键生成保号账单」（仅 PAYG，先检测已有存储，显示还差多少 GB / 已满足，支持进度、续传、删除）；Bucket 列表显示大小 / 对象数 / 存储层；区域显示城市名（如 `ap-northeast-1 · 东京`）；OCI 安全组按子网选择，实例另挂 NSG 时只读提示；审计日志一键清空；A1 免费额度按账号类型显示（免费号 2 OCPU / 12 GB，PAYG 4 OCPU / 24 GB）。
- **新功能：OCI 子网改名**（可同时改 VCN 名称）：Web / Android / iOS 安全组页「改名」，只改显示名称，不影响实例、IP 和安全规则。
- **修复：Lightsail 区域**：Lightsail 页只列 Lightsail 支持的区域（台北 `ap-east-2` 等不再出现），已保存的区域不支持时自动切换并提示；后端遇到不支持的区域给出明确提示，不再报 EndpointConnectionError。
- 版本：Android versionCode 19 / iOS build 19（版本号仍 1.6.0），需同时更新面板到最新版。

**Android**：下载 `TriCloud-*.apk` 直接安装（需允许安装未知来源应用），可覆盖升级。

**Windows**：`TriCloud-*-windows-setup.exe` 是安装版，`TriCloud-*-windows-portable.exe` 是免安装版，双击即可运行（需要 WebView2，Windows 10/11 自带）。

**iOS**：`TriCloud-*-unsigned.ipa` 是未签名包，用轻松签 / 爱思助手 / Sideloadly / AltStore / TrollStore 等工具自签安装。

首次打开 App 填你自己的面板地址。面板一键安装见 README。

> 本项目代码全部由 AI 生成，请自行评估风险，作者不对任何账号凭证泄露、账号被盗或由此产生的损失承担责任。
