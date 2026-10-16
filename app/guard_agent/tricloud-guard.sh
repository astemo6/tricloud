#!/usr/bin/env bash
# TriCloud 流量守护 agent（build 22）：超限限速 + 按端口 / 服务的流量明细。纯 bash + iproute2（tc / ss）+ nftables（或 iptables），
# 不依赖 Python / jq，无常驻进程。
#
# 由用户自己在实例上安装（面板不会远程执行任何命令）。systemd timer 每 5 分钟运行一次 `tricloud-guard run`：
#   1. 流量明细（面板里开了才做）：读计数规则 → 算出上次成功上报以来的增量，随心跳 POST 给面板；
#   2. 用本守护专属 token 拉取 <面板>/api/guard-agent/state（只能读写这条守护自己的数据）；
#   3. 需要限速时在主网卡出站方向挂 HTB：SSH 端口（从 sshd 配置读取，默认 22）的回包走不限速的 1:10，其余流量走 1:20
#      （rate = ceil = 设定 Mbps）；解除时删除本 agent 建的根 qdisc（handle 1: 的 htb），网卡恢复系统默认队列；
#   4. 流量明细的计数规则按当前监听端口（ss -lntup）自动增删：nftables 独立 table `inet tricloud_acct`，
#      没有 nft 时用 iptables / ip6tables mangle 表里的 TRICLOUD_ACCT_* 计数链。规则只计数（没有 drop / accept / reject），
#      不影响防火墙；非监听端口的流量（如本机主动访问外网）= 网卡总量 − 各端口之和，记为「其他/出站连接」。
# 安全策略：
#   - token 被重置 / 守护被删除（HTTP 401/404）→ 立即解除限速并删除计数规则；
#   - 面板连不上 → 保持当前状态，流量明细的增量留在本地下次补报；连续 24 小时连不上 → 解除限速（宁可不限，不把机器一直卡住）。
# 子命令：run（默认）| status | clear | uninstall | commands | acct-rules | ports | version
set -u

VERSION=2
CONF="${TRICLOUD_GUARD_CONF:-/etc/tricloud-guard/conf}"
STATE_DIR="${TRICLOUD_GUARD_STATE:-/var/lib/tricloud-guard}"
FAIL_OPEN_SECS=$((24 * 3600))
HANDLE="1:"
ACCT_TABLE="tricloud_acct"
ACCT_CHAINS="TRICLOUD_ACCT_IN TRICLOUD_ACCT_OUT TRICLOUD_ACCT_FWD"
MAX_PORTS=64

log() { printf '%s tricloud-guard: %s\n' "$(date '+%F %T')" "$*"; }

need_root() {
  if [ "${TRICLOUD_GUARD_TEST:-}" != "1" ] && [ "$(id -u)" != "0" ]; then
    echo "需要 root 运行（sudo tricloud-guard $*）" >&2
    exit 1
  fi
}

load_conf() {
  PANEL=""
  TOKEN=""
  IFACE_OVERRIDE=""
  if [ -r "$CONF" ]; then
    while IFS='=' read -r k v; do
      case "$k" in
        PANEL) PANEL="$v" ;;
        TOKEN) TOKEN="$v" ;;
        IFACE) IFACE_OVERRIDE="$v" ;;
      esac
    done < "$CONF"
  fi
  case "$PANEL" in http://* | https://*) ;; *) PANEL="" ;; esac
  case "$TOKEN" in *[!A-Za-z0-9_-]* | "") TOKEN="" ;; esac
  case "$IFACE_OVERRIDE" in *[!A-Za-z0-9_.@:-]*) IFACE_OVERRIDE="" ;; esac
}

