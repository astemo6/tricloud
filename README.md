# TriCloud · OCI / AWS / Azure 三合一云服务器管理面板

一个 Web 面板，一次登录管理三家云的虚拟机。功能对标
[SIJULY/Oracle](https://github.com/SIJULY/Oracle) 面板，并扩展到 AWS 与 Azure。

## 功能

| 功能 | OCI | AWS (EC2) | Azure |
|---|---|---|---|
| 多账号管理（凭证加密存储） | ✅ | ✅ | ✅ |
| 实例列表（状态/IP/规格/地域） | ✅ | ✅ | ✅ |
| 启动 / 停止 / 重启 / 终止 | ✅ | ✅ | ✅ |
| 更换公网 IP | ✅ | ✅（弹性 IP 重分配 / 停机换 IP） | ✅ |
| 分配 IPv6 | ✅ | – | – |
| 更改实例配置（升降配） | ✅ | – | – |
| 简化创建实例（自动建网） | ✅ | ✅ | ✅ |
| 自动抢机（后台循环 + 断点恢复概念） | ✅ | – | – |
| 后台任务队列 + 任务历史 | ✅ | ✅ | ✅ |

- **安全**：面板密码 PBKDF2 哈希存储；云凭证用 Fernet 加密存 SQLite；
  会话 HttpOnly Cookie + 2 小时滑动过期；无硬编码密钥。
- **任务系统**：耗时操作（创建/抢机/换 IP 等）全部后台线程执行，
  前端实时看日志；可手动停止；重启后未完成的任务标记为 interrupted。

## 快速部署（Docker）

```bash
cd tricloud
# 1. 设置面板密码（首次启动时初始化，之后可在面板内修改）
echo "PANEL_PASSWORD=你的密码" > .env

# 2. 启动（只监听本机 127.0.0.1:18711）
docker compose up -d --build

# 3. 公网访问：自行在 Cloudflare Tunnel 加一条 Public Hostname
#    例如 panel.6668800.xyz -> http://127.0.0.1:18711
```

打开面板 → 用密码登录 → 在各云 Tab 下「管理账号」添加凭证
（添加时会自动校验连通性）→ 开始管理。

## 各云凭证获取

- **OCI**：控制台右上角用户 → API 密钥 → 生成密钥对，
  记下 Tenancy OCID、User OCID、指纹、区域，私钥粘贴 PEM 全文。
- **AWS**：IAM → 用户 → 创建访问密钥（Access Key ID + Secret）。
- **Azure**：Cloud Shell 执行
  `az ad sp create-for-rbac --role contributor --scopes /subscriptions/<订阅ID>`，
  得到 client_id（appId）、client_secret（password）、tenant，
  再加订阅 ID。

## 本地开发

```bash
pip install -r requirements.txt
PANEL_PASSWORD=dev DATA_DIR=./data uvicorn app.main:app --reload
```

## 目录结构

```
app/
  main.py            # FastAPI 路由（登录/账号/实例/任务）
  config.py crypto.py db.py auth.py jobs.py
  providers/
    base.py          # 统一接口：InstanceInfo / Provider
    oci_provider.py  # OCI：列表/操作/换IP/IPv6/改配/创建/抢机
    aws_provider.py  # AWS EC2
    azure_provider.py# Azure VM
frontend/            # login.html / index.html / app.js（原生 JS）
```

## 注意事项

- 更换公网 IP、终止实例等为不可逆操作，面板内有二次确认。
- OCI 抢机请合理设置重试间隔，频繁请求可能被限流。
- Azure「停止」默认释放资源（deallocate），停止计费。
- AWS 换 IP：有弹性 IP 则重新分配；否则走停止→启动换临时 IP。
