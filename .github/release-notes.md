### 1.6.0 build 20 更新内容

- **新功能：AWS「新号 Credit」**（Web / Android / iOS 的 AWS 账号新增标签）：显示新免费计划类型、剩余 credit、到期时间，以及 EC2 / Budgets / Lambda / RDS / Bedrock 5 个官方活动的状态、奖励和完成时间（需要 IAM 只读权限 `freetier:GetAccountPlanState`、`freetier:ListAccountActivities`、`freetier:GetAccountActivity`）。
- **一键完成活动**：每个未完成活动一个按钮，后台任务执行并显示进度和日志，以最低成本完成后自动删除资源（EC2、RDS 只运行几分钟，费用极小，从 credit 中扣；预算免费、默认保留）；也可「一键全部完成」（两次确认）。所有资源打标签 `tricloud-credit=1`，另有「清理残留」兜底。
- **注意**：AWS 没有公开说明用 API 完成的操作是否计入活动，执行后显示「已执行，等待 AWS 识别」，奖励以 AWS 返回的活动状态为准（可能要几分钟到几小时）；Bedrock 官方要求在 playground 使用，API 调用不一定计入。
- 版本：Android versionCode 20 / iOS build 20（版本号仍 1.6.0），需同时更新面板到最新版。

**Android**：下载 `TriCloud-*.apk` 直接安装（需允许安装未知来源应用），可覆盖升级。

**Windows**：`TriCloud-*-windows-setup.exe` 是安装版，`TriCloud-*-windows-portable.exe` 是免安装版，双击即可运行（需要 WebView2，Windows 10/11 自带）。

**iOS**：`TriCloud-*-unsigned.ipa` 是未签名包，用轻松签 / 爱思助手 / Sideloadly / AltStore / TrollStore 等工具自签安装。

首次打开 App 填你自己的面板地址。面板一键安装见 README。

> 本项目代码全部由 AI 生成，请自行评估风险，作者不对任何账号凭证泄露、账号被盗或由此产生的损失承担责任。