# 主网卡：默认路由所在的网卡（可在 conf 里写 IFACE=xxx 覆盖）
detect_iface() {
  if [ -n "${IFACE_OVERRIDE:-}" ]; then
    echo "$IFACE_OVERRIDE"
    return
  fi
  local dev
  dev=$(ip -o route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") { print $(i + 1); exit }}')
  if [ -z "$dev" ]; then
    dev=$(ip -o route show default 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") { print $(i + 1); exit }}')
  fi
  case "$dev" in *[!A-Za-z0-9_.@:-]*) dev="" ;; esac
  echo "$dev"
}

# SSH 端口：优先 sshd -T（生效配置），再读配置文件，最后默认 22；可能有多个
detect_ssh_ports() {
  local ports=""
  if command -v sshd >/dev/null 2>&1; then
    ports=$(sshd -T 2>/dev/null | awk 'tolower($1) == "port" && $2 ~ /^[0-9]+$/ { print $2 }')
  fi
  if [ -z "$ports" ]; then
    ports=$(cat /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null \
      | awk 'tolower($1) == "port" && $2 ~ /^[0-9]+$/ { print $2 }')
  fi
  [ -z "$ports" ] && ports=22
  printf '%s\n' "$ports" | awk '$1 > 0 && $1 < 65536' | sort -un | tr '\n' ' ' | sed 's/ *$//'
}

# 生成限速用的 tc 命令（一行一条，便于测试和 status 显示）。参数：网卡 速率kbit 端口...
tc_commands() {
  local dev="$1" kbit="$2"
  shift 2
  echo "tc qdisc replace dev $dev root handle $HANDLE htb default 20"
  echo "tc class replace dev $dev parent 1: classid 1:1 htb rate 10gbit"
  echo "tc class replace dev $dev parent 1:1 classid 1:10 htb rate 10gbit prio 0"
  echo "tc class replace dev $dev parent 1:1 classid 1:20 htb rate ${kbit}kbit ceil ${kbit}kbit prio 1"
  local p
  for p in "$@"; do
    echo "tc filter add dev $dev parent 1: protocol ip prio 1 u32 match ip sport $p 0xffff flowid 1:10"
    echo "tc filter add dev $dev parent 1: protocol ipv6 prio 2 u32 match ip6 sport $p 0xffff flowid 1:10"
  done
}

is_ours() {
  tc qdisc show dev "$1" 2>/dev/null | grep -q "htb $HANDLE root"
}

apply_limit() {
  local dev="$1" kbit="$2" ports="$3" sig
  sig="$dev $kbit $ports"
  if is_ours "$dev" && [ "$(cat "$STATE_DIR/applied" 2>/dev/null)" = "$sig" ]; then
    return 0
  fi
  # 先删掉旧的（包括我们之前建的），再按新参数重建；filter 不能 replace，所以整棵树重建
  if is_ours "$dev"; then tc qdisc del dev "$dev" root 2>/dev/null; fi
  local line ok=1
  # shellcheck disable=SC2086
  while IFS= read -r line; do
    # ipv6 filter 在少数内核上不支持，失败不影响 IPv4
    if ! $line 2>/dev/null; then
      case "$line" in *"protocol ipv6"*) ;; *) ok=0; log "失败：$line" ;; esac
    fi
  done < <(tc_commands "$dev" "$kbit" $ports)
  if [ "$ok" = 1 ]; then
    echo "$sig" > "$STATE_DIR/applied"
    log "已限速 $dev 出站 ${kbit}kbit，SSH 端口 $ports 不限"
    return 0
  fi
  tc qdisc del dev "$dev" root 2>/dev/null
  rm -f "$STATE_DIR/applied"
  return 1
}

clear_limit() {
  local dev="$1"
  if [ -n "$dev" ] && is_ours "$dev"; then
    tc qdisc del dev "$dev" root 2>/dev/null && log "已解除 $dev 限速"
  fi
  rm -f "$STATE_DIR/applied"
}

# ======================= 流量明细（只计数） =======================

# 计数后端：nft（优先）/ iptables / none。TRICLOUD_GUARD_ACCT 可强制指定（测试 / 排查用）
acct_backend() {
  if [ -n "${TRICLOUD_GUARD_ACCT:-}" ]; then
    echo "$TRICLOUD_GUARD_ACCT"
  elif command -v nft >/dev/null 2>&1 && nft list tables >/dev/null 2>&1; then
    echo nft
  elif command -v iptables >/dev/null 2>&1 && iptables -t mangle -S >/dev/null 2>&1; then
    echo iptables
  else
    echo none
  fi
}

