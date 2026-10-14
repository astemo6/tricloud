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
   - 登录 OCI 控制台 → 右上角人像 → **我的概要信息** → 左侧 **API 密钥** → **添加 API 密钥**
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
| 账单页 IAM 相关开关 | root 账号去 Billing → Account 开 "IAM user and role access to Billing information" |

> 面板对缺权限做了降级处理（如 DescribeRegions 失败会用内置区域列表），但缺关键权限对应功能会报错，届时按报错提示补权限即可。

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

## 填到面板

面板（Web / Android / iOS / Windows 客户端）→ **账号** → **添加账号**：

- 可以直接把上面的输出 / 复制的内容整段粘贴到「粘贴自动识别」，面板会识别云厂商并拆分字段；也可以逐项手动填写。
- 保存前会自动测活，凭证有误不会保存。

更换 / 轮换凭证：在账号列表点 **编辑**，填入新的密钥即可（留空的密钥字段保持不变，修改凭证时同样先测活）。
