### 1.6.0 build 24 更新内容

- **修复：总览实例数只统计了账号默认区域**。以前 AWS 账号卡片固定查 us-east-1（弗吉尼亚北部），机器在东京等其他区域时显示「0 台」。现在按账号**所有已启用区域**统计 EC2 + Lightsail，卡片区域显示实际有机器的区域（1 个区域显示「ap-northeast-1 · 东京」，多个显示「东京 等 2 个区域」并列出分布），没有机器时才显示默认区域。
- OCI 卡片统计所有已订阅区域；Azure 卡片统计整个订阅（一次请求，不再逐台查网卡），并显示 VM 所在区域，加载更快。
- 结果有缓存：全区域扫描 30 分钟一次，期间刷新只重查已知有机器的区域；总览新增「↻ 重新扫描区域」立即全量扫描。IAM 没有 DescribeRegions 权限的 AWS 账号也能扫描（自动改用区域表，跳过未启用的区域）。「区域扫描」页与总览共用同一份结果。
- 安全修复：备份恢复失败自动回滚；反代头只信任本机 127.0.0.1，防伪造来源 IP（经反代部署请按 README 设 TRUST_PROXY=true）；服务器内部错误不再把异常原文返回给浏览器（返回 request_id，详情看日志）。
- 版本：Android versionCode 24 / iOS build 24（版本号仍 1.6.0），需同时更新面板到最新版。

**Android**：下载 `TriCloud-*.apk` 直接安装（需允许安装未知来源应用），可覆盖升级。

**Windows**：`TriCloud-*-windows-setup.exe` 是安装版，`TriCloud-*-windows-portable.exe` 是免安装版，双击即可运行（需要 WebView2，Windows 10/11 自带）。

**iOS**：`TriCloud-*-unsigned.ipa` 是未签名包，用轻松签 / 爱思助手 / Sideloadly / AltStore / TrollStore 等工具自签安装。

首次打开 App 填你自己的面板地址。面板一键安装见 README。

> 本项目代码全部由 AI 生成，请自行评估风险，作者不对任何账号凭证泄露、账号被盗或由此产生的损失承担责任。