# 当前监听端口：每行「协议 端口 进程名」，排除只监听回环地址的；Docker 发布端口映射成 docker:容器名。最多 MAX_PORTS 个
listen_ports() {
  local raw dmap=""
  raw=$(ss -Hlntup 2>/dev/null) || raw=$(ss -lntup 2>/dev/null | tail -n +2)
  if command -v docker >/dev/null 2>&1; then
    dmap=$(timeout 5 docker ps --format '{{.Names}}|{{.Ports}}' 2>/dev/null)
  fi
  {
    printf '%s\n' "$raw" | awk '
      $1 == "tcp" || $1 == "udp" {
        loc = $5; n = split(loc, a, ":"); port = a[n]; addr = substr(loc, 1, length(loc) - length(port) - 1)
        if (port !~ /^[0-9]+$/ || port < 1 || port > 65535) next
        if (addr ~ /^127\./ || addr ~ /^\[?::1\]?$/ || addr ~ /%lo$/ || addr ~ /^\[::ffff:127\./) next
        proc = "-"
        if (match($0, /users:\(\("[^"]+"/)) { proc = substr($0, RSTART + 9, RLENGTH - 10) }
        gsub(/[^A-Za-z0-9._-]/, "_", proc); proc = substr(proc, 1, 32)
        print $1, port, proc
      }'
    # docker ps 的 Ports：0.0.0.0:8080->80/tcp, :::8080->80/tcp（只取对外发布的，127.0.0.1 绑定的跳过）
    printf '%s\n' "$dmap" | awk -F'|' 'NF == 2 {
        name = $1; gsub(/[^A-Za-z0-9._-]/, "_", name); name = substr(name, 1, 24)
        n = split($2, items, ", ")
        for (i = 1; i <= n; i++) {
          it = items[i]
          if (it !~ /->/ || it ~ /^127\./ || it ~ /^\[::1\]/) continue
          split(it, lr, "->"); host = lr[1]; m = split(host, hp, ":"); hport = hp[m]
          split(lr[2], tp, "/"); proto = tp[2]
          if (hport ~ /^[0-9]+$/ && (proto == "tcp" || proto == "udp")) print proto, hport, "docker:" name
        }
      }'
  } | awk '
      { k = $1 " " $2
        if (!(k in p) || p[k] == "-" || p[k] == "docker-proxy") p[k] = $3 }
      END { for (k in p) print k, p[k] }' | sort -k2,2n -k1,1 | head -n "$MAX_PORTS"
}

# 生成 nftables 规则（独立 table，只有 counter，没有任何 verdict）。参数：网卡 端口文件；forward 链单独生成（失败不影响主表）
acct_nft_rules() {
  local dev="$1" pf="$2"
  echo "table inet $ACCT_TABLE {"
  echo "  chain input {"
  echo "    type filter hook input priority -160; policy accept;"
  echo "    iif \"lo\" return"
  echo "    counter comment \"all 0 in\""
  awk '{ printf "    meta l4proto %s th dport %s counter comment \"%s %s in\"\n", $1, $2, $1, $2 }' "$pf"
  echo "  }"
  echo "  chain output {"
  echo "    type filter hook output priority -160; policy accept;"
  echo "    oif \"lo\" return"
  echo "    counter comment \"all 0 out\""
  awk '{ printf "    meta l4proto %s th sport %s counter comment \"%s %s out\"\n", $1, $2, $1, $2 }' "$pf"
  echo "  }"
  echo "}"
  [ -n "$dev" ] || return 0
  # Docker 等 DNAT 到容器的流量走 forward：按原始目的端口计；所有经主网卡转发的流量计入总量
  echo "#FORWARD"
  echo "table inet $ACCT_TABLE {"
  echo "  chain forward {"
  echo "    type filter hook forward priority -160; policy accept;"
  echo "    iifname \"$dev\" counter comment \"all 0 in\""
  echo "    oifname \"$dev\" counter comment \"all 0 out\""
  awk -v dev="$dev" '{
      printf "    iifname \"%s\" ct status dnat ct protocol %s ct original proto-dst %s counter comment \"%s %s in\"\n", dev, $1, $2, $1, $2
      printf "    oifname \"%s\" ct status dnat ct protocol %s ct original proto-dst %s counter comment \"%s %s out\"\n", dev, $1, $2, $1, $2 }' "$pf"
  echo "  }"
  echo "}"
}

# iptables 计数链（mangle 表，规则不带 -j，只计数；回环用 RETURN 回到调用链，不影响后续规则）。输出：命令参数（不含 iptables 本身）
acct_ipt_rules() {
  local dev="$1" pf="$2"
  echo "-t mangle -A TRICLOUD_ACCT_IN -i lo -j RETURN"
  echo "-t mangle -A TRICLOUD_ACCT_IN -m comment --comment all_0_in"
  echo "-t mangle -A TRICLOUD_ACCT_OUT -o lo -j RETURN"
  echo "-t mangle -A TRICLOUD_ACCT_OUT -m comment --comment all_0_out"
  awk '{ printf "-t mangle -A TRICLOUD_ACCT_IN -p %s --dport %s -m comment --comment %s_%s_in\n", $1, $2, $1, $2
         printf "-t mangle -A TRICLOUD_ACCT_OUT -p %s --sport %s -m comment --comment %s_%s_out\n", $1, $2, $1, $2 }' "$pf"
  [ -n "$dev" ] || return 0
  echo "-t mangle -A TRICLOUD_ACCT_FWD -i $dev -m comment --comment all_0_in"
  echo "-t mangle -A TRICLOUD_ACCT_FWD -o $dev -m comment --comment all_0_out"
  awk -v dev="$dev" '{
      printf "-t mangle -A TRICLOUD_ACCT_FWD -i %s -p %s -m conntrack --ctstate DNAT --ctorigdstport %s -m comment --comment %s_%s_in\n", dev, $1, $2, $1, $2
      printf "-t mangle -A TRICLOUD_ACCT_FWD -o %s -p %s -m conntrack --ctstate DNAT --ctorigdstport %s -m comment --comment %s_%s_out\n", dev, $1, $2, $1, $2 }' "$pf"
}

