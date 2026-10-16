#!/usr/bin/env bash
# TriCloud 流量守护 agent 安装脚本（build 22：超限限速 + 按端口 / 服务的流量明细）。由面板按守护生成：只含面板地址和这条守护的专属 token。
# 用法：curl -fsSL '<面板>/api/guard-agent/install.sh?token=<token>' | sudo bash
# 安装内容：/usr/local/bin/tricloud-guard、/etc/tricloud-guard/conf（0600）、tricloud-guard.service + .timer（每 5 分钟）。
# 卸载：sudo tricloud-guard uninstall（或 curl -fsSL '<面板>/api/guard-agent/uninstall.sh' | sudo bash）
set -eu
PANEL='__PANEL__'
TOKEN='__TOKEN__'

if [ "$(id -u)" != "0" ]; then echo "请用 root 运行（... | sudo bash）" >&2; exit 1; fi
command -v tc >/dev/null 2>&1 || { echo "缺少 tc（iproute2），请先安装：apt install iproute2 / dnf install iproute-tc" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "缺少 curl" >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo "需要 systemd" >&2; exit 1; }

install -d -m 755 /usr/local/bin
cat > /usr/local/bin/tricloud-guard <<'TRICLOUD_AGENT_EOF'
__AGENT__
TRICLOUD_AGENT_EOF
chmod 755 /usr/local/bin/tricloud-guard

install -d -m 700 /etc/tricloud-guard
umask 077
printf 'PANEL=%s\nTOKEN=%s\n' "$PANEL" "$TOKEN" > /etc/tricloud-guard/conf
chmod 600 /etc/tricloud-guard/conf

cat > /etc/systemd/system/tricloud-guard.service <<'UNIT_EOF'
[Unit]
Description=TriCloud traffic guard agent (tc throttle + port accounting)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/tricloud-guard run
UNIT_EOF

cat > /etc/systemd/system/tricloud-guard.timer <<'UNIT_EOF'
[Unit]
Description=Run TriCloud traffic guard agent every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
UNIT_EOF

systemctl daemon-reload
systemctl enable --now tricloud-guard.timer >/dev/null
systemctl start tricloud-guard.service || true
echo "已安装 TriCloud 流量守护 agent：每 5 分钟连一次面板，超限时出站限速（SSH 端口不限）；面板开了流量明细时按端口计数（只计数不拦截）。"
echo "查看状态：sudo tricloud-guard status    卸载：sudo tricloud-guard uninstall"
