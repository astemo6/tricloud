# sijuly 云管理面板系列仓库调研报告

> 调研时间：2026-10-10（Pi 通过 GitHub API 实时核实 + 下载源码审计）
> 结论前置：四个目标仓库全部存在；`cloud_manager` 三合一仓库确认已下架（404）。四个仓库**均未发现硬编码后门或向第三方回传数据**，主要风险是凭证明文存储和默认弱口令。

## 一、仓库存在性

| 仓库 | 地址 | 状态 | 最后更新 | Stars |
|---|---|---|---|---|
| Oracle | https://github.com/SIJULY/Oracle | ✅ 存在 | 2025-10-30（约12个月未动） | 1 |
| aws | https://github.com/SIJULY/aws | ✅ 存在 | 2026-09-28 | 1 |
| azure | https://github.com/SIJULY/azure | ✅ 存在，活跃 | 2026-10-10（当天仍在提交） | 6 |
| tgbot | https://github.com/SIJULY/tgbot | ✅ 存在 | 2026-10-06 | 2 |
| cloud_manager | https://github.com/SIJULY/cloud_manager | ❌ 404 已下架 | — | —（缓存显示曾 46★）|

四个仓库均无 LICENSE 文件、无 releases。旁证：sijuly 名下共 67 个公开仓库，相关还有 `Oracle-Cloud-GUI`（Tkinter 桌面版）。

## 二、各仓库功能与架构

### SIJULY/Oracle（OCI Web 面板）
- **功能**：多 OCI 账号管理；实例启停/重启/终止；一键换公网 IPv4；分配 IPv6；实例创建+**自动抢机**（Celery 后台循环）；任务历史（SQLite，可找回 Root 密码）；VCN/子网/安全列表管理；改实例配置；**Cloudflare DNS 联动**（抢机成功自动更新 A 记录）；Telegram 任务通知；REST API（Bearer Key）；默认 SSH Key 管理
- **架构**：Python + Flask 2.3 + gunicorn + Celery 5.3 + Redis 6 + SQLite；Docker Compose 四服务（web/worker/redis/caddy，Caddy 自动 HTTPS）
- **风险**（有代码证据）：① 硬编码默认密码（原文已脱敏）（`app.py:22`）；② 硬编码 Flask secret key；③ **OCI API 私钥明文存 `oci_profiles.json`**（含 key_content）；④ TG/Cloudflare token 明文存 JSON；⑤ 实例 Root 密码明文存库；⑥ cloud-init 默认开 SSH 密码登录+`PermitRootLogin yes`
- 未发现后门/外传：出站仅 api.telegram.org、api.cloudflare.com、OCI 官方 API

### SIJULY/aws（AWS 实例工具套件）
- **功能**：EC2+Lightsail 实例创建/查询/启停/重启/删除；换 IP（EIP 重绑）；Service Quotas 配额查询；区域激活；跨区域总览；异步任务+日志；**Tinyproxy 代理服务**（固定 AWS 出口 IP）；附赠 `check-claude-access.sh`（Bedrock 各区域 Claude 可用性检测）
- **架构**：Python + Flask + boto3 + gunicorn；**无数据库**，凭据存纯文本 `key.txt`；纯源码部署（install.sh → venv → systemd → Caddy）
- **风险**（有代码证据）：① 源码硬编码弱口令 `PASSWORD="<已脱敏>"`；② 硬编码 Flask secret key；③ AWS Key 明文存 `key.txt`；④ 凭据写入 Flask session（客户端签名 cookie，非加密）
- **无账单、无监控、无 TG 通知**。未发现后门/外传

### SIJULY/azure（Azure 面板，维护最活跃）
- **功能**：账号/资源组/VM/Foundry 总览；服务主体管理+批量导入+连通性检测；**账单**（Cost Management，本月 MTD+12 个月历史+趋势图，本系列唯一有账单的）；Compute/Foundry/OpenAI 配额；VM 开机/关机/重启/删除/换公网 IP/创建；**Foundry（Azure AI）配额层级、创建 AI Services、批量部署模型**；**代理管理**（HTTP/HTTPS/SOCKS5，批量添加+连通性测试）；cloud-init/PowerShell 初始化脚本模板；任务中心；**操作审计日志**；API Token 管理（哈希存储）；**内嵌 Swagger API 文档**
- **架构**：Python 3.12 + FastAPI + uvicorn + SQLAlchemy + SQLite；前端 React 19 + Vite + Tailwind；Docker Compose；一键 install.sh
- **风险**：① 默认 `admin/<已脱敏>`（三处硬编码，README 要求首次登录修改）；② 凭据加密存储（Fernet，密钥 0600）、bcrypt、JWT、审计——**四个仓库中安全实践最好**；③ 要求 Azure 管理平面权限范围较广，README 未声明最小权限
- 无自动抢机、无 TG 通知。未发现后门/外传