ipt_bins() {
  command -v iptables >/dev/null 2>&1 && echo iptables
  command -v ip6tables >/dev/null 2>&1 && echo ip6tables
}

acct_present() {
  case "$1" in
    nft) nft list table inet "$ACCT_TABLE" >/dev/null 2>&1 ;;
    iptables) iptables -t mangle -S TRICLOUD_ACCT_IN >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}

# 当前计数：每行「协议 端口 方向 字节」（同一 key 多条规则 / IPv4+IPv6 求和）
acct_read() {
  case "$1" in
    nft)
      nft list table inet "$ACCT_TABLE" 2>/dev/null | awk '
        /counter packets/ && /comment "/ {
          b = ""; for (i = 1; i < NF; i++) if ($i == "bytes") b = $(i + 1)
          match($0, /comment "[^"]+"/); k = substr($0, RSTART + 9, RLENGTH - 10)
          if (b ~ /^[0-9]+$/) s[k] += b
        }
        END { for (k in s) print k, s[k] }' ;;
    iptables)
      local bin c
      for bin in $(ipt_bins); do
        for c in $ACCT_CHAINS; do
          "$bin" -t mangle -nvxL "$c" 2>/dev/null
        done
      done | awk '
        $2 ~ /^[0-9]+$/ && match($0, /\/\* [a-z]+_[0-9]+_(in|out) \*\//) {
          k = substr($0, RSTART + 3, RLENGTH - 6); gsub(/_/, " ", k); s[k] += $2
        }
        END { for (k in s) print k, s[k] }' ;;
  esac
}

acct_remove() {
  local bin c ch
  if command -v nft >/dev/null 2>&1; then
    nft delete table inet "$ACCT_TABLE" >/dev/null 2>&1
  fi
  for bin in $(ipt_bins); do
    for c in INPUT:TRICLOUD_ACCT_IN OUTPUT:TRICLOUD_ACCT_OUT FORWARD:TRICLOUD_ACCT_FWD; do
      ch="${c#*:}"
      while "$bin" -t mangle -D "${c%%:*}" -j "$ch" >/dev/null 2>&1; do :; done
      "$bin" -t mangle -F "$ch" >/dev/null 2>&1
      "$bin" -t mangle -X "$ch" >/dev/null 2>&1
    done
  done
  rm -f "$STATE_DIR/acct_sig" "$STATE_DIR/acct_snap" "$STATE_DIR/acct_ports" "$STATE_DIR/acct_pending"
}

