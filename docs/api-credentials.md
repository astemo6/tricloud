# 三平台 API 凭证获取指南

TriCloud 面板通过各云官方 API 管理资源，需要先在对应云平台创建 API 凭证，再填到面板「管理账号 → 添加账号」里。

> ⚠️ 凭证等同于账号密码，**不要截图发群、不要提交到公开仓库**。泄露后立即在云控制台删除/轮换。

---

## 一、Oracle Cloud（OCI）

面板需要的字段：`user_ocid`、`tenancy_ocid`、`fingerprint`、`private_key`、`region`

### 步骤

1. **生成 API 密钥对**（本地执行）：
   ```bash
   mkdir -p ~/.oci && cd ~/.oci
   openssl genrsa -out oci_api_key.pem 2048
   openssl rsa -pubout -in oci_api_key.pem -out oci_api_key_public.pem
   ```

2. **上传公钥到 OCI**：
   - 登录 OCI 控制台 → 右上角头像（Profile）→ **User settings**，会进入 Identity & Security 下的 **My profile** 页 → 顶部 **Tokens and keys** 标签 → API keys 区域点 **Add API key**
   - 旧版控制台：右上角头像 → **我的概要信息** → 左下「资源」里的 **API 密钥**；管理员给别人加：身份和安全 → 用户 → 点用户名 → API 密钥
   - 选择「粘贴公钥」，把 `oci_api_key_public.pem` 的内容粘贴进去 → 添加
   - 添加成功后页面会显示三样东西，**复制保存**：
     - **指纹**（Fingerprint）→ 填 `fingerprint`
     - **用户 OCID** → 填 `user_ocid`
     - **租户 OCID** → 填 `tenancy_ocid`

3. **私钥**：把 `oci_api_key.pem` 的**完整内容**（含 `-----BEGIN RSA PRIVATE KEY-----` 头尾）填到 `private_key`。

4. **区域**：填你的租户主区域，如 `ap-tokyo-1`（东京）、`ap-singapore-1`（新加坡）、`us-ashburn-1` 等。

### 权限说明

API 密钥继承该 IAM 用户的权限。建议给专用 IAM 用户最小权限，或直接用有实例管理权限的用户。需要用到**账单（Usage API）**时，租户管理员要在 IAM Policy 里加：

```
allow group <你的组> to read usage-reports in tenancy
```

---

## 二、AWS

面板需要的字段：`access_key`、`secret_key`、`region`

### 步骤

1. 登录 AWS 控制台 → 搜索 **IAM** → 左侧 **用户** → **创建用户**，用户名如 `tricloud`。
2. 权限先选 **直接附加策略**，按需勾选（见下方权限说明），下一步创建。
3. 点进刚建的用户 → **安全凭证** → **创建访问密钥** → 用途选「第三方服务」→ 创建。
4. **只显示一次**：复制 **访问密钥 ID** → 填 `access_key`，**秘密访问密钥** → 填 `secret_key`。
5. **区域**：填常用区域，如 `ap-northeast-1`（东京）、`us-east-1`（弗吉尼亚）。

### 权限说明（按需勾选）

| 面板功能 | 需要的 IAM 权限 |
|---|---|
| EC2 实例管理 | `ec2:*`（或按 API 细化） |
| Lightsail 管理 | `lightsail:*` |
| CloudFront 管理 | `cloudfront:*` |
| 账单（Cost Explorer） | `ce:GetCostAndUsage`、`ce:GetCostForecast` |
| 配额查询 | `servicequotas:ListServiceQuotas` |
| 切换 CloudFront 套餐 | `pricing-plan-manager:*`（按量切包月用） |
| 创建实例时列区域/密钥对 | `ec2:DescribeRegions`、`ec2:DescribeKeyPairs` |
| 新号 Credit 查询（build 20） | `freetier:GetAccountPlanState`、`freetier:ListAccountActivities`、`freetier:GetAccountActivity`（只读） |
| 新号 Credit 一键完成活动（可选） | EC2：`ec2:RunInstances / DescribeInstances / TerminateInstances / CreateTags / DescribeInstanceTypeOfferings`、`ssm:GetParameter`；Budgets：`budgets:ModifyBudget / ViewBudget`；Lambda：`iam:CreateRole / GetRole / PassRole / TagRole / DeleteRole`、`lambda:CreateFunction / GetFunction / CreateFunctionUrlConfig / AddPermission / DeleteFunction`；RDS：`rds:CreateDBInstance / DescribeDBInstances / DeleteDBInstance / AddTagsToResource / DescribeOrderableDBInstanceOptions`；Bedrock：`bedrock:InvokeModel` |
| 账单页 IAM 相关开关 | root 账号去 Billing → Account 开 "IAM user and role access to Billing information" |

