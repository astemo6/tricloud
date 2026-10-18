### 1.6.0 build 25 更新内容

- **修复：账号列表的区域显示成默认区域**。以前 AWS 账号固定显示「us-east-1 · 弗吉尼亚北部」，机器在东京也一样。现在 Web / Android / iOS 的账号列表显示**实际有机器的区域**（如「ap-northeast-1 · 东京」，多个区域显示「东京 等 2 个区域」）；没有机器时显示「无机器 · 默认 …」，还没扫描过时注明「（默认区域）」。OCI 显示有实例的区域，Azure 显示 VM 所在区域。
- 打开账号时默认选中机器最多的区域，不再停在空的默认区域；手动选过的区域仍然优先。
- 区域信息来自总览的全区域扫描（有缓存），账号列表直接读面板保存的记录，不会因此变慢；没有记录的账号在后台逐个补查。
- 版本：Android versionCode 25 / iOS build 25（版本号仍 1.6.0），需同时更新面板到最新版。

**Android**：下载 `TriCloud-*.apk` 直接安装（需允许安装未知来源应用），可覆盖升级。

**Windows**：`TriCloud-*-windows-setup.exe` 是安装版，`TriCloud-*-windows-portable.exe` 是免安装版，双击即可运行（需要 WebView2，Windows 10/11 自带）。

**iOS**：`TriCloud-*-unsigned.ipa` 是未签名包，用轻松签 / 爱思助手 / Sideloadly / AltStore / TrollStore 等工具自签安装。

首次打开 App 填你自己的面板地址。面板一键安装见 README。

> 本项目代码全部由 AI 生成，请自行评估风险，作者不对任何账号凭证泄露、账号被盗或由此产生的损失承担责任。