# 读计数 → 与上次快照相减得到增量 → 累加进待上报文件（acct_pending：协议 端口 入 出），更新快照
acct_collect() {
  local be="$1" cur
  acct_present "$be" || return 0
  cur=$(acct_read "$be")
  touch "$STATE_DIR/acct_snap" "$STATE_DIR/acct_pending"
  printf '%s\n' "$cur" | awk -v snapf="$STATE_DIR/acct_snap" -v pendf="$STATE_DIR/acct_pending" '
    BEGIN {
      while ((getline l < snapf) > 0) { n = split(l, a, " "); if (n == 4) snap[a[1] " " a[2] " " a[3]] = a[4] }
      while ((getline l < pendf) > 0) { n = split(l, a, " "); if (n == 4) { pin[a[1] " " a[2]] += a[3]; pout[a[1] " " a[2]] += a[4] } }
    }
    NF == 4 && $4 ~ /^[0-9]+$/ {
      k = $1 " " $2 " " $3; d = $4 - (k in snap ? snap[k] : 0); if (d < 0) d = $4   # 计数被重置
      if ($1 == "all") { all[$3] += d } else { pk = $1 " " $2; if ($3 == "in") { pin[pk] += d; sum["in"] += d } else { pout[pk] += d; sum["out"] += d } }
    }
    END {
      o_in = all["in"] - sum["in"]; o_out = all["out"] - sum["out"]
      if (o_in > 0) pin["other 0"] += o_in
      if (o_out > 0) pout["other 0"] += o_out
      for (k in pin) seen[k] = 1
      for (k in pout) seen[k] = 1
      for (k in seen) if (pin[k] + pout[k] > 0) printf "%s %.0f %.0f\n", k, pin[k], pout[k]
    }' > "$STATE_DIR/acct_pending.new" && mv "$STATE_DIR/acct_pending.new" "$STATE_DIR/acct_pending"
  printf '%s\n' "$cur" | awk 'NF == 4' > "$STATE_DIR/acct_snap"
}

# 上报正文：协议 端口 进程名 入 出
acct_report() {
  [ -s "$STATE_DIR/acct_pending" ] || return 0
  awk -v pf="$STATE_DIR/acct_ports" '
    BEGIN { while ((getline l < pf) > 0) { n = split(l, a, " "); if (n == 3) proc[a[1] " " a[2]] = a[3] } }
    NF == 4 { k = $1 " " $2; print $1, $2, (k in proc ? proc[k] : "-"), $3, $4 }' "$STATE_DIR/acct_pending"
}

# 按当前监听端口建 / 更新计数规则（端口集合或网卡没变就不动，计数不清零）
acct_sync() {
  local be="$1" dev="$2" pf sig
  [ "$be" = none ] && return 1
  pf="$STATE_DIR/acct_ports.new"
  listen_ports > "$pf"
  sig="$be $dev $(awk '{ printf "%s/%s,", $1, $2 }' "$pf")"
  if acct_present "$be" && [ "$(cat "$STATE_DIR/acct_sig" 2>/dev/null)" = "$sig" ]; then
    mv "$pf" "$STATE_DIR/acct_ports"   # 进程名可能变了（同端口换服务），端口没变不重建
    return 0
  fi
  acct_collect "$be"   # 重建前把旧规则的计数收进待上报，避免丢数据
  acct_remove_rules_only "$be"
  local ok=1
  if [ "$be" = nft ]; then
    local rules main fwd
    rules=$(acct_nft_rules "$dev" "$pf")
    main="${rules%%#FORWARD*}"
    if ! printf '%s\n' "$main" | nft -f - 2>"$STATE_DIR/acct_err"; then
      ok=0
    elif [ "$main" != "$rules" ]; then
      fwd="${rules#*#FORWARD}"
      printf '%s\n' "$fwd" | nft -f - 2>/dev/null || log "forward 计数链创建失败（Docker 转发流量将计入其他）"
    fi
  else
    local bin c line
    for bin in $(ipt_bins); do
      for c in $ACCT_CHAINS; do "$bin" -t mangle -N "$c" >/dev/null 2>&1; done
      "$bin" -t mangle -I INPUT 1 -j TRICLOUD_ACCT_IN 2>"$STATE_DIR/acct_err" || ok=0
      "$bin" -t mangle -I OUTPUT 1 -j TRICLOUD_ACCT_OUT 2>>"$STATE_DIR/acct_err" || ok=0
      "$bin" -t mangle -I FORWARD 1 -j TRICLOUD_ACCT_FWD >/dev/null 2>&1
      # shellcheck disable=SC2086
      while IFS= read -r line; do
        case "$bin $line" in
          ip6tables*"--ctorigdstport"*) "$bin" $line >/dev/null 2>&1 ;;   # 少数内核 IPv6 conntrack 不全，失败忽略
          *) "$bin" $line >/dev/null 2>&1 || case "$line" in *TRICLOUD_ACCT_FWD*) ;; *) ok=0 ;; esac ;;
        esac
      done < <(acct_ipt_rules "$dev" "$pf")
    done
  fi
  if [ "$ok" = 1 ]; then
    mv "$pf" "$STATE_DIR/acct_ports"
    echo "$sig" > "$STATE_DIR/acct_sig"
    rm -f "$STATE_DIR/acct_snap" "$STATE_DIR/acct_err"
    log "流量明细计数规则已更新（$be，$(wc -l < "$STATE_DIR/acct_ports") 个端口）"
    return 0
  fi
  log "流量明细计数规则创建失败（$be）：$(head -c 200 "$STATE_DIR/acct_err" 2>/dev/null)"
  acct_remove_rules_only "$be"
  rm -f "$pf" "$STATE_DIR/acct_sig"
  return 1
}