> 面板对缺权限做了降级处理（如 DescribeRegions 失败会用内置区域列表），但缺关键权限对应功能会报错，届时按报错提示补权限即可。


### AWS 新号 Credit：查询与一键完成活动

2025-07-15 之后注册的 AWS 新账号，注册送 $100 credit，另外完成 5 个「Explore AWS」活动每个再送 $20（最多再送 $100）。面板 AWS 账号页的 **「新号 Credit」** 标签可以查看剩余 credit、到期时间和每个活动的状态，并能一键执行活动。

#### 1. 给 IAM 用户加权限

IAM → 用户 → 你给面板用的用户（如 `tricloud`）→ **权限** → **添加权限** → **创建内联策略** → 切到 **JSON**，粘贴下面其中一段 → 命名（如 `tricloud-credit`）→ 创建。

**A. 只查看状态（只读，推荐至少加这段）**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FreeTierRead",
      "Effect": "Allow",
      "Action": [
        "freetier:GetAccountPlanState",
        "freetier:ListAccountActivities",
        "freetier:GetAccountActivity"
      ],
      "Resource": "*"
    }
  ]
}
```

缺 `freetier:ListAccountActivities` 时，面板能显示剩余 credit，但活动状态会显示「无权限读取」。

**B. 查看 + 一键完成活动（完整）**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FreeTierRead",
      "Effect": "Allow",
      "Action": [
        "freetier:GetAccountPlanState",
        "freetier:ListAccountActivities",
        "freetier:GetAccountActivity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EC2Activity",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceTypeOfferings",
        "ec2:DescribeImages",
        "ec2:TerminateInstances",
        "ec2:CreateTags",
        "ssm:GetParameter"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BudgetsActivity",
      "Effect": "Allow",
      "Action": [
        "budgets:ViewBudget",
        "budgets:ModifyBudget",
        "budgets:TagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LambdaActivity",
      "Effect": "Allow",
      "Action": [
        "lambda:ListFunctions",
        "lambda:CreateFunction",
        "lambda:GetFunction",
        "lambda:CreateFunctionUrlConfig",
        "lambda:DeleteFunctionUrlConfig",
        "lambda:AddPermission",
        "lambda:InvokeFunctionUrl",
        "lambda:DeleteFunction",
        "lambda:TagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LambdaRoleOnlyTriCloud",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:GetRole",
        "iam:TagRole",
        "iam:PassRole",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
        "iam:DetachRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:DeleteRole"
      ],
      "Resource": "arn:aws:iam::*:role/tricloud-credit-*"
    },
    {
      "Sid": "RDSActivity",
      "Effect": "Allow",
      "Action": [
        "rds:DescribeOrderableDBInstanceOptions",
        "rds:CreateDBInstance",
        "rds:DescribeDBInstances",
        "rds:AddTagsToResource",
        "rds:DeleteDBInstance"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BedrockActivity",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "*"
    }
  ]
}
```

IAM 角色权限限定在 `tricloud-credit-*` 名下，面板没法借此改动你其他的角色。如果用户本来就有 `AdministratorAccess`，就不用再加 B 段。

#### 2. Bedrock 模型访问

部分账号首次使用 Bedrock 需要先开通模型：控制台切到 **us-east-1** → Amazon Bedrock → **Model access** → 开通 **Amazon Nova Micro**。未开通时面板会提示。

#### 3. 在面板里操作

1. AWS 账号页 → **新号 Credit** → 点 **刷新**，确认能看到剩余 credit 和 5 个活动。
2. 对状态为「未开始」的活动点 **一键完成**；或点 **一键全部完成**（需要确认两次）。
3. 每个活动做什么、什么时候清理：

