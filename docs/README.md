# docs/

v1.5.0 起从线上旧版 TriCloud（无 git 的那一版）复制过来的调研文档，内容为当时的调研结论，**文中的代码引用（`app/db.py`、`frontend/app.js`、`android-native/` 等）指旧版代码，不是本仓库**。

复制前做过检查：没有服务器 IP（只有 `127.0.0.1`）、没有凭证或密钥。以下内容已脱敏：

- `probe-tools-research.md`：第三方论坛 / TG / GitHub 账号与域名。
- `sijuly-research.md`、`功能对照表.md`、`截图功能核查.md`：第三方项目里的硬编码弱口令原文。

与本仓库不一致之处：`功能对照表.md` 把「Web SSH / 类 Cloud Shell 远程控制台」列为不建议做；本仓库 v1.3 曾加过串口控制台，v1.5.0 已按用户决定整体移除，两者现已一致。