# 只删规则（保留待上报的增量）
acct_remove_rules_only() {
  local keep=""
  [ -s "$STATE_DIR/acct_pending" ] && keep=$(cat "$STATE_DIR/acct_pending")
  local ports=""
  [ -s "$STATE_DIR/acct_ports" ] && ports=$(cat "$STATE_DIR/acct_ports")
  acct_remove
  [ -n "$keep" ] && printf '%s\n' "$keep" > "$STATE_DIR/acct_pending"
  [ -n "$ports" ] && printf '%s\n' "$ports" > "$STATE_DIR/acct_ports"
  return 0
}

# 解析面板返回的 format=env：throttle=0|1、rate_kbit=整数、acct=0|1、interval=秒
parse_state() {
  THROTTLE=""
  RATE_KBIT=""
  ACCT_WANT=0
  local k v
  while IFS='=' read -r k v; do
    v="${v%$'\r'}"
    case "$k" in
      throttle) [[ "$v" =~ ^[01]$ ]] && THROTTLE="$v" ;;
      rate_kbit) [[ "$v" =~ ^[0-9]{1,8}$ ]] && RATE_KBIT="$v" ;;
      acct) [[ "$v" =~ ^[01]$ ]] && ACCT_WANT="$v" ;;
    esac
  done <<< "$1"
  [ -n "$THROTTLE" ] && { [ "$THROTTLE" = 0 ] || [ -n "$RATE_KBIT" ]; }
}