### SIJULY/tgbot（配套 TG 机器人）
- **功能**：从面板加载 OCI 账号；实例开机/关机/重启/终止；换 IPv4、分配 IPv6；**纯按钮交互式创建实例**；自动抢机；任务完成主动推送；白名单 `AUTHORIZED_USER_IDS`
- **架构**：Python 单文件 `bot.py`（33KB）+ python-telegram-bot + httpx；无数据库无 Docker；systemd 部署；通过 `{PANEL_URL}/api/v1/oci` + Bearer Key 调用面板 API
- **风险**：配置文件（PANEL_URL/API_KEY/BOT_TOKEN）明文存 bot.py；默认白名单占位符 `[123456789]` 不改则有未授权风险。未发现后门

## 三、功能对照：TriCloud 缺什么

| sijuly 有 / TriCloud 无 | 来源 | 值得补？ | 说明 |
|---|---|---|---|
| **Cloudflare DNS 联动**（抢机成功自动更新 A 记录） | Oracle | ✅ 值得 | TriCloud 有 OCI 自动抢机，补上 DNS 联动即完整闭环；纯用户自填 token，无额外风险 |
| **API Token 管理**（外部调用凭证，哈希存储） | azure | ✅ 值得 | TriCloud 的 Android App 直连 API，目前靠面板密码 Cookie；正式 API Key 机制更干净 |
| **操作审计日志** | azure | ✅ 值得 | TriCloud 有任务历史，但无"谁在何时做了什么"的审计维度 |
| **Swagger API 文档** | azure | ✅ 值得 | 零风险，方便二次开发 |
| **账号连通性检测**（不通不入库） | azure | ✅ 值得 | TriCloud 添加账号时可先测连通性，减少无效账号 |
| **代理管理**（HTTP/SOCKS5，面板走代理发请求） | azure | ⚠️ 可选 | 对需要代理访问云 API 的用户有用，但增加复杂度 |
| **Azure Foundry（AI）管理** | azure | ⚠️ 可选 | 配额/部署模型；看用户是否用 Azure AI，不用则无意义 |
| **初始化脚本模板**（cloud-init/PowerShell） | azure | ⚠️ 可选 | TriCloud 创建实例如已有则跳过 |
| **纯按钮交互式创建实例**（TG Bot 内） | tgbot | ⚠️ 可选 | TriCloud TG Bot 已有实例操作，补创建流程体验更好但非刚需 |
| Tinyproxy 固定出口 IP | aws | ❌ 不建议 | 易被用于绕过风控/滥用，且与面板定位无关 |
| Bedrock Claude 可用性检测脚本 | aws | ❌ 不建议 | 小众需求，与面板核心无关 |
| 默认 SSH Key 明文管理 | Oracle | ❌ 不建议 | 功能可做，但绝不能学它的明文存储 |

## 四、安全对比结论

- **TriCloud 在凭证安全上全面优于 sijuly**：Fernet 加密 vs 明文 JSON/key.txt；PBKDF2 vs 硬编码弱口令（三个硬编码弱口令，原文已脱敏）
- **sijuly 四个仓库均未发现后门或数据回传**（有源码下载审计为证），主要问题是开发习惯差（明文凭证、弱口令），不是恶意
- 值得警惕的是 **SIJULY/aws**：登录密码写死在源码里，任何人 clone 下来不用改就能登录——如果用户直接部署不改密码等于裸奔
- 四个仓库均无 LICENSE，法律上"保留所有权利"，参考功能可以，整仓照搬有合规瑕疵

## 五、给 TriCloud 的补强优先级建议

1. **P0（安全对齐）**：TriCloud 已优于对方，无需补；但可借鉴 azure 仓库的**操作审计日志**和 **admin 首次登录强制改密**思路
2. **P1（功能闭环）**：Cloudflare DNS 联动（配合 OCI 抢机）、API Token 管理、账号连通性检测
3. **P2（体验）**：Swagger 文档、TG Bot 内交互式创建、代理管理（按需）
4. **不做**：Tinyproxy、Claude 检测脚本、任何明文凭证方案