| 活动 | 面板做的事 | 清理 | 费用（从 credit 扣） |
|---|---|---|---|
| EC2 | 默认区域启动 1 台 t3.micro / t2.micro（Amazon Linux 2023） | 约 5 分钟后终止，另有 30 分钟自动关机兜底 | 约 $0.001 |
| Budgets | 建 $1 月度成本预算 `tricloud-credit-budget` | 预算免费，默认保留 | $0 |
| Lambda | 建角色 + Python 函数 + 公开函数 URL，访问一次 | 10 分钟后删除函数、URL、角色 | 约 $0 |
| RDS | 最小 MySQL（db.t4g.micro / db.t3.micro，20 GB，不开公网） | 可用后约 1 分钟删除，不留快照 | 约 $0.01 |
| Bedrock | us-east-1 用 Nova Micro 发一句话 | 无 | < $0.0001 |

4. 所有资源都打 `tricloud-credit=1` 标签；任务中途停止也会清理。万一有残留，点 **清理残留**（可勾选同时删除预算）。

#### 4. 注意

- AWS 没公开说明 API 完成的操作是否计入活动。面板执行后显示「已执行，等待 AWS 识别」，是否完成以 AWS 返回的状态为准，可能要几分钟到几小时才更新。
- Bedrock 官方要求「在 playground 里使用」，API 调用可能不算。长时间不更新的话，到控制台 Bedrock → **Playgrounds → Chat** 手动发一句。
- 升级为付费计划后剩余 credit 仍会显示；不是新免费计划的老账号会提示「不适用」。

---

## 三、Microsoft Azure

面板需要的字段：`tenant_id`、`client_id`、`client_secret`、`subscription_id`

### 方法一：Cloud Shell 命令（推荐，约 1 分钟）

