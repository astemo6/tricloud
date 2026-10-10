# AWS / Azure 云服务器管理面板开源项目调研报告

**调研方式**：Pi (openrouter/nvidia/nemotron-3-ultra) 联网调研 + 人工交叉核实（GitHub API 实时数据）
**调研日期**：2026-10-10
**说明**：stars 数与更新时间为查询当日 GitHub API 实时数值；未找到的项目如实标注，不编造。

---

## 1. 项目介绍表

| 项目名 | GitHub 地址 | Stars | 最后更新 | 一句话介绍 |
|---|---|---|---|---|
| Komiser | https://github.com/mlabouardy/komiser | 4145 | 2026-09-10 | 多云资源与成本检查器：AWS/Azure/GCP/OCI 等资产清单、资源级成本拆分、闲置/无标签资源识别（只读分析，不做实例启停） |
| ManageIQ | https://github.com/ManageIQ/manageiq | 1402 | 2026-10-08 | Red Hat 系企业级混合 IT 管理平台：EC2/Azure 实例全生命周期、Chargeback 成本分摊、监控告警、完整 RBAC |
| CloudExplorer Lite | https://github.com/1Panel-dev/CloudExplorer | 761 | 2026-03-31（已归档） | 飞致云轻量云管平台：云主机管理、云账单/分账、资源优化建议、安全合规扫描（Lite 版**不含 AWS/Azure**，作通用云管代表收录） |
| Polynimbus | https://github.com/polynimbus/polynimbus | 89 | 2024-03-22 | Python 多云基础设施工具集：AWS/Azure 计算全生命周期 API + 跨账号资源 Inventory 爬虫（Web Panel 子项目已停滞） |
| Cloudforet | https://github.com/cloudforet-io/cloudforet | 88 | 主仓库 2024-02；console 2026-08；采集插件 2025-12~2026-01 | Linux Foundation 多云管理平台：插件化纳管 AWS/Azure/GCP/OCI 等，资产清单、成本与预算、监控事件通知、RBAC |
| azure-manager | https://github.com/elunez/azure-manager | 52 | 2026-09-29 | 轻量 Azure VM 第三方面板（Flask+Docker）：多账号、创建/删除/启停/换 IP、费用概览、任务日志、登录审计与失败锁定 |

> 备注：本领域高 stars 项目稀缺——多数人直接用官方控制台。AWS 专用面板的高 stars 代表是 Komiser（多云，偏成本）；Azure 专用面板普遍 stars < 100，azure-manager（52★）是其中功能最完整且仍活跃的。

---

## 2. 各项目功能清单与架构

### 2.1 Komiser（4145★，Go，ELv2）

- **实例管理**：❌ 无（只读：资产清单展示，不做启停/创建/终止）
- **账单/成本**：✅ 资源级成本拆分、多云费用视图、**闲置资源识别**、**无标签资源识别**、安全漏洞检测
- **监控告警**：❌ 无实例性能监控
- **批量操作**：❌ 无
- **快照/镜像**：❌ 无
- **IAM/多人协作**：❌ 无
- **架构部署**：Go 后端 + 前端 dashboard；Docker 单容器部署，复杂度低

### 2.2 ManageIQ（1402★，Ruby，Apache-2.0）

- **实例管理**：✅ 列表/创建（服务目录化、基于模板/AMI）/启停/终止/改配置/退役
- **账单/成本**：✅ Chargeback 费率体系（CPU/内存/存储费率、按标签或部门分摊、成本报告与趋势）；❌ 无自动优化建议
- **监控告警**：✅ 性能/利用率指标采集、仪表盘、阈值/表达式/日志告警；通知渠道**邮件 + SNMP Trap**
- **批量操作**：✅ 标签批量管理、批量退役
- **快照/镜像**：✅ VM 快照、AWS AMI 管理
- **IAM/多人协作**：✅ 完整 RBAC（角色/用户/组/租户）、LDAP/AD/SAML/OIDC、2FA
- **其他**：合规策略引擎、自动化引擎、REST API、定时报告邮件发送
- **架构部署**：Ruby on Rails + PostgreSQL + Redis；OVA/容器/K8s/OpenShift 部署，**复杂度高**（企业级）

### 2.3 CloudExplorer Lite（761★，Java，GPLv3，已归档）

- **实例管理**：✅ 云主机全生命周期、磁盘管理、任务、回收站
- **账单/成本**：✅ 云账单总览/明细/自定义账单、**分账设置/计费策略**、运营分析（**资源优化建议**）
- **监控告警**：❌ 无
- **批量操作**：⚠️ 未明确
- **快照/镜像**：❌ 未找到
- **IAM/多人协作**：✅ 多租户（用户/角色/组织三级）
- **其他**：安全合规扫描（自定义规则/风险条例）
- **架构部署**：Spring Boot + Vue3 + MySQL + Docker，**复杂度低**

### 2.4 Polynimbus（89★，Python，MIT）

- **实例管理**：✅ 统一 API 支持 AWS/Azure 计算全生命周期；Web Panel 展示跨账号资源
- **账单/成本**：❌ 无费用展示（设计目标是靠跨厂商迁移降本）
- **监控告警**：❌ 无
- **批量操作**：⚠️ API 层面可脚本化；UI 未明确
- **快照/镜像**：❌ 无
- **IAM/多人协作**：⚠️ 可读写 IAM 资源，无内置多用户体系
- **其他**：跨账号 Inventory 爬虫、对象存储自动本地备份
- **架构部署**：Python 工具集 + install.sh；Web Panel 为独立 PHP 仓库（**2021 年后停更**），复杂度低但有维护风险

### 2.5 Cloudforet（88★，Python，Apache-2.0）

