#!/usr/bin/env bash
# TriCloud 一键安装 / 升级脚本（Debian / Ubuntu / CentOS / Rocky / Alma 等，需 root）
#
#   bash install.sh                 # 安装或升级
#   PORT=8080 bash install.sh       # 指定端口（默认 8000）
#   BIND=127.0.0.1 bash install.sh  # 只监听本机（配合 Nginx / Caddy / Cloudflare Tunnel）
#   GH_TOKEN=xxx bash install.sh    # 仓库为私有时，用有读权限的 GitHub Token 下载代码
#
# 可选环境变量：DIR（安装目录，默认 /opt/docker/tricloud）、REPO（默认 astemo6/tricloud）、
# BRANCH（默认 master）、PANEL_PASSWORD（首次安装的面板密码，留空则随机生成）、
# CN=1（国内机器：Docker 用阿里云镜像源安装）。
# 再次运行即升级：保留 .env 与 data/，只更新代码并重建容器。
set -euo pipefail

REPO="${REPO:-astemo6/tricloud}"
BRANCH="${BRANCH:-master}"
DIR="${DIR:-/opt/docker/tricloud}"
# 升级时沿用上次安装的端口和监听地址（命令行指定的优先）
if [ -f "$DIR/.install.conf" ]; then
  _p="${PORT:-}"; _b="${BIND:-}"
  . "$DIR/.install.conf"
  PORT="${_p:-$PORT}"; BIND="${_b:-$BIND}"
fi
PORT="${PORT:-8000}"
BIND="${BIND:-0.0.0.0}"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请用 root 运行（sudo -i 后再执行）"
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "PORT 不合法：$PORT"

# ---------- 基础工具 ----------
need_pkgs=()
for c in curl tar openssl; do command -v "$c" >/dev/null 2>&1 || need_pkgs+=("$c"); done
if [ ${#need_pkgs[@]} -gt 0 ]; then
  say "安装依赖：${need_pkgs[*]}"
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${need_pkgs[@]}" ca-certificates
  elif command -v dnf >/dev/null 2>&1; then dnf install -y -q "${need_pkgs[@]}" ca-certificates
  elif command -v yum >/dev/null 2>&1; then yum install -y -q "${need_pkgs[@]}" ca-certificates
  elif command -v apk >/dev/null 2>&1; then apk add --no-cache "${need_pkgs[@]}" ca-certificates bash
  else die "无法自动安装 ${need_pkgs[*]}，请手动安装后重试"; fi
fi

# ---------- Docker ----------
if ! command -v docker >/dev/null 2>&1; then
  say "安装 Docker"
  if [ "${CN:-0}" = "1" ]; then
    curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun
  else
    curl -fsSL https://get.docker.com | sh
  fi
fi
command -v systemctl >/dev/null 2>&1 && systemctl enable --now docker >/dev/null 2>&1 || true
docker info >/dev/null 2>&1 || die "Docker 未能启动，请检查 systemctl status docker"
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
else
  say "安装 docker compose 插件"
  if command -v apt-get >/dev/null 2>&1; then apt-get install -y -qq docker-compose-plugin
  elif command -v dnf >/dev/null 2>&1; then dnf install -y -q docker-compose-plugin
  elif command -v yum >/dev/null 2>&1; then yum install -y -q docker-compose-plugin
  fi
  docker compose version >/dev/null 2>&1 || die "docker compose 安装失败"
  DC="docker compose"
fi

# ---------- 下载代码 ----------
say "下载 TriCloud（$REPO@$BRANCH）"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
auth=()
[ -n "${GH_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $GH_TOKEN")
if ! curl -fsSL ${auth[@]+"${auth[@]}"} -o "$tmp/src.tgz" "https://api.github.com/repos/$REPO/tarball/$BRANCH"; then
  die "下载失败。仓库若为私有，请设置 GH_TOKEN（需要该仓库 Contents 读权限）"
fi
mkdir -p "$tmp/src" && tar -xzf "$tmp/src.tgz" -C "$tmp/src" --strip-components=1
[ -f "$tmp/src/Dockerfile" ] && [ -d "$tmp/src/app" ] || die "下载内容不完整"

mkdir -p "$DIR/data"
fresh=0; [ -f "$DIR/.env" ] || fresh=1
if [ "$fresh" = 0 ] && [ -d "$DIR/app" ]; then
  bk="$DIR/../backup-tricloud-$(date +%Y%m%d-%H%M%S).tgz"
  say "备份现有安装到 $bk"
  tar -czf "$bk" -C "$DIR" . || warn "备份失败，继续"
fi
# 只替换代码，保留 .env / data
for d in app web; do rm -rf "${DIR:?}/$d"; done
for f in Dockerfile entrypoint.sh requirements.txt docker-compose.yml .env.example .dockerignore install.sh README.md LICENSE; do
  [ -e "$tmp/src/$f" ] && cp -f "$tmp/src/$f" "$DIR/$f"
done
cp -r "$tmp/src/app" "$tmp/src/web" "$DIR/"
chmod +x "$DIR/install.sh" "$DIR/entrypoint.sh" 2>/dev/null || true

# ---------- .env ----------
cd "$DIR"
if [ "$fresh" = 1 ]; then
  cp .env.example .env
  pw="${PANEL_PASSWORD:-$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)}"
  sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=$pw|" .env
  chmod 600 .env
fi

# 端口映射（每次运行按 BIND/PORT 重写，并记在 .install.conf，升级时沿用）
sed -i -E "s|^([[:space:]]*)- \"[0-9.]*:?[0-9]+:8000\"|\1- \"$BIND:$PORT:8000\"|" docker-compose.yml
grep -qF "\"$BIND:$PORT:8000\"" docker-compose.yml || die "写入端口映射失败"
printf 'BIND=%s\nPORT=%s\n' "$BIND" "$PORT" > .install.conf

# ---------- 构建并启动 ----------
say "构建并启动容器（首次约 1-3 分钟）"
$DC up -d --build
say "等待服务就绪"
ok=0
for _ in $(seq 1 30); do
  if curl -fs "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[ "$ok" = 1 ] || { $DC logs --tail 50; die "服务未就绪，日志见上"; }

ip="$(curl -fs4 --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
echo
say "TriCloud 已运行"
if [ "$BIND" = "127.0.0.1" ]; then
  echo "    本机地址：http://127.0.0.1:$PORT （请配置反代后访问）"
else
  echo "    访问地址：http://$ip:$PORT"
fi
if [ "$fresh" = 1 ]; then
  echo "    初始密码：$(grep '^PANEL_PASSWORD=' .env | cut -d= -f2-)  （登录后请在设置里修改并开启 2FA）"
fi
echo "    安装目录：$DIR （data/ 里的 tricloud.db 和 fernet.key 必须一起备份）"
echo "    升级：再次运行本脚本；查看日志：cd $DIR && $DC logs -f"
if [ "$BIND" != "127.0.0.1" ]; then
  warn "面板直接暴露在公网。建议用 HTTPS 反代（Caddy/Nginx/Cloudflare Tunnel），并在 .env 设 COOKIE_SECURE=true、TRUST_PROXY=true；防火墙或安全组也要放行 $PORT 端口。"
fi
