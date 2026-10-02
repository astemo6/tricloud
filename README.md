# TriCloud · OCI / AWS / Azure 三合一云服务器管理面板

一个 Web 面板，一次登录管理 Oracle Cloud（OCI）、AWS、Azure 三家云的虚拟机。
自托管，数据全在自己服务器上。

## 背景

市面上的甲骨文云面板（如 [SIJULY/Oracle](https://github.com/SIJULY/Oracle)）一次只能管一家云，
作者的三合一仓库（sijuly/cloud_manager）又已删除。
同时 R-Bot（cysk003/java_oci_manage）那套"Telegram 里管机器 + 配额查询 + 状态监控告警"的体验很好，
但它是闭源分发、只有 OCI。

TriCloud 就是为了解决这两个痛点：

- **三合一**：OCI / AWS / Azure 一个面板统一管理
- **Web + Telegram 双端**：把 R-Bot 那套 Telegram 交互（菜单操作、配额查询、异常告警、每日账单报告）完整搬进来，
  同时所有功能在 Web 端也有一份，不依赖 Telegram 也能用
- **自托管**：FastAPI + 原生 JS + SQLite，后台线程跑任务队列，无 Celery/Redis，
  一条 `docker compose` 命令就能跑起来

## 使用前提

| 项目 | 说明 |
|---|---|
| 服务器 | 任意能跑 Docker 的 Linux（VPS、家用小主机都行），1 核 1G 足够 |
| 公网入口（可选） | 想在外面访问，需要一个公网入口。推荐 Cloudflare Tunnel（免费），把一个 hostname 指到本机 `127.0.0.1:18711` |
| OCI 凭证 | Tenancy OCID、User OCID、API Key 指纹、私钥内容、归属 Region（在 OCI 控制台 → 用户 → API 密钥 处生成） |
| AWS 凭证 | Access Key ID + Secret Access Key（IAM 用户，需要 EC2 / Lightsail / CloudFront / Cost Explorer / Service Quotas 相关权限） |
| Azure 凭证 | Tenant ID、Client ID、Client Secret、Subscription ID（应用注册 + 订阅的参与者/读者角色；看账单需 Cost Management Reader） |
| Telegram（可选） | 用 [@BotFather](https://t.me/BotFather) 建一个 Bot 拿到 Token，再跟 [@userinfobot](https://t.me/userinfobot) 拿到自己的 Chat ID |

> 账单功能需要额外 IAM 权限：OCI 需租户的用量报告读取策略，AWS 需 `ce:GetCostAndUsage`，Azure 需订阅的 Cost Management Reader 角色。
> 没有这些权限不影响实例管理，只是账单页会报错。

## 部署方法

### 方式一：Docker Compose（推荐）

```bash
git clone https://github.com/<你的用户名>/tricloud.git
cd tricloud

# 1. 设置面板登录密码（只在首次启动时用于初始化，之后在面板内修改）
echo "PANEL_PASSWORD=换成你自己的强密码" > .env
chmod 600 .env

# 2. 启动（默认只监听本机 127.0.0.1:18711，不直接暴露公网）
docker compose up -d --build
```

打开 `http://服务器IP:18711`（或配好隧道后的域名），用密码登录即可。

数据（账号凭证库、任务历史）存在 `./data` 目录，重建容器不丢失。
注意 `./data` 属主需要是 `1000:1000`（容器内 appuser），否则启动会报权限错误：

```bash
mkdir -p data && sudo chown -R 1000:1000 data
```

### 方式二：本地直接运行（不喜欢 Docker 的）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PANEL_PASSWORD=换成你自己的强密码 DATA_DIR=./data \
  uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

> 必须只用 1 个 worker：任务线程池和 SQLite 都在该进程内，多 worker 会乱。

### 公网访问（Cloudflare Tunnel 示例）

```bash
# VPS 上跑 cloudflared，把 hostname 指到面板
cloudflared tunnel route dns <隧道名> panel.example.com
# 然后在 tunnel 配置里加一条：
#   hostname: panel.example.com
#   service: http://127.0.0.1:18711
```

面板本身只绑 `127.0.0.1`，公网流量经由你自己的隧道进来，不建议把 18711 直接暴露到公网。

### Android App（可选）

`android/` 目录下有 WebView 壳工程，`TriCloud-v1.0.apk` 是已打好的包（debug 签名，仅适合侧载）。
首次打开会让你填面板地址，之后就是手机版面板。手机浏览器直接访问面板域名效果一样，
APK 只是多个桌面图标。

## 使用说明

### 1. 添加云账号

登录后顶部有 OCI / AWS / Azure 三个 Tab，每个 Tab 下点「管理账号」→ 填入对应凭证。
添加时会自动校验连通性，不通会直接告诉你哪一步失败。

### 2. 实例管理

- **列表**：状态、公网 IP、规格、地域一目了然
- **生命周期**：启动 / 停止 / 重启 / 终止（Azure 停止 = deallocate，不计费）
- **换 IP**：OCI 一键更换公网 IPv4 / 分配 IPv6；
  AWS 弹性 IP 重分配，没 EIP 就停机再开机换临时 IP；
  Azure 重建 Public IP
- **改配置**：OCI 改 Shape/OCPU/内存；Azure 重置系统（reimage，危险操作有二次确认）
- **磁盘扩容**：只调大云盘，系统里的分区/文件系统要进机器手动扩
- **开放端口**：一键放行 TCP 端口（默认对公网 `0.0.0.0/0`，按需收紧）
- **改名**：改实例显示名
- **简化创建**：OCI 自动建 VCN/子网/安全组，一步开出能 SSH 的机器
- **自动抢机**：OCI 后台循环抢占，抢到自动停；面板重启后未完成的抢机任务标为 interrupted，不会自动恢复

耗时操作全部进后台任务队列，前端实时看日志，可手动停止，历史可查。

### 3. 配额 / 账单 / 订阅

- **配额**：OCI（Limits API，按可用域查余量）、AWS（Service Quotas）、Azure（区域用量）
  > 注意：OCI 免费号的 A1 余量以免费额度（4 OCPU）为准，
  > Limits API 返回的是付费视角上限，数字偏大，仅供参考
- **账单**：OCI（Usage API）、AWS（Cost Explorer）、Azure（Cost Management），看当月花费
- **订阅**：OCI 租户名、归属区域、租户 OCID

### 4. 一键测活

账号多了之后，点一下批量验证所有账号凭证是否有效，失效的标出来。

### 5. 监控告警（实例状态监控）

每个账号可单独打开：

- **状态告警**：实例异常停止 → Telegram 告警；恢复运行 → 通知
- **异常自启**：异常停止后自动尝试启动
- 巡检间隔默认 5 分钟（设置里可改 1–120 分钟）

### 6. 每日账单报告

每天定时把三家云的当日费用推送到 Telegram，推送时间可在设置里改（默认 9:00）。

### 7. Telegram Bot

在面板「设置」里填 Bot Token + Chat ID，Bot 自动上线。
`/start` 出主菜单：选云 → 选账号 → 实例/配额/账单/Lightsail/CloudFront/监控，
实例操作有二次确认，需要参数的（改名、扩容、开端口、CloudFront 刷新路径）直接回文字。
任务成功/失败/停止、监控告警、每日报告都会自动推送。Bot 只响应你配置的 chat_id。

AWS 还有 **Lightsail**（列表/启动/停止/重启）和 **CloudFront**
（分发列表/缓存刷新/启用/停用），Web 和 Telegram 都有入口。

## 安全说明

- 面板密码：PBKDF2 哈希存 SQLite，可在面板内修改；`.env` 里的 `PANEL_PASSWORD` 只用于首次初始化
- 云凭证：Fernet 加密后存 SQLite，明文只在内存里用一下
- 会话：HttpOnly Cookie，2 小时滑动过期
- 仓库里没有任何真实密钥，`.env` / `data/` 已在 `.gitignore` 中，**不要**把它们提交上来

## 目录结构

```
tricloud/
├── app/                # FastAPI 后端
│   ├── main.py         # 入口、路由、鉴权中间件
│   ├── providers/      # OCI / AWS / Azure 适配层
│   ├── tasks.py        # 后台任务队列
│   ├── monitor.py      # 实例状态监控 + 每日报告
│   └── tg.py           # Telegram Bot
├── frontend/           # 原生 JS 前端（index.html / login.html / app.js）
├── android/            # Android WebView 壳工程 + 成品 APK
├── tests/smoke_test.py # 冒烟测试（mock 方式，24 项）
├── Dockerfile
└── docker-compose.yml
```

## 测试

```bash
python3 tests/smoke_test.py
```

24 项冒烟测试（mock 云 API），覆盖鉴权、账号流程、实例操作、抢机、账单、
Lightsail/CloudFront、配额、测活、监控、每日报告。
真实云操作请用只读功能先联调（列表/账单/配额），破坏性操作务必确认实例后再执行。
