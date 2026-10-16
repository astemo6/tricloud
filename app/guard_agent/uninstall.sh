#!/usr/bin/env bash
# 卸载 TriCloud 流量守护 agent：清除 tc 限速规则与流量明细计数规则（nftables table inet tricloud_acct / iptables TRICLOUD_ACCT_*）、
# 停用 timer、删除程序和配置。
# 用法：curl -fsSL '<面板>/api/guard-agent/uninstall.sh' | sudo bash
set -u
if [ "$(id -u)" != "0" ]; then echo "请用 root 运行（... | sudo bash）" >&2; exit 1; fi
if [ -x /usr/local/bin/tricloud-guard ]; then
  /usr/local/bin/tricloud-guard uninstall
  exit 0
fi
# 程序已被删掉时的兜底
systemctl disable --now tricloud-guard.timer >/dev/null 2>&1
rm -f /etc/systemd/system/tricloud-guard.timer /etc/systemd/system/tricloud-guard.service
systemctl daemon-reload >/dev/null 2>&1
for dev in $(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | cut -d@ -f1); do
  if tc qdisc show dev "$dev" 2>/dev/null | grep -q 'htb 1: root'; then tc qdisc del dev "$dev" root 2>/dev/null; fi
done
if command -v nft >/dev/null 2>&1; then nft delete table inet tricloud_acct >/dev/null 2>&1; fi
for bin in iptables ip6tables; do
  command -v "$bin" >/dev/null 2>&1 || continue
  for c in INPUT:TRICLOUD_ACCT_IN OUTPUT:TRICLOUD_ACCT_OUT FORWARD:TRICLOUD_ACCT_FWD; do
    while "$bin" -t mangle -D "${c%%:*}" -j "${c#*:}" >/dev/null 2>&1; do :; done
    "$bin" -t mangle -F "${c#*:}" >/dev/null 2>&1
    "$bin" -t mangle -X "${c#*:}" >/dev/null 2>&1
  done
done
rm -rf /etc/tricloud-guard /var/lib/tricloud-guard
echo "已卸载 TriCloud 流量守护 agent"