cmd_run() {
  need_root run
  mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR"
  load_conf
  if [ -z "$PANEL" ] || [ -z "$TOKEN" ]; then
    log "配置缺失（$CONF），请重新运行安装命令"
    exit 1
  fi
  local dev ports applied=0 body code now last be acct_state="off" nports=0
  dev=$(detect_iface)
  ports=$(detect_ssh_ports)
  is_ours "${dev:-none}" && applied=1
  be=$(acct_backend)
  if acct_present "$be"; then
    acct_collect "$be"
    acct_state="$be"
    nports=$(wc -l < "$STATE_DIR/acct_ports" 2>/dev/null || echo 0)
  elif [ "$be" = none ]; then
    acct_state="none"
  fi
  acct_report > "$STATE_DIR/report"
  now=$(date +%s)
  body=$(curl -sS -m 30 -w '\n%{http_code}' -X POST -H "X-TriCloud-Guard-Token: $TOKEN" -H 'Content-Type: text/plain' \
    --data-binary @"$STATE_DIR/report" \
    "$PANEL/api/guard-agent/state?format=env&v=$VERSION&applied=$applied&iface=${dev:-unknown}&ssh=${ports// /,}&acct=$acct_state&nports=${nports// /}" 2>/dev/null)
  code="${body##*$'\n'}"
  body="${body%$'\n'*}"
  if [ "$code" = 401 ] || [ "$code" = 404 ]; then
    log "token 无效（守护已删除或 token 已重置），解除限速并删除计数规则"
    clear_limit "$dev"
    acct_remove
    exit 0
  fi
  if [ "$code" != 200 ] || ! parse_state "$body"; then
    last=$(cat "$STATE_DIR/last_ok" 2>/dev/null || echo "$now")
    [[ "$last" =~ ^[0-9]+$ ]] || last="$now"
    [ -f "$STATE_DIR/last_ok" ] || echo "$now" > "$STATE_DIR/last_ok"
    if [ $((now - last)) -ge "$FAIL_OPEN_SECS" ]; then
      log "连续 24 小时连不上面板（HTTP ${code:-无响应}），解除限速"
      clear_limit "$dev"
    else
      log "连不上面板（HTTP ${code:-无响应}），保持当前状态，流量明细下次补报"
    fi
    exit 0
  fi
  echo "$now" > "$STATE_DIR/last_ok"
  rm -f "$STATE_DIR/acct_pending" "$STATE_DIR/report"   # 已上报
  if [ "$ACCT_WANT" = 1 ]; then
    acct_sync "$be" "$dev" || true
  elif acct_present "$be" || [ -f "$STATE_DIR/acct_sig" ]; then
    acct_remove
    log "面板已关闭流量明细，计数规则已删除"
  fi
  if [ -z "$dev" ]; then
    log "找不到主网卡（可在 $CONF 写 IFACE=网卡名）"
    exit 1
  fi
  if [ "$THROTTLE" = 1 ]; then
    [ "$RATE_KBIT" -lt 8 ] && RATE_KBIT=8
    apply_limit "$dev" "$RATE_KBIT" "$ports"
  else
    clear_limit "$dev"
  fi
}

cmd_status() {
  load_conf
  local dev be
  dev=$(detect_iface)
  be=$(acct_backend)
  echo "面板：${PANEL:-未配置}"
  echo "网卡：${dev:-未知}  SSH 端口：$(detect_ssh_ports)"
  if is_ours "${dev:-none}"; then
    echo "限速：限速中（$(cat "$STATE_DIR/applied" 2>/dev/null)）"
    tc -s class show dev "$dev" 2>/dev/null
  else
    echo "限速：未限速"
  fi
  if acct_present "$be"; then
    echo "流量明细：已开启（$be，$(wc -l < "$STATE_DIR/acct_ports" 2>/dev/null || echo 0) 个端口），当前计数："
    acct_read "$be" | sort -k4,4nr | head -20
  else
    echo "流量明细：未开启（计数后端：$be）"
  fi
  systemctl list-timers tricloud-guard.timer --no-pager 2>/dev/null | head -3
}

cmd_uninstall() {
  need_root uninstall
  load_conf
  clear_limit "$(detect_iface)"
  acct_remove
  systemctl disable --now tricloud-guard.timer >/dev/null 2>&1
  systemctl stop tricloud-guard.service >/dev/null 2>&1
  rm -f /etc/systemd/system/tricloud-guard.timer /etc/systemd/system/tricloud-guard.service
  systemctl daemon-reload >/dev/null 2>&1
  rm -rf /etc/tricloud-guard "$STATE_DIR"
  rm -f /usr/local/bin/tricloud-guard
  echo "已卸载 TriCloud 流量守护 agent，限速规则与流量计数规则已清除"
}

case "${1:-run}" in
  run) cmd_run ;;
  status) cmd_status ;;
  clear) need_root clear; load_conf; clear_limit "$(detect_iface)" ;;
  uninstall) cmd_uninstall ;;
  commands) shift; tc_commands "$@" ;;   # 测试 / 排查用：只打印将执行的 tc 命令
  acct-rules) # 测试 / 排查用：只打印将创建的计数规则。参数：nft|iptables 网卡
    pf=$(mktemp); listen_ports > "$pf"
    if [ "${2:-nft}" = iptables ]; then acct_ipt_rules "${3:-}" "$pf"; else acct_nft_rules "${3:-}" "$pf"; fi
    rm -f "$pf" ;;
  ports) listen_ports ;;
  version) echo "$VERSION" ;;
  *) echo "用法：tricloud-guard run|status|clear|uninstall" >&2; exit 2 ;;
esac
