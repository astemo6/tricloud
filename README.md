# TriCloud — OCI / AWS / Azure 三合一 VPS 管理面板

自托管、凭证自己掌控的多云面板。凭证经 Fernet 加密存在本机 SQLite，不经过任何第三方服务器。提供 Web、Telegram Bot、Android 和 iOS 原生 App。

> **免责声明**：本项目的全部代码均由 AI 生成，作者未逐行审计。请自行评估风险后使用，作者不对任何云账号凭证泄露、账号被盗、资源被滥用或由此产生的费用和损失承担责任。

## 主要功能

- **账号**：多账号管理，粘贴随手复制的内容自动识别（控制台、环境变量、AWS CSV、Azure 门户、OCI config），批量添加、一键测活、存活天数、每账号独立代理
- **实例**：启停 / 重启 / 终止、换 IP（可指定或排除网段）、IPv6、改配置、改名同步主机名、开放端口
- **OCI**：创建、自动抢机（多租户）、安全组、存储与对象存储、配额 / 网络（底部「高级」里有区域订阅，不可撤销）、流量
- **AWS**：EC2、Lightsail、CloudFront、区域激活与全区域扫描、配额、闲置资源
- **Azure**：创建 VM、资源组、配额、Foundry、订阅信息
- **成本**：三家账单、Credit 与教育优惠到期提醒、免费额度护栏与免费体检（OCI A1：免费号 2C/12G，付费号 4C/24G）
- **运维**：流量守护（超限自动关机 / 实例自装 agent 限速 + 按端口/服务的流量明细）、IP 连通监控与自动换 IP、DNS 联动（Cloudflare）、开机脚本模板、随机开机密码、跨云迁移、任务实时日志、账号健康度
- **安全**：TOTP 二次验证、API Token、审计日志、加密备份 / 恢复

不提供 Web SSH、串口控制台或远程终端。功能详解见 [docs/FEATURES.md](docs/FEATURES.md)，更新日志见 [CHANGELOG.md](CHANGELOG.md)。

## 部署（Docker 一键安装）

在新 VPS 上用 root 执行一行即可：自动装好 curl、Docker 和 compose，下载代码、生成随机初始密码、构建并启动，最后打印访问地址和密码。

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/astemo6/tricloud/master/install.sh)
```

仓库为私有时，先 `export GH_TOKEN=<有该仓库读权限的 Token>`，再执行：

```bash
bash <(curl -fsSL -H "Authorization: Bearer $GH_TOKEN" https://raw.githubusercontent.com/astemo6/tricloud/master/install.sh)
```

常用参数（加在 `bash` 前）：`PORT=8080` 换端口（默认 8000）；`BIND=127.0.0.1` 只监听本机，配合反代；`CN=1` 国内机器用阿里云源装 Docker；`DIR=/path` 改安装目录（默认 `/opt/docker/tricloud`）。再次运行同一条命令就是升级：保留 `.env` 和 `data/`，升级前自动备份。

手动部署：放入代码后 `cp .env.example .env`，再 `docker compose up -d --build`。

一键脚本默认对外监听，手动部署默认只监听 `127.0.0.1:8000`。正式使用请用 Nginx / Caddy / Cloudflare Tunnel 反代并启用 HTTPS，再在 `.env` 设 `COOKIE_SECURE=true`、`TRUST_PROXY=true`。

数据都在 `./data`：`tricloud.db` 和 `fernet.key`，**两者必须一起备份，丢了密钥凭证就无法解密**。建议在面板前加 Cloudflare Access，并给每个云账号用最小权限凭证。

从旧版迁移：`python3 tools/migrate_from_legacy.py --legacy-db <旧 data>/tricloud.db --new-data <新 data> [--dry-run]`

## 凭证与最小权限

**OCI**：控制台右上角头像 → User settings（进入 Identity & Security → My profile）→ Tokens and keys 标签 → Add API key，填入 user / tenancy OCID、指纹、区域与私钥 PEM。账单需要 Usage 读权限（租户管理员默认具备）。

**AWS**（IAM 用户策略示例）：

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["ec2:Describe*", "ec2:StartInstances", "ec2:StopInstances", "ec2:RebootInstances",
               "ec2:TerminateInstances", "ec2:ListSnapshotsInRecycleBin", "ec2:AllocateAddress", "ec2:AssociateAddress", "ec2:ReleaseAddress",
               "ec2:RunInstances", "ec2:CreateTags", "ec2:CreateSecurityGroup", "ec2:AuthorizeSecurityGroupIngress", "ssm:GetParameter",
               "account:ListRegions", "account:EnableRegion",
               "lightsail:*", "cloudfront:*Distribution*", "servicequotas:Get*", "ce:GetCostAndUsage",
               "sts:GetCallerIdentity"],
    "Resource": "*"
  }]
}
```

**Azure**：`az ad sp create-for-rbac --name tricloud --role "Virtual Machine Contributor" --scopes /subscriptions/<SUB_ID>`，换 IP / 创建 VM / 资源组管理需在订阅上授予 Contributor（或 Virtual Machine Contributor + Network Contributor + 资源组写权限），账单需 Cost Management Reader。学生订阅部分账单 API 可能不可用，面板会显示错误而不影响其他功能。

> 三家云凭证的图文获取步骤（含 Azure Cloud Shell 一键命令）见 [docs/api-credentials.md](docs/api-credentials.md)。

> AWS 只有 Cost Explorer 按次收费（$0.01/次）。面板只在每月 15 号和月末自动查询，其余时间读缓存，正常每账号每月 ≤ $0.04。

## Telegram

@BotFather 创建 Bot，在面板「设置 → Telegram」填 Token 和 Chat ID。命令：`/start` 按钮菜单管理实例，`/bill`、`/tasks`、`/credits`、`/health`、`/traffic`、`/ports 实例名`、`/backup`。长轮询，无需 Webhook。

## App

直接下载：[Releases](https://github.com/astemo6/tricloud/releases/latest) 里有 Android APK、Windows 客户端（安装版和免安装版 exe）和 iOS 未签名 IPA。首次打开填你自己的面板地址。

自行构建：

- **Android**（Java，Material 3）：`cd android && ./gradlew assembleRelease`（JDK 17 + Android SDK 34，签名配置见 `keystore.properties.example`）。
- **Windows**（Tauri 2 + WebView2）：推送 `desktop/` 改动或手动运行 Actions「Windows EXE」，自动发布到 Releases。本地：`cd desktop && npx @tauri-apps/cli@2 icon ../ios/TriCloud/Assets.xcassets/AppIcon.appiconset/icon-1024.png && npx @tauri-apps/cli@2 build`。
- **iOS**（SwiftUI，iOS 15+）：推送 `ios/` 改动或手动运行 Actions「iOS IPA」，在 Releases 生成未签名 IPA，用 Sideloadly / AltStore / TrollStore 等自签安装。本地：`cd ios && xcodegen generate`。

首次打开填写面板地址和密码（开了 2FA 再填验证码），只允许 HTTPS。

## 本地开发

```bash
pip install -r requirements.txt
TRICLOUD_DATA=./data PANEL_PASSWORD=devpassword123 uvicorn app.main:app --reload
```

## License

MIT