1. 登录 [Azure Portal](https://portal.azure.com)，点顶栏 `>_` 图标打开 **Cloud Shell**，选 **Bash**。
2. 查订阅 ID：

   ```bash
   az account show --query id -o tsv
   ```

3. 创建服务主体并授权（把 `<SUB_ID>` 换成上一步的订阅 ID）：

   ```bash
   az ad sp create-for-rbac --name tricloud --role Contributor --scopes /subscriptions/<SUB_ID>
   ```

4. 输出字段对应关系：`appId` → `client_id`，`password` → `client_secret`（只显示这一次，请立即保存），`tenant` → `tenant_id`。
5. 如需面板查**账单**，再授权 Cost Management 读者：

   ```bash
   az role assignment create --assignee <appId> --role "Cost Management Reader" --scope /subscriptions/<SUB_ID>
   ```

6. 把第 3 步的输出 JSON 连同一行 `subscription_id: <SUB_ID>` 一起粘贴到面板「添加账号 → 粘贴自动识别」，会自动拆成四个字段。

> 想收紧权限：可把 Contributor 换成 **Virtual Machine Contributor + Network Contributor**（换 IP、创建 VM 还需资源组写权限）。

### 方法二：Portal 网页手动创建

1. 登录 [Azure Portal](https://portal.azure.com) → 搜索 **Microsoft Entra ID**（原 Azure AD）。
2. 左侧 **应用注册** → **新注册**，名称如 `tricloud`，受支持的帐户类型保持默认 → 注册。
3. 注册成功后在「概述」页复制：
   - **应用程序（客户端）ID** → 填 `client_id`
   - **目录（租户）ID** → 填 `tenant_id`
4. 左侧 **证书和密码** → **新客户端密码** → 添加，**立即复制密码的「值」**（只显示一次）→ 填 `client_secret`。
5. 复制 **订阅 ID**：Portal 搜索 **订阅** → 点进你的订阅 → 复制 **订阅 ID** → 填 `subscription_id`。

### 授权（关键步骤）

服务主体默认没有任何订阅权限，必须手动授权：

1. Portal 搜索 **订阅** → 点进订阅 → 左侧 **访问控制(IAM)** → **添加角色分配**。
2. 角色选 **参与者**（Contributor；只要开关机/改配置够用，只读需求可选「读者」）。
3. 成员选刚注册的应用 `tricloud` → 查看+分配。
4. 如需面板查**账单**，再加一个角色分配：**Cost Management 读者**（Cost Management Reader）。

> Azure 学生订阅（$100 教育优惠）同样适用以上流程；教育优惠到期日可在 Sponsorships 门户查看后填到面板账单页。

---

## 四、OneDrive 备份（可选，Microsoft Graph）

面板「设置 → OneDrive 备份」可以把数据库和加密密钥定期加密上传到**你自己的** OneDrive。面板不内置任何第三方应用，需要你在 Azure 门户注册一个自己的应用，只把它的 `client_id` 填进面板。整个过程约 3 分钟，个人 Microsoft 帐户（outlook.com / hotmail.com / live.com）免费可用，不需要 Azure 订阅。

面板只申请两个权限：`Files.ReadWrite.AppFolder`（只能读写 OneDrive 里 **应用 / <你的应用名>** 这一个文件夹，看不到网盘里其他任何文件）和 `offline_access`（拿到 refresh token，才能无人值守定时备份）。不要给这个应用加别的权限。

### 注册应用（Azure 门户）

1. 打开 <https://portal.azure.com>，用要存放备份的 Microsoft 帐户登录（个人帐户也能登录门户，没有订阅也没关系）。
   顶部搜索框输入「应用注册」（App registrations）→ 进入后点左上角 **＋ 新注册**（New registration）。
2. **注册应用程序**页面（截图位置：页面中间的表单）：
   - 名称：例如 `TriCloud Backup`（这个名字就是 OneDrive 里「应用」下面的文件夹名）。
   - 受支持的帐户类型：选 **「任何组织目录中的帐户和个人 Microsoft 帐户」**，或 **「仅个人 Microsoft 帐户」**（只用个人 OneDrive 时推荐后者）。
     这里选成「仅此组织目录」的话，个人 Microsoft 帐户无法登录，绑定时会提示 client_id 不支持个人帐户。
   - 重定向 URI：**留空**（设备码登录不需要）。
   - 点底部 **注册**。
3. 注册完成后进入应用的 **概述**（Overview）页：页面顶部「概要」区块里的 **应用程序(客户端) ID**（Application (client) ID，形如 `00000000-0000-0000-0000-000000000000`）就是面板要填的 `client_id`，点右边的复制图标复制。
   「目录(租户) ID」不需要填。
4. 左侧菜单 **身份验证**（Authentication）→ 拉到页面最底部 **高级设置**（Advanced settings）→ **允许公共客户端流**（Allow public client flows）→ 选 **是**（Yes）→ 顶部 **保存**。
   这一步决定能不能用设备码登录；没打开时绑定会提示「该应用未启用允许公共客户端流」。
   （新版门户的「身份验证」页如果是分标签的样式，这个开关在「设置」标签里。）
5. 左侧菜单 **API 权限**（API permissions）：默认已有 `Microsoft Graph / User.Read`，可以保留也可以删除；**不需要**手动添加 `Files.ReadWrite.AppFolder`——面板在登录时动态申请，你在 Microsoft 的授权页上同意即可。不要添加 `Files.ReadWrite.All` 之类更大的权限。
6. **不需要**创建客户端密码（Client secret）或证书：这是公共客户端，面板里不保存任何应用密钥。

### 在面板里绑定

1. 面板 **设置 → OneDrive 备份**（或侧栏「☁️ OneDrive 备份」，App 在「更多 → OneDrive 备份」）→ 填 `client_id` → 登录端点保持 **consumers**（个人帐户；同时要用工作/学校帐户时选 common）→ 点 **保存**。
2. **保存后点右边蓝色「绑定 OneDrive」按钮，下方弹出代码**（如 `ABCD-EFGH`）——只点「保存」不会出现代码（App 里同样是「保存」之后点蓝色的「绑定 OneDrive」）。拿到代码后：在任意设备打开 <https://microsoft.com/devicelogin>，输入代码 → 登录 Microsoft 帐户 → 授权页确认只列出「访问应用的文件夹」和「保持访问权限」两项 → 接受。面板每几秒自动检查一次，授权后显示「已绑定」（代码 15 分钟内有效）。
3. 设置 **备份密码**（不能为空，长度和复杂度不限，两次输入要一致；务必另外记下来，丢了就无法恢复）、备份计划（见下方「备份计划」，按面板时区，默认 Asia/Shanghai）、保留份数（默认 30）。点 **立即备份** 试一次，OneDrive 网页版「我的文件 → 应用 → TriCloud Backup」里会出现 `tricloud-backup-时间.tcod`。

### 备份计划（build 23）

「修改计划」里有五种频率，保存前页面会显示 **接下来 3 次** 的备份时间（`POST /api/onedrive/schedule/preview`，只预览不保存，非法设置直接提示原因）：

| 频率 | 设置 | 例子 |
|---|---|---|
| 每 N 小时 | 间隔 1–24 小时、第几分钟（0 = 整点）、起始小时（每天从这个小时起按间隔对齐） | 每 6 小时、第 15 分 → 每天 00:15、06:15、12:15、18:15 |
| 每天 | 一个或多个时间点（HH:MM，最多 24 个） | 08:00、20:00 |
| 每周 | 多选星期 + 一个或多个时间点 | 周一、三、五 03:30 |
| 每月 | 多选 1–31 日和「月末」+ 时间点 | 1、15 日和月末 02:00 |
| Cron（高级） | 标准 5 段：分 时 日 月 周 | `30 3 * * 1-5`（工作日 03:30） |

- 全部按面板时区的墙上时间计算；夏令时切换不会多跑或漏跑（跳过的那一小时里的计划在跳过后立即执行一次，重复的那一小时只执行一次）。
- 每月选了 29–31 日时，没有这一天的月份会**跳过**（例如 2 月）；要每月最后一天请选「月末」（2 月会自动是 28 或 29 日）。
- Cron 支持 `*` `,` `-` `/`、数字、英文缩写（`mon`–`sun`、`jan`–`dec`）和 `@hourly` `@daily` `@weekly` `@monthly` `@yearly`；星期 0 和 7 都是周日；「日」和「周」都指定时满足任一即可（与 Linux cron 相同）。不支持 `L` `W` `#` `?`（每月最后一天用「每月 → 月末」）。
- 两次备份至少间隔 30 分钟；8 年内都不会触发的计划（如 `0 0 30 2 *`）不能保存。
- 失败重试：周期 ≥4 小时时失败后 1 小时重试；更短的周期（每 1–3 小时）按周期的 1/4 重试（每 1 小时 = 15 分钟后），每期最多 3 次，离下一期不到 5 分钟就不再重试，不会跨到下一期补跑。
- 从旧版本升级：原来的「每天 / 每周 + 时间」自动变成对应的新设置，下次备份时间不变；旧版 App 仍能查看和修改保留份数，不会覆盖新计划。

### 安全说明

- refresh token 和备份密码都用面板自己的 Fernet 密钥（`data/fernet.key`）加密后存在本机数据库里——定时备份需要无人值守解开它们。能读到 `data/` 的人本来就能读到全部云凭证，所以这不增加风险。
- 上传到 OneDrive 的文件只用备份密码加密（scrypt 派生 + AES-256-GCM），与 `fernet.key` 无关；只拿到 OneDrive 文件、不知道备份密码，解不开。
- API Token 只能查看状态 / 列表和「立即备份」，不能绑定、改设置（含计划预览）、恢复、解绑（返回 403）。
- 撤销授权：<https://account.live.com/consent/Manage> 里删掉这个应用，或在面板点「解绑」（只删除本机 token，OneDrive 上的备份文件保留）。

### 新装机恢复

装好面板 → 登录 → OneDrive 备份页填同一个 `client_id` 并绑定同一个 Microsoft 帐户 → 备份列表选一份 → 恢复 → 输入备份密码 → 二次确认。恢复前面板会把当前数据保存到 `data/pre-restore-时间/`，替换数据库和密钥后自动重启（Docker 的 restart 策略拉起），用备份时的面板密码重新登录。

### 离线解密

不依赖面板，任何装了 Python 3 和 `cryptography`（`pip install cryptography`）的电脑，在仓库根目录：

```
python -m tools.decrypt_backup tricloud-backup-20261016-033000.tcod 输出目录
```

会提示输入备份密码（也可以作为第二个参数或环境变量 `TRICLOUD_BACKUP_PASSWORD` 传入），输出 `tricloud.db`、`fernet.key`、`meta.json`。手动恢复：停面板 → 把这两个文件覆盖到 `data/`（先备份原文件）→ `chmod 600` → 启动面板。

---

## 填到面板

面板（Web / Android / iOS / Windows 客户端）→ **账号** → **添加账号**：

- 可以直接把上面的输出 / 复制的内容整段粘贴到「粘贴自动识别」，面板会识别云厂商并拆分字段；也可以逐项手动填写。
- 保存前会自动测活，凭证有误不会保存。

更换 / 轮换凭证：在账号列表点 **编辑**，填入新的密钥即可（留空的密钥字段保持不变，修改凭证时同样先测活）。