- **实例管理**：❌ 以资产发现为主，无启停/创建
- **账单/成本**：✅ 费用明细、基于成本的资源优化、**预算管理（防超支）**
- **监控告警**：✅ 统一监控、事件通知、事故管理
- **批量操作**：❌ 无（Automation 支持自定义作业）
- **快照/镜像**：❌ 无
- **IAM/多人协作**：✅ RBAC + 项目/项目组
- **其他**：插件架构、Open API、中英韩日多语言
- **架构部署**：Python 微服务 + gRPC + K8s/Helm/Istio/Prometheus，**复杂度中高**

### 2.6 azure-manager（52★，Python，无 License）

- **实例管理**：✅ 创建/删除/启动/停止/换 IP；❌ 无重启/改配置
- **账单/成本**：✅ 费用概览（Cost Management API：本月累计、每日趋势、服务明细；30 分钟缓存）
- **监控告警**：❌ 无
- **批量操作**：❌ 无
- **快照/镜像**：❌ 无
- **IAM/多人协作**：⚠️ 单管理员 + **登录审计（2000 条）+ 失败限速锁定（5 分钟 5 次/15 分钟 10 次锁 15 分钟）**；无 RBAC
- **其他**：多 Azure 账号（凭据加密存储 0600）、任务日志、安全 Cookie、创建失败自动清理避免残留计费
- **架构部署**：Flask + Gunicorn + SQLite + Docker（GHCR），**复杂度低**，与 TriCloud 技术栈最接近

---

## 3. TriCloud 缺失功能清单（带建议评级）

> 纠正：Pi 初版误将"实例创建"列为缺失——TriCloud Web 端已有实例创建（OCI 简化创建、AWS EC2 创建等），缺的是 App 端对齐。此处已修正。

评级说明：**值得补**=高价值低风险，适合个人自用面板；**可选**=有价值但优先级不高；**不建议**=企业级场景或与 TriCloud 定位冲突，并注明理由。

### 值得补

| 缺失功能 | 出处项目 | 说明 |
|---|---|---|
| 登录失败限速/锁定 + 登录审计 | azure-manager | TriCloud 2026-10-03 安全审计已明确指出"登录接口无失败限速"是已知风险；实现简单（计数器+时间窗），纯后端逻辑，无云 API 风险 |
| 闲置资源识别 / 成本优化建议 | Komiser、CloudExplorer Lite、Cloudforet | 用户对成本极敏感（$0.16 追到 16 次 API 调用）；实现为规则判断（长期低 CPU/已停止仍计费的实例），只读 API，低风险高价值 |
| 快照管理（AWS EBS / Azure 磁盘快照） | ManageIQ | 备份刚需；create/describe/delete_snapshot 均为免费 API，实现简单 |
| 批量操作（批量启停、批量打标签） | ManageIQ、Polynimbus | 多实例场景省时；复用现有单实例 API 循环调用即可 |

### 可选

| 缺失功能 | 出处项目 | 说明 |
|---|---|---|
| 预算告警（月度预算+超支提醒） | Cloudforet | 有价值，但用户账号少、消费低，优先级低于闲置识别 |
| 实例性能监控图表（CPU/内存趋势） | ManageIQ、azure_cloud_dashboard | CloudWatch/GetMetricData 有免费额度，但会增加 API 调用复杂度；TriCloud 已有账号级监控，实例级是增强 |
| 邮件通知渠道 | ManageIQ | 目前仅 Telegram；多一个渠道是加分项，非必需 |
| 模板化/服务目录式创建 | ManageIQ | TriCloud 已有基础创建能力；服务目录是企业级形态，个人用处不大 |
| 多资源类型清单（数据库/DNS/对象存储） | Polynimbus | 信息聚合价值有，但超出"服务器管理"核心定位 |

### 不建议

| 缺失功能 | 出处项目 | 不建议理由 |
|---|---|---|
| 完整 RBAC / 多租户 / 多人协作 | ManageIQ、CloudExplorer Lite、Cloudforet | TriCloud 是个人自用面板；引入用户/角色/组织体系将大幅增加复杂度，且与"凭证自己掌控"的单用户定位冲突 |
| LDAP/AD/SAML/OIDC/2FA 外部认证 | ManageIQ | 企业级身份源对接，个人面板过度设计；当前 PBKDF2+会话机制已够用 |
| Chargeback 费率体系 / 成本分账 | ManageIQ、CloudExplorer Lite | 企业财务分摊场景，个人用户用不上 |
| 安全合规扫描引擎 | CloudExplorer Lite | 需自建规则引擎，复杂度高；个人账号合规需求低 |
| 编排栈管理（CloudFormation/Heat） | ManageIQ | 属 IaC 范畴，与"管理面板"定位不符 |
| SNMP Trap 告警 | ManageIQ | 企业监控对接方式，个人场景无接收端 |

---

## 4. 结论

1. **TriCloud 的差异化优势**（上述项目普遍没有）：OCI 换公网 IP/IPv6/自动抢机、AWS Lightsail 与 CloudFront 管理、配额查询、Telegram Bot 交互、每日账单报告、回收站、任务历史、主题切换——在"个人多雲操控"这个定位上，TriCloud 比这些开源项目更贴合个人站长/独立开发者。
2. **最值得补的 4 项**：登录限速锁定（安全审计遗留风险）、闲置资源识别（契合用户成本敏感）、快照管理、批量操作——都是低风险、高频使用的能力。
3. **不要碰的方向**：RBAC/多租户、LDAP、Chargeback、合规扫描——这些是企业云管平台（ManageIQ/CloudExplorer）的复杂度来源，会稀释 TriCloud"轻量个人面板"的定位。
