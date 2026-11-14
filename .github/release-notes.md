### 1.6.11 build 45 更新内容

- **Android 侧边栏折叠真正顺滑了**：上一版减少了刷新次数，但抽屉组件每次仍会把整个列表连同背后的页面重新排版一遍，所以还有一下顿挫。这版把抽屉换成自己画的列表，折叠时只收起 / 展开那一组，带过渡动画，背后页面不再跟着重排。iOS 与网页没有这个问题，iOS 版本号按惯例同步。
- 版本：Android versionCode 45 / iOS build 45（versionName 1.6.11）。

**Android**：下载 `TriCloud-*.apk` 直接安装（需允许安装未知来源应用），可覆盖升级。

**Windows**：`TriCloud-*-windows-setup.exe` 是安装版，`TriCloud-*-windows-portable.exe` 是免安装版，双击即可运行（需要 WebView2，Windows 10/11 自带）。

**iOS**：`TriCloud-*-unsigned.ipa` 是未签名包，用轻松签 / 爱思助手 / Sideloadly / AltStore / TrollStore 等工具自签安装。

首次打开 App 填你自己的面板地址。面板一键安装见 README。

> 本项目代码全部由 AI 生成，请自行评估风险，作者不对任何账号凭证泄露、账号被盗或由此产生的损失承担责任。
